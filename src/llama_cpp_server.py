"""Small llama.cpp server wrapper shared by local model daemons."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LLAMA_BACKEND_NAMES = {"llama.cpp", "llamacpp", "llama_cpp", "gguf"}


def normalize_model_backend(value: object, model_id: str, repo_root: Path) -> str:
    backend = str(value or "auto").strip().lower()
    if backend in LLAMA_BACKEND_NAMES:
        return "llama.cpp"
    if backend == "mlx":
        return "mlx"
    if backend != "auto":
        return "mlx"

    expanded = os.path.expanduser(model_id)
    if expanded.endswith(".gguf"):
        return "llama.cpp"
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if candidate.is_dir() and any(candidate.glob("*.gguf")):
        return "llama.cpp"
    return "mlx"


def resolve_gguf_model_path(model_id: str, repo_root: Path) -> Path:
    raw = Path(os.path.expanduser(model_id))
    candidates = [raw] if raw.is_absolute() else [repo_root / raw, raw]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
        if candidate.is_dir():
            gguf_files = sorted(candidate.glob("*.gguf"))
            if len(gguf_files) == 1:
                return gguf_files[0].resolve()
            if len(gguf_files) > 1:
                names = ", ".join(path.name for path in gguf_files[:5])
                raise RuntimeError(
                    f"model directory contains multiple GGUF files: {names}"
                )
    raise RuntimeError(f"GGUF model not found: {model_id}")


class LlamaCppServer:
    def __init__(
        self,
        *,
        model_id: str,
        repo_root: Path,
        server_bin: str = "llama-server",
        host: str = "127.0.0.1",
        port: int = 8091,
        ctx_size: int = 8192,
        gpu_layers: object = "auto",
        start_timeout: float = 300.0,
        chat_timeout: float = 120.0,
        extra_args: list[str] | None = None,
    ) -> None:
        self.model_id = model_id
        self.repo_root = repo_root
        self.server_bin = server_bin
        self.host = host
        self.port = int(port)
        self.ctx_size = int(ctx_size)
        self.gpu_layers = gpu_layers
        self.start_timeout = float(start_timeout)
        self.chat_timeout = float(chat_timeout)
        self.extra_args = list(extra_args or [])
        self.process: subprocess.Popen | None = None

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def model_path(self) -> Path:
        return resolve_gguf_model_path(self.model_id, self.repo_root)

    def command(self) -> list[str]:
        binary = shutil.which(self.server_bin) or self.server_bin
        command = [
            binary,
            "--model",
            str(self.model_path()),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.ctx_size),
            "--n-gpu-layers",
            str(self.gpu_layers),
            "--no-webui",
            "--reasoning",
            "off",
        ]
        command.extend(self.extra_args)
        return command

    def health(self, *, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self.base_url()}/health",
                timeout=timeout,
            ) as resp:
                return 200 <= int(resp.status) < 500
        except (OSError, urllib.error.URLError, TimeoutError):
            return False

    def start(self) -> None:
        if self.health(timeout=0.5):
            return

        lock_path = self._lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            if self.health(timeout=0.5):
                return
            self.process = subprocess.Popen(self.command(), cwd=str(self.repo_root))
            self._wait_until_ready()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url()}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.chat_timeout) as resp:
                response = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama.cpp chat failed: {exc.code} {detail}") from exc
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"llama.cpp chat failed: {exc}") from exc

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"bad llama.cpp chat response: {response}") from exc
        return str(content)

    def close(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5.0)

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited before becoming ready: {self.process.returncode}"
                )
            if self.health(timeout=1.0):
                return
            time.sleep(0.5)
        raise TimeoutError(f"llama-server did not become ready at {self.base_url()}")

    def _lock_path(self) -> Path:
        safe_host = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.host)
        return (
            Path.home()
            / ".handsfree"
            / "locks"
            / f"llama-server-{safe_host}-{self.port}.lock"
        )
