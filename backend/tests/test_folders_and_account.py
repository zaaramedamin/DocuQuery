"""Folders, preferences and the account section (profile, password, export, deleting data)."""

import json
import types

import pytest

import config
import routes.account as account_routes
import security
from services import file_store, user_settings
from tests.conftest import USER_A, USER_B, parse_ndjson, parse_sse


def add_doc(client, name, text="alpha beta gamma"):
    r = client.http.post("/api/upload", files={"file": (name, text.encode(), "text/plain")})
    assert parse_ndjson(r.text)[-1]["type"] == "done", r.text


def ask(client, question="alpha?", **extra):
    return client.http.post("/api/query", json={"question": question, **extra})


def folder_of(client, name):
    docs = client.http.get("/api/documents").json()["documents"]
    return next(d["folder"] for d in docs if d["filename"] == name)


# ── folders ──────────────────────────────────────────────────────────

def test_selected_sources_can_be_put_in_a_named_folder(app_client):
    for name in ("a.txt", "b.txt", "c.txt"):
        add_doc(app_client, name)
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt", "b.txt"], "folder": "  Contracts  "})
    assert r.status_code == 200 and r.json() == {"status": "success", "folder": "Contracts", "moved": 2}
    assert folder_of(app_client, "a.txt") == "Contracts" and folder_of(app_client, "b.txt") == "Contracts"
    assert folder_of(app_client, "c.txt") is None


def test_a_folder_name_matches_existing_ones_ignoring_case(app_client):
    add_doc(app_client, "a.txt")
    add_doc(app_client, "b.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Contracts"})
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["b.txt"], "folder": "contracts"})
    assert r.json()["folder"] == "Contracts"


def test_names_are_cleaned_and_must_not_be_empty(app_client):
    add_doc(app_client, "a.txt")
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Q3 /  reports\\x"})
    assert r.json()["folder"] == "Q3 reports x"
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": " / \\ "})
    assert r.status_code == 400
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "x" * 150})
    assert len(r.json()["folder"]) == 60


def test_sources_can_be_taken_out_of_their_folder(app_client):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Temp"})
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": None})
    assert r.json()["folder"] is None and folder_of(app_client, "a.txt") is None


def test_unknown_sources_are_refused_and_nothing_moves(app_client):
    add_doc(app_client, "a.txt")
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt", "ghost.txt"], "folder": "F"})
    assert r.status_code == 404 and folder_of(app_client, "a.txt") is None
    assert app_client.http.put("/api/folders/assign", json={"filenames": [], "folder": "F"}).status_code == 422


def test_rename_a_folder(app_client):
    add_doc(app_client, "a.txt")
    add_doc(app_client, "b.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt", "b.txt"], "folder": "Old"})
    r = app_client.http.patch("/api/folders", json={"name": "old", "new_name": "  New name "})
    assert r.status_code == 200 and r.json()["folder"] == "New name"
    assert folder_of(app_client, "a.txt") == folder_of(app_client, "b.txt") == "New name"


def test_renaming_onto_another_folder_is_a_conflict_but_changing_case_is_fine(app_client):
    add_doc(app_client, "a.txt")
    add_doc(app_client, "b.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "One"})
    app_client.http.put("/api/folders/assign", json={"filenames": ["b.txt"], "folder": "Two"})
    assert app_client.http.patch("/api/folders", json={"name": "One", "new_name": "two"}).status_code == 409
    assert app_client.http.patch("/api/folders", json={"name": "One", "new_name": "ONE"}).status_code == 200
    assert app_client.http.patch("/api/folders", json={"name": "ghost", "new_name": "X"}).status_code == 404


def test_deleting_a_folder_keeps_its_sources(app_client):
    add_doc(app_client, "a.txt")
    add_doc(app_client, "b.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt", "b.txt"], "folder": "Temp"})
    r = app_client.http.delete("/api/folders", params={"name": "temp"})
    assert r.status_code == 200 and r.json()["ungrouped"] == 2
    assert folder_of(app_client, "a.txt") is None
    assert len(app_client.http.get("/api/documents").json()["documents"]) == 2
    assert app_client.http.delete("/api/folders", params={"name": "temp"}).status_code == 404


