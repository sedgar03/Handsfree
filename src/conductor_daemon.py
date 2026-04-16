#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-lm>=0.30.7"]
# ///
"""Resident local LLM daemon for phase-1 Conductor mode."""

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
from config import CONDUCTOR_PID, CONDUCTOR_SOCKET, REPO_ROOT, get_config
from conductor_harness import (
    ConductorHarness,
    json_candidates as _json_candidates,
    parse_tool_call as _parse_tool_call,
    strip_thinking_markup as _strip_thinking_markup,
    tool_result_message as _tool_result_message,
)
from conductor_models import ConductorModelAdapter
from conductor_tools import execute_tool, tools_prompt
from conductor_transcript import append_transcript_event
from prompt_loader import load_prompt
from service_control import write_service_status

DEFAULT_SYSTEM_PROMPT = """You are the Handsfree conductor: a resident local voice interface for a developer.
You are not the main coding model. You are a fast collaborator and orchestrator.
{{tool_guidance}}
Only answer the user's current request. Do not volunteer status updates, pane summaries, task claims, or next actions the user did not ask for.
If the user asks what panes are open or what a pane is doing, use the tmux tools. If the needed information is not available from those tools, say what is missing.
Do not claim a file changed, a command ran, a model finished, or an agent did work unless that fact is explicitly present in the current user text or host context.
Help the user think, clarify intent, and say what you would delegate when heavier work is needed.
Keep responses natural, concrete, and short enough for text-to-speech.
Do not use markdown, bullet lists, tables, code fences, or decorative formatting in spoken replies.
Use emotionally legible wording when it fits the situation: relief for success, mild concern for risk, apology when something fails, dry humor only when it is genuinely appropriate.
{{chatterbox_guidance}}
For pane write/control requests, use the controlled pane tools only when the user explicitly asks for a specific pane action. Never claim text was sent, focus changed, or a command ran unless the tool result says it succeeded."""


def load_conductor_system_prompt() -> str:
    config = get_config()
    return load_prompt(
        "conductor_system.md",
        DEFAULT_SYSTEM_PROMPT,
        {
            "tool_guidance": tools_prompt(),
            "chatterbox_guidance": chatterbox_prompt_guidance(
                enabled=config.get("tts_provider") == "chatterbox"
            )
        },
    )


SYSTEM_PROMPT = load_conductor_system_prompt()


class ConductorDaemon:
    def __init__(self) -> None:
        self.config = get_config()
        self.started_at = time.time()
        self.model_adapter = ConductorModelAdapter(self.config, repo_root=REPO_ROOT)
        self.harness = ConductorHarness(
            complete_chat=lambda messages: self._complete_chat(messages),
            load_system_prompt=load_conductor_system_prompt,
            history_turns=int(self.config.get("conductor_history_turns") or 8),
            tool_max_rounds=int(self.config.get("conductor_tool_max_rounds") or 1),
            transcript_enabled=bool(self.config.get("conductor_transcript_enabled", True)),
            tool_executor=lambda name, args, **kwargs: execute_tool(name, args, **kwargs),
            transcript_writer=lambda conversation_id, event_type, **kwargs: append_transcript_event(
                conversation_id,
                event_type,
                **kwargs,
            ),
        )

    @property
    def model_id(self) -> str:
        return self.model_adapter.model_id

    @property
    def backend(self) -> str:
        return self.model_adapter.backend

    @property
    def temperature(self) -> float:
        return self.model_adapter.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.model_adapter.temperature = float(value)

    @property
    def max_tokens(self) -> int:
        return self.model_adapter.max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        self.model_adapter.max_tokens = int(value)

    @property
    def history_turns(self) -> int:
        return self.harness.history_turns

    @history_turns.setter
    def history_turns(self, value: int) -> None:
        self.harness.history_turns = max(1, int(value))

    @property
    def tool_max_rounds(self) -> int:
        return self.harness.tool_max_rounds

    @tool_max_rounds.setter
    def tool_max_rounds(self, value: int) -> None:
        self.harness.tool_max_rounds = max(0, int(value))

    @property
    def transcript_enabled(self) -> bool:
        return self.harness.transcript_enabled

    @transcript_enabled.setter
    def transcript_enabled(self, value: bool) -> None:
        self.harness.transcript_enabled = bool(value)

    @property
    def histories(self) -> dict[str, list[dict[str, str]]]:
        return self.harness.histories

    @property
    def model(self) -> Any:
        return self.model_adapter.model

    @model.setter
    def model(self, value: Any) -> None:
        self.model_adapter.model = value

    @property
    def tokenizer(self) -> Any:
        return self.model_adapter.tokenizer

    @tokenizer.setter
    def tokenizer(self, value: Any) -> None:
        self.model_adapter.tokenizer = value

    @property
    def sampler(self) -> Any:
        return self.model_adapter.sampler

    @sampler.setter
    def sampler(self, value: Any) -> None:
        self.model_adapter.sampler = value

    @property
    def llama(self):
        return self.model_adapter.llama

    @property
    def llama_ready(self) -> bool:
        return self.model_adapter.llama_ready

    @llama_ready.setter
    def llama_ready(self, value: bool) -> None:
        self.model_adapter.llama_ready = bool(value)

    def load(self) -> None:
        write_service_status(
            "conductor",
            "starting",
            backend=self.backend,
            model=self.model_id,
        )
        self.model_adapter.load()
        write_service_status("conductor", "ready", **self.status_details())

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
            payload["server"] = self.llama.base_url()
        return payload

    def status_details(self) -> dict[str, Any]:
        return self.model_adapter.status_details()

    def reset(self, conversation_id: str) -> dict[str, Any]:
        return self.harness.reset(conversation_id)

    def _append_transcript(
        self,
        conversation_id: str,
        event_type: str,
        text: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.harness.append_transcript(conversation_id, event_type, text=text, data=data)

    def chat(self, text: str, *, conversation_id: str, reset: bool = False) -> str:
        self.model_adapter.ensure_ready()
        return self.harness.chat(text, conversation_id=conversation_id, reset=reset)

    def _complete_chat(self, messages: list[dict[str, str]]) -> str:
        if self.backend == "llama.cpp":
            return self._chat_llama_cpp(messages)
        return self._chat_mlx(messages)

    def _chat_mlx(self, messages: list[dict[str, str]]) -> str:
        return self.model_adapter.chat_mlx(
            messages,
            apply_template=lambda prompt_messages: self._apply_chat_template(
                prompt_messages
            ),
        )

    def _apply_chat_template(self, messages: list[dict[str, str]]) -> str:
        return self.model_adapter.apply_chat_template(messages)

    def _llama_server_command(self) -> list[str]:
        return self.model_adapter.command()

    def _load_llama_cpp(self) -> None:
        self.model_adapter.load_llama_cpp()

    def _llama_health(self, *, timeout: float) -> bool:
        return self.model_adapter.health(timeout=timeout)

    def _wait_for_llama_server(self) -> None:
        self.model_adapter.wait_for_llama_server()

    def _chat_llama_cpp(self, messages: list[dict[str, str]]) -> str:
        return self.model_adapter.chat_llama_cpp(messages)

    def close(self) -> None:
        self.model_adapter.close()


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
    try:
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        return


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
                    write_service_status("conductor", "active", **daemon.status_details())
                    response = daemon.chat(
                        str(request.get("text") or ""),
                        conversation_id=conversation_id,
                        reset=bool(request.get("reset")),
                    )
                    write_service_status("conductor", "ready", **daemon.status_details())
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
                write_service_status(
                    "conductor",
                    "error",
                    **daemon.status_details(),
                    error=str(exc),
                )
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
