"""
The route tests run against an in-memory fake, so they can't prove the REAL
queries in db_service are scoped to the signed-in user. These tests record
the Supabase query chain each function builds and assert it always filters
by user_id — the guarantee behind private libraries.
"""

from datetime import datetime, timezone

import pytest

from services import db_service
from tests.conftest import USER_A

OTHER_ID = "33333333-3333-4333-8333-333333333333"


class Result:
    def __init__(self, data=None, count=0):
        self.data = data if data is not None else []
        self.count = count


class RecordingBuilder:
    """Stands in for postgrest's chainable builder; remembers every call."""

    def __init__(self, log, table):
        self.log = log
        self.table_name = table
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return method

    def execute(self):
        self.log.append(self)
        # A row, so functions that need one (e.g. update checks) behave normally.
        row = {
            "id": OTHER_ID, "role": "assistant", "content": "x", "conversation_id": OTHER_ID,
            "title": "t", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return Result(data=[row], count=1)

    def filters(self):
        return [(a[0], a[1]) for (n, a, _) in self.calls if n == "eq"]


class RecordingClient:
    def __init__(self):
        self.log: list[RecordingBuilder] = []
        self.rpc_calls: list[tuple[str, dict]] = []

    def table(self, name):
        return RecordingBuilder(self.log, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return RecordingBuilder(self.log, f"rpc:{name}")


@pytest.fixture
def client(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(db_service, "supabase_client", recorder)
    return recorder


READS_AND_DELETES = [
    ("list_documents", lambda: db_service.list_documents(USER_A)),
    ("get_document", lambda: db_service.get_document(USER_A, "a.pdf")),
    ("get_document+pages", lambda: db_service.get_document(USER_A, "a.pdf", include_pages=True)),
    ("delete_document_row", lambda: db_service.delete_document_row(USER_A, "a.pdf")),
    ("count_documents", lambda: db_service.count_documents(USER_A)),
    ("storage_used_bytes", lambda: db_service.storage_used_bytes(USER_A)),
    ("has_any_documents", lambda: db_service.has_any_documents(USER_A)),
    ("delete_chunks", lambda: db_service.delete_chunks(USER_A, "a.pdf")),
    ("list_conversations", lambda: db_service.list_conversations(USER_A)),
    ("get_conversation", lambda: db_service.get_conversation(USER_A, OTHER_ID)),
    ("rename_conversation", lambda: db_service.rename_conversation(USER_A, OTHER_ID, "t")),
    ("touch_conversation", lambda: db_service.touch_conversation(USER_A, OTHER_ID)),
    ("delete_conversation", lambda: db_service.delete_conversation(USER_A, OTHER_ID)),
    ("list_messages", lambda: db_service.list_messages(USER_A, OTHER_ID)),
    ("recent_messages", lambda: db_service.recent_messages(USER_A, OTHER_ID, 5)),
    ("set_message_feedback", lambda: db_service.set_message_feedback(USER_A, OTHER_ID, "up")),
    ("count_user_questions_since", lambda: db_service.count_user_questions_since(USER_A, datetime.now(timezone.utc))),
    ("set_document_tags", lambda: db_service.set_document_tags(USER_A, "a.pdf", ["x"])),
    ("search_conversations", lambda: db_service.search_conversations(USER_A, "refund")),
    ("find_share (chat)", lambda: db_service.find_share(USER_A, "conversation", OTHER_ID)),
    ("find_share (document)", lambda: db_service.find_share(USER_A, "document", "a.pdf")),
    ("list_shares", lambda: db_service.list_shares(USER_A)),
    ("delete_share", lambda: db_service.delete_share(USER_A, OTHER_ID)),
    ("delete_document_shares", lambda: db_service.delete_document_shares(USER_A, "a.pdf")),
    ("set_documents_folder", lambda: db_service.set_documents_folder(USER_A, ["a.pdf"], "Contracts")),
    ("set_documents_folder (remove)", lambda: db_service.set_documents_folder(USER_A, ["a.pdf"], None)),
    ("rename_folder", lambda: db_service.rename_folder(USER_A, "Old", "New")),
    ("get_profile", lambda: db_service.get_profile(USER_A)),
    ("delete_all_conversations", lambda: db_service.delete_all_conversations(USER_A)),
]


@pytest.mark.parametrize("label, call", READS_AND_DELETES, ids=[l for l, _ in READS_AND_DELETES])
def test_every_query_is_filtered_by_user_id(client, label, call):
    call()
    assert client.log, "function made no query"
    for builder in client.log:
        assert ("user_id", USER_A) in builder.filters(), f"{label}: query on '{builder.table_name}' is not scoped to the user"


def test_delete_last_exchange_only_deletes_the_users_rows(client, monkeypatch):
    pair = [{"id": "m1", "role": "user"}, {"id": "m2", "role": "assistant"}]
    monkeypatch.setattr(db_service, "recent_messages", lambda *a: pair)
    db_service.delete_last_exchange(USER_A, OTHER_ID)
    delete_query = client.log[-1]
    assert ("user_id", USER_A) in delete_query.filters()
    assert any(name == "in_" and args[1] == ["m1", "m2"] for name, args, _ in delete_query.calls)


def test_hybrid_search_is_always_scoped_to_the_user(client):
    db_service.hybrid_search(USER_A, [0.1] * 384, "term", 10, filename="a.pdf")
    name, params = client.rpc_calls[0]
    assert name == "hybrid_search" and params["p_user_id"] == USER_A and params["filter_filename"] == "a.pdf"


def test_new_rows_are_stamped_with_the_owner(client):
    db_service.create_conversation(USER_A, "t")
    db_service.add_message(USER_A, OTHER_ID, "user", "hi")
    db_service.insert_feedback(USER_A, "m", "up", "q", "a")
    for builder in client.log:
        inserted = next(args[0] for name, args, _ in builder.calls if name == "insert")
        assert inserted["user_id"] == USER_A


def test_old_schema_errors_are_reported_helpfully():
    error = db_service._db_error("Search failed", Exception("function hybrid_search does not exist"))
    assert "supabase_schema.sql" in error.detail


def test_hybrid_search_passes_a_tag_scope_to_the_database(client):
    db_service.hybrid_search(USER_A, [0.1] * 384, "term", 10, filenames=["a.pdf", "b.pdf"])
    _, params = client.rpc_calls[0]
    assert params["filter_filenames"] == ["a.pdf", "b.pdf"] and params["p_user_id"] == USER_A
    assert "filter_filename" not in params


def test_new_shares_are_stamped_with_the_owner(client):
    db_service.create_share(USER_A, "conversation", OTHER_ID, "tok")
    db_service.create_share(USER_A, "document", "a.pdf", "tok2")
    for builder in client.log:
        inserted = next(args[0] for name, args, _ in builder.calls if name == "insert")
        assert inserted["user_id"] == USER_A


def test_the_only_unscoped_lookup_is_by_secret_token(client):
    """Share links work without a session, so the token itself is the credential."""
    db_service.get_share_by_token("some-secret-token")
    (builder,) = client.log
    assert ("token", "some-secret-token") in builder.filters() and ("user_id", USER_A) not in builder.filters()


def test_cloning_a_document_is_an_explicit_two_user_operation(monkeypatch):
    calls = []

    class ScalarRpcClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return type("Query", (), {"execute": staticmethod(lambda: Result(data=3))})()

    monkeypatch.setattr(db_service, "supabase_client", ScalarRpcClient())
    assert db_service.clone_document_chunks(USER_A, OTHER_ID, "a.pdf", "a (2).pdf") == 3
    name, params = calls[0]
    assert name == "clone_document_chunks" and params["p_src_user"] == USER_A and params["p_dst_user"] == OTHER_ID


def test_search_escapes_like_wildcards():
    assert db_service._like_pattern("100%_done") == r"%100\%\_done%"


def test_updating_a_profile_stamps_the_owner_and_never_touches_another_user(client):
    db_service.update_profile(USER_A, {"display_name": "Alex"})
    (builder,) = client.log
    row = next(args[0] for name, args, _ in builder.calls if name == "upsert")
    assert row["user_id"] == USER_A and row["display_name"] == "Alex"
    assert next(kwargs for name, _, kwargs in builder.calls if name == "upsert") == {"on_conflict": "user_id"}


def test_a_missing_profiles_table_does_not_break_the_app(monkeypatch):
    """Until the schema is updated, everyone is simply on the Free plan."""

    class Broken:
        def table(self, name):
            raise Exception("relation \"profiles\" does not exist")

    monkeypatch.setattr(db_service, "supabase_client", Broken())
    assert db_service.get_profile(USER_A) is None


def test_document_lists_still_work_before_the_folder_column_exists(monkeypatch):
    """A database that has not had the latest schema yet keeps its library (folders just stay empty)."""
    asked = []

    class OldSchema:
        def table(self, name):
            return Query()

    class Query:
        def select(self, columns):
            asked.append(columns)
            self.columns = columns
            return self

        def __getattr__(self, name):
            return lambda *a, **k: self

        def execute(self):
            if "folder" in self.columns:
                raise Exception("column documents.folder does not exist")
            return Result(data=[{"filename": "a.pdf"}])

    monkeypatch.setattr(db_service, "supabase_client", OldSchema())
    rows = db_service.list_documents(USER_A)
    assert rows == [{"filename": "a.pdf", "folder": None}]
    assert "folder" in asked[0] and "folder" not in asked[1]
