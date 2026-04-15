#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mlx-whisper",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""Wake-phrase listener backed by local VAD + Whisper.

This is not a tiny keyword model. It is a pragmatic wake phrase mode: keep the
mic open while the shared wake toggle is enabled, capture one speech utterance,
transcribe it locally, and only act when the transcription starts with a
configured phrase like "handsfree" or "hey codex".
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Allow imports from src/ when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import get_config, is_wake_enabled

SAMPLE_RATE = 16000
CHUNK_DURATION = 0.1
CALIBRATION_DURATION = 0.5
PRE_ROLL_SECONDS = 0.4


@dataclass(slots=True, frozen=True)
class WakePhraseMatch:
    phrase: str
    command: str


def _normalize(text: str) -> str:
    text = text.lower().replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_wake_phrase(
    text: str,
    wake_words: Sequence[str],
) -> WakePhraseMatch | None:
    """Return the wake phrase and remaining command when text is addressed to us."""

    normalized = _normalize(text)
    if not normalized:
        return None

    phrases = sorted(
        {_normalize(word) for word in wake_words if _normalize(word)},
        key=len,
        reverse=True,
    )
    for phrase in phrases:
        if normalized == phrase:
            return WakePhraseMatch(phrase=phrase, command="")
        prefix = f"{phrase} "
        if normalized.startswith(prefix):
            return WakePhraseMatch(
                phrase=phrase,
                command=normalized[len(prefix) :].strip(),
            )
    return None


def _is_read_queue_command(command: str) -> bool:
    normalized = _normalize(command)
    return normalized in {
        "",
        "read",
        "read next",
        "read the next message",
        "read message",
        "next",
        "next message",
        "latest",
        "latest message",
        "last",
        "last message",
        "read latest",
        "read last",
        "whats next",
        "what is next",
        "whats up",
        "what is up",
        "what happened",
        "what did i miss",
        "queue",
        "read queue",
    }


def is_bare_queue_command(text: str) -> bool:
    """Return True for low-risk queue commands that can work without a prefix."""

    return _is_read_queue_command(text)


def looks_like_hallucination(text: str, duration: float) -> bool:
    """Filter common Whisper noise hallucinations before command handling."""

    normalized = _normalize(text)
    if not normalized:
        return True
    words = normalized.split()
    if not words:
        return True
    if len(words) > 24 and duration < 4.0:
        return True
    counts = Counter(words)
    most_common_count = counts.most_common(1)[0][1]
    if len(words) >= 8 and most_common_count / len(words) >= 0.55:
        return True
    if len(set(words)) <= 2 and len(words) >= 8:
        return True
    return False


