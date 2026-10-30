import asyncio
import config
import contextlib

import routes.query as query_routes
from tests.conftest import USER_A, USER_B, parse_ndjson, parse_sse


def add_doc(client, name, text):
    r = client.http.post("/api/upload", files={"file": (name, text.encode(), "text/plain")})
    assert parse_ndjson(r.text)[-1]["type"] == "done", r.text


def ask(client, question, **extra):
    return client.http.post("/api/query", json={"question": question, **extra})


def events_of(response):
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


def answer_of(events):
    return "".join(e["token"] for e in events if e["type"] == "token")


# ── basic flow ───────────────────────────────────────────────────────

def test_query_requires_documents(app_client):
    r = ask(app_client, "anything?")
    assert r.status_code == 400 and "No documents" in r.json()["detail"]


def test_streams_meta_sources_tokens_then_done(app_client):
    add_doc(app_client, "policy.txt", "The refund policy allows returns within 30 days.")
    events = events_of(ask(app_client, "What is the refund policy?"))

    assert [e["type"] for e in events] == ["meta", "sources", "token", "token", "done"]
    assert answer_of(events) == "Hello world."
    assert events[1]["sources"][0]["filename"] == "policy.txt"


def test_first_question_creates_a_titled_conversation_and_saves_both_messages(app_client, fake_db):
    add_doc(app_client, "policy.txt", "The refund policy allows returns within 30 days.")
    events = events_of(ask(app_client, "What is the refund policy?"))
    meta = events[0]

    assert len(fake_db.conversations) == 1
    conv = fake_db.conversations[0]
    assert conv["id"] == meta["conversation_id"] and conv["title"] == "What is the refund policy?"

    messages = fake_db.list_messages(USER_A, conv["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["id"] == meta["message_id"] and messages[1]["content"] == "Hello world."
    assert messages[1]["question"] == "What is the refund policy?" and messages[1]["sources"]


def test_long_questions_get_a_truncated_title(app_client, fake_db):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    events_of(ask(app_client, "alpha " * 60))
    assert len(fake_db.conversations[0]["title"]) <= 60


def test_follow_up_uses_saved_history(app_client, fake_db, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    cid = events_of(ask(app_client, "first question about alpha"))[0]["conversation_id"]
    events_of(ask(app_client, "and what about beta?", conversation_id=cid))

    prompt = fake_gemini.prompts[-1]
    assert "Previous conversation:" in prompt
    assert "first question about alpha" in prompt and "Hello world." in prompt
    assert len(fake_db.conversations) == 1 and len(fake_db.messages) == 4


def test_client_supplied_history_is_ignored(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    events_of(ask(app_client, "alpha?", history=[{"role": "user", "content": "INJECTED"}]))
    assert "INJECTED" not in fake_gemini.prompts[-1]


# ── regenerate ───────────────────────────────────────────────────────

def test_regenerate_replaces_the_last_answer(app_client, fake_db, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    cid = events_of(ask(app_client, "alpha?"))[0]["conversation_id"]

    fake_gemini.stream_tokens = ["A ", "better ", "answer."]
    events_of(ask(app_client, "alpha?", conversation_id=cid, regenerate=True))

    messages = fake_db.list_messages(USER_A, cid)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "A better answer."


def test_regenerate_does_not_feed_the_old_answer_back_as_context(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    cid = events_of(ask(app_client, "alpha?"))[0]["conversation_id"]
    events_of(ask(app_client, "alpha?", conversation_id=cid, regenerate=True))
    assert "Hello world." not in fake_gemini.prompts[-1]


def test_failed_retrieval_leaves_the_conversation_untouched(app_client, fake_db, monkeypatch):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    cid = events_of(ask(app_client, "alpha?"))[0]["conversation_id"]
    monkeypatch.setattr(query_routes.retrieval, "retrieve", lambda *a, **k: [])
    r = ask(app_client, "alpha?", conversation_id=cid, regenerate=True)
    assert r.status_code == 404
    assert len(fake_db.list_messages(USER_A, cid)) == 2, "the old exchange must survive a failed regenerate"


# ── scope: single document and compare ───────────────────────────────

def test_single_document_scope_filters_sources(app_client):
    add_doc(app_client, "cats.txt", "cats purr softly")
    add_doc(app_client, "dogs.txt", "dogs bark loudly")
    events = events_of(ask(app_client, "what do they do?", filenames=["dogs.txt"]))
    assert {s["filename"] for s in events[1]["sources"]} == {"dogs.txt"}


def test_compare_mode_pulls_from_every_selected_document(app_client, fake_gemini):
    add_doc(app_client, "cats.txt", "cats purr softly")
    add_doc(app_client, "dogs.txt", "dogs bark loudly")
    add_doc(app_client, "birds.txt", "birds sing sweetly")
    events = events_of(ask(app_client, "compare how they sound", filenames=["cats.txt", "dogs.txt"]))

    assert {s["filename"] for s in events[1]["sources"]} == {"cats.txt", "dogs.txt"}
    prompt = fake_gemini.prompts[-1]
    assert "=== Document: cats.txt ===" in prompt and "=== Document: dogs.txt ===" in prompt
    assert "birds.txt" not in prompt and "compare" in prompt.lower()


def test_unknown_document_scope_is_404(app_client):
    add_doc(app_client, "a.txt", "alpha")
    r = ask(app_client, "q?", filenames=["ghost.txt"])
    assert r.status_code == 404 and "ghost.txt" in r.json()["detail"]


def test_duplicate_filenames_do_not_trigger_compare_mode(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta")
    events_of(ask(app_client, "alpha?", filenames=["a.txt", "a.txt"]))
    assert "=== Document" not in fake_gemini.prompts[-1]


# ── isolation ────────────────────────────────────────────────────────

def test_answers_only_draw_on_the_askers_own_documents(app_client):
    add_doc(app_client, "alice.txt", "alice secret launch codes")
    app_client.as_user(USER_B)
    add_doc(app_client, "bob.txt", "bob grocery list")

    events = events_of(ask(app_client, "launch codes secret?"))
    assert {s["filename"] for s in events[1]["sources"]} == {"bob.txt"}


def test_user_cannot_query_with_someone_elses_document_name(app_client):
    add_doc(app_client, "alice.txt", "alice secret launch codes")
    app_client.as_user(USER_B)
    add_doc(app_client, "bob.txt", "bob grocery list")
    assert ask(app_client, "codes?", filenames=["alice.txt"]).status_code == 404


def test_user_cannot_write_into_someone_elses_conversation(app_client):
    add_doc(app_client, "a.txt", "alpha beta")
    cid = events_of(ask(app_client, "alpha?"))[0]["conversation_id"]

    app_client.as_user(USER_B)
    add_doc(app_client, "b.txt", "beta gamma")
    assert ask(app_client, "beta?", conversation_id=cid).status_code == 404


def test_malformed_conversation_id_is_404_not_500(app_client):
    add_doc(app_client, "a.txt", "alpha")
    assert ask(app_client, "alpha?", conversation_id="not-a-uuid").status_code == 404


# ── failures & limits ────────────────────────────────────────────────

def test_mid_stream_model_failure_reports_error_and_keeps_partial_answer(app_client, fake_db, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta")
    fake_gemini.stream_error_after = 1
    events = events_of(ask(app_client, "alpha?"))

    assert [e["type"] for e in events][-2:] == ["error", "done"]
    assert "503" in events[-2]["error"]
    saved = [m for m in fake_db.messages if m["role"] == "assistant"]
    assert [m["content"] for m in saved] == ["Hello "]


def test_total_model_failure_saves_no_empty_answer(app_client, fake_db, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta")
    fake_gemini.stream_error_after = 0
    events = events_of(ask(app_client, "alpha?"))
    assert events[-2]["type"] == "error"
    assert not [m for m in fake_db.messages if m["role"] == "assistant"]


STREAM_ARGS = ("99999999-9999-4999-8999-999999999999", "prompt", [], "q?")


def test_closing_the_stream_early_keeps_what_was_generated(fake_db, fake_gemini, monkeypatch):
    monkeypatch.setattr(query_routes, "gemini_client", fake_gemini)
    cid = fake_db.create_conversation(USER_A, "t")["id"]
    fake_gemini.stream_tokens = ["one ", "two ", "three"]

    async def scenario():
        stream = query_routes._stream_answer(USER_A, cid, *STREAM_ARGS)
        for _ in range(3):          # meta, sources, first token
            await stream.__anext__()
        await stream.aclose()

    asyncio.run(scenario())
    assert [m["content"] for m in fake_db.list_messages(USER_A, cid)] == ["one "]


def test_cancelling_the_request_keeps_what_was_generated(fake_db, fake_gemini, monkeypatch):
    """What a real browser Stop / closed tab does: the server cancels the streaming task."""
    monkeypatch.setattr(query_routes, "gemini_client", fake_gemini)
    cid = fake_db.create_conversation(USER_A, "t")["id"]
    fake_gemini.stream_tokens = [f"t{i} " for i in range(40)]
    fake_gemini.stream_delay = 0.03

    async def scenario():
        stream = query_routes._stream_answer(USER_A, cid, *STREAM_ARGS)

        async def consume():
            async for _ in stream:
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.3)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    saved = fake_db.list_messages(USER_A, cid)
    assert len(saved) == 1 and saved[0]["content"].startswith("t0 t1 ")
    assert 0 < len(saved[0]["content"].split()) < 40, "partial answer, not the whole thing"


def test_daily_question_limit(app_client, monkeypatch):
    add_doc(app_client, "a.txt", "alpha beta")
    monkeypatch.setattr(config, "DAILY_QUERY_LIMIT", 2)
    events_of(ask(app_client, "alpha 1?"))
    events_of(ask(app_client, "alpha 2?"))
    r = ask(app_client, "alpha 3?")
    assert r.status_code == 429 and "today's limit" in r.json()["detail"]["message"]


def test_query_rate_limit(app_client):
    add_doc(app_client, "a.txt", "alpha beta")
    codes = [ask(app_client, f"alpha {i}?").status_code for i in range(22)]
    assert codes[:20] == [200] * 20 and 429 in codes[20:]


def test_blank_question_is_rejected(app_client):
    add_doc(app_client, "a.txt", "alpha")
    assert ask(app_client, "   ").status_code == 400
    assert ask(app_client, "").status_code == 422


# ── feedback ─────────────────────────────────────────────────────────

def test_feedback_is_stored_on_the_message_and_in_the_feedback_table(app_client, fake_db):
    add_doc(app_client, "a.txt", "alpha beta")
    message_id = events_of(ask(app_client, "alpha?"))[0]["message_id"]

    r = app_client.http.post("/api/feedback", json={"message_id": message_id, "feedback": "up", "question": "alpha?", "answer": "Hello world."})
    assert r.status_code == 200
    assert next(m for m in fake_db.messages if m["id"] == message_id)["feedback"] == "up"
    assert fake_db.feedback[0]["user_id"] == USER_A


def test_feedback_cannot_be_set_on_another_users_message(app_client, fake_db):
    add_doc(app_client, "a.txt", "alpha beta")
    message_id = events_of(ask(app_client, "alpha?"))[0]["message_id"]
    app_client.as_user(USER_B)
    app_client.http.post("/api/feedback", json={"message_id": message_id, "feedback": "down"})
    assert next(m for m in fake_db.messages if m["id"] == message_id)["feedback"] is None


def test_feedback_value_is_validated(app_client):
    r = app_client.http.post("/api/feedback", json={"message_id": "x", "feedback": "meh"})
    assert r.status_code == 400


# ── response styles ──────────────────────────────────────────────────

def test_response_style_changes_the_writing_instruction(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    events_of(ask(app_client, "alpha?", style="explanatory"))
    assert "step by step" in fake_gemini.prompts[-1]
    events_of(ask(app_client, "alpha?", style="formal"))
    assert "formal, precise" in fake_gemini.prompts[-1]


def test_normal_style_adds_no_instruction(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    events_of(ask(app_client, "alpha?"))
    prompt = fake_gemini.prompts[-1]
    assert "step by step" not in prompt and "formal, precise" not in prompt and "relaxed" not in prompt


def test_unknown_style_is_rejected(app_client):
    add_doc(app_client, "a.txt", "alpha")
    assert ask(app_client, "alpha?", style="pirate").status_code == 422


def test_prompt_asks_for_a_direct_answer_without_greetings(app_client, fake_gemini):
    add_doc(app_client, "a.txt", "alpha beta gamma")
    events_of(ask(app_client, "alpha?"))
    assert "do not greet the user, introduce yourself" in fake_gemini.prompts[-1]
