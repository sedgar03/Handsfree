from __future__ import annotations

import json

import llama_cpp_server
from llama_cpp_server import LlamaCppServer


def test_normalize_model_backend_auto_detects_gguf_directory(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "local.gguf").write_bytes(b"")

    backend = llama_cpp_server.normalize_model_backend("auto", str(model_dir), tmp_path)

    assert backend == "llama.cpp"


def test_llama_cpp_server_command_resolves_relative_model(monkeypatch, tmp_path):
    model_dir = tmp_path / "models" / "local"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "local.gguf"
    model_path.write_bytes(b"")
    monkeypatch.setattr(llama_cpp_server.shutil, "which", lambda _name: None)

    server = LlamaCppServer(
        model_id="models/local",
        repo_root=tmp_path,
        server_bin="llama-server",
        host="127.0.0.1",
        port=8099,
        ctx_size=4096,
        gpu_layers="auto",
        extra_args=["--log-disable"],
    )

    command = server.command()

    assert command[:3] == ["llama-server", "--model", str(model_path.resolve())]
    assert "--host" in command
    assert "127.0.0.1" in command
    assert "--port" in command
    assert "8099" in command
    assert "--reasoning" in command
    assert "off" in command
    assert "--log-disable" in command


def test_llama_cpp_server_chat_uses_openai_compatible_endpoint(monkeypatch, tmp_path):
    requests = []
    server = LlamaCppServer(
        model_id="models/local",
        repo_root=tmp_path,
        host="127.0.0.1",
        port=8099,
        chat_timeout=30.0,
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

    monkeypatch.setattr(llama_cpp_server.urllib.request, "urlopen", fake_urlopen)

    response = server.chat(
        [{"role": "user", "content": "hello"}],
        temperature=0.4,
        max_tokens=64,
    )

    assert response == "Ready to conduct."
    request, timeout = requests[0]
    assert request.full_url == "http://127.0.0.1:8099/v1/chat/completions"
    assert timeout == 30.0
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "models/local"
    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 64
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
