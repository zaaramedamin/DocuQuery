"""
Routes for document management: list, upload, delete.
"""

import os
import fitz
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response

from backend.config import MAX_UPLOAD_BYTES
from backend.services import db_service
from backend.services.rag_service import get_embeddings, chunk_text

router = APIRouter(prefix="/api", tags=["documents"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_filename(filename: str | None) -> str:
    """
    Reduce a client-supplied filename to its base name so it can never
    escape UPLOAD_DIR (blocks path traversal such as "..\\..\\x.pdf").
    """
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    if not name or name in (".", "..") or not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    return name


@router.get("/documents")
def list_documents():
    """Return all unique document filenames stored in Supabase."""
    try:
        filenames = db_service.list_filenames()
        return {"documents": filenames}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")


# NOTE: deliberately a sync `def` — FastAPI runs it in a worker thread, so the
# blocking Hugging Face embedding calls do not stall the event loop for
# every other request while a document is being processed.
@router.post("/upload")
def upload_document(file: UploadFile = File(...)):
    """Upload a PDF, chunk its pages, embed each chunk, and persist to Supabase."""
    safe_name = _safe_filename(file.filename)

    file_bytes = file.file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        all_chunks: list[dict] = []
        for page_idx, page in enumerate(doc):
            page_text = page.get_text()
            all_chunks.extend(chunk_text(page_text, page_idx + 1))

        if not all_chunks:
            raise HTTPException(status_code=400, detail="No readable text found in the PDF.")

        print(f"Extracted {len(all_chunks)} chunks from '{safe_name}'. Generating embeddings…")

        # Embed everything BEFORE touching the database, so a failure here
        # leaves any previously indexed version of the document intact.
        vectors = get_embeddings([item["chunk"] for item in all_chunks])

        records = [
            {
                "filename": safe_name,
                "chunk_index": idx,
                "text": item["chunk"],
                "page": item["page"],
                "embedding": vector.tolist(),
            }
            for idx, (item, vector) in enumerate(zip(all_chunks, vectors))
        ]

        # Replace previous version of same document
        db_service.delete_by_filename(safe_name)
        db_service.insert_chunks(records)

        # Persist the raw PDF: local disk (fast path) + Supabase Storage
        # (durable across redeploys on ephemeral-filesystem hosts).
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        db_service.upload_pdf_to_storage(safe_name, file_bytes)

        return {
            "status": "success",
            "filename": safe_name,
            "chunks_count": len(records),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {e}")


@router.delete("/documents/{filename}")
def delete_document(filename: str):
    """Delete a document and all its cached chunks / vectors."""
    safe_name = _safe_filename(filename)
    try:
        deleted = db_service.delete_by_filename(safe_name)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Document not found.")

        # Also clean up the raw file (local cache + durable storage)
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        if os.path.exists(file_path):
            os.remove(file_path)
        db_service.delete_pdf_from_storage(safe_name)

        return {"status": "success", "deleted_count": deleted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.get("/documents/file/{filename}")
def get_pdf_file(filename: str):
    """Serve the raw PDF file for viewing."""
    safe_name = _safe_filename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/pdf")

    # Local cache miss (e.g. after a redeploy) — restore from Supabase Storage.
    data = db_service.download_pdf_from_storage(safe_name)
    if data:
        try:
            with open(file_path, "wb") as f:
                f.write(data)
        except OSError:
            pass  # serving still works even if caching fails
        return Response(content=data, media_type="application/pdf")

    raise HTTPException(status_code=404, detail="File not found.")
