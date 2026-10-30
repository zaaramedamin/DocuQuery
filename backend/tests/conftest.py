"""
Shared test fixtures.

Tests never touch the network or the real Supabase / Gemini accounts:
credentials are blanked BEFORE the app is imported (so python-dotenv can't
load a developer's real .env), and the database / model are replaced with
in-memory fakes.
"""

import os
import re
import uuid
from datetime import datetime, timezone

# Must happen before `config` is imported anywhere.
for _name in ("SUPABASE_URL", "SUPABASE_KEY", "GEMINI_API_KEY"):
    os.environ[_name] = ""
os.environ["BILLING_DEMO_MODE"] = "true"  # the developer's own .env must not change test results

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
import security
from services import db_service, file_store, ingest, llm, rate_limit, retrieval, summarizer

assert config.supabase_client is None and config.gemini_client is None, "tests must not use real credentials"

USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


# ── Fake database ────────────────────────────────────────────────────

class FakeDB:
    """In-memory stand-in for services.db_service with the same function names."""

    def __init__(self):
        self.documents: list[dict] = []
        self.chunks: list[dict] = []
        self.conversations: list[dict] = []
        self.messages: list[dict] = []
        self.feedback: list[dict] = []
        self.shares: list[dict] = []
        self.profiles: dict[str, dict] = {}
        self.storage: dict[str, bytes] = {}
        self._seq = 0
        self._chunk_id = 0

    # documents
    def list_documents(self, user_id):
        rows = [d for d in self.documents if d["user_id"] == user_id]
        return [{k: v for k, v in d.items() if k not in ("pages", "storage_key", "user_id")} for d in rows]

    def get_document(self, user_id, filename, include_pages=False):
        for d in self.documents:
            if d["user_id"] == user_id and d["filename"] == filename:
                row = dict(d)
                if not include_pages:
                    row.pop("pages", None)
                return row
        return None

    def save_document(self, row):
        previous = next(
            (d for d in self.documents if d["user_id"] == row["user_id"] and d["filename"] == row["filename"]), None
        )
        self.documents = [d for d in self.documents if d is not previous]
        stored = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tags": (previous or {}).get("tags", []),
            "folder": (previous or {}).get("folder"),
            **row,
        }
        self.documents.append(stored)
        return dict(stored)

    def delete_document_row(self, user_id, filename):
        self.documents = [d for d in self.documents if not (d["user_id"] == user_id and d["filename"] == filename)]

    def count_documents(self, user_id):
        return len([d for d in self.documents if d["user_id"] == user_id])

    def storage_used_bytes(self, user_id):
        return sum(d["size_bytes"] for d in self.documents if d["user_id"] == user_id)

    def has_any_documents(self, user_id):
        return self.count_documents(user_id) > 0

    # chunks
    def insert_chunks(self, chunks):
        for c in chunks:
            self._chunk_id += 1
            self.chunks.append({"id": self._chunk_id, **c})
        return len(chunks)

    def delete_chunks(self, user_id, filename):
        before = len(self.chunks)
        self.chunks = [c for c in self.chunks if not (c["user_id"] == user_id and c["filename"] == filename)]
        return before - len(self.chunks)

    def hybrid_search(self, user_id, embedding, tsquery, match_count, filename=None, filenames=None):
        words = [w for w in tsquery.split(" | ") if w]
        scored = []
        for c in self.chunks:
            if c["user_id"] != user_id or (filename and c["filename"] != filename):
                continue
            if filenames and c["filename"] not in filenames:
                continue
            hits = sum(1 for w in words if w in c["text"].lower())
            scored.append((hits, c))
        scored.sort(key=lambda pair: -pair[0])
        return [
            {"id": c["id"], "filename": c["filename"], "chunk_index": c["chunk_index"],
             "text": c["text"], "page": c["page"], "similarity": 0.5, "score": float(h)}
            for h, c in scored[:match_count]
        ]

    def clone_document_chunks(self, src_user, dst_user, filename, new_filename):
        copies = [
            {**c, "user_id": dst_user, "filename": new_filename}
            for c in self.chunks
            if c["user_id"] == src_user and c["filename"] == filename
        ]
        self.insert_chunks([{k: v for k, v in c.items() if k != "id"} for c in copies])
        return len(copies)

    def set_document_tags(self, user_id, filename, tags):
        for d in self.documents:
            if d["user_id"] == user_id and d["filename"] == filename:
                d["tags"] = tags
                return True
        return False

    # folders
    def set_documents_folder(self, user_id, filenames, folder):
        moved = 0
        for d in self.documents:
            if d["user_id"] == user_id and d["filename"] in filenames:
                d["folder"] = folder
                moved += 1
        return moved

    def rename_folder(self, user_id, old, new):
        moved = 0
        for d in self.documents:
            if d["user_id"] == user_id and d.get("folder") == old:
                d["folder"] = new
                moved += 1
        return moved

    # profiles
    def get_profile(self, user_id):
        row = self.profiles.get(user_id)
        return dict(row) if row else None

    def update_profile(self, user_id, fields):
        row = self.profiles.setdefault(user_id, {
            "user_id": user_id, "display_name": None, "plan": "free", "subscription_status": None, "current_period_end": None,
            "cancel_at_period_end": False, "settings": {},
        })
        row.update(fields)
        return dict(row)

    # sharing
    def find_share(self, user_id, kind, ref):
        key = "conversation_id" if kind == "conversation" else "document_filename"
        for sh in self.shares:
            if sh["user_id"] == user_id and sh["kind"] == kind and sh.get(key) == ref:
                return self._share_out(sh)
        return None

    @staticmethod
    def _share_out(sh):
        return {k: v for k, v in sh.items() if k != "user_id"}

    def create_share(self, user_id, kind, ref, token):
        row = {"id": str(uuid.uuid4()), "token": token, "user_id": user_id, "kind": kind,
               "conversation_id": ref if kind == "conversation" else None,
               "document_filename": ref if kind == "document" else None,
               "created_at": datetime.now(timezone.utc).isoformat()}
        self.shares.append(row)
        return self._share_out(row)

    def list_shares(self, user_id):
        return [self._share_out(s) for s in self.shares if s["user_id"] == user_id]

    def delete_share(self, user_id, share_id):
        before = len(self.shares)
        self.shares = [s for s in self.shares if not (s["user_id"] == user_id and s["id"] == share_id)]
        return len(self.shares) < before

    def delete_document_shares(self, user_id, filename):
        self.shares = [s for s in self.shares
                       if not (s["user_id"] == user_id and s["kind"] == "document" and s["document_filename"] == filename)]

    def get_share_by_token(self, token):
        return next((dict(s) for s in self.shares if s["token"] == token), None)

    # searching chats
    def search_conversations(self, user_id, query, limit=30):
        needle = query.lower()
        found = {}
        for c in self.conversations:
            if c["user_id"] == user_id and needle in c["title"].lower():
                found[c["id"]] = {"id": c["id"], "title": c["title"], "updated_at": c["updated_at"], "snippet": ""}
        for m in self.messages:
            if m["user_id"] == user_id and needle in m["content"].lower():
                conv = next(c for c in self.conversations if c["id"] == m["conversation_id"])
                entry = found.setdefault(conv["id"], {"id": conv["id"], "title": conv["title"],
                                                      "updated_at": conv["updated_at"], "snippet": ""})
                entry["snippet"] = entry["snippet"] or m["content"]
        return sorted(found.values(), key=lambda r: r["updated_at"], reverse=True)[:limit]

    # storage
    def upload_file_to_storage(self, key, data, content_type):
        self.storage[key] = data
        return True

    def download_file_from_storage(self, key):
        return self.storage.get(key)

    def delete_file_from_storage(self, key):
        self.storage.pop(key, None)

    # conversations
    def create_conversation(self, user_id, title="New chat"):
        now = datetime.now(timezone.utc).isoformat()
        row = {"id": str(uuid.uuid4()), "user_id": user_id, "title": title, "created_at": now, "updated_at": now}
        self.conversations.append(row)
        return {k: v for k, v in row.items() if k != "user_id"}

    def list_conversations(self, user_id, limit=100):
        rows = [c for c in self.conversations if c["user_id"] == user_id]
        rows.sort(key=lambda c: c["updated_at"], reverse=True)
        return [{k: v for k, v in c.items() if k != "user_id"} for c in rows[:limit]]

    def get_conversation(self, user_id, conversation_id):
        for c in self.conversations:
            if c["user_id"] == user_id and c["id"] == conversation_id:
                return {k: v for k, v in c.items() if k != "user_id"}
        return None

    def rename_conversation(self, user_id, conversation_id, title):
        for c in self.conversations:
            if c["user_id"] == user_id and c["id"] == conversation_id:
                c["title"] = title
                return True
        return False

    def touch_conversation(self, user_id, conversation_id):
        for c in self.conversations:
            if c["user_id"] == user_id and c["id"] == conversation_id:
                c["updated_at"] = datetime.now(timezone.utc).isoformat()

    def delete_conversation(self, user_id, conversation_id):
        found = self.get_conversation(user_id, conversation_id) is not None
        self.conversations = [c for c in self.conversations if not (c["user_id"] == user_id and c["id"] == conversation_id)]
        self.messages = [m for m in self.messages if m["conversation_id"] != conversation_id]
        self.shares = [s for s in self.shares if s.get("conversation_id") != conversation_id]  # ON DELETE CASCADE
        return found

    def delete_all_conversations(self, user_id):
        ids = {c["id"] for c in self.conversations if c["user_id"] == user_id}
        self.conversations = [c for c in self.conversations if c["id"] not in ids]
        self.messages = [m for m in self.messages if m["conversation_id"] not in ids]
        self.shares = [s for s in self.shares if s.get("conversation_id") not in ids]
        return len(ids)

    # messages
    def add_message(self, user_id, conversation_id, role, content, sources=None, question=None, message_id=None):
        self._seq += 1
        row = {
            "id": message_id or str(uuid.uuid4()), "seq": self._seq, "user_id": user_id,
            "conversation_id": conversation_id, "role": role, "content": content,
            "sources": sources or [], "question": question, "feedback": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.messages.append(row)
        return row

    def _conv_messages(self, user_id, conversation_id):
        rows = [m for m in self.messages if m["user_id"] == user_id and m["conversation_id"] == conversation_id]
        return sorted(rows, key=lambda m: m["seq"])

    def list_messages(self, user_id, conversation_id):
        return [{k: v for k, v in m.items() if k not in ("user_id", "seq", "conversation_id")}
                for m in self._conv_messages(user_id, conversation_id)]

    def recent_messages(self, user_id, conversation_id, count):
        return self.list_messages(user_id, conversation_id)[-count:]

    def delete_last_exchange(self, user_id, conversation_id):
        last = self.recent_messages(user_id, conversation_id, 2)
        if len(last) != 2 or last[0]["role"] != "user" or last[1]["role"] != "assistant":
            return
        ids = {last[0]["id"], last[1]["id"]}
        self.messages = [m for m in self.messages if m["id"] not in ids]

    def set_message_feedback(self, user_id, message_id, feedback):
        for m in self.messages:
            if m["user_id"] == user_id and m["id"] == message_id:
                m["feedback"] = feedback

    def count_user_questions_since(self, user_id, since):
        return len([m for m in self.messages
                    if m["user_id"] == user_id and m["role"] == "user"
                    and datetime.fromisoformat(m["created_at"]) >= since])

    def insert_feedback(self, user_id, message_id, feedback, question, answer):
        self.feedback.append({"user_id": user_id, "message_id": message_id, "feedback": feedback,
                              "question": question, "answer": answer})


_DB_FUNCTIONS = [
    name for name in vars(FakeDB)
    if not name.startswith("_") and callable(getattr(FakeDB, name))
]


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    db = FakeDB()
    for name in _DB_FUNCTIONS:
        monkeypatch.setattr(db_service, name, getattr(db, name))
    monkeypatch.setattr(file_store, "UPLOAD_DIR", str(tmp_path / "uploads"))
    return db


# ── Fake embeddings / Gemini ─────────────────────────────────────────

def _vector_for(text: str) -> np.ndarray:
    seed = abs(hash(text)) % (2**32)
    return np.random.default_rng(seed).random(config.EMBEDDING_DIM, dtype=np.float32)


class FakeGemini:
    """Stands in for google-genai's client: scripted answers, recorded prompts."""

    def __init__(self):
        self.stream_tokens: list[str] = ["Hello ", "world."]
        self.stream_error_after: int | None = None   # raise after N tokens
        self.stream_delay = 0.0                       # seconds between tokens
        self.text_response = "rewritten query"
        self.json_response = '{"summary": "A short summary.", "questions": ["Q one?", "Q two?"]}'
        self.prompts: list[str] = []
        self.models = self

    class _Chunk:
        def __init__(self, text):
            self.text = text

    def generate_content_stream(self, model, contents, config):
        self.prompts.append(contents if isinstance(contents, str) else str(contents))
        for index, token in enumerate(self.stream_tokens):
            if self.stream_error_after is not None and index >= self.stream_error_after:
                raise RuntimeError("503 UNAVAILABLE")
            if self.stream_delay:
                import time
                time.sleep(self.stream_delay)
            yield self._Chunk(token)

    def generate_content(self, model, contents, config):
        wants_json = getattr(config, "response_mime_type", None) == "application/json"
        return self._Chunk(self.json_response if wants_json else self.text_response)


@pytest.fixture
def fake_gemini(monkeypatch):
    fake = FakeGemini()
    for module in (llm, retrieval, summarizer):
        monkeypatch.setattr(module, "gemini_client", fake)
    import routes.query as query_routes
    monkeypatch.setattr(query_routes, "gemini_client", fake)
    monkeypatch.setattr(ingest, "get_embeddings", lambda texts: [_vector_for(t) for t in texts])
    monkeypatch.setattr(retrieval, "get_embedding", lambda text: _vector_for(text))
    return fake


# ── HTTP client with a switchable signed-in user ─────────────────────

class AppClient:
    def __init__(self, client: TestClient, app):
        self.http = client
        self._app = app
        self.as_user(USER_A)

    def as_user(self, user_id: str, email: str = "user@example.com"):
        self._app.dependency_overrides[security.get_current_user] = lambda: security.AuthUser(user_id, email)
        return self


@pytest.fixture
def app_client(fake_db, fake_gemini):
    import main

    rate_limit.reset()
    security.clear_token_cache()
    main.app.dependency_overrides.clear()
    client = AppClient(TestClient(main.app), main.app)
    yield client
    main.app.dependency_overrides.clear()
    rate_limit.reset()


def parse_sse(text: str) -> list[dict]:
    import json
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


def parse_ndjson(text: str) -> list[dict]:
    import json
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def make_pdf(pages: list[str]) -> bytes:
    """Build a small text PDF in memory."""
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 780), text, fontsize=11)
    return doc.tobytes()


