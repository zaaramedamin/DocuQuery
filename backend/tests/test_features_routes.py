"""Routes added in the second round: new file types, pasted text, tags, chat search, sharing, password reset."""

import types
import config

import pytest

import main
import routes.auth as auth_routes
import routes.documents as documents_routes
import routes.shares as shares_routes
import security
from services import rate_limit
from tests.conftest import (
    USER_A,
    USER_B,
    make_docx,
    make_pdf,
    make_pptx,
    make_xlsx,
    parse_ndjson,
    parse_sse,
)


def upload(client, name, data, mime="application/octet-stream"):
    return client.http.post("/api/upload", files={"file": (name, data, mime)})


def done(response):
    assert response.status_code == 200, response.text
    last = parse_ndjson(response.text)[-1]
    assert last["type"] == "done", last
    return last["document"]


def ask(client, question, **extra):
    return client.http.post("/api/query", json={"question": question, **extra})


# ── PowerPoint / Excel / CSV uploads ─────────────────────────────────

def test_upload_powerpoint_one_page_per_slide(app_client, fake_db):
    doc = done(upload(app_client, "deck.pptx", make_pptx(["Q3 results\nRevenue up 12%", "Roadmap\nLaunch in March"])))
    assert doc["file_type"] == "pptx" and doc["page_count"] == 2
    assert {c["page"] for c in fake_db.chunks} == {1, 2}  # citations point at slide numbers


def test_upload_excel(app_client, fake_db):
    doc = done(upload(app_client, "budget.xlsx", make_xlsx({"Budget": [["Team", "Cost"], ["Sales", 5000], ["Eng", 9000]]})))
    assert doc["file_type"] == "xlsx"
    assert any("Team: Eng; Cost: 9000" in c["text"] for c in fake_db.chunks)


def test_upload_csv(app_client, fake_db):
    doc = done(upload(app_client, "people.csv", b"name,city\nAlice,Paris\nBob,Cairo\n"))
    assert doc["file_type"] == "csv"
    assert any("name: Bob; city: Cairo" in c["text"] for c in fake_db.chunks)


def test_new_types_are_served_as_downloads_not_inline(app_client):
    done(upload(app_client, "deck.pptx", make_pptx(["hello"])))
    r = app_client.http.get("/api/documents/file/deck.pptx")
    assert r.headers["content-disposition"] == "attachment" and r.headers["x-content-type-options"] == "nosniff"


def test_corrupt_office_files_give_clear_errors(app_client):
    for name in ("bad.pptx", "bad.xlsx"):
        last = parse_ndjson(upload(app_client, name, b"definitely not an office file").text)[-1]
        assert last["type"] == "error" and last["detail"]


def test_pages_endpoint_works_for_spreadsheets(app_client):
    done(upload(app_client, "t.csv", b"a,b\n1,2\n"))
    pages = app_client.http.get("/api/document-pages/t.csv").json()["pages"]
    assert pages[0].startswith("Columns: a, b")


# ── pasted text (sites that can't be fetched) ────────────────────────

def test_paste_text_creates_a_source(app_client, fake_db):
    r = app_client.http.post("/api/upload-text", json={"title": "Pricing article", "text": "The pro plan costs 20 dollars.\n\nThe team plan costs 50."})
    doc = done(r)
    assert doc["filename"] == "Pricing article" and doc["file_type"] == "txt" and doc["source_url"] is None
    assert any("pro plan" in c["text"] for c in fake_db.chunks)


def test_paste_text_from_a_page_keeps_its_link_and_names_it(app_client):
    r = app_client.http.post(
        "/api/upload-text",
        json={"title": "A long read", "text": "Some article body text here.", "url": "https://www.medium.com/p/abc"},
    )
    doc = done(r)
    assert doc["file_type"] == "url" and doc["source_url"] == "https://www.medium.com/p/abc"
    assert doc["filename"] == "A long read (medium.com)"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>", "ftp://x.com/a", "not a url"])
