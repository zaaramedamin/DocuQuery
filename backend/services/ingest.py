"""
Document ingestion pipeline.

    extract text (OCR for scans) → chunk → embed → summarize → store

``ingest()`` is a generator that yields progress events so the upload
endpoint can stream real progress to the browser:

    {"type": "progress", "percent": 42, "message": "Embedding 64/150 chunks…"}

and finishes by returning the saved document row (via ``StopIteration``)
or raising ``HTTPException`` for problems the user can fix.
"""

import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Iterator

import pymupdf
from fastapi import HTTPException

from config import (
    MAX_OCR_PAGES,
    MAX_PAGES_PER_DOC,
    MAX_TEXT_CHARS,
    OCR_MIN_CHARS,
)
from services import db_service, extractors, file_store
from services.rag_service import chunk_text, get_embeddings
from services.summarizer import summarize_document

_EMBED_STEP = 32
_OCR_WORKERS = 3
_OCR_DPI = 150


@dataclass
class IngestRequest:
    user_id: str
    filename: str            # display name, unique per user
    file_type: str           # pdf | docx | txt | md | image | url
    ext: str                 # extension used for the stored copy (".pdf", ".docx", ".html", …)
    data: bytes              # raw bytes of the original file
    content_type: str
    source_url: str | None = None
    # Pre-extracted pages (web pages); skips file parsing when given.
    pages: list[str] | None = None
    # Scanned pages read with OCR (the plan's cap); None = the server default.
    max_ocr_pages: int | None = None


@dataclass
class Extraction:
    pages: list[str]
    page_count: int
    warnings: list[str] = field(default_factory=list)


def progress(percent: int, message: str) -> dict:
    return {"type": "progress", "percent": max(0, min(100, percent)), "message": message}


# ── Extraction ───────────────────────────────────────────────────────

