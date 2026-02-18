from __future__ import annotations

import importlib
import sys
import types

import numpy as np


class FakeWhisper:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def transcribe(self, audio, path_or_hf_repo, language):
        self.calls.append(
            {
                "audio": audio,
                "path_or_hf_repo": path_or_hf_repo,
                "language": language,
            }
        )
        return {"text": self.text}


def _load_stt(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.rec = lambda *args, **kwargs: np.zeros((1, 1), dtype=np.float32)
    fake_sd.wait = lambda: None
    fake_sd.InputStream = object
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    sys.modules.pop("stt", None)
    return importlib.import_module("stt")


def test_transcribe_passes_numpy_audio_to_whisper(monkeypatch):
    stt = _load_stt(monkeypatch)
    audio = np.array([0.1, -0.1, 0.05], dtype=np.float32)
    fake_whisper = FakeWhisper("  transcribed text  ")
    monkeypatch.setattr(stt, "_get_whisper", lambda: fake_whisper)

    result = stt.transcribe(audio)

    assert result == "transcribed text"
    assert len(fake_whisper.calls) == 1
    assert fake_whisper.calls[0]["audio"] is audio
    assert fake_whisper.calls[0]["path_or_hf_repo"] == stt.MODEL_ID
    assert fake_whisper.calls[0]["language"] == "en"


def test_transcribe_handles_empty_audio(monkeypatch):
    stt = _load_stt(monkeypatch)
    empty_audio = np.array([], dtype=np.float32)
    fake_whisper = FakeWhisper("   ")
    monkeypatch.setattr(stt, "_get_whisper", lambda: fake_whisper)

    result = stt.transcribe(empty_audio)

    assert result == ""
    assert len(fake_whisper.calls) == 1
    assert fake_whisper.calls[0]["audio"].size == 0
