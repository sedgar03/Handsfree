from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


def _load_module():
    sys.modules.pop("codex_notify", None)
    return importlib.import_module("codex_notify")


def test_agent_turn_complete_speaks_last_assistant_message(monkeypatch):
    module = _load_module()
    fake_summarizer = types.SimpleNamespace(summarize=lambda text: "No input needed. I updated the docs.")
    monkeypatch.setitem(sys.modules, "summarizer", fake_summarizer)

    summary = module._summary_for_payload(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": "Long markdown response",
        },
        "handsfree",
    )

    assert summary == "No input needed. I updated the docs."


def test_agent_turn_complete_preserves_direct_readout(monkeypatch):
    module = _load_module()
    long_summary = "Direct speech. " * 80
    fake_summarizer = types.SimpleNamespace(summarize=lambda _text: long_summary)
    monkeypatch.setitem(sys.modules, "summarizer", fake_summarizer)

    summary = module._summary_for_payload(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": "Long markdown response",
        },
        "handsfree",
    )

    assert summary == long_summary.strip()
    assert len(summary) > 360


def test_agent_turn_complete_falls_back_to_plain_markdown(monkeypatch):
    module = _load_module()
    fake_summarizer = types.SimpleNamespace(summarize=lambda _text: "")
    monkeypatch.setitem(sys.modules, "summarizer", fake_summarizer)

    summary = module._summary_for_payload(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": (
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


def test_agent_turn_complete_without_message_keeps_generic_summary():
    module = _load_module()

    summary = module._summary_for_payload({"type": "agent-turn-complete"}, "handsfree")

    assert summary == "Codex finished a turn."


def test_codex_dedup_suppresses_immediate_duplicate(monkeypatch, tmp_path: Path):
    module = _load_module()
    monkeypatch.setattr(module, "_DEDUP_FILE", tmp_path / "codex-seen.json")
    monkeypatch.setattr(module, "_DEDUP_LOCK", tmp_path / "codex-seen.lock")

    assert module._dedup_check("same assistant response") is False
    assert module._dedup_check("same assistant response") is True


def test_codex_dedup_allows_different_message(monkeypatch, tmp_path: Path):
    module = _load_module()
    monkeypatch.setattr(module, "_DEDUP_FILE", tmp_path / "codex-seen.json")
    monkeypatch.setattr(module, "_DEDUP_LOCK", tmp_path / "codex-seen.lock")

    assert module._dedup_check("first assistant response") is False
    assert module._dedup_check("second assistant response") is False


def test_main_skips_duplicate_raw_message_before_summary(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_load_payload",
        lambda: {
            "type": "agent-turn-complete",
            "last-assistant-message": "same assistant response",
        },
    )
    monkeypatch.setattr(
        module,
        "current_context",
        lambda: types.SimpleNamespace(workflow="handsfree", current_path="/tmp", pane="%1"),
    )
    monkeypatch.setattr(module, "_dedup_check", lambda _key: True)
    monkeypatch.setattr(
        module,
        "_summary_for_payload",
        lambda _payload, _workflow: (_ for _ in ()).throw(AssertionError("summarized duplicate")),
    )

    assert module.main() == 0
