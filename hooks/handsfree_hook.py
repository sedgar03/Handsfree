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
_PENDING_PERMISSION_FILE = Path("/tmp/handsfree-pending-permission.json")
_PERMISSION_RECENCY = 30  # seconds — skip if permission hook spoke recently


def _log(msg: str):
    import datetime
    with open(_DEBUG_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")


_PENDING_QUESTION_FILE = Path("/tmp/handsfree-pending-question.json")
_OPTION_LETTERS = "ABCD"


def _extract_last_assistant(transcript_path: str) -> dict | None:
    """Read transcript JSONL and return the last assistant message content.

    Returns a dict with:
      - "text": concatenated text blocks (str or None)
      - "ask_question": the AskUserQuestion tool_input dict, or None
    """
    path = Path(transcript_path)
    if not path.exists():
        return None

    last_text = None
    last_text_pos = -1
    last_question = None
    last_question_pos = -1
    pos = 0
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
                ask_question = None
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif (
                            block.get("type") == "tool_use"
                            and block.get("name") == "AskUserQuestion"
                        ):
                            ask_question = block.get("input", {})
                    elif isinstance(block, str):
                        texts.append(block)
                if texts and "\n".join(texts).strip():
                    last_text = "\n".join(texts)
                    last_text_pos = pos
                if ask_question:
                    last_question = ask_question
                    last_question_pos = pos
            pos += 1

    if not last_text and not last_question:
        return None
    # Only return whichever came last — don't let a stale question
    # override a more recent text response.
    return {
        "text": last_text if last_text_pos >= last_question_pos else None,
        "ask_question": last_question if last_question_pos > last_text_pos else None,
    }


def _speak_ask_question(ask_input: dict) -> bool:
    """Speak an AskUserQuestion with structured options. Returns True if spoken."""
    import time

    questions = ask_input.get("questions", [])
    if not questions:
        return False

    try:
        from tts import speak
    except Exception as e:
        _log(f"Failed to import tts for ask_question: {e}")
        return False

    # Write pending question file so the listener can pick it up
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
        os.rename(tmp_path, str(_PENDING_QUESTION_FILE))
        _log(f"Wrote pending question file with {len(all_options)} options")
    except OSError as e:
        _log(f"Failed to write pending question file: {e}")

    speak("Attention: there's a question on your computer.")
    time.sleep(0.5)

    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        options = q.get("options", [])
        if not question_text:
            continue

        speak(question_text)
        time.sleep(0.4)

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

        if i < len(questions) - 1:
            time.sleep(0.5)

    return True


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

    # Brief delay to let Claude Code finish writing the latest response
    # to the transcript JSONL. The Stop hook fires slightly before the
    # final assistant message is flushed.
    import time as _time
    _time.sleep(1.0)

    # Skip speaking if the permission hook already spoke recently.
    # This avoids double-speech when both Notification[permission_prompt]
    # and PermissionRequest fire for the same permission dialog.
    if _PENDING_PERMISSION_FILE.exists():
        try:
            import time
            stat = _PENDING_PERMISSION_FILE.stat()
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

    # Get last assistant message (text + any AskUserQuestion tool call)
    last = _extract_last_assistant(transcript_path)
    if not last:
        _log("No assistant content found in transcript")
        return

    # If the last message contains AskUserQuestion, speak it with structured
    # options instead of summarizing. This handles the case where Claude uses
    # the AskUserQuestion tool and the PreToolUse hook didn't fire.
    if last["ask_question"]:
        _log("Detected AskUserQuestion in transcript, speaking options")
        if _speak_ask_question(last["ask_question"]):
            _log("Spoke AskUserQuestion options")
            return
        _log("AskUserQuestion speak failed, falling through to summarize")

    text = last["text"]
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
