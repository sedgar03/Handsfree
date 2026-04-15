from __future__ import annotations

import subprocess
import types

import tmux_target


def test_current_context_prefers_useful_window_name(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(
            stdout="%9\tUSChem\tMap LLM chemistry papers\t/Users/stevenedgar/Code/synapse\tzsh\n"
        )

    monkeypatch.setattr(tmux_target.subprocess, "run", fake_run)

    context = tmux_target.current_context(pane="%9", cwd="/fallback")

    assert context.workflow == "USChem"
    assert context.window_name == "USChem"
    assert context.pane_title == "Map LLM chemistry papers"


def test_current_context_uses_pane_title_when_window_name_is_placeholder(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(
            stdout="%9\tzsh\tMap LLM chemistry papers\t/Users/stevenedgar/Code/synapse\tzsh\n"
        )

    monkeypatch.setattr(tmux_target.subprocess, "run", fake_run)

    context = tmux_target.current_context(pane="%9", cwd="/fallback")

    assert context.workflow == "Map LLM chemistry papers"


def test_current_context_falls_back_to_cwd_on_tmux_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["tmux"])

    monkeypatch.setattr(tmux_target.subprocess, "run", fake_run)

    context = tmux_target.current_context(pane="%9", cwd="/Users/stevenedgar/Code/handsfree")

    assert context.workflow == "handsfree"