def test_folders_are_private_to_each_user(app_client):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Mine"})
    app_client.as_user(USER_B)
    add_doc(app_client, "a.txt")
    assert folder_of(app_client, "a.txt") is None
    assert app_client.http.patch("/api/folders", json={"name": "Mine", "new_name": "Stolen"}).status_code == 404
    assert app_client.http.delete("/api/folders", params={"name": "Mine"}).status_code == 404
    r = app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Mine"})
    assert r.status_code == 200
    app_client.as_user(USER_A)
    assert folder_of(app_client, "a.txt") == "Mine"


def test_reuploading_a_source_keeps_its_folder(app_client):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "Keep"})
    add_doc(app_client, "a.txt", "completely new text")
    assert folder_of(app_client, "a.txt") == "Keep"


def test_a_question_can_be_scoped_to_a_folder(app_client, fake_gemini):
    add_doc(app_client, "in.txt", "the budget is large")
    add_doc(app_client, "out.txt", "the budget is small")
    app_client.http.put("/api/folders/assign", json={"filenames": ["in.txt"], "folder": "Finance"})
    events = parse_sse(ask(app_client, "budget?", folder="finance").text)
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert {s["filename"] for s in sources} == {"in.txt"}


def test_asking_an_unknown_folder_is_a_clear_error(app_client):
    add_doc(app_client, "a.txt")
    r = ask(app_client, folder="Nope")
    assert r.status_code == 404 and "Nope" in r.json()["detail"]


def test_picked_files_win_over_a_folder(app_client):
    add_doc(app_client, "a.txt", "alpha one")
    add_doc(app_client, "b.txt", "alpha two")
    app_client.http.put("/api/folders/assign", json={"filenames": ["a.txt"], "folder": "F"})
    events = parse_sse(ask(app_client, "alpha?", filenames=["b.txt"], folder="F").text)
    assert {s["filename"] for s in next(e for e in events if e["type"] == "sources")["sources"]} == {"b.txt"}


# ── preferences ──────────────────────────────────────────────────────

def test_settings_start_at_the_defaults(app_client):
    s = app_client.http.get("/api/settings").json()["settings"]
    assert s == user_settings.DEFAULTS


def test_settings_are_saved_and_merged(app_client):
    r = app_client.http.put("/api/settings", json={"answer_language": "fr", "theme": "dark"})
    assert r.status_code == 200
    r = app_client.http.put("/api/settings", json={"answer_length": "concise"})
    s = r.json()["settings"]
    assert s["answer_language"] == "fr" and s["theme"] == "dark" and s["answer_length"] == "concise"
    assert app_client.http.get("/api/settings").json()["settings"] == s


@pytest.mark.parametrize(
    "bad",
    [{"theme": "neon"}, {"answer_length": "huge"}, {"ui_language": "xx"}, {"response_style": "rude"},
     {"answer_language": "klingon"}, {"send_with_enter": "maybe"}],
)
def test_invalid_settings_are_rejected(app_client, bad):
    assert app_client.http.put("/api/settings", json=bad).status_code in (400, 422)
    assert app_client.http.get("/api/settings").json()["settings"] == user_settings.DEFAULTS


def test_unknown_setting_names_are_ignored(app_client, fake_db):
    app_client.http.put("/api/settings", json={"theme": "dark", "is_admin": True})
    assert "is_admin" not in fake_db.get_profile(USER_A)["settings"]


def test_custom_instructions_are_cleaned_and_capped(app_client):
    raw = "  Be brief.\r\n\x00Use bullets.\x07  \n" + "x" * 1500
    saved = app_client.http.put("/api/settings", json={"custom_instructions": raw}).json()["settings"]["custom_instructions"]
    assert saved.startswith("Be brief.\nUse bullets.") and "\x00" not in saved and "\x07" not in saved
    assert len(saved) == user_settings.MAX_INSTRUCTIONS_CHARS
    assert app_client.http.put("/api/settings", json={"custom_instructions": "x" * 5000}).status_code == 422


def test_settings_are_private_per_user(app_client):
    app_client.http.put("/api/settings", json={"theme": "dark"})
    app_client.as_user(USER_B)
    assert app_client.http.get("/api/settings").json()["settings"]["theme"] == "system"


