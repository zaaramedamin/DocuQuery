"""
In-memory sliding-window rate limiter.

State lives in the current process, which is right for a single-worker
deployment (Render free tier, docker compose). With several workers each
one enforces its own window, so the effective limit is looser.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_MAX_KEYS = 20_000  # safety valve against unbounded growth


def check_rate_limit(key: str, limit: int, window_seconds: int, *, now: float | None = None) -> None:
    """
    Record one hit for *key*; raise HTTP 429 when more than *limit* hits
    happened in the last *window_seconds*.
    """
    if limit <= 0:
        return  # a non-positive limit disables the check
    current = time.monotonic() if now is None else now
    cutoff = current - window_seconds

    with _lock:
        if len(_hits) > _MAX_KEYS:
            _prune(cutoff)
        bucket = _hits[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(bucket[0] + window_seconds - current) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please wait {retry_after}s and try again.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(current)


def _prune(cutoff: float) -> None:
    for key in [k for k, b in _hits.items() if not b or b[-1] <= cutoff]:
        del _hits[key]


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
