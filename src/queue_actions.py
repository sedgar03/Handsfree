"""High-level queue actions shared by hooks, broker CLI, and listener."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import time

from config import get_config, queue_consume_after_timestamp
from event_queue import AgentEvent, activate_next_event, get_active_event, update_event_status
from tmux_target import send_text_to_pane

_SKIP_WORDS = {"skip", "dismiss", "clear", "done", "never mind", "nevermind"}
_REPEAT_WORDS = {"repeat", "say again", "read again"}
INTRO_PAUSE_SECONDS = 0.5
_TMUX_PANE_NOUN = r"(?:panes?|pains?|terminals?|windows?)"
_TMUX_PANE_QUERY_RE = re.compile(
    rf"\btmux\b.*\b{_TMUX_PANE_NOUN}\b|"
    rf"\b{_TMUX_PANE_NOUN}\b.*\btmux\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class TmuxPane:
    location: str
    pane_id: str
    window: str
    cwd: str
    command: str
    title: str
    active: bool = False


def workflow_intro_text(workflow: str) -> str:
    """Return a short spoken context marker for an agent event."""

    label = re.sub(r"\s+", " ", workflow or "").strip(" .:-\t")
    if not label:
        return ""
    return f"{label} here."


def _event_body_text(event: AgentEvent) -> str:
    body = event.summary.strip()
    if event.kind == "permission":
        body = body.rstrip(".")
        return f"Permission needed. {body}. Say allow or deny."
    return body


def _spoken_event_text(event: AgentEvent) -> str:
    parts: list[str] = []
    intro = workflow_intro_text(event.workflow)
    if intro:
        parts.append(intro)
    parts.append(_event_body_text(event))
    return ". ".join(part.strip(". ") for part in parts if part.strip())


def _spoken_event_parts(event: AgentEvent) -> tuple[str, str]:
    return workflow_intro_text(event.workflow), _event_body_text(event)


def _queue_intro_mode() -> str:
    config = get_config()
    mode = config.get("queue_intro_mode", "auto")
    if mode in {"split", "combined"}:
        return str(mode)
    return "combined" if config.get("tts_provider") == "chatterbox" else "split"


def _speak(text: str) -> bool:
    try:
        from tts_client import request_tts_daemon

        if request_tts_daemon(text):
            return True
        try:
            from service_control import start_tts_daemon

            start_tts_daemon(wait=True, timeout=240.0)
            if request_tts_daemon(text, connect_timeout=5.0):
                return True
        except Exception as exc:  # noqa: BLE001
            print(f"[queue] TTS daemon start failed: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[queue] TTS daemon client failed: {exc}", file=sys.stderr)

    try:
        from tts import speak

        speak(text)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[queue] speak failed: {exc}", file=sys.stderr)
        return False


def speak_text(text: str) -> bool:
    """Speak arbitrary text through the configured TTS path."""

    return _speak(text)


def speak_event_direct(event: AgentEvent) -> bool:
    intro, body = _spoken_event_parts(event)
    if not intro:
        return _speak(body)
    if _queue_intro_mode() == "combined":
        return _speak(_spoken_event_text(event))
    intro_ok = _speak(intro)
    time.sleep(INTRO_PAUSE_SECONDS)
    body_ok = _speak(body)
    return intro_ok and body_ok


def _conductor_event_prompt(event: AgentEvent) -> str:
    parts = [
        "A terminal agent event needs spoken handling.",
        "Produce the exact concise spoken response for the user.",
        "Preserve the factual content and any required action.",
        "If this is a permission event, keep the allow-or-deny instruction.",
        "Do not use markdown.",
        "",
        f"source: {event.source}",
        f"workflow: {event.workflow}",
        f"kind: {event.kind}",
        f"summary: {event.summary}",
    ]
    if event.target_pane:
        parts.append(f"target_pane: {event.target_pane}")
    if event.target_cwd:
        parts.append(f"target_cwd: {event.target_cwd}")
    detail = event.detail.strip()
    if detail:
        parts.append(f"detail: {detail[:1500]}")
    return "\n".join(parts)


def _speak_event_via_conductor(event: AgentEvent) -> bool:
    try:
        from conductor_client import request_conductor
        from service_control import start_conductor_daemon

        start_conductor_daemon(wait=True, timeout=120.0)
        conversation_id = f"event:{event.source}:{event.session_id or event.target_pane or 'default'}"
        payload = request_conductor(
            _conductor_event_prompt(event),
            conversation_id=conversation_id,
            connect_timeout=5.0,
            response_timeout=120.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[queue] conductor event routing failed: {exc}", file=sys.stderr)
        return speak_event_direct(event)

    if not payload or not payload.get("ok"):
        print("[queue] conductor event routing unavailable; using direct speech.", file=sys.stderr)
        return speak_event_direct(event)

    response = str(payload.get("response") or "").strip()
    if not response:
        print("[queue] conductor returned empty event response; using direct speech.", file=sys.stderr)
        return speak_event_direct(event)
    return _speak(response)


def speak_event(event: AgentEvent) -> bool:
    if get_config().get("interaction_mode") == "conductor":
        return _speak_event_via_conductor(event)
    return speak_event_direct(event)


def read_next_event(*, speak_empty: bool = False) -> AgentEvent | None:
    """Activate and speak the next queued event."""

    event = activate_next_event(created_after=queue_consume_after_timestamp())
    if event is None:
        if speak_empty:
            _speak("No queued messages.")
        return None
    if speak_event(event):
        update_event_status(event.id, "done")
    return event


def _tmux_panes_snapshot() -> str:
    try:
        result = subprocess.run(
            [
                "tmux",
                "list-panes",
                "-a",
                "-F",
                "#{session_name}:#{window_index}.#{pane_index}\t#{pane_id}\t"
                "#{window_name}\t#{pane_current_path}\t#{pane_current_command}\t"
                "#{pane_title}\t#{pane_active}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"tmux pane snapshot unavailable: {exc}"

    output = result.stdout.strip()
    if result.returncode != 0:
        detail = result.stderr.strip() or f"tmux exited with {result.returncode}"
        return f"tmux pane snapshot unavailable: {detail}"
    return output or "No tmux panes are currently visible."


def _parse_tmux_pane(line: str) -> TmuxPane | None:
    tab_parts = line.split("\t")
    if len(tab_parts) >= 7:
        location, pane_id, window, cwd, command, title, active = tab_parts[:7]
        return TmuxPane(
            location=location,
            pane_id=pane_id,
            window=window,
            cwd=cwd,
            command=command,
            title=title,
            active=active == "1",
        )

    match = re.match(
        r"(?P<location>\S+)\s+(?P<pane>%\S+)\s+cwd=(?P<cwd>\S+)\s+"
        r"command=(?P<command>\S+)\s+title=(?P<title>.*)",
        line,
    )
    if match is None:
        return None
    return TmuxPane(
        location=match.group("location"),
        pane_id=match.group("pane"),
        window="",
        cwd=match.group("cwd"),
        command=match.group("command"),
        title=match.group("title"),
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


def _tmux_pane_label(pane: TmuxPane) -> str:
    project = _clean_spoken_label(Path(pane.cwd).name or pane.cwd)
    window = _clean_spoken_label(pane.window)
    command = _spoken_command(pane.command)
    title = _clean_spoken_label(pane.title)
    host_title = title.endswith(".local") or title == "Stevens-MacBook-Pro.local"

    prefix = window if window else pane.location
    if prefix and prefix not in {project, command, title}:
        label = f"{prefix}: {project} running {command}"
    else:
        label = f"{project} running {command}"

    if title and not host_title and title not in {prefix, project, command}:
        label = f"{label}, {title}"
    return label


def _format_tmux_panes_answer(snapshot: str) -> str:
    if snapshot.startswith("tmux pane snapshot unavailable"):
        return snapshot
    if snapshot == "No tmux panes are currently visible.":
        return snapshot

    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if not lines:
        return "No tmux panes are currently visible."

    panes = [_parse_tmux_pane(line) for line in lines]
    labels = [_tmux_pane_label(pane) if pane is not None else line for pane, line in zip(panes, lines)]

    listed = labels[:10]
    sessions = {
        (pane.location.split(":", 1)[0] if pane is not None else "")
        for pane in panes
    }
    sessions.discard("")
    session_clause = f" across {len(sessions)} sessions" if len(sessions) > 1 else ""
    pane_word = "pane" if len(lines) == 1 else "panes"
    answer = f"I see {len(lines)} tmux {pane_word}{session_clause}: " + "; ".join(listed) + "."
    remainder = len(lines) - len(listed)
    if remainder > 0:
        answer += f" There are {remainder} more not listed."
    return answer


def _tmux_panes_answer_if_requested(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not _TMUX_PANE_QUERY_RE.search(normalized):
        return None
    return _format_tmux_panes_answer(_tmux_panes_snapshot())


def _conductor_turn_text(text: str) -> str:
    panes = _tmux_panes_snapshot()
    current_pane = os.environ.get("TMUX_PANE", "").strip()
    current = f"\nCurrent pane id: {current_pane}" if current_pane else ""
    return (
        "Host-provided current context follows. Treat it as factual, but do not "
        "claim broader live tool access.\n\n"
        f"Current tmux panes:{current}\n{panes}\n\n"
        f"User said: {text.strip()}"
    )


def handle_conductor_text(text: str) -> bool:
    """Route a spoken freeform command to the resident conductor."""

    if not text or not text.strip():
        return False

    print(f"[queue] Conductor command: {text.strip()}", file=sys.stderr)
    direct_answer = _tmux_panes_answer_if_requested(text)
    if direct_answer is not None:
        print(f"[queue] Answering tmux pane query directly: {direct_answer}", file=sys.stderr)
        _speak(direct_answer)
        return True

    try:
        from conductor_client import request_conductor
        from service_control import start_conductor_daemon

        start_conductor_daemon(wait=True, timeout=120.0)
        payload = request_conductor(
            _conductor_turn_text(text),
            conversation_id="voice",
            connect_timeout=5.0,
            response_timeout=120.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[queue] conductor failed: {exc}", file=sys.stderr)
        _speak("Conductor is not ready.")
        return True

    if not payload or not payload.get("ok"):
        _speak("Conductor is not ready.")
        return True

    response = str(payload.get("response") or "").strip()
    if not response:
        _speak("Conductor did not return a response.")
        return True
    _speak(response)
    return True


def _matches_any(text: str, phrases: set[str]) -> bool:
    normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()
    return any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in phrases)


def handle_active_event_text(text: str) -> bool:
    """Route a spoken response to the active event's tmux pane.

    Returns True when the transcription was consumed by queue handling.
    """

    event = get_active_event(created_after=queue_consume_after_timestamp())
    if event is None:
        return False

    if _matches_any(text, _REPEAT_WORDS):
        speak_event(event)
        return True

    if _matches_any(text, _SKIP_WORDS):
        update_event_status(event.id, "done")
        _speak("Cleared.")
        return True

    if not event.target_pane:
        return False

    if not send_text_to_pane(event.target_pane, text, submit=True):
        _speak("I could not send that to the target pane.")
        return True

    update_event_status(event.id, "done")
    workflow = event.workflow or "that workflow"
    _speak(f"Sent to {workflow}.")
    return True
