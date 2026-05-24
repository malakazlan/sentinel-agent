"""Centralized constants for Sentinel.

Single source of truth for values referenced from multiple modules. The most
load-bearing entry is ``COORDINATOR_MODEL`` — see ADR-008 for the dev-vs-demo
model strategy.
"""

from __future__ import annotations

# ── Models ─────────────────────────────────────────────────────────────────
# ADR-008: Develop on free/cheap models for rapid iteration; switch to Gemini 3
# family (3 Flash for sub-agents, 3.1 Pro for Coordinator/Drafter) for the demo
# and final hackathon submission. This file is where the swap happens — one line.
COORDINATOR_MODEL = "gemini-2.5-flash-lite"
SUBAGENT_MODEL = "gemini-2.5-flash-lite"  # → Gemini 3 Flash via Vertex at Phase 4
