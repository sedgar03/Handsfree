#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Summarize Claude Code output via `claude -p` for spoken TTS updates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Allow imports from src/ when run from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import get_config

PROMPTS = {
    "terse": (
        "You are a voice assistant giving a spoken status update to a developer. "
        "One sentence max. Lead with what matters: do you need their input, or is everything fine? "
        "Never read out file names, paths, or code. "
        "Here is Claude's output:\n\n"
    ),
    "detailed": (
        "You are a voice assistant giving a spoken status update to a developer "
        "wearing AirPods who is away from their desk. Rules:\n"
        "- Lead with whether you need their input or not.\n"
        "- Then briefly cover ALL the meaningful changes or actions, not just one. "
        "For example: 'No input needed. I updated the summarizer prompts to be less verbose and bumped the TTS speed.'\n"
        "- Don't cherry-pick one change and ignore others.\n"
        "- NEVER read out file names, file paths, function names, or code.\n"
        "- Speak naturally like a coworker giving a quick update.\n"
        "- 2-3 sentences max.\n"
        "Here is Claude's output:\n\n"
    ),
}


def _resolve_claude_bin() -> str | None:
    """Find a usable Claude CLI binary path."""
    # Explicit override for non-standard installs.
    override = os.environ.get("HANDSFREE_CLAUDE_BIN")
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return str(path)

    found = shutil.which("claude")
    if found:
        return found

    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.exists():
        return str(fallback)

    return None


def summarize(text: str, verbosity: str | None = None) -> str:
    """Summarize text via claude -p. Returns the summary string."""
    if not text or not text.strip():
        return ""

    if verbosity is None:
        verbosity = get_config().get("verbosity", "detailed")

    prompt_prefix = PROMPTS.get(verbosity, PROMPTS["detailed"])
    full_prompt = prompt_prefix + text

    try:
        claude_bin = _resolve_claude_bin()
        if not claude_bin:
            print(
                "[handsfree] claude binary not found. Set HANDSFREE_CLAUDE_BIN or add claude to PATH.",
                file=sys.stderr,
            )
            return text[:200] if len(text) > 200 else text
        # Pass HANDSFREE_ACTIVE env var so claude -p's hooks know not to recurse
        env = {**os.environ, "HANDSFREE_ACTIVE": "1"}
        result = subprocess.run(
            [claude_bin, "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            # Fallback: return a truncated version of the original
            return text[:200] if len(text) > 200 else text
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[handsfree] claude -p failed: {e}", file=sys.stderr)
        return text[:200] if len(text) > 200 else text


if __name__ == "__main__":
    # Read from stdin or use argv
    if not sys.stdin.isatty():
        input_text = sys.stdin.read()
    elif len(sys.argv) > 1:
        input_text = " ".join(sys.argv[1:])
    else:
        print("Usage: echo 'text' | uv run src/summarizer.py")
        print("   or: uv run src/summarizer.py 'text to summarize'")
        sys.exit(1)

    summary = summarize(input_text)
    print(summary)
