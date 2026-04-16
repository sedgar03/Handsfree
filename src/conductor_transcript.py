"""Persistent transcript helpers for conductor conversations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable

from config import HANDSFREE_HOME

TRANSCRIPT_DIR = HANDSFREE_HOME / "conductor" / "transcripts"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_conversation_id(conversation_id: str) -> str:
    value = _SAFE_ID_RE.sub("_", (conversation_id or "default").strip())
    return value.strip("._-") or "default"


def transcript_path(
    conversation_id: str = "voice",
    *,
    root: Path | None = None,
) -> Path:
    base = TRANSCRIPT_DIR if root is None else root
    return base / f"{safe_conversation_id(conversation_id)}.jsonl"


def ensure_transcript(
    conversation_id: str = "voice",
    *,
    root: Path | None = None,
) -> Path:
    path = transcript_path(conversation_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


def append_transcript_event(
    conversation_id: str,
    event_type: str,
    *,
    text: str = "",
    data: dict[str, Any] | None = None,
    root: Path | None = None,
) -> Path:
    path = ensure_transcript(conversation_id, root=root)
    now = time.time()
    record: dict[str, Any] = {
        "ts": now,
        "time": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
        "conversation_id": conversation_id,
        "type": event_type,
    }
    if text:
        record["text"] = text
    if data:
        record["data"] = data

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
    return path


def iter_transcript_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def format_transcript_record(record: dict[str, Any]) -> str:
    timestamp = str(record.get("time") or "")
    event_type = str(record.get("type") or "event")
    text = str(record.get("text") or "").strip()
    data = record.get("data")
    if text:
        return f"[{timestamp}] {event_type}: {text}"
    if isinstance(data, dict) and data:
        return f"[{timestamp}] {event_type}: {json.dumps(data, ensure_ascii=True, sort_keys=True)}"
    return f"[{timestamp}] {event_type}"
