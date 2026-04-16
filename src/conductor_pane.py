"""tmux pane/window helpers for observing conductor conversations."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Any

from config import REPO_ROOT
from conductor_transcript import ensure_transcript


def watch_command(conversation_id: str = "voice", *, lines: int = 80) -> str:
    quoted_repo = shlex.quote(str(REPO_ROOT))
    quoted_conversation = shlex.quote(conversation_id)
    return (
        f"cd {quoted_repo} && "
        "PYTHONPATH=src uv run python -m broker conductor watch "
        f"--conversation-id {quoted_conversation} --lines {int(lines)}"
    )


def _tmux(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *args],
        capture_output=capture,
        text=True,
        check=False,
    )


def _current_session() -> str:
    result = _tmux(["display-message", "-p", "#{session_name}"])
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def _sessions() -> list[str]:
    result = _tmux(["list-sessions", "-F", "#{session_name}"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build_attach_command(
    *,
    session: str,
    window_name: str,
    command: str,
    session_exists: bool,
) -> str:
    quoted_session = shlex.quote(session)
    quoted_window = shlex.quote(window_name)
    quoted_command = shlex.quote(command)
    if session_exists:
        return (
            f"tmux new-window -t {quoted_session}: -n {quoted_window} {quoted_command} "
            f"&& tmux attach-session -t {quoted_session}"
        )
    return (
        f"tmux new-session -A -s {quoted_session} -n {quoted_window} "
        f"{quoted_command}"
    )


def open_conductor_pane(
    *,
    conversation_id: str = "voice",
    session: str | None = None,
    window_name: str = "handsfree-conductor",
    attach: bool = False,
    print_only: bool = False,
    lines: int = 80,
) -> dict[str, Any]:
    ensure_transcript(conversation_id)
    command = watch_command(conversation_id, lines=lines)
    if shutil.which("tmux") is None:
        return {
            "ok": False,
            "error": "tmux not found",
            "command": command,
        }

    inside_tmux = bool(os.environ.get("TMUX"))
    existing_sessions = _sessions()
    session_exists = False
    if session:
        session_exists = session in existing_sessions
    elif inside_tmux:
        session = _current_session()
        session_exists = bool(session)
    elif existing_sessions:
        session = existing_sessions[0]
        session_exists = True
    else:
        session = "handsfree"

    attach_command = build_attach_command(
        session=session,
        window_name=window_name,
        command=command,
        session_exists=session_exists,
    )

    if print_only or (not inside_tmux and not attach):
        return {
            "ok": True,
            "created": False,
            "session": session,
            "window_name": window_name,
            "command": command,
            "attach_command": attach_command,
            "message": "Run attach_command to open the conductor transcript window.",
        }

    if session_exists:
        args = ["new-window", "-t", f"{session}:", "-n", window_name, command]
    else:
        args = ["new-session", "-d", "-s", session, "-n", window_name, command]
    result = _tmux(args)
    if result.returncode != 0:
        return {
            "ok": False,
            "error": result.stderr.strip() or f"tmux exited with {result.returncode}",
            "session": session,
            "window_name": window_name,
            "command": command,
            "attach_command": attach_command,
        }

    if attach and not inside_tmux:
        attach_result = _tmux(["attach-session", "-t", session], capture=False)
        if attach_result.returncode != 0:
            return {
                "ok": False,
                "error": f"tmux attach exited with {attach_result.returncode}",
                "session": session,
                "window_name": window_name,
                "command": command,
                "attach_command": attach_command,
            }

    return {
        "ok": True,
        "created": True,
        "session": session,
        "window_name": window_name,
        "command": command,
        "attach_command": attach_command,
    }
