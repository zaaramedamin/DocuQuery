"""
Account routes: sign up, sign in, refresh a session, who am I.

The browser never talks to Supabase Auth directly — these endpoints do it
through the backend, so the frontend needs no extra Supabase configuration.
"""

import re
import sys
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import config
from config import ALLOWED_ORIGINS, FRONTEND_URL, RATE_LIMIT_AUTH, RATE_LIMIT_RESET
from security import AuthUser, get_current_user, verify_token
from services.rate_limit import check_rate_limit, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


def _auth_client(implicit_flow: bool = False):
    """
    A throwaway Supabase client for one auth call. The shared client must
    never sign a user in: it would keep that user's session and then act as
    them on every later request.

    ``implicit_flow`` makes emailed links carry the session in the URL, which
    is what a server-side request needs (PKCE would require a browser to hold
    the verifier).
    """
    if not (config.SUPABASE_URL and config.SUPABASE_KEY):
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server.")
    from supabase import ClientOptions, create_client

    options = ClientOptions(flow_type="implicit") if implicit_flow else None
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY, options)


def _session_payload(session, user) -> dict:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": getattr(session, "expires_at", None),
        "user": {"id": str(user.id), "email": user.email},
    }


def _check(request: Request) -> None:
    check_rate_limit(f"auth:{client_ip(request)}", RATE_LIMIT_AUTH[0], RATE_LIMIT_AUTH[1])


def _validated(body: Credentials) -> tuple[str, str]:
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    return email, body.password


def _auth_error(exc: Exception, fallback: str, status: int = 400) -> HTTPException:
    message = str(getattr(exc, "message", "") or exc)
    lowered = message.lower()
    if "invalid login" in lowered or "invalid credentials" in lowered:
        return HTTPException(status_code=401, detail="Incorrect email or password.")
    if "not confirmed" in lowered:
        return HTTPException(status_code=403, detail="Please confirm your email address first — check your inbox.")
    if "already" in lowered and "registered" in lowered:
        return HTTPException(status_code=409, detail="An account with this email already exists. Try signing in.")
    if "password" in lowered:
        return HTTPException(status_code=400, detail=message)
    if "rate limit" in lowered or "too many" in lowered:
        return HTTPException(status_code=429, detail="Too many attempts. Please wait a bit and try again.")
    return HTTPException(status_code=status, detail=fallback)


@router.post("/signup")
def sign_up(body: Credentials, request: Request):
    _check(request)
    email, password = _validated(body)
    try:
        result = _auth_client().auth.sign_up({"email": email, "password": password})
    except HTTPException:
        raise
    except Exception as exc:
        raise _auth_error(exc, "Could not create the account. Please try again.")

    if result.session and result.user:
        return _session_payload(result.session, result.user)
    # Email confirmation is enabled in Supabase: no session until the link is clicked.
    return {"needs_confirmation": True, "email": email}


@router.post("/login")
def log_in(body: Credentials, request: Request):
    _check(request)
    email, password = _validated(body)
    try:
        result = _auth_client().auth.sign_in_with_password({"email": email, "password": password})
    except HTTPException:
        raise
    except Exception as exc:
        raise _auth_error(exc, "Could not sign in. Please try again.", status=401)

    if not (result.session and result.user):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return _session_payload(result.session, result.user)


@router.post("/refresh")
def refresh(body: RefreshBody, request: Request):
    _check(request)
    try:
        result = _auth_client().auth.refresh_session(body.refresh_token)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")

    if not (result.session and result.user):
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return _session_payload(result.session, result.user)


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}


# ── Forgot / reset password ──────────────────────────────────────────

class ForgotBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # Where the emailed link should land (the site the user is on).
    redirect_to: str | None = Field(default=None, max_length=300)


class ResetBody(BaseModel):
    access_token: str = Field(min_length=10, max_length=4096)
    password: str = Field(min_length=8, max_length=128)


def safe_redirect(redirect_to: str | None) -> str | None:
    """
    Accept the requested landing page only if it is a site we own. Otherwise a
    stranger could request a reset email whose link sends the victim's token
    to a site they control.
    """
    if not redirect_to:
        return None
    parts = urlsplit(redirect_to)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    allowed = {o.rstrip("/") for o in ALLOWED_ORIGINS if o != "*"}
    if FRONTEND_URL:
        allowed.add(FRONTEND_URL)
    if origin in allowed or parts.hostname in ("localhost", "127.0.0.1"):
        return origin + "/"
    return None


@router.post("/forgot-password")
def forgot_password(body: ForgotBody, request: Request):
    """
    Email a reset link. The answer is always the same, whether or not the
    address has an account, so this can't be used to find out who is registered.
    """
    _check(request)
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    check_rate_limit(f"reset-email:{email}", RATE_LIMIT_RESET[0], RATE_LIMIT_RESET[1])
    check_rate_limit(f"reset-ip:{client_ip(request)}", RATE_LIMIT_RESET[0] * 4, RATE_LIMIT_RESET[1])

    options = {}
    redirect = safe_redirect(body.redirect_to)
    if redirect:
        options["redirect_to"] = redirect
    try:
        _auth_client(implicit_flow=True).auth.reset_password_for_email(email, options)
    except HTTPException:
        raise
    except Exception as exc:
        # Don't tell the caller (it would reveal whether the account exists), but do log it:
        # an unconfigured email provider is the usual cause.
        print(f"Warning: password reset email failed: {exc}", file=sys.stderr)
    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(body: ResetBody, request: Request):
    """Set a new password using the token from the emailed reset link."""
    _check(request)
    user = verify_token(body.access_token)
    client = config.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server.")
    try:
        client.auth.admin.update_user_by_id(user.id, {"password": body.password})
    except Exception as exc:
        raise _auth_error(exc, "Could not update the password. Please try again.")
    return {"status": "success"}
