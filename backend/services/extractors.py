"""
Turn uploaded files into plain text "pages".

Every supported source ends up as a list of page texts so the rest of the
pipeline (chunking → embedding → citations) is identical for all types:

  PDF    – real pages (scanned pages are read with the vision model, OCR)
  PPTX   – one page per slide (speaker notes included)
  DOCX   – paragraphs grouped into ~350-word pseudo-pages
  TXT/MD – paragraphs grouped into ~350-word pseudo-pages
  XLSX / CSV – rows turned into "column: value" lines, ~40 rows per page
  Images – a single page whose text comes from OCR
  URLs   – see services/url_fetch.py
"""

import csv
import datetime
import io
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from fastapi import HTTPException
from google.genai import types

from config import OCR_MODEL
from services import llm

# extension → logical file type
EXTENSION_TYPES: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}

CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

SUPPORTED_LABEL = "PDF, Word, PowerPoint, Excel, CSV, TXT, Markdown, PNG, JPG or WEBP"

WORDS_PER_PAGE = 350
MAX_IMAGE_BYTES = 15 * 1024 * 1024
_MAX_DOCX_XML_BYTES = 40 * 1024 * 1024
_MAX_OFFICE_UNZIPPED_BYTES = 250 * 1024 * 1024   # zip-bomb guard for pptx / xlsx
ROWS_PER_PAGE = 40
MAX_TABLE_ROWS = 50_000
_MAX_HEADER_COLUMNS = 30

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

OCR_PROMPT = (
    "Transcribe ALL the text visible in this image exactly as written, in reading order. "
    "Keep paragraph breaks. Render tables as plain text rows. "
    "Output only the transcribed text — no commentary. "
    "If the image contains no readable text, output nothing."
)


# ── File naming / classification ─────────────────────────────────────

def clean_display_name(filename: str | None) -> str:
    """Reduce a client-supplied filename to a safe base name (no directories)."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name


def classify_filename(filename: str | None) -> tuple[str, str, str]:
    """
    Validate an uploaded filename. Returns (display_name, file_type, extension)
    or raises HTTP 400 when the extension is not supported.
    """
    name = clean_display_name(filename)
    ext = os.path.splitext(name)[1].lower()
    if not name or name in (".", "..") or ext not in EXTENSION_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file. Please upload a {SUPPORTED_LABEL} file.")
    return name, EXTENSION_TYPES[ext], ext


# ── Pagination helpers ───────────────────────────────────────────────

def paginate_paragraphs(paragraphs: list[str], words_per_page: int = WORDS_PER_PAGE) -> list[str]:
    """
    Group paragraphs into pseudo-pages of roughly *words_per_page* words so
    plain-text sources get page-style citations. Oversized paragraphs are
    split on word boundaries.
    """
    pages: list[str] = []
    current: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal current, count
        if current:
            pages.append("\n\n".join(current))
        current, count = [], 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        words = paragraph.split()
        if len(words) > words_per_page * 1.5:
            flush()
            for start in range(0, len(words), words_per_page):
                pages.append(" ".join(words[start : start + words_per_page]))
            continue
        if count and count + len(words) > words_per_page:
            flush()
        current.append(paragraph)
        count += len(words)
    flush()
    return pages


def decode_text(data: bytes) -> str:
    """
    Decode user-supplied text bytes: UTF-16 only when a byte-order mark says
    so (guessing it would mangle Latin-1 text), otherwise UTF-8, then Latin-1.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def split_paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ── DOCX ─────────────────────────────────────────────────────────────

