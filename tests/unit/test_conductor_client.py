from __future__ import annotations

import json
import socket

import conductor_client


class FakeSocket:
    def __init__(self, response: dict):
        self.response = response
        self.sent = b""
        self.timeouts: list[float] = []
        self.connected_to = ""
        self._recv_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def connect(self, path: str) -> None:
        self.connected_to = path

    def sendall(self, payload: bytes) -> None:
        self.sent += payload

    def recv(self, _size: int) -> bytes:
        self._recv_count += 1
        if self._recv_count == 1:
            return (json.dumps(self.response) + "\n").encode("utf-8")
        return b""


def test_request_conductor_sends_chat_payload(monkeypatch):
    fake = FakeSocket({"ok": True, "response": "hi", "conversation_id": "work"})
    monkeypatch.setattr(socket, "socket", lambda *_args: fake)

    response = conductor_client.request_conductor(
        "hello",
        conversation_id="work",
        reset=True,
        connect_timeout=1.5,
        response_timeout=7.0,
    )

    assert response == {"ok": True, "response": "hi", "conversation_id": "work"}
    payload = json.loads(fake.sent.decode("utf-8"))
    assert payload == {
        "command": "chat",
        "text": "hello",
        "conversation_id": "work",
        "reset": True,
    }
    assert fake.timeouts == [1.5, 7.0]


def test_reset_conductor_sends_reset_payload(monkeypatch):
    fake = FakeSocket({"ok": True, "conversation_id": "work", "reset": True})
    monkeypatch.setattr(socket, "socket", lambda *_args: fake)

    response = conductor_client.reset_conductor(conversation_id="work")

    assert response == {"ok": True, "conversation_id": "work", "reset": True}
    payload = json.loads(fake.sent.decode("utf-8"))
    assert payload == {"command": "reset", "conversation_id": "work"}


def test_request_conductor_returns_none_when_unreachable(monkeypatch):
    class FailingSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, _path: str) -> None:
            raise OSError("no daemon")

    monkeypatch.setattr(socket, "socket", lambda *_args: FailingSocket())

    assert conductor_client.request_conductor("hello") is None