def make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal valid .docx in memory."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def make_pptx(slides: list[str], notes: dict[int, str] | None = None, reverse_order: bool = False) -> bytes:
    """
    Build a minimal .pptx. ``slides`` are the texts in presentation order. With
    ``reverse_order`` the files are numbered backwards, so file order and
    presentation order disagree (as in a real, re-arranged deck).
    """
    import io
    import zipfile
    from xml.sax.saxutils import escape

    ns = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    count = len(slides)
    file_numbers = list(range(count, 0, -1)) if reverse_order else list(range(1, count + 1))
    notes = notes or {}

    def body(lines):
        paras = "".join(f"<a:p><a:r><a:t>{escape(line)}</a:t></a:r></a:p>" for line in lines.split("\n") if line)
        return f"<p:sld {ns}><p:cSld><p:spTree><p:sp><p:txBody>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"

    ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(count))
    presentation = f"<p:presentation {ns}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    slide_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
    notes_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
    pres_rels = "".join(
        f'<Relationship Id="rId{i + 1}" Type="{slide_type}" Target="slides/slide{file_numbers[i]}.xml"/>'
        for i in range(count)
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{rel_ns}">{pres_rels}</Relationships>')
        for i, text in enumerate(slides):
            n = file_numbers[i]
            archive.writestr(f"ppt/slides/slide{n}.xml", body(text))
            if i + 1 in notes:
                archive.writestr(
                    f"ppt/slides/_rels/slide{n}.xml.rels",
                    f'<Relationships xmlns="{rel_ns}"><Relationship Id="rId9" Type="{notes_type}" '
                    f'Target="../notesSlides/notesSlide{n}.xml"/></Relationships>',
                )
                archive.writestr(f"ppt/notesSlides/notesSlide{n}.xml", body(notes[i + 1]))
    return buffer.getvalue()


def make_xlsx(sheets: dict[str, list[list]], hidden: tuple[str, ...] = ()) -> bytes:
    """Build an .xlsx from {sheet name: rows}."""
    import io
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
        if name in hidden:
            ws.sheet_state = "hidden"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def words(n: int, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


__all__ = ["USER_A", "USER_B", "parse_sse", "parse_ndjson", "make_pdf", "make_docx", "make_pptx", "make_xlsx", "words"]
