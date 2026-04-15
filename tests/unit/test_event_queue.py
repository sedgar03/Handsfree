from __future__ import annotations

import sqlite3
from pathlib import Path

import event_queue


def _set_event_time(path: Path, event_id: int, timestamp: float) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE events SET created_at = ?, updated_at = ? WHERE id = ?",
            (timestamp, timestamp, event_id),
        )


def test_list_and_count_filter_events_before_consume_cutoff(tmp_path: Path):
    queue_path = tmp_path / "events.sqlite"
    old = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="old muted event",
        path=queue_path,
    )
    new = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="new unmuted event",
        path=queue_path,
    )
    _set_event_time(queue_path, old.id, 100.0)
    _set_event_time(queue_path, new.id, 200.0)

    visible = event_queue.list_events(path=queue_path, created_after=150.0)

    assert [event.id for event in visible] == [new.id]
    assert event_queue.pending_count(path=queue_path, created_after=150.0) == 1


def test_activate_next_event_skips_pending_before_consume_cutoff(tmp_path: Path):
    queue_path = tmp_path / "events.sqlite"
    old = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="old muted event",
        path=queue_path,
    )
    new = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="new unmuted event",
        path=queue_path,
    )
    _set_event_time(queue_path, old.id, 100.0)
    _set_event_time(queue_path, new.id, 200.0)

    event = event_queue.activate_next_event(path=queue_path, created_after=150.0)

    assert event is not None
    assert event.id == new.id


def test_active_event_before_consume_cutoff_does_not_block_new_event(tmp_path: Path):
    queue_path = tmp_path / "events.sqlite"
    old = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="old muted event",
        path=queue_path,
    )
    new = event_queue.enqueue_event(
        source="claude",
        kind="summary",
        summary="new unmuted event",
        path=queue_path,
    )
    _set_event_time(queue_path, old.id, 100.0)
    _set_event_time(queue_path, new.id, 200.0)
    with sqlite3.connect(queue_path) as conn:
        conn.execute("UPDATE events SET status = 'active' WHERE id = ?", (old.id,))

    event = event_queue.activate_next_event(path=queue_path, created_after=150.0)

    assert event is not None
    assert event.id == new.id