def extract_docx_paragraphs(data: bytes) -> list[str]:
    """Read paragraph text out of a .docx (a zip of XML) without extra dependencies."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError:
                raise HTTPException(status_code=400, detail="This DOCX file has no readable document body.")
            if info.file_size > _MAX_DOCX_XML_BYTES:
                raise HTTPException(status_code=413, detail="This DOCX file is too large to process.")
            xml_bytes = archive.read(info)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="This file is not a valid DOCX document.")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="This DOCX file could not be parsed.")

    paragraphs: list[str] = []
    for para in root.iter(f"{_W}p"):
        parts: list[str] = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


# ── Dispatch for text-like sources ───────────────────────────────────

def extract_text_pages(data: bytes, file_type: str, max_chars: int) -> list[str]:
    """Extract pseudo-pages from DOCX / TXT / Markdown bytes."""
    if file_type == "pptx":
        return _limit_chars(extract_pptx_pages(data), max_chars)
    if file_type == "xlsx":
        return _limit_chars(extract_xlsx_pages(data), max_chars)
    if file_type == "csv":
        return _limit_chars(extract_csv_pages(data), max_chars)

    if file_type == "docx":
        paragraphs = extract_docx_paragraphs(data)
    elif file_type in ("txt", "md"):
        paragraphs = split_paragraphs(decode_text(data))
    else:
        raise ValueError(f"extract_text_pages does not handle '{file_type}'")

    pages = paginate_paragraphs(paragraphs)
    return _limit_chars(pages, max_chars)


def _limit_chars(pages: list[str], max_chars: int) -> list[str]:
    """Trim a page list so its total size stays under *max_chars*."""
    kept: list[str] = []
    total = 0
    for page in pages:
        if total + len(page) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                kept.append(page[:remaining])
            break
        kept.append(page)
        total += len(page)
    return kept


# ── OCR (vision model) ───────────────────────────────────────────────

def ocr_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """Read the text out of an image with the vision model."""
    contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), OCR_PROMPT]
    return llm.generate_text(contents, model=OCR_MODEL, max_output_tokens=8192)


def image_mime_type(ext: str) -> str:
    return CONTENT_TYPES.get(ext, "image/png").split(";")[0]


# ── PowerPoint ───────────────────────────────────────────────────────

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_MAX_PART_BYTES = 20 * 1024 * 1024


def _open_office_zip(data: bytes, label: str) -> zipfile.ZipFile:
    """Open an Office file (a zip) and refuse zip bombs."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail=f"This file is not a valid {label} document.")
    if sum(info.file_size for info in archive.infolist()) > _MAX_OFFICE_UNZIPPED_BYTES:
        raise HTTPException(status_code=413, detail=f"This {label} file is too large to process.")
    return archive


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_PART_BYTES:
        raise HTTPException(status_code=413, detail="This file contains a section that is too large to process.")
    try:
        return ET.fromstring(archive.read(info))
    except ET.ParseError:
        return None


def _relationships(archive: zipfile.ZipFile, rels_name: str, base_dir: str) -> dict[str, tuple[str, str]]:
    """Map relationship id -> (type, resolved part path) from a .rels file."""
    root = _read_xml(archive, rels_name)
    result: dict[str, tuple[str, str]] = {}
    if root is None:
        return result
    for rel in root.iter(f"{_PKG_REL}Relationship"):
        target = rel.get("Target", "")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base_dir, target))
        result[rel.get("Id", "")] = (rel.get("Type", ""), path)
    return result


def _drawingml_text(root: ET.Element) -> list[str]:
    """Paragraph texts of a slide / notes part (slide-number fields are skipped)."""
    paragraphs: list[str] = []
    for para in root.iter(f"{_A}p"):
        parts: list[str] = []
        for child in para:
            if child.tag == f"{_A}r":
                parts.extend(t.text or "" for t in child.iter(f"{_A}t"))
            elif child.tag == f"{_A}br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _slide_paths(archive: zipfile.ZipFile) -> list[str]:
    """Slide parts in presentation order (falls back to file-name order)."""
    presentation = _read_xml(archive, "ppt/presentation.xml")
    rels = _relationships(archive, "ppt/_rels/presentation.xml.rels", "ppt")
    names = set(archive.namelist())
    ordered: list[str] = []
    if presentation is not None:
        for node in presentation.iter():
            if node.tag.endswith("}sldId"):
                target = rels.get(node.get(f"{_R}id", ""))
                if target and target[1] in names:
                    ordered.append(target[1])
    if ordered:
        return ordered
    numbered = [
        (int(m.group(1)), name)
        for name in names
        if (m := re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name))
    ]
    return [name for _, name in sorted(numbered)]


