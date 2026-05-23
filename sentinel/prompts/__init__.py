"""Prompt loader. Prompts live next to this file as Markdown so they version-control cleanly."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the contents of the named prompt file.

    Args:
        name: Prompt file stem, without the ``.md`` extension. Example: ``"coordinator"``
            loads ``sentinel/prompts/coordinator.md``.

    Returns:
        The full text of the prompt, stripped of trailing whitespace.

    Raises:
        FileNotFoundError: If no matching ``.md`` file exists.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8").rstrip()
