"""FastAPI app factory.

Mount this with uvicorn:
    uvicorn sentinel.api.main:app --reload --port 8000
"""

from __future__ import annotations

from dotenv import load_dotenv

# Load .env BEFORE any sentinel imports so Vertex AI config
# (GOOGLE_CLOUD_PROJECT, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_LOCATION) is in
# the environment by the time the ADK Client is constructed.
load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from sentinel.api.incidents import router as incidents_router  # noqa: E402
from sentinel.observability.instrumentation import setup_tracing  # noqa: E402

setup_tracing()


def create_app() -> FastAPI:
    """Build the FastAPI app with CORS, the incidents router, and a health endpoint."""
    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        description="HTTP + SSE wrapper around the Sentinel five-agent pipeline.",
    )
    # Permissive CORS for local dev. The Next.js dev server runs on 3000.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(incidents_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Simple liveness probe — returns `{'status': 'ok'}`."""
        return {"status": "ok"}

    return app


app = create_app()
