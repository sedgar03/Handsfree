from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import summary_daemon
import summarizer


def test_summary_prompt_adds_chatterbox_guidance_only_for_chatterbox(monkeypatch):
    monkeypatch.setattr(summary_daemon, "get_config", lambda: {"tts_provider": "kokoro"})
    kokoro_prompt = summary_daemon.load_summary_system_prompt()
    assert "[laugh]" not in kokoro_prompt
    assert "Do not invent tags" not in kokoro_prompt

    monkeypatch.setattr(summary_daemon, "get_config", lambda: {"tts_provider": "chatterbox"})
    chatterbox_prompt = summary_daemon.load_summary_system_prompt()
    assert "[laugh]" in chatterbox_prompt
    assert "[sigh]" in chatterbox_prompt
    assert "Do not invent tags" in chatterbox_prompt


def test_legacy_claude_prompt_adds_chatterbox_guidance_only_for_chatterbox(monkeypatch):
    monkeypatch.setattr(summarizer, "get_config", lambda: {"tts_provider": "kokoro"})
    kokoro_prompt = summarizer._prompt_for_verbosity("detailed")
    assert "[laugh]" not in kokoro_prompt
    assert "Do not invent tags" not in kokoro_prompt

    monkeypatch.setattr(summarizer, "get_config", lambda: {"tts_provider": "chatterbox"})
    chatterbox_prompt = summarizer._prompt_for_verbosity("detailed")
    assert "[laugh]" in chatterbox_prompt
    assert "[sigh]" in chatterbox_prompt
    assert "Do not invent tags" in chatterbox_prompt


def test_summary_daemon_auto_selects_llama_cpp_for_gguf_directory(monkeypatch, tmp_path):
    model_dir = tmp_path / "supergemma"
    model_dir.mkdir()
    model_path = model_dir / "supergemma.gguf"
    model_path.write_bytes(b"")

    monkeypatch.setattr(
        summary_daemon,
        "get_config",
        lambda: {
            "summary_model_backend": "auto",
            "summary_model": str(model_dir),
        },
    )

    daemon = summary_daemon.SummaryDaemon()

    assert daemon.backend == "llama.cpp"
    assert daemon.llama.model_path() == model_path.resolve()


