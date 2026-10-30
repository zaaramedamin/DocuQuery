"""
Route for the RAG query pipeline:
reformulate → embed → hybrid search → rerank → LLM generation (SSE streaming).

Every question belongs to a saved conversation. The server owns the
history (it is read from the database, not trusted from the client).
"""

import json
import sys
import uuid
from datetime import datetime, timezone

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from config import (
    RATE_LIMIT_QUERY,
    gemini_client,
    GENERATION_MODEL,
)
from security import AuthUser, get_current_user, is_valid_uuid, limited_user
from services import db_service, plans, retrieval, user_settings
from services.llm import generation_config

router = APIRouter(prefix="/api", tags=["query"])

query_user = limited_user("query", RATE_LIMIT_QUERY)

_HISTORY_MESSAGES = 6
_TITLE_CHARS = 60


class QueryBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # 0 documents = search everything, 1 = that document, 2+ = compare them.
    filenames: list[str] = Field(default_factory=list, max_length=20)
    # Search inside every source carrying this tag (used when no files are picked).
    tag: str | None = Field(default=None, max_length=60)
    # Search inside every source in this folder (also used when no files are picked).
    folder: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = None
    # Re-answer the last question: the previous answer is replaced.
    regenerate: bool = False
    # How the answer should be written (the user's response-style setting).
    style: Literal["normal", "casual", "explanatory", "formal"] = "normal"


# Writing instructions for each response style. "normal" adds nothing.
STYLE_INSTRUCTIONS: dict[str, str] = {
    "normal": "",
    "casual": "Write in a relaxed, friendly, conversational tone with short sentences. ",
    "explanatory": (
        "Explain step by step as if teaching: define key terms, give the reasoning behind each point, "
        "and add a short example where it helps. "
    ),
    "formal": "Write in a formal, precise, professional register. Avoid contractions and casual phrasing. ",
}


class FeedbackBody(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)
    feedback: str
    question: str = Field(default="", max_length=4000)
    answer: str = Field(default="", max_length=20000)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _make_title(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= _TITLE_CHARS else title[: _TITLE_CHARS - 1].rstrip() + "…"


def _start_of_today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _build_prompt(
    question: str,
    history: list[dict],
    chunks: list[dict],
    compare: bool,
    style: str = "normal",
    settings: dict | None = None,
) -> str:
    preferences, preferences_block = user_settings.prompt_preferences(settings or user_settings.DEFAULTS)
    history_section = ""
    if history:
        history_section = "Previous conversation:\n" + "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in history[-_HISTORY_MESSAGES:]
        ) + "\n\n"

    if compare:
        # Group passages under their document so the model can contrast them.
        groups: dict[str, list[dict]] = {}
        for c in chunks:
            groups.setdefault(c["filename"], []).append(c)
        context = "\n\n".join(
            f"=== Document: {name} ===\n"
            + "\n\n".join(f"[Page {c['page']}]\n{c['text']}" for c in items)
            for name, items in groups.items()
        )
        task = (
            "The user selected several documents to compare. Answer using ONLY the context below. "
            "Name each document explicitly, and where the question calls for it, organise the answer "
            "into similarities and differences (a Markdown table is welcome). "
            "If one document says nothing about the point, say so. "
        )
    else:
        context = "\n\n---\n\n".join(
            f"[Source: {c['filename']}, Page {c['page']}]\n{c['text']}" for c in chunks
        )
        task = "Answer questions using ONLY the context provided below. "

    return (
        "You are DocuQuery, an intelligent document analysis assistant. "
        f"{task}"
        f"{STYLE_INSTRUCTIONS.get(style, '')}"
        f"{preferences}"
        "Start directly with the answer: do not greet the user, introduce yourself or restate these instructions. "
        "Use Markdown formatting (bold, lists, headers) to structure your response clearly. "
        'If the answer is not in the context, say "I don\'t know based on the available documents."\n\n'
        f"{preferences_block}"
        f"{history_section}"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n"
    )


def _dedupe(names: list[str]) -> list[str]:
    return list(dict.fromkeys(n for n in names if n))


_END = object()


def _open_stream(prompt: str):
    """Start the model stream (blocking; runs in a worker thread)."""
    return iter(
        gemini_client.models.generate_content_stream(
            model=GENERATION_MODEL,
            contents=prompt,
            config=generation_config(max_output_tokens=4096),
        )
    )


def _save_answer(user_id: str, conversation_id: str, message_id: str, answer: str, sources: list[dict], question: str) -> None:
    try:
        db_service.add_message(
            user_id, conversation_id, "assistant", answer,
            sources=sources, question=question, message_id=message_id,
        )
        db_service.touch_conversation(user_id, conversation_id)
    except Exception as save_error:
        print(f"Warning: could not save answer: {save_error}", file=sys.stderr)