def test_pasted_text_never_stores_a_dangerous_link(app_client, url):
    doc = done(app_client.http.post("/api/upload-text", json={"title": "x", "text": "some text here", "url": url}))
    assert doc["source_url"] is None and doc["file_type"] == "txt"


def test_paste_text_without_a_title_gets_a_default_name(app_client):
    doc = done(app_client.http.post("/api/upload-text", json={"text": "just some words"}))
    assert doc["filename"].startswith("Pasted text ")


def test_paste_text_rejects_empty_and_whitespace(app_client):
    assert app_client.http.post("/api/upload-text", json={"text": ""}).status_code == 422
    assert app_client.http.post("/api/upload-text", json={"text": "   \n\n  "}).status_code == 400


def test_paste_text_title_cannot_contain_path_separators(app_client):
    doc = done(app_client.http.post("/api/upload-text", json={"title": "a/b\\c", "text": "words words"}))
    assert "/" not in doc["filename"] and "\\" not in doc["filename"]


def test_paste_text_respects_quotas(app_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 1)
    done(app_client.http.post("/api/upload-text", json={"title": "one", "text": "first text"}))
    r = app_client.http.post("/api/upload-text", json={"title": "two", "text": "second text"})
    assert r.status_code == 403


# ── tags ─────────────────────────────────────────────────────────────

def test_set_and_list_tags(app_client):
    done(upload(app_client, "a.txt", b"alpha text"))
    r = app_client.http.patch("/api/documents/a.txt/tags", json={"tags": ["Legal", "2025", "legal", " #Contracts "]})
    assert r.json()["tags"] == ["Legal", "2025", "Contracts"]  # trimmed, # removed, case-insensitive de-dupe
    assert app_client.http.get("/api/documents").json()["documents"][0]["tags"] == ["Legal", "2025", "Contracts"]


def test_tags_are_capped(app_client):
    done(upload(app_client, "a.txt", b"alpha text"))
    tags = app_client.http.patch("/api/documents/a.txt/tags", json={"tags": [f"t{i}" for i in range(25)] + ["x" * 80]}).json()["tags"]
    assert len(tags) == 10 and all(len(t) <= 30 for t in tags)


def test_tags_survive_reuploading_the_same_file(app_client):
    done(upload(app_client, "a.txt", b"version one"))
    app_client.http.patch("/api/documents/a.txt/tags", json={"tags": ["keep"]})
    done(upload(app_client, "a.txt", b"version two"))
    assert app_client.http.get("/api/documents").json()["documents"][0]["tags"] == ["keep"]


def test_tags_on_unknown_or_foreign_documents_are_404(app_client):
    done(upload(app_client, "a.txt", b"alpha text"))
    assert app_client.http.patch("/api/documents/ghost.txt/tags", json={"tags": ["x"]}).status_code == 404
    app_client.as_user(USER_B)
    assert app_client.http.patch("/api/documents/a.txt/tags", json={"tags": ["hacked"]}).status_code == 404
    app_client.as_user(USER_A)
    assert app_client.http.get("/api/documents").json()["documents"][0]["tags"] == []


def test_asking_within_a_tag_searches_only_those_sources(app_client, fake_gemini):
    for name, text in [("cats.txt", "cats purr softly"), ("dogs.txt", "dogs bark loudly"), ("fish.txt", "fish swim quietly")]:
        done(upload(app_client, name, text.encode()))
    app_client.http.patch("/api/documents/cats.txt/tags", json={"tags": ["pets"]})
    app_client.http.patch("/api/documents/dogs.txt/tags", json={"tags": ["Pets"]})

    events = parse_sse(ask(app_client, "what do they do?", tag="PETS").text)
    assert {s["filename"] for s in events[1]["sources"]} == {"cats.txt", "dogs.txt"}
    assert "=== Document" not in fake_gemini.prompts[-1], "a tag scope is a normal search, not compare mode"