class WakePhraseListener:
    """Continuously capture utterances while the shared wake toggle is enabled."""

    def __init__(
        self,
        *,
        wake_words: Sequence[str],
        on_command: Callable[[str], bool],
        on_submit: Callable[[], None] | None = None,
        auto_submit: bool = True,
        speech_threshold: float = 0.002,
        silence_threshold: float = 0.0015,
        silence_timeout: float = 1.2,
        max_utterance: float = 20.0,
        min_utterance: float = 0.4,
        require_toggle: bool = True,
        allow_queue_without_prefix: bool = True,
    ):
        self.wake_words = tuple(wake_words)
        self.on_command = on_command
        self.on_submit = on_submit
        self.auto_submit = auto_submit
        self.speech_threshold = speech_threshold
        self.silence_threshold = silence_threshold
        self.silence_timeout = silence_timeout
        self.max_utterance = max_utterance
        self.min_utterance = min_utterance
        self.require_toggle = require_toggle
        self.allow_queue_without_prefix = allow_queue_without_prefix
        self._armed_notice_printed = False
        self._waiting_notice_printed = False

    def _enabled(self) -> bool:
        return not self.require_toggle or is_wake_enabled()

    def run(self) -> None:
        print("[wake] Wake phrase listener ready.", file=sys.stderr)
        print(f"[wake] Phrases: {', '.join(self.wake_words)}", file=sys.stderr)
        if self.require_toggle:
            print("[wake] Arm/disarm with the HUD wake button.", file=sys.stderr)

        while True:
            if not self._enabled():
                if not self._waiting_notice_printed:
                    print("[wake] Waiting; wake toggle is off.", file=sys.stderr)
                    self._waiting_notice_printed = True
                    self._armed_notice_printed = False
                time.sleep(0.5)
                continue

            if not self._armed_notice_printed:
                print("[wake] Armed. Say a wake phrase, then the command.", file=sys.stderr)
                self._armed_notice_printed = True
                self._waiting_notice_printed = False

            audio = self._capture_utterance()
            if audio is None:
                continue
            self._handle_utterance(audio)

    def _capture_utterance(self):
        import numpy as np
        import sounddevice as sd

        chunks: list[np.ndarray] = []
        read_index = 0
        speech_started = False
        speech_start_at: float | None = None
        silence_start_at: float | None = None
        wait_start = time.monotonic()
        utterance_chunks: list[np.ndarray] = []
        pre_roll: deque[np.ndarray] = deque(
            maxlen=max(1, int(PRE_ROLL_SECONDS / CHUNK_DURATION))
        )
        calibration_samples: list[float] = []
        noise_floor: float | None = None
        effective_silence_threshold = self.silence_threshold
        effective_speech_threshold = self.speech_threshold
        chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)

        def callback(indata, frames, time_info, status):
            chunks.append(indata.copy())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=chunk_samples,
            callback=callback,
        )
        stream.start()
        try:
            while self._enabled():
                time.sleep(CHUNK_DURATION)
                if read_index >= len(chunks):
                    continue

                new_chunks = chunks[read_index:]
                read_index = len(chunks)
                for chunk in new_chunks:
                    flattened = chunk.flatten()
                    rms = float(np.sqrt(np.mean(flattened**2)))
                    elapsed_wait = time.monotonic() - wait_start

                    if noise_floor is None:
                        calibration_samples.append(rms)
                        if elapsed_wait >= CALIBRATION_DURATION and calibration_samples:
                            noise_floor = sum(calibration_samples) / len(calibration_samples)
                            effective_silence_threshold = max(
                                noise_floor * 2.0,
                                self.silence_threshold,
                            )
                            effective_speech_threshold = max(
                                noise_floor * 3.0,
                                self.speech_threshold,
                            )
                        pre_roll.append(chunk)
                        continue

                    if not speech_started:
                        pre_roll.append(chunk)
                        if rms > effective_speech_threshold:
                            speech_started = True
                            speech_start_at = time.monotonic()
                            silence_start_at = None
                            utterance_chunks = list(pre_roll)
                            print("[wake] Speech detected.", file=sys.stderr)
                        continue

                    utterance_chunks.append(chunk)
                    now = time.monotonic()
                    if speech_start_at is not None and now - speech_start_at > self.max_utterance:
                        print("[wake] Max utterance reached.", file=sys.stderr)
                        return np.concatenate(utterance_chunks).flatten()
                    if rms < effective_silence_threshold:
                        if silence_start_at is None:
                            silence_start_at = now
                        elif now - silence_start_at >= self.silence_timeout:
                            return np.concatenate(utterance_chunks).flatten()
                    else:
                        silence_start_at = None
            return None
        finally:
            stream.stop()
            stream.close()

    def _handle_utterance(self, audio) -> None:
        duration = len(audio) / SAMPLE_RATE
        if duration < self.min_utterance:
            print("[wake] Ignoring short utterance.", file=sys.stderr)
            return

        print(f"[wake] Captured {duration:.1f}s, transcribing...", file=sys.stderr)
        try:
            from stt import transcribe

            text = transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            print(f"[wake] Transcription error: {exc}", file=sys.stderr)
            return

        if not text:
            print("[wake] Empty transcription.", file=sys.stderr)
            return
        if looks_like_hallucination(text, duration):
            print(f"[wake] Ignored likely hallucination: {text}", file=sys.stderr)
            return

        if self.allow_queue_without_prefix and is_bare_queue_command(text):
            print(f"[wake] Bare queue command: {text}", file=sys.stderr)
            try:
                from queue_actions import read_next_event

                read_next_event(speak_empty=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[wake] Queue read failed: {exc}", file=sys.stderr)
            return

        match = parse_wake_phrase(text, self.wake_words)
        if match is None:
            print(f"[wake] Ignored: {text}", file=sys.stderr)
            return

        print(f"[wake] Matched '{match.phrase}': {match.command or '(read queue)'}", file=sys.stderr)
        if _is_read_queue_command(match.command):
            try:
                from queue_actions import read_next_event

                read_next_event(speak_empty=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[wake] Queue read failed: {exc}", file=sys.stderr)
            return

        handled = self.on_command(match.command)
        if not handled and self.auto_submit and self.on_submit is not None:
            self.on_submit()


def main() -> None:
    config = get_config()

    def _print_command(command: str) -> bool:
        print(f">>> {command}")
        return True

    listener = WakePhraseListener(
        wake_words=config.get("wake_words", []),
        on_command=_print_command,
        auto_submit=False,
        speech_threshold=config.get(
            "wake_speech_threshold",
            config.get("speech_threshold", 0.002),
        ),
        silence_threshold=config.get(
            "wake_silence_threshold",
            config.get("silence_threshold", 0.0015),
        ),
        silence_timeout=config.get("wake_silence_timeout", 1.2),
        max_utterance=config.get("wake_max_utterance", 20.0),
        min_utterance=config.get("wake_min_utterance", 0.4),
        allow_queue_without_prefix=config.get("wake_allow_queue_without_prefix", True),
    )
    listener.run()


if __name__ == "__main__":
    main()
