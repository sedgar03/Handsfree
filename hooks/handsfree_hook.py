#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile"]
# ///
"""Handsfree hook for Claude Code — summarize assistant output and speak it.

Called by Claude Code on Stop events only.
Reads hook JSON from stdin, extracts the last assistant message from the
transcript file, summarizes via claude -p, and speaks via Kokoro TTS.

AskUserQuestion handling is done by ask_question_hook.py (PreToolUse).
Permission handling is done by permission_hook.py (PermissionRequest).

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

# Wire up src/ and hooks/ imports
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))
sys.path.insert(0, str(_repo_root / "hooks"))

from config import is_handsfree_enabled
from shared import log as _log_shared

_PERMISSION_RECENCY = 30  # seconds — skip if permission hook spoke recently
_DEDUP_WINDOW = 30  # seconds — skip if same content hash was spoken recently


def _session_path(base: str, session_id: str) -> Path:
    """Build a session-scoped temp file path."""
    tag = session_id[:8] if session_id else "unknown"
    return Path(f"/tmp/handsfree-{base}-{tag}.json")


def _dedup_lock_path(session_id: str) -> Path:
    tag = session_id[:8] if session_id else "unknown"
    return Path(f"/tmp/handsfree-dedup-{tag}.lock")


def _log(msg: str):
    _log_shared(msg, tag="tts")


def _dedup_check(content_key: str, session_id: str) -> bool:
    """Return True if this content was already spoken recently (should skip).

    Uses a file-based approach with a file lock to serialize concurrent
    hook invocations (Stop + other hooks can fire near-simultaneously).
    State files are session-scoped to avoid cross-session collisions.
    """
    import fcntl
    import hashlib
    import time

    spoken_file = _session_path("last-spoken", session_id)
    lock_file = _dedup_lock_path(session_id)

    content_hash = hashlib.md5(content_key.encode()).hexdigest()[:12]
    now = time.time()

    # File lock to serialize read-modify-write across concurrent hook processes
    lock_fd = None
    try:
        lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Read existing state
        state = {}
        if spoken_file.exists():
            try:
                with open(spoken_file) as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                state = {}

        # Check if this hash was spoken recently
        last_time = state.get(content_hash, 0)
        if now - last_time < _DEDUP_WINDOW:
            _log(f"Dedup: skipping (hash={content_hash}, age={now - last_time:.1f}s)")
            return True

        # Record this speech
        # Clean old entries while we're at it
        state = {h: t for h, t in state.items() if now - t < _DEDUP_WINDOW * 2}
        state[content_hash] = now
        try:
            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(dir="/tmp", suffix=".json")
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp_path, str(spoken_file))
        except OSError:
            pass

        return False
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            except OSError:
                pass


def _extract_last_assistant_text(transcript_path: str) -> str | None:
    """Read transcript JSONL and return the last assistant message text."""
    path = Path(transcript_path)
    if not path.exists():
        return None

    last_text = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "assistant":
                message = entry.get("message", {})
                content = message.get("content", [])
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                if texts and "\n".join(texts).strip():
                    last_text = "\n".join(texts)

    return last_text


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

    # Log event type for debugging
    event_type = hook_input.get("event", hook_input.get("type", "unknown"))
    session_id = hook_input.get("session_id", "?")
    _log(f"Event: {event_type} | session: {session_id[:8]}")

    # Brief delay to let Claude Code finish writing the latest response
    # to the transcript JSONL. The Stop hook fires slightly before the
    # final assistant message is flushed.
    import time as _time
    _time.sleep(1.0)

    # Skip speaking if the permission hook already spoke recently.
    # This avoids double-speech when both PermissionRequest and Stop
    # fire for the same permission dialog.
    pending_perm = _session_path("pending-permission", session_id)
    if pending_perm.exists():
        try:
            import time
            stat = pending_perm.stat()
            age = time.time() - stat.st_mtime
            if age < _PERMISSION_RECENCY:
                _log(f"Pending permission file is {age:.1f}s old, skipping (permission hook already spoke)")
                return
        except OSError:
            pass

    # Extract transcript path
    transcript_path = hook_input.get("transcript_path")
    if not transcript_path:
        _log("No transcript_path in input")
        return

    _log(f"Transcript: {transcript_path}")

    # Get last assistant message text
    text = _extract_last_assistant_text(transcript_path)
    if not text:
        _log("No assistant text found in transcript")
        return

    # Dedup check — same text shouldn't be spoken twice
    if _dedup_check(f"text:{text[:500]}", session_id):
        _log("Text already spoken (dedup), skipping")
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