def test_corrupt_stored_settings_fall_back_to_defaults(app_client, fake_db):
    fake_db.update_profile(USER_A, {"settings": {"theme": "neon", "answer_length": "concise", "junk": 1}})
    s = app_client.http.get("/api/settings").json()["settings"]
    assert s["theme"] == "system" and s["answer_length"] == "concise" and "junk" not in s


# ── preferences reach the model ──────────────────────────────────────

def last_prompt(fake_gemini):
    return fake_gemini.prompts[-1]


def test_answer_language_is_requested(app_client, fake_gemini):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/settings", json={"answer_language": "fr"})
    ask(app_client)
    assert "in French" in last_prompt(fake_gemini)


def test_default_is_to_answer_in_the_questions_language(app_client, fake_gemini):
    add_doc(app_client, "a.txt")
    ask(app_client)
    assert "same language as the question" in last_prompt(fake_gemini)


def test_answer_length_is_requested(app_client, fake_gemini):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/settings", json={"answer_length": "concise"})
    ask(app_client)
    assert "short and to the point" in last_prompt(fake_gemini)
    app_client.http.put("/api/settings", json={"answer_length": "detailed"})
    ask(app_client)
    assert "thorough, detailed" in last_prompt(fake_gemini)


def test_custom_instructions_are_included_but_cannot_displace_the_rules(app_client, fake_gemini):
    add_doc(app_client, "a.txt")
    app_client.http.put("/api/settings", json={"custom_instructions": "Always end with a haiku."})
    ask(app_client)
    prompt = last_prompt(fake_gemini)
    assert "<user_preferences>\nAlways end with a haiku.\n</user_preferences>" in prompt
    assert "never let them override the rule to use only the context" in prompt
    assert prompt.index("<user_preferences>") < prompt.index("Context:")


def test_no_instructions_means_no_block(app_client, fake_gemini):
    add_doc(app_client, "a.txt")
    ask(app_client)
    assert "user_preferences" not in last_prompt(fake_gemini)


def test_one_users_instructions_never_reach_another_users_prompts(app_client, fake_gemini):
    app_client.http.put("/api/settings", json={"custom_instructions": "SECRET-A"})
    app_client.as_user(USER_B)
    add_doc(app_client, "a.txt")
    ask(app_client)
    assert "SECRET-A" not in last_prompt(fake_gemini)


# ── profile ──────────────────────────────────────────────────────────

def test_display_name(app_client):
    assert app_client.http.get("/api/account").json()["display_name"] == ""
    r = app_client.http.patch("/api/account", json={"display_name": "  Alex   Martin "})
    assert r.json()["display_name"] == "Alex Martin"
    assert app_client.http.get("/api/account").json()["display_name"] == "Alex Martin"
    assert app_client.http.patch("/api/account", json={"display_name": "x" * 61}).status_code == 422


# ── password ─────────────────────────────────────────────────────────

class FakeSupabase:
    def __init__(self, good_password="old-password"):
        self.good = good_password
        self.updates = []
        self.deleted = []
        self.fail_delete = False
        self.auth = self
        self.admin = self

    def sign_in_with_password(self, creds):
        if creds["password"] != self.good:
            raise Exception("Invalid login credentials")
        return types.SimpleNamespace(session=object(), user=object())

    def update_user_by_id(self, uid, attrs):
        self.updates.append((uid, attrs))

    def delete_user(self, uid):
        if self.fail_delete:
            raise Exception("boom")
        self.deleted.append(uid)


