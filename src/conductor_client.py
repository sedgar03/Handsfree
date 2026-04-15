"""Dependency-free client for the resident conductor daemon."""

from __future__ import annotations

import json
import os
import socket
from typing import Any

from config import CONDUCTOR_SOCKET


def _send_conductor_request(
    payload: dict[str, Any],
    *,
    connect_timeout: float,
    response_timeout: float,
) -> dict[str, Any] | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(connect_timeout)
            client.connect(str(CONDUCTOR_SOCKET))
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
        return None

    if not chunks:
        return None
    try:
        response = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return response if isinstance(response, dict) else None


def request_conductor(
    text: str,
    *,
    conversation_id: str = "default",
    reset: bool = False,
    connect_timeout: float = 0.35,
    response_timeout: float = 120.0,
) -> dict[str, Any] | None:
    """Send a chat turn to the resident conductor daemon.

    Returns the decoded response payload, or ``None`` when the daemon is not
    reachable. This module intentionally has no ML/audio dependencies so hooks,
    HUD controls, and broker commands can use it from lightweight interpreters.
    """

    if os.environ.get("HANDSFREE_CONDUCTOR_DAEMON") == "1":
        return None
    if not text or not text.strip():
        return {"ok": True, "response": "", "conversation_id": conversation_id}

    payload = {
        "command": "chat",
        "text": text,
        "conversation_id": conversation_id,
        "reset": bool(reset),
    }
    return _send_conductor_request(
        payload,
        connect_timeout=connect_timeout,
        response_timeout=response_timeout,
    )


def reset_conductor(
    *,
    conversation_id: str = "default",
    connect_timeout: float = 0.35,
    response_timeout: float = 30.0,
) -> dict[str, Any] | None:
    """Clear one conductor conversation."""

    if os.environ.get("HANDSFREE_CONDUCTOR_DAEMON") == "1":
        return None
    payload = {
        "command": "reset",
        "conversation_id": conversation_id,
    }
    return _send_conductor_request(
        payload,
        connect_timeout=connect_timeout,
        response_timeout=response_timeout,
    )
