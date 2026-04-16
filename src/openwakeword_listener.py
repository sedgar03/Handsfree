#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openwakeword",
#   "mlx-whisper",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""OpenWakeWord first-stage listener with Whisper command capture."""

from __future__ import annotations

import sys
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Allow imports from src/ when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import WAKE_TOGGLE, get_config, is_wake_enabled, queue_consume_after_timestamp
from event_queue import pending_count
from wake_phrase_listener import SAMPLE_RATE, CHUNK_DURATION, CALIBRATION_DURATION, PRE_ROLL_SECONDS
from wake_phrase_listener import _normalize, is_bare_queue_command, looks_like_hallucination

_NOOP_COMMANDS = {
    "clear throat",
    "cough",
    "gasp",
    "groan",
    "i",
    "i am going to go",
    "i'm sorry",
    "i'm going to go",
    "i'm gonna go",
    "im sorry",
    "im going to go",
    "im gonna go",
    "laugh",
    "sorry",
    "sigh",
    "sniff",
    "so",
    "thank you",
    "thanks",
    "ok",
    "okay",
    "enjoy",
    "you",
}


@dataclass(slots=True, frozen=True)
class WakeDetection:
    model: str
    score: float
    scores: dict[str, float]


def score_triggered(scores: dict[str, float], threshold: float) -> WakeDetection | None:
    """Return the highest wake score above threshold."""

    if not scores:
        return None
    model, score = max(scores.items(), key=lambda item: item[1])
    if float(score) >= threshold:
        return WakeDetection(model=model, score=float(score), scores=scores)
    return None


def _float_audio_from_int16(audio: np.ndarray) -> np.ndarray:
    return audio.astype(np.float32) / 32768.0


def strip_wake_phrase(text: str, wake_models: Sequence[str]) -> tuple[bool, str]:
    """Strip the wake phrase when Whisper captures it as part of the command."""

    normalized = _normalize(text)
    phrases = sorted(
        {
            _normalize(model.replace("_", " "))
            for model in wake_models
            if _normalize(model.replace("_", " "))
        },
        key=len,
        reverse=True,
    )
    for phrase in phrases:
        if normalized == phrase:
            return True, ""
        prefix = f"{phrase} "
        if normalized.startswith(prefix):
            return True, normalized[len(prefix) :].strip()
    return False, text.strip()