def _extract_pdf(data: bytes, max_ocr_pages: int | None = None) -> Iterator[dict]:
    """Yield progress while reading a PDF; returns an Extraction."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(status_code=400, detail="This PDF could not be opened. It may be corrupted or password-protected.")

    if doc.needs_pass:
        raise HTTPException(status_code=400, detail="This PDF is password-protected and can't be read.")
    page_count = doc.page_count
    if page_count > MAX_PAGES_PER_DOC:
        raise HTTPException(
            status_code=400,
            detail=f"This PDF has {page_count} pages; the limit is {MAX_PAGES_PER_DOC}.",
        )

    texts: list[str] = []
    for page in doc:
        texts.append(page.get_text())
    yield progress(10, f"Read {page_count} page{'s' if page_count != 1 else ''}")

    scanned = [i for i, t in enumerate(texts) if len(t.strip()) < OCR_MIN_CHARS]
    warnings: list[str] = []
    if scanned:
        ocr_limit = max_ocr_pages if max_ocr_pages is not None else MAX_OCR_PAGES
        to_ocr = scanned[:ocr_limit]
        if len(scanned) > len(to_ocr):
            skipped = len(scanned) - len(to_ocr)
            warnings.append(
                f"{skipped} scanned page{'s were' if skipped != 1 else ' was'} skipped (OCR limit is {ocr_limit} pages)."
            )

        # Render in this thread (PyMuPDF documents are not thread-safe), OCR in parallel.
        images: dict[int, bytes] = {}
        for index in to_ocr:
            pix = doc[index].get_pixmap(dpi=_OCR_DPI)
            images[index] = pix.tobytes("jpeg", jpg_quality=85)

        failures = 0
        last_error = ""
        done = 0
        with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
            futures = {pool.submit(_ocr_safe, images[i]): i for i in to_ocr}
            for future in as_completed(futures):
                index = futures[future]
                text, error = future.result()
                done += 1
                if error:
                    failures += 1
                    last_error = error
                else:
                    texts[index] = text
                yield progress(10 + int(25 * done / len(to_ocr)), f"Reading scanned pages {done}/{len(to_ocr)}…")

        if failures:
            warnings.append(f"{failures} scanned page{'s' if failures != 1 else ''} could not be read ({last_error}).")
        if failures == len(to_ocr) and not any(t.strip() for t in texts):
            raise HTTPException(
                status_code=502,
                detail=f"This looks like a scanned document, but the text could not be read: {last_error}",
            )

    doc.close()
    return Extraction(pages=texts, page_count=page_count, warnings=warnings)


def _ocr_safe(image_bytes: bytes) -> tuple[str, str]:
    """OCR one page image. Returns (text, error_message)."""
    try:
        return extractors.ocr_image(image_bytes, "image/jpeg"), ""
    except Exception as exc:
        return "", str(exc)[:200]


def _check_page_limit(count: int) -> None:
    if count > MAX_PAGES_PER_DOC:
        raise HTTPException(
            status_code=400,
            detail=f"This file has {count} pages / sections; the limit is {MAX_PAGES_PER_DOC}.",
        )


def _extract(req: IngestRequest) -> Iterator[dict]:
    if req.pages is not None:
        pages = extractors._limit_chars(req.pages, MAX_TEXT_CHARS)
        return Extraction(pages=pages, page_count=len(pages))

    if req.file_type == "pdf":
        extraction = yield from _extract_pdf(req.data, req.max_ocr_pages)
        return extraction

    if req.file_type in ("docx", "pptx", "xlsx", "csv", "txt", "md"):
        yield progress(8, "Reading document…")
        pages = extractors.extract_text_pages(req.data, req.file_type, MAX_TEXT_CHARS)
        _check_page_limit(len(pages))
        return Extraction(pages=pages, page_count=len(pages))

    if req.file_type == "image":
        if len(req.data) > extractors.MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large to read (max 15 MB).")
        yield progress(10, "Reading text from image…")
        mime = extractors.image_mime_type(req.ext)
        text, error = "", ""
        try:
            text = extractors.ocr_image(req.data, mime)
        except Exception as exc:
            error = str(exc)[:200]
        if not text.strip():
            detail = f"The text in this image could not be read: {error}" if error else "No readable text found in this image."
            raise HTTPException(status_code=502 if error else 400, detail=detail)
        return Extraction(pages=[text], page_count=1)

    raise HTTPException(status_code=400, detail="Unsupported file type.")


# ── Pipeline ─────────────────────────────────────────────────────────

def ingest(req: IngestRequest) -> Iterator[dict]:
    """Run the full pipeline; yields progress events and returns the saved document row."""
    yield progress(2, "Starting…")

    extraction: Extraction = yield from _extract(req)
    pages = extraction.pages
    if not any(p.strip() for p in pages):
        raise HTTPException(status_code=400, detail="No readable text found in this file.")

    # Chunk
    all_chunks: list[dict] = []
    for page_number, page_text in enumerate(pages, start=1):
        all_chunks.extend(chunk_text(page_text, page_number))
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No readable text found in this file.")
    yield progress(38, f"Split into {len(all_chunks)} passages")

    # Embed everything BEFORE touching the database, so a failure here
    # leaves any previously indexed version of the document intact.
    texts = [c["chunk"] for c in all_chunks]
    vectors = []
    for start in range(0, len(texts), _EMBED_STEP):
        vectors.extend(get_embeddings(texts[start : start + _EMBED_STEP]))
        done = min(start + _EMBED_STEP, len(texts))
        yield progress(38 + int(47 * done / len(texts)), f"Embedding passages {done}/{len(texts)}…")

    # Summary + suggested questions (best effort)
    yield progress(87, "Writing a summary…")
    summary = summarize_document(req.filename, pages)

    # Persist
    yield progress(93, "Saving…")
    existing = db_service.get_document(req.user_id, req.filename)
    doc_id = str(uuid.uuid4())
    key = file_store.storage_key(req.user_id, doc_id, req.ext)

    records = [
        {
            "user_id": req.user_id,
            "filename": req.filename,
            "chunk_index": idx,
            "text": item["chunk"],
            "page": item["page"],
            "embedding": vector.tolist(),
        }
        for idx, (item, vector) in enumerate(zip(all_chunks, vectors))
    ]

    try:
        db_service.delete_chunks(req.user_id, req.filename)  # replace any previous version
        db_service.insert_chunks(records)
        file_store.save(req.user_id, doc_id, req.ext, req.data, req.content_type)
        row = db_service.save_document(
            {
                "id": doc_id,
                "user_id": req.user_id,
                "filename": req.filename,
                "file_type": req.file_type,
                "storage_key": key,
                "size_bytes": len(req.data),
                "page_count": extraction.page_count,
                "chunks_count": len(records),
                "summary": summary["summary"] if summary else None,
                "suggested_questions": summary["questions"] if summary else [],
                "source_url": req.source_url,
                # Page text powers the in-app viewer for sources that aren't PDFs.
                "pages": None if req.file_type == "pdf" else pages,
            }
        )
    except Exception:
        # Don't leave half-written chunks behind a document that has no row.
        try:
            db_service.delete_chunks(req.user_id, req.filename)
        except Exception as cleanup_error:
            print(f"Warning: cleanup after failed ingest also failed: {cleanup_error}", file=sys.stderr)
        raise

    if existing:
        file_store.delete(req.user_id, existing)  # drop the superseded original file

    row = dict(row)
    row.pop("pages", None)
    row.pop("storage_key", None)
    row["warnings"] = extraction.warnings
    yield progress(100, "Done")
    return row