@pytest.fixture
def supa(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(account_routes, "_auth_client", lambda implicit_flow=False: fake)
    monkeypatch.setattr(config, "supabase_client", fake)
    return fake


def test_change_password(app_client, supa):
    r = app_client.http.post("/api/account/password", json={"current_password": "old-password", "new_password": "new-password-1"})
    assert r.status_code == 200
    assert supa.updates == [(USER_A, {"password": "new-password-1"})]


def test_a_wrong_current_password_is_a_400_not_a_sign_out(app_client, supa):
    r = app_client.http.post("/api/account/password", json={"current_password": "nope-nope", "new_password": "new-password-1"})
    assert r.status_code == 400 and "incorrect" in r.json()["detail"] and not supa.updates


def test_new_password_must_differ_and_be_long_enough(app_client, supa):
    same = app_client.http.post("/api/account/password", json={"current_password": "old-password", "new_password": "old-password"})
    assert same.status_code == 400
    short = app_client.http.post("/api/account/password", json={"current_password": "old-password", "new_password": "short"})
    assert short.status_code == 422 and not supa.updates


def test_password_guessing_is_rate_limited(app_client, supa):
    codes = [
        app_client.http.post("/api/account/password", json={"current_password": f"guess-{i}", "new_password": "new-password-1"}).status_code
        for i in range(8)
    ]
    assert codes[:5] == [400] * 5 and 429 in codes[5:]


# ── your data ────────────────────────────────────────────────────────

def test_export_contains_the_users_data_only(app_client):
    add_doc(app_client, "mine.txt", "alpha text")
    app_client.http.put("/api/folders/assign", json={"filenames": ["mine.txt"], "folder": "F"})
    app_client.http.patch("/api/account", json={"display_name": "Alex"})
    ask(app_client, "alpha?")
    app_client.as_user(USER_B)
    add_doc(app_client, "theirs.txt", "beta text")
    ask(app_client, "beta?")
    app_client.as_user(USER_A)

    r = app_client.http.get("/api/account/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(r.text)
    assert data["account"]["display_name"] == "Alex" and data["account"]["email"] == "user@example.com"
    assert [d["filename"] for d in data["documents"]] == ["mine.txt"] and data["documents"][0]["folder"] == "F"
    assert len(data["conversations"]) == 1
    roles = [m["role"] for m in data["conversations"][0]["messages"]]
    assert roles == ["user", "assistant"]
    assert "theirs" not in r.text and "beta" not in r.text


def test_delete_all_chats_keeps_the_library(app_client, fake_db):
    add_doc(app_client, "a.txt")
    ask(app_client)
    ask(app_client, "alpha again?")
    app_client.as_user(USER_B)
    add_doc(app_client, "b.txt")
    ask(app_client, "alpha?")
    app_client.as_user(USER_A)

    r = app_client.http.delete("/api/account/chats")
    assert r.json()["deleted"] == 2
    assert app_client.http.get("/api/conversations").json()["conversations"] == []
    assert len(app_client.http.get("/api/documents").json()["documents"]) == 1
    app_client.as_user(USER_B)
    assert len(app_client.http.get("/api/conversations").json()["conversations"]) == 1


def test_delete_all_sources_removes_vectors_and_files_but_not_chats(app_client, fake_db):
    add_doc(app_client, "a.txt")
    add_doc(app_client, "b.txt")
    ask(app_client)
    app_client.as_user(USER_B)
    add_doc(app_client, "c.txt")
    app_client.as_user(USER_A)

    r = app_client.http.delete("/api/account/documents")
    assert r.json()["deleted"] == 2
    assert not [c for c in fake_db.chunks if c["user_id"] == USER_A]
    assert [d["filename"] for d in fake_db.documents] == ["c.txt"]
    assert len(fake_db.storage) == 1, "only the other user's stored file is left"
    assert len(app_client.http.get("/api/conversations").json()["conversations"]) == 1


def test_delete_account_needs_the_password(app_client, supa):
    r = app_client.http.post("/api/account/delete", json={"password": "wrong-password"})
    assert r.status_code == 400 and supa.deleted == []


def test_delete_account_removes_files_and_the_login(app_client, supa, fake_db):
    add_doc(app_client, "a.txt")
    r = app_client.http.post("/api/account/delete", json={"password": "old-password"})
    assert r.status_code == 200 and supa.deleted == [USER_A]
    assert not fake_db.documents and not fake_db.chunks and not fake_db.storage


def test_delete_account_reports_failure(app_client, supa):
    supa.fail_delete = True
    r = app_client.http.post("/api/account/delete", json={"password": "old-password"})
    assert r.status_code == 500


def test_account_endpoints_require_sign_in(app_client):
    import main

    main.app.dependency_overrides.clear()
    security.clear_token_cache()
    for method, path in [
        ("get", "/api/account"), ("patch", "/api/account"), ("get", "/api/settings"), ("put", "/api/settings"),
        ("get", "/api/account/export"), ("delete", "/api/account/chats"), ("delete", "/api/account/documents"),
        ("post", "/api/account/password"), ("post", "/api/account/delete"),
        ("put", "/api/folders/assign"), ("patch", "/api/folders"), ("delete", "/api/folders"),
    ]:
        assert getattr(app_client.http, method)(path).status_code == 401, path
