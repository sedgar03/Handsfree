"""tmux workflow labeling and targeted input helpers."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class TmuxContext:
    pane: str | None
    workflow: str
    window_name: str = ""
    pane_title: str = ""
    current_path: str = ""
    current_command: str = ""


_PLACEHOLDER_TITLES = {
    "",
    "node",
    "bash",
    "zsh",
    "python",
    "python3",
    "tmux",
}


def _clean_label(value: str) -> str:
    """Normalize a tmux title/window label for spoken use."""

    label = re.sub(r"^[^\w/.-]+", "", value.strip())
    label = re.sub(r"\s+", " ", label).strip(" -:\t")
    return label


def _label_is_useful(value: str) -> bool:
    label = _clean_label(value)
    if label.lower() in _PLACEHOLDER_TITLES:
        return False
    if label.endswith(".local"):
        return False
    return bool(label)


def current_context(pane: str | None = None, cwd: str | None = None) -> TmuxContext:
    """Read tmux metadata and choose a human workflow label.

    Preference order:
    1. tmux window name, if it looks human-authored
    2. pane title
    3. cwd basename
    """

    target = pane or os.environ.get("TMUX_PANE")
    fallback_cwd = cwd or os.getcwd()
    fallback_label = Path(fallback_cwd).name or fallback_cwd
    if not target:
        return TmuxContext(
            pane=None,
            workflow=_clean_label(fallback_label),
            current_path=fallback_cwd,
        )

    fmt = "#{pane_id}\t#{window_name}\t#{pane_title}\t#{pane_current_path}\t#{pane_current_command}"
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", target, fmt],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return TmuxContext(
            pane=target,
            workflow=_clean_label(fallback_label),
            current_path=fallback_cwd,
        )

    parts = result.stdout.rstrip("\n").split("\t")
    while len(parts) < 5:
        parts.append("")
    pane_id, window_name, pane_title, current_path, current_command = parts[:5]

    if _label_is_useful(window_name):
        workflow = _clean_label(window_name)
    elif _label_is_useful(pane_title):
        workflow = _clean_label(pane_title)
    else:
        workflow = _clean_label(Path(current_path or fallback_cwd).name or fallback_label)

    return TmuxContext(
        pane=pane_id or target,
        workflow=workflow,
        window_name=_clean_label(window_name),
        pane_title=_clean_label(pane_title),
        current_path=current_path or fallback_cwd,
        current_command=current_command,
    )


def send_text_to_pane(pane: str, text: str, *, submit: bool = True) -> bool:
    """Paste text into a tmux pane and optionally press Enter."""

    if not pane or not text:
        return False

    buffer_name = f"handsfree-{os.getpid()}"
    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buffer_name, "-"],
            input=text,
            text=True,
            check=True,
            timeout=5,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-d", "-b", buffer_name, "-t", pane],
            check=True,
            timeout=5,
        )
        if submit:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane, "Enter"],
                check=True,
                timeout=5,
            )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return True
