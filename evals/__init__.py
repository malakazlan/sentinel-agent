"""Evaluations for Sentinel.

Eval modules sit outside ``sentinel/`` so they can be reasoned about as
external judges of the agent — they read traces from Phoenix and write
annotations back. They are not imported into the agent's hot path; agent
code only calls them at integration points (e.g. ``app.py`` invokes
``time_to_response.annotate_latest_root_span`` after a Coordinator run).
"""
