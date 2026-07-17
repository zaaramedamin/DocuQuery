# Deployment Guide – DocuQuery

Follow these instructions to deploy the DocuQuery RAG Document QA Engine to production. We will host the **FastAPI Backend on Render** (via Docker to satisfy all binary dependencies) and the **React Frontend on Vercel**.

---

## Part 1: Deploying the Backend on Render

Deploying the backend as a Docker container on Render is highly recommended, as it automatically configures all native system library requirements for `PyMuPDF` (the PDF processing engine).

### Step-by-Step:
1. Push your repository to **GitHub**, **GitLab**, or **Bitbucket**.
2. Log in to **[Render](https://render.com/)** and click **New +** → **Web Service**.
3. Connect your Git repository.
4. Configure the service settings:
   - **Name**: `docuquery-backend` (or similar)
   - **Environment**: **`Docker`** (Render will automatically detect your `Dockerfile`)
   - **Region**: Select the region closest to you
   - **Branch**: `main` (or your active branch)
   - **Plan**: Select **`Free`** (or your preferred tier)
5. Click **Advanced** and add the following **Environment Variables**:
   - `SUPABASE_URL`: Your Supabase Project URL (e.g. `https://your-project-id.supabase.co`)
   - `SUPABASE_KEY`: Your Supabase secure `service_role` secret key (starts with `sb_secret_` or `eyJ...`)
   - `HF_TOKEN`: Your Hugging Face access token (starts with `hf_...`)
6. Click **Create Web Service**. 
7. Once the deploy finishes, copy your backend URL (e.g. `https://docuquery-backend.onrender.com`).

---

## Part 2: Deploying the Frontend on Vercel

Vercel is the ideal host for the React + TypeScript frontend.

### Step-by-Step:
1. Log in to **[Vercel](https://vercel.com/)** and click **Add New** → **Project**.
2. Import your Git repository.
3. Configure the Project settings:
   - **Framework Preset**: **`Vite`** (automatically detected)
   - **Root Directory**: Select **`frontend`** (click Edit, navigate to `frontend`, and select it)
   - **Build Command**: `npm run build` (default)
   - **Output Directory**: `dist` (default)
4. Under **Environment Variables**, add:
   - **Key**: `VITE_API_URL`
   - **Value**: Your Render backend URL copied from Part 1 (e.g., `https://docuquery-backend.onrender.com`)
   > [!IMPORTANT]
   > Do **not** append a trailing slash `/` or `/api` to the `VITE_API_URL`. Ensure it reads exactly like `https://docuquery-backend.onrender.com`.
5. Click **Deploy**.
6. Vercel will build the frontend and serve it at a public URL (e.g. `https://docuquery-frontend.vercel.app`).

---

## Environment Variable Checklist

### Backend Env (Render Dashboard)
| Key | Value Description |
| :--- | :--- |
| `SUPABASE_URL` | Your Supabase Project REST endpoint |
| `SUPABASE_KEY` | Supabase private `service_role` token |
| `HF_TOKEN` | Hugging Face Read access token |

### Frontend Env (Vercel Dashboard)
| Key | Value Description |
| :--- | :--- |
| `VITE_API_URL` | The public URL of your Render backend |

---

## How It Works in Production
- The frontend loads environmental settings during the build stage. When fetching `/api/query` or `/api/documents`, it targets `VITE_API_URL` directly.
- The `vercel.json` rewrite configuration handles SPA fallback routing so you can reload individual sub-pages without getting `404 Not Found` errors.
