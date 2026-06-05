# Sentinel API — FastAPI + uvicorn, served on Cloud Run.
#
# Build:   docker build -t sentinel-api .
# Run:     docker run --rm -p 8080:8080 -e PORT=8080 sentinel-api
# Deploy:  see docs/deploy.md
#
# Lives at the repo root so ``gcloud builds submit --tag ...`` auto-finds
# it. The web frontend has its own Dockerfile at ``web/Dockerfile`` with
# its own build context.
#
# The image installs only the runtime dependency group (no pytest, no
# playwright). Source is copied AFTER deps so an unchanged dep set produces
# a cached layer on rebuilds.

ARG PYTHON_VERSION=3.10
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# uv — the project's package manager. Pin matches pyproject's expectation.
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first so changing application code doesn't bust
# the (much larger) deps layer. ``--no-install-project`` skips building
# the sentinel package itself (which would otherwise require LICENSE +
# sentinel/ + evals/ during the sync); we run uvicorn against the source
# in CWD instead of as an installed wheel.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen --no-install-project 2>/dev/null \
    || uv sync --no-dev --no-install-project

# Application code (no editable install — uvicorn imports from CWD).
COPY sentinel ./sentinel
COPY evals ./evals
COPY LICENSE ./LICENSE

# Cloud Run injects $PORT; default to 8080 so the image runs locally too.
ENV PORT=8080
EXPOSE 8080

# Run uvicorn directly from the venv built by uv. ``exec`` form so SIGTERM
# reaches uvicorn (Cloud Run needs graceful shutdown to bleed in-flight
# SSE streams). PYTHONPATH=/app lets uvicorn import ``sentinel.api.main``
# without an editable install.
ENV PYTHONPATH=/app
CMD ["sh", "-c", "/app/.venv/bin/uvicorn sentinel.api.main:app --host 0.0.0.0 --port ${PORT}"]
