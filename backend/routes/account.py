"""
Account: usage and plan, profile, preferences, password, data export and deletion.
"""

import json
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import config
import security
from config import PRO_PRICE_CENTS
from routes.auth import _auth_client, _auth_error
from security import AuthUser, get_current_user
from services import db_service, file_store, plans, user_settings
from services.rate_limit import check_rate_limit

router = APIRouter(prefix="/api", tags=["account"])


def _start_of_today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _limits_out(limits: plans.PlanLimits) -> dict:
    return {
        "max_upload_bytes": limits.max_upload_bytes,
        "documents": limits.max_documents,
        "storage_bytes": limits.max_storage_bytes,
        "daily_questions": limits.daily_questions,
        "ocr_pages": limits.max_ocr_pages,
    }


@router.get("/usage")
def get_usage(user: AuthUser = Depends(get_current_user)):
    limits = plans.plan_for_user(user.id)
    rows = db_service.list_documents(user.id)
    return {
        "plan": limits.plan,
        "max_upload_bytes": limits.max_upload_bytes,
        "documents": {"used": len(rows), "limit": limits.max_documents},
        "storage": {
            "used_bytes": sum(int(r.get("size_bytes") or 0) for r in rows),
            "limit_bytes": limits.max_storage_bytes,
        },
        "questions_today": {
            "used": db_service.count_user_questions_since(user.id, _start_of_today_utc()),
            "limit": limits.daily_questions,
        },
    }


# ── Profile & plan ───────────────────────────────────────────────────

@router.get("/account")
def get_account(user: AuthUser = Depends(get_current_user)):
    """Who the user is, which plan they're on, and what Pro would give them."""
    profile = db_service.get_profile(user.id)
    current = plans.limits_for(plans.plan_of(profile))
    return {
        "id": user.id,
        "email": user.email,
        "display_name": (profile or {}).get("display_name") or "",
        "plan": current.plan,
        "subscription": {
            "status": (profile or {}).get("subscription_status"),
            "renews_at": (profile or {}).get("current_period_end"),
            "cancel_at_period_end": bool((profile or {}).get("cancel_at_period_end")),
        },
        "billing": {
            "available": config.BILLING_DEMO_MODE,
            "demo": True,
            "price_cents": PRO_PRICE_CENTS,
            "currency": "usd",
        },
        "limits": {
            plans.FREE: _limits_out(plans.limits_for(plans.FREE)),
            plans.PRO: _limits_out(plans.limits_for(plans.PRO)),
        },
    }


class ProfileBody(BaseModel):
    display_name: str = Field(max_length=60)


@router.patch("/account")
def update_account(body: ProfileBody, user: AuthUser = Depends(get_current_user)):
    name = " ".join(body.display_name.split())
    db_service.update_profile(user.id, {"display_name": name})
    return {"status": "success", "display_name": name}


# ── Preferences ──────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(user: AuthUser = Depends(get_current_user)):
    profile = db_service.get_profile(user.id)
    return {"settings": user_settings.merged((profile or {}).get("settings"))}


@router.put("/settings")
def update_settings(patch: user_settings.SettingsPatch, user: AuthUser = Depends(get_current_user)):
    profile = db_service.get_profile(user.id)
    try:
        settings = user_settings.apply_patch((profile or {}).get("settings"), patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db_service.update_profile(user.id, {"settings": settings})
    return {"settings": settings}


# ── Password ─────────────────────────────────────────────────────────

class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _verify_password(user: AuthUser, password: str) -> None:
    """
    Confirm the account password before a sensitive change. A wrong password is
    answered with 400, not 401: a 401 makes the app think the session expired
    and signs the user out.
    """
    check_rate_limit(f"password:{user.id}", 5, 900)
    if not user.email:
        raise HTTPException(status_code=400, detail="This account has no email address to verify.")
    try:
        _auth_client().auth.sign_in_with_password({"email": user.email, "password": password})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")


@router.post("/account/password")
def change_password(body: PasswordBody, user: AuthUser = Depends(get_current_user)):
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="Choose a password different from the current one.")
    _verify_password(user, body.current_password)
    client = config.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server.")
    try:
        client.auth.admin.update_user_by_id(user.id, {"password": body.new_password})
    except Exception as exc:
        raise _auth_error(exc, "Could not update the password. Please try again.")
    return {"status": "success"}


# ── Your data ────────────────────────────────────────────────────────

@router.get("/account/export")
def export_data(user: AuthUser = Depends(get_current_user)):
    """Everything DocuQuery stores about the user, as one JSON download."""
    profile = db_service.get_profile(user.id)
    conversations = []
    for conversation in db_service.list_conversations(user.id, limit=1000):
        messages = db_service.list_messages(user.id, conversation["id"])
        conversations.append(
            {
                **conversation,
                "messages": [
                    {k: m.get(k) for k in ("role", "content", "sources", "created_at")} for m in messages
                ],
            }
        )
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "email": user.email,
            "display_name": (profile or {}).get("display_name") or "",
            "plan": plans.plan_of(profile),
        },
        "settings": user_settings.merged((profile or {}).get("settings")),
        "documents": [
            {k: d.get(k) for k in ("filename", "file_type", "size_bytes", "page_count", "summary", "source_url", "tags", "folder", "created_at")}
            for d in db_service.list_documents(user.id)
        ],
        "conversations": conversations,
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="docuquery-export.json"'},
    )


def _delete_all_documents(user_id: str) -> int:
    removed = 0
    for row in db_service.list_documents(user_id):
        doc = db_service.get_document(user_id, row["filename"])
        db_service.delete_chunks(user_id, row["filename"])
        db_service.delete_document_row(user_id, row["filename"])
        db_service.delete_document_shares(user_id, row["filename"])
        if doc:
            file_store.delete(user_id, doc)
        removed += 1
    return removed


@router.delete("/account/chats")
def delete_all_chats(user: AuthUser = Depends(get_current_user)):
    return {"status": "success", "deleted": db_service.delete_all_conversations(user.id)}


@router.delete("/account/documents")
def delete_all_documents(user: AuthUser = Depends(get_current_user)):
    return {"status": "success", "deleted": _delete_all_documents(user.id)}


class DeleteAccountBody(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/account/delete")
def delete_account(body: DeleteAccountBody, user: AuthUser = Depends(get_current_user)):
    """Permanently delete the account and everything in it. Needs the account password."""
    _verify_password(user, body.password)
    client = config.supabase_client
    if client is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server.")

    _delete_all_documents(user.id)  # also removes the stored files, which the database can't do
    try:
        # Deleting the auth user cascades to chats, messages, shares, feedback and the profile.
        client.auth.admin.delete_user(user.id)
    except Exception as exc:
        print(f"Warning: could not delete user {user.id}: {exc}", file=sys.stderr)
        raise HTTPException(status_code=500, detail="Could not delete the account. Please try again.")
    security.clear_token_cache()
    return {"status": "success"}
