# DocuQuery: Intelligent Document QA Engine (RAG)

A professional full-stack Document Query Engine (Retrieval-Augmented Generation) built using a **React 19 + TypeScript** frontend, **FastAPI** backend, **Supabase** (PostgreSQL with `pgvector`), and **Hugging Face Serverless Inference API**.

This project processes uploaded PDF documents, segments the content page-by-page, generates dense vector embeddings, stores them in Supabase, and uses a state-of-the-art Large Language Model (LLM) to answer natural language questions with source citations.

---

## Features

- **Semantic Vector Search**: Answers questions based on meaning and content context, rather than simple keyword matches.
- **Page-Aware Source Citations**: Every response returns a list of source pages from the specific documents used to answer the query.
- **Supabase pgvector Persistence**: Uploaded documents and vectors are permanently cached in Supabase, avoiding redundant processing.
- **Dynamic Scope Filtering**: Select and query a single document, or query across your entire knowledge library.
- **React 19 + TypeScript UI**: A highly polished, glassmorphic dark-theme SPA featuring smooth file drag-and-drop, connection status badges, state-driven search scopes, and citation hover previews.
- **Vite-based Development**: Extremely fast hot-reloading using Vite with a local API proxy.
- **Fully Containerized**: Ready to run out-of-the-box using Docker and Docker Compose.

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
                               |  Hugging Face   |  |    Supabase     |
                               |  Serverless API |  | (Postgres Vector)|
                               +-----------------+  +-----------------+
```

- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional dense vectors)
- **Generative Model**: `Qwen/Qwen2.5-7B-Instruct` (Fast and accurate instruction-following)

---

## Directory Structure

```
├── backend/
│   ├── routes/
│   │   ├── documents.py   # Document upload and database CRUD endpoints
│   │   └── query.py       # RAG pipeline query execution endpoint
│   ├── services/
│   │   ├── db_service.py  # Data access layer for Supabase
│   │   └── rag_service.py # Pure logic for embeddings and similarity search
│   ├── config.py          # Configuration and external client initializations
│   ├── main.py            # FastAPI main application and routing
│   └── requirements.txt   # Python dependency list
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Sidebar.tsx    # Drag-and-drop zone & library controls
│   │   │   └── ChatPanel.tsx  # Dynamic conversation feed & scope triggers
│   │   ├── App.tsx        # Top-level composition shell
│   │   ├── api.ts         # Axios/fetch wrappers mapped to endpoints
│   │   ├── types.ts       # Shared TypeScript type definitions
│   │   └── index.css      # Core styles & dark theme definitions
│   ├── vite.config.ts     # Dev-proxy settings for the API
│   └── package.json       # React dependencies and scripts
├── docker-compose.yml     # Orchestration for FastAPI web service container
├── Dockerfile             # Multi-stage production container setup
├── supabase_schema.sql    # Database schema migration script
└── README.md              # Project documentation
```

---

## Getting Started

### Configuration

Copy `.env.example` to `.env` in the root directory and fill in your values:

```env
# Hugging Face User Access Token (Required)
HF_TOKEN=hf_your_token_here

# Supabase Credentials (Required)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-service-role-or-anon-key

# Optional hardening
# ALLOWED_ORIGINS=https://your-frontend.vercel.app   # CORS allow-list (default: *)
# MAX_UPLOAD_MB=25                                   # PDF upload size limit
```

> ⚠️ The `.env` file is git-ignored — never commit real credentials.

### Database Migration

Before starting the application, you must run the database migration to configure Supabase:
1. Open your **Supabase Dashboard** for your project.
2. Go to the **SQL Editor** from the left navigation panel.
3. Click **New query**, paste the entire contents of the `supabase_schema.sql` file, and click **Run**.
4. This will enable the `vector` extension, create the `document_chunks` and `feedback` tables, configure the HNSW index, register the matching / filename-listing RPC functions, and create the private `documents` storage bucket that keeps uploaded PDFs durable across redeploys.

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
Activate your Python virtual environment and launch FastAPI:
```bash
.\rag-env\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
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
