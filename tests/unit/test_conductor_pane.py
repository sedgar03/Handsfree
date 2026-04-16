from __future__ import annotations

import subprocess

import conductor_pane


def test_open_conductor_pane_prints_attach_command_outside_tmux(monkeypatch, tmp_path):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(conductor_pane, "ensure_transcript", lambda _conversation_id: tmp_path / "voice.jsonl")
    monkeypatch.setattr(conductor_pane.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(conductor_pane, "_sessions", lambda: ["work"])

    payload = conductor_pane.open_conductor_pane(conversation_id="voice")

    assert payload["ok"] is True
    assert payload["created"] is False
    assert payload["session"] == "work"
    assert "tmux new-window -t work:" in payload["attach_command"]
    assert "tmux attach-session -t work" in payload["attach_command"]


def test_open_conductor_pane_creates_window_inside_tmux(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(conductor_pane, "ensure_transcript", lambda _conversation_id: tmp_path / "voice.jsonl")
    monkeypatch.setattr(conductor_pane.shutil, "which", lambda _name: "/usr/bin/tmux")
    monkeypatch.setattr(conductor_pane, "_sessions", lambda: ["work"])
    monkeypatch.setattr(conductor_pane, "_current_session", lambda: "work")
    monkeypatch.setattr(
        conductor_pane,
        "_tmux",
        lambda args, capture=True: calls.append((args, capture))
        or subprocess.CompletedProcess(["tmux", *args], 0, "", ""),
    )

    payload = conductor_pane.open_conductor_pane(conversation_id="voice")

    assert payload["ok"] is True
    assert payload["created"] is True
    assert calls[0][0][:5] == ["new-window", "-t", "work:", "-n", "handsfree-conductor"]
