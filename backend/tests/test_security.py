import pytest
from fastapi import HTTPException

import config
import security
from tests.conftest import USER_A


class FakeAuthClient:
    def __init__(self, user_id=USER_A, email="a@example.com", error=None):
        self.calls = 0
        self.user_id = user_id
        self.email = email
        self.error = error
        self.auth = self

    def get_user(self, token):
        self.calls += 1
        if self.error:
            raise self.error
        user = type("U", (), {"id": self.user_id, "email": self.email})()
        return type("R", (), {"user": user})()


class AuthApiError(Exception):
    """Same class name as the real supabase-auth error."""


@pytest.fixture(autouse=True)
def _clean_cache():
    security.clear_token_cache()
    yield
    security.clear_token_cache()


def use_client(monkeypatch, client):
    monkeypatch.setattr(config, "supabase_client", client)


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer   ", "token-without-scheme"])
def test_missing_or_malformed_header_is_401(header):
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(header)
    assert exc.value.status_code == 401


def test_valid_token_returns_the_user(monkeypatch):
    use_client(monkeypatch, FakeAuthClient())
    user = security.get_current_user("Bearer good-token")
    assert user == security.AuthUser(USER_A, "a@example.com")


def test_bearer_scheme_is_case_insensitive(monkeypatch):
    use_client(monkeypatch, FakeAuthClient())
    assert security.get_current_user("bearer good-token").id == USER_A


def test_verified_tokens_are_cached(monkeypatch):
    client = FakeAuthClient()
    use_client(monkeypatch, client)
    security.get_current_user("Bearer t")
    security.get_current_user("Bearer t")
    assert client.calls == 1


def test_expired_cache_entries_are_rechecked(monkeypatch):
    client = FakeAuthClient()
    use_client(monkeypatch, client)
    monkeypatch.setattr(security, "TOKEN_CACHE_TTL_SECONDS", -1)  # entries expire immediately
    security.get_current_user("Bearer t")
    security.get_current_user("Bearer t")
    assert client.calls == 2


def test_rejected_token_is_401_and_not_cached(monkeypatch):
    client = FakeAuthClient(error=AuthApiError("invalid JWT"))
    use_client(monkeypatch, client)
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            security.get_current_user("Bearer bad")
        assert exc.value.status_code == 401
    assert client.calls == 2


def test_network_failure_is_503_not_401(monkeypatch):
    use_client(monkeypatch, FakeAuthClient(error=ConnectionError("dns failure")))
    with pytest.raises(HTTPException) as exc:
        security.get_current_user("Bearer t")
    assert exc.value.status_code == 503


def test_response_without_a_valid_user_id_is_401(monkeypatch):
    use_client(monkeypatch, FakeAuthClient(user_id="not-a-uuid"))
    with pytest.raises(HTTPException) as exc:
        security.get_current_user("Bearer t")
    assert exc.value.status_code == 401


def test_unconfigured_supabase_is_503(monkeypatch):
    use_client(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        security.get_current_user("Bearer t")
    assert exc.value.status_code == 503


def test_is_valid_uuid():
    assert security.is_valid_uuid(USER_A)
    for bad in ("", "abc", "../../etc", None, 5):
        assert not security.is_valid_uuid(bad)
