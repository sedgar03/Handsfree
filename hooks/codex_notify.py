#!/usr/bin/env python3
"""Codex notify command: enqueue, ding, and optionally speak."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))
sys.path.insert(0, str(_repo_root / "hooks"))

from audio_output import play_notification
from config import is_handsfree_enabled, is_wake_enabled
from event_queue import enqueue_event, update_event_status
from queue_actions import speak_event
from shared import log as _log_shared
from tmux_target import current_context


_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_DEDUP_WINDOW = 60
_DEDUP_FILE = Path("/tmp/handsfree-codex-notify-seen.json")
_DEDUP_LOCK = Path("/tmp/handsfree-codex-notify-seen.lock")


def _log(message: str) -> None:
    try:
        _log_shared(message, tag="codex")
    except Exception:
        pass


def _load_payload() -> dict:
    raw = ""
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _plain_spoken_fallback(text: str, *, limit: int = 360) -> str:
    """Convert assistant markdown to a compact spoken fallback."""

    cleaned = _CODE_FENCE_RE.sub(" I included code or commands in the response. ", text)
    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"[*_#>\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[:limit].rsplit(" ", 1)[0].strip()
    return f"{truncated}."


def _dedup_key(payload: dict, summary: str) -> str:
    message = str(payload.get("last-assistant-message") or payload.get("message") or "").strip()
    return message or summary


def _dedup_check(content_key: str) -> bool:
    """Return True if the same Codex notification was handled recently."""
    import fcntl
    import hashlib
    import tempfile

    if not content_key.strip():
        return False

    content_hash = hashlib.md5(content_key.encode()).hexdigest()[:12]
    now = time.time()
    lock_fd = None
    try:
        lock_fd = os.open(str(_DEDUP_LOCK), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        state = {}
        if _DEDUP_FILE.exists():
            try:
                state = json.loads(_DEDUP_FILE.read_text())
            except (OSError, json.JSONDecodeError):
                state = {}

        last_time = float(state.get(content_hash, 0) or 0)
        if now - last_time < _DEDUP_WINDOW:
            _log(f"Dedup: skipping duplicate Codex notification (hash={content_hash}, age={now - last_time:.1f}s)")
            return True

        state = {h: t for h, t in state.items() if now - float(t or 0) < _DEDUP_WINDOW * 2}
        state[content_hash] = now
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir="/tmp", suffix=".json")
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp_path, str(_DEDUP_FILE))
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


def _summarize_for_voice(text: str) -> str:
    try:
        from summarizer import summarize

        summary = summarize(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[codex-notify] summarizer failed: {exc}", file=sys.stderr)
        summary = ""

    return summary.strip() if summary.strip() else _plain_spoken_fallback(text)


def _summary_for_payload(payload: dict, workflow: str) -> str:
    event_type = str(payload.get("type") or payload.get("event") or "notification")
    if event_type == "agent-turn-complete":
        message = str(payload.get("last-assistant-message") or "").strip()
        if message:
            return _summarize_for_voice(message)
        return "Codex finished a turn."
    if event_type == "approval-requested":
        return "Codex needs approval."
    if event_type == "agent-message":
        message = str(payload.get("message") or "").strip()
        if message:
            return _summarize_for_voice(message)
    if workflow:
        return f"Codex needs attention in {workflow}."
    return "Codex needs attention."


def main() -> int:
    _log("Codex notify started")
    payload = _load_payload()
    context = current_context()
    workflow = str(payload.get("workflow") or context.workflow)
    target_cwd = str(payload.get("target_cwd") or context.current_path)
    target_pane_value = payload.get("target_pane")
    target_pane = str(target_pane_value) if target_pane_value else context.pane
    raw_dedup_key = _dedup_key(payload, "")
    if raw_dedup_key and _dedup_check(raw_dedup_key):
        return 0
    summary = _summary_for_payload(payload, workflow)
    _log(f"Summary: {summary[:120]}")
    if not raw_dedup_key and _dedup_check(_dedup_key(payload, summary)):
        return 0
    event = enqueue_event(
        source="codex",
        kind="notification",
        summary=summary,
        detail=json.dumps(payload, sort_keys=True),
        priority=50,
        workflow=workflow,
        target_pane=target_pane,
        target_cwd=target_cwd,
        payload=payload,
    )

    # Notification and speech are independent controls. Notification sound
    # follows ~/.codex/mute; automatic speech follows ~/.handsfree/speech-enabled.
    play_notification("codex")
    if is_handsfree_enabled():
        if speak_event(event):
            update_event_status(event.id, "done")
            _log(f"Spoke event {event.id}")
        else:
            _log(f"Speak failed for event {event.id}; leaving queued")
    elif not is_wake_enabled():
        # Keep the event only when there is a wake path to retrieve it.
        update_event_status(event.id, "done")
        _log(f"Speech/wake disabled; marked event {event.id} done")
    else:
        _log(f"Queued event {event.id} for wake retrieval")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
