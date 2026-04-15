#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Handsfree config reader with shared speech-toggle support."""

import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Canonical Handsfree state directory shared by hooks, daemons, and the HUD.
HANDSFREE_HOME = Path.home() / ".handsfree"

# Canonical cross-agent speech toggle. Claude and Codex hooks should both
# read this file so the HUD can control speech from one place.
HANDSFREE_TOGGLE = HANDSFREE_HOME / "speech-enabled"
# Canonical flag for always-on wake listening / wake-word mode.
WAKE_TOGGLE = HANDSFREE_HOME / "wake-enabled"
# Optional queue-consumption watermark. HUDs or scripts can touch/write this
# when wake/speech is re-armed so old muted-era queue rows are not consumed.
CONSUME_AFTER = HANDSFREE_HOME / "consume-after"
SERVICE_STATUS_DIR = HANDSFREE_HOME / "services"
SUMMARY_SOCKET = HANDSFREE_HOME / "summary-daemon.sock"
SUMMARY_PID = HANDSFREE_HOME / "summary-daemon.pid"
TTS_SOCKET = HANDSFREE_HOME / "tts-daemon.sock"
TTS_PID = HANDSFREE_HOME / "tts-daemon.pid"
CONDUCTOR_SOCKET = HANDSFREE_HOME / "conductor-daemon.sock"
CONDUCTOR_PID = HANDSFREE_HOME / "conductor-daemon.pid"
LISTENER_PID = HANDSFREE_HOME / "listener.pid"
LOG_DIR = HANDSFREE_HOME / "logs"
# Backward-compatible fallback for older launchers / sessions.
LEGACY_HANDSFREE_TOGGLE = Path.home() / ".claude" / "handsfree"
CONFIG_PATH = Path.home() / ".claude" / "voice-config.json"

DEFAULTS = {
    "input_mode": "media_key",
    "verbosity": "detailed",
    "summary_backend": "mlx",
    "summary_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
    "conductor_backend": "auto",
    "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
    "conductor_temperature": 0.3,
    "conductor_max_tokens": 180,
    "conductor_history_turns": 8,
    "conductor_llama_server_bin": "llama-server",
    "conductor_llama_host": "127.0.0.1",
    "conductor_llama_port": 8091,
    "conductor_llama_ctx_size": 8192,
    "conductor_llama_gpu_layers": "auto",
    "conductor_llama_start_timeout": 300.0,
    "conductor_llama_chat_timeout": 120.0,
    "conductor_llama_extra_args": [],
    "interaction_mode": "off",
    "last_interaction_mode": "direct",
    "tts_provider": "kokoro",
    "chatterbox_voice": "default",
    "chatterbox_device": "cpu",
    "chatterbox_style": "auto",
    "chatterbox_style_strength": 0.35,
    "chatterbox_temperature": 0.8,
    "chatterbox_top_p": 0.95,
    "chatterbox_repetition_penalty": 1.2,
    "queue_intro_mode": "auto",
    "kokoro_voice": "af_heart",
    "kokoro_speed": 1.1,
    "hotkey": "F18",
    "auto_submit": True,
    "auto_submit_after_transcription": True,
    "silence_timeout": 4.5,
    "max_recording": 300.0,
    "speech_threshold": 0.002,
    "silence_threshold": 0.0015,
    "wake_words": ["handsfree", "hands free", "hey codex", "hey claude"],
    "wake_engine": "openwakeword",
    "openwakeword_models": ["hey jarvis"],
    "openwakeword_threshold": 0.5,
    "openwakeword_inference_framework": "onnx",
    "openwakeword_vad_threshold": 0.0,
    "openwakeword_frame_ms": 80,
    "openwakeword_cooldown": 1.5,
    "openwakeword_post_speech_cooldown": 4.0,
    "openwakeword_false_wake_limit": 3,
    "openwakeword_false_wake_window": 45.0,
    "openwakeword_false_wake_disarm": True,
    "openwakeword_auto_read_queue": True,
    "openwakeword_allow_freeform_commands": False,
    "openwakeword_command_timeout": 6.0,
    "wake_speech_threshold": 0.008,
    "wake_silence_threshold": 0.004,
    "wake_silence_timeout": 1.2,
    "wake_max_utterance": 20.0,
    "wake_min_utterance": 0.4,
    "wake_allow_queue_without_prefix": True,
}

