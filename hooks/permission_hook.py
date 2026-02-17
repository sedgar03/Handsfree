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

from config import is_handsfree_enabled

_DEBUG_LOG = Path("/tmp/handsfree-tts-hook.log")
_PENDING_PERMISSION_FILE = Path("/tmp/handsfree-pending-permission.json")


def _log(msg: str):
    import datetime
    with open(_DEBUG_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} [perm] {msg}\n")


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
        os.rename(tmp_path, str(_PENDING_PERMISSION_FILE))
        _log("Wrote pending permission file")
    except OSError as e:
        _log(f"Failed to write pending permission file: {e}")

    # Import TTS lazily (zero dep overhead when disabled)
    try:
        from tts import speak
    except Exception as e:
        _log(f"Failed to import tts: {e}")
        return

    # Speak the permission request
    speak(f"Attention: permission needed. {message}. Say allow or deny.")

    _log("Finished speaking permission request")


if __name__ == "__main__":
    main()
