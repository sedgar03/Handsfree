"""Model adapters for the Handsfree conductor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from config import REPO_ROOT
from llama_cpp_server import LlamaCppServer, normalize_model_backend

Message = dict[str, str]


class ConductorModelAdapter:
    def __init__(self, config: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> None:
        self.config = dict(config)
        self.repo_root = repo_root
        self.model_id = str(
            self.config.get("conductor_model")
            or "mlx-community/Qwen3.5-2B-OptiQ-4bit"
        )
        self.backend = normalize_model_backend(
            self.config.get("conductor_backend"),
            self.model_id,
            self.repo_root,
        )
        self.temperature = float(self.config.get("conductor_temperature") or 0.3)
        self.max_tokens = int(self.config.get("conductor_max_tokens") or 180)
        extra_args = self.config.get("conductor_llama_extra_args") or []
        self.model = None
        self.tokenizer = None
        self.sampler = None
        self.llama = LlamaCppServer(
            model_id=self.model_id,
            repo_root=self.repo_root,
            server_bin=str(self.config.get("conductor_llama_server_bin") or "llama-server"),
            host=str(self.config.get("conductor_llama_host") or "127.0.0.1"),
            port=int(self.config.get("conductor_llama_port") or 8091),
            ctx_size=int(self.config.get("conductor_llama_ctx_size") or 8192),
            gpu_layers=self.config.get("conductor_llama_gpu_layers", "auto"),
            start_timeout=float(self.config.get("conductor_llama_start_timeout") or 300.0),
            chat_timeout=float(self.config.get("conductor_llama_chat_timeout") or 120.0),
            extra_args=[str(arg) for arg in extra_args] if isinstance(extra_args, list) else [],
        )
        self.llama_ready = False

    def load(self) -> None:
        if self.backend == "llama.cpp":
            self.load_llama_cpp()
            return
        self.load_mlx()

    def load_mlx(self) -> None:
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler

        self.model, self.tokenizer = load(self.model_id)
        self.sampler = make_sampler(temp=self.temperature)

    def load_llama_cpp(self) -> None:
        self.llama.start()
        self.llama_ready = True

    def status_details(self) -> dict[str, Any]:
        payload = {"backend": self.backend, "model": self.model_id}
        if self.backend == "llama.cpp":
            payload["server"] = self.llama.base_url()
        return payload

    def complete(self, messages: list[Message]) -> str:
        self.ensure_ready()
        if self.backend == "llama.cpp":
            return self.chat_llama_cpp(messages)
        return self.chat_mlx(messages)

    def ensure_ready(self) -> None:
        if self.backend == "mlx" and (
            self.model is None or self.tokenizer is None or self.sampler is None
        ):
            raise RuntimeError("model is not loaded")
        if self.backend == "llama.cpp" and not self.llama_ready:
            raise RuntimeError("llama.cpp server is not loaded")

    def chat_mlx(
        self,
        messages: list[Message],
        *,
        apply_template: Callable[[list[Message]], str] | None = None,
    ) -> str:
        prompt = (
            apply_template(messages)
            if apply_template is not None
            else self.apply_chat_template(messages)
        )
        return self.generate_mlx(prompt)

    def generate_mlx(self, prompt: str) -> str:
        from mlx_lm import generate

        return str(
            generate(
                self.model,
                self.tokenizer,
                prompt=prompt,
                max_tokens=self.max_tokens,
                sampler=self.sampler,
                verbose=False,
            )
        )

    def apply_chat_template(self, messages: list[Message]) -> str:
        try:
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

    def chat_llama_cpp(self, messages: list[Message]) -> str:
        return self.llama.chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def command(self) -> list[str]:
        return self.llama.command()

    def health(self, *, timeout: float) -> bool:
        return self.llama.health(timeout=timeout)

    def wait_for_llama_server(self) -> None:
        self.llama._wait_until_ready()

    def close(self) -> None:
        self.llama.close()
