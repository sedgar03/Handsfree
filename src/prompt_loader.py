"""Load editable prompt text from repo files or user overrides."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_PROMPTS_DIR = REPO_ROOT / "prompts"
USER_PROMPTS_DIR = Path.home() / ".handsfree" / "prompts"


def _safe_prompt_name(name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe prompt path: {name}")
    return path


def load_prompt(
    name: str,
    fallback: str,
    replacements: Mapping[str, str] | None = None,
) -> str:
    """Return prompt text, preferring user overrides over repo defaults.

    Prompt files are intentionally read at call time so daemon prompt edits can
    take effect without a process restart for the hot paths that call this per
    request.
    """

    relative = _safe_prompt_name(name)
    text = ""
    for base in (USER_PROMPTS_DIR, REPO_PROMPTS_DIR):
        candidate = base / relative
        try:
            loaded = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if loaded:
            text = loaded
            break

    if not text:
        text = fallback.strip()

    for key, value in (replacements or {}).items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text.strip()
