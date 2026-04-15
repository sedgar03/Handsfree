"""Durable queue for handsfree agent events."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from tmux_target import current_context

DEFAULT_QUEUE_PATH = Path.home() / ".handsfree" / "events.sqlite"
ACTIVE_STATUSES = ("active",)
PENDING_STATUSES = ("pending", "active")


@dataclass(slots=True, frozen=True)
class AgentEvent:
    id: int
    created_at: float
    updated_at: float
    source: str
    kind: str
    priority: int
    workflow: str
    summary: str
    detail: str
    target_pane: str | None
    target_cwd: str
    transcript_path: str
    session_id: str
    status: str
    payload: dict[str, Any]

    @property
    def actionable(self) -> bool:
        return self.kind in {"permission", "question", "notification"}


def _connect(path: Path = DEFAULT_QUEUE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            workflow TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            target_pane TEXT,
            target_cwd TEXT NOT NULL DEFAULT '',
            transcript_path TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_status_priority "
        "ON events(status, priority DESC, created_at ASC)"
    )
    conn.commit()


def _event_from_row(row: sqlite3.Row) -> AgentEvent:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return AgentEvent(
        id=int(row["id"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        source=str(row["source"]),
        kind=str(row["kind"]),
        priority=int(row["priority"]),
        workflow=str(row["workflow"] or ""),
        summary=str(row["summary"] or ""),
        detail=str(row["detail"] or ""),
        target_pane=row["target_pane"],
        target_cwd=str(row["target_cwd"] or ""),
        transcript_path=str(row["transcript_path"] or ""),
        session_id=str(row["session_id"] or ""),
        status=str(row["status"] or ""),
        payload=payload,
    )


def enqueue_event(
    *,
    source: str,
    kind: str,
    summary: str,
    detail: str = "",
    priority: int = 0,
    workflow: str | None = None,
    target_pane: str | None = None,
    target_cwd: str | None = None,
    transcript_path: str = "",
    session_id: str = "",
    payload: dict[str, Any] | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> AgentEvent:
    """Append an event and return the stored row."""

    context = current_context(pane=target_pane, cwd=target_cwd)
    now = time.time()
    workflow_value = workflow or context.workflow
    target_pane_value = target_pane if target_pane is not None else context.pane
    target_cwd_value = target_cwd or context.current_path
    payload_json = json.dumps(payload or {}, sort_keys=True)

    with _connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO events (
                created_at, updated_at, source, kind, priority, workflow, summary,
                detail, target_pane, target_cwd, transcript_path, session_id,
                status, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                now,
                now,
                source,
                kind,
                int(priority),
                workflow_value,
                summary,
                detail,
                target_pane_value,
                target_cwd_value,
                transcript_path,
                session_id,
                payload_json,
            ),
        )
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _event_from_row(row)


def list_events(
    statuses: Iterable[str] = PENDING_STATUSES,
    *,
    limit: int = 20,
    created_after: float | None = None,
    path: Path = DEFAULT_QUEUE_PATH,
) -> list[AgentEvent]:
    status_values = tuple(statuses)
    if not status_values:
        return []
    placeholders = ",".join("?" for _ in status_values)
    params: list[Any] = [*status_values]
    query = f"SELECT * FROM events WHERE status IN ({placeholders}) "
    if created_after is not None:
        query += "AND created_at >= ? "
        params.append(float(created_after))
    query += "ORDER BY priority DESC, created_at ASC LIMIT ?"
    params.append(int(limit))
    with _connect(path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_event_from_row(row) for row in rows]


def pending_count(
    path: Path = DEFAULT_QUEUE_PATH,
    *,
    created_after: float | None = None,
) -> int:
    params: list[Any] = []
    query = "SELECT COUNT(*) AS count FROM events WHERE status = 'pending'"
    if created_after is not None:
        query += " AND created_at >= ?"
        params.append(float(created_after))
    with _connect(path) as conn:
        row = conn.execute(query, params).fetchone()
    return int(row["count"])


def get_active_event(
    path: Path = DEFAULT_QUEUE_PATH,
    *,
    created_after: float | None = None,
) -> AgentEvent | None:
    params: list[Any] = []
    query = "SELECT * FROM events WHERE status = 'active' "
    if created_after is not None:
        query += "AND created_at >= ? "
        params.append(float(created_after))
    query += "ORDER BY updated_at DESC LIMIT 1"
    with _connect(path) as conn:
        row = conn.execute(query, params).fetchone()
    return _event_from_row(row) if row else None


def activate_next_event(
    path: Path = DEFAULT_QUEUE_PATH,
    *,
    created_after: float | None = None,
) -> AgentEvent | None:
    """Return the active event, or promote the next pending event."""

    active = get_active_event(path, created_after=created_after)
    if active is not None:
        return active

    now = time.time()
    params: list[Any] = []
    query = "SELECT * FROM events WHERE status = 'pending' "
    if created_after is not None:
        query += "AND created_at >= ? "
        params.append(float(created_after))
    query += "ORDER BY priority DESC, created_at ASC LIMIT 1"
    with _connect(path) as conn:
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE events SET status = 'active', updated_at = ? WHERE id = ?",
            (now, int(row["id"])),
        )
        updated = conn.execute(
            "SELECT * FROM events WHERE id = ?",
            (int(row["id"]),),
        ).fetchone()
    return _event_from_row(updated)


def update_event_status(
    event_id: int,
    status: str,
    *,
    path: Path = DEFAULT_QUEUE_PATH,
) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE events SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), int(event_id)),
        )


def clear_done(*, older_than_seconds: float | None = None, path: Path = DEFAULT_QUEUE_PATH) -> int:
    """Delete completed events, optionally only older than an age."""

    cutoff = time.time() - older_than_seconds if older_than_seconds is not None else None
    with _connect(path) as conn:
        if cutoff is None:
            cur = conn.execute("DELETE FROM events WHERE status = 'done'")
        else:
            cur = conn.execute(
                "DELETE FROM events WHERE status = 'done' AND updated_at < ?",
                (cutoff,),
            )
    return int(cur.rowcount or 0)