def extract_pptx_pages(data: bytes) -> list[str]:
    """One page of text per slide, with the speaker notes appended."""
    archive = _open_office_zip(data, "PowerPoint")
    paths = _slide_paths(archive)
    if not paths:
        raise HTTPException(status_code=400, detail="This PowerPoint file has no readable slides.")

    pages: list[str] = []
    for path in paths:
        root = _read_xml(archive, path)
        paragraphs = _drawingml_text(root) if root is not None else []
        text = "\n".join(paragraphs)

        folder = posixpath.dirname(path)
        slide_rels = _relationships(archive, f"{folder}/_rels/{posixpath.basename(path)}.rels", folder)
        for rel_type, target in slide_rels.values():
            if rel_type.endswith("/notesSlide"):
                notes_root = _read_xml(archive, target)
                notes = _drawingml_text(notes_root) if notes_root is not None else []
                if notes:
                    text = (text + "\n\n" if text else "") + "Speaker notes: " + " ".join(notes)
                break
        pages.append(text)
    return pages


# ── Tables: CSV and Excel ────────────────────────────────────────────

def _clean_cell(value: object) -> str:
    """One spreadsheet / CSV cell as short, single-line text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime.datetime):
        return value.date().isoformat() if value.time() == datetime.time(0) else value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def rows_to_pages(rows, sheet_name: str | None = None, rows_per_page: int = ROWS_PER_PAGE) -> list[str]:
    """
    Turn table rows into pages of "Row n: column: value; ..." lines. The first
    non-empty row is the header and is repeated at the top of every page, so
    each page (and each search hit) still says what the columns mean.
    """
    header: list[str] | None = None
    prefix = ""
    pages: list[str] = []
    lines: list[str] = []
    data_rows = 0

    for row_number, raw in enumerate(rows, start=1):
        cells = [_clean_cell(c) for c in raw]
        if not any(cells):
            continue
        if header is None:
            header = [h or f"Column {i + 1}" for i, h in enumerate(cells)]
            shown = ", ".join(header[:_MAX_HEADER_COLUMNS]) + (" ..." if len(header) > _MAX_HEADER_COLUMNS else "")
            prefix = (f"Sheet: {sheet_name}\n" if sheet_name else "") + f"Columns: {shown}\n"
            continue

        pairs = []
        for i, value in enumerate(cells):
            if value:
                name = header[i] if i < len(header) else f"Column {i + 1}"
                pairs.append(f"{name}: {value}")
        lines.append(f"Row {row_number}: " + "; ".join(pairs))
        data_rows += 1
        if len(lines) >= rows_per_page:
            pages.append(prefix + "\n".join(lines))
            lines = []
        if data_rows >= MAX_TABLE_ROWS:
            break

    if lines:
        pages.append(prefix + "\n".join(lines))
    elif header is not None and not pages:
        pages.append(prefix.rstrip("\n"))  # a header with no data rows still says what the sheet is
    return pages


def extract_csv_pages(data: bytes) -> list[str]:
    text = decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    csv.field_size_limit(1_000_000)
    try:
        return rows_to_pages(csv.reader(io.StringIO(text, newline=""), dialect))
    except csv.Error:
        raise HTTPException(status_code=400, detail="This CSV file could not be parsed.")


def extract_xlsx_pages(data: bytes) -> list[str]:
    """Rows of every visible sheet as text pages (formulas use their last saved value)."""
    _open_office_zip(data, "Excel").close()
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="This Excel file could not be read.")

    pages: list[str] = []
    try:
        for sheet in workbook.worksheets:
            if getattr(sheet, "sheet_state", "visible") != "visible":
                continue
            try:
                pages.extend(rows_to_pages(sheet.iter_rows(values_only=True), sheet_name=sheet.title))
            except Exception:
                continue  # one unreadable sheet shouldn't lose the rest of the workbook
    finally:
        workbook.close()
    return pages
