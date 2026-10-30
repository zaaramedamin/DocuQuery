"""
Application entry-point.

Creates the FastAPI app, registers route modules, and configures
static-file serving for the React production build.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# Import config first so env/clients are initialized
from config import ALLOWED_ORIGINS
from routes.account import router as account_router
from routes.auth import router as auth_router
from routes.billing import router as billing_router
from routes.conversations import router as conversations_router
from routes.documents import router as documents_router
from routes.folders import router as folders_router
from routes.query import router as query_router
from routes.shares import router as shares_router
from services.plans import largest_upload_bytes

app = FastAPI(title="DocuQuery – Document QA Engine")


class UploadSizeLimitMiddleware:
    """
    Reject oversized uploads from their Content-Length header BEFORE the
    request body is read and buffered. This is only the server-wide ceiling (the
    biggest file any plan accepts); the route applies the signed-in user's own
    plan limit. (A plain ASGI middleware, so it does not interfere with
    streaming responses.)
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes + 1024 * 1024  # allow for multipart overhead

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/upload":
            for key, value in scope["headers"]:
                if key == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                    limit_mb = (self.max_bytes - 1024 * 1024) // (1024 * 1024)
                    response = JSONResponse(
                        {"detail": f"File too large (max {limit_mb} MB)."}, status_code=413
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


app.add_middleware(UploadSizeLimitMiddleware, max_bytes=largest_upload_bytes())

# ── CORS ──────────────────────────────────────────────────────────────
# Credentials are only allowed when explicit origins are configured:
# the "*" wildcard + credentials combination is rejected by browsers
# and would otherwise reflect any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ─────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(folders_router)
app.include_router(conversations_router)
app.include_router(query_router)
app.include_router(shares_router)
app.include_router(account_router)
app.include_router(billing_router)


# ── Health check (used by Render / uptime monitors) ──────────────────
@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# ── Static file serving (React production build) ─────────────────────
# Resolved relative to this file (backend/ -> ../frontend/dist) so it works
# no matter which directory uvicorn is started from.
_frontend_dist = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
)

if os.path.isdir(_frontend_dist):
    _assets_dir = os.path.join(_frontend_dist, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

    @app.get("/{rest_of_path:path}")
    def serve_spa(rest_of_path: str):
        # Unknown API routes must 404 (as JSON), not fall through to the SPA.
        if rest_of_path == "api" or rest_of_path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        # Resolve and confine the path to the dist directory to prevent
        # path traversal (e.g. "/../.env").
        file_path = os.path.abspath(os.path.join(_frontend_dist, rest_of_path))
        if file_path.startswith(_frontend_dist + os.sep) and os.path.isfile(file_path):
            return FileResponse(file_path)
        # SPA fallback
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

