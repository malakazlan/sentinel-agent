"""Sub-agents dispatched by the Coordinator via ADK's native A2A protocol.

Each sub-agent has a single responsibility (per CLAUDE.md §5) and its own
prompt + (optionally) its own tool set. The Coordinator registers them via
``sub_agents=[...]`` and the LLM decides when to transfer.

Phase 2 adds: TraceAnalyzer, EvalRunner.
Phase 4 adds: RootCause, Remediation, Postmortem.
"""
