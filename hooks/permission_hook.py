#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile"]
# ///
"""Handsfree hook for PermissionRequest — speak the permission prompt via TTS.

Called by Claude Code on PermissionRequest events.
Reads tool_name and tool_input from stdin, formats a human-friendly message,
writes a state file for the listener, and speaks the request.

Must be async: true so the permission dialog remains interactive.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Recursion guard: claude -p (used by summarizer) also fires hooks.
# This env var prevents infinite hook -> claude -p -> hook loops.
if os.environ.get("HANDSFREE_ACTIVE"):
    sys.exit(0)
os.environ["HANDSFREE_ACTIVE"] = "1"

# Wire up src/ imports
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from config import is_handsfree_enabled, is_wake_enabled

# Wire up hooks/ imports for shared module
sys.path.insert(0, str(_repo_root / "hooks"))
from shared import log as _log_shared

_DEDUP_WINDOW = 30


def _session_path(base: str, session_id: str) -> Path:
    """Build a session-scoped temp file path."""
    tag = session_id[:8] if session_id else "unknown"
    return Path(f"/tmp/handsfree-{base}-{tag}.json")


def _dedup_lock_path(session_id: str) -> Path:
    tag = session_id[:8] if session_id else "unknown"
    return Path(f"/tmp/handsfree-permission-dedup-{tag}.lock")


def _log(msg: str):
    _log_shared(msg, tag="perm")


def _dedup_check(content_key: str, session_id: str) -> bool:
    """Return True when the same permission alert was handled recently."""
    import fcntl
    import hashlib
    import tempfile

    seen_file = _session_path("permission-seen", session_id)
    lock_file = _dedup_lock_path(session_id)
    content_hash = hashlib.md5(content_key.encode()).hexdigest()[:12]
    now = time.time()

    lock_fd = None
    try:
        lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        state = {}
        if seen_file.exists():
            try:
                with open(seen_file) as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                state = {}

        last_time = float(state.get(content_hash, 0) or 0)
        if now - last_time < _DEDUP_WINDOW:
            _log(f"Dedup: skipping duplicate permission (hash={content_hash}, age={now - last_time:.1f}s)")
            return True

        state = {h: t for h, t in state.items() if now - float(t or 0) < _DEDUP_WINDOW * 2}
        state[content_hash] = now
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir="/tmp", suffix=".json")
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp_path, str(seen_file))
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


def _format_permission_message(tool_name: str, tool_input: dict) -> str:
    """Format a human-friendly message based on the tool and its input."""
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if len(command) > 120:
            command = command[:120] + "..."
        return f"Claude wants to run: {command}"

    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        basename = Path(file_path).name if file_path else "unknown file"
        action = "write" if tool_name == "Write" else "edit"
        return f"Claude wants to {action}: {basename}"

    if tool_name == "Task":
        description = tool_input.get("description", "a subagent")
        return f"Claude wants to spawn a subagent: {description}"

    return f"Claude wants to use {tool_name}"


def main():
    _log("Permission hook started")

    speech_enabled = is_handsfree_enabled()
    wake_enabled = is_wake_enabled()

    # Fast exit if neither automatic speech nor wake-queue mode is on.
    if not speech_enabled and not wake_enabled:
        _log("Handsfree speech/wake not enabled")
        return

    # Read hook JSON from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        _log("Failed to read stdin")
        return

    session_id = hook_input.get("session_id", "?")
    _log(f"Got hook input keys: {list(hook_input.keys())} | session: {session_id[:8]}")

    # Extract tool_name and tool_input from the PermissionRequest payload
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if not tool_name:
        _log("No tool_name found in hook input")
        return

    _log(f"Permission request for tool: {tool_name}")

    # Format the message
    message = _format_permission_message(tool_name, tool_input)
    _log(f"Message: {message}")
    if _dedup_check(f"permission:{message}", session_id):
        return

    # Write pending permission state file BEFORE speaking.
    # This closes the race window where the user clicks their AirPod stem
    # during TTS playback — the listener can pick up the file immediately.
    state = {
        "tool_name": tool_name,
        "message": message,
        "timestamp": time.time(),
    }
    try:
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(dir="/tmp", suffix=".json")
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f)
        pending_perm_file = _session_path("pending-permission", session_id)
        os.rename(tmp_path, str(pending_perm_file))
        _log("Wrote pending permission file")
    except OSError as e:
        _log(f"Failed to write pending permission file: {e}")

    event = None
    try:
        from event_queue import enqueue_event

        event = enqueue_event(
            source="claude",
            kind="permission",
            summary=message,
            detail=json.dumps(state, sort_keys=True),
            priority=200,
            session_id=session_id,
            payload={"tool_name": tool_name, "tool_input": tool_input},
        )
        _log(f"Queued permission event {event.id}")
    except Exception as e:
        _log(f"Failed to queue permission event: {e}")

    if not speech_enabled:
        if wake_enabled:
            try:
                from audio_output import play_notification

                play_notification("claude")
            except Exception as e:
                _log(f"Notification sound failed: {e}")
        _log("Speech disabled; permission queued only")
        return

    # Speak the permission request with the captured workflow label when queueing succeeded.
    try:
        if event is not None:
            from queue_actions import speak_event

            speak_event(event)
        else:
            from tts import speak

            speak(f"Attention: permission needed. {message}. Say allow or deny.")
    except Exception as e:
        _log(f"Failed to speak permission request: {e}")
        return

    _log("Finished speaking permission request")


if __name__ == "__main__":
    main()
