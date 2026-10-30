import time
import types

import pytest

import main
import routes.auth as auth_routes
import security
from services import rate_limit
from tests.conftest import USER_A, USER_B, parse_ndjson, parse_sse

# ── conversations ────────────────────────────────────────────────────


def chat(client, question, **extra):
    client.http.post("/api/upload", files={"file": ("a.txt", b"alpha beta gamma", "text/plain")})
    r = client.http.post("/api/query", json={"question": question, **extra})
    return parse_sse(r.text)[0]["conversation_id"]


def test_list_conversations_newest_activity_first(app_client, fake_db):
    first = chat(app_client, "first topic alpha")
    time.sleep(0.01)
    second = chat(app_client, "second topic beta")
    time.sleep(0.01)
    app_client.http.post("/api/query", json={"question": "more alpha", "conversation_id": first})

    ids = [c["id"] for c in app_client.http.get("/api/conversations").json()["conversations"]]
    assert ids == [first, second]


def test_open_conversation_returns_messages_in_order(app_client):
    cid = chat(app_client, "alpha?")
    data = app_client.http.get(f"/api/conversations/{cid}").json()
    assert data["conversation"]["title"] == "alpha?"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][1]["sources"][0]["filename"] == "a.txt"


def test_rename_conversation(app_client):
    cid = chat(app_client, "alpha?")
    r = app_client.http.patch(f"/api/conversations/{cid}", json={"title": "  My   renamed chat "})
    assert r.json()["title"] == "My renamed chat"
    assert app_client.http.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == "My renamed chat"


def test_rename_rejects_blank_title(app_client):
    cid = chat(app_client, "alpha?")
    assert app_client.http.patch(f"/api/conversations/{cid}", json={"title": ""}).status_code == 422


def test_delete_conversation_removes_its_messages(app_client, fake_db):
    cid = chat(app_client, "alpha?")
    assert app_client.http.delete(f"/api/conversations/{cid}").status_code == 200
    assert fake_db.messages == []
    assert app_client.http.get(f"/api/conversations/{cid}").status_code == 404


def test_conversations_are_private(app_client):
    cid = chat(app_client, "alpha?")
    app_client.as_user(USER_B)
    assert app_client.http.get("/api/conversations").json()["conversations"] == []
    assert app_client.http.get(f"/api/conversations/{cid}").status_code == 404
    assert app_client.http.patch(f"/api/conversations/{cid}", json={"title": "hacked"}).status_code == 404
    assert app_client.http.delete(f"/api/conversations/{cid}").status_code == 404
    app_client.as_user(USER_A)
    assert app_client.http.get(f"/api/conversations/{cid}").status_code == 200


@pytest.mark.parametrize("bad_id", ["nope", "123", "../etc/passwd"])
def test_invalid_conversation_ids_are_404(app_client, bad_id):
    assert app_client.http.get(f"/api/conversations/{bad_id}").status_code == 404


# ── auth routes ──────────────────────────────────────────────────────

class FakeSupabaseAuth:
    def __init__(self):
        self.mode = "session"          # session | confirm | error
        self.error = None
        self.calls = []
        self.auth = self

    def _result(self):
        if self.error:
            raise Exception(self.error)
        user = types.SimpleNamespace(id=USER_A, email="a@example.com")
        if self.mode == "confirm":
            return types.SimpleNamespace(session=None, user=user)
        session = types.SimpleNamespace(access_token="access-1", refresh_token="refresh-1", expires_at=123)
        return types.SimpleNamespace(session=session, user=user)

    def sign_up(self, creds):
        self.calls.append(("sign_up", creds))
        return self._result()

    def sign_in_with_password(self, creds):
        self.calls.append(("login", creds))
        return self._result()

    def refresh_session(self, token):
        self.calls.append(("refresh", token))
        return self._result()


@pytest.fixture
def supa(monkeypatch):
    fake = FakeSupabaseAuth()
    monkeypatch.setattr(auth_routes, "_auth_client", lambda: fake)
    rate_limit.reset()
    main.app.dependency_overrides.clear()
    yield fake
    rate_limit.reset()


@pytest.fixture
def http():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


CREDS = {"email": "  A@Example.com ", "password": "correct horse battery"}


def test_login_returns_a_session(supa, http):
    r = http.post("/api/auth/login", json=CREDS)
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "access-1" and body["refresh_token"] == "refresh-1"
    assert body["user"] == {"id": USER_A, "email": "a@example.com"}
    assert supa.calls[0] == ("login", {"email": "a@example.com", "password": "correct horse battery"})  # normalised


def test_signup_with_instant_session(supa, http):
    assert http.post("/api/auth/signup", json=CREDS).json()["access_token"] == "access-1"


def test_signup_waiting_for_email_confirmation(supa, http):
    supa.mode = "confirm"
    body = http.post("/api/auth/signup", json=CREDS).json()
    assert body == {"needs_confirmation": True, "email": "a@example.com"}


@pytest.mark.parametrize(
    "error, status",
    [
        ("Invalid login credentials", 401),
        ("Email not confirmed", 403),
        ("User already registered", 409),
        ("Password should be at least 6 characters", 400),
        ("email rate limit exceeded", 429),
    ],
)
def test_supabase_errors_are_translated(supa, http, error, status):
    supa.error = error
    path = "/api/auth/signup" if "registered" in error or "Password" in error else "/api/auth/login"
    assert http.post(path, json=CREDS).status_code == status


def test_unknown_auth_failures_do_not_leak_internals(supa, http):
    supa.error = "psycopg2 connection to 10.0.0.5 refused"
    r = http.post("/api/auth/login", json=CREDS)
    assert r.status_code == 401 and "10.0.0.5" not in r.text


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "longenough1"},
        {"email": "a@b.co", "password": "short"},
        {"email": "a@b.co", "password": "x" * 200},
        {"email": "a@b.co"},
    ],
)
def test_bad_credentials_are_rejected_before_reaching_supabase(supa, http, payload):
    assert http.post("/api/auth/signup", json=payload).status_code in (400, 422)
    assert supa.calls == []


def test_refresh_issues_a_new_session(supa, http):
    r = http.post("/api/auth/refresh", json={"refresh_token": "old-refresh-token"})
    assert r.status_code == 200 and r.json()["access_token"] == "access-1"


def test_refresh_with_a_dead_token_is_401(supa, http):
    supa.error = "Invalid Refresh Token"
    assert http.post("/api/auth/refresh", json={"refresh_token": "dead-refresh-token"}).status_code == 401


def test_auth_endpoints_are_rate_limited(supa, http):
    codes = [http.post("/api/auth/login", json=CREDS).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and 429 in codes[10:]


def test_me_requires_and_returns_the_session_user(supa, http, monkeypatch):
    assert http.get("/api/auth/me").status_code == 401

    class Client:
        auth = types.SimpleNamespace(
            get_user=lambda token: types.SimpleNamespace(user=types.SimpleNamespace(id=USER_A, email="a@example.com"))
        )

    monkeypatch.setattr(security.config, "supabase_client", Client())
    security.clear_token_cache()
    r = http.get("/api/auth/me", headers={"Authorization": "Bearer good"})
    assert r.json() == {"id": USER_A, "email": "a@example.com"}


def test_unknown_api_routes_are_json_404s(http):
    r = http.get("/api/does-not-exist")
    assert r.status_code == 404
