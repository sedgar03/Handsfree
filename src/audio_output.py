"""Shared audio output helpers for notification sounds.

TTS and notification sounds intentionally share one file lock so they do
not talk over each other when hooks fire close together.
"""

from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

AUDIO_LOCK_FILE = Path("/tmp/handsfree-audio.lock")
DEFAULT_NOTIFICATION_SOUND = Path.home() / ".claude" / "hooks" / "sounds" / "notification.mp3"
SOUND_THEME_PATH = Path.home() / ".claude" / "theme"
SOUND_THEME_ROOT = Path.home() / ".claude" / "hooks" / "sounds"
DEFAULT_SOUND_THEME = "aoe"
MUTE_PATHS = {
    "claude": Path.home() / ".claude" / "mute",
    "codex": Path.home() / ".codex" / "mute",
    "gemini": Path.home() / ".gemini" / "mute",
}


def notifications_enabled(source: str | None = None) -> bool:
    """Return whether notification sounds are enabled for a source."""

    key = (source or "").strip().lower()
    mute_path = MUTE_PATHS.get(key)
    if mute_path is not None:
        return not mute_path.exists()
    return not any(path.exists() for path in MUTE_PATHS.values())


def play_sound(
    path: Path = DEFAULT_NOTIFICATION_SOUND,
    *,
    volume: float = 1.0,
    timeout: float = 10.0,
) -> bool:
    """Play a sound through afplay under the shared audio lock."""

    if not path.exists():
        return False

    lock_fd = open(AUDIO_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        result = subprocess.run(
            ["afplay", "-v", str(volume), str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    return result.returncode == 0


def notification_sound_path() -> Path:
    """Resolve the configured notification sound with legacy fallback."""

    try:
        theme = SOUND_THEME_PATH.read_text().strip() or DEFAULT_SOUND_THEME
    except OSError:
        theme = DEFAULT_SOUND_THEME

    candidates = (
        SOUND_THEME_ROOT / theme / "notify.mp3",
        SOUND_THEME_ROOT / theme / "notification.mp3",
        SOUND_THEME_ROOT / DEFAULT_SOUND_THEME / "notify.mp3",
        SOUND_THEME_ROOT / DEFAULT_SOUND_THEME / "notification.mp3",
        DEFAULT_NOTIFICATION_SOUND,
    )
    for path in candidates:
        if path.exists():
            return path
    return DEFAULT_NOTIFICATION_SOUND


def play_notification(source: str | None = None) -> bool:
    """Play the default notification if that source is not muted."""

    if not notifications_enabled(source):
        return False
    return play_sound(notification_sound_path())
