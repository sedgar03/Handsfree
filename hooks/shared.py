"""Shared utilities for handsfree hooks."""

from __future__ import annotations

import datetime
from pathlib import Path

DEBUG_LOG = Path("/tmp/handsfree-tts-hook.log")


def log(msg: str, tag: str = "hook"):
    """Append a timestamped log line to the shared debug log."""
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} [{tag}] {msg}\n")