class OpenWakeWordListener:
    """Continuously listen for a small wake model, then transcribe one command."""

    def __init__(
        self,
        *,
        wake_models: Sequence[str],
        on_command: Callable[[str], bool],
        on_submit: Callable[[], None] | None = None,
        auto_submit: bool = True,
        threshold: float = 0.5,
        inference_framework: str = "onnx",
        vad_threshold: float = 0.0,
        frame_ms: int = 80,
        cooldown: float = 1.5,
        post_speech_cooldown: float = 4.0,
        false_wake_limit: int = 3,
        false_wake_window: float = 45.0,
        false_wake_disarm: bool = True,
        auto_read_queue: bool = True,
        allow_freeform_commands: bool = False,
        command_timeout: float = 6.0,
        speech_threshold: float = 0.008,
        silence_threshold: float = 0.004,
        silence_timeout: float = 1.2,
        min_utterance: float = 0.4,
        require_toggle: bool = True,
    ):
        self.wake_models = tuple(wake_models) or ("hey jarvis",)
        self.on_command = on_command
        self.on_submit = on_submit
        self.auto_submit = auto_submit
        self.threshold = threshold
        self.inference_framework = inference_framework
        self.vad_threshold = vad_threshold
        self.frame_ms = frame_ms
        self.cooldown = cooldown
        self.post_speech_cooldown = max(0.0, post_speech_cooldown)
        self.false_wake_limit = max(0, false_wake_limit)
        self.false_wake_window = max(1.0, false_wake_window)
        self.false_wake_disarm = false_wake_disarm
        self.auto_read_queue = auto_read_queue
        self.allow_freeform_commands = allow_freeform_commands
        self.command_timeout = command_timeout
        self.speech_threshold = speech_threshold
        self.silence_threshold = silence_threshold
        self.silence_timeout = silence_timeout
        self.min_utterance = min_utterance
        self.require_toggle = require_toggle
        self._model = None
        self._armed_notice_printed = False
        self._waiting_notice_printed = False
        self._last_detection_at = 0.0
        self._suppress_until = 0.0
        self._false_wake_times: deque[float] = deque()

    def _enabled(self) -> bool:
        return not self.require_toggle or is_wake_enabled()

    def _conductor_mode_enabled(self) -> bool:
        try:
            return get_config().get("interaction_mode") == "conductor"
        except Exception:
            return False

    def _auto_queue_read_enabled(self) -> bool:
        if not self.auto_read_queue:
            return False
        try:
            config = get_config()
        except Exception:
            return True
        if config.get("interaction_mode") != "conductor":
            return True
        return bool(config.get("conductor_auto_read_queue", False))

    def _looks_like_noop_command(self, text: str) -> bool:
        normalized = _normalize(text)
        if normalized in _NOOP_COMMANDS:
            return True
        return normalized in {f"{phrase}." for phrase in _NOOP_COMMANDS}

    def _wake_suppressed(self) -> bool:
        return time.monotonic() < self._suppress_until

    def _suppress_wake_for(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._suppress_until = max(self._suppress_until, time.monotonic() + seconds)

    def _record_successful_wake(self) -> None:
        self._false_wake_times.clear()

    def _record_false_wake(self, reason: str) -> bool:
        if self.false_wake_limit <= 0:
            return False

        now = time.monotonic()
        self._false_wake_times.append(now)
        while self._false_wake_times and now - self._false_wake_times[0] > self.false_wake_window:
            self._false_wake_times.popleft()

        count = len(self._false_wake_times)
        if count < self.false_wake_limit:
            print(
                f"[oww] Possible false wake ({reason}); {count}/{self.false_wake_limit}.",
                file=sys.stderr,
            )
            return False

        self._false_wake_times.clear()
        if self.false_wake_disarm and self.require_toggle:
            print(
                f"[oww] Loop guard disarming wake after repeated false wakes ({reason}).",
                file=sys.stderr,
            )
            WAKE_TOGGLE.unlink(missing_ok=True)
            self._armed_notice_printed = False
            self._waiting_notice_printed = False
        else:
            backoff = max(self.post_speech_cooldown, self.cooldown * self.false_wake_limit)
            self._suppress_wake_for(backoff)
            print(
                f"[oww] Loop guard suppressing wake for {backoff:.1f}s after repeated false wakes ({reason}).",
                file=sys.stderr,
            )
        return True

    def _load_model(self):
        if self._model is not None:
            return self._model
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models()
        self._model = Model(
            wakeword_models=list(self.wake_models),
            inference_framework=self.inference_framework,
            vad_threshold=self.vad_threshold,
        )
        return self._model

    def warm(self) -> dict[str, object]:
        """Load the wake model before the listener is marked ready."""

        started = time.time()
        model = self._load_model()
        return {
            "ok": True,
            "wake_engine": "openwakeword",
            "models": list(model.models.keys()),
            "load_seconds": round(time.time() - started, 3),
        }

    def run(self) -> None:
        print("[oww] OpenWakeWord listener ready.", file=sys.stderr)
        print(f"[oww] Models: {', '.join(self.wake_models)}", file=sys.stderr)
        print(f"[oww] Threshold: {self.threshold:.2f}", file=sys.stderr)
        if self.require_toggle:
            print("[oww] Arm/disarm with the HUD wake button.", file=sys.stderr)

        self.warm()
        while True:
            if not self._enabled():
                if not self._waiting_notice_printed:
                    print("[oww] Waiting; wake toggle is off.", file=sys.stderr)
                    self._waiting_notice_printed = True
                    self._armed_notice_printed = False
                time.sleep(0.5)
                continue

            if not self._armed_notice_printed:
                print("[oww] Armed. Say the wake word.", file=sys.stderr)
                self._armed_notice_printed = True
                self._waiting_notice_printed = False

            detection = self._wait_for_wake()
            if detection is None:
                continue
            self._handle_detection(detection)

    def _wait_for_wake(self) -> WakeDetection | None:
        import sounddevice as sd

        model = self._load_model()
        chunks: list[np.ndarray] = []
        read_index = 0
        frame_samples = int(SAMPLE_RATE * (self.frame_ms / 1000.0))

        def callback(indata, frames, time_info, status):
            chunks.append(indata.copy().flatten())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
            callback=callback,
        )
        stream.start()
        try:
            while self._enabled():
                time.sleep(self.frame_ms / 1000.0)
                if self._wake_suppressed():
                    continue
                if read_index >= len(chunks):
                    continue
                new_chunks = chunks[read_index:]
                read_index = len(chunks)
                for chunk in new_chunks:
                    scores = {
                        key: float(value)
                        for key, value in model.predict(chunk).items()
                    }
                    detection = score_triggered(scores, self.threshold)
                    if detection is None:
                        continue
                    now = time.monotonic()
                    if now - self._last_detection_at < self.cooldown:
                        continue
                    self._last_detection_at = now
                    return detection
            return None
        finally:
            stream.stop()
            stream.close()

    def _has_current_queue(self) -> bool:
        try:
            return pending_count(created_after=queue_consume_after_timestamp()) > 0
        except Exception as exc:  # noqa: BLE001
            print(f"[oww] Queue check failed: {exc}", file=sys.stderr)
            return False

    def _read_queue(self, *, speak_empty: bool = True) -> None:
        try:
            from queue_actions import read_next_event

            read_next_event(speak_empty=speak_empty)
            self._suppress_wake_for(self.post_speech_cooldown)
        except Exception as exc:  # noqa: BLE001
            print(f"[oww] Queue read failed: {exc}", file=sys.stderr)

    def _handle_detection(self, detection: WakeDetection) -> None:
        print(
            f"[oww] Wake detected: {detection.model} ({detection.score:.2f})",
            file=sys.stderr,
        )
        if self._auto_queue_read_enabled() and self._has_current_queue():
            self._read_queue(speak_empty=False)
            self._record_successful_wake()
            return

        audio = self._capture_command()
        if audio is None:
            loop_guard_tripped = self._record_false_wake("no command heard")
            if self._auto_queue_read_enabled() and not loop_guard_tripped:
                self._read_queue(speak_empty=True)
            return
        if self._handle_command_audio(audio):
            self._record_successful_wake()
            self._suppress_wake_for(self.post_speech_cooldown)
        else:
            self._record_false_wake("ignored command")

    def _capture_command(self) -> np.ndarray | None:
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
            chunks.append(indata.copy().flatten())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=chunk_samples,
            callback=callback,
        )
        stream.start()
        try:
            while self._enabled():
                time.sleep(CHUNK_DURATION)
                if time.monotonic() - wait_start > self.command_timeout and not speech_started:
                    print("[oww] No command heard after wake.", file=sys.stderr)
                    return None
                if read_index >= len(chunks):
                    continue

                new_chunks = chunks[read_index:]
                read_index = len(chunks)
                for chunk in new_chunks:
                    float_chunk = _float_audio_from_int16(chunk)
                    rms = float(np.sqrt(np.mean(float_chunk**2)))
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
                        pre_roll.append(float_chunk)
                        continue

                    if not speech_started:
                        pre_roll.append(float_chunk)
                        if rms > effective_speech_threshold:
                            speech_started = True
                            speech_start_at = time.monotonic()
                            silence_start_at = None
                            utterance_chunks = list(pre_roll)
                            print("[oww] Command speech detected.", file=sys.stderr)
                        continue

                    utterance_chunks.append(float_chunk)
                    now = time.monotonic()
                    if speech_start_at is not None and now - speech_start_at > self.command_timeout:
                        print("[oww] Command timeout reached.", file=sys.stderr)
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

    def _handle_command_audio(self, audio: np.ndarray) -> bool:
        duration = len(audio) / SAMPLE_RATE
        if duration < self.min_utterance:
            print("[oww] Ignoring short command.", file=sys.stderr)
            return False

        print(f"[oww] Captured command {duration:.1f}s, transcribing...", file=sys.stderr)
        try:
            from stt import transcribe

            text = transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            print(f"[oww] Transcription error: {exc}", file=sys.stderr)
            return False

        if not text:
            print("[oww] Empty command transcription.", file=sys.stderr)
            return False

        had_wake_phrase, command_text = strip_wake_phrase(text, self.wake_models)
        if had_wake_phrase:
            if not command_text:
                if self._auto_queue_read_enabled():
                    print("[oww] Heard wake phrase only; reading queue.", file=sys.stderr)
                    self._read_queue(speak_empty=True)
                    return True
                print("[oww] Heard wake phrase only; ignoring.", file=sys.stderr)
                return False
            print(f"[oww] Stripped wake phrase from command: {command_text}", file=sys.stderr)
            text = command_text

        if looks_like_hallucination(text, duration):
            print(f"[oww] Ignored likely hallucination: {text}", file=sys.stderr)
            return False
        if self._looks_like_noop_command(text):
            print(f"[oww] Ignored no-op command: {text}", file=sys.stderr)
            return False

        print(f"[oww] Command transcript: {text}", file=sys.stderr)

        if is_bare_queue_command(text):
            print(f"[oww] Queue command: {text}", file=sys.stderr)
            self._read_queue(speak_empty=True)
            return True

        if not self.allow_freeform_commands and not self._conductor_mode_enabled():
            print(f"[oww] Ignored non-queue command after wake: {text}", file=sys.stderr)
            return False

        handled = self.on_command(text)
        if not handled and self.auto_submit and self.on_submit is not None:
            self.on_submit()
            return True
        return handled


if __name__ == "__main__":
    def _print_command(command: str) -> bool:
        print(f">>> {command}")
        return True

    OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=_print_command,
        auto_submit=False,
    ).run()
