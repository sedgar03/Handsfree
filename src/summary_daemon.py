#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-lm>=0.30.7"]
# ///
"""Resident MLX summary daemon for fast spoken status updates."""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any

# Allow imports from src/ when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chatterbox_markup import chatterbox_prompt_guidance
from config import REPO_ROOT, SUMMARY_PID, SUMMARY_SOCKET, get_config
from llama_cpp_server import LlamaCppServer, normalize_model_backend
from prompt_loader import load_prompt
from service_control import write_service_status

DEFAULT_SYSTEM_PROMPT = """You are an assistant which takes responses from command line agents and prepares them for a downstream text-to-speech engine. A primary objective of this role is to compress to the desired length while maintaining essential information for the user.
{{chatterbox_guidance}}
If VERBOSITY is tiny, return 5 to 10 words.
If VERBOSITY is terse, return 10 to 20 words.
If VERBOSITY is detailed, return 45 to 110 words.
If VERBOSITY is expanded, return 100 to 220 words.
Do not include prefixes like "No input needed" or "I need your input".
Mention filenames, paths, commands, test counts, or bullets only when they are essential for the listener. When essential, paraphrase them in plain spoken language instead of reading raw syntax.
Never reproduce markdown tables, table pipes, fenced code, or raw bullet structure. Convert them into plain spoken prose.
If MODE is choice, do not choose or recommend; start with "Choose whether" and preserve the options.
If MODE is status, summarize only what changed or passed; never use "choose", "whether", or ask a question."""


def load_summary_system_prompt() -> str:
    config = get_config()
    return load_prompt(
        "summary_system.md",
        DEFAULT_SYSTEM_PROMPT,
        {
            "chatterbox_guidance": chatterbox_prompt_guidance(
                enabled=config.get("tts_provider") == "chatterbox"
            )
        },
    )


SYSTEM_PROMPT = load_summary_system_prompt()