async def _stream_answer(
    user_id: str,
    conversation_id: str,
    message_id: str,
    prompt: str,
    sources: list[dict],
    question: str,
):
    """
    Generate the SSE stream for one answer and save it to the conversation.

    This is an ASYNC generator on purpose: when the browser stops the request
    (Stop button, closed tab) the server cancels it, and only an async
    generator reliably gets to run its ``finally`` block then. The save lives
    there, so a partly generated answer is kept instead of being lost.
    """
    yield _sse({"type": "meta", "conversation_id": conversation_id, "message_id": message_id})
    yield _sse({"type": "sources", "sources": sources})

    parts: list[str] = []
    error: str | None = None
    try:
        iterator = await run_in_threadpool(_open_stream, prompt)
        while True:
            chunk = await run_in_threadpool(next, iterator, _END)
            if chunk is _END:
                break
            token = chunk.text
            if token:
                parts.append(token)
                yield _sse({"type": "token", "token": token})
    except Exception as e:  # model failure: reported to the client below
        error = str(e)
    finally:
        answer = "".join(parts)
        if answer.strip():
            # Shielded: the save must finish even though this task is being cancelled.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(_save_answer, user_id, conversation_id, message_id, answer, sources, question)

    if error:
        yield _sse({"type": "error", "error": error})
    yield _sse({"type": "done"})


@router.post("/query")
def query_documents(body: QueryBody, user: AuthUser = Depends(query_user)):
    """
    Run the full RAG pipeline with SSE streaming:
    1. Reformulate the question using conversation history.
    2. Hybrid search (vector + keyword) over the user's documents, then rerank.
    3. Stream the LLM answer token-by-token via SSE.
    4. Save the exchange to the conversation.
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Please enter a question.")
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini client is not initialized (GEMINI_API_KEY missing).")

    documents = db_service.list_documents(user.id)
    if not documents:
        raise HTTPException(status_code=400, detail="No documents uploaded yet. Please add a source first.")

    filenames = _dedupe(body.filenames)
    known = {d["filename"] for d in documents}
    missing = [f for f in filenames if f not in known]
    if missing:
        raise HTTPException(status_code=404, detail=f"Document not found: {missing[0]}")

    within: list[str] | None = None
    if body.folder and body.folder.strip() and not filenames:
        wanted_folder = body.folder.strip().lower()
        within = [d["filename"] for d in documents if (d.get("folder") or "").lower() == wanted_folder]
        if not within:
            raise HTTPException(status_code=404, detail=f"There are no sources in the folder \"{body.folder.strip()}\".")
    elif body.tag and not filenames:
        wanted = body.tag.strip().lower()
        within = [d["filename"] for d in documents if wanted in [t.lower() for t in d.get("tags") or []]]
        if not within:
            raise HTTPException(status_code=404, detail=f"No sources are tagged \"{body.tag.strip()}\".")

    profile = db_service.get_profile(user.id)
    limits = plans.limits_for(plans.plan_of(profile))
    if limits.daily_questions > 0 and db_service.count_user_questions_since(user.id, _start_of_today_utc()) >= limits.daily_questions:
        raise HTTPException(
            status_code=429,
            detail=plans.limit_error(
                limits,
                f"You've reached today's limit of {limits.daily_questions} questions. It resets at midnight UTC"
                + (", or upgrade to Pro for many more." if plans.upgrade_hint(limits) else "."),
                "daily_limit",
            ),
        )

    conversation = None
    history: list[dict] = []
    if body.conversation_id:
        if not is_valid_uuid(body.conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        conversation = db_service.get_conversation(user.id, body.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")
        stored = db_service.recent_messages(user.id, conversation["id"], _HISTORY_MESSAGES + 2)
        if body.regenerate and len(stored) >= 2 and stored[-1]["role"] == "assistant" and stored[-2]["role"] == "user":
            stored = stored[:-2]  # the exchange being replaced is not context
        history = [{"role": m["role"], "content": m["content"]} for m in stored[-_HISTORY_MESSAGES:]]

    compare = len(filenames) >= 2

    try:
        chunks = retrieval.retrieve(user.id, question, history, filenames, within)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating answer: {e}")

    if not chunks:
        raise HTTPException(status_code=404, detail="No matching document chunks found.")

    # Retrieval worked: now it is safe to change the saved conversation.
    if conversation is None:
        conversation = db_service.create_conversation(user.id, _make_title(question))
    elif body.regenerate:
        db_service.delete_last_exchange(user.id, conversation["id"])
    conversation_id = conversation["id"]
    db_service.add_message(user.id, conversation_id, "user", question)

    prompt = _build_prompt(question, history, chunks, compare, body.style, user_settings.merged((profile or {}).get("settings")))
    sources = [
        {
            "filename": c["filename"],
            "page": c["page"],
            "text": c["text"][:150] + ("…" if len(c["text"]) > 150 else ""),
        }
        for c in chunks
    ]
    message_id = str(uuid.uuid4())

    return StreamingResponse(
        _stream_answer(user.id, conversation_id, message_id, prompt, sources, question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback")
def submit_feedback(body: FeedbackBody, user: AuthUser = Depends(get_current_user)):
    """
    Store user feedback (thumbs up/down) on a response, both on the message
    itself and in the 'feedback' table used for quality review.
    """
    if body.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Feedback must be 'up' or 'down'.")

    if is_valid_uuid(body.message_id):
        db_service.set_message_feedback(user.id, body.message_id, body.feedback)
    try:
        db_service.insert_feedback(user.id, body.message_id, body.feedback, body.question, body.answer)
        return {"status": "success"}
    except Exception as e:
        # Non-critical — don't crash the app if feedback storage fails
        print(f"Warning: Failed to store feedback: {e}", file=sys.stderr)
        return {"status": "ok", "note": "Feedback noted (storage unavailable)"}
