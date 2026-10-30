"""
Supabase data-access layer.

Every function that touches user data takes a ``user_id`` and filters by
it, so one user can never read or modify another user's documents or chats.
Route handlers stay thin and the whole module can be swapped out in tests.
"""

import sys
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from config import supabase_client

# Supabase Storage bucket that holds the original uploaded files so they
# survive ephemeral-filesystem hosts (e.g. Render free tier).
STORAGE_BUCKET = "documents"

# Columns returned when listing documents (omits the large `pages` blob).
_DOC_LIST_COLUMNS = (
    "id,filename,file_type,size_bytes,page_count,chunks_count,"
    "summary,suggested_questions,source_url,tags,folder,created_at"
)
# The same without `folder`, for a database that has not had the latest schema run yet.
_DOC_LIST_COLUMNS_NO_FOLDER = _DOC_LIST_COLUMNS.replace("tags,folder,", "tags,")
_INSERT_BATCH = 100


def _lacks_folder_column(exc: Exception) -> bool:
    return "folder" in str(exc) and "does not exist" in str(exc)


def get_client():
    """Return the Supabase client, or raise 500 if it is not configured/connected."""
    if supabase_client is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase is not connected. Please verify your SUPABASE_URL and SUPABASE_KEY in your .env file.",
        )
    return supabase_client


def _db_error(action: str, exc: Exception) -> HTTPException:
    text = str(exc)
    if "hybrid_search" in text or "does not exist" in text or "PGRST205" in text or "PGRST202" in text:
        return HTTPException(
            status_code=500,
            detail=(
                f"{action}: the database schema is out of date. "
                "Run the latest supabase_schema.sql in the Supabase SQL editor."
            ),
        )
    return HTTPException(status_code=500, detail=f"{action}: {text}")


# ══════════════════════════════════════════════════════════════════════
# Documents
# ══════════════════════════════════════════════════════════════════════

def list_documents(user_id: str) -> list[dict]:
    """Return the user's documents (metadata only), newest first."""
    client = get_client()

    def fetch(columns: str):
        return client.table("documents").select(columns).eq("user_id", user_id).order("created_at", desc=True).execute()

    try:
        try:
            res = fetch(_DOC_LIST_COLUMNS)
            return res.data or []
        except Exception as e:
            if not _lacks_folder_column(e):
                raise
            # Folders arrived in a later schema: until it is run, the library works without them.
            return [{**row, "folder": None} for row in (fetch(_DOC_LIST_COLUMNS_NO_FOLDER).data or [])]
    except Exception as e:
        raise _db_error("Failed to list documents", e)


def get_document(user_id: str, filename: str, include_pages: bool = False) -> dict | None:
    """Return one document row, or None when the user has no such document."""
    client = get_client()

    def fetch(columns: str):
        return client.table("documents").select(columns).eq("user_id", user_id).eq("filename", filename).limit(1).execute()

    try:
        try:
            res = fetch("*" if include_pages else _DOC_LIST_COLUMNS + ",storage_key")
        except Exception as e:
            if include_pages or not _lacks_folder_column(e):
                raise
            res = fetch(_DOC_LIST_COLUMNS_NO_FOLDER + ",storage_key")
        return res.data[0] if res.data else None
    except Exception as e:
        raise _db_error("Failed to load document", e)


def save_document(row: dict) -> dict:
    """Insert or replace the document row identified by (user_id, filename)."""
    client = get_client()
    try:
        res = client.table("documents").upsert(row, on_conflict="user_id,filename").execute()
        return res.data[0] if res.data else row
    except Exception as e:
        raise _db_error("Failed to save document", e)


def delete_document_row(user_id: str, filename: str) -> None:
    client = get_client()
    try:
        client.table("documents").delete().eq("user_id", user_id).eq("filename", filename).execute()
    except Exception as e:
        raise _db_error("Failed to delete document", e)


def count_documents(user_id: str) -> int:
    client = get_client()
    try:
        res = client.table("documents").select("id", count="exact").eq("user_id", user_id).execute()
        return res.count or 0
    except Exception as e:
        raise _db_error("Failed to count documents", e)


