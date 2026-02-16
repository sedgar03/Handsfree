#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile"]
# ///
"""Handsfree hook for Claude Code — summarize assistant output and speak it.

Called by Claude Code on Stop, Notification, and PreCompact events.
Reads hook JSON from stdin, extracts the last assistant message from the
transcript file, summarizes via claude -p, and speaks via Kokoro TTS.

Exit immediately (zero overhead) when handsfree mode is disabled.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Recursion guard: claude -p (used by summarizer) also fires hooks.
# This env var prevents infinite hook → claude -p → hook loops.
if os.environ.get("HANDSFREE_ACTIVE"):
    sys.exit(0)
os.environ["HANDSFREE_ACTIVE"] = "1"

# Wire up src/ imports
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from config import is_handsfree_enabled

_DEBUG_LOG = Path("/tmp/handsfree-tts-hook.log")


def _log(msg: str):
    import datetime
    with open(_DEBUG_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")


def _extract_last_assistant_text(transcript_path: str) -> str | None:
    """Read transcript JSONL and return the last assistant message text."""
    path = Path(transcript_path)
    if not path.exists():
        return None

    last_assistant_text = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Claude Code transcript entries have type "assistant" with message content
            if entry.get("type") == "assistant":
                message = entry.get("message", {})
                content = message.get("content", [])
                # Content is a list of blocks; extract text blocks
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                if texts:
                    last_assistant_text = "\n".join(texts)

    return last_assistant_text


def main():
    _log("TTS hook started")

    # Fast exit if handsfree mode is off
    if not is_handsfree_enabled():
        _log("Handsfree not enabled")
        return

    # Read hook JSON from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        _log("Failed to read stdin")
        return

    _log(f"Got hook input keys: {list(hook_input.keys())}")

    # Extract transcript path
    transcript_path = hook_input.get("transcript_path")
    if not transcript_path:
        _log("No transcript_path in input")
        return

    _log(f"Transcript: {transcript_path}")

    # Get last assistant message
    text = _extract_last_assistant_text(transcript_path)
    if not text:
        _log("No assistant text found in transcript")
        return

    _log(f"Got text ({len(text)} chars), summarizing...")

    # Summarize and speak (import lazily so disabled mode has zero dep overhead)
    try:
        from summarizer import summarize
        from tts import speak

        summary = summarize(text)
        _log(f"Summary: {summary[:100] if summary else '(empty)'}")
        if summary:
            speak(summary)
            _log("Spoke summary")
    except Exception as e:
        _log(f"Error: {e}")


if __name__ == "__main__":
    main()
