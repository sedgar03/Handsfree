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

import json
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from airpods_check import print_status as check_airpods
from config import get_config
from hotkey_listener import HotkeyListener
from media_key_listener import MediaKeyListener


PENDING_QUESTION_FILE = Path("/tmp/handsfree-pending-question.json")
PENDING_QUESTION_MAX_AGE = 300  # 5 minutes

PENDING_PERMISSION_FILE = Path("/tmp/handsfree-pending-permission.json")
PENDING_PERMISSION_MAX_AGE = 300  # 5 minutes

_OPTION_LETTERS = "ABCD"

# Voice words for permission allow/deny
_ALLOW_WORDS = {"allow", "yes", "approve", "go ahead", "do it", "sure", "okay", "ok", "yep", "yeah"}
_DENY_WORDS = {"deny", "no", "reject", "block", "nope", "dont"}

# Phonetic aliases — Whisper often transcribes single letters phonetically
_PHONETIC_ALIASES: dict[str, str] = {
    "ay": "a", "eh": "a",
    "be": "b", "bee": "b", "v": "b",
    "sea": "c", "see": "c", "si": "c",
    "dee": "d", "de": "d",
}

_LETTER_TO_INDEX: dict[str, int] = {"a": 0, "b": 1, "c": 2, "d": 3}
_ORDINAL_TO_INDEX: dict[str, int] = {
    "first": 0, "one": 0, "1": 0,
    "second": 1, "two": 1, "2": 1,
    "third": 2, "three": 2, "3": 2,
    "fourth": 3, "four": 3, "4": 3,
}

_CANCEL_WORDS = {"cancel", "never mind", "nevermind", "dismiss"}


def _parse_option(text: str, options: list[str]) -> int | None:
    """Parse transcribed text into a 0-based option index.

    Returns None if no match found (caller should fall through to normal injection).
    Returns -1 for cancel.
    Returns len(options) for "other".
    """
    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()

    # Cancel — word-boundary match to avoid "cancellation", "don't dismiss", etc.
    for cancel in _CANCEL_WORDS:
        if re.search(rf"\b{re.escape(cancel)}\b", normalized):
            return -1

    # "Other" — word-boundary match to avoid "another", "mother", etc.
    if re.search(r"\bother\b", normalized):
        return len(options)

    # Apply phonetic aliases to single-word transcriptions
    word = normalized.split()[0] if normalized.split() else ""
    canonical = _PHONETIC_ALIASES.get(word, word)

    # "option X" pattern — e.g. "option b", "option 2"
    m = re.search(r"option\s+(\w+)", normalized)
    if m:
        token = m.group(1)
        token = _PHONETIC_ALIASES.get(token, token)
        if token in _LETTER_TO_INDEX:
            return _LETTER_TO_INDEX[token]
        if token in _ORDINAL_TO_INDEX:
            return _ORDINAL_TO_INDEX[token]

    # Direct letter match (single word like "b" or phonetic alias resolved)
    if canonical in _LETTER_TO_INDEX:
        return _LETTER_TO_INDEX[canonical]

    # Ordinal / number match — scan words, but skip ambiguous ones in multi-word input
    _AMBIGUOUS_ORDINALS = {"one", "1"}
    words = normalized.split()
    for w in words:
        if w in _ORDINAL_TO_INDEX:
            if len(words) > 1 and w in _AMBIGUOUS_ORDINALS:
                continue  # "that one" / "the 1" — too ambiguous
            return _ORDINAL_TO_INDEX[w]

    # Also support "number X" pattern
    m_num = re.search(r"number\s+(\w+)", normalized)
    if m_num:
        token = m_num.group(1)
        if token in _ORDINAL_TO_INDEX:
            return _ORDINAL_TO_INDEX[token]

    # Fuzzy match against option labels — exact first, then longest substring
    for i, label in enumerate(options):
        if label.lower() == normalized:
            return i
    best_match = None
    best_len = 0
    for i, label in enumerate(options):
        label_lower = label.lower()
        if label_lower in normalized and len(label_lower) > best_len:
            best_match = i
            best_len = len(label_lower)
    if best_match is not None:
        return best_match

    return None


def _select_picker_option(index: int, num_options: int) -> bool:
    """Simulate arrow keys + Enter to select option in Claude Code picker.

    The picker starts with the first option highlighted. Navigate down `index`
    times, then press Enter. num_options is the count of regular options
    (not including "Other").
    """
    # Bounds check — index can be 0..num_options (num_options = "Other")
    if index < 0 or index > num_options:
        print(f"[listener] Invalid index {index} for {num_options} options", file=sys.stderr)
        return False

    script_parts = ['tell application "System Events"']
    for _ in range(index):
        script_parts.append("  key code 125")  # down arrow
        script_parts.append("  delay 0.08")
    script_parts.append("  delay 0.3")  # pause before Enter for picker to settle
    script_parts.append("  key code 36")  # Enter
    script_parts.append("end tell")

    result = _run_osascript(script_parts)
    return result.returncode == 0