VALID_INPUT_MODES = {"hotkey", "media_key", "wake_word"}
VALID_VERBOSITIES = {"direct", "detailed", "terse", "tiny"}
VALID_SUMMARY_BACKENDS = {"local", "mlx", "claude"}
VALID_CONDUCTOR_BACKENDS = {
    "auto",
    "mlx",
    "llama.cpp",
    "llamacpp",
    "llama_cpp",
    "gguf",
}
VALID_WAKE_ENGINES = {"openwakeword", "whisper"}
VALID_CHATTERBOX_DEVICES = {"cpu", "mps"}
VALID_QUEUE_INTRO_MODES = {"auto", "split", "combined"}
VALID_CHATTERBOX_STYLES = {
    "auto",
    "neutral",
    "angry",
    "fear",
    "surprised",
    "whispering",
    "advertisement",
    "dramatic",
    "narration",
    "crying",
    "happy",
    "sarcastic",
    "clear throat",
    "sigh",
    "shush",
    "cough",
    "groan",
    "sniff",
    "gasp",
    "chuckle",
    "laugh",
}


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
    if config.get("verbosity") not in VALID_VERBOSITIES:
        config["verbosity"] = DEFAULTS["verbosity"]
    if config.get("summary_backend") not in VALID_SUMMARY_BACKENDS:
        config["summary_backend"] = DEFAULTS["summary_backend"]
    if config.get("conductor_backend") not in VALID_CONDUCTOR_BACKENDS:
        config["conductor_backend"] = DEFAULTS["conductor_backend"]
    if config.get("wake_engine") not in VALID_WAKE_ENGINES:
        config["wake_engine"] = DEFAULTS["wake_engine"]
    if config.get("chatterbox_device") not in VALID_CHATTERBOX_DEVICES:
        config["chatterbox_device"] = DEFAULTS["chatterbox_device"]
    if config.get("chatterbox_style") not in VALID_CHATTERBOX_STYLES:
        config["chatterbox_style"] = DEFAULTS["chatterbox_style"]
    if config.get("queue_intro_mode") not in VALID_QUEUE_INTRO_MODES:
        config["queue_intro_mode"] = DEFAULTS["queue_intro_mode"]
    # Environment variable overrides for per-terminal voice assignment
    # Usage: export HANDSFREE_VOICE=af_bella
    env_voice = os.environ.get("HANDSFREE_VOICE")
    if env_voice:
        config["kokoro_voice"] = env_voice
    env_summary_backend = os.environ.get("HANDSFREE_SUMMARY_BACKEND")
    if env_summary_backend in VALID_SUMMARY_BACKENDS:
        config["summary_backend"] = env_summary_backend
    env_conductor_backend = os.environ.get("HANDSFREE_CONDUCTOR_BACKEND")
    if env_conductor_backend in VALID_CONDUCTOR_BACKENDS:
        config["conductor_backend"] = env_conductor_backend
    env_conductor_model = os.environ.get("HANDSFREE_CONDUCTOR_MODEL")
    if env_conductor_model:
        config["conductor_model"] = env_conductor_model
    return config


def is_handsfree_enabled() -> bool:
    """Check if speech mode is active.

    The shared ``~/.handsfree/speech-enabled`` flag is the canonical state.
    The legacy Claude-scoped flag remains readable so existing launcher
    sessions continue to work during migration.
    """

    return HANDSFREE_TOGGLE.exists() or LEGACY_HANDSFREE_TOGGLE.exists()


def is_wake_enabled() -> bool:
    """Check if wake listening is enabled."""

    return WAKE_TOGGLE.exists()


def mark_consume_after(timestamp: float | None = None) -> float:
    """Record the queue-consumption watermark and return its timestamp."""

    value = time.time() if timestamp is None else float(timestamp)
    CONSUME_AFTER.parent.mkdir(parents=True, exist_ok=True)
    CONSUME_AFTER.write_text(f"{value:.6f}\n")
    os.utime(CONSUME_AFTER, (value, value))
    return value


def queue_consume_after_timestamp() -> float | None:
    """Return the newest known time after which queued events are consumable."""

    candidates: list[float] = []

    for path in (CONSUME_AFTER, WAKE_TOGGLE, HANDSFREE_TOGGLE, LEGACY_HANDSFREE_TOGGLE):
        if not path.exists():
            continue
        try:
            if path == CONSUME_AFTER:
                raw = path.read_text().strip()
                if raw:
                    candidates.append(float(raw))
                    continue
            candidates.append(path.stat().st_mtime)
        except (OSError, ValueError):
            continue

    return max(candidates) if candidates else None


if __name__ == "__main__":
    print(f"Handsfree enabled: {is_handsfree_enabled()}")
    print(f"Queue consume after: {queue_consume_after_timestamp()}")
    print(f"Config: {json.dumps(get_config(), indent=2)}")
