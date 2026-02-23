from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import summarizer


@pytest.mark.parametrize("verbosity", ["terse", "detailed"])
def test_summarize_uses_expected_prompt(monkeypatch, verbosity: str):
    calls = []

    def fake_run(cmd, input=None, capture_output=False, text=False, timeout=None, env=None):
        calls.append(
            {
                "cmd": cmd,
                "input": input,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "env": env,
            }
        )
        return SimpleNamespace(returncode=0, stdout="  concise summary  ")

    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarizer.summarize("Module update", verbosity=verbosity)

    assert result == "concise summary"
    assert len(calls) == 1
    assert calls[0]["cmd"] == ["/usr/local/bin/claude", "-p", "-"]
    assert calls[0]["input"].startswith(summarizer.PROMPTS[verbosity])
    assert "Module update" in calls[0]["input"]
    assert calls[0]["env"]["HANDSFREE_ACTIVE"] == "1"


def test_summarize_falls_back_when_claude_binary_missing(monkeypatch):
    text = "x" * 250
    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: None)

    result = summarizer.summarize(text, verbosity="terse")

    assert result == text[:200]


def test_summarize_handles_timeout(monkeypatch):
    text = "A relatively long update that should be truncated on timeout. " * 6

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude -p", timeout=30)

    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarizer.summarize(text, verbosity="detailed")

    assert result == text[:200]


def test_summarize_uses_config_verbosity_when_unspecified(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, capture_output=False, text=False, timeout=None, env=None):
        calls.append({"cmd": cmd, "input": input})
        return SimpleNamespace(returncode=0, stdout="from-config")

    monkeypatch.setattr(summarizer, "get_config", lambda: {"verbosity": "terse"})
    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarizer.summarize("Use config verbosity", verbosity=None)

    assert result == "from-config"
    assert calls[0]["input"].startswith(summarizer.PROMPTS["terse"])
