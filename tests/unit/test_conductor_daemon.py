from __future__ import annotations

import sys
import types

import conductor_daemon
import llama_cpp_server


def _mlx_config() -> dict:
    return {
        "conductor_backend": "mlx",
        "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
        "conductor_temperature": 0.3,
        "conductor_max_tokens": 180,
        "conductor_history_turns": 8,
        "conductor_tool_max_rounds": 1,
        "conductor_transcript_enabled": False,
    }


def test_conductor_prompt_adds_chatterbox_guidance_only_for_chatterbox(monkeypatch):
    monkeypatch.setattr(conductor_daemon, "get_config", lambda: {"tts_provider": "kokoro"})
    kokoro_prompt = conductor_daemon.load_conductor_system_prompt()
    assert "[laugh]" not in kokoro_prompt
    assert "Do not invent tags" not in kokoro_prompt
    assert "read-only tools" in kokoro_prompt
    assert "Controlled pane tools" in kokoro_prompt
    assert "list_panes" in kokoro_prompt
    assert "send_text_to_pane" in kokoro_prompt
    assert "Only answer the user's current request" in kokoro_prompt
    assert "use the tmux tools" in kokoro_prompt
    assert "Do not use markdown" in kokoro_prompt

    monkeypatch.setattr(conductor_daemon, "get_config", lambda: {"tts_provider": "chatterbox"})
    chatterbox_prompt = conductor_daemon.load_conductor_system_prompt()
    assert "[laugh]" in chatterbox_prompt
    assert "[dramatic]" in chatterbox_prompt
    assert "Do not invent tags" in chatterbox_prompt


def test_strip_thinking_markup_removes_hidden_reasoning():
    text = "Before. <think>private chain</think> After."

    assert conductor_daemon._strip_thinking_markup(text) == "Before.  After."


def test_parse_tool_call_accepts_plain_and_fenced_json():
    assert conductor_daemon._parse_tool_call('{"tool":"list_panes","args":{}}') == {
        "name": "list_panes",
        "args": {},
    }
    assert conductor_daemon._parse_tool_call(
        '```json\n{"tool_call":{"name":"read_pane","arguments":{"pane_id":"%3"}}}\n```'
    ) == {
        "name": "read_pane",
        "args": {"pane_id": "%3"},
    }


def test_conductor_history_is_bounded(monkeypatch):
    monkeypatch.setattr(conductor_daemon, "get_config", _mlx_config)
    daemon = conductor_daemon.ConductorDaemon()
    daemon.model = object()
    daemon.tokenizer = object()
    daemon.sampler = object()
    daemon.history_turns = 2

    monkeypatch.setattr(daemon, "_apply_chat_template", lambda _messages: "prompt")
    monkeypatch.setattr(
        conductor_daemon,
        "_strip_thinking_markup",
        lambda text: text,
    )

    def fake_generate(*_args, **_kwargs):
        return "response"

    fake_mlx_lm = types.ModuleType("mlx_lm")
    fake_mlx_lm.generate = fake_generate
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx_lm)

    for idx in range(4):
        daemon.chat(f"turn {idx}", conversation_id="work")

    history = daemon.histories["work"]
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "turn 2"}


def test_conductor_chat_writes_transcript_when_enabled(monkeypatch):
    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            **_mlx_config(),
            "conductor_transcript_enabled": True,
        },
    )
    events = []
    monkeypatch.setattr(
        conductor_daemon,
        "append_transcript_event",
        lambda conversation_id, event_type, text="": events.append(
            (conversation_id, event_type, text)
        ),
    )
    daemon = conductor_daemon.ConductorDaemon()
    daemon.model = object()
    daemon.tokenizer = object()
    daemon.sampler = object()
    monkeypatch.setattr(daemon, "_apply_chat_template", lambda _messages: "prompt")
    monkeypatch.setattr(conductor_daemon, "_strip_thinking_markup", lambda text: text)

    fake_mlx_lm = types.ModuleType("mlx_lm")
    fake_mlx_lm.generate = lambda *_args, **_kwargs: "response"
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx_lm)

    daemon.chat("help me plan", conversation_id="voice")

    assert events == [
        ("voice", "user", "help me plan"),
        ("voice", "assistant", "response"),
    ]


