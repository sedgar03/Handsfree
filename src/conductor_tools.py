"""Tools available to the Handsfree conductor."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from tmux_target import send_text_to_pane as _paste_text_to_pane

TMUX_PANE_FORMAT = (
    "#{session_name}:#{window_index}.#{pane_index}\t"
    "#{pane_id}\t"
    "#{window_name}\t"
    "#{pane_current_path}\t"
    "#{pane_current_command}\t"
    "#{pane_title}\t"
    "#{pane_active}"
)

MAX_CAPTURE_LINES = 300
DEFAULT_CAPTURE_LINES = 80
MAX_DRAFT_CHARS = 2000

TOOL_GUIDANCE = """You have these tmux tools:

Read-only tools:
- list_panes: returns the currently open tmux panes.
- read_pane: reads recent visible text from one tmux pane.

Controlled pane tools:
- send_text_to_pane: drafts one single-line text into a specific tmux pane without pressing Enter. submit must be false.
- focus_pane: focuses a specific tmux pane.

Use read-only tools when the user's current request needs live tmux pane inventory or pane text.
Use controlled pane tools only when the user's current request explicitly asks you to type, paste, draft, or focus a specific pane. If the target pane is ambiguous, call list_panes first or ask a short clarifying question.
You still cannot run commands, press Enter, edit files, launch agents, or perform destructive actions. If the user asks to run or submit something, draft it into the pane with submit=false and tell the user it is waiting for review.

To call a tool, output exactly one JSON object and no surrounding prose:
{"tool":"list_panes","args":{}}
{"tool":"read_pane","args":{"pane_id":"%12","lines":80}}
{"tool":"send_text_to_pane","args":{"pane_id":"%12","text":"git status","submit":false}}
{"tool":"focus_pane","args":{"pane_id":"%12"}}

