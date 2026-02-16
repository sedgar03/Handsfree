#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper", "sounddevice", "numpy"]
# ///
"""Whisper STT wrapper — record from mic and transcribe locally.

Uses mlx-whisper with whisper-large-v3-turbo for fast Apple Silicon transcription.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import sounddevice as sd

# Lazy-loaded whisper
_whisper = None

MODEL_ID = "mlx-community/whisper-large-v3-turbo"
SAMPLE_RATE = 16000  # Whisper expects 16kHz mono


def _get_whisper():
    """Lazy-init mlx_whisper."""
    global _whisper
    if _whisper is None:
        import mlx_whisper
        _whisper = mlx_whisper
    return _whisper


def record(duration: float = 5.0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Record audio from the default input device.

    Returns numpy array of float32 samples at the given sample rate.
    """
    print(f"Recording for {duration}s... (speak now)", file=sys.stderr)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    print("Recording complete.", file=sys.stderr)
    return audio.flatten()


def record_until_stop(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Record audio until stop() is called externally.

    Returns numpy array of float32 samples. Uses a streaming approach
    with a callback to accumulate audio chunks.
    """
    chunks = []

    def callback(indata, frames, time_info, status):
        chunks.append(indata.copy())

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        callback=callback,
    )
    return stream, chunks


def transcribe(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    """Transcribe audio using mlx-whisper.

    Args:
        audio: float32 numpy array of audio samples
        sample_rate: sample rate of the audio (default 16kHz)

    Returns:
        Transcribed text string.
    """
    whisper = _get_whisper()

    # Pass numpy array directly — avoids needing ffmpeg for file loading
    result = whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL_ID,
        language="en",
    )
    return result.get("text", "").strip()


def listen(duration: float = 5.0) -> str:
    """Record from mic and transcribe. Convenience function combining record + transcribe."""
    audio = record(duration=duration)
    return transcribe(audio)


if __name__ == "__main__":
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    text = listen(duration=duration)
    print(f"\nTranscription: {text}")
