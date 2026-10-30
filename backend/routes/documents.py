"""
Routes for document management: list, upload (file or web link), view, delete.

Uploads stream newline-delimited JSON so the browser can show real
progress while the document is read, embedded and summarized:

    {"type": "progress", "percent": 40, "message": "Embedding passages 32/80…"}
    {"type": "done", "document": {...}}          (or {"type": "error", "detail": "..."})
"""

import json
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from config import MAX_TEXT_CHARS, RATE_LIMIT_UPLOAD
from security import AuthUser, get_current_user, limited_user
from services import db_service, extractors, file_store, plans, url_fetch
from services.ingest import IngestRequest, ingest

router = APIRouter(prefix="/api", tags=["documents"])

upload_user = limited_user("upload", RATE_LIMIT_UPLOAD)


class UrlBody(BaseModel):
    url: str = Field(min_length=4, max_length=2000)


class TextBody(BaseModel):
    """Text the user copied from a page themselves (for sites that can't be fetched)."""

    text: str = Field(min_length=1, max_length=2_000_000)
    title: str = Field(default="", max_length=200)
    url: str | None = Field(default=None, max_length=2000)


class TagsBody(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=30)


MAX_TAGS = 10
MAX_TAG_CHARS = 30


def normalize_tags(raw: list[str]) -> list[str]:
    """Trim, drop a leading #, de-duplicate case-insensitively, and cap the count and length."""
    seen: dict[str, str] = {}
    for item in raw:
        tag = " ".join(item.replace(",", " ").split()).lstrip("#").strip()[:MAX_TAG_CHARS].strip()
        if tag:
            seen.setdefault(tag.lower(), tag)
    return list(seen.values())[:MAX_TAGS]


def safe_http_url(url: str | None) -> str | None:
    """Return *url* only when it is a plain http(s) address (it is shown as a link, so no javascript: etc.)."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url.strip()


def _mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.0f} MB"


def too_large(limits: plans.PlanLimits) -> HTTPException:
    """413 for a file over the plan's size limit; on Free the body says Pro would allow it."""
    pro_limit = plans.limits_for(plans.PRO).max_upload_bytes
    if plans.upgrade_hint(limits) and pro_limit > limits.max_upload_bytes:
        message = (
            f"This file is over the {_mb(limits.max_upload_bytes)} limit of the Free plan. "
            f"Upgrade to Pro to upload files up to {_mb(pro_limit)}."
        )
    else:
        message = f"File too large (max {_mb(limits.max_upload_bytes)})."
    return HTTPException(status_code=413, detail=plans.limit_error(limits, message, "file_too_large"))


def check_quota(user_id: str, filename: str, new_bytes: int, limits: plans.PlanLimits | None = None) -> None:
    """Reject the upload if it would push the user over their plan's library limits."""
    limits = limits or plans.plan_for_user(user_id)
    if new_bytes > limits.max_upload_bytes:
        raise too_large(limits)

    rows = db_service.list_documents(user_id)
    existing = next((r for r in rows if r["filename"] == filename), None)

    if existing is None and len(rows) >= limits.max_documents:
        raise HTTPException(
            status_code=403,
            detail=plans.limit_error(
                limits,
                f"Your library is full ({limits.max_documents} sources). Delete one to add another"
                + (", or upgrade to Pro for more room." if plans.upgrade_hint(limits) else "."),
                "library_full",
            ),
        )
    used = sum(int(r.get("size_bytes") or 0) for r in rows)
    used -= int((existing or {}).get("size_bytes") or 0)
    if used + new_bytes > limits.max_storage_bytes:
        raise HTTPException(
            status_code=403,
            detail=plans.limit_error(
                limits,
                f"This would exceed your {_mb(limits.max_storage_bytes)} storage limit. Delete something first"
                + (", or upgrade to Pro for more storage." if plans.upgrade_hint(limits) else "."),
                "storage_full",
            ),
        )


def _ndjson(event: dict) -> str:
    return json.dumps(event, default=str) + "\n"


def _ingest_response(req: IngestRequest) -> StreamingResponse:
    """Run the ingest pipeline and stream its progress as NDJSON."""

    def events() -> Iterator[str]:
        try:
            document = yield from _forward(ingest(req))
            yield _ndjson({"type": "done", "document": document})
        except HTTPException as exc:
            yield _ndjson({"type": "error", "detail": exc.detail})
        except Exception as exc:  # unexpected: report it, don't drop the connection
            yield _ndjson({"type": "error", "detail": f"Failed to process file: {exc}"})

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _forward(pipeline) -> Iterator[str]:
    """Re-emit a pipeline's progress events as NDJSON lines; return the pipeline's result."""
    while True:
        try:
            event = next(pipeline)
        except StopIteration as stop:
            return stop.value
        yield _ndjson(event)


@router.get("/documents")
def list_documents(user: AuthUser = Depends(get_current_user)):
    """Return the signed-in user's documents with metadata and summaries."""
    return {"documents": db_service.list_documents(user.id)}


# NOTE: deliberately a sync `def` — FastAPI runs it in a worker thread, so the
# blocking Gemini calls do not stall the event loop for other requests.
@router.post("/upload")
def upload_document(file: UploadFile = File(...), user: AuthUser = Depends(upload_user)):
    """Upload a PDF / DOCX / TXT / Markdown / image, then index it."""
    name, file_type, ext = extractors.classify_filename(file.filename)

    limits = plans.plan_for_user(user.id)
    data = file.file.read(limits.max_upload_bytes + 1)
    if len(data) > limits.max_upload_bytes:
        raise too_large(limits)
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")

    check_quota(user.id, name, len(data), limits)
    return _ingest_response(
        IngestRequest(
            user_id=user.id,
            filename=name,
            file_type=file_type,
            ext=ext,
            data=data,
            content_type=extractors.CONTENT_TYPES[ext],
            max_ocr_pages=limits.max_ocr_pages,
        )
    )


