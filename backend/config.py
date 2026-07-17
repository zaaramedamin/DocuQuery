"""
Application-wide configuration and client initialization.

Loads environment variables and initializes external service connections
(Hugging Face Inference API, Supabase) once at import time.
"""

import os
import sys
from huggingface_hub import InferenceClient
import dotenv

# Load .env from project root (one level up from backend/)
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Hugging Face ──────────────────────────────────────────────────────
HF_TOKEN: str | None = os.getenv("HF_TOKEN")

# NOTE: the embedding dimension (384) is baked into supabase_schema.sql
# (vector(384)); changing this model to one with a different dimension
# also requires updating the schema and re-indexing every document.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Chat model served via HF Inference Providers. It must be served by a
# provider your token has access to — check the model page or
# https://huggingface.co/settings/inference-providers. Override with the
# GENERATION_MODEL env var (e.g. "Qwen/Qwen2.5-72B-Instruct" for higher
# quality at greater cost).
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

# ── App settings ──────────────────────────────────────────────────────
# Comma-separated list of allowed CORS origins; defaults to "*" for local dev.
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
# Maximum accepted PDF upload size (bytes).
MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024

if not HF_TOKEN:
    print(
        "Warning: HF_TOKEN is not set. The application will fail to run queries.",
        file=sys.stderr,
    )

hf_client: InferenceClient | None = InferenceClient(token=HF_TOKEN) if HF_TOKEN else None

# ── Supabase ───────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Warning: Failed to initialize Supabase client. Error: {e}", file=sys.stderr)
else:
    print("Warning: SUPABASE_URL or SUPABASE_KEY is missing in your .env file.", file=sys.stderr)
