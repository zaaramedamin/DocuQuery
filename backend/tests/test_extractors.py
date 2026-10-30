import pytest
from fastapi import HTTPException

from services import extractors
from services.summarizer import normalize_summary
from tests.conftest import make_docx, words


# ── filename validation ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "name, expected_type",
    [
        ("report.pdf", "pdf"),
        ("Notes.DOCX", "docx"),
        ("readme.md", "md"),
        ("notes.markdown", "md"),
        ("plain.txt", "txt"),
        ("scan.PNG", "image"),
        ("photo.jpeg", "image"),
        ("pic.webp", "image"),
    ],
)
def test_classify_accepts_supported_types(name, expected_type):
    clean, file_type, ext = extractors.classify_filename(name)
    assert clean == name and file_type == expected_type and ext == name[name.rindex("."):].lower()


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "image.svg", "noextension", "", None, ".pdf.exe", ".."])
def test_classify_rejects_unsupported(name):
    with pytest.raises(HTTPException) as exc:
        extractors.classify_filename(name)
    assert exc.value.status_code == 400


def test_classify_strips_directories():
    clean, _, _ = extractors.classify_filename("..\\..\\secret\\evil.pdf")
    assert clean == "evil.pdf"
    clean, _, _ = extractors.classify_filename("/etc/passwd.txt")
    assert clean == "passwd.txt"


# ── pagination ───────────────────────────────────────────────────────

def test_paginate_groups_paragraphs_into_pages():
    paragraphs = [words(200, "a"), words(200, "b"), words(200, "c")]
    pages = extractors.paginate_paragraphs(paragraphs, words_per_page=350)
    assert len(pages) == 3  # 200 + 200 > 350, so each paragraph starts a new page


def test_paginate_packs_small_paragraphs_together():
    paragraphs = [words(50, f"p{i}_") for i in range(6)]
    pages = extractors.paginate_paragraphs(paragraphs, words_per_page=150)
    assert len(pages) == 2
    assert all(len(p.split()) <= 150 for p in pages)


def test_paginate_splits_oversized_paragraphs():
    pages = extractors.paginate_paragraphs([words(1000)], words_per_page=300)
    assert len(pages) == 4
    assert sum(len(p.split()) for p in pages) == 1000


def test_paginate_ignores_blank_paragraphs():
    assert extractors.paginate_paragraphs(["", "   ", "real text"]) == ["real text"]


# ── text decoding ────────────────────────────────────────────────────

def test_decode_text_handles_utf8_bom_and_unicode():
    assert extractors.decode_text("﻿café — ملف".encode("utf-8")) == "café — ملف"


def test_decode_text_falls_back_to_latin1():
    assert extractors.decode_text("café".encode("latin-1")) == "café"


def test_text_pages_from_markdown_and_txt():
    data = b"# Title\n\nFirst paragraph.\n\nSecond paragraph."
    pages = extractors.extract_text_pages(data, "md", max_chars=10_000)
    assert pages == ["# Title\n\nFirst paragraph.\n\nSecond paragraph."]


def test_text_pages_respect_character_cap():
    data = ("word " * 5000).encode()
    pages = extractors.extract_text_pages(data, "txt", max_chars=3000)
    assert sum(len(p) for p in pages) <= 3000


# ── DOCX ─────────────────────────────────────────────────────────────

def test_docx_paragraphs_are_extracted_in_order():
    data = make_docx(["Heading one", "Body & <special> text", "", "Last line"])
    assert extractors.extract_docx_paragraphs(data) == ["Heading one", "Body & <special> text", "Last line"]


def test_docx_rejects_non_zip_data():
    with pytest.raises(HTTPException) as exc:
        extractors.extract_docx_paragraphs(b"this is not a zip file")
    assert exc.value.status_code == 400


def test_docx_rejects_archive_without_document_body():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.txt", "x")
    with pytest.raises(HTTPException):
        extractors.extract_docx_paragraphs(buffer.getvalue())


def test_docx_text_pages_end_to_end():
    pages = extractors.extract_text_pages(make_docx(["Alpha beta.", "Gamma delta."]), "docx", 10_000)
    assert pages == ["Alpha beta.\n\nGamma delta."]


# ── summary validation ───────────────────────────────────────────────

def test_normalize_summary_accepts_good_payload():
    result = normalize_summary({"summary": "  Short.  ", "questions": ["Q1?", " Q2? ", "", 5, "Q3?", "Q4?", "Q5?"]})
    assert result == {"summary": "Short.", "questions": ["Q1?", "Q2?", "Q3?", "Q4?"]}


@pytest.mark.parametrize("bad", [None, [], "text", {"summary": ""}, {"summary": 3}, {"questions": ["x"]}])
def test_normalize_summary_rejects_bad_payloads(bad):
    assert normalize_summary(bad) is None


def test_normalize_summary_tolerates_missing_questions():
    assert normalize_summary({"summary": "ok"}) == {"summary": "ok", "questions": []}


def test_decode_text_reads_utf16_with_bom():
    assert extractors.decode_text("hello wörld".encode("utf-16")) == "hello wörld"
