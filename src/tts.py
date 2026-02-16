#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile", "numpy"]
# ///
"""Kokoro TTS wrapper — synthesize speech and play through speakers.

Falls back to macOS `say` if Kokoro model files are missing.
Uses a file lock to serialize concurrent invocations.
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
from pathlib import Path

import numpy as np

# Allow imports from src/ when run from anywhere
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from config import get_config

MODELS_DIR = _repo_root / "models"
KOKORO_MODEL = MODELS_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES = MODELS_DIR / "voices-v1.0.bin"
LOCK_FILE = Path("/tmp/handsfree-tts.lock")

# Lazy-initialized Kokoro instance
_kokoro = None


def _get_kokoro():
    """Lazy-init Kokoro. Returns the Kokoro instance or None if models missing."""
    global _kokoro
    if _kokoro is not None:
        return _kokoro

    if not KOKORO_MODEL.exists() or not KOKORO_VOICES.exists():
        return None

    try:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        return _kokoro
    except Exception as e:
        print(f"[handsfree] Kokoro init failed: {e}", file=sys.stderr)
        return None


def _resolve_voice(voice_spec: str, kokoro):
    """Resolve a voice spec to a string name or blended numpy array.

    Supports:
      - Plain name:      "af_heart"
      - Preset name:     "audiobook_narrator"  (looked up in config voice_presets)
      - Blend spec:      "af_heart:0.7,af_nicole:0.3"
    """
    # Check if it's a preset name
    if ":" not in voice_spec and "," not in voice_spec:
        presets = get_config().get("voice_presets", {})
        voice_spec = presets.get(voice_spec, voice_spec)

    if ":" not in voice_spec:
        return voice_spec

    parts = [p.strip() for p in voice_spec.split(",")]
    styles = []
    for part in parts:
        name, _, weight = part.partition(":")
        name = name.strip()
        weight = float(weight.strip()) if weight.strip() else 1.0
        styles.append((kokoro.get_voice_style(name), weight))

    # Normalize weights so they sum to 1.0
    total = sum(w for _, w in styles)
    blend = sum(style * (w / total) for style, w in styles)
    return blend


def _play_audio(samples, sample_rate: int):
    """Play audio samples through the default output device."""
    import sounddevice as sd
    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def _say_fallback(text: str):
    """macOS say command as TTS fallback."""
    subprocess.run(["say", text], check=False)


def speak(text: str, voice: str | None = None, speed: float = 1.1):
    """Synthesize and speak text. Uses Kokoro if available, else macOS say."""
    if not text or not text.strip():
        return

    config = get_config()
    if voice is None:
        voice = config.get("kokoro_voice", "af_heart")
    if speed == 1.1:  # default — allow config override
        speed = config.get("kokoro_speed", 1.1)

    # Acquire file lock to serialize concurrent TTS calls
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        kokoro = _get_kokoro()
        if kokoro is None:
            _say_fallback(text)
            return

        voice = _resolve_voice(voice, kokoro)
        samples, sample_rate = kokoro.create(text, voice=voice, speed=speed)
        _play_audio(samples, sample_rate)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hello from Handsfree"
    speak(text)
