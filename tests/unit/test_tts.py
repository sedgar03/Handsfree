from __future__ import annotations

from pathlib import Path

import numpy as np

import tts


class FakeKokoro:
    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed):
        self.calls.append({"text": text, "voice": voice, "speed": speed})
        return np.array([0.1, 0.2], dtype=np.float32), 24000


def test_speak_uses_kokoro_when_available(monkeypatch, tmp_path: Path):
    fake_kokoro = FakeKokoro()
    play_calls = []
    fallback_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "_kokoro", None)
    monkeypatch.setattr(tts, "_get_kokoro", lambda: fake_kokoro)
    monkeypatch.setattr(tts, "_resolve_voice", lambda voice, _k: f"resolved:{voice}")
    monkeypatch.setattr(tts, "_play_audio", lambda samples, rate: play_calls.append((samples, rate)))
    monkeypatch.setattr(tts, "_say_fallback", lambda text: fallback_calls.append(text))
    monkeypatch.setattr(
        tts,
        "get_config",
        lambda: {
            "kokoro_voice": "af_nicole",
            "kokoro_speed": 1.25,
        },
    )

    tts.speak("Hello from tests")

    assert fake_kokoro.calls == [
        {"text": "Hello from tests", "voice": "resolved:af_nicole", "speed": 1.25}
    ]
    assert len(play_calls) == 1
    assert fallback_calls == []


def test_speak_falls_back_to_macos_say_when_kokoro_missing(monkeypatch, tmp_path: Path):
    fallback_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "_get_kokoro", lambda: None)
    monkeypatch.setattr(tts, "_say_fallback", lambda text: fallback_calls.append(text))

    tts.speak("Fallback text")

    assert fallback_calls == ["Fallback text"]


def test_speak_acquires_and_releases_file_lock(monkeypatch, tmp_path: Path):
    flock_calls = []

    def fake_flock(_fd, operation):
        flock_calls.append(operation)

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "_get_kokoro", lambda: None)
    monkeypatch.setattr(tts, "_say_fallback", lambda _text: None)
    monkeypatch.setattr(tts.fcntl, "flock", fake_flock)

    tts.speak("Lock behavior")

    assert flock_calls == [tts.fcntl.LOCK_EX, tts.fcntl.LOCK_UN]