def test_summary_daemon_llama_cpp_summarize_uses_summary_prompt(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    calls = []

    monkeypatch.setattr(
        summary_daemon,
        "get_config",
        lambda: {
            "summary_model_backend": "llama.cpp",
            "summary_model": str(model_path),
            "summary_llama_host": "127.0.0.1",
            "summary_llama_port": 8099,
            "summary_llama_chat_timeout": 30.0,
        },
    )
    daemon = summary_daemon.SummaryDaemon()
    monkeypatch.setattr(
        daemon.llama,
        "chat",
        lambda messages, **kwargs: calls.append((messages, kwargs)) or "Tests passed.",
    )

    result = daemon.summarize("Updated code and tests passed.", mode="status", verbosity="terse")

    assert result == "Tests passed."
    messages, kwargs = calls[0]
    assert kwargs == {"temperature": 0.0, "max_tokens": 32}
    assert messages[0] == {
        "role": "system",
        "content": summary_daemon.load_summary_system_prompt(),
    }
    assert "VERBOSITY: terse" in messages[1]["content"]
    assert "Updated code and tests passed." in messages[1]["content"]


def test_summary_daemon_detailed_summary_allows_one_hundred_eighty_tokens(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    calls = []

    monkeypatch.setattr(
        summary_daemon,
        "get_config",
        lambda: {
            "summary_model_backend": "llama.cpp",
            "summary_model": str(model_path),
            "summary_llama_host": "127.0.0.1",
            "summary_llama_port": 8099,
            "summary_llama_chat_timeout": 30.0,
        },
    )
    daemon = summary_daemon.SummaryDaemon()
    monkeypatch.setattr(
        daemon.llama,
        "chat",
        lambda messages, **kwargs: calls.append((messages, kwargs)) or "Detailed summary.",
    )

    result = daemon.summarize("A longer update.", mode="status", verbosity="detailed")

    assert result == "Detailed summary."
    assert calls[0][1]["max_tokens"] == 180


def test_summary_daemon_expanded_summary_allows_three_hundred_twenty_tokens(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    calls = []

    monkeypatch.setattr(
        summary_daemon,
        "get_config",
        lambda: {
            "summary_model_backend": "llama.cpp",
            "summary_model": str(model_path),
            "summary_llama_host": "127.0.0.1",
            "summary_llama_port": 8099,
            "summary_llama_chat_timeout": 30.0,
        },
    )
    daemon = summary_daemon.SummaryDaemon()
    monkeypatch.setattr(
        daemon.llama,
        "chat",
        lambda messages, **kwargs: calls.append((messages, kwargs)) or "Expanded summary.",
    )

    result = daemon.summarize("A longer document update.", mode="status", verbosity="expanded")

    assert result == "Expanded summary."
    assert calls[0][1]["max_tokens"] == 320
    assert "VERBOSITY: expanded" in calls[0][0][1]["content"]


@pytest.mark.parametrize("verbosity", ["tiny", "terse", "detailed", "expanded"])
def test_summarize_claude_backend_uses_expected_prompt(monkeypatch, verbosity: str):
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
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: {"tts_provider": "chatterbox"},
    )

    result = summarizer.summarize("Module update", verbosity=verbosity, backend="claude")

    assert result == "concise summary"
    assert len(calls) == 1
    assert calls[0]["cmd"] == ["/usr/local/bin/claude", "-p", "-"]
    assert calls[0]["input"].startswith(summarizer._prompt_for_verbosity(verbosity))
    assert "Module update" in calls[0]["input"]
    assert calls[0]["env"]["HANDSFREE_ACTIVE"] == "1"


def test_summarize_direct_bypasses_model_backend(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("direct readout should not call claude")

    monkeypatch.setattr(summarizer.subprocess, "run", fail_run)

    result = summarizer.summarize(
        "Read [this file](/tmp/secret.py) directly.",
        verbosity="direct",
        backend="claude",
    )

    assert result == "Read this file directly."
    assert "/tmp/secret.py" not in result


def test_summarize_defaults_to_local_backend(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("claude -p should not run for local summaries")

    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: {"verbosity": "detailed", "summary_backend": "local"},
    )
    monkeypatch.setattr(summarizer.subprocess, "run", fail_run)

    result = summarizer.summarize(
        "Patched [the hook](/Users/me/project/hooks/codex_notify.py). "
        "Validation passed with pytest.",
    )

    assert result.startswith("No input needed.")
    assert "/Users/me" not in result
    assert "Validation passed" in result


def test_summarize_mlx_uses_deterministic_prefix(monkeypatch):
    def fake_request(*_args, **_kwargs):
        raise AssertionError("MLX should not infer explicit question text")

    monkeypatch.setattr(summarizer, "_request_mlx_summary", fake_request)

    result = summarizer.summarize_mlx(
        "Should we keep the MLX backend permanent or use the deterministic fallback?",
        verbosity="detailed",
    )

    assert result == (
        "I need your input. Should we keep the MLX backend permanent or use the "
        "deterministic fallback?"
    )


def test_summarize_mlx_falls_back_to_local(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise OSError("no socket")

    monkeypatch.setattr(summarizer, "_request_mlx_summary", fail_request)

    result = summarizer.summarize_mlx("Updated the queue and tests passed.")

    assert result.startswith("No input needed.")
    assert "Updated the queue" in result


def test_summarize_local_detects_questions():
    result = summarizer.summarize_local(
        "I found two options. Do you want me to run the full batch?",
        verbosity="detailed",
    )

    assert result.startswith("I need your input.")


def test_summarize_local_does_not_treat_relative_which_as_question():
    result = summarizer.summarize_local(
        "MOSAIC had an 18-month lag during which the frontier moved upward. "
        "The chemistry papers use models from the left side of the chart.",
        verbosity="detailed",
    )

    assert result.startswith("No input needed.")


def test_summarize_local_detects_question_without_question_mark():
    result = summarizer.summarize_local(
        "I found two options. Which database should we use.",
        verbosity="detailed",
    )

    assert result.startswith("I need your input.")


def test_summarize_local_speaks_final_question_not_status_options():
    result = summarizer.summarize_local(
        "Still running. The task spec covers a ChemBench loader and a White et al. "
        "code-gen loader. I'll let you know when Codex finishes. "
        "Want to work on anything else while it runs?",
        verbosity="detailed",
    )

    assert result == "I need your input. Want to work on anything else while it runs?"


def test_summarize_mlx_uses_deterministic_question_text(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError("MLX should not infer the question text")

    monkeypatch.setattr(summarizer, "_request_mlx_summary", fail_request)

    result = summarizer.summarize_mlx(
        "Still running. The task spec covers a ChemBench loader and a White et al. "
        "code-gen loader. Want to work on anything else while it runs?",
        verbosity="detailed",
    )

    assert result == "I need your input. Want to work on anything else while it runs?"


def test_summarize_local_respects_existing_prefix():
    result = summarizer.summarize_local(
        "No input needed. Tests passed. I updated the hook.",
        verbosity="detailed",
    )

    assert result.startswith("No input needed.")
    assert result.count("No input needed") == 1


def test_summarize_local_tiny_is_heavily_capped():
    result = summarizer.summarize_local(
        "The build completed successfully. I also updated the docs and restarted the daemon.",
        verbosity="tiny",
    )

    assert result.startswith("No input needed.")
    assert "I also updated" not in result
    assert len(result) <= 180


def test_summarize_local_expanded_keeps_more_context():
    result = summarizer.summarize_local(
        "The first document argues for a local conductor harness. "
        "The second document says the transcript pane is important for trust. "
        "The third document recommends expanded summaries for research mode. "
        "The fourth document warns that normal speech updates should stay short. "
        "The fifth document is less relevant.",
        verbosity="expanded",
    )

    assert result.startswith("No input needed.")
    assert "local conductor harness" in result
    assert "transcript pane" in result
    assert "expanded summaries" in result
    assert "normal speech updates" in result
    assert "less relevant" not in result
    assert len(result) <= 1600


def test_summarize_local_does_not_read_markdown_table_as_input_request():
    result = summarizer.summarize_local(
        "The decision rule should be pragmatic:\n\n"
        "| Outcome | Interpretation | Next Step |\n"
        "|---|---|---|\n"
        "| Prompt helps | It was under-specified | Lock prompt |\n"
        "| Prompt barely helps | Decision boundary is learned | Retrain |\n\n"
        "So yes, the question is exactly: what is the best prompted starting point "
        "before we spend another training run?\n\n"
        "My recommendation: run a small prompt-ablation benchmark next.",
        verbosity="detailed",
    )

    assert result.startswith("No input needed.")
    assert "I need your input" not in result
    assert "|" not in result


def test_summarize_falls_back_when_claude_binary_missing(monkeypatch):
    text = "A long markdown update for `/tmp/file.py`. " * 10
    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: None)

    result = summarizer.summarize(text, verbosity="terse", backend="claude")

    assert result.startswith("No input needed.")
    assert "/tmp/file.py" not in result


def test_summarize_handles_timeout(monkeypatch):
    text = "A relatively long update that should be truncated on timeout. " * 6

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude -p", timeout=30)

    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarizer.summarize(text, verbosity="detailed", backend="claude")

    assert result.startswith("No input needed.")
    assert len(result) <= 420


def test_summarize_uses_config_backend_and_verbosity_when_unspecified(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, capture_output=False, text=False, timeout=None, env=None):
        calls.append({"cmd": cmd, "input": input})
        return SimpleNamespace(returncode=0, stdout="from-config")

    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: {
            "verbosity": "terse",
            "summary_backend": "claude",
            "tts_provider": "kokoro",
        },
    )
    monkeypatch.setattr(summarizer, "_resolve_claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setattr(summarizer.subprocess, "run", fake_run)

    result = summarizer.summarize("Use config verbosity", verbosity=None)

    assert result == "from-config"
    assert calls[0]["input"].startswith(summarizer._prompt_for_verbosity("terse"))


def test_summarize_strips_speech_tags_for_non_chatterbox(monkeypatch):
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: {"verbosity": "detailed", "summary_backend": "local", "tts_provider": "kokoro"},
    )

    result = summarizer.summarize(
        "[dramatic] Updated the prompt. [think] Hidden planning should not be read.",
        verbosity="direct",
    )

    assert result == "Updated the prompt. Hidden planning should not be read."


def test_summarize_preserves_limited_valid_tags_for_chatterbox(monkeypatch):
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: {
            "verbosity": "direct",
            "summary_backend": "local",
            "tts_provider": "chatterbox",
        },
    )

    result = summarizer.summarize(
        "[dramatic] Updated the prompt. [think] Hidden planning is stripped. [happy] Tests passed.",
        verbosity="direct",
    )

    assert result == "[dramatic] Updated the prompt. Hidden planning is stripped. [happy] Tests passed."