@router.post("/upload-url")
def upload_url(body: UrlBody, user: AuthUser = Depends(upload_user)):
    """Import a web page (or a linked PDF / text file) as a source."""
    limits = plans.plan_for_user(user.id)
    page = url_fetch.fetch_url(body.url)

    if page.kind == "pdf":
        name = url_fetch.display_name_for_url(page.final_url, "")
        req = IngestRequest(
            user_id=user.id,
            filename=name,
            file_type="pdf",
            ext=".pdf",
            data=page.data,
            content_type="application/pdf",
            source_url=page.final_url,
            max_ocr_pages=limits.max_ocr_pages,
        )
    else:
        if page.kind == "html":
            title, paragraphs = url_fetch.html_to_text(url_fetch.decode_html(page.data, page.content_type))
        else:
            title, paragraphs = "", extractors.split_paragraphs(extractors.decode_text(page.data))
        pages = extractors.paginate_paragraphs(paragraphs)
        if not pages:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No readable text found on that page. It probably builds its content with JavaScript or needs "
                    "a login. Open it in your browser and use \"Paste text\" (or the DocuQuery browser button) "
                    "to add what you can see, or save it as a PDF and upload that."
                ),
            )
        pages = extractors._limit_chars(pages, MAX_TEXT_CHARS)
        # Keep a plain-text copy (never the raw HTML, which could contain scripts).
        text_copy = "\n\n".join(pages).encode("utf-8")
        req = IngestRequest(
            user_id=user.id,
            filename=url_fetch.display_name_for_url(page.final_url, title),
            file_type="url",
            ext=".txt",
            data=text_copy,
            content_type="text/plain; charset=utf-8",
            source_url=page.final_url,
            pages=pages,
        )

    check_quota(user.id, req.filename, len(req.data), limits)
    return _ingest_response(req)


@router.post("/upload-text")
def upload_text(body: TextBody, user: AuthUser = Depends(upload_user)):
    """Add text the user pasted (or sent from their own browser) as a source."""
    pages = extractors.paginate_paragraphs(extractors.split_paragraphs(body.text))
    pages = extractors._limit_chars(pages, MAX_TEXT_CHARS)
    if not pages:
        raise HTTPException(status_code=400, detail="There is no text to add.")

    source_url = safe_http_url(body.url)
    title = re.sub(r"[\\/\x00-\x1f\x7f]+", " ", body.title)
    title = re.sub(r"\s+", " ", title).strip()[:90]
    if not title:
        title = (
            url_fetch.display_name_for_url(source_url, "")
            if source_url
            else f"Pasted text {datetime.now(timezone.utc):%Y-%m-%d %H:%M}"
        )
    elif source_url:
        title = url_fetch.display_name_for_url(source_url, title)

    text_copy = "\n\n".join(pages).encode("utf-8")
    req = IngestRequest(
        user_id=user.id,
        filename=title,
        file_type="url" if source_url else "txt",
        ext=".txt",
        data=text_copy,
        content_type="text/plain; charset=utf-8",
        source_url=source_url,
        pages=pages,
    )
    check_quota(user.id, req.filename, len(req.data))
    return _ingest_response(req)


@router.patch("/documents/{filename}/tags")
def set_tags(filename: str, body: TagsBody, user: AuthUser = Depends(get_current_user)):
    """Replace a document's tags (labels for organising a large library)."""
    tags = normalize_tags(body.tags)
    if not db_service.set_document_tags(user.id, filename, tags):
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"status": "success", "tags": tags}


@router.delete("/documents/{filename}")
def delete_document(filename: str, user: AuthUser = Depends(get_current_user)):
    """Delete a document, its cached chunks / vectors and its stored file."""
    doc = db_service.get_document(user.id, filename)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    deleted = db_service.delete_chunks(user.id, filename)
    db_service.delete_document_row(user.id, filename)
    db_service.delete_document_shares(user.id, filename)
    file_store.delete(user.id, doc)
    return {"status": "success", "deleted_count": deleted}


_INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}


@router.get("/documents/file/{filename}")
def get_document_file(filename: str, user: AuthUser = Depends(get_current_user)):
    """Serve the original uploaded file (for the viewer / download)."""
    doc = db_service.get_document(user.id, filename)
    if doc is None:
        raise HTTPException(status_code=404, detail="File not found.")

    data = file_store.load(user.id, doc)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found.")

    ext = "." + (doc.get("storage_key") or "").rsplit(".", 1)[-1].lower()
    media_type = extractors.CONTENT_TYPES.get(ext, "application/octet-stream")
    headers = {"X-Content-Type-Options": "nosniff"}
    if media_type.split(";")[0] not in _INLINE_TYPES:
        # Never let the browser render user-supplied documents inline.
        headers["Content-Disposition"] = "attachment"
    return Response(content=data, media_type=media_type, headers=headers)


@router.get("/document-pages/{filename}")
def get_document_pages(filename: str, user: AuthUser = Depends(get_current_user)):
    """Extracted text per page, for sources that are not PDFs (DOCX, TXT, web pages…)."""
    doc = db_service.get_document(user.id, filename, include_pages=True)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {
        "filename": doc["filename"],
        "file_type": doc["file_type"],
        "source_url": doc.get("source_url"),
        "pages": doc.get("pages") or [],
    }
