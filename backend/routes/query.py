"""
Route for the RAG query pipeline: embed question → query reformulation →
Supabase vector search → LLM generation with SSE streaming.
"""

import json
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse

from backend.config import hf_client, GENERATION_MODEL
from backend.services import db_service
from backend.services.rag_service import get_embedding

router = APIRouter(prefix="/api", tags=["query"])


def _reformulate_query(question: str, history: list[dict]) -> str:
    """
    Use a quick LLM call to rewrite a vague follow-up question into
    a self-contained, search-optimized query using conversation history.
    """
    if not history or not hf_client:
        return question

    recent = history[-6:]  # last 3 exchanges
    history_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'AI'}: {m['content']}" for m in recent
    )

    reformulation_prompt = (
        "Given the conversation history and the latest user question, "
        "rewrite the question as a standalone, search-optimized query. "
        "Only output the rewritten query, nothing else.\n\n"
        f"History:\n{history_text}\n\n"
        f"Latest question: {question}\n\n"
        "Rewritten query:"
    )

    try:
        resp = hf_client.chat_completion(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": reformulation_prompt}],
            max_tokens=100,
        )
        rewritten = resp.choices[0].message.content.strip()
        return rewritten if rewritten else question
    except Exception:
        return question


@router.post("/query")
def query_documents(
    question: str = Body(..., embed=True),
    filename: str = Body(None, embed=True),
    history: list[dict] = Body(default=[], embed=True),
):
    """
    Run the full RAG pipeline with SSE streaming:
    1. Reformulate question using conversation history.
    2. Embed the reformulated question.
    3. Perform database-side vector search using Supabase RPC.
    4. Stream the LLM answer token-by-token via SSE.
    """
    if not db_service.has_any_documents():
        raise HTTPException(status_code=400, detail="No documents uploaded yet. Please upload a PDF first.")

    if not hf_client:
        raise HTTPException(status_code=500, detail="Hugging Face client is not initialized (HF_TOKEN missing).")

    try:
        # 1. Reformulate question for better retrieval
        search_query = _reformulate_query(question, history)

        # 2. Generate query embedding
        question_vector = get_embedding(search_query)

        # 3. Invoke match_documents RPC on Supabase
        client = db_service.get_client()
        rpc_params = {
            "query_embedding": question_vector.tolist(),
            "match_threshold": 0.2,
            "match_count": 5,
        }
        if filename:
            rpc_params["filter_filename"] = filename

        response = client.rpc("match_documents", rpc_params).execute()
        top_k = response.data

        if not top_k:
            raise HTTPException(status_code=404, detail="No matching document chunks found.")

        # 4. Build context
        context_parts = [
            f"[Source: {c['filename']}, Page {c['page']}]\n{c['text']}" for c in top_k
        ]
        context = "\n\n---\n\n".join(context_parts)

        # Include conversation history in the prompt
        history_section = ""
        if history:
            recent = history[-6:]
            history_section = "Previous conversation:\n" + "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in recent
            ) + "\n\n"

        prompt = (
            "You are DocuQuery, an intelligent document analysis assistant. "
            "Answer questions using ONLY the context provided below. "
            "Use Markdown formatting (bold, lists, headers) to structure your response clearly. "
            'If the answer is not in the context, say "I don\'t know based on the available documents."\n\n'
            f"{history_section}"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n"
        )

        sources = [
            {
                "filename": c["filename"],
                "page": c["page"],
                "text": c["text"][:150] + ("…" if len(c["text"]) > 150 else ""),
            }
            for c in top_k
        ]

        # 5. Stream the response via SSE
        def event_stream():
            # Send sources first as a JSON event
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            # Stream LLM tokens
            try:
                stream = hf_client.chat_completion(
                    model=GENERATION_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating answer: {e}")


@router.post("/feedback")
def submit_feedback(
    message_id: str = Body(..., embed=True),
    feedback: str = Body(..., embed=True),
    question: str = Body("", embed=True),
    answer: str = Body("", embed=True),
):
    """
    Store user feedback (thumbs up/down) on a response.
    Stores to Supabase 'feedback' table.
    """
    if feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Feedback must be 'up' or 'down'.")

    try:
        client = db_service.get_client()
        client.table("feedback").insert({
            "message_id": message_id,
            "feedback": feedback,
            "question": question,
            "answer": answer,
        }).execute()
        return {"status": "success"}
    except Exception as e:
        # Non-critical — don't crash the app if feedback storage fails
        print(f"Warning: Failed to store feedback: {e}")
        return {"status": "ok", "note": "Feedback noted (storage unavailable)"}
