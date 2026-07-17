"""
Core RAG services: embedding, similarity, and text chunking.

These are pure-logic functions with no knowledge of FastAPI or HTTP.
"""

import numpy as np
from backend.config import hf_client, EMBEDDING_MODEL

# all-MiniLM-L6-v2 truncates input at 256 word-piece tokens (~180 words).
# Chunks larger than that are silently cut off by the embedding model,
# making their tail invisible to semantic search.
DEFAULT_CHUNK_WORDS = 180
DEFAULT_OVERLAP_WORDS = 30

# Number of texts sent to the HF feature-extraction endpoint per request.
EMBEDDING_BATCH_SIZE = 32


def get_embedding(text: str) -> np.ndarray:
    """Generate a dense vector embedding for the given text."""
    if not hf_client:
        raise RuntimeError("Hugging Face client is not initialized (HF_TOKEN missing).")
    result = hf_client.feature_extraction(text, model=EMBEDDING_MODEL)
    return np.array(result).flatten()


def get_embeddings(texts: list[str]) -> list[np.ndarray]:
    """
    Generate embeddings for many texts, batching API calls instead of
    issuing one HTTP round-trip per chunk. Falls back to per-text calls
    if the endpoint rejects a batched payload.
    """
    if not hf_client:
        raise RuntimeError("Hugging Face client is not initialized (HF_TOKEN missing).")

    embeddings: list[np.ndarray] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        try:
            result = np.array(hf_client.feature_extraction(batch, model=EMBEDDING_MODEL))
            if result.ndim == 1:  # single flat vector returned
                result = result.reshape(1, -1)
            if result.shape[0] != len(batch):
                raise ValueError("Batch embedding count mismatch")
            embeddings.extend(result[i] for i in range(result.shape[0]))
        except Exception:
            # Fallback: embed one at a time
            embeddings.extend(get_embedding(t) for t in batch)
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
