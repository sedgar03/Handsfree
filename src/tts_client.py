"""Dependency-free client for the resident TTS daemon."""

from __future__ import annotations

import json
import os
import socket

from config import TTS_SOCKET


def request_tts_daemon(
    text: str,
    *,
    voice: str | None = None,
    speed: float = 1.1,
    connect_timeout: float = 0.35,
    response_timeout: float = 180.0,
) -> bool:
    """Ask the resident TTS daemon to speak text.

    This module intentionally imports no audio or numeric dependencies so thin
    hooks, especially Codex's plain Python notify command, can use the warm TTS
    daemon without needing `numpy`, `sounddevice`, or Kokoro installed in that
    interpreter.
    """

    if os.environ.get("HANDSFREE_TTS_DAEMON") == "1":
        return False
    if not text or not text.strip():
        return True

    payload = {
        "command": "speak",
        "text": text,
        "voice": voice,
        "speed": speed,
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(connect_timeout)
            client.connect(str(TTS_SOCKET))
            client.settimeout(response_timeout)
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
    except OSError:
        return False
    if not chunks:
        return False
    try:
        response = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(response.get("ok"))
