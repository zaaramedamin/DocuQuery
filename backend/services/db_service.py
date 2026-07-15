"""
Supabase data-access layer.

Provides CRUD helpers that wrap Supabase client calls so route handlers
stay thin and testable.
"""

from fastapi import HTTPException
from backend.config import supabase_client


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
        response = client.table("document_chunks").select("filename").execute()
        # De-duplicate the filenames returned
        return list(set(row["filename"] for row in response.data))
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
    """Return True if at least one chunk exists in the table."""
    client = get_client()
    try:
        response = client.table("document_chunks").select("id").limit(1).execute()
        return len(response.data) > 0
    except Exception as e:
        # If table is empty or doesn't exist, return False
        return False
