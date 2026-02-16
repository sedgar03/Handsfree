#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper", "sounddevice", "numpy"]
# ///
"""Auto-listen — triggered on idle_prompt, records with VAD, transcribes, pastes.

Flow:
  1. Play a chime so the user knows we're listening
  2. Record from mic with energy-based voice activity detection
  3. Wait for speech to start (energy above threshold)
  4. Once speech detected, record until silence gap (energy below threshold)
  5. Transcribe via mlx-whisper
  6. Paste into active terminal via pbcopy + Cmd+V

The user sees the pasted text and presses Enter to send (safety measure).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stt import SAMPLE_RATE, transcribe

# --- Config ---
_SOUNDS_DIR = str(Path(__file__).resolve().parent.parent / "sounds")
CHIME_SOUND = f"{_SOUNDS_DIR}/snapchat-notification.mp3"
DONE_SOUND = f"{_SOUNDS_DIR}/snapchat-notification.mp3"

# VAD parameters
CHUNK_DURATION = 0.1  # seconds per chunk for energy calculation
SPEECH_THRESHOLD = 0.015  # RMS energy threshold to detect speech
SILENCE_THRESHOLD = 0.008  # RMS below this = silence
SILENCE_TIMEOUT = 1.5  # seconds of silence after speech to stop
MAX_WAIT_FOR_SPEECH = 10.0  # max seconds to wait before anyone speaks
MAX_RECORDING = 30.0  # absolute max recording time
MIN_SPEECH_DURATION = 0.3  # ignore very short bursts (clicks, etc.)


def play_sound(path: str, duration: float | None = None):
    """Play a sound file via afplay. Optionally limit to duration seconds."""
    cmd = ["afplay", path]
    if duration:
        cmd += ["-t", str(duration)]
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=duration + 1 if duration else 5,
    )


def record_with_vad(
    sample_rate: int = SAMPLE_RATE,
    speech_threshold: float = SPEECH_THRESHOLD,
    silence_threshold: float = SILENCE_THRESHOLD,
    silence_timeout: float = SILENCE_TIMEOUT,
    max_wait: float = MAX_WAIT_FOR_SPEECH,
    max_duration: float = MAX_RECORDING,
) -> np.ndarray | None:
    """Record audio with voice activity detection.

    Waits for speech to start, then records until a silence gap.
    Returns the audio as a numpy array, or None if no speech detected.
    """
    chunk_samples = int(CHUNK_DURATION * sample_rate)
    chunks: list[np.ndarray] = []
    speech_started = False
    silence_start: float | None = None
    recording_start = time.monotonic()
    wait_start = time.monotonic()

    def callback(indata, frames, time_info, status):
        chunks.append(indata.copy())

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=chunk_samples,
        callback=callback,
    )

    with stream:
        while True:
            time.sleep(CHUNK_DURATION)
            elapsed = time.monotonic() - recording_start

            # Absolute timeout
            if elapsed > max_duration:
                print("[auto-listen] Max recording time reached.", file=sys.stderr)
                break

            # Calculate current energy from recent chunks
            if not chunks:
                continue

            recent = chunks[-1].flatten()
            rms = float(np.sqrt(np.mean(recent**2)))

            if not speech_started:
                # Waiting for speech
                if rms > speech_threshold:
                    speech_started = True
                    silence_start = None
                    print("[auto-listen] Speech detected.", file=sys.stderr)
                elif time.monotonic() - wait_start > max_wait:
                    print("[auto-listen] No speech detected, giving up.", file=sys.stderr)
                    return None
            else:
                # Speech in progress — watch for silence
                if rms < silence_threshold:
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start > silence_timeout:
                        print("[auto-listen] Silence detected, stopping.", file=sys.stderr)
                        break
                else:
                    silence_start = None

    if not chunks:
        return None

    audio = np.concatenate(chunks).flatten()

    # Check minimum duration of actual speech
    if not speech_started or len(audio) / sample_rate < MIN_SPEECH_DURATION:
        return None

    return audio


def inject_text(text: str):
    """Paste text into the active terminal via clipboard + Cmd+V."""
    subprocess.run(["pbcopy"], input=text.encode(), check=True)
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ],
        check=False,
    )
    print(f"[auto-listen] Injected: {text}", file=sys.stderr)


def main():
    # Play chime to indicate listening (short burst)
    play_sound(CHIME_SOUND, duration=1.0)
    print("[auto-listen] Listening... (speak now)", file=sys.stderr)

    # Record with VAD
    audio = record_with_vad()

    if audio is None:
        print("[auto-listen] No speech captured.", file=sys.stderr)
        return

    duration = len(audio) / SAMPLE_RATE
    print(f"[auto-listen] Captured {duration:.1f}s of audio, transcribing...", file=sys.stderr)

    # Transcribe
    text = transcribe(audio)

    if not text or not text.strip():
        print("[auto-listen] Empty transcription.", file=sys.stderr)
        return

    # Play done sound (short burst)
    play_sound(DONE_SOUND, duration=1.0)

    # Paste into terminal
    inject_text(text.strip())


if __name__ == "__main__":
    main()
