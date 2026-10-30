"""
Generate a short summary and a few starter questions for a freshly
indexed document. Always best-effort: failure just means no summary.
"""

import sys

from config import gemini_client
from services import llm

_MAX_WORDS_SAMPLED = 6000
_MAX_QUESTIONS = 4


def _sample_text(pages: list[str]) -> str:
    """First ~6,000 words of the document (enough to capture its subject)."""
    words: list[str] = []
    for page in pages:
        words.extend(page.split())
        if len(words) >= _MAX_WORDS_SAMPLED:
            break
    return " ".join(words[:_MAX_WORDS_SAMPLED])


def summarize_document(filename: str, pages: list[str]) -> dict | None:
    """
    Return ``{"summary": str, "questions": [str, ...]}`` or None when the
    model is unavailable or returns something unusable.
    """
    if not gemini_client or not pages:
        return None
    sample = _sample_text(pages)
    if not sample.strip():
        return None

    prompt = (
        "You are helping a user explore a document they just uploaded.\n"
        "Read the excerpt and respond with JSON of the form:\n"
        '{"summary": "<3-4 sentence summary of what the document is about>", '
        '"questions": ["<question 1>", "<question 2>", "<question 3>", "<question 4>"]}\n'
        "Rules: the questions must be specific, answerable from the document, and under 100 characters. "
        "Write in the same language as the document.\n\n"
        f"Document name: {filename}\n\nExcerpt:\n{sample}"
    )
    try:
        data = llm.generate_json(prompt, max_output_tokens=1500)
    except Exception as exc:
        print(f"Warning: summary generation failed: {exc}", file=sys.stderr)
        return None
    return normalize_summary(data)


def normalize_summary(data) -> dict | None:
    """Validate the model's JSON and coerce it into the stored shape."""
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    raw_questions = data.get("questions")
    questions = [
        q.strip()
        for q in (raw_questions if isinstance(raw_questions, list) else [])
        if isinstance(q, str) and q.strip()
    ][:_MAX_QUESTIONS]
    return {"summary": summary.strip(), "questions": questions}