def _try_answer_question(text: str) -> bool:
    """Check for a pending AskUserQuestion and answer it via voice.

    Returns True if the question was handled (caller should NOT inject text).
    Returns False to fall through to normal text injection.
    """
    if not PENDING_QUESTION_FILE.exists():
        return False

    try:
        with open(PENDING_QUESTION_FILE) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable — clean up and fall through
        PENDING_QUESTION_FILE.unlink(missing_ok=True)
        return False

    # Expire stale questions
    ts = state.get("timestamp", 0)
    if time.time() - ts > PENDING_QUESTION_MAX_AGE:
        print("[listener] Pending question expired, ignoring.", file=sys.stderr)
        PENDING_QUESTION_FILE.unlink(missing_ok=True)
        return False

    options = state.get("options", [])
    if not options:
        PENDING_QUESTION_FILE.unlink(missing_ok=True)
        return False

    index = _parse_option(text, options)
    if index is None:
        # No match — fall through to normal injection
        print(f"[listener] No option match for '{text}', falling through.", file=sys.stderr)
        return False

    # Handle cancel — clear file immediately
    if index == -1:
        PENDING_QUESTION_FILE.unlink(missing_ok=True)
        print("[listener] Voice cancel — cleared pending question.", file=sys.stderr)
        try:
            from tts import speak
            speak("Cancelled.")
        except Exception:
            pass
        return True

    # Select the option via keyboard simulation
    num_options = len(options)
    letter = _OPTION_LETTERS[index] if index < len(_OPTION_LETTERS) else "Other"

    print(f"[listener] Selecting option {letter} (index {index}).", file=sys.stderr)
    if not _select_picker_option(index, num_options):
        print("[listener] Keyboard simulation failed, keeping pending question for retry.", file=sys.stderr)
        return True  # Still consumed — don't inject raw text

    # Success — NOW delete the file
    PENDING_QUESTION_FILE.unlink(missing_ok=True)

    # Speak confirmation
    try:
        from tts import speak
        if index < num_options:
            speak(f"Selected option {letter}.")
        else:
            speak("Selected other.")
    except Exception:
        pass

    return True


def _try_answer_permission(text: str) -> bool:
    """Check for a pending permission prompt and answer it via voice.

    Returns True if the permission was handled (caller should NOT inject text).
    Returns False to fall through to normal text injection.
    """
    if not PENDING_PERMISSION_FILE.exists():
        return False

    try:
        with open(PENDING_PERMISSION_FILE) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        PENDING_PERMISSION_FILE.unlink(missing_ok=True)
        return False

    # Expire stale permissions
    ts = state.get("timestamp", 0)
    if time.time() - ts > PENDING_PERMISSION_MAX_AGE:
        print("[listener] Pending permission expired, ignoring.", file=sys.stderr)
        PENDING_PERMISSION_FILE.unlink(missing_ok=True)
        return False

    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()

    # Check for allow words (word-boundary match)
    is_allow = any(re.search(rf"\b{re.escape(w)}\b", normalized) for w in _ALLOW_WORDS)
    is_deny = any(re.search(rf"\b{re.escape(w)}\b", normalized) for w in _DENY_WORDS)

    if not is_allow and not is_deny:
        print(f"[listener] No permission match for '{text}', falling through.", file=sys.stderr)
        return False

    # Resolve conflict: if both matched, default to deny (safer)
    if is_allow and is_deny:
        print("[listener] Both allow and deny matched, defaulting to deny (safer).", file=sys.stderr)
        is_allow = False

    # Send keystroke: "y" for allow, "n" for deny
    key = "y" if is_allow else "n"
    action = "allowed" if is_allow else "denied"
    print(f"[listener] Permission {action} — sending '{key}' keystroke.", file=sys.stderr)

    result = _run_osascript([
        'tell application "System Events"',
        f'  keystroke "{key}"',
        'end tell',
    ])

    if result.returncode != 0:
        print(f"[listener] Keystroke failed, keeping pending permission for retry.", file=sys.stderr)
        return True  # Still consumed — don't inject raw text

    # Success — delete the file
    PENDING_PERMISSION_FILE.unlink(missing_ok=True)

    # Speak confirmation
    try:
        from tts import speak
        speak(f"Permission {action}.")
    except Exception:
        pass

    return True


def inject_text(text: str) -> bool:
    """Inject text into the active terminal via clipboard + paste.

    If a pending permission prompt exists, intercepts the transcription
    and sends y/n keystroke. If a pending AskUserQuestion exists, intercepts
    and answers via keyboard simulation instead.

    Otherwise copies text to clipboard, then simulates Cmd+V in the frontmost app.
    The user sees the text and presses Enter manually — this is intentional
    since Whisper might mishear and we don't want to auto-execute.

    Returns True if a pending prompt was answered (caller should skip auto-submit).
    """
    # Permission check first — it blocks Claude (higher priority),
    # and "yes"/"no" would otherwise fuzzy-match question option labels.
    if _try_answer_permission(text):
        return True
    if _try_answer_question(text):
        return True
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
    return False


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
