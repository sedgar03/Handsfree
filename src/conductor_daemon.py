#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-lm>=0.30.7"]
# ///
"""Resident local LLM daemon for phase-1 Conductor mode."""

from __future__ import annotations

import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Allow imports from src/ when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chatterbox_markup import CHATTERBOX_PROMPT_GUIDANCE
from config import CONDUCTOR_PID, CONDUCTOR_SOCKET, REPO_ROOT, get_config
from service_control import write_service_status

SYSTEM_PROMPT = f"""You are the Handsfree conductor: a resident local voice interface for a developer.
You are not the main coding model. You are a fast collaborator and orchestrator.
For now, no external tools are connected, so do not claim to inspect files, control tmux, or launch agents.
You may receive host-provided context snapshots, such as current tmux panes. Use those snapshots as factual context without implying broader live tool access.
Help the user think, clarify intent, and say what you would delegate when heavier work is needed.
Keep responses natural, concrete, and short enough for text-to-speech.
Use emotionally legible wording when it fits the situation: relief for success, mild concern for risk, apology when something fails, dry humor only when it is genuinely appropriate.
{CHATTERBOX_PROMPT_GUIDANCE}
When a future tool action is needed, name the action plainly instead of pretending it already happened."""

_THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LLAMA_BACKEND_NAMES = {"llama.cpp", "llamacpp", "llama_cpp", "gguf"}


def _strip_thinking_markup(text: str) -> str:
    text = _THINKING_RE.sub("", text)
    text = text.replace("<think>", "").replace("</think>", "")
    return text.strip()


def _normalize_backend(value: object, model_id: str) -> str:
    backend = str(value or "auto").strip().lower()
    if backend in _LLAMA_BACKEND_NAMES:
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
        candidate = REPO_ROOT / candidate
    if candidate.is_dir() and any(candidate.glob("*.gguf")):
        return "llama.cpp"
    return "mlx"


class ConductorDaemon:
    def __init__(self) -> None:
        self.config = get_config()
        self.model_id = str(
            self.config.get("conductor_model")
            or "mlx-community/Qwen3.5-2B-OptiQ-4bit"
        )
        self.backend = _normalize_backend(
            self.config.get("conductor_backend"),
            self.model_id,
        )
        self.temperature = float(self.config.get("conductor_temperature") or 0.3)
        self.max_tokens = int(self.config.get("conductor_max_tokens") or 180)
        self.history_turns = max(1, int(self.config.get("conductor_history_turns") or 8))
        self.llama_server_bin = str(
            self.config.get("conductor_llama_server_bin") or "llama-server"
        )
        self.llama_host = str(self.config.get("conductor_llama_host") or "127.0.0.1")
        self.llama_port = int(self.config.get("conductor_llama_port") or 8091)
        self.llama_ctx_size = int(self.config.get("conductor_llama_ctx_size") or 8192)
        self.llama_gpu_layers = self.config.get("conductor_llama_gpu_layers", "auto")
        self.llama_start_timeout = float(
            self.config.get("conductor_llama_start_timeout") or 300.0
        )
        self.llama_chat_timeout = float(
            self.config.get("conductor_llama_chat_timeout") or 120.0
        )
        extra_args = self.config.get("conductor_llama_extra_args") or []
        self.llama_extra_args = (
            [str(arg) for arg in extra_args] if isinstance(extra_args, list) else []
        )
        self.started_at = time.time()
        self.model = None
        self.tokenizer = None
        self.sampler = None
        self.llama_process: subprocess.Popen | None = None
        self.llama_ready = False
        self.histories: dict[str, list[dict[str, str]]] = {}

    def load(self) -> None:
        write_service_status(
            "conductor",
            "starting",
            backend=self.backend,
            model=self.model_id,
        )
        if self.backend == "llama.cpp":
            self._load_llama_cpp()
            write_service_status(
                "conductor",
                "ready",
                backend=self.backend,
                model=self.model_id,
                server=self._llama_base_url(),
            )
            return

        self._load_mlx()
        write_service_status("conductor", "ready", backend=self.backend, model=self.model_id)

    def _load_mlx(self) -> None:
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler

        self.model, self.tokenizer = load(self.model_id)
        self.sampler = make_sampler(temp=self.temperature)

    def status(self) -> dict[str, Any]:
        payload = {
            "ok": True,
            "state": "ready",
            "pid": os.getpid(),
            "backend": self.backend,
            "model": self.model_id,
            "conversation_count": len(self.histories),
            "uptime_seconds": round(time.time() - self.started_at, 3),
        }
        if self.backend == "llama.cpp":
            payload["server"] = self._llama_base_url()
        return payload

    def reset(self, conversation_id: str) -> dict[str, Any]:
        self.histories.pop(conversation_id, None)
        return {"ok": True, "conversation_id": conversation_id, "reset": True}

    def chat(self, text: str, *, conversation_id: str, reset: bool = False) -> str:
        if self.backend == "mlx" and (
            self.model is None or self.tokenizer is None or self.sampler is None
        ):
            raise RuntimeError("model is not loaded")
        if self.backend == "llama.cpp" and not self.llama_ready:
            raise RuntimeError("llama.cpp server is not loaded")

        text = text.strip()
        if not text:
            return ""
        if reset:
            self.histories.pop(conversation_id, None)

        history = self.histories.setdefault(conversation_id, [])
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": text},
        ]

        if self.backend == "llama.cpp":
            response = self._chat_llama_cpp(messages)
        else:
            response = self._chat_mlx(messages)
        response = _strip_thinking_markup(str(response))
        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": response},
            ]
        )
        del history[: max(0, len(history) - self.history_turns * 2)]
        return response

    def _chat_mlx(self, messages: list[dict[str, str]]) -> str:
        prompt = self._apply_chat_template(messages)

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

    def _apply_chat_template(self, messages: list[dict[str, str]]) -> str:
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

    def _resolve_llama_model_path(self) -> Path:
        raw = Path(os.path.expanduser(self.model_id))
        candidates = [raw] if raw.is_absolute() else [REPO_ROOT / raw, raw]
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
                        f"conductor_model directory contains multiple GGUF files: {names}"
                    )
        raise RuntimeError(f"GGUF conductor model not found: {self.model_id}")

    def _llama_base_url(self) -> str:
        return f"http://{self.llama_host}:{self.llama_port}"

    def _llama_server_command(self) -> list[str]:
        model_path = self._resolve_llama_model_path()
        binary = shutil.which(self.llama_server_bin) or self.llama_server_bin
        command = [
            binary,
            "--model",
            str(model_path),
            "--host",
            self.llama_host,
            "--port",
            str(self.llama_port),
            "--ctx-size",
            str(self.llama_ctx_size),
            "--n-gpu-layers",
            str(self.llama_gpu_layers),
            "--no-webui",
        ]
        command.extend(self.llama_extra_args)
        return command

    def _load_llama_cpp(self) -> None:
        if self._llama_health(timeout=0.5):
            self.llama_ready = True
            return

        command = self._llama_server_command()
        self.llama_process = subprocess.Popen(command, cwd=str(REPO_ROOT))
        self._wait_for_llama_server()
        self.llama_ready = True

    def _llama_health(self, *, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self._llama_base_url()}/health",
                timeout=timeout,
            ) as resp:
                return 200 <= int(resp.status) < 500
        except (OSError, urllib.error.URLError, TimeoutError):
            return False

    def _wait_for_llama_server(self) -> None:
        deadline = time.monotonic() + self.llama_start_timeout
        while time.monotonic() < deadline:
            if self.llama_process is not None and self.llama_process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited before becoming ready: {self.llama_process.returncode}"
                )
            if self._llama_health(timeout=1.0):
                return
            time.sleep(0.5)
        raise TimeoutError(f"llama-server did not become ready at {self._llama_base_url()}")

    def _chat_llama_cpp(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self._llama_base_url()}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.llama_chat_timeout) as resp:
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
        if self.llama_process is None or self.llama_process.poll() is not None:
            return
        self.llama_process.terminate()
        try:
            self.llama_process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.llama_process.kill()
            self.llama_process.wait(timeout=5.0)


