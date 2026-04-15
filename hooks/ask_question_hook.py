#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile"]
# ///
"""Handsfree hook for AskUserQuestion — speak the question and options via TTS.

Called by Claude Code on PreToolUse (matcher: AskUserQuestion).
Reads the tool_input from stdin, formats the question and options,
and speaks them so the user knows to return to their computer.

Must be async: true to avoid bug #12031 (PreToolUse hooks can strip
AskUserQuestion result data when synchronous).
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

_OPTION_LETTERS = "ABCD"


def _session_path(base: str, session_id: str) -> Path:
    """Build a session-scoped temp file path."""
    tag = session_id[:8] if session_id else "unknown"
    return Path(f"/tmp/handsfree-{base}-{tag}.json")


def _log(msg: str):
    _log_shared(msg, tag="ask")


def main():
    _log("AskQuestion hook started")

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

    # Extract tool_input.questions from the PreToolUse payload
    tool_input = hook_input.get("tool_input", {})
    questions = tool_input.get("questions", [])

    if not questions:
        _log("No questions found in tool_input")
        return

    _log(f"Found {len(questions)} question(s)")

    # Write pending question state file BEFORE speaking.
    # This closes the race window where the user clicks their AirPod stem
    # during TTS playback — the listener can pick up the file immediately.
    last_q = questions[-1]
    all_options = [opt.get("label", "") for opt in last_q.get("options", [])]
    state = {
        "question": last_q.get("question", ""),
        "options": all_options,
        "timestamp": time.time(),
    }
    try:
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(dir="/tmp", suffix=".json")
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f)
        pending_question_file = _session_path("pending-question", session_id)
        os.rename(tmp_path, str(pending_question_file))
        _log(f"Wrote pending question file with {len(all_options)} options")
    except OSError as e:
        _log(f"Failed to write pending question file: {e}")

    event = None
    try:
        from event_queue import enqueue_event

        question_summary = last_q.get("question", "") or "Claude has a question."
        event = enqueue_event(
            source="claude",
            kind="question",
            summary=question_summary,
            detail=json.dumps(state, sort_keys=True),
            priority=100,
            session_id=session_id,
            payload={"questions": questions},
        )
        _log(f"Queued question event {event.id}")
    except Exception as e:
        _log(f"Failed to queue question event: {e}")

    if not speech_enabled:
        if wake_enabled:
            try:
                from audio_output import play_notification

                play_notification("claude")
            except Exception as e:
                _log(f"Notification sound failed: {e}")
        _log("Speech disabled; question queued only")
        return

    # Import TTS lazily (zero dep overhead when disabled)
    try:
        from tts import speak
    except Exception as e:
        _log(f"Failed to import tts: {e}")
        return

    # Give the user the workflow context before the detailed question/options.
    if event is not None:
        try:
            from queue_actions import INTRO_PAUSE_SECONDS, workflow_intro_text

            intro = workflow_intro_text(event.workflow)
            if intro:
                speak(intro)
                time.sleep(INTRO_PAUSE_SECONDS)
        except Exception as e:
            _log(f"Failed to speak workflow intro: {e}")

    # Speak attention getter
    speak("Attention: there's a question on your computer.")
    time.sleep(0.5)

    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        options = q.get("options", [])

        if not question_text:
            continue

        # Speak the question
        speak(question_text)
        time.sleep(0.4)

        # Speak each option with a letter label
        for j, opt in enumerate(options):
            if j >= len(_OPTION_LETTERS):
                break
            letter = _OPTION_LETTERS[j]
            label = opt.get("label", "")
            description = opt.get("description", "")

            if description:
                speak(f"Option {letter}: {label}. {description}.")
            else:
                speak(f"Option {letter}: {label}.")
            time.sleep(0.3)

        # Pause between multiple questions
        if i < len(questions) - 1:
            time.sleep(0.5)

    _log("Finished speaking question(s)")


if __name__ == "__main__":
    main()
