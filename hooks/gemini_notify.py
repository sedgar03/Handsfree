#!/usr/bin/env python3
"""Gemini CLI hook: enqueue, ding, and optionally speak Handsfree events.

Gemini CLI hooks parse stdout as JSON, so this script keeps diagnostics on
stderr/shared hook logs and prints only a small neutral JSON object.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))
sys.path.insert(0, str(_repo_root / "hooks"))

from audio_output import play_notification
from config import is_wake_enabled, should_auto_speak_events
from event_queue import enqueue_event, update_event_status
from queue_actions import speak_event
from shared import log as _log_shared
from tmux_target import current_context


SOURCE = "gemini"
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_DEDUP_WINDOW = 60
_DEDUP_FILE = Path("/tmp/handsfree-gemini-notify-seen.json")
_DEDUP_LOCK = Path("/tmp/handsfree-gemini-notify-seen.lock")
_PAYLOAD_TEXT_LIMIT = 4000
_DETAIL_LIMIT = 2000


def _log(message: str) -> None:
    try:
        _log_shared(message, tag=SOURCE)
    except Exception:
        print(f"[gemini-notify] {message}", file=sys.stderr)


def _load_payload() -> dict[str, Any]:
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


def _hook_event_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("hook_event_name")
        or payload.get("event")
        or payload.get("type")
        or "Notification"
    )


def _plain_spoken_fallback(text: str, *, limit: int = 360) -> str:
    cleaned = _CODE_FENCE_RE.sub(" I included code or commands in the response. ", text)
    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = re.sub(r"[*_#>\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[:limit].rsplit(" ", 1)[0].strip()
    return f"{truncated}."


def _summarize_for_voice(text: str) -> str:
    try:
        from summarizer import summarize

        summary = summarize(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[gemini-notify] summarizer failed: {exc}", file=sys.stderr)
        summary = ""

    return summary.strip() if summary.strip() else _plain_spoken_fallback(text)


def _summary_for_payload(payload: dict[str, Any], workflow: str) -> str:
    event_name = _hook_event_name(payload)
    if event_name == "AfterAgent":
        response = str(payload.get("prompt_response") or "").strip()
        if response:
            return _summarize_for_voice(response)
        return "Gemini finished a turn."

    if event_name == "Notification":
        message = str(payload.get("message") or "").strip()
        details = payload.get("details")
        if not isinstance(details, dict):
            details = {}
        notification_type = str(payload.get("notification_type") or "")
        if notification_type == "ToolPermission":
            tool_name = str(
                details.get("tool_name")
                or details.get("toolName")
                or details.get("name")
                or ""
            ).strip()
            if message:
                return f"Gemini wants permission: {message}"
            if tool_name:
                return f"Gemini wants to use {tool_name}"
            return "Gemini needs tool permission."
        if message:
            return message

    if workflow:
        return f"Gemini needs attention in {workflow}."
    return "Gemini needs attention."


def _kind_for_payload(payload: dict[str, Any]) -> str:
    event_name = _hook_event_name(payload)
    if event_name == "AfterAgent":
        return "summary"
    if (
        event_name == "Notification"
        and str(payload.get("notification_type") or "") == "ToolPermission"
    ):
        return "permission"
    return "notification"


def _priority_for_kind(kind: str) -> int:
    if kind == "permission":
        return 100
    if kind == "notification":
        return 50
    return 0


def _dedup_key(payload: dict[str, Any], summary: str) -> str:
    event_name = _hook_event_name(payload)
    if event_name == "AfterAgent":
        response = str(payload.get("prompt_response") or "").strip()
        if response:
            return f"AfterAgent:{response}"
    if event_name == "Notification":
        details = payload.get("details")
        details_key = ""
        if isinstance(details, dict):
            try:
                details_key = json.dumps(details, sort_keys=True)
            except (TypeError, ValueError):
                details_key = repr(details)
        message = str(payload.get("message") or "").strip()
        return f"Notification:{payload.get('notification_type')}:{message}:{details_key}"
    return summary


def _dedup_check(content_key: str) -> bool:
    """Return True if the same Gemini notification was handled recently."""
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
            _log(
                "Dedup: skipping duplicate Gemini notification "
                f"(hash={content_hash}, age={now - last_time:.1f}s)"
            )
            return True

        state = {
            h: t for h, t in state.items()
            if now - float(t or 0) < _DEDUP_WINDOW * 2
        }
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


def _truncate_text(value: Any, limit: int = _PAYLOAD_TEXT_LIMIT) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def _queue_payload(payload: dict[str, Any]) -> dict[str, Any]:
    queued = dict(payload)
    for key in ("prompt", "prompt_response", "message"):
        if key in queued:
            queued[key] = _truncate_text(queued[key])
    return queued


def _detail_for_payload(payload: dict[str, Any]) -> str:
    event_name = _hook_event_name(payload)
    if event_name == "AfterAgent":
        return str(payload.get("prompt_response") or "")[:_DETAIL_LIMIT]
    try:
        return json.dumps(_queue_payload(payload), sort_keys=True)[:_DETAIL_LIMIT]
    except (TypeError, ValueError):
        return repr(payload)[:_DETAIL_LIMIT]


def handle_payload(payload: dict[str, Any]) -> bool:
    """Process a Gemini hook payload. Return True when an event was queued."""

    context = current_context(cwd=str(payload.get("cwd") or ""))
    workflow = str(payload.get("workflow") or context.workflow)
    target_cwd = str(payload.get("cwd") or context.current_path)
    target_pane_value = payload.get("target_pane")
    target_pane = str(target_pane_value) if target_pane_value else context.pane

    summary = _summary_for_payload(payload, workflow)
    if _dedup_check(_dedup_key(payload, summary)):
        return False

    kind = _kind_for_payload(payload)
    event = enqueue_event(
        source=SOURCE,
        kind=kind,
        summary=summary,
        detail=_detail_for_payload(payload),
        priority=_priority_for_kind(kind),
        workflow=workflow,
        target_pane=target_pane,
        target_cwd=target_cwd,
        transcript_path=str(payload.get("transcript_path") or ""),
        session_id=str(payload.get("session_id") or ""),
        payload=_queue_payload(payload),
    )

    play_notification(SOURCE)
    if should_auto_speak_events():
        if speak_event(event):
            update_event_status(event.id, "done")
            _log(f"Spoke event {event.id}")
        else:
            _log(f"Speak failed for event {event.id}; leaving queued")
    elif not is_wake_enabled():
        update_event_status(event.id, "done")
        _log(f"Speech/wake disabled; marked event {event.id} done")
    else:
        _log(f"Queued event {event.id} for wake retrieval")

    return True


def main() -> int:
    _log("Gemini notify started")
    try:
        handle_payload(_load_payload())
    except Exception as exc:  # noqa: BLE001
        print(f"[gemini-notify] error: {exc}", file=sys.stderr)
    print(json.dumps({"suppressOutput": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
