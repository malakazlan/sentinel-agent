"""Centralized constants for Sentinel.

Single source of truth for values referenced from multiple modules. The most
load-bearing entry is ``COORDINATOR_MODEL`` — see ADR-008 for the dev-vs-demo
model strategy.
"""

from __future__ import annotations

# ── Models ─────────────────────────────────────────────────────────────────
# ADR-008 (dev/demo split) + ADR-010 (Gemini 3 swap landed Phase 4 step 4):
# we now run the production Gemini 3 family via Vertex AI (region `global`).
# Coordinator gets Pro for routing + drafting; sub-agents get Flash Lite GA
# for tool-heavy work where Flash is sufficient.
#
# Preview-status caveat: `gemini-3.1-pro-preview` is the latest 3.1 Pro but
# carries Google's "preview" label — it can change or be deprecated. Track
# this in `07-known-issues.md`. Fall-back if deprecated mid-hackathon:
# `gemini-3.5-flash` (GA) for Coordinator at a small reasoning-quality cost.
COORDINATOR_MODEL = "gemini-3.1-pro-preview"
SUBAGENT_MODEL = "gemini-3.1-flash-lite"
