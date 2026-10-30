"""
Storage for the original uploaded files.

Two layers: a local disk cache (fast path) and Supabase Storage (durable
across redeploys on ephemeral-filesystem hosts). Files are keyed by
``<user_id>/<document_id><extension>`` — never by the user-supplied name —
so odd characters in a filename can't break storage or escape the folder.
"""

import os

from security import is_valid_uuid
from services import db_service

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")


def storage_key(user_id: str, doc_id: str, ext: str) -> str:
    return f"{user_id}/{doc_id}{ext}"


def _local_path(user_id: str, doc_id: str, ext: str) -> str | None:
    """Path of the cached copy, or None if the ids aren't valid UUIDs."""
    if not (is_valid_uuid(user_id) and is_valid_uuid(doc_id)):
        return None
    if not ext.startswith(".") or "/" in ext or "\\" in ext:
        return None
    return os.path.join(UPLOAD_DIR, user_id, f"{doc_id}{ext}")


def save(user_id: str, doc_id: str, ext: str, data: bytes, content_type: str) -> str:
    """Persist the file to disk and Supabase Storage; returns the storage key."""
    key = storage_key(user_id, doc_id, ext)
    path = _local_path(user_id, doc_id, ext)
    if path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass  # the cache is best-effort; Supabase Storage still holds the file
    db_service.upload_file_to_storage(key, data, content_type.split(";")[0])
    return key


def _doc_ext(doc: dict) -> str:
    return os.path.splitext(doc.get("storage_key") or "")[1].lower()


def load(user_id: str, doc: dict) -> bytes | None:
    """Return the file's bytes (cache first, then Supabase Storage), or None."""
    ext = _doc_ext(doc)
    path = _local_path(user_id, str(doc.get("id", "")), ext)
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()

    key = doc.get("storage_key")
    if not key:
        return None
    data = db_service.download_file_from_storage(key)
    if data and path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            pass  # serving still works even if caching fails
    return data


def delete(user_id: str, doc: dict) -> None:
    """Remove both copies of the file (best effort)."""
    path = _local_path(user_id, str(doc.get("id", "")), _doc_ext(doc))
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    if doc.get("storage_key"):
        db_service.delete_file_from_storage(doc["storage_key"])
