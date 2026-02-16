#!/Users/steven_edgar/.local/bin/uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Handsfree config reader — reads ~/.claude/voice-config.json with sensible defaults."""

import json
from pathlib import Path

HANDSFREE_TOGGLE = Path.home() / ".claude" / "handsfree"
CONFIG_PATH = Path.home() / ".claude" / "voice-config.json"

DEFAULTS = {
    "input_mode": "media_key",
    "verbosity": "detailed",
    "kokoro_voice": "af_heart",
    "hotkey": "F18",
    "auto_submit": True,
    "auto_submit_after_transcription": True,
    "silence_timeout": 2.5,
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
    return config


def is_handsfree_enabled() -> bool:
    """Check if handsfree mode is active (toggle file exists)."""
    return HANDSFREE_TOGGLE.exists()


if __name__ == "__main__":
    print(f"Handsfree enabled: {is_handsfree_enabled()}")
    print(f"Config: {json.dumps(get_config(), indent=2)}")
