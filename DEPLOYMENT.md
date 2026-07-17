# Deployment Guide – DocuQuery

This deploys the app as two services:

- **Backend (FastAPI)** on **Render**, as a Docker container.
- **Frontend (React + Vite)** on **Vercel**, as a static site pointed at the Render API.

The backend also serves a built copy of the frontend at its own URL, which is
handy for smoke-testing the API in a browser. Vercel is the production frontend.

---

## Prerequisites

1. A **Supabase** project with the schema applied. Open the SQL Editor, paste the
   full contents of [`supabase_schema.sql`](./supabase_schema.sql), and run it.
   This creates the `document_chunks` and `feedback` tables, the vector index,
   the `match_documents` / `list_document_filenames` RPCs, and the private
   `documents` storage bucket (which keeps uploaded PDFs durable across
   redeploys — Render's free disk is ephemeral).
2. A **Hugging Face** access token with the *"Make calls to Inference Providers"*
   permission, and at least one provider enabled that serves the chat model
   (see [Inference Providers settings](https://huggingface.co/settings/inference-providers)).
3. Your code pushed to **GitHub / GitLab / Bitbucket**.

---

## Part 1: Backend on Render

The repo ships a [`render.yaml`](./render.yaml) blueprint, so you can either use
**New + → Blueprint** (Render reads the file) or configure a Web Service manually.

### Using the Blueprint (recommended)
1. In Render, click **New + → Blueprint** and connect your repository.
2. Render detects `render.yaml` and proposes the `docuquery-backend` service.
3. Fill in the environment variables it marks as required (see the table below).
4. Click **Apply**. Render builds the Docker image and deploys.

### Manual setup (alternative)
- **Environment**: `Docker` (auto-detects the `Dockerfile`)
- **Health Check Path**: `/api/health`
- **Plan / Region**: your choice (`render.yaml` defaults to `free` / `frankfurt`)

### Backend environment variables

| Key | Required | Description |
| :--- | :--- | :--- |
| `SUPABASE_URL` | ✅ | Your Supabase project REST endpoint |
| `SUPABASE_KEY` | ✅ | Supabase `service_role` secret key |
| `HF_TOKEN` | ✅ | Hugging Face access token |
| `ALLOWED_ORIGINS` | ⬜ | Comma-separated allow-list, e.g. your Vercel URL. Defaults to `*` |
| `GENERATION_MODEL` | ⬜ | Override the default `meta-llama/Llama-3.1-8B-Instruct` |
| `MAX_UPLOAD_MB` | ⬜ | Max PDF upload size (default `25`) |

> The container binds to the `PORT` Render provides automatically — no port
> config needed.

Once deployed, note the backend URL (e.g. `https://docuquery-backend.onrender.com`)
and confirm `https://<url>/api/health` returns `{"status":"ok"}`.

> **Free-tier note:** the service spins down after inactivity, so the first
> request after an idle period can take ~50 seconds while it wakes up. The UI
> shows a loading state during this.

---

## Part 2: Frontend on Vercel

1. In Vercel, **Add New → Project** and import your repository.
2. Configure:
   - **Framework Preset**: `Vite` (auto-detected)
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build` (default)
   - **Output Directory**: `dist` (default)
3. Under **Environment Variables**, add:
   - **Key**: `VITE_API_URL`
   - **Value**: your Render backend URL, with **no** trailing slash and **no**
     `/api` suffix — e.g. `https://docuquery-backend.onrender.com`
4. Click **Deploy**.

SPA routing is handled by [`frontend/vercel.json`](./frontend/vercel.json).

---

## Part 3: Lock down CORS (recommended)

Once you know the Vercel URL, set `ALLOWED_ORIGINS` on the Render service to it
(e.g. `https://docuquery.vercel.app`) and redeploy. This restricts the API to
your frontend instead of the permissive `*` default.

---

## How it works in production
- The Vercel frontend reads `VITE_API_URL` at build time and calls
  `<VITE_API_URL>/api/...` directly on Render.
- The Render backend embeds queries, runs vector search in Supabase, and streams
  the LLM answer back via Server-Sent Events.
- Uploaded PDFs are cached on the backend's local disk and mirrored to Supabase
  Storage, so citation previews keep working after a redeploy.

---

## Environment Variable Checklist

### Backend (Render)
`SUPABASE_URL`, `SUPABASE_KEY`, `HF_TOKEN` (required); `ALLOWED_ORIGINS`,
`GENERATION_MODEL`, `MAX_UPLOAD_MB` (optional).

### Frontend (Vercel)
`VITE_API_URL` — the public URL of your Render backend.
