from __future__ import annotations

import json
import sys
import types

import conductor_daemon


def _mlx_config() -> dict:
    return {
        "conductor_backend": "mlx",
        "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
        "conductor_temperature": 0.3,
        "conductor_max_tokens": 180,
        "conductor_history_turns": 8,
    }


def test_conductor_prompt_allows_chatterbox_tags_with_guardrails():
    assert "[laugh]" in conductor_daemon.SYSTEM_PROMPT
    assert "[dramatic]" in conductor_daemon.SYSTEM_PROMPT
    assert "Do not invent tags" in conductor_daemon.SYSTEM_PROMPT
    assert "host-provided context snapshots" in conductor_daemon.SYSTEM_PROMPT


def test_strip_thinking_markup_removes_hidden_reasoning():
    text = "Before. <think>private chain</think> After."

    assert conductor_daemon._strip_thinking_markup(text) == "Before.  After."


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
    assert daemon._resolve_llama_model_path() == model_path.resolve()


def test_llama_cpp_load_starts_server(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    statuses = []
    popen_calls = []

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

    class FakeProcess:
        returncode = None

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return FakeProcess()

    daemon = conductor_daemon.ConductorDaemon()
    monkeypatch.setattr(daemon, "_llama_health", lambda timeout: False)
    monkeypatch.setattr(daemon, "_wait_for_llama_server", lambda: None)
    monkeypatch.setattr(conductor_daemon.shutil, "which", lambda _name: None)
    monkeypatch.setattr(conductor_daemon.subprocess, "Popen", fake_popen)

    daemon.load()

    command, kwargs = popen_calls[0]
    assert command[:3] == ["llama-server", "--model", str(model_path.resolve())]
    assert "--no-webui" in command
    assert "--log-disable" in command
    assert kwargs["cwd"] == str(conductor_daemon.REPO_ROOT)
    assert daemon.llama_ready is True
    assert statuses[-1][0][:2] == ("conductor", "ready")
    assert statuses[-1][1]["backend"] == "llama.cpp"


def test_llama_cpp_chat_uses_openai_compatible_endpoint(monkeypatch, tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    requests = []

    monkeypatch.setattr(
        conductor_daemon,
        "get_config",
        lambda: {
            "conductor_backend": "llama.cpp",
            "conductor_model": str(model_path),
            "conductor_temperature": 0.4,
            "conductor_max_tokens": 64,
            "conductor_history_turns": 2,
            "conductor_llama_host": "127.0.0.1",
            "conductor_llama_port": 8099,
            "conductor_llama_chat_timeout": 30.0,
        },
    )

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Ready to conduct."}}]}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    daemon = conductor_daemon.ConductorDaemon()
    daemon.llama_ready = True
    monkeypatch.setattr(conductor_daemon.urllib.request, "urlopen", fake_urlopen)

    response = daemon.chat("help me steer this", conversation_id="work")

    assert response == "Ready to conduct."
    request, timeout = requests[0]
    assert request.full_url == "http://127.0.0.1:8099/v1/chat/completions"
    assert timeout == 30.0
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 64
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1] == {
        "role": "user",
        "content": "help me steer this",
    }