def storage_used_bytes(user_id: str) -> int:
    client = get_client()
    try:
        res = client.table("documents").select("size_bytes").eq("user_id", user_id).execute()
        return sum(int(r.get("size_bytes") or 0) for r in (res.data or []))
    except Exception as e:
        raise _db_error("Failed to compute storage usage", e)


def has_any_documents(user_id: str) -> bool:
    """True if the user has at least one document.

    Raises HTTP 500 on genuine database errors instead of masking them
    as "no documents uploaded yet".
    """
    client = get_client()
    try:
        res = client.table("documents").select("id").eq("user_id", user_id).limit(1).execute()
        return len(res.data) > 0
    except Exception as e:
        raise _db_error("Database check failed", e)


# ══════════════════════════════════════════════════════════════════════
# Chunks & search
# ══════════════════════════════════════════════════════════════════════

def insert_chunks(chunks: list[dict]) -> int:
    """Bulk-insert chunk rows (each must include user_id). Returns the count inserted."""
    if not chunks:
        return 0
    client = get_client()
    inserted = 0
    try:
        for start in range(0, len(chunks), _INSERT_BATCH):
            batch = chunks[start : start + _INSERT_BATCH]
            res = client.table("document_chunks").insert(batch).execute()
            inserted += len(res.data)
        return inserted
    except Exception as e:
        raise _db_error("Failed to insert chunks", e)


def delete_chunks(user_id: str, filename: str) -> int:
    """Delete all of the user's chunks belonging to *filename*. Returns deleted count."""
    client = get_client()
    try:
        res = (
            client.table("document_chunks")
            .delete()
            .eq("user_id", user_id)
            .eq("filename", filename)
            .execute()
        )
        return len(res.data)
    except Exception as e:
        raise _db_error("Failed to delete chunks", e)


def hybrid_search(
    user_id: str,
    embedding: list[float],
    tsquery: str,
    match_count: int,
    filename: str | None = None,
    filenames: list[str] | None = None,
) -> list[dict]:
    """
    Vector + keyword search (RRF-fused), restricted to the user's own chunks.
    ``filename`` limits it to one document, ``filenames`` to a set (e.g. a tag).
    """
    client = get_client()
    params: dict[str, Any] = {
        "p_user_id": user_id,
        "query_embedding": embedding,
        "query_tsquery": tsquery,
        "match_count": match_count,
    }
    if filename:
        params["filter_filename"] = filename
    if filenames:
        params["filter_filenames"] = filenames
    try:
        return client.rpc("hybrid_search", params).execute().data or []
    except Exception as e:
        raise _db_error("Search failed", e)


# ══════════════════════════════════════════════════════════════════════
# Supabase Storage (original files)
# ══════════════════════════════════════════════════════════════════════
# Best-effort: local disk remains the fast path, storage keeps the file
# durable across redeploys.

