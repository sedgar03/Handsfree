from __future__ import annotations

import json

import conductor_transcript


def test_append_transcript_event_writes_jsonl(tmp_path):
    path = conductor_transcript.append_transcript_event(
        "voice/session",
        "user",
        text="help me plan",
        root=tmp_path,
    )

    assert path == tmp_path / "voice_session.jsonl"
    record = json.loads(path.read_text().strip())
    assert record["conversation_id"] == "voice/session"
    assert record["type"] == "user"
    assert record["text"] == "help me plan"
    assert record["time"].endswith("Z")


def test_format_transcript_record_prefers_text():
    rendered = conductor_transcript.format_transcript_record(
        {"time": "2026-04-15T12:00:00Z", "type": "assistant", "text": "Ready."}
    )

    assert rendered == "[2026-04-15T12:00:00Z] assistant: Ready."
