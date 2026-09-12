# Career Copilot — one image, one process, one port.
#
# The frontend is built in a throwaway Node stage and its output copied into
# the Python image, which serves it alongside the API. That is why there is no
# second container and no CORS configuration to keep in sync: the browser sees
# a single origin.
#
# Build:  docker build -t career-copilot .
# Run:    docker run -p 8000:8000 --env-file backend/.env career-copilot

# --------------------------------------------------------------------------- #
# Stage 1 — build the frontend
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS frontend

WORKDIR /build

# Copy manifests first so a source-only change doesn't reinstall node_modules.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --------------------------------------------------------------------------- #
# Stage 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.13-slim AS runtime

# PYTHONUNBUFFERED so logs reach the platform's collector immediately rather
# than sitting in a buffer; container logs that arrive late are worse than none.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr is only needed for screenshot ingestion. Drop this layer if you
# don't use that tab — it is most of the image size.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/
RUN pip install -r backend/requirements.txt \
    # Not in requirements.txt because local development defaults to SQLite.
    && pip install "psycopg[binary]==3.2.3"

COPY backend/ ./backend/

# main.py looks for ../../frontend/dist relative to app/, so the build has to
# land in the same relative position it occupies in the repo.
COPY --from=frontend /build/dist ./frontend/dist

# Run as a non-root user. Many platforms enforce this; all of them are safer
# for it.
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

WORKDIR /app/backend

EXPOSE 8000

# Honour the platform's $PORT when it sets one (Render, Railway, Fly and Heroku
# all do), falling back to 8000 locally. Shell form is required for the
# variable to expand.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