def upload_file_to_storage(key: str, data: bytes, content_type: str) -> bool:
    """Store the raw file in the storage bucket. Returns True on success."""
    try:
        client = get_client()
        client.storage.from_(STORAGE_BUCKET).upload(
            key,
            data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return True
    except Exception as e:
        print(f"Warning: could not store file in Supabase Storage: {e}", file=sys.stderr)
        return False


def download_file_from_storage(key: str) -> bytes | None:
    """Fetch the raw file from the storage bucket, or None if unavailable."""
    try:
        client = get_client()
        return client.storage.from_(STORAGE_BUCKET).download(key)
    except Exception:
        return None


def delete_file_from_storage(key: str) -> None:
    """Best-effort removal of the file from the storage bucket."""
    try:
        client = get_client()
        client.storage.from_(STORAGE_BUCKET).remove([key])
    except Exception as e:
        print(f"Warning: could not delete file from Supabase Storage: {e}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════
# Conversations & messages
# ══════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_conversation(user_id: str, title: str = "New chat") -> dict:
    client = get_client()
    try:
        res = client.table("conversations").insert({"user_id": user_id, "title": title}).execute()
        return res.data[0]
    except Exception as e:
        raise _db_error("Failed to create conversation", e)


def list_conversations(user_id: str, limit: int = 100) -> list[dict]:
    client = get_client()
    try:
        res = (
            client.table("conversations")
            .select("id,title,created_at,updated_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise _db_error("Failed to list conversations", e)


def get_conversation(user_id: str, conversation_id: str) -> dict | None:
    client = get_client()
    try:
        res = (
            client.table("conversations")
            .select("id,title,created_at,updated_at")
            .eq("user_id", user_id)
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        raise _db_error("Failed to load conversation", e)


def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    client = get_client()
    try:
        res = (
            client.table("conversations")
            .update({"title": title})
            .eq("user_id", user_id)
            .eq("id", conversation_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        raise _db_error("Failed to rename conversation", e)


def touch_conversation(user_id: str, conversation_id: str) -> None:
    """Bump updated_at so the chat floats to the top of the history list."""
    client = get_client()
    try:
        client.table("conversations").update({"updated_at": _now_iso()}).eq("user_id", user_id).eq(
            "id", conversation_id
        ).execute()
    except Exception as e:
        print(f"Warning: could not update conversation timestamp: {e}", file=sys.stderr)


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    client = get_client()
    try:
        res = (
            client.table("conversations")
            .delete()
            .eq("user_id", user_id)
            .eq("id", conversation_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        raise _db_error("Failed to delete conversation", e)


_MESSAGE_COLUMNS = "id,role,content,sources,question,feedback,created_at"


def list_messages(user_id: str, conversation_id: str) -> list[dict]:
    """All messages of a conversation, oldest first."""
    client = get_client()
    try:
        res = (
            client.table("messages")
            .select(_MESSAGE_COLUMNS)
            .eq("user_id", user_id)
            .eq("conversation_id", conversation_id)
            .order("seq")
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise _db_error("Failed to load messages", e)


def recent_messages(user_id: str, conversation_id: str, count: int) -> list[dict]:
    """The last *count* messages of a conversation, oldest first."""
    client = get_client()
    try:
        res = (
            client.table("messages")
            .select(_MESSAGE_COLUMNS)
            .eq("user_id", user_id)
            .eq("conversation_id", conversation_id)
            .order("seq", desc=True)
            .limit(count)
            .execute()
        )
        return list(reversed(res.data or []))
    except Exception as e:
        raise _db_error("Failed to load messages", e)


def add_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
    question: str | None = None,
    message_id: str | None = None,
) -> dict:
    client = get_client()
    row: dict[str, Any] = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "question": question,
    }
    if message_id:
        row["id"] = message_id
    try:
        res = client.table("messages").insert(row).execute()
        return res.data[0]
    except Exception as e:
        raise _db_error("Failed to save message", e)


def delete_last_exchange(user_id: str, conversation_id: str) -> None:
    """
    Remove the trailing assistant answer and the user question before it
    (used by "Regenerate"). Does nothing unless the conversation really
    ends with a user → assistant pair.
    """
    last = recent_messages(user_id, conversation_id, 2)
    if len(last) != 2 or last[0]["role"] != "user" or last[1]["role"] != "assistant":
        return
    client = get_client()
    try:
        client.table("messages").delete().eq("user_id", user_id).in_(
            "id", [last[0]["id"], last[1]["id"]]
        ).execute()
    except Exception as e:
        raise _db_error("Failed to remove previous answer", e)


def set_message_feedback(user_id: str, message_id: str, feedback: str) -> None:
    client = get_client()
    try:
        client.table("messages").update({"feedback": feedback}).eq("user_id", user_id).eq(
            "id", message_id
        ).execute()
    except Exception as e:
        print(f"Warning: could not store feedback on message: {e}", file=sys.stderr)


def count_user_questions_since(user_id: str, since: datetime) -> int:
    client = get_client()
    try:
        res = (
            client.table("messages")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("role", "user")
            .gte("created_at", since.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception as e:
        raise _db_error("Failed to count questions", e)


def insert_feedback(user_id: str, message_id: str, feedback: str, question: str, answer: str) -> None:
    client = get_client()
    client.table("feedback").insert(
        {
            "user_id": user_id,
            "message_id": message_id,
            "feedback": feedback,
            "question": question,
            "answer": answer,
        }
    ).execute()


# ══════════════════════════════════════════════════════════════════════
# Tags
# ══════════════════════════════════════════════════════════════════════

def set_document_tags(user_id: str, filename: str, tags: list[str]) -> bool:
    client = get_client()
    try:
        res = (
            client.table("documents")
            .update({"tags": tags})
            .eq("user_id", user_id)
            .eq("filename", filename)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        raise _db_error("Failed to update tags", e)


# ══════════════════════════════════════════════════════════════════════
# Folders
# ══════════════════════════════════════════════════════════════════════
# A folder is just a name stored on each document that belongs to it (a document is
# in at most one folder), so a folder exists exactly as long as it holds a document.

def set_documents_folder(user_id: str, filenames: list[str], folder: str | None) -> int:
    """Put the user's documents *filenames* into *folder* (None = take them out). Returns how many moved."""
    if not filenames:
        return 0
    client = get_client()
    try:
        res = (
            client.table("documents")
            .update({"folder": folder})
            .eq("user_id", user_id)
            .in_("filename", filenames)
            .execute()
        )
        return len(res.data or [])
    except Exception as e:
        raise _db_error("Failed to update folder", e)


def rename_folder(user_id: str, old: str, new: str) -> int:
    """Rename a folder (every document in it moves). Returns how many documents changed."""
    client = get_client()
    try:
        res = client.table("documents").update({"folder": new}).eq("user_id", user_id).eq("folder", old).execute()
        return len(res.data or [])
    except Exception as e:
        raise _db_error("Failed to rename folder", e)


# ══════════════════════════════════════════════════════════════════════
# Searching past chats
# ══════════════════════════════════════════════════════════════════════

def _like_pattern(text: str) -> str:
    """Escape LIKE wildcards so the user's text is matched literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_conversations(user_id: str, query: str, limit: int = 30) -> list[dict]:
    """
    Chats whose title or messages contain *query* (case-insensitive).
    Returns [{id, title, updated_at, snippet}] newest first.
    """
    client = get_client()
    pattern = _like_pattern(query)
    try:
        by_title = (
            client.table("conversations")
            .select("id,title,updated_at")
            .eq("user_id", user_id)
            .ilike("title", pattern)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        hits = (
            client.table("messages")
            .select("conversation_id,content,created_at")
            .eq("user_id", user_id)
            .ilike("content", pattern)
            .order("created_at", desc=True)
            .limit(limit * 3)
            .execute()
            .data
            or []
        )
        results: dict[str, dict] = {c["id"]: {**c, "snippet": ""} for c in by_title}

        snippets: dict[str, str] = {}
        for hit in hits:
            snippets.setdefault(hit["conversation_id"], hit["content"])
        missing = [cid for cid in snippets if cid not in results]
        if missing:
            rows = (
                client.table("conversations")
                .select("id,title,updated_at")
                .eq("user_id", user_id)
                .in_("id", missing)
                .execute()
                .data
                or []
            )
            for row in rows:
                results[row["id"]] = {**row, "snippet": ""}
        for cid, content in snippets.items():
            if cid in results:
                results[cid]["snippet"] = content

        ordered = sorted(results.values(), key=lambda r: r["updated_at"], reverse=True)
        return ordered[:limit]
    except Exception as e:
        raise _db_error("Search failed", e)


# ══════════════════════════════════════════════════════════════════════
# Sharing
# ══════════════════════════════════════════════════════════════════════

_SHARE_COLUMNS = "id,token,kind,conversation_id,document_filename,created_at"


def find_share(user_id: str, kind: str, ref: str) -> dict | None:
    """The user's existing share link for a conversation id / document filename, if any."""
    client = get_client()
    column = "conversation_id" if kind == "conversation" else "document_filename"
    try:
        res = (
            client.table("shares")
            .select(_SHARE_COLUMNS)
            .eq("user_id", user_id)
            .eq("kind", kind)
            .eq(column, ref)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        raise _db_error("Failed to look up share", e)


def create_share(user_id: str, kind: str, ref: str, token: str) -> dict:
    client = get_client()
    row: dict[str, Any] = {"user_id": user_id, "kind": kind, "token": token}
    row["conversation_id" if kind == "conversation" else "document_filename"] = ref
    try:
        return client.table("shares").insert(row).execute().data[0]
    except Exception as e:
        raise _db_error("Failed to create share", e)


def list_shares(user_id: str) -> list[dict]:
    client = get_client()
    try:
        res = (
            client.table("shares")
            .select(_SHARE_COLUMNS)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise _db_error("Failed to list shares", e)


def delete_share(user_id: str, share_id: str) -> bool:
    client = get_client()
    try:
        res = client.table("shares").delete().eq("user_id", user_id).eq("id", share_id).execute()
        return bool(res.data)
    except Exception as e:
        raise _db_error("Failed to delete share", e)


def delete_document_shares(user_id: str, filename: str) -> None:
    """Remove the share link of a document that no longer exists."""
    client = get_client()
    try:
        client.table("shares").delete().eq("user_id", user_id).eq("kind", "document").eq(
            "document_filename", filename
        ).execute()
    except Exception as e:
        print(f"Warning: could not remove document share: {e}", file=sys.stderr)


def get_share_by_token(token: str) -> dict | None:
    """
    Look a share link up by its secret token. This is the ONE query that is not
    scoped by the signed-in user: the unguessable token itself is the credential.
    """
    client = get_client()
    try:
        res = client.table("shares").select(_SHARE_COLUMNS + ",user_id").eq("token", token).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        raise _db_error("Failed to open share", e)


def clone_document_chunks(src_user: str, dst_user: str, filename: str, new_filename: str) -> int:
    """Copy a document's chunks and embeddings to another user (no re-embedding)."""
    client = get_client()
    try:
        res = client.rpc(
            "clone_document_chunks",
            {
                "p_src_user": src_user,
                "p_dst_user": dst_user,
                "p_filename": filename,
                "p_new_filename": new_filename,
            },
        ).execute()
        copied = res.data
        if isinstance(copied, list):  # some client versions wrap a scalar result in a list
            copied = copied[0] if copied else 0
        return int(copied or 0)
    except Exception as e:
        raise _db_error("Failed to copy document", e)


# ══════════════════════════════════════════════════════════════════════
# Profiles (display name, plan, preferences)
# ══════════════════════════════════════════════════════════════════════

_PROFILE_COLUMNS = (
    "user_id,display_name,plan,subscription_status,current_period_end,cancel_at_period_end,settings"
)


def get_profile(user_id: str) -> dict | None:
    """
    The user's profile row, or None when there is none yet.

    Deliberately fail-soft: if the profiles table is missing (schema not updated
    yet) the app keeps working on the Free plan instead of failing every request.
    """
    client = get_client()
    try:
        res = client.table("profiles").select(_PROFILE_COLUMNS).eq("user_id", user_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Warning: could not load the profile: {e}", file=sys.stderr)
        return None


def update_profile(user_id: str, fields: dict) -> dict:
    """Create the profile if needed and merge *fields* into it."""
    client = get_client()
    row = {"user_id": user_id, **fields, "updated_at": _now_iso()}
    try:
        res = client.table("profiles").upsert(row, on_conflict="user_id").execute()
        return res.data[0] if res.data else row
    except Exception as e:
        raise _db_error("Failed to save your profile", e)


# ══════════════════════════════════════════════════════════════════════
# Bulk deletes (account settings)
# ══════════════════════════════════════════════════════════════════════

def delete_all_conversations(user_id: str) -> int:
    """Delete every saved chat of the user (messages and chat share links go with them)."""
    client = get_client()
    try:
        res = client.table("conversations").delete().eq("user_id", user_id).execute()
        return len(res.data or [])
    except Exception as e:
        raise _db_error("Failed to delete chats", e)
