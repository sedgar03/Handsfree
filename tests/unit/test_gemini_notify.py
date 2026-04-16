from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path


def _load_module():
    sys.modules.pop("gemini_notify", None)
    return importlib.import_module("gemini_notify")


def test_after_agent_speaks_prompt_response(monkeypatch):
    module = _load_module()
    fake_summarizer = types.SimpleNamespace(summarize=lambda text: "No input needed. Gemini updated the docs.")
    monkeypatch.setitem(sys.modules, "summarizer", fake_summarizer)

    summary = module._summary_for_payload(
        {
            "hook_event_name": "AfterAgent",
            "prompt_response": "Long markdown response",
        },
        "handsfree",
    )

    assert summary == "No input needed. Gemini updated the docs."


def test_after_agent_falls_back_to_plain_markdown(monkeypatch):
    module = _load_module()
    fake_summarizer = types.SimpleNamespace(summarize=lambda _text: "")
    monkeypatch.setitem(sys.modules, "summarizer", fake_summarizer)

    summary = module._summary_for_payload(
        {
            "hook_event_name": "AfterAgent",
            "prompt_response": (
                "Patched [the file](/tmp/file.py).\n\n"
                "```bash\npytest\n```\n"
                "Validation passed."
            ),
        },
        "handsfree",
    )

    assert "the file" in summary
    assert "/tmp/file.py" not in summary
    assert "```" not in summary
    assert "Validation passed" in summary


def test_tool_permission_notification_becomes_permission_event():
    module = _load_module()
    payload = {
        "hook_event_name": "Notification",
        "notification_type": "ToolPermission",
        "message": "run shell command",
    }

    assert module._kind_for_payload(payload) == "permission"
    assert module._summary_for_payload(payload, "handsfree") == "Gemini wants permission: run shell command"


def test_gemini_dedup_suppresses_immediate_duplicate(monkeypatch, tmp_path: Path):
    module = _load_module()
    monkeypatch.setattr(module, "_DEDUP_FILE", tmp_path / "gemini-seen.json")
    monkeypatch.setattr(module, "_DEDUP_LOCK", tmp_path / "gemini-seen.lock")

    assert module._dedup_check("same assistant response") is False
    assert module._dedup_check("same assistant response") is True


def test_queue_payload_truncates_prompt_response():
    module = _load_module()

    queued = module._queue_payload(
        {
            "hook_event_name": "AfterAgent",
            "prompt_response": "x" * (module._PAYLOAD_TEXT_LIMIT + 10),
        }
    )

    assert len(queued["prompt_response"]) <= module._PAYLOAD_TEXT_LIMIT + 3
    assert queued["prompt_response"].endswith("...")


def test_main_prints_only_json_stdout(monkeypatch, capsys):
    module = _load_module()
    recorded = []

    monkeypatch.setattr(
        module,
        "_load_payload",
        lambda: {
            "hook_event_name": "AfterAgent",
            "prompt_response": "Done.",
            "cwd": "/tmp/handsfree",
            "session_id": "session-1",
        },
    )
    monkeypatch.setattr(
        module,
        "current_context",
        lambda cwd="": types.SimpleNamespace(workflow="handsfree", current_path=cwd, pane="%1"),
    )
    monkeypatch.setattr(module, "_dedup_check", lambda _key: False)
    monkeypatch.setattr(module, "_summary_for_payload", lambda _payload, _workflow: "Done.")
    monkeypatch.setattr(module, "play_notification", lambda _source: True)
    monkeypatch.setattr(module, "should_auto_speak_events", lambda: False)
    monkeypatch.setattr(module, "is_wake_enabled", lambda: False)
    monkeypatch.setattr(module, "update_event_status", lambda event_id, status: recorded.append((event_id, status)))
    monkeypatch.setattr(
        module,
        "enqueue_event",
        lambda **kwargs: recorded.append(kwargs) or types.SimpleNamespace(id=123),
    )

    assert module.main() == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"suppressOutput": True}
    assert captured.out.strip().startswith("{")
    assert recorded[-1] == (123, "done")
    assert recorded[0]["source"] == "gemini"
    assert recorded[0]["kind"] == "summary"
