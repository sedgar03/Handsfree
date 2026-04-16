from __future__ import annotations

from conductor_models import ConductorModelAdapter


def test_model_adapter_auto_selects_llama_cpp_for_gguf_directory(tmp_path):
    model_dir = tmp_path / "supergemma"
    model_dir.mkdir()
    model_path = model_dir / "supergemma.gguf"
    model_path.write_bytes(b"")

    adapter = ConductorModelAdapter(
        {
            "conductor_backend": "auto",
            "conductor_model": str(model_dir),
        },
        repo_root=tmp_path,
    )

    assert adapter.backend == "llama.cpp"
    assert adapter.llama.model_path() == model_path.resolve()


def test_model_adapter_llama_cpp_chat_uses_shared_client(tmp_path):
    model_path = tmp_path / "supergemma.gguf"
    model_path.write_bytes(b"")
    calls = []
    adapter = ConductorModelAdapter(
        {
            "conductor_backend": "llama.cpp",
            "conductor_model": str(model_path),
            "conductor_temperature": 0.4,
            "conductor_max_tokens": 64,
            "conductor_llama_host": "127.0.0.1",
            "conductor_llama_port": 8099,
            "conductor_llama_chat_timeout": 30.0,
        },
        repo_root=tmp_path,
    )
    adapter.llama_ready = True
    adapter.llama.chat = (
        lambda messages, **kwargs: calls.append((messages, kwargs))
        or "Ready to conduct."
    )

    response = adapter.complete([{"role": "user", "content": "hello"}])

    assert response == "Ready to conduct."
    messages, kwargs = calls[0]
    assert messages == [{"role": "user", "content": "hello"}]
    assert kwargs == {"temperature": 0.4, "max_tokens": 64}
