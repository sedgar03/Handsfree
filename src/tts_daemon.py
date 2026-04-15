#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile", "numpy", "chatterbox-tts>=0.1.7"]
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///
"""Resident TTS daemon for warm provider-selected playback."""

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

from config import TTS_PID, TTS_SOCKET
from service_control import write_service_status
from tts import _speak_direct, warm


class TtsDaemon:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.engine = "unknown"

    def load(self) -> None:
        write_service_status("tts", "starting")
        status = warm()
        self.engine = str(status.get("engine") or "unknown")
        write_service_status("tts", "ready", engine=self.engine)

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "state": "ready",
            "pid": os.getpid(),
            "engine": self.engine,
            "uptime_seconds": round(time.time() - self.started_at, 3),
        }


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


def _serve(daemon: TtsDaemon) -> None:
    TTS_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    TTS_PID.write_text(f"{os.getpid()}\n")
    if TTS_SOCKET.exists():
        TTS_SOCKET.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(TTS_SOCKET))
    server.listen(8)

    def _shutdown(*_args) -> None:
        write_service_status("tts", "stopped", engine=daemon.engine)
        try:
            server.close()
        finally:
            TTS_SOCKET.unlink(missing_ok=True)
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
                elif command == "speak":
                    engine = _speak_direct(
                        str(request.get("text") or ""),
                        voice=request.get("voice"),
                        speed=float(request.get("speed") or 1.1),
                    )
                    if engine:
                        daemon.engine = str(engine)
                        write_service_status("tts", "ready", engine=daemon.engine)
                    _send_response(conn, {"ok": True})
                else:
                    _send_response(conn, {"ok": False, "error": "unknown command"})
            except Exception as exc:  # noqa: BLE001
                _send_response(conn, {"ok": False, "error": str(exc)})


def main() -> int:
    os.environ["HANDSFREE_TTS_DAEMON"] = "1"
    daemon = TtsDaemon()
    try:
        daemon.load()
        _serve(daemon)
    except Exception as exc:  # noqa: BLE001
        write_service_status("tts", "error", engine=daemon.engine, error=str(exc))
        print(f"[tts-daemon] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
