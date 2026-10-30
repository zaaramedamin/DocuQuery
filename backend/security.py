"""
Authentication: resolve the Supabase user behind a request's Bearer token.

The frontend signs users in through /api/auth/* and then sends the access
token on every request. Tokens are verified against Supabase Auth; positive
results are cached briefly so a burst of requests costs one round-trip.
"""

import re
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

import config
from services.rate_limit import check_rate_limit

TOKEN_CACHE_TTL_SECONDS = 60
_TOKEN_CACHE_MAX = 2000

_cache_lock = threading.Lock()
_token_cache: dict[str, tuple[float, "AuthUser"]] = {}

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None


def clear_token_cache() -> None:
    with _cache_lock:
        _token_cache.clear()


def _cache_get(token: str) -> "AuthUser | None":
    with _cache_lock:
        entry = _token_cache.get(token)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        _token_cache.pop(token, None)
        return None


def _cache_put(token: str, user: "AuthUser") -> None:
    with _cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            now = time.monotonic()
            for key in [k for k, (exp, _) in _token_cache.items() if exp <= now]:
                del _token_cache[key]
            if len(_token_cache) >= _TOKEN_CACHE_MAX:
                _token_cache.clear()
        _token_cache[token] = (time.monotonic() + TOKEN_CACHE_TTL_SECONDS, user)


def verify_token(token: str) -> AuthUser:
    """Validate *token* with Supabase Auth and return its user, or raise 401/503."""
    cached = _cache_get(token)
    if cached:
        return cached

    client = config.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Authentication service is not configured.")

    try:
        response = client.auth.get_user(token)
    except Exception as exc:
        # Supabase answers invalid/expired tokens with an auth error; network
        # problems surface as other exception types. Treat both as a failed
        # check, but tell the client which kind it was.
        if exc.__class__.__name__.startswith("AuthApi") or "jwt" in str(exc).lower():
            raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
        raise HTTPException(status_code=503, detail="Could not verify your session. Please try again.")

    supa_user = getattr(response, "user", None)
    user_id = str(getattr(supa_user, "id", "") or "")
    if not user_id or not _UUID_RE.match(user_id):
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")

    user = AuthUser(id=user_id, email=getattr(supa_user, "email", None))
    _cache_put(token, user)
    return user


def get_current_user(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency: require a valid `Authorization: Bearer <token>` header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return verify_token(token)


def limited_user(bucket: str, limit: tuple[int, int]):
    """
    Build a dependency that authenticates the caller AND applies a per-user
    rate limit named *bucket* — ``limit`` is ``(max_requests, window_seconds)``.
    """

    def dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        check_rate_limit(f"{bucket}:{user.id}", limit[0], limit[1])
        return user

    return dependency


def is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True
