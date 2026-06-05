"""FastAPI app factory.

Mount this with uvicorn:
    uvicorn sentinel.api.main:app --reload --port 8000
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env BEFORE any sentinel imports so Vertex AI config
# (GOOGLE_CLOUD_PROJECT, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_LOCATION) is in
# the environment by the time the ADK Client is constructed.
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from sentinel.api.incidents import router as incidents_router  # noqa: E402
from sentinel.api.phase8_routes import router as phase8_router  # noqa: E402
from sentinel.observability.instrumentation import setup_tracing  # noqa: E402

setup_tracing()


_DEV_ORIGINS: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")


def _allowed_origins() -> list[str]:
    """Resolve the CORS allow-list.

    Reads ``SENTINEL_ALLOWED_ORIGINS`` (comma-separated) and unions it
    with the localhost dev origins. On Cloud Run, set this env var to the
    deployed web origin (e.g. ``https://sentinel-web-XXX.run.app``) so
    EventSource requests from the browser are not blocked. Wildcard
    ``*`` is intentionally NOT special-cased — keep it explicit.
    """
    extra = os.environ.get("SENTINEL_ALLOWED_ORIGINS", "")
    parsed = [o.strip() for o in extra.split(",") if o.strip()]
    # Preserve order, dedupe.
    seen: set[str] = set()
    out: list[str] = []
    for origin in (*_DEV_ORIGINS, *parsed):
        if origin not in seen:
            seen.add(origin)
            out.append(origin)
    return out


def create_app() -> FastAPI:
    """Build the FastAPI app with CORS, the incidents router, and a health endpoint."""
    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        description="HTTP + SSE wrapper around the Sentinel five-agent pipeline.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(incidents_router)
    app.include_router(phase8_router)  # Phase 8 / ADR-027 — additive routes

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Simple liveness probe — returns `{'status': 'ok'}`."""
        return {"status": "ok"}

    return app


app = create_app()
