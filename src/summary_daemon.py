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

from chatterbox_markup import CHATTERBOX_PROMPT_GUIDANCE
from config import SUMMARY_PID, SUMMARY_SOCKET, get_config
from service_control import write_service_status

SYSTEM_PROMPT = f"""You compress agent replies for speech.
Return exactly one short sentence.
If VERBOSITY is tiny, return 5 to 10 words.
If VERBOSITY is terse, return 8 to 16 words.
If VERBOSITY is detailed, return 12 to 22 words.
Do not copy long source wording.
Do not mention filenames, paths, commands, markdown, test counts, or bullets.
Do not include prefixes like "No input needed" or "I need your input".
{CHATTERBOX_PROMPT_GUIDANCE}
If MODE is choice, do not choose or recommend; start with "Choose whether" and preserve the options.
If MODE is status, summarize only what changed or passed; never use "choose", "whether", or ask a question."""


class SummaryDaemon:
    def __init__(self) -> None:
        self.config = get_config()
        self.model_id = str(self.config.get("summary_model") or "mlx-community/Qwen3.5-2B-OptiQ-4bit")
        self.started_at = time.time()
        self.model = None
        self.tokenizer = None
        self.sampler = None

    def load(self) -> None:
        write_service_status("summary", "starting", model=self.model_id)
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler

        self.model, self.tokenizer = load(self.model_id)
        self.sampler = make_sampler(temp=0.0)
        write_service_status("summary", "ready", model=self.model_id)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "state": "ready",
            "pid": os.getpid(),
            "model": self.model_id,
            "uptime_seconds": round(time.time() - self.started_at, 3),
        }

    def summarize(self, text: str, *, mode: str, verbosity: str) -> str:
        if self.model is None or self.tokenizer is None or self.sampler is None:
            raise RuntimeError("model is not loaded")

        text = text.strip()
        if not text:
            return ""
        mode = "choice" if mode == "choice" else "status"
        verbosity = verbosity if verbosity in {"detailed", "terse", "tiny"} else "detailed"
        max_tokens = 18 if verbosity == "tiny" else 32 if verbosity == "terse" else 40
        user = f"MODE: {mode}\nVERBOSITY: {verbosity}\nSource: {text}\nOutput:"
        prompt = self.tokenizer.apply_chat_template(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
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
    conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def _serve(daemon: SummaryDaemon) -> None:
    SUMMARY_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PID.write_text(f"{os.getpid()}\n")
    if SUMMARY_SOCKET.exists():
        SUMMARY_SOCKET.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SUMMARY_SOCKET))
    server.listen(8)

    def _shutdown(*_args) -> None:
        write_service_status("summary", "stopped", model=daemon.model_id)
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
                    summary = daemon.summarize(
                        str(request.get("text") or ""),
                        mode=str(request.get("mode") or "status"),
                        verbosity=str(request.get("verbosity") or "detailed"),
                    )
                    _send_response(conn, {"ok": True, "summary": summary})
                else:
                    _send_response(conn, {"ok": False, "error": "unknown command"})
            except Exception as exc:  # noqa: BLE001
                _send_response(conn, {"ok": False, "error": str(exc)})


def main() -> int:
    daemon = SummaryDaemon()
    try:
        daemon.load()
        _serve(daemon)
    except Exception as exc:  # noqa: BLE001
        write_service_status("summary", "error", model=daemon.model_id, error=str(exc))
        print(f"[summary-daemon] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