def test_unknown_tag_is_a_clear_404(app_client):
    done(upload(app_client, "a.txt", b"alpha text"))
    r = ask(app_client, "q?", tag="nothing")
    assert r.status_code == 404 and "nothing" in r.json()["detail"]


def test_explicit_documents_win_over_a_tag(app_client):
    for name, text in [("cats.txt", "cats purr"), ("dogs.txt", "dogs bark")]:
        done(upload(app_client, name, text.encode()))
    app_client.http.patch("/api/documents/cats.txt/tags", json={"tags": ["pets"]})
    events = parse_sse(ask(app_client, "bark?", filenames=["dogs.txt"], tag="pets").text)
    assert {s["filename"] for s in events[1]["sources"]} == {"dogs.txt"}


# ── searching past chats ─────────────────────────────────────────────

def chat(client, question):
    done(client.http.post("/api/upload", files={"file": ("a.txt", b"refund shipping policy", "text/plain")}))
    return parse_sse(ask(client, question).text)[0]["conversation_id"]


def test_search_finds_chats_by_message_text(app_client):
    refunds = chat(app_client, "How do refunds work?")
    chat(app_client, "What about shipping times?")
    found = app_client.http.get("/api/conversations/search", params={"q": "REFUND"}).json()["results"]
    assert [r["id"] for r in found] == [refunds]
    assert "refund" in found[0]["snippet"].lower()


def test_search_finds_chats_by_title_and_in_assistant_answers(app_client, fake_gemini):
    fake_gemini.stream_tokens = ["The warranty ", "lasts two years."]
    cid = chat(app_client, "tell me more")
    assert [r["id"] for r in app_client.http.get("/api/conversations/search", params={"q": "warranty"}).json()["results"]] == [cid]
    assert [r["id"] for r in app_client.http.get("/api/conversations/search", params={"q": "tell me"}).json()["results"]] == [cid]


def test_search_is_private_to_the_user(app_client):
    chat(app_client, "my secret project codename")
    app_client.as_user(USER_B)
    assert app_client.http.get("/api/conversations/search", params={"q": "secret"}).json()["results"] == []


@pytest.mark.parametrize("q", ["a", " ", ""])
def test_search_requires_a_real_query(app_client, q):
    assert app_client.http.get("/api/conversations/search", params={"q": q}).status_code in (400, 422)


def test_search_route_is_not_mistaken_for_a_conversation_id(app_client):
    r = app_client.http.get("/api/conversations/search", params={"q": "xx"})
    assert r.status_code == 200 and r.json() == {"results": []}


def test_snippets_are_centered_on_the_match():
    from routes.conversations import make_snippet

    text = "word " * 40 + "NEEDLE" + " word" * 40
    snippet = make_snippet(text, "needle")
    assert "NEEDLE" in snippet and snippet.startswith("…") and snippet.endswith("…") and len(snippet) < 200
    assert make_snippet("short text", "zzz") == "short text"


# ── sharing ──────────────────────────────────────────────────────────

def make_share(client, kind, ref):
    r = client.http.post("/api/shares", json={"kind": kind, "ref": ref})
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_a_share_twice_returns_the_same_link(app_client):
    cid = chat(app_client, "refund?")
    first, second = make_share(app_client, "conversation", cid), make_share(app_client, "conversation", cid)
    assert first["token"] == second["token"] and len(first["token"]) >= 30
    assert len(app_client.http.get("/api/shares").json()["shares"]) == 1


def test_tokens_are_unique_and_unguessable(app_client):
    for i in range(3):
        done(upload(app_client, f"f{i}.txt", b"some text"))
    tokens = {make_share(app_client, "document", f"f{i}.txt")["token"] for i in range(3)}
    assert len(tokens) == 3


def test_anyone_can_read_a_shared_chat_without_signing_in(app_client):
    cid = chat(app_client, "How do refunds work?")
    token = make_share(app_client, "conversation", cid)["token"]

    main.app.dependency_overrides.clear()  # an anonymous visitor
    data = app_client.http.get(f"/api/shared/{token}").json()
    assert data["kind"] == "conversation" and data["title"] == "How do refunds work?"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][1]["sources"] == [{"filename": "a.txt", "page": 1}]


