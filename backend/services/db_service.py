"""
Supabase data-access layer.

Provides CRUD helpers that wrap Supabase client calls so route handlers
stay thin and testable.
"""

import sys
from fastapi import HTTPException
from backend.config import supabase_client

# Supabase Storage bucket that holds the original uploaded PDFs so they
# survive ephemeral-filesystem hosts (e.g. Render free tier).
STORAGE_BUCKET = "documents"


def get_client():
    """Return the Supabase client, or raise 500 if it is not configured/connected."""
    if supabase_client is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase is not connected. Please verify your SUPABASE_URL and SUPABASE_KEY in your .env file.",
        )
    return supabase_client


def list_filenames() -> list[str]:
    """Return a deduplicated list of uploaded document filenames."""
    client = get_client()
    try:
        # Prefer the DISTINCT RPC (avoids fetching one row per chunk).
        response = client.rpc("list_document_filenames", {}).execute()
        return sorted(response.data or [])
    except Exception:
        pass  # RPC not deployed yet — fall back to a plain select
    try:
        response = client.table("document_chunks").select("filename").execute()
        return sorted(set(row["filename"] for row in response.data))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query filenames: {e}")


def insert_chunks(chunks: list[dict]) -> int:
    """Bulk-insert chunk documents into Supabase. Returns the count inserted."""
    if not chunks:
        return 0
    client = get_client()
    try:
        response = client.table("document_chunks").insert(chunks).execute()
        return len(response.data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to insert chunks: {e}")


def delete_by_filename(filename: str) -> int:
    """Delete all chunks belonging to *filename*. Returns deleted count."""
    client = get_client()
    try:
        response = client.table("document_chunks").delete().eq("filename", filename).execute()
        return len(response.data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chunks: {e}")


def has_any_documents() -> bool:
    """Return True if at least one chunk exists in the table.

    Raises HTTP 500 on genuine database errors instead of masking them
    as "no documents uploaded yet".
    """
    client = get_client()
    try:
        response = client.table("document_chunks").select("id").limit(1).execute()
        return len(response.data) > 0
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database check failed: {e}")


# ── Supabase Storage (original PDF files) ─────────────────────────────
# These are best-effort: local disk remains the fast path, storage keeps
# the file durable across redeploys.

def upload_pdf_to_storage(filename: str, data: bytes) -> bool:
    """Store the raw PDF in the storage bucket. Returns True on success."""
    try:
        client = get_client()
        client.storage.from_(STORAGE_BUCKET).upload(
            filename,
            data,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return True
    except Exception as e:
        print(f"Warning: could not store PDF in Supabase Storage: {e}", file=sys.stderr)
        return False


def download_pdf_from_storage(filename: str) -> bytes | None:
    """Fetch the raw PDF from the storage bucket, or None if unavailable."""
    try:
        client = get_client()
        return client.storage.from_(STORAGE_BUCKET).download(filename)
    except Exception:
        return None


def delete_pdf_from_storage(filename: str) -> None:
    """Best-effort removal of the PDF from the storage bucket."""
    try:
        client = get_client()
        client.storage.from_(STORAGE_BUCKET).remove([filename])
    except Exception as e:
        print(f"Warning: could not delete PDF from Supabase Storage: {e}", file=sys.stderr)