class SummaryDaemon:
    def __init__(self) -> None:
        self.config = get_config()
        self.model_id = str(
            self.config.get("summary_model") or "mlx-community/Qwen3.5-2B-OptiQ-4bit"
        )
        self.backend = normalize_model_backend(
            self.config.get("summary_model_backend"),
            self.model_id,
            REPO_ROOT,
        )
        self.tts_provider = str(self.config.get("tts_provider") or "kokoro")
        self.started_at = time.time()
        self.model = None
        self.tokenizer = None
        self.sampler = None
        extra_args = self.config.get("summary_llama_extra_args") or []
        self.llama = LlamaCppServer(
            model_id=self.model_id,
            repo_root=REPO_ROOT,
            server_bin=str(
                self.config.get("summary_llama_server_bin") or "llama-server"
            ),
            host=str(self.config.get("summary_llama_host") or "127.0.0.1"),
            port=int(self.config.get("summary_llama_port") or 8091),
            ctx_size=int(self.config.get("summary_llama_ctx_size") or 8192),
            gpu_layers=self.config.get("summary_llama_gpu_layers", "auto"),
            start_timeout=float(
                self.config.get("summary_llama_start_timeout") or 300.0
            ),
            chat_timeout=float(self.config.get("summary_llama_chat_timeout") or 120.0),
            extra_args=(
                [str(arg) for arg in extra_args] if isinstance(extra_args, list) else []
            ),
        )

    def load(self) -> None:
        write_service_status(
            "summary",
            "starting",
            backend=self.backend,
            model=self.model_id,
            prompt_tts_provider=self.tts_provider,
        )
        if self.backend == "llama.cpp":
            self.llama.start()
            write_service_status(
                "summary",
                "ready",
                backend=self.backend,
                model=self.model_id,
                prompt_tts_provider=self.tts_provider,
                server=self.llama.base_url(),
            )
            return

        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler

        self.model, self.tokenizer = load(self.model_id)
        self.sampler = make_sampler(temp=0.0)
        write_service_status(
            "summary",
            "ready",
            backend=self.backend,
            model=self.model_id,
            prompt_tts_provider=self.tts_provider,
        )

    def status(self) -> dict[str, Any]:
        payload = {
            "ok": True,
            "state": "ready",
            "pid": os.getpid(),
            "backend": self.backend,
            "model": self.model_id,
            "prompt_tts_provider": self.tts_provider,
            "uptime_seconds": round(time.time() - self.started_at, 3),
        }
        if self.backend == "llama.cpp":
            payload["server"] = self.llama.base_url()
        return payload

    def status_details(self) -> dict[str, Any]:
        payload = {
            "backend": self.backend,
            "model": self.model_id,
            "prompt_tts_provider": self.tts_provider,
        }
        if self.backend == "llama.cpp":
            payload["server"] = self.llama.base_url()
        return payload

    def summarize(self, text: str, *, mode: str, verbosity: str) -> str:
        if self.backend == "mlx" and (
            self.model is None or self.tokenizer is None or self.sampler is None
        ):
            raise RuntimeError("model is not loaded")

        text = text.strip()
        if not text:
            return ""
        mode = "choice" if mode == "choice" else "status"
        verbosity = (
            verbosity
            if verbosity in {"expanded", "detailed", "terse", "tiny"}
            else "detailed"
        )
        max_tokens = (
            24
            if verbosity == "tiny"
            else 32
            if verbosity == "terse"
            else 320
            if verbosity == "expanded"
            else 180
        )
        user = f"MODE: {mode}\nVERBOSITY: {verbosity}\nSource: {text}\nOutput:"
        messages = [
            {"role": "system", "content": load_summary_system_prompt()},
            {"role": "user", "content": user},
        ]
        if self.backend == "llama.cpp":
            return self.llama.chat(
                messages,
                temperature=0.0,
                max_tokens=max_tokens,
            ).strip()

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

        from mlx_lm import generate

        return generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=self.sampler,
            verbose=False,
        ).strip()

    def close(self) -> None:
        self.llama.close()


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
    raw = b"".join(chunks).split(b"\n", 1)[0]
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _send_response(conn: socket.socket, payload: dict[str, Any]) -> None:
    try:
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        return


def _serve(daemon: SummaryDaemon) -> None:
    SUMMARY_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PID.write_text(f"{os.getpid()}\n")
    if SUMMARY_SOCKET.exists():
        SUMMARY_SOCKET.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SUMMARY_SOCKET))
    server.listen(8)

    def _shutdown(*_args) -> None:
        daemon.close()
        write_service_status("summary", "stopped", backend=daemon.backend, model=daemon.model_id)
        try:
            server.close()
        finally:
            SUMMARY_SOCKET.unlink(missing_ok=True)
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        conn, _ = server.accept()
        with conn:
            try:
                request = _read_request(conn)
                command = request.get("command")
                if command in {"ping", "status"}:
                    _send_response(conn, daemon.status())
                elif command == "summarize":
                    write_service_status("summary", "active", **daemon.status_details())
                    summary = daemon.summarize(
                        str(request.get("text") or ""),
                        mode=str(request.get("mode") or "status"),
                        verbosity=str(request.get("verbosity") or "detailed"),
                    )
                    write_service_status("summary", "ready", **daemon.status_details())
                    _send_response(conn, {"ok": True, "summary": summary})
                else:
                    _send_response(conn, {"ok": False, "error": "unknown command"})
            except Exception as exc:  # noqa: BLE001
                write_service_status(
                    "summary",
                    "error",
                    **daemon.status_details(),
                    error=str(exc),
                )
                _send_response(conn, {"ok": False, "error": str(exc)})


def main() -> int:
    daemon = SummaryDaemon()
    try:
        daemon.load()
        _serve(daemon)
    except Exception as exc:  # noqa: BLE001
        daemon.close()
        write_service_status(
            "summary",
            "error",
            backend=daemon.backend,
            model=daemon.model_id,
            error=str(exc),
        )
        print(f"[summary-daemon] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