def _read_request(conn: socket.socket) -> dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        return {}
    payload = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _send_response(conn: socket.socket, payload: dict[str, Any]) -> None:
    conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def _serve(daemon: ConductorDaemon) -> None:
    CONDUCTOR_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    CONDUCTOR_PID.write_text(f"{os.getpid()}\n")
    if CONDUCTOR_SOCKET.exists():
        CONDUCTOR_SOCKET.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(CONDUCTOR_SOCKET))
    server.listen(8)

    def _shutdown(*_args) -> None:
        daemon.close()
        write_service_status(
            "conductor",
            "stopped",
            backend=daemon.backend,
            model=daemon.model_id,
        )
        try:
            server.close()
        finally:
            CONDUCTOR_SOCKET.unlink(missing_ok=True)
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        conn, _ = server.accept()
        with conn:
            try:
                request = _read_request(conn)
                command = request.get("command")
                conversation_id = str(request.get("conversation_id") or "default")
                if command in {"ping", "status"}:
                    _send_response(conn, daemon.status())
                elif command == "reset":
                    _send_response(conn, daemon.reset(conversation_id))
                elif command == "chat":
                    response = daemon.chat(
                        str(request.get("text") or ""),
                        conversation_id=conversation_id,
                        reset=bool(request.get("reset")),
                    )
                    _send_response(
                        conn,
                        {
                            "ok": True,
                            "response": response,
                            "conversation_id": conversation_id,
                            "backend": daemon.backend,
                            "model": daemon.model_id,
                        },
                    )
                else:
                    _send_response(conn, {"ok": False, "error": "unknown command"})
            except Exception as exc:  # noqa: BLE001
                _send_response(conn, {"ok": False, "error": str(exc)})


def main() -> int:
    os.environ["HANDSFREE_CONDUCTOR_DAEMON"] = "1"
    daemon = ConductorDaemon()
    try:
        daemon.load()
        _serve(daemon)
    except Exception as exc:  # noqa: BLE001
        daemon.close()
        write_service_status(
            "conductor",
            "error",
            backend=daemon.backend,
            model=daemon.model_id,
            error=str(exc),
        )
        print(f"[conductor-daemon] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
