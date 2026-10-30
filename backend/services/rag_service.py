"""
Core RAG services: embedding, similarity, and text chunking.

These are pure-logic functions with no knowledge of FastAPI or HTTP.
"""

import numpy as np
from google.genai import types
from config import gemini_client, EMBEDDING_MODEL, EMBEDDING_DIM

# Chunk size controls retrieval granularity: small chunks give precise
# citations. gemini-embedding-2 accepts up to 8,192 tokens per input, so
# this can be raised if answers need more surrounding context.
DEFAULT_CHUNK_WORDS = 180
DEFAULT_OVERLAP_WORDS = 30

# Number of chunks sent to the Gemini embedding endpoint per request.
EMBEDDING_BATCH_SIZE = 32


def _embed(texts: list[str]) -> list[np.ndarray]:
    """Embed each text separately, using a single API call."""
    if not gemini_client:
        raise RuntimeError("Gemini client is not initialized (GEMINI_API_KEY missing).")

    # gemini-embedding-2 merges a plain list of strings into ONE vector.
    # Wrapping each text in its own Content returns one vector per text.
    contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
    result = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=contents,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
    )
    vectors = [np.array(e.values, dtype=np.float32) for e in (result.embeddings or [])]
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: sent {len(texts)} texts, got {len(vectors)} vectors."
        )
    return vectors


def get_embedding(query: str) -> np.ndarray:
    """Embed a search query (uses Gemini's query-side retrieval prefix)."""
    return _embed([f"task: search result | query: {query}"])[0]


def get_embeddings(texts: list[str]) -> list[np.ndarray]:
    """
    Embed document chunks (uses Gemini's document-side retrieval prefix),
    batching API calls instead of issuing one round-trip per chunk.
    """
    embeddings: list[np.ndarray] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        embeddings.extend(_embed([f"title: none | text: {t}" for t in batch]))
    return embeddings


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return the cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def chunk_text(
    text: str,
    page_num: int,
    chunk_size: int = DEFAULT_CHUNK_WORDS,
    overlap: int = DEFAULT_OVERLAP_WORDS,
) -> list[dict]:
    """Split *text* into overlapping word-level chunks tagged with *page_num*."""
    words = text.split()
    step = max(1, chunk_size - overlap)
    chunks: list[dict] = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append({"chunk": chunk, "page": page_num})
        i += step
    return chunks
