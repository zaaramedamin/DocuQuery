# DocuQuery: Intelligent Document QA Engine (RAG)

A professional full-stack Document Query Engine (Retrieval-Augmented Generation) built using a **React 19 + TypeScript** frontend, **FastAPI** backend, **Supabase** (PostgreSQL with `pgvector`), and the **Google Gemini API** (free tier via Google AI Studio).

This project turns your documents — PDFs (including scans), Word files, text and Markdown, images and web pages — into a private, searchable knowledge base. It indexes them page by page, stores dense vector embeddings in Supabase, and uses a Large Language Model to answer natural-language questions with page-level source citations.

<p align="center">
  <img src="docs/demo.gif" width="900" alt="DocuQuery demo: signing in, uploading three files, grouping sources in a folder, asking a question and getting a cited answer, opening the cited page, comparing two handbooks, switching to the dark theme, the Free-plan file limit offering Pro, and searching past chats">
</p>
<p align="center">
  Upload files, group them in folders, ask questions with page citations, open the cited page, compare documents, switch themes, try the Pro plan and search past chats.
  <br>
  <a href="docs/demo.mp4">Watch in full quality (MP4, 90 seconds)</a>
</p>

---

## Features

**Search & answers**
- **Hybrid retrieval**: vector (meaning) search and keyword search run together in Postgres and are fused with Reciprocal Rank Fusion, then an LLM re-ranks the candidates. Exact terms, names and numbers are found as reliably as paraphrases.
- **Page-aware citations**: every answer lists the exact pages it came from; click a citation to open the source at that page.
- **Compare documents**: select 2–4 sources and ask how they differ — each source is represented in the answer.
- **Streaming answers** with **Stop**, **Regenerate** and **Copy** controls.

**Sources**
- **Many file types**: PDF, Word, **PowerPoint** (one page per slide, speaker notes included), **Excel** and **CSV** (rows become searchable `column: value` text), text, Markdown, images (PNG/JPG/WEBP) and **web page links**.
- **Pages that can't be fetched**: paste the text you copied, or use the one-click **browser button** to send the page you're looking at from your own browser (see below).
- **OCR for scans**: scanned PDF pages and images are read with the Gemini vision model.
- **Summary on upload**: each source gets an AI summary and suggested starter questions.
- **Live upload progress** for every stage (reading, OCR, embedding, summarizing), with multi-file queueing.

**Accounts & history**
- **Private libraries**: sign up / sign in with Supabase Auth; documents, chats and vectors are visible only to their owner.
- **Forgot password**: emailed reset link and a new-password screen.
- **Saved chat history**: reopen, rename or delete past conversations, and **search across all of them**.
- **Sharing by link**: share a chat (anyone can read it) or a source (a signed-in recipient can add their own copy). Links can be switched off at any time.
- **Folders**: select sources, **Move to folder** and name it; folders collapse, rename, and can be searched on their own.
- **Tags**: label sources, filter the library by tag, and ask questions across everything with a tag.
- **Export** any conversation as Markdown or PDF.
- **Quotas & rate limits** protect your API budget (sources per user, storage, questions per day, requests per minute).

**Plans & payments**
- **Free and Pro plans.** Free accepts files up to **10 MB**; a bigger file shows an alert that offers **Pro** (50 MB files, 250 sources, 5 GB, 2,000 questions a day). An **Upgrade to Pro** button sits in the top bar.
- **Pro is a demonstration**: *Upgrade to Pro* switches your account to Pro with no payment (the page says $10/month, nothing is charged), and *Switch to Free* goes back. There is no payment provider.

**Settings & personalization**
- **Settings** (gear icon): General, Personalization, Account, Plan & usage and Data controls.
- **Language**: English and French interface (follows the browser by default), and the language the assistant **answers** in (15 languages).
- **Appearance**: light, dark or follow the device. **Answer length** (concise / balanced / detailed), **response style**, and **custom instructions** the assistant always follows.
- **Account**: display name, change password, export all your data as JSON, delete all chats, delete all sources, or delete the account.
- **Notifications**: pop-ups confirm changes and report problems, and our own confirmation dialogs replace the browser's.

