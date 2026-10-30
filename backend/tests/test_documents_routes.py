import pymupdf
import config
import pytest

import main
import routes.documents as documents_routes
from services import extractors, rate_limit, url_fetch
from tests.conftest import USER_A, USER_B, make_docx, make_pdf, parse_ndjson, words


def upload(client, name, data, mime="application/octet-stream"):
    return client.http.post("/api/upload", files={"file": (name, data, mime)})


def finished(response):
    """Parse an NDJSON upload stream; returns (events, final_event)."""
    assert response.status_code == 200, response.text
    events = parse_ndjson(response.text)
    return events, events[-1]


def scanned_pdf(pages=1) -> bytes:
    """A PDF whose pages contain only an image (no text layer), like a scan."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 80), False)
    pix.clear_with(180)
    png = pix.tobytes("png")
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 400, 400), stream=png)
    return doc.tobytes()


# ── supported file types ─────────────────────────────────────────────

def test_upload_txt_streams_progress_and_indexes_it(app_client, fake_db):
    r = upload(app_client, "notes.txt", f"Refund policy. {words(300)}".encode())
    events, last = finished(r)

    assert last["type"] == "done"
    assert [e["percent"] for e in events if e["type"] == "progress"] == sorted(
        e["percent"] for e in events if e["type"] == "progress"
    ), "progress must never go backwards"
    assert events[-2]["percent"] == 100

    doc = last["document"]
    assert doc["filename"] == "notes.txt" and doc["file_type"] == "txt"
    assert doc["summary"] == "A short summary." and doc["suggested_questions"] == ["Q one?", "Q two?"]
    assert "pages" not in doc and "storage_key" not in doc

    assert fake_db.chunks and all(c["user_id"] == USER_A for c in fake_db.chunks)
    assert len(fake_db.storage) == 1


def test_upload_docx(app_client, fake_db):
    _, last = finished(upload(app_client, "brief.docx", make_docx(["Quarterly results are up.", "Costs are down."])))
    assert last["document"]["file_type"] == "docx"
    assert any("Quarterly results" in c["text"] for c in fake_db.chunks)


def test_upload_markdown(app_client):
    _, last = finished(upload(app_client, "readme.md", b"# Title\n\nSome content here."))
    assert last["document"]["file_type"] == "md"


def test_upload_pdf_keeps_real_page_numbers(app_client, fake_db):
    _, last = finished(upload(app_client, "paper.pdf", make_pdf(["First page text.", "Second page text."])))
    assert last["document"]["page_count"] == 2
    assert {c["page"] for c in fake_db.chunks} == {1, 2}
    assert fake_db.get_document(USER_A, "paper.pdf", include_pages=True)["pages"] is None  # PDFs are viewed natively


def test_upload_image_is_read_with_ocr(app_client, fake_db, monkeypatch):
    monkeypatch.setattr(extractors, "ocr_image", lambda data, mime="image/png": "Invoice total: 42 EUR")
    _, last = finished(upload(app_client, "receipt.png", b"\x89PNG fake bytes"))
    assert last["document"]["file_type"] == "image"
    assert fake_db.chunks[0]["text"] == "Invoice total: 42 EUR"


def test_image_without_text_is_rejected(app_client, monkeypatch):
    monkeypatch.setattr(extractors, "ocr_image", lambda data, mime="image/png": "")
    _, last = finished(upload(app_client, "blank.png", b"\x89PNG"))
    assert last["type"] == "error" and "No readable text" in last["detail"]


# ── OCR for scanned PDFs ─────────────────────────────────────────────

def test_scanned_pdf_pages_are_read_with_ocr(app_client, fake_db, monkeypatch):
    monkeypatch.setattr(extractors, "ocr_image", lambda data, mime="image/png": "Scanned contract text")
    events, last = finished(upload(app_client, "scan.pdf", scanned_pdf(pages=2)))
    assert last["type"] == "done"
    assert any("scanned" in e.get("message", "").lower() for e in events if e["type"] == "progress")
    assert {c["page"] for c in fake_db.chunks} == {1, 2}
    assert all("Scanned contract text" in c["text"] for c in fake_db.chunks)


def test_ocr_page_limit_is_enforced_with_a_warning(app_client, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "MAX_OCR_PAGES", 2)  # the Free plan's cap
    monkeypatch.setattr(extractors, "ocr_image", lambda data, mime="image/png": calls.append(1) or "text")
    _, last = finished(upload(app_client, "big-scan.pdf", scanned_pdf(pages=4)))
    assert len(calls) == 2
    assert any("skipped" in w for w in last["document"]["warnings"])


def test_scan_with_failing_ocr_reports_why(app_client, monkeypatch):
    def failing(data, mime="image/png"):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(extractors, "ocr_image", failing)
    _, last = finished(upload(app_client, "scan.pdf", scanned_pdf()))
    assert last["type"] == "error" and "503" in last["detail"]


def test_mixed_pdf_only_ocrs_the_scanned_pages(app_client, monkeypatch):
    doc = pymupdf.open(stream=make_pdf(["Real text page with plenty of characters."]), filetype="pdf")
    doc.insert_pdf(pymupdf.open(stream=scanned_pdf(), filetype="pdf"))
    calls = []
    monkeypatch.setattr(extractors, "ocr_image", lambda data, mime="image/png": calls.append(1) or "ocr text")
    _, last = finished(upload(app_client, "mixed.pdf", doc.tobytes()))
    assert last["type"] == "done" and len(calls) == 1


# ── rejected uploads ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["malware.exe", "page.html", "archive.zip", "noextension"])
def test_unsupported_types_are_rejected(app_client, name):
    r = upload(app_client, name, b"data")
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]


def test_empty_file_is_rejected(app_client):
    assert upload(app_client, "empty.txt", b"").status_code == 400


def test_oversized_upload_is_rejected(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    assert upload(app_client, "big.txt", b"x" * 500).status_code == 413


def test_oversized_content_length_is_rejected_before_reading_the_body(app_client):
    r = app_client.http.post(
        "/api/upload",
        files={"file": ("a.txt", b"hi", "text/plain")},
        headers={"content-length": str(10_000_000_000)},
    )
    assert r.status_code == 413


def test_corrupt_pdf_gives_a_clear_error(app_client):
    _, last = finished(upload(app_client, "bad.pdf", b"this is not a pdf"))
    assert last["type"] == "error" and "could not be opened" in last["detail"]


def test_pdf_page_limit(app_client, monkeypatch):
    import services.ingest as ingest_module
    monkeypatch.setattr(ingest_module, "MAX_PAGES_PER_DOC", 2)
    _, last = finished(upload(app_client, "long.pdf", make_pdf(["a", "b", "c"])))
    assert last["type"] == "error" and "limit" in last["detail"]


def test_text_only_stopwords_file_with_no_text_is_rejected(app_client):
    _, last = finished(upload(app_client, "blank.txt", b"   \n\n   "))
    assert last["type"] == "error" and "No readable text" in last["detail"]


# ── quotas & rate limits ─────────────────────────────────────────────

def test_document_count_quota(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 2)
    for name in ("a.txt", "b.txt"):
        finished(upload(app_client, name, b"some text here"))
    r = upload(app_client, "c.txt", b"some text here")
    assert r.status_code == 403 and "library is full" in r.json()["detail"]["message"]


def test_replacing_a_document_does_not_count_against_the_quota(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 1)
    finished(upload(app_client, "a.txt", b"first version"))
    _, last = finished(upload(app_client, "a.txt", b"second version"))
    assert last["type"] == "done"


def test_storage_quota(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_STORAGE_BYTES_PER_USER", 100)
    finished(upload(app_client, "a.txt", b"x " * 40))
    r = upload(app_client, "b.txt", b"y " * 40)
    assert r.status_code == 403 and "storage limit" in r.json()["detail"]["message"]


def test_quotas_are_per_user(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 1)
    finished(upload(app_client, "a.txt", b"hello there"))
    app_client.as_user(USER_B)
    _, last = finished(upload(app_client, "a.txt", b"hello there"))
    assert last["type"] == "done"


def test_upload_rate_limit(app_client):
    rate_limit.reset()
    statuses = [upload(app_client, f"f{i}.txt", b"tiny text").status_code for i in range(22)]
    assert statuses[:20] == [200] * 20
    assert 429 in statuses[20:]


# ── replacing, listing, deleting ─────────────────────────────────────

def test_reuploading_replaces_chunks_and_the_old_file(app_client, fake_db):
    finished(upload(app_client, "a.txt", b"old content about cats"))
    old_keys = set(fake_db.storage)
    finished(upload(app_client, "a.txt", b"new content about dogs"))

    assert len(fake_db.documents) == 1
    assert all("dogs" in c["text"] for c in fake_db.chunks)
    assert not (old_keys & set(fake_db.storage)), "superseded original must be removed"
    assert len(fake_db.storage) == 1


def test_list_documents_returns_metadata(app_client):
    finished(upload(app_client, "a.txt", b"hello world"))
    docs = app_client.http.get("/api/documents").json()["documents"]
    assert [d["filename"] for d in docs] == ["a.txt"]
    assert {"id", "file_type", "size_bytes", "page_count", "chunks_count", "summary", "suggested_questions"} <= docs[0].keys()
    assert "pages" not in docs[0]


def test_delete_removes_everything(app_client, fake_db):
    finished(upload(app_client, "a.txt", b"hello world"))
    r = app_client.http.delete("/api/documents/a.txt")
    assert r.status_code == 200 and r.json()["deleted_count"] >= 1
    assert not fake_db.documents and not fake_db.chunks and not fake_db.storage


def test_delete_unknown_document_is_404(app_client):
    assert app_client.http.delete("/api/documents/ghost.txt").status_code == 404


def test_filenames_with_special_characters_round_trip(app_client):
    name = "Q3 report #2 (final) — v1.txt"
    finished(upload(app_client, name, b"numbers and more numbers"))
    from urllib.parse import quote
    assert app_client.http.get(f"/api/document-pages/{quote(name)}").status_code == 200
    assert app_client.http.delete(f"/api/documents/{quote(name)}").status_code == 200


# ── viewing files ────────────────────────────────────────────────────

def test_pdf_is_served_inline_with_nosniff(app_client):
    pdf = make_pdf(["hello"])
    finished(upload(app_client, "a.pdf", pdf))
    r = app_client.http.get("/api/documents/file/a.pdf")
    assert r.status_code == 200 and r.content == pdf
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-disposition" not in r.headers


def test_non_viewable_types_are_forced_to_download(app_client):
    finished(upload(app_client, "a.docx", make_docx(["hello"])))
    r = app_client.http.get("/api/documents/file/a.docx")
    assert r.headers["content-disposition"] == "attachment"


def test_file_is_restored_from_storage_when_the_local_cache_is_gone(app_client, fake_db, tmp_path):
    import shutil
    pdf = make_pdf(["hello"])
    finished(upload(app_client, "a.pdf", pdf))
    shutil.rmtree(tmp_path / "uploads")
    assert app_client.http.get("/api/documents/file/a.pdf").content == pdf


def test_pages_endpoint_returns_extracted_text(app_client):
    finished(upload(app_client, "a.txt", b"Alpha.\n\nBeta."))
    r = app_client.http.get("/api/document-pages/a.txt").json()
    assert r["file_type"] == "txt" and r["pages"] == ["Alpha.\n\nBeta."]


# ── isolation between users ──────────────────────────────────────────

def test_users_cannot_see_or_touch_each_others_documents(app_client):
    finished(upload(app_client, "private.txt", b"top secret plans"))

    app_client.as_user(USER_B)
    assert app_client.http.get("/api/documents").json()["documents"] == []
    assert app_client.http.get("/api/documents/file/private.txt").status_code == 404
    assert app_client.http.get("/api/document-pages/private.txt").status_code == 404
    assert app_client.http.delete("/api/documents/private.txt").status_code == 404

    app_client.as_user(USER_A)  # and A's document is untouched
    assert len(app_client.http.get("/api/documents").json()["documents"]) == 1


def test_same_filename_for_two_users_is_independent(app_client, fake_db):
    finished(upload(app_client, "a.txt", b"alice words"))
    app_client.as_user(USER_B)
    finished(upload(app_client, "a.txt", b"bob words"))
    assert {(c["user_id"], c["text"]) for c in fake_db.chunks} == {(USER_A, "alice words"), (USER_B, "bob words")}


def test_requests_without_a_session_are_rejected(app_client):
    main.app.dependency_overrides.clear()
    for method, path in [("get", "/api/documents"), ("get", "/api/conversations"), ("get", "/api/usage"),
                         ("post", "/api/query"), ("delete", "/api/documents/x.txt")]:
        assert getattr(app_client.http, method)(path).status_code == 401, path
    assert upload(app_client, "a.txt", b"hi").status_code == 401


# ── web pages ────────────────────────────────────────────────────────

HTML_PAGE = b"<html><head><title>Pricing</title></head><body><p>The pro plan costs 20 dollars.</p></body></html>"


def test_import_a_web_page(app_client, fake_db, monkeypatch):
    monkeypatch.setattr(
        url_fetch, "fetch_url",
        lambda url: url_fetch.FetchedPage("html", HTML_PAGE, "https://www.example.com/pricing", "text/html"),
    )
    r = app_client.http.post("/api/upload-url", json={"url": "https://www.example.com/pricing"})
    _, last = finished(r)
    doc = last["document"]
    assert doc["file_type"] == "url" and doc["filename"] == "Pricing (example.com)"
    assert doc["source_url"] == "https://www.example.com/pricing"
    assert any("pro plan" in c["text"] for c in fake_db.chunks)
    # Only extracted text is stored, never the raw HTML.
    assert b"<html" not in next(iter(fake_db.storage.values()))
    pages = app_client.http.get("/api/document-pages/Pricing%20(example.com)").json()
    assert pages["source_url"] == "https://www.example.com/pricing" and "pro plan" in pages["pages"][0]


def test_import_a_linked_pdf(app_client, monkeypatch):
    pdf = make_pdf(["Linked paper text"])
    monkeypatch.setattr(
        url_fetch, "fetch_url",
        lambda url: url_fetch.FetchedPage("pdf", pdf, "https://example.com/paper.pdf", "application/pdf"),
    )
    _, last = finished(app_client.http.post("/api/upload-url", json={"url": "https://example.com/paper.pdf"}))
    assert last["document"]["file_type"] == "pdf"


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://localhost/admin", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
     "http://10.0.0.1/"],
)
def test_importing_internal_addresses_is_blocked(app_client, url):
    r = app_client.http.post("/api/upload-url", json={"url": url})
    assert r.status_code == 400


def test_page_with_no_text_is_rejected(app_client, monkeypatch):
    monkeypatch.setattr(
        url_fetch, "fetch_url",
        lambda url: url_fetch.FetchedPage("html", b"<html><body><script>x()</script></body></html>", "https://example.com/", "text/html"),
    )
    r = app_client.http.post("/api/upload-url", json={"url": "https://example.com/"})
    assert r.status_code == 400 and "No readable text" in r.json()["detail"]


# ── usage ────────────────────────────────────────────────────────────

def test_usage_reports_quota(app_client):
    finished(upload(app_client, "a.txt", b"hello world"))
    usage = app_client.http.get("/api/usage").json()
    assert usage["documents"]["used"] == 1 and usage["documents"]["limit"] > 0
    assert usage["storage"]["used_bytes"] == len(b"hello world")
    assert usage["questions_today"]["used"] == 0
