#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Handsfree config reader — reads ~/.claude/voice-config.json with sensible defaults."""

import json
import os
from pathlib import Path

HANDSFREE_TOGGLE = Path.home() / ".claude" / "handsfree"
CONFIG_PATH = Path.home() / ".claude" / "voice-config.json"

DEFAULTS = {
    "input_mode": "media_key",
    "verbosity": "detailed",
    "kokoro_voice": "af_heart",
    "kokoro_speed": 1.1,
    "hotkey": "F18",
    "auto_submit": True,
    "auto_submit_after_transcription": True,
    "silence_timeout": 4.5,
    "max_recording": 300.0,
    "speech_threshold": 0.002,
    "silence_threshold": 0.0015,
}

VALID_INPUT_MODES = {"hotkey", "media_key"}


def get_config() -> dict:
    """Read config from ~/.claude/voice-config.json, merging with defaults."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                user_config = json.load(f)
            config.update(user_config)
        except (json.JSONDecodeError, OSError):
            pass  # Malformed or unreadable — use defaults
    # Validate input_mode
    if config.get("input_mode") not in VALID_INPUT_MODES:
        config["input_mode"] = DEFAULTS["input_mode"]
    # Environment variable overrides for per-terminal voice assignment
    # Usage: export HANDSFREE_VOICE=af_bella
    env_voice = os.environ.get("HANDSFREE_VOICE")
    if env_voice:
        config["kokoro_voice"] = env_voice
    return config


def is_handsfree_enabled() -> bool:
    """Check if handsfree mode is active (toggle file exists)."""
    return HANDSFREE_TOGGLE.exists()


if __name__ == "__main__":
    print(f"Handsfree enabled: {is_handsfree_enabled()}")
    print(f"Config: {json.dumps(get_config(), indent=2)}")