def test_shared_chat_does_not_leak_private_data(app_client):
    cid = chat(app_client, "refund?")
    token = make_share(app_client, "conversation", cid)["token"]
    body = app_client.http.get(f"/api/shared/{token}").text
    assert USER_A not in body and "user@example.com" not in body
    assert "refund shipping policy" not in body, "quoted passages from the owner's documents must not be exposed"


def test_shared_document_preview_is_minimal(app_client):
    done(upload(app_client, "plan.txt", b"confidential plan details"))
    token = make_share(app_client, "document", "plan.txt")["token"]
    main.app.dependency_overrides.clear()
    data = app_client.http.get(f"/api/shared/{token}").json()
    assert set(data) == {"kind", "filename", "file_type", "page_count", "size_bytes", "summary"}


@pytest.mark.parametrize("token", ["nope", "a" * 40, "bad$token!with*chars" * 2, "x" * 200])
def test_unknown_and_malformed_links_are_404(app_client, token):
    main.app.dependency_overrides.clear()
    r = app_client.http.get(f"/api/shared/{token}")
    assert r.status_code == 404 and "doesn't exist" in r.json()["detail"]


def test_revoking_a_link_turns_it_off(app_client):
    cid = chat(app_client, "refund?")
    share = make_share(app_client, "conversation", cid)
    assert app_client.http.delete(f"/api/shares/{share['id']}").status_code == 200
    assert app_client.http.get(f"/api/shared/{share['token']}").status_code == 404
    new = make_share(app_client, "conversation", cid)
    assert new["token"] != share["token"], "a re-created link must be a new secret"


def test_deleting_the_chat_or_the_source_kills_its_link(app_client):
    cid = chat(app_client, "refund?")
    chat_link = make_share(app_client, "conversation", cid)["token"]
    doc_link = make_share(app_client, "document", "a.txt")["token"]
    app_client.http.delete(f"/api/conversations/{cid}")
    app_client.http.delete("/api/documents/a.txt")
    assert app_client.http.get(f"/api/shared/{chat_link}").status_code == 404
    assert app_client.http.get(f"/api/shared/{doc_link}").status_code == 404
    assert app_client.http.get("/api/shares").json()["shares"] == []


def test_cannot_share_things_you_dont_own(app_client):
    cid = chat(app_client, "refund?")
    app_client.as_user(USER_B)
    assert app_client.http.post("/api/shares", json={"kind": "conversation", "ref": cid}).status_code == 404
    assert app_client.http.post("/api/shares", json={"kind": "document", "ref": "a.txt"}).status_code == 404
    assert app_client.http.post("/api/shares", json={"kind": "conversation", "ref": "not-a-uuid"}).status_code == 404


def test_cannot_revoke_someone_elses_link(app_client):
    cid = chat(app_client, "refund?")
    share = make_share(app_client, "conversation", cid)
    app_client.as_user(USER_B)
    assert app_client.http.delete(f"/api/shares/{share['id']}").status_code == 404
    assert app_client.http.get("/api/shares").json()["shares"] == []
    assert app_client.http.get(f"/api/shared/{share['token']}").status_code == 200


def test_share_creation_is_rate_limited(app_client):
    done(upload(app_client, "a.txt", b"some text"))
    codes = [app_client.http.post("/api/shares", json={"kind": "document", "ref": "a.txt"}).status_code for _ in range(62)]
    assert codes[0] == 200 and 429 in codes


def test_public_link_lookups_are_rate_limited_per_ip(app_client):
    main.app.dependency_overrides.clear()
    codes = [app_client.http.get("/api/shared/" + "a" * 30).status_code for _ in range(65)]
    assert codes[0] == 404 and 429 in codes


# ── accepting a shared source ────────────────────────────────────────

