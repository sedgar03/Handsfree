from __future__ import annotations

import types

import broker


def test_conductor_chat_defaults_to_voice_conversation():
    args = broker.parse_args(["conductor", "chat", "hello"])

    assert args.conversation_id == "voice"


def test_conductor_reset_defaults_to_voice_conversation():
    args = broker.parse_args(["conductor", "reset"])

    assert args.conversation_id == "voice"


def test_enqueue_speak_uses_auto_speech_gate(monkeypatch, capsys):
    spoken = []

    monkeypatch.setattr(broker, "should_auto_speak_events", lambda: False)
    monkeypatch.setattr(
        broker,
        "enqueue_event",
        lambda **_kwargs: types.SimpleNamespace(id=42, status="pending"),
    )
    monkeypatch.setattr(broker, "speak_event", lambda event: spoken.append(event) or True)

    args = broker.parse_args(
        [
            "enqueue",
            "--source",
            "codex",
            "--kind",
            "notification",
            "--summary",
            "Done.",
            "--speak",
        ]
    )

    assert broker._cmd_enqueue(args) == 0
    assert spoken == []
    assert '"id": 42' in capsys.readouterr().out
