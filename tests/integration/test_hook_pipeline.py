from __future__ import annotations

import importlib
import io
import json
import sys
import time
import types
from pathlib import Path


def _load_handsfree_hook(monkeypatch):
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    sys.modules.pop("handsfree_hook", None)
    module = importlib.import_module("handsfree_hook")
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    return module


def _write_transcript(tmp_path: Path, content_blocks: list[object]) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    entry = {
        "type": "assistant",
        "message": {
            "content": content_blocks,
        },
    }
    transcript.write_text(json.dumps(entry) + "\n")
    return transcript


def test_hook_pipeline_stdin_to_summary_to_speech(monkeypatch, tmp_path: Path):
    hook = _load_handsfree_hook(monkeypatch)

    transcript = _write_transcript(
        tmp_path,
        [{"type": "text", "text": "Updated tests and fixed a bug."}],
    )

    summary_calls = []
    speak_calls = []

    def fake_summarize(text: str) -> str:
        summary_calls.append(text)
        return "No input needed. Tests were updated."

    def fake_speak(text: str):
        speak_calls.append(text)

    monkeypatch.setattr(hook, "is_handsfree_enabled", lambda: True)
    monkeypatch.setattr(hook, "_log", lambda _msg: None)
    monkeypatch.setattr(hook, "_PENDING_PERMISSION_FILE", tmp_path / "pending-permission.json")
    monkeypatch.setitem(sys.modules, "summarizer", types.SimpleNamespace(summarize=fake_summarize))
    monkeypatch.setitem(sys.modules, "tts", types.SimpleNamespace(speak=fake_speak))

    payload = {"transcript_path": str(transcript)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    hook.main()

    assert summary_calls == ["Updated tests and fixed a bug."]
    assert speak_calls == ["No input needed. Tests were updated."]