def test_conductor_executes_tool_call_then_answers(monkeypatch):
    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            **_mlx_config(),
            "conductor_transcript_enabled": True,
        },
    )
    transcript_events = []
    monkeypatch.setattr(
        conductor_daemon,
        "append_transcript_event",
        lambda conversation_id, event_type, **kwargs: transcript_events.append(
            (conversation_id, event_type, kwargs)
        ),
    )
    tool_calls = []
    monkeypatch.setattr(
        conductor_daemon,
        "execute_tool",
        lambda name, args: tool_calls.append((name, args))
        or {
            "ok": True,
            "panes": [{"pane_id": "%3", "window": "work"}],
            "summary": "%3: work",
        },
    )

    daemon = conductor_daemon.ConductorDaemon()
    daemon.model = object()
    daemon.tokenizer = object()
    daemon.sampler = object()
    responses = iter(
        [
            '{"tool":"list_panes","args":{}}',
            "I see one tmux pane: work.",
        ]
    )
    calls = []

    def fake_complete(messages):
        calls.append(list(messages))
        return next(responses)

    monkeypatch.setattr(daemon, "_complete_chat", fake_complete)

    response = daemon.chat("what tmux panes are open?", conversation_id="voice")

    assert response == "I see one tmux pane: work."
    assert tool_calls == [("list_panes", {})]
    assert "Tool result for list_panes" in calls[1][-1]["content"]
    assert daemon.histories["voice"][-1] == {
        "role": "assistant",
        "content": "I see one tmux pane: work.",
    }
    assert [event[1] for event in transcript_events] == ["user", "tool", "assistant"]
    assert transcript_events[1][2]["data"]["name"] == "list_panes"


def test_conductor_auto_selects_llama_cpp_for_gguf_directory(monkeypatch, tmp_path):
    model_dir = tmp_path / "supergemma"
    model_dir.mkdir()
    model_path = model_dir / "supergemma.gguf"
    model_path.write_bytes(b"")

    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            "conductor_backend": "auto",
            "conductor_model": str(model_dir),
        },
    )

    daemon = conductor_daemon.ConductorDaemon()

    assert daemon.backend == "llama.cpp"
    assert daemon.llama.model_path() == model_path.resolve()


def test_llama_cpp_load_starts_server(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    statuses = []

    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            "conductor_backend": "llama.cpp",
            "conductor_model": str(model_path),
            "conductor_llama_server_bin": "llama-server",
            "conductor_llama_host": "127.0.0.1",
            "conductor_llama_port": 8099,
            "conductor_llama_ctx_size": 4096,
            "conductor_llama_gpu_layers": "auto",
            "conductor_llama_start_timeout": 5.0,
            "conductor_llama_chat_timeout": 30.0,
            "conductor_llama_extra_args": ["--log-disable"],
        },
    )
    monkeypatch.setattr(
        conductor_daemon,
        "write_service_status",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    daemon = conductor_daemon.ConductorDaemon()
    monkeypatch.setattr(llama_cpp_server.shutil, "which", lambda _name: None)
    starts = []
    monkeypatch.setattr(daemon.llama, "start", lambda: starts.append(True))

    daemon.load()

    command = daemon._llama_server_command()
    assert command[:3] == ["llama-server", "--model", str(model_path.resolve())]
    assert "--no-webui" in command
    assert "--log-disable" in command
    assert starts == [True]
    assert daemon.llama_ready is True
    assert statuses[-1][0][:2] == ("conductor", "ready")
    assert statuses[-1][1]["backend"] == "llama.cpp"


def test_conductor_llama_cpp_chat_uses_shared_client(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    calls = []

    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            "conductor_backend": "llama.cpp",
            "conductor_model": str(model_path),
            "conductor_temperature": 0.4,
            "conductor_max_tokens": 64,
            "conductor_history_turns": 2,
            "conductor_transcript_enabled": False,
            "conductor_llama_host": "127.0.0.1",
            "conductor_llama_port": 8099,
            "conductor_llama_chat_timeout": 30.0,
        },
    )

    daemon = conductor_daemon.ConductorDaemon()
    daemon.llama_ready = True
    monkeypatch.setattr(
        daemon.llama,
        "chat",
        lambda messages, **kwargs: calls.append((messages, kwargs)) or "Ready to conduct.",
    )

    response = daemon.chat("help me steer this", conversation_id="work")

    assert response == "Ready to conduct."
    messages, kwargs = calls[0]
    assert kwargs == {"temperature": 0.4, "max_tokens": 64}
    assert messages[0]["role"] == "system"
    assert messages[-1] == {
        "role": "user",
        "content": "help me steer this",
    }
