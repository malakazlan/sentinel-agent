"""Phase 0 Streamlit UI — single input, single response, single trace into Phoenix."""

from __future__ import annotations

import asyncio
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from sentinel.coordinator import run_coordinator  # noqa: E402  (load_dotenv must come first)
from sentinel.observability.instrumentation import setup_tracing  # noqa: E402

setup_tracing()

st.set_page_config(page_title="Sentinel — Phase 0", page_icon="🛡️", layout="centered")

st.title("Sentinel")
st.caption("Phase 0 hello-world — verifying OpenInference spans land in Phoenix.")

phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
st.info(f"Phoenix UI: {phoenix_endpoint}")

user_text = st.text_input(
    "Greet the Coordinator:",
    placeholder="hello",
    key="user_text",
)

if st.button("Send", type="primary", disabled=not user_text):
    with st.spinner("Coordinator thinking..."):
        try:
            response = asyncio.run(run_coordinator(user_text))
        except Exception as exc:  # surface failure into the UI instead of swallowing
            st.error(f"Coordinator failed: {exc}")
            st.exception(exc)
        else:
            st.markdown("**Coordinator:**")
            st.write(response or "_(empty response)_")
            st.success(
                f"Trace emitted. Open {phoenix_endpoint} and look in the "
                f"`{os.environ.get('PHOENIX_PROJECT_NAME', 'sentinel')}` project."
            )
