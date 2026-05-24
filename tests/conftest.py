"""Session-wide pytest setup.

Loads ``.env`` once at session start so module-level ``pytest.mark.skipif``
decorators can read ``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_API_KEY`` / etc.
without each test having to ``load_dotenv()`` first.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=False)