After a tool result is provided, answer the original user in normal spoken language.
For list_panes results, prefer spoken_summary unless the user explicitly asks for raw pane IDs or full details."""


def tools_prompt() -> str:
    return TOOL_GUIDANCE


def _tmux_error(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    error = (completed.stderr or completed.stdout or "tmux command failed").strip()
    return {"ok": False, "error": error, "returncode": completed.returncode}


def _run_tmux(args: list[str], *, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - args are passed without a shell.
        ["tmux", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_bool(value: str) -> bool:
    return value.strip() == "1"


def _pane_summary(pane: dict[str, Any]) -> str:
    active = " active" if pane["active"] else ""
    return (
        f"{pane['location']} {pane['pane_id']}{active}: "
        f"{pane['window']} / {pane['command']} / {pane['cwd']}"
    )


def _clean_spoken_label(value: str) -> str:
    label = re.sub(r"\s+", " ", value).strip()
    label = re.sub(r"^[^\w/.-]+", "", label).strip()
    return label.replace("_", " ")


def _spoken_command(command: str) -> str:
    if re.fullmatch(r"\d+(?:\.\d+)+", command):
        return "Claude"
    if command == "zsh":
        return "shell"
    if command == "tail":
        return "log tail"
    if command.startswith("python"):
        return "python"
    return command


def _pane_spoken_label(pane: dict[str, Any]) -> str:
    project = _clean_spoken_label(Path(str(pane.get("cwd") or "")).name)
    window = _clean_spoken_label(str(pane.get("window") or ""))
    command = _spoken_command(str(pane.get("command") or "process"))
    title = _clean_spoken_label(str(pane.get("title") or ""))
    host_title = title.endswith(".local") or title == "Stevens-MacBook-Pro.local"
    prefix = window or str(pane.get("location") or "").strip()
    if prefix and prefix not in {project, command, title}:
        label = f"{prefix} is {project} running {command}"
    else:
        label = f"{project} is running {command}"
    if title and not host_title and title not in {prefix, project, command}:
        label = f"{label}, titled {title}"
    return label


def _spoken_panes_summary(panes: list[dict[str, Any]]) -> str:
    if not panes:
        return "No tmux panes are currently visible."

    sessions = {
        str(pane.get("location") or "").split(":", 1)[0]
        for pane in panes
        if pane.get("location")
    }
    sessions.discard("")
    session_clause = f" across {len(sessions)} sessions" if len(sessions) > 1 else ""
    pane_word = "pane" if len(panes) == 1 else "panes"
    active = [pane for pane in panes if pane.get("active")]
    ordered = active + [pane for pane in panes if not pane.get("active")]
    listed = ordered if len(ordered) <= 3 else ordered[:3]
    labels = [_pane_spoken_label(pane) for pane in listed]

    answer = f"I see {len(panes)} tmux {pane_word}{session_clause}. "
    if len(ordered) <= 3:
        answer += " ".join(f"{label}." for label in labels)
    else:
        intro = "Active windows include: " if active else "The first few are: "
        answer += intro + " ".join(f"{label}." for label in labels)
        answer += f" I skipped {len(ordered) - len(listed)} more so this stays readable."
    return answer


def list_panes() -> dict[str, Any]:
    """Return a structured inventory of current tmux panes."""

    try:
        completed = _run_tmux(["list-panes", "-a", "-F", TMUX_PANE_FORMAT])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    if completed.returncode != 0:
        return _tmux_error(completed)

    panes: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        location, pane_id, window, cwd, command, title, active = parts[:7]
        panes.append(
            {
                "location": location,
                "pane_id": pane_id,
                "window": window,
                "cwd": cwd,
                "command": command,
                "title": title,
                "active": _parse_bool(active),
            }
        )

    return {
        "ok": True,
        "panes": panes,
        "summary": "\n".join(_pane_summary(pane) for pane in panes),
        "spoken_summary": _spoken_panes_summary(panes),
    }


def _valid_target(target: str) -> bool:
    if not target or target.startswith("-"):
        return False
    return all(char.isalnum() or char in "%:_-.@" for char in target)


def _bool_arg(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _coerce_line_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_CAPTURE_LINES
    return min(MAX_CAPTURE_LINES, max(1, count))


def read_pane(pane_id: str, *, lines: Any = DEFAULT_CAPTURE_LINES) -> dict[str, Any]:
    """Read recent text from a tmux pane by id or target location."""

    target = str(pane_id or "").strip()
    if not _valid_target(target):
        return {"ok": False, "error": "invalid pane target"}

    line_count = _coerce_line_count(lines)
    try:
        completed = _run_tmux(
            ["capture-pane", "-p", "-t", target, "-S", f"-{line_count}"],
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    if completed.returncode != 0:
        return _tmux_error(completed)

    return {
        "ok": True,
        "pane_id": target,
        "lines": line_count,
        "text": completed.stdout.rstrip(),
    }


_DRAFT_INTENT_RE = re.compile(
    r"\b(?:type|paste|draft|write|put|send)\b.*\b(?:pane|terminal|tmux|window|%\d+)\b|"
    r"\b(?:pane|terminal|tmux|window|%\d+)\b.*\b(?:type|paste|draft|write|put|send)\b",
    re.IGNORECASE,
)
_FOCUS_INTENT_RE = re.compile(
    r"\b(?:focus|switch|select|go\s+to|show)\b.*\b(?:pane|terminal|tmux|window|%\d+)\b|"
    r"\b(?:pane|terminal|tmux|window|%\d+)\b.*\b(?:focus|switch|select|go\s+to|show)\b",
    re.IGNORECASE,
)


def _requires_intent(tool_name: str, user_text: str, pattern: re.Pattern[str]) -> dict[str, Any] | None:
    if pattern.search(user_text or ""):
        return None
    return {
        "ok": False,
        "error": f"{tool_name} requires explicit current-user intent",
        "requires_clarification": True,
    }


def send_text_to_pane(
    pane_id: str,
    text: str,
    *,
    submit: Any = False,
    user_text: str = "",
) -> dict[str, Any]:
    """Draft a single line of text into a pane without submitting it."""

    intent_error = _requires_intent("send_text_to_pane", user_text, _DRAFT_INTENT_RE)
    if intent_error is not None:
        return intent_error

    target = str(pane_id or "").strip()
    if not _valid_target(target):
        return {"ok": False, "error": "invalid pane target"}

    draft = str(text or "")
    if not draft:
        return {"ok": False, "error": "text is required"}
    if len(draft) > MAX_DRAFT_CHARS:
        return {"ok": False, "error": f"text is too long; limit is {MAX_DRAFT_CHARS} characters"}
    if "\n" in draft or "\r" in draft:
        return {
            "ok": False,
            "error": "draft text must be one line; newline characters could submit input",
            "requires_clarification": True,
        }
    if _bool_arg(submit):
        return {
            "ok": False,
            "error": "submitting text is disabled in this phase; draft with submit=false",
            "requires_confirmation": True,
        }

    if not _paste_text_to_pane(target, draft, submit=False):
        return {"ok": False, "error": "failed to draft text into pane"}
    return {
        "ok": True,
        "pane_id": target,
        "drafted": True,
        "submitted": False,
        "text_preview": draft[:120],
        "spoken_summary": f"I drafted that into pane {target} without pressing Enter.",
    }


def focus_pane(pane_id: str, *, user_text: str = "") -> dict[str, Any]:
    """Focus/select a tmux pane."""

    intent_error = _requires_intent("focus_pane", user_text, _FOCUS_INTENT_RE)
    if intent_error is not None:
        return intent_error

    target = str(pane_id or "").strip()
    if not _valid_target(target):
        return {"ok": False, "error": "invalid pane target"}

    try:
        completed = _run_tmux(["select-pane", "-t", target])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    if completed.returncode != 0:
        return _tmux_error(completed)
    return {
        "ok": True,
        "pane_id": target,
        "focused": True,
        "spoken_summary": f"I focused pane {target}.",
    }


def submit_pane(pane_id: str, *, user_text: str = "") -> dict[str, Any]:
    """Reject pane submission until a confirmation layer exists."""

    del user_text
    target = str(pane_id or "").strip()
    if not _valid_target(target):
        return {"ok": False, "error": "invalid pane target"}
    return {
        "ok": False,
        "pane_id": target,
        "error": "submit_pane is not enabled yet; draft text first and review it before submitting",
        "requires_confirmation": True,
    }


def execute_tool(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    user_text: str = "",
) -> dict[str, Any]:
    """Execute one allowlisted conductor tool."""

    tool_args = args if isinstance(args, dict) else {}
    if name == "list_panes":
        return list_panes()
    if name == "read_pane":
        target = str(tool_args.get("pane_id") or tool_args.get("target") or "").strip()
        return read_pane(target, lines=tool_args.get("lines", DEFAULT_CAPTURE_LINES))
    if name == "send_text_to_pane":
        target = str(tool_args.get("pane_id") or tool_args.get("target") or "").strip()
        return send_text_to_pane(
            target,
            str(tool_args.get("text") or ""),
            submit=tool_args.get("submit", False),
            user_text=user_text,
        )
    if name == "focus_pane":
        target = str(tool_args.get("pane_id") or tool_args.get("target") or "").strip()
        return focus_pane(target, user_text=user_text)
    if name == "submit_pane":
        target = str(tool_args.get("pane_id") or tool_args.get("target") or "").strip()
        return submit_pane(target, user_text=user_text)
    return {"ok": False, "error": f"unknown tool: {name}"}
