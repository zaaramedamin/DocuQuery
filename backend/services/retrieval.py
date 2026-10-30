"""
Retrieval pipeline: reformulate → embed → hybrid search (vector + keyword)
→ optional LLM rerank. Also builds per-document context for compare mode.
"""

import re
import sys

from config import (
    gemini_client,
    RETRIEVAL_CANDIDATES,
    RETRIEVAL_TOP_K,
    RERANK_ENABLED,
    COMPARE_CHUNKS_PER_DOC,
    MAX_COMPARE_DOCS,
)
from services import db_service, llm
from services.rag_service import get_embedding

# Words that carry no search signal. Keeping them out of the keyword query
# stops "what is the ..." questions from matching every chunk.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from had has have how i if in into is it its
    me my of on or our please should so than that the their them then there these they this those to us was we
    were what when where which who whom why will with would you your about tell give show explain
    """.split()
)
_MAX_KEYWORDS = 12
_RERANK_SNIPPET_CHARS = 700


def build_tsquery(text: str) -> str:
    """
    Turn a natural-language question into an OR-joined ``to_tsquery`` string
    (e.g. ``refund | policy | days``). Only plain word characters are kept,
    so the result can never be a malformed tsquery. Returns '' when nothing
    meaningful is left (the search then runs on vectors alone).
    """
    seen: dict[str, None] = {}
    for token in re.findall(r"[^\W_]+", (text or "").lower()):
        if len(token) < 2 or token in _STOPWORDS:
            continue
        seen.setdefault(token)
        if len(seen) >= _MAX_KEYWORDS:
            break
    return " | ".join(seen)


def reformulate_query(question: str, history: list[dict]) -> str:
    """
    Use a quick LLM call to rewrite a vague follow-up question into
    a self-contained, search-optimized query using conversation history.
    """
    if not history or not gemini_client:
        return question

    recent = history[-6:]  # last 3 exchanges
    history_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'AI'}: {m['content']}" for m in recent
    )
    prompt = (
        "Given the conversation history and the latest user question, "
        "rewrite the question as a standalone, search-optimized query. "
        "Only output the rewritten query, nothing else.\n\n"
        f"History:\n{history_text}\n\n"
        f"Latest question: {question}\n\n"
        "Rewritten query:"
    )
    try:
        # The budget covers thinking tokens too; the rewritten query itself is short.
        rewritten = llm.generate_text(prompt, max_output_tokens=1024)
        return rewritten or question
    except Exception:
        return question


def rerank(question: str, chunks: list[dict], top_k: int) -> list[dict]:
    """
    Reorder *chunks* by how well each answers *question*, using one LLM call
    that scores every passage 0-10, and keep the best *top_k*. Any failure
    falls back to the hybrid-search order, so reranking can never break a query.
    """
    if len(chunks) <= 1:
        return chunks[:top_k]
    if not RERANK_ENABLED or not gemini_client or len(chunks) <= top_k:
        return chunks[:top_k]

    passages = "\n\n".join(
        f"[{i}] {c['text'][:_RERANK_SNIPPET_CHARS]}" for i, c in enumerate(chunks)
    )
    prompt = (
        "You are a search relevance judge. Score how useful each passage is for answering "
        "the question: 0 = irrelevant, 10 = directly answers it.\n\n"
        f"Question: {question}\n\nPassages:\n{passages}\n\n"
        f"Return ONLY a JSON array of exactly {len(chunks)} integers (one score per passage, in order)."
    )
    try:
        scores = llm.generate_json(prompt, max_output_tokens=1024)
        if isinstance(scores, dict):  # tolerate {"scores": [...]}
            scores = next((v for v in scores.values() if isinstance(v, list)), None)
        if not isinstance(scores, list) or len(scores) != len(chunks):
            return chunks[:top_k]
        numeric = [float(s) for s in scores]
    except Exception as exc:
        print(f"Warning: rerank skipped ({exc})", file=sys.stderr)
        return chunks[:top_k]

    order = sorted(range(len(chunks)), key=lambda i: (-numeric[i], i))
    relevant = [i for i in order if numeric[i] >= 1]
    chosen = relevant[:top_k] if len(relevant) >= 2 else order[:top_k]
    return [chunks[i] for i in chosen]


def retrieve(
    user_id: str,
    question: str,
    history: list[dict],
    filenames: list[str],
    within: list[str] | None = None,
) -> list[dict]:
    """
    Find the chunks that should ground the answer.

    * 0 or 1 document selected → hybrid search (+ rerank) over that scope.
    * 2+ documents selected    → compare mode: take the best chunks from EACH
      document so every one is represented in the answer.
    * ``within`` (a tag / folder) → ordinary search, but only inside that set
      of documents.
    """
    search_query = reformulate_query(question, history)
    embedding = get_embedding(search_query).tolist()
    tsquery = build_tsquery(search_query)

    if len(filenames) >= 2:
        chunks: list[dict] = []
        for name in filenames[:MAX_COMPARE_DOCS]:
            chunks.extend(
                db_service.hybrid_search(user_id, embedding, tsquery, COMPARE_CHUNKS_PER_DOC, name)
            )
        return chunks

    scope = filenames[0] if filenames else None
    candidates = db_service.hybrid_search(
        user_id, embedding, tsquery, RETRIEVAL_CANDIDATES, scope, filenames=None if scope else within
    )
    return rerank(question, candidates, RETRIEVAL_TOP_K)
