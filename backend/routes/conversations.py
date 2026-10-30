"""
Saved chat history: list, open, rename and delete conversations.

Conversations are created automatically by the first question (see
routes/query.py), so there is no "create" endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from security import AuthUser, get_current_user, is_valid_uuid
from services import db_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _require_id(conversation_id: str) -> str:
    if not is_valid_uuid(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation_id


@router.get("")
def list_conversations(user: AuthUser = Depends(get_current_user)):
    return {"conversations": db_service.list_conversations(user.id)}


def make_snippet(content: str, query: str, radius: int = 60) -> str:
    """A short excerpt of *content* around the first match of *query*."""
    text = " ".join((content or "").split())
    index = text.lower().find(query.lower())
    if index < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


# Declared before "/{conversation_id}" so "search" isn't read as an id.
@router.get("/search")
def search_conversations(q: str = Query(min_length=2, max_length=100), user: AuthUser = Depends(get_current_user)):
    query = " ".join(q.split())
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Type at least 2 characters.")
    results = db_service.search_conversations(user.id, query)
    for row in results:
        row["snippet"] = make_snippet(row.get("snippet", ""), query) if row.get("snippet") else ""
    return {"results": results}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, user: AuthUser = Depends(get_current_user)):
    conversation = db_service.get_conversation(user.id, _require_id(conversation_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {
        "conversation": conversation,
        "messages": db_service.list_messages(user.id, conversation["id"]),
    }


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: RenameBody, user: AuthUser = Depends(get_current_user)):
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(status_code=400, detail="The title can't be empty.")
    if not db_service.rename_conversation(user.id, _require_id(conversation_id), title):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "success", "title": title}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, user: AuthUser = Depends(get_current_user)):
    if not db_service.delete_conversation(user.id, _require_id(conversation_id)):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "success"}
