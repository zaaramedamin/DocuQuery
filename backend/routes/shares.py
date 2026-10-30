"""
Sharing by link.

* Chat   → anyone with the link can READ the conversation (no sign-in needed).
* Source → a signed-in recipient can ADD A COPY to their own library; the copy
           is independent, so the owner deleting theirs doesn't affect it.

Links carry an unguessable token. The owner can revoke a link at any time.
"""

import os
import re
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import RATE_LIMIT_SHARE, RATE_LIMIT_SHARED_VIEW, RATE_LIMIT_UPLOAD
from routes.documents import check_quota
from security import AuthUser, get_current_user, is_valid_uuid, limited_user
from services import db_service, extractors, file_store
from services.rate_limit import check_rate_limit, client_ip

router = APIRouter(prefix="/api", tags=["shares"])

share_user = limited_user("share", RATE_LIMIT_SHARE)
accept_user = limited_user("upload", RATE_LIMIT_UPLOAD)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


class ShareBody(BaseModel):
    kind: Literal["conversation", "document"]
    # conversation id, or the document's file name
    ref: str = Field(min_length=1, max_length=300)


def _present(row: dict) -> dict:
    return {
        "id": row["id"],
        "token": row["token"],
        "kind": row["kind"],
        "ref": row.get("conversation_id") if row["kind"] == "conversation" else row.get("document_filename"),
        "created_at": row.get("created_at"),
    }


def _not_found() -> HTTPException:
    # One message for unknown, revoked and malformed links: don't reveal which.
    return HTTPException(status_code=404, detail="This link doesn't exist or has been turned off.")


def _lookup(token: str, request: Request) -> dict:
    check_rate_limit(f"shared-view:{client_ip(request)}", RATE_LIMIT_SHARED_VIEW[0], RATE_LIMIT_SHARED_VIEW[1])
    if not _TOKEN_RE.match(token or ""):
        raise _not_found()
    share = db_service.get_share_by_token(token)
    if share is None:
        raise _not_found()
    return share


# ── owner: create / list / revoke ────────────────────────────────────

@router.post("/shares")
def create_share(body: ShareBody, user: AuthUser = Depends(share_user)):
    """Create a share link (or return the existing one for the same chat / source)."""
    if body.kind == "conversation":
        if not is_valid_uuid(body.ref) or db_service.get_conversation(user.id, body.ref) is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    elif db_service.get_document(user.id, body.ref) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    existing = db_service.find_share(user.id, body.kind, body.ref)
    if existing:
        return _present(existing)
    return _present(db_service.create_share(user.id, body.kind, body.ref, secrets.token_urlsafe(24)))


@router.get("/shares")
def list_shares(user: AuthUser = Depends(get_current_user)):
    return {"shares": [_present(row) for row in db_service.list_shares(user.id)]}


@router.delete("/shares/{share_id}")
def revoke_share(share_id: str, user: AuthUser = Depends(get_current_user)):
    if not is_valid_uuid(share_id) or not db_service.delete_share(user.id, share_id):
        raise HTTPException(status_code=404, detail="Share not found.")
    return {"status": "success"}


# ── recipient: open a link ───────────────────────────────────────────

@router.get("/shared/{token}")
def view_shared(token: str, request: Request):
    """Public, read-only. A chat shows its messages; a source shows a short preview."""
    share = _lookup(token, request)
    owner = share["user_id"]

    if share["kind"] == "conversation":
        conversation = db_service.get_conversation(owner, share["conversation_id"])
        if conversation is None:
            raise _not_found()
        messages = [
            {
                "role": m["role"],
                "content": m["content"],
                # Only where an answer came from, never the quoted passages themselves.
                "sources": [{"filename": s.get("filename"), "page": s.get("page")} for s in (m.get("sources") or [])],
            }
            for m in db_service.list_messages(owner, conversation["id"])
        ]
        return {"kind": "conversation", "title": conversation["title"], "messages": messages}

    document = db_service.get_document(owner, share["document_filename"])
    if document is None:
        raise _not_found()
    return {
        "kind": "document",
        "filename": document["filename"],
        "file_type": document["file_type"],
        "page_count": document["page_count"],
        "size_bytes": document["size_bytes"],
        "summary": document.get("summary"),
    }


def _unique_name(user_id: str, wanted: str) -> str:
    """*wanted*, or "name (2).ext" etc. when the recipient already has a file with that name."""
    taken = {d["filename"] for d in db_service.list_documents(user_id)}
    if wanted not in taken:
        return wanted
    stem, ext = os.path.splitext(wanted)
    for n in range(2, 100):
        candidate = f"{stem} ({n}){ext}"
        if candidate not in taken:
            return candidate
    return f"{stem} ({uuid.uuid4().hex[:6]}){ext}"


@router.post("/shared/{token}/accept")
def accept_shared(token: str, request: Request, user: AuthUser = Depends(accept_user)):
    """Add a copy of a shared source to the signed-in user's library."""
    share = _lookup(token, request)
    if share["kind"] != "document":
        raise HTTPException(status_code=400, detail="Only shared sources can be added to a library.")
    owner = share["user_id"]
    if owner == user.id:
        raise HTTPException(status_code=400, detail="This source is already in your library.")

    source = db_service.get_document(owner, share["document_filename"], include_pages=True)
    if source is None:
        raise _not_found()

    new_name = _unique_name(user.id, source["filename"])
    check_quota(user.id, new_name, int(source.get("size_bytes") or 0))

    doc_id = str(uuid.uuid4())
    storage_key = None
    data = file_store.load(owner, source)
    if data is not None:
        ext = os.path.splitext(source.get("storage_key") or "")[1].lower() or ".bin"
        storage_key = file_store.save(
            user.id, doc_id, ext, data, extractors.CONTENT_TYPES.get(ext, "application/octet-stream")
        )

    copied = db_service.clone_document_chunks(owner, user.id, source["filename"], new_name)
    try:
        row = db_service.save_document(
            {
                "id": doc_id,
                "user_id": user.id,
                "filename": new_name,
                "file_type": source["file_type"],
                "storage_key": storage_key,
                "size_bytes": source.get("size_bytes") or 0,
                "page_count": source.get("page_count") or 0,
                "chunks_count": copied,
                "summary": source.get("summary"),
                "suggested_questions": source.get("suggested_questions") or [],
                "source_url": source.get("source_url"),
                "pages": source.get("pages"),
            }
        )
    except Exception:
        db_service.delete_chunks(user.id, new_name)  # don't leave orphan chunks behind
        raise

    row = dict(row)
    row.pop("pages", None)
    row.pop("storage_key", None)
    return {"status": "success", "document": row}
