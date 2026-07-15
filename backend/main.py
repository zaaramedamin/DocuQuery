"""
Application entry-point.

Creates the FastAPI app, registers route modules, and configures
static-file serving for the React production build.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Import config first so env/clients are initialized
import backend.config  # noqa: F401
from backend.routes.documents import router as documents_router
from backend.routes.query import router as query_router

app = FastAPI(title="DocuQuery – Document QA Engine")

# ── CORS ──────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ─────────────────────────────────────────────
app.include_router(documents_router)
app.include_router(query_router)

# ── Static file serving (React production build) ─────────────────────
# When running `uvicorn backend.main:app` from the project root,
# the CWD is the project root, so "frontend/dist" resolves correctly.
_frontend_dist = os.path.join("frontend", "dist")

if os.path.isdir(_frontend_dist):
    _assets_dir = os.path.join(_frontend_dist, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

    @app.get("/{rest_of_path:path}")
    def serve_spa(rest_of_path: str):
        file_path = os.path.join(_frontend_dist, rest_of_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # SPA fallback
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
