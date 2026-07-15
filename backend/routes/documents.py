"""
Routes for document management: list, upload, delete.
"""

import os
import fitz
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from backend.services import db_service
from backend.services.rag_service import get_embedding, chunk_text

router = APIRouter(prefix="/api", tags=["documents"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


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


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF, chunk its pages, embed each chunk, and persist to Supabase."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    try:
        file_bytes = await file.read()
        
        # Save raw file to uploads directory for PDF viewing
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        doc = fitz.open(stream=file_bytes, filetype="pdf")

        all_chunks: list[dict] = []
        for page_idx, page in enumerate(doc):
            page_text = page.get_text()
            all_chunks.extend(chunk_text(page_text, page_idx + 1))

        if not all_chunks:
            # Clean up the file if it contains no text
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="No readable text found in the PDF.")

        print(f"Extracted {len(all_chunks)} chunks from '{file.filename}'. Generating embeddings…")

        records = []
        for idx, item in enumerate(all_chunks):
            vector = get_embedding(item["chunk"])
            records.append(
                {
                    "filename": file.filename,
                    "chunk_index": idx,
                    "text": item["chunk"],
                    "page": item["page"],
                    "embedding": vector.tolist(),
                }
            )

        # Replace previous version of same document
        db_service.delete_by_filename(file.filename)
        db_service.insert_chunks(records)

        return {
            "status": "success",
            "filename": file.filename,
            "chunks_count": len(records),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {e}")


@router.delete("/documents/{filename}")
def delete_document(filename: str):
    """Delete a document and all its cached chunks / vectors."""
    try:
        deleted = db_service.delete_by_filename(filename)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Document not found.")
            
        # Also clean up the raw file
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        return {"status": "success", "deleted_count": deleted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.get("/documents/file/{filename}")
def get_pdf_file(filename: str):
    """Serve the raw PDF file for viewing."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path, media_type="application/pdf")
