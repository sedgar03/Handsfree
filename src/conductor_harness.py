"""Conversation and tool-call harness for the Handsfree conductor."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

from conductor_tools import execute_tool
from conductor_transcript import append_transcript_event

Message = dict[str, str]
CompleteChat = Callable[[list[Message]], str]
LoadSystemPrompt = Callable[[], str]
ToolExecutor = Callable[..., dict[str, Any]]
TranscriptWriter = Callable[..., Any]

_THINKING_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TOOL_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def strip_thinking_markup(text: str) -> str:
    text = _THINKING_RE.sub("", text)
    text = text.replace("<think>", "").replace("</think>", "")
    return text.strip()


def json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    candidates.extend(match.group(1).strip() for match in _TOOL_FENCE_RE.finditer(stripped))
    return candidates


def parse_tool_call(text: str) -> dict[str, Any] | None:
    """Parse the small JSON tool-call ABI from a model response."""

    for candidate in json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue

        if isinstance(parsed.get("tool_call"), dict):
            call = parsed["tool_call"]
            name = call.get("name") or call.get("tool")
            args = call.get("arguments") or call.get("args") or {}
        else:
            name = parsed.get("tool") or parsed.get("name")
            args = parsed.get("args") or parsed.get("arguments") or {}

        if isinstance(name, str) and isinstance(args, dict):
            return {"name": name, "args": args}
    return None


def tool_result_message(tool_name: str, result: dict[str, Any]) -> str:
    payload = json.dumps(result, ensure_ascii=True, sort_keys=True)
    return (
        f"Tool result for {tool_name}:\n"
        f"```json\n{payload}\n```\n"
        "Now answer the user's original request in natural spoken language. "
        "If the result includes spoken_summary, prefer that wording unless the user asked for raw details. "
        "Do not output another tool call unless another tmux lookup or explicitly requested pane action is required."
    )


class ConductorHarness:
    def __init__(
        self,
        *,
        complete_chat: CompleteChat,
        load_system_prompt: LoadSystemPrompt,
        history_turns: int = 8,
        tool_max_rounds: int = 1,
        transcript_enabled: bool = True,
        tool_executor: ToolExecutor = execute_tool,
        transcript_writer: TranscriptWriter = append_transcript_event,
    ) -> None:
        self.complete_chat = complete_chat
        self.load_system_prompt = load_system_prompt
        self.history_turns = max(1, int(history_turns))
        self.tool_max_rounds = max(0, int(tool_max_rounds))
        self.transcript_enabled = bool(transcript_enabled)
        self.tool_executor = tool_executor
        self.transcript_writer = transcript_writer
        self.histories: dict[str, list[Message]] = {}

    def reset(self, conversation_id: str) -> dict[str, Any]:
        self.histories.pop(conversation_id, None)
        self.append_transcript(conversation_id, "reset")
        return {"ok": True, "conversation_id": conversation_id, "reset": True}

    def append_transcript(
        self,
        conversation_id: str,
        event_type: str,
        text: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.transcript_enabled:
            return
        try:
            if data is None:
                self.transcript_writer(conversation_id, event_type, text=text)
            else:
                self.transcript_writer(conversation_id, event_type, text=text, data=data)
        except OSError as exc:
            if os.environ.get("HANDSFREE_DEBUG"):
                print(f"[conductor-harness] transcript write failed: {exc}", file=sys.stderr)

    def chat(self, text: str, *, conversation_id: str, reset: bool = False) -> str:
        text = text.strip()
        if not text:
            return ""
        if reset:
            self.histories.pop(conversation_id, None)

        self.append_transcript(conversation_id, "user", text)
        history = self.histories.setdefault(conversation_id, [])
        messages = [
            {"role": "system", "content": self.load_system_prompt()},
            *history,
            {"role": "user", "content": text},
        ]

        response = strip_thinking_markup(str(self.complete_chat(messages)))
        for _ in range(self.tool_max_rounds):
            tool_call = parse_tool_call(response)
            if tool_call is None:
                break

            tool_name = str(tool_call["name"])
            tool_args = tool_call["args"]
            result = self._execute_tool(tool_name, tool_args, user_text=text)
            self.append_transcript(
                conversation_id,
                "tool",
                text=tool_name,
                data={"name": tool_name, "args": tool_args, "result": result},
            )
            messages.extend(
                [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": tool_result_message(tool_name, result)},
                ]
            )
            response = strip_thinking_markup(str(self.complete_chat(messages)))

        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": response},
            ]
        )
        del history[: max(0, len(history) - self.history_turns * 2)]
        self.append_transcript(conversation_id, "assistant", response)
        return response

    def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        user_text: str,
    ) -> dict[str, Any]:
        try:
            return self.tool_executor(tool_name, tool_args, user_text=user_text)
        except TypeError as exc:
            if "user_text" not in str(exc):
                raise
            return self.tool_executor(tool_name, tool_args)
