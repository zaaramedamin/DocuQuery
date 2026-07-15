"""
Core RAG services: embedding, similarity, and text chunking.

These are pure-logic functions with no knowledge of FastAPI or HTTP.
"""

import numpy as np
from backend.config import hf_client, EMBEDDING_MODEL


def get_embedding(text: str) -> np.ndarray:
    """Generate a dense vector embedding for the given text."""
    if not hf_client:
        raise RuntimeError("Hugging Face client is not initialized (HF_TOKEN missing).")
    result = hf_client.feature_extraction(text, model=EMBEDDING_MODEL)
    return np.array(result).flatten()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return the cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def chunk_text(text: str, page_num: int, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    """Split *text* into overlapping word-level chunks tagged with *page_num*."""
    words = text.split()
    chunks: list[dict] = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append({"chunk": chunk, "page": page_num})
        i += chunk_size - overlap
    return chunks
