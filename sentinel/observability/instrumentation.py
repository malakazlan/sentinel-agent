"""OpenInference → Phoenix tracing setup for the Sentinel agent."""

from __future__ import annotations

import os

from openinference.instrumentation.google_adk import GoogleADKInstrumentor
from phoenix.otel import register

_DEFAULT_ENDPOINT = "http://localhost:6006"
_DEFAULT_PROJECT = "sentinel"

_initialized = False


def setup_tracing() -> None:
    """Wire OpenInference tracing for google-adk into the local Phoenix backend.

    Registers a Phoenix tracer provider that exports OTLP/HTTP spans to the
    Phoenix collector, and instruments the google-adk SDK so every LLM call,
    sub-agent dispatch, and tool invocation emits a span automatically.

    Reads ``PHOENIX_COLLECTOR_ENDPOINT`` and ``PHOENIX_PROJECT_NAME`` from the
    environment; falls back to ``http://localhost:6006`` and ``sentinel``.

    Idempotent: safe to call across Streamlit reruns in the same process.
    """
    global _initialized
    if _initialized:
        return

    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")
    project = os.environ.get("PHOENIX_PROJECT_NAME", _DEFAULT_PROJECT)

    tracer_provider = register(
        endpoint=f"{endpoint}/v1/traces",
        project_name=project,
        protocol="http/protobuf",
        auto_instrument=False,
    )
    GoogleADKInstrumentor().instrument(tracer_provider=tracer_provider)
    _initialized = True
