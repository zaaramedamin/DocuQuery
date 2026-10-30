# ── Stage 1: build the React frontend ────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /build/dist ./frontend/dist

EXPOSE 8000

# Bind to the port the host provides ($PORT on Render), defaulting to 8000
# for local runs. `exec` keeps uvicorn as PID 1 so it receives stop signals.
# --proxy-headers / --forwarded-allow-ips: the app sits behind the host's load
# balancer (Render, etc.). Trusting its X-Forwarded-For header lets the per-IP
# sign-in rate limit see each visitor's real address instead of the proxy's.
WORKDIR /app/backend
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
