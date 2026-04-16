from __future__ import annotations

import subprocess

import conductor_tools


def test_list_panes_returns_structured_tmux_inventory(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["tmux", "list-panes", "-a"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="dev:1.0\t%3\twork\t/tmp/project\tzsh\twork title\t1\n",
            stderr="",
        )

    monkeypatch.setattr(conductor_tools.subprocess, "run", fake_run)

    payload = conductor_tools.list_panes()

    assert payload["ok"] is True
    assert payload["panes"] == [
        {
            "location": "dev:1.0",
            "pane_id": "%3",
            "window": "work",
            "cwd": "/tmp/project",
            "command": "zsh",
            "title": "work title",
            "active": True,
        }
    ]
    assert "%3 active" in payload["summary"]
    assert payload["spoken_summary"] == "I see 1 tmux pane. work is project running shell, titled work title."


def test_read_pane_clamps_line_count_and_uses_tmux_target(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="recent output\n", stderr="")

    monkeypatch.setattr(conductor_tools.subprocess, "run", fake_run)

    payload = conductor_tools.read_pane("%3", lines=999)

    assert payload == {
        "ok": True,
        "pane_id": "%3",
        "lines": 300,
        "text": "recent output",
    }
    assert calls == [["tmux", "capture-pane", "-p", "-t", "%3", "-S", "-300"]]


def test_read_pane_rejects_invalid_target(monkeypatch):
    calls = []
    monkeypatch.setattr(conductor_tools.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    payload = conductor_tools.read_pane("; rm -rf /", lines=20)

    assert payload["ok"] is False
    assert payload["error"] == "invalid pane target"
    assert calls == []


def test_send_text_to_pane_requires_explicit_user_intent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conductor_tools,
        "_paste_text_to_pane",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    payload = conductor_tools.send_text_to_pane("%3", "git status")

    assert payload["ok"] is False
    assert payload["requires_clarification"] is True
    assert calls == []


def test_send_text_to_pane_drafts_single_line_without_submit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conductor_tools,
        "_paste_text_to_pane",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    payload = conductor_tools.send_text_to_pane(
        "%3",
        "git status",
        user_text="type git status into pane %3",
    )

    assert payload["ok"] is True
    assert payload["pane_id"] == "%3"
    assert payload["drafted"] is True
    assert payload["submitted"] is False
    assert calls == [(("%3", "git status"), {"submit": False})]


def test_send_text_to_pane_rejects_newlines_and_submit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conductor_tools,
        "_paste_text_to_pane",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    newline = conductor_tools.send_text_to_pane(
        "%3",
        "git status\n",
        user_text="paste git status into pane %3",
    )
    submit = conductor_tools.send_text_to_pane(
        "%3",
        "git status",
        submit=True,
        user_text="paste and run git status into pane %3",
    )

    assert newline["ok"] is False
    assert "newline" in newline["error"]
    assert submit["ok"] is False
    assert submit["requires_confirmation"] is True
    assert calls == []


def test_focus_pane_selects_tmux_target(monkeypatch):
    calls = []

    def fake_tmux(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(["tmux", *args], 0, "", "")

    monkeypatch.setattr(conductor_tools, "_run_tmux", fake_tmux)

    payload = conductor_tools.focus_pane("%3", user_text="focus pane %3")

    assert payload == {
        "ok": True,
        "pane_id": "%3",
        "focused": True,
        "spoken_summary": "I focused pane %3.",
    }
    assert calls == [(["select-pane", "-t", "%3"], {})]


def test_submit_pane_requires_confirmation_layer():
    payload = conductor_tools.submit_pane("%3", user_text="press enter in pane %3")

    assert payload["ok"] is False
    assert payload["requires_confirmation"] is True
    assert "not enabled yet" in payload["error"]


def test_execute_tool_passes_user_text_to_write_guard(monkeypatch):
    calls = []
    monkeypatch.setattr(
        conductor_tools,
        "_paste_text_to_pane",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    payload = conductor_tools.execute_tool(
        "send_text_to_pane",
        {"pane_id": "%3", "text": "git status", "submit": False},
        user_text="type git status into pane %3",
    )

    assert payload["ok"] is True
    assert calls == [(("%3", "git status"), {"submit": False})]


def test_execute_tool_rejects_unknown_tool():
    payload = conductor_tools.execute_tool("run_command", {})

    assert payload == {"ok": False, "error": "unknown tool: run_command"}
