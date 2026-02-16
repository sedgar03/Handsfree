#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-framework-Quartz",
#   "pyobjc-framework-Cocoa",
#   "mlx-whisper",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""Handsfree listener — detect input events, record, transcribe, inject text.

Reads config from ~/.claude/voice-config.json for input mode:
  - "hotkey" — F18 hold-to-talk (original)
  - "media_key" — AirPods stem click with VAD auto-stop

Transcribed text is copied to clipboard and pasted into the active terminal.
User reviews the pasted text and presses Enter manually (safety measure),
or double-clicks AirPods stem to auto-submit.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from airpods_check import print_status as check_airpods
from config import get_config
from hotkey_listener import HotkeyListener
from media_key_listener import MediaKeyListener


def inject_text(text: str):
    """Inject text into the active terminal via clipboard + paste.

    Copies text to clipboard, then simulates Cmd+V in the frontmost app.
    The user sees the text and presses Enter manually — this is intentional
    since Whisper might mishear and we don't want to auto-execute.
    """
    subprocess.run(["pbcopy"], input=text.encode(), check=True)
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ],
        check=False,
    )
    print(f"[injected] {text}", file=sys.stderr)


def _run_osascript(lines: list[str]):
    cmd = ["osascript"]
    for line in lines:
        cmd.extend(["-e", line])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def submit_text():
    """Simulate pressing Enter in the frontmost app."""
    methods = [
        ("keycode-36", ["delay 0.35", 'tell application "System Events" to key code 36']),
        ("keystroke-return", ["delay 0.35", 'tell application "System Events" to keystroke return']),
        (
            "keystroke-ascii13",
            ["delay 0.35", 'tell application "System Events" to keystroke (ASCII character 13)'],
        ),
    ]

    for name, script_lines in methods:
        result = _run_osascript(script_lines)
        if result.returncode == 0:
            print(f"[submit] Enter pressed via {name}.", file=sys.stderr)
            return
        stderr = (result.stderr or "").strip()
        print(f"[submit] {name} failed (rc={result.returncode}): {stderr}", file=sys.stderr)

    print("[submit] Failed to press Enter via all methods.", file=sys.stderr)


def main():
    import os
    config = get_config()
    # CLI override via env var (set by handsfree.sh --media-key / --hotkey)
    input_mode = os.environ.get("HANDSFREE_INPUT_MODE") or config.get("input_mode", "media_key")

    print("=== Handsfree Listener ===", file=sys.stderr)

    if input_mode == "media_key":
        check_airpods()
        auto_submit = config.get("auto_submit", True)
        auto_submit_after_tx = config.get("auto_submit_after_transcription", True)
        print("Input: AirPods stem click (media keys)", file=sys.stderr)
        print("  Single click → record (VAD auto-stop on silence)", file=sys.stderr)
        print("  Double click during recording → manual stop", file=sys.stderr)
        if auto_submit_after_tx and auto_submit:
            print("  Auto-submit after transcription (no second click required)", file=sys.stderr)
        elif auto_submit:
            print("  Double click in idle → submit (Enter)", file=sys.stderr)
        print(f"  Silence timeout: {config.get('silence_timeout', 2.5)}s", file=sys.stderr)
        print("", file=sys.stderr)

        listener = MediaKeyListener(
            on_transcription=inject_text,
            on_submit=submit_text if auto_submit else None,
            silence_timeout=config.get("silence_timeout", 2.5),
            auto_submit=auto_submit,
            auto_submit_after_transcription=auto_submit_after_tx,
        )
    else:
        hotkey = config.get("hotkey", "F18")
        print(f"Input: {hotkey} hold-to-talk", file=sys.stderr)
        print("  Hold to record, release to transcribe + paste", file=sys.stderr)
        print("  Press Enter to send to Claude.", file=sys.stderr)
        print("", file=sys.stderr)

        listener = HotkeyListener(hotkey=hotkey, on_transcription=inject_text)

    listener.run()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
