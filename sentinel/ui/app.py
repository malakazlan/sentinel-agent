"""Phase 1 Streamlit UI — input, response, and an agent-reasoning sidebar that shows tool calls."""

from __future__ import annotations

import asyncio
import json
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from sentinel.coordinator import stream_coordinator  # noqa: E402
from sentinel.observability.instrumentation import setup_tracing  # noqa: E402

setup_tracing()

st.set_page_config(page_title="Sentinel — Phase 1", page_icon="🛡️", layout="wide")

# ── session state ──────────────────────────────────────────────────────────
if "agent_records" not in st.session_state:
    st.session_state.agent_records = []
if "agent_response" not in st.session_state:
    st.session_state.agent_response = ""
if "last_input" not in st.session_state:
    st.session_state.last_input = ""

phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
phoenix_project = os.environ.get("PHOENIX_PROJECT_NAME", "sentinel")


# ── stream consumer ────────────────────────────────────────────────────────
async def _consume(user_text: str) -> tuple[list[dict], str]:
    """Drain the Coordinator's event stream into a (records, final_text) pair."""
    records: list[dict] = []
    final_text = ""
    async for rec in stream_coordinator(user_text):
        records.append(rec)
        if rec["kind"] == "final":
            final_text += rec["text"]
    return records, final_text


def _render_record(rec: dict) -> None:
    kind = rec.get("kind")
    if kind == "tool_call":
        st.markdown(f"🔧 **{rec['tool']}**")
        st.code(json.dumps(rec.get("args", {}), indent=2), language="json")
    elif kind == "tool_result":
        st.markdown(f"⟵ result from `{rec['tool']}`")
        st.text(rec.get("result_excerpt", ""))
    elif kind == "assistant_text":
        st.markdown(f"💭 *{rec['text']}*")
    elif kind == "final":
        st.markdown("💬 final reply")


# ── main pane ──────────────────────────────────────────────────────────────
st.title("Sentinel")
st.caption("Phase 1 — Coordinator with one tool. Ask about recent production activity.")

st.info(f"Phoenix: {phoenix_endpoint} · project `{phoenix_project}`")

user_text = st.text_input(
    "Ask the Coordinator:",
    value=st.session_state.last_input,
    placeholder="what has been happening in production lately?",
    key="user_text_input",
)

if st.button("Send", type="primary", disabled=not user_text):
    st.session_state.last_input = user_text
    with st.spinner("Coordinator working..."):
        try:
            records, response = asyncio.run(_consume(user_text))
        except Exception as exc:
            st.session_state.agent_records = []
            st.session_state.agent_response = ""
            st.error(f"Coordinator failed: {exc}")
            st.exception(exc)
        else:
            st.session_state.agent_records = records
            st.session_state.agent_response = response

if st.session_state.agent_response:
    st.markdown("**Coordinator:**")
    st.write(st.session_state.agent_response)
    st.success(
        f"Trace emitted to Phoenix. Open {phoenix_endpoint} and look in the "
        f"`{phoenix_project}` project for the nested span tree."
    )
elif st.session_state.agent_records:
    st.warning("Coordinator returned no final text. See sidebar for raw events.")

# ── sidebar: agent reasoning ───────────────────────────────────────────────
with st.sidebar:
    st.header("🧠 Agent reasoning")
    if not st.session_state.agent_records:
        st.caption("No invocations yet. Send a message to see the agent's tool calls.")
    else:
        tool_calls = sum(1 for r in st.session_state.agent_records if r["kind"] == "tool_call")
        st.caption(
            f"{len(st.session_state.agent_records)} event(s) · "
            f"{tool_calls} tool call(s)"
        )
        st.divider()
        for rec in st.session_state.agent_records:
            _render_record(rec)
            st.divider()