def test_recipient_can_add_a_copy_to_their_library(app_client, fake_db):
    pdf = make_pdf(["Quarterly numbers are strong."])
    done(upload(app_client, "report.pdf", pdf))
    app_client.http.patch("/api/documents/report.pdf/tags", json={"tags": ["owner-only"]})
    token = make_share(app_client, "document", "report.pdf")["token"]

    app_client.as_user(USER_B)
    r = app_client.http.post(f"/api/shared/{token}/accept")
    assert r.status_code == 200
    copy = r.json()["document"]
    assert copy["filename"] == "report.pdf" and copy["chunks_count"] > 0 and copy["tags"] == []

    # Bob owns an independent copy: chunks, file and metadata.
    assert [c["filename"] for c in fake_db.chunks if c["user_id"] == USER_B]
    assert app_client.http.get("/api/documents/file/report.pdf").content == pdf
    events = parse_sse(ask(app_client, "quarterly numbers").text)
    assert events[1]["sources"][0]["filename"] == "report.pdf"


def test_the_copy_survives_the_owner_deleting_theirs(app_client):
    done(upload(app_client, "report.txt", b"important facts inside"))
    token = make_share(app_client, "document", "report.txt")["token"]
    app_client.as_user(USER_B)
    app_client.http.post(f"/api/shared/{token}/accept")
    app_client.as_user(USER_A)
    app_client.http.delete("/api/documents/report.txt")
    app_client.as_user(USER_B)
    assert [d["filename"] for d in app_client.http.get("/api/documents").json()["documents"]] == ["report.txt"]
    assert app_client.http.get("/api/document-pages/report.txt").json()["pages"] == ["important facts inside"]


def test_name_clashes_get_a_numbered_name(app_client):
    done(upload(app_client, "notes.txt", b"alice notes"))
    token = make_share(app_client, "document", "notes.txt")["token"]
    app_client.as_user(USER_B)
    done(upload(app_client, "notes.txt", b"bob's own notes"))
    r = app_client.http.post(f"/api/shared/{token}/accept")
    assert r.json()["document"]["filename"] == "notes (2).txt"
    assert len(app_client.http.get("/api/documents").json()["documents"]) == 2


def test_cannot_accept_your_own_share_or_a_chat_link(app_client):
    done(upload(app_client, "a.txt", b"some text"))
    doc_token = make_share(app_client, "document", "a.txt")["token"]
    assert app_client.http.post(f"/api/shared/{doc_token}/accept").status_code == 400
    cid = chat(app_client, "refund?")
    chat_token = make_share(app_client, "conversation", cid)["token"]
    app_client.as_user(USER_B)
    assert app_client.http.post(f"/api/shared/{chat_token}/accept").status_code == 400


def test_accepting_respects_the_recipients_quota(app_client, monkeypatch):
    done(upload(app_client, "a.txt", b"some text"))
    token = make_share(app_client, "document", "a.txt")["token"]
    app_client.as_user(USER_B)
    done(upload(app_client, "mine.txt", b"my own text"))
    monkeypatch.setattr(config, "MAX_DOCS_PER_USER", 1)
    assert app_client.http.post(f"/api/shared/{token}/accept").status_code == 403


def test_accepting_requires_sign_in_and_a_live_link(app_client):
    done(upload(app_client, "a.txt", b"some text"))
    share = make_share(app_client, "document", "a.txt")
    main.app.dependency_overrides.clear()
    assert app_client.http.post(f"/api/shared/{share['token']}/accept").status_code == 401
    app_client.as_user(USER_B)
    app_client.as_user(USER_A)
    app_client.http.delete(f"/api/shares/{share['id']}")
    app_client.as_user(USER_B)
    assert app_client.http.post(f"/api/shared/{share['token']}/accept").status_code == 404


# ── forgot / reset password ──────────────────────────────────────────

