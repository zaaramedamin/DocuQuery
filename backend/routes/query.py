"""
Route for the RAG query pipeline: embed question → Supabase vector search → LLM generation.
"""

from fastapi import APIRouter, HTTPException, Body

from backend.config import hf_client, GENERATION_MODEL
from backend.services import db_service
from backend.services.rag_service import get_embedding

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query")
def query_documents(
    question: str = Body(..., embed=True),
    filename: str = Body(None, embed=True),
):
    """
    Run the full RAG pipeline:
    1. Embed the user question.
    2. Perform database-side vector search using Supabase RPC.
    3. Feed the top-3 matched chunks as context to the LLM.
    4. Return the generated answer with source citations.
    """
    if not db_service.has_any_documents():
        raise HTTPException(status_code=400, detail="No documents uploaded yet. Please upload a PDF first.")

    if not hf_client:
        raise HTTPException(status_code=500, detail="Hugging Face client is not initialized (HF_TOKEN missing).")

    try:
        # 1. Generate query embedding
        question_vector = get_embedding(question)

        # 2. Invoke match_documents RPC on Supabase
        client = db_service.get_client()
        rpc_params = {
            "query_embedding": question_vector.tolist(),
            "match_threshold": 0.2,
            "match_count": 3,
        }
        if filename:
            rpc_params["filter_filename"] = filename

        response = client.rpc("match_documents", rpc_params).execute()
        top_k = response.data

        if not top_k:
            raise HTTPException(status_code=404, detail="No matching document chunks found.")

        # 3. Build context
        context_parts = [
            f"[Source: {c['filename']}, Page {c['page']}]\n{c['text']}" for c in top_k
        ]
        context = "\n\n---\n\n".join(context_parts)

        prompt = (
            "Answer the following question using ONLY the context provided below.\n"
            'If the answer is not in the context, say "I don\'t know based on this document."\n\n'
            f"Context:\n{context}\n\n"
            f"Question: {question}\n"
        )

        # 4. Request completion from Hugging Face model
        response = hf_client.chat_completion(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        answer = response.choices[0].message.content

        sources = [
            {"filename": c["filename"], "page": c["page"], "text": c["text"][:150] + "…"}
            for c in top_k
        ]

        return {"answer": answer, "sources": sources}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating answer: {e}")