**Engineering**
- **React 19 + TypeScript UI**: a quiet workspace in light or dark (icon rail, top bar, chat, library panel), Geist type, response styles (Normal, Casual, Explanatory, Formal), drawers on tablets and phones, drag-and-drop.
- **Tested**: pytest suite for the API and a vitest suite for the frontend, run in CI on every push.
- **Fully containerized**: Docker and Docker Compose, deployable on Render + Vercel.

---

## Architecture

```
                                      +-------------------------+
                                      |     React 19 Frontend   |
                                      |   (TypeScript / Vite)   |
                                      +------------+------------+
                                                   |
                                           HTTPS API Calls
                                                   |
                                                   v
                                      +-------------------------+
                                      |     FastAPI Backend     |
                                      +-----+------------+------+
                                            |            |
                     Vector Embeddings & QA |            | Document & Vector Database
                                            v            v
                               +-----------------+  +-----------------+
                               |  Google Gemini  |  |    Supabase     |
                               |       API       |  | (Postgres Vector)|
                               +-----------------+  +-----------------+
```

- **Embedding Model**: `gemini-embedding-2` (384-dimensional dense vectors)
- **Generative Model**: `gemini-3.8-flash` (override via the `GENERATION_MODEL` env var). Both models are available on the free tier of [Google AI Studio](https://aistudio.google.com/apikey). Note that on the free tier, Google may use prompts and uploaded document text to improve its products.

---

## Directory Structure

```
├── backend/
│   ├── routes/
│   │   ├── auth.py          # Sign up / sign in / refresh (via Supabase Auth)
│   │   ├── documents.py     # Upload (files + URLs, streamed progress), view, delete
│   │   ├── query.py         # RAG query endpoint (SSE streaming) + feedback
│   │   ├── conversations.py # Saved chat history + search
│   │   ├── shares.py        # Share links for chats and sources
│   │   ├── folders.py       # Put sources in named folders
│   │   ├── billing.py       # Demo switch between the Free and Pro plans
│   │   └── account.py       # Usage + plan, profile, settings, password, export, deletion
│   ├── services/
│   │   ├── db_service.py    # Data access layer (every query is scoped to the user)
│   │   ├── ingest.py        # extract → chunk → embed → summarize → store pipeline
│   │   ├── extractors.py    # DOCX / TXT / MD / image text extraction + OCR
│   │   ├── url_fetch.py     # SSRF-safe web page fetching and HTML → text
│   │   ├── retrieval.py     # Query rewrite, hybrid search, LLM re-rank, compare mode
│   │   ├── summarizer.py    # Document summary + suggested questions
│   │   ├── rag_service.py   # Embeddings and text chunking
│   │   ├── llm.py           # Shared Gemini helpers
│   │   ├── file_store.py    # Original-file storage (disk cache + Supabase Storage)
│   │   ├── plans.py         # Free / Pro limits and which plan a user is on
│   │   ├── user_settings.py # Per-user preferences and what they add to the prompt
│   │   └── rate_limit.py    # Sliding-window rate limiter
│   ├── tests/               # pytest suite (no network, no real credentials)
│   ├── security.py          # Bearer-token authentication dependency
│   ├── config.py            # Configuration and external client initializations
│   ├── main.py              # FastAPI application and routing
│   └── requirements.txt     # Python dependencies (including pytest for the tests)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── AuthScreen.tsx   # Sign in / create account / forgot password
│   │   │   ├── ResetPasswordScreen.tsx # New password after the emailed link
│   │   │   ├── Dialogs.tsx      # Share, paste-text, browser-import and folder dialogs
│   │   │   ├── SettingsDialog.tsx # General, Personalization, Account, Plan & usage, Data controls
│   │   │   ├── UpgradeDialog.tsx  # Free vs Pro and the demo upgrade button
│   │   │   ├── Notifications.tsx  # Toast pop-ups and the confirmation dialog
│   │   │   ├── SharedView.tsx   # The page behind a share link
│   │   │   ├── Rail.tsx         # Icon rail: new chat, history, library, usage, style, account
│   │   │   ├── TopBar.tsx       # Scope and response-style pills, breadcrumb, share, new chat
│   │   │   ├── ChatPanel.tsx    # Questions, source cards, answers, composer
│   │   │   ├── LibraryPanel.tsx # Add sources, library with tags, suggested tasks and questions
│   │   │   ├── HistoryPanel.tsx # Chat history flyout with search
│   │   │   └── SourceViewer.tsx # PDF, image and text source viewer
│   │   ├── i18n/                # English / French translations (the English text is the key)
│   │   ├── preferences.ts       # Language, theme, answer style… kept on this device and on the account
│   │   ├── utils/               # Formatting, conversation export, upload-size checks
│   │   ├── hooks/               # Upload queue, notifications, click-outside dismissal
│   │   ├── App.tsx              # Page routing (share links, password reset) and top-level state
│   │   ├── api.ts               # API client: sessions, token refresh, streamed uploads
│   │   └── types.ts             # Shared TypeScript types
│   ├── vite.config.ts           # Dev proxy + vitest settings
│   └── package.json
├── .github/workflows/ci.yml     # Backend tests + frontend lint, tests and build
├── docker-compose.yml           # Orchestration for the FastAPI web service container
├── Dockerfile                   # Multi-stage production container setup
├── supabase_schema.sql          # Database schema (safe to re-run to upgrade)
└── README.md
```

---

## Getting Started

### Configuration

Copy `.env.example` to `.env` in the root directory and fill in your values:

```env
# Google AI Studio API key (Required) — free at https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Supabase Credentials (Required)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-service-role-key

# Optional hardening
# ALLOWED_ORIGINS=https://your-frontend.vercel.app   # CORS allow-list (default: *)

# Plan limits (defaults shown). FREE plan:
# MAX_UPLOAD_MB=10                # largest file; a bigger one offers the Pro upgrade
# MAX_DOCS_PER_USER=25            # sources per account
# MAX_STORAGE_MB_PER_USER=200     # total upload size per account
# DAILY_QUERY_LIMIT=200           # questions per account per day (UTC)
# MAX_OCR_PAGES=30                # scanned pages read per document
# PRO plan:
# PRO_MAX_UPLOAD_MB=50
# PRO_MAX_DOCS_PER_USER=250
# PRO_MAX_STORAGE_MB_PER_USER=5120
# PRO_DAILY_QUERY_LIMIT=2000
# PRO_MAX_OCR_PAGES=150
# PRO_PRICE_CENTS=1000            # shown in the app and charged: $10 per month

# Pro is a demo (no payment). Set to false to hide the working Upgrade button:
# BILLING_DEMO_MODE=true
# RATE_LIMIT_QUERY_PER_MIN=20     # questions per minute per account
# RATE_LIMIT_UPLOAD_PER_HOUR=20   # uploads per hour per account
# RATE_LIMIT_AUTH_PER_MIN=10      # sign-in attempts per minute per IP
# RATE_LIMIT_RESET_PER_HOUR=5     # password-reset emails per address per hour
# RATE_LIMIT_SHARE_PER_HOUR=60    # share links created per account per hour
# RATE_LIMIT_SHARED_VIEW_PER_MIN=60  # share-link page views per IP per minute
# FRONTEND_URL=https://your-app.vercel.app  # where password-reset links point (also add it in Supabase)

# Optional retrieval / ingestion tuning (defaults shown)
# RERANK_ENABLED=true             # LLM re-rank step (one extra model call per question)
# RETRIEVAL_CANDIDATES=15         # chunks fetched before re-ranking
# RETRIEVAL_TOP_K=6               # chunks sent to the answer prompt
# URL_FETCH_USER_AGENT=...        # how web-page imports identify themselves (set your own contact URL)
# OCR_MODEL=                      # vision model for OCR (defaults to GENERATION_MODEL)
```

> ⚠️ The `.env` file is git-ignored — never commit real credentials.
>
> `SUPABASE_KEY` must be the **service-role / secret** key (not the public anon key). The backend uses it to enforce each user's privacy itself, and the database's row-level security blocks everyone else.

### Database Migration

Before starting the application, you must run the database migration to configure Supabase:
1. Open your **Supabase Dashboard** for your project.
2. Go to the **SQL Editor** from the left navigation panel.
3. Click **New query**, paste the entire contents of the `supabase_schema.sql` file, and click **Run**.
4. This enables the `vector` extension and creates the `document_chunks`, `documents` (with folders and tags), `conversations`, `messages`, `shares`, `profiles` (name, plan, preferences) and `feedback` tables, the HNSW and full-text indexes, the `hybrid_search` function, row-level security policies, and the private `documents` storage bucket.
5. The script is idempotent: **re-run it whenever you pull an update** to upgrade an existing database.

### Accounts (Supabase Auth)

> **Password reset** sends an email through Supabase. Its built-in sender is limited to a handful of emails per hour and is meant for testing, so for real use configure your own SMTP provider under **Authentication → Emails → SMTP Settings**. Also add your site's address (for example `http://localhost:5173` while developing, and your Vercel URL in production) under **Authentication → URL Configuration → Redirect URLs**; the reset link only works for addresses listed there.

Sign-in uses Supabase Auth with email + password, which is enabled by default. In the dashboard under **Authentication → Providers → Email** you can choose whether new users must confirm their email address first (recommended in production; turn it off for quick local testing).

> **Upgrading from the single-user version?** Old documents have no owner and won't appear. See the commented "adopt documents uploaded before accounts existed" block at the bottom of `supabase_schema.sql` to assign them to your new account.

---

## Running the Application

### Option A: Using Docker Compose (Easiest)

This command automatically builds the FastAPI web container and starts the application.

1. Ensure Docker is running.
2. In your terminal, run:
   ```bash
   docker compose up --build
   ```
3. Open your browser and navigate to: **`http://localhost:8000`**

---

### Option B: Running Locally (Development Mode)

To run the application locally with hot-reloading for the frontend:

#### 1. Start the Backend
From the `backend` folder, use its virtual environment to launch FastAPI:
```bash
cd backend
rag-env\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```
The backend API is now running at `http://localhost:8000`.

#### 2. Start the Frontend
In a new terminal window, navigate to the `frontend` folder, install packages, and start the Vite server:
```bash
cd frontend
npm install
npm run dev
```
Open your browser and navigate to the Vite development address: **`http://localhost:5173`**. Any API calls will be proxied to the backend on port 8000 automatically.

#### 3. Production Build (Optional)
If you want FastAPI to serve the React pages directly on `http://localhost:8000` without running Vite:
```bash
cd frontend
npm run build
```
FastAPI detects the `frontend/dist` bundle on start and serves the build.

---

### Free and Pro plans (demo)

Every account starts on **Free** (files up to 10 MB). **Pro** raises the limits (50 MB files, 250 sources, 5 GB, 2,000 questions a day). There is **no payment provider**: *Upgrade to Pro* simply switches the signed-in account to Pro, and *Settings → Plan & usage → Switch to Free* switches it back. The page shows "$10 / month" but nothing is charged. The limits are read when a request is made, so changing them in `.env` needs only a restart.

Set `BILLING_DEMO_MODE=false` to turn the switch off (the dialog then says upgrading isn't available). Remember that while it is on, **any user can give themselves Pro**; that is fine for a demo, not for a paid product.

Why 10 MB? Files are read page by page: text is extracted on the server and only small pieces (a page of text, one scanned page as an image) go to Gemini, so Gemini's request limits are never reached. The cap keeps memory and processing time bounded.

### Importing web pages

Paste a link into the Sources tab to index a page. Plain HTML pages work well (Wikipedia, documentation, news, blogs). Links to private, internal or localhost addresses are blocked on purpose.

Some sites refuse automated requests (Stack Overflow, Medium, the New York Times…) and others build their content with JavaScript (Reddit…), so the server sees nothing to read. DocuQuery does not try to get around those protections. Instead, you add the page **from your own browser**, where you can already read it:

- **Paste text** — open the page, copy the text, click *Paste text instead* and paste it.
- **Browser button** — in the *Paste text* dialog, drag **Add to DocuQuery** to your bookmarks bar. Click it on any page (including logged-in or paywalled pages you have access to) and DocuQuery shows what it received and asks before adding it. The page text is sent directly from your browser to your own DocuQuery; nothing goes through a third party.

### Sharing, tags and chat search

- **Share a chat** (Share button in the chat header): creates a link anyone can open to *read* the conversation, no account needed. It shows your questions, the answers and which pages were cited, never your documents.
- **Share a source** (share icon on a source): a signed-in recipient who opens the link can **add their own copy** to their library. Copies are independent, so deleting yours doesn't affect theirs.
- Turn a link off with **Stop sharing**; the old link stops working at once, and sharing again makes a new one.
- **Folders**: tick one or more sources and press **Move to folder**. Type a name (or pick an existing folder) and they are grouped under it. A folder collapses, can be renamed, and its message icon makes questions search **only that folder**. Removing a folder keeps its sources.
- **Tags**: use the tag icon on a source to label it. Click a tag chip to filter the library and to ask questions across every source with that tag. (Selecting individual sources still takes priority, and selecting 2–4 compares them.)
- **Search chats**: the box on the Chats tab searches the titles and messages of every saved conversation.

## Deploying (Render + Vercel)

The backend is a Docker service on **Render** ([`render.yaml`](render.yaml) is a ready-made blueprint) and the frontend is a static site on **Vercel**. The Docker image also contains the built frontend, so the Render URL alone is already a working app.

1. **Supabase:** run [`supabase_schema.sql`](supabase_schema.sql) in the SQL editor (safe to run again, and do it *before* each update that changes the schema). Under *Authentication → URL Configuration* set the **Site URL** to your frontend and add it to **Redirect URLs**.
2. **Render:** *New + → Blueprint* and pick this repository. Set `SUPABASE_URL`, `SUPABASE_KEY` (the *service_role* key) and `GEMINI_API_KEY`. Then set `ALLOWED_ORIGINS` and `FRONTEND_URL` to your frontend URL (no trailing slash). Check `https://<backend>/api/health` answers `{"status":"ok"}`.
3. **Vercel:** import the repository with **Root Directory** `frontend` and set `VITE_API_URL` to the Render URL (no trailing slash, no `/api`). Redeploy whenever you change it, because it is read at build time.
4. **Update later:** run the schema, `git push`, and both hosts redeploy. Use Render's *Deploys → Rollback* to go back (schema changes are additive, so an older backend keeps working).

Troubleshooting: an empty library or "schema is out of date" means the schema was not run; CORS errors mean `ALLOWED_ORIGINS` is not the exact frontend URL; 401/503 after signing in usually means `SUPABASE_KEY` is the anon key instead of *service_role*; the free Render plan sleeps, so the first request can take about 50 seconds. The environment variables are listed under *Configuration* above.

## Testing

```bash
# Backend (from the backend folder). Uses fakes: no network, no real credentials.
cd backend
rag-env\Scripts\python.exe -m pip install -r requirements.txt
rag-env\Scripts\python.exe -m pytest

# Frontend
cd frontend
npm test          # unit tests (vitest)
npm run lint
npm run build     # type-check + production build
```

GitHub Actions runs all of the above on every push and pull request ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
