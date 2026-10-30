"""
Application-wide configuration and client initialization.

Loads environment variables and initializes external service connections
(Google Gemini API, Supabase) once at import time.
"""

import os
import sys
import dotenv
from google import genai
from google.genai import types

# Load .env from project root (one level up from backend/)
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Google Gemini ─────────────────────────────────────────────────────
# Free API key from Google AI Studio: https://aistudio.google.com/apikey
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

# NOTE: the embedding size (384) is baked into supabase_schema.sql
# (vector(384)). Changing EMBEDDING_MODEL or EMBEDDING_DIM also requires
# updating the schema and re-uploading every document, because vectors
# from different models (or sizes) can't be compared with each other.
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIM = 384

# Chat model. Any Gemini model your AI Studio key can use works here;
# override with the GENERATION_MODEL env var (e.g. "gemini-3.5-flash-lite"
# for a lighter, faster model).
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gemini-3.5-flash-lite")
# Vision model used to read scanned PDF pages and images (OCR). It must accept
# image input; defaults to the chat model.
OCR_MODEL = os.getenv("OCR_MODEL", GENERATION_MODEL)


# ── App settings ──────────────────────────────────────────────────────
# Comma-separated list of allowed CORS origins; defaults to "*" for local dev.
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to *default* on missing/invalid values."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Maximum accepted upload size on the Free plan (bytes).
MAX_UPLOAD_BYTES: int = _env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── Retrieval ─────────────────────────────────────────────────────────
# Hybrid search fetches RETRIEVAL_CANDIDATES chunks, an optional LLM rerank
# step keeps the best RETRIEVAL_TOP_K for the answer prompt.
RETRIEVAL_CANDIDATES: int = _env_int("RETRIEVAL_CANDIDATES", 15)
RETRIEVAL_TOP_K: int = _env_int("RETRIEVAL_TOP_K", 6)
RERANK_ENABLED: bool = _env_bool("RERANK_ENABLED", True)
# Chunks pulled from EACH document when several documents are compared.
COMPARE_CHUNKS_PER_DOC: int = _env_int("COMPARE_CHUNKS_PER_DOC", 4)
MAX_COMPARE_DOCS: int = _env_int("MAX_COMPARE_DOCS", 4)

# ── Ingestion ─────────────────────────────────────────────────────────
MAX_PAGES_PER_DOC: int = _env_int("MAX_PAGES_PER_DOC", 400)
# Scanned pages are read with the vision model; cap how many per document
# so a huge scan can't burn through the free-tier quota.
MAX_OCR_PAGES: int = _env_int("MAX_OCR_PAGES", 30)
# Pages with fewer extracted characters than this are treated as scanned.
OCR_MIN_CHARS: int = _env_int("OCR_MIN_CHARS", 25)
# Cap on characters kept from non-PDF sources (DOCX / TXT / web pages).
MAX_TEXT_CHARS: int = _env_int("MAX_TEXT_CHARS", 2_000_000)
MAX_URL_BYTES: int = _env_int("MAX_URL_MB", 10) * 1024 * 1024
# How the server identifies itself when importing web pages. Several sites
# (Wikipedia, for one) refuse requests that don't say who is asking; set this
# to your own deployment's URL / contact if you run the app publicly.
URL_FETCH_USER_AGENT: str = os.getenv(
    "URL_FETCH_USER_AGENT",
    "DocuQuery/1.0 (+https://github.com/zaaramedamin/DocuQuery; document Q&A tool)",
)

# ── Per-user quotas & rate limits ─────────────────────────────────────
# The values below are the FREE plan. The Pro plan's are further down.
MAX_DOCS_PER_USER: int = _env_int("MAX_DOCS_PER_USER", 25)
MAX_STORAGE_BYTES_PER_USER: int = _env_int("MAX_STORAGE_MB_PER_USER", 200) * 1024 * 1024
DAILY_QUERY_LIMIT: int = _env_int("DAILY_QUERY_LIMIT", 200)

# ── Pro plan ──────────────────────────────────────────────────────────
# Files are read page by page (text is extracted here, scanned pages are sent to
# Gemini one image at a time), so Gemini's own request-size limit is never hit by
# the upload size. These caps just keep memory and processing time bounded.
PRO_MAX_UPLOAD_BYTES: int = _env_int("PRO_MAX_UPLOAD_MB", 50) * 1024 * 1024
PRO_MAX_DOCS_PER_USER: int = _env_int("PRO_MAX_DOCS_PER_USER", 250)
PRO_MAX_STORAGE_BYTES_PER_USER: int = _env_int("PRO_MAX_STORAGE_MB_PER_USER", 5120) * 1024 * 1024
PRO_DAILY_QUERY_LIMIT: int = _env_int("PRO_DAILY_QUERY_LIMIT", 2000)
PRO_MAX_OCR_PAGES: int = _env_int("PRO_MAX_OCR_PAGES", 150)
# Price shown in the app for Pro (USD cents per month). Nothing is charged.
PRO_PRICE_CENTS: int = _env_int("PRO_PRICE_CENTS", 1000)

# ── Rate limits ───────────────────────────────────────────────────────
# "<requests>/<seconds>" windows, tracked in memory per process.
RATE_LIMIT_QUERY: tuple[int, int] = (_env_int("RATE_LIMIT_QUERY_PER_MIN", 20), 60)
RATE_LIMIT_UPLOAD: tuple[int, int] = (_env_int("RATE_LIMIT_UPLOAD_PER_HOUR", 20), 3600)
RATE_LIMIT_AUTH: tuple[int, int] = (_env_int("RATE_LIMIT_AUTH_PER_MIN", 10), 60)
RATE_LIMIT_SHARE: tuple[int, int] = (_env_int("RATE_LIMIT_SHARE_PER_HOUR", 60), 3600)
# Opening share links (public, so limited per IP address).
RATE_LIMIT_SHARED_VIEW: tuple[int, int] = (_env_int("RATE_LIMIT_SHARED_VIEW_PER_MIN", 60), 60)
# Password-reset emails per address / per IP per hour (stops mail-bombing someone).
RATE_LIMIT_RESET: tuple[int, int] = (_env_int("RATE_LIMIT_RESET_PER_HOUR", 5), 3600)
# Public site address, used for the "reset password" link in emails. Optional: it
# must also be listed under Supabase -> Authentication -> URL Configuration.
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "").rstrip("/")

# ── Pro plan switch ───────────────────────────────────────────────────
# There is no payment provider: "Upgrade to Pro" just switches the signed-in account to
# Pro, as a demonstration. Set BILLING_DEMO_MODE=false to turn that off.
BILLING_DEMO_MODE: bool = _env_bool("BILLING_DEMO_MODE", True)

if not GEMINI_API_KEY:
    print(
        "Warning: GEMINI_API_KEY is not set. The application will fail to run queries.",
        file=sys.stderr,
    )

# The free AI Studio tier has low per-minute limits, so retry rate-limited
# (429) and temporarily unavailable (5xx) requests with exponential backoff
# instead of failing on the first hit.
gemini_client: genai.Client | None = (
    genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=5,
                initial_delay=2.0,
                max_delay=30.0,
                http_status_codes=[429, 500, 502, 503, 504],
            )
        ),
    )
    if GEMINI_API_KEY
    else None
)

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
