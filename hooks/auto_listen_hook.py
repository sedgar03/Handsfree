#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper", "sounddevice", "numpy"]
# ///
"""Auto-listen hook for Claude Code — fires on idle_prompt to record and transcribe.

Called by Claude Code on Notification (idle_prompt) events.
Waits for TTS to finish, then records with VAD, transcribes, and pastes.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Recursion guard
if os.environ.get("HANDSFREE_ACTIVE"):
    sys.exit(0)
os.environ["HANDSFREE_ACTIVE"] = "1"

# Wire up src/ imports
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from config import get_config, is_handsfree_enabled

TTS_LOCK = Path("/tmp/handsfree-tts.lock")
DEBUG_LOG = Path("/tmp/handsfree-auto-listen.log")


def _log(msg: str):
    """Append debug message to log file."""
    import datetime
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")


def wait_for_tts(timeout: float = 15.0):
    """Wait for TTS to finish by checking the lock file."""
    import fcntl

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            fd = open(TTS_LOCK, "w")
            # Try non-blocking lock — if we get it, TTS is done
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
            return
        except (BlockingIOError, OSError):
            fd.close()
            time.sleep(0.2)


def main():
    _log("Hook started")

    if not is_handsfree_enabled():
        _log("Handsfree not enabled, exiting")
        return

    config = get_config()
    if config.get("input_mode") == "media_key":
        _log("media_key mode active, skipping auto-listen (stem click handles input)")
        return

    # Read hook JSON from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        _log("Failed to read stdin JSON, exiting")
        return

    _log(f"Hook input: {json.dumps(hook_input)[:200]}")

    # Wait for TTS to finish speaking before we start listening
    _log("Waiting for TTS...")
    wait_for_tts()
    _log("TTS done")

    # Small pause so TTS audio fully clears the speakers/mic
    time.sleep(0.3)

    # Import and run auto-listen
    _log("Starting auto-listen")
    try:
        from auto_listen import main as auto_listen_main
        auto_listen_main()
        _log("Auto-listen completed")
    except Exception as e:
        _log(f"Auto-listen error: {e}")
        raise


if __name__ == "__main__":
    main()