class FakeAuthAdmin:
    def __init__(self):
        self.reset_calls = []
        self.password_updates = []
        self.fail_reset = False
        self.fail_update = None
        self.auth = self
        self.admin = self

    def reset_password_for_email(self, email, options=None):
        if self.fail_reset:
            raise RuntimeError("SMTP not configured")
        self.reset_calls.append((email, options))

    def update_user_by_id(self, uid, attributes):
        if self.fail_update:
            raise Exception(self.fail_update)
        self.password_updates.append((uid, attributes))

    def get_user(self, token):
        if token != "valid-recovery-token":
            raise type("AuthApiError", (Exception,), {})("invalid JWT")
        return types.SimpleNamespace(user=types.SimpleNamespace(id=USER_A, email="a@example.com"))


@pytest.fixture
def supa(monkeypatch):
    fake = FakeAuthAdmin()
    monkeypatch.setattr(auth_routes, "_auth_client", lambda implicit_flow=False: fake)
    monkeypatch.setattr(security.config, "supabase_client", fake)
    monkeypatch.setattr(auth_routes.config, "supabase_client", fake)
    security.clear_token_cache()
    rate_limit.reset()
    main.app.dependency_overrides.clear()
    yield fake
    rate_limit.reset()
    security.clear_token_cache()


@pytest.fixture
def http():
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def test_forgot_password_sends_the_email(supa, http):
    r = http.post("/api/auth/forgot-password", json={"email": "  A@Example.com "})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert supa.reset_calls[0][0] == "a@example.com"


def test_the_answer_is_identical_when_sending_fails(supa, http):
    """Otherwise the endpoint would reveal which emails have accounts."""
    ok = http.post("/api/auth/forgot-password", json={"email": "known@example.com"})
    supa.fail_reset = True
    failed = http.post("/api/auth/forgot-password", json={"email": "unknown@example.com"})
    assert (ok.status_code, ok.json()) == (failed.status_code, failed.json())


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "@x.com"])
def test_forgot_password_validates_the_address(supa, http, bad):
    assert http.post("/api/auth/forgot-password", json={"email": bad}).status_code in (400, 422)
    assert supa.reset_calls == []


def test_reset_links_may_only_point_at_our_own_sites(supa, http, monkeypatch):
    monkeypatch.setattr(auth_routes, "ALLOWED_ORIGINS", ["https://docuquery.vercel.app"])
    for i, (requested, expected) in enumerate(
        [
            ("https://docuquery.vercel.app/some/page", "https://docuquery.vercel.app/"),
            ("http://localhost:5173/", "http://localhost:5173/"),
            ("https://evil.example.com/steal", None),
            ("https://docuquery.vercel.app.evil.com/", None),
            ("javascript:alert(1)", None),
        ]
    ):
        http.post("/api/auth/forgot-password", json={"email": f"u{i}@example.com", "redirect_to": requested})
        options = supa.reset_calls[-1][1]
        assert options.get("redirect_to") == expected, requested


def test_forgot_password_is_rate_limited_per_address_and_per_ip(supa, http):
    codes = [http.post("/api/auth/forgot-password", json={"email": "same@example.com"}).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]
    assert len(supa.reset_calls) == 5, "no mail may be sent once limited"


def test_reset_password_changes_the_password_with_the_emailed_token(supa, http):
    r = http.post("/api/auth/reset-password", json={"access_token": "valid-recovery-token", "password": "a-new-password"})
    assert r.status_code == 200
    assert supa.password_updates == [(USER_A, {"password": "a-new-password"})]


def test_reset_password_rejects_bad_tokens_and_weak_passwords(supa, http):
    assert http.post("/api/auth/reset-password", json={"access_token": "forged-token-value", "password": "a-new-password"}).status_code == 401
    assert http.post("/api/auth/reset-password", json={"access_token": "valid-recovery-token", "password": "short"}).status_code == 422
    assert supa.password_updates == []


def test_reset_password_reports_supabase_password_rules(supa, http):
    supa.fail_update = "Password should contain at least one number"
    r = http.post("/api/auth/reset-password", json={"access_token": "valid-recovery-token", "password": "alllowercase"})
    assert r.status_code == 400 and "number" in r.json()["detail"]
