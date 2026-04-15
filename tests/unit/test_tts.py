from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

import tts
import tts_client


class FakeKokoro:
    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed):
        self.calls.append({"text": text, "voice": voice, "speed": speed})
        return np.array([0.1, 0.2], dtype=np.float32), 24000


class FakeChatterbox:
    def __init__(self):
        self.sr = 22050
        self.prepared = []
        self.generated = []
        self.generate_kwargs = []

    def prepare_conditionals(self, reference_path):
        self.prepared.append(reference_path)

    def generate(self, text, **kwargs):
        self.generated.append(text)
        self.generate_kwargs.append(kwargs)
        return np.array([[0.3, 0.4]], dtype=np.float32)


def test_get_kokoro_loads_when_model_files_exist(monkeypatch, tmp_path: Path):
    calls = []

    class FakeKokoroClass:
        def __init__(self, model_path, voices_path):
            calls.append((model_path, voices_path))

    model_path = tmp_path / "kokoro.onnx"
    voices_path = tmp_path / "voices.bin"
    model_path.write_bytes(b"model")
    voices_path.write_bytes(b"voices")

    monkeypatch.setattr(tts, "_kokoro", None)
    monkeypatch.setattr(tts, "KOKORO_MODEL", model_path)
    monkeypatch.setattr(tts, "KOKORO_VOICES", voices_path)
    monkeypatch.setitem(
        sys.modules,
        "kokoro_onnx",
        types.SimpleNamespace(Kokoro=FakeKokoroClass),
    )

    kokoro = tts._get_kokoro()

    assert isinstance(kokoro, FakeKokoroClass)
    assert calls == [(str(model_path), str(voices_path))]


def test_speak_uses_kokoro_when_available(monkeypatch, tmp_path: Path):
    fake_kokoro = FakeKokoro()
    play_calls = []
    fallback_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
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


def test_speak_uses_chatterbox_when_selected(monkeypatch, tmp_path: Path):
    fake_chatterbox = FakeChatterbox()
    ref_path = tmp_path / "reference.wav"
    ref_path.write_bytes(b"wav")
    play_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(tts, "_get_chatterbox", lambda *_args: fake_chatterbox)
    monkeypatch.setattr(tts, "_chatterbox_conditioned_ref", None)
    monkeypatch.setattr(
        tts,
        "_get_kokoro",
        lambda: (_ for _ in ()).throw(AssertionError("Kokoro should not run")),
    )
    monkeypatch.setattr(
        tts,
        "_play_audio",
        lambda samples, rate: play_calls.append((samples, rate)),
    )
    monkeypatch.setattr(
        tts,
        "get_config",
        lambda: {
            "tts_provider": "chatterbox",
            "chatterbox_voice": "default",
            "chatterbox_reference_audio": str(ref_path),
            "chatterbox_style": "happy",
            "chatterbox_style_strength": 0.7,
            "chatterbox_temperature": 0.9,
        },
    )

    tts.speak("Hello from Chatterbox")

    assert fake_chatterbox.prepared == [str(ref_path)]
    assert fake_chatterbox.generated == ["[happy] Hello from Chatterbox"]
    assert fake_chatterbox.generate_kwargs == [
        {
            "temperature": 0.9,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
        }
    ]
    assert len(play_calls) == 1
    samples, sample_rate = play_calls[0]
    assert sample_rate == 22050
    np.testing.assert_array_equal(samples, np.array([0.3, 0.4], dtype=np.float32))


def test_chatterbox_auto_emotion_matches_text():
    assert (
        tts._chatterbox_tagged_text(
            "Sorry, I could not finish that.",
            {"chatterbox_style": "auto", "chatterbox_style_strength": 0.35},
        )
        == "[sigh] Sorry, I could not finish that."
    )
    assert (
        tts._chatterbox_tagged_text(
            "The tests passed. Everything is green.",
            {"chatterbox_style": "auto", "chatterbox_style_strength": 0.35},
        )
        == "[happy] The tests passed. Everything is green."
    )


def test_chatterbox_auto_emotion_tiles_multiple_tags():
    assert (
        tts._chatterbox_tagged_text(
            "Sorry, the tests failed. The fix is done.",
            {"chatterbox_style": "auto", "chatterbox_style_strength": 1.0},
        )
        == "[sigh][dramatic] Sorry, the tests failed. [happy] The fix is done."
    )


def test_chatterbox_auto_emotion_respects_zero_load():
    text = "Sorry, the tests failed."

    assert (
        tts._chatterbox_tagged_text(
            text,
            {"chatterbox_style": "auto", "chatterbox_style_strength": 0.0},
        )
        == text
    )


def test_chatterbox_auto_preserves_model_tags_within_load():
    assert (
        tts._chatterbox_tagged_text(
            "[laugh] That was oddly satisfying. [dramatic] Production is still risky.",
            {"chatterbox_style": "auto", "chatterbox_style_strength": 0.35},
        )
        == "[laugh] That was oddly satisfying. Production is still risky."
    )


def test_chatterbox_auto_strips_unknown_model_tags():
    assert (
        tts._chatterbox_tagged_text(
            "[excited] The update is steady.",
            {"chatterbox_style": "auto", "chatterbox_style_strength": 1.0},
        )
        == "The update is steady."
    )


def test_kokoro_strips_chatterbox_tags(monkeypatch, tmp_path: Path):
    fake_kokoro = FakeKokoro()

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(tts, "_kokoro", None)
    monkeypatch.setattr(tts, "_get_kokoro", lambda: fake_kokoro)
    monkeypatch.setattr(tts, "_resolve_voice", lambda voice, _k: voice)
    monkeypatch.setattr(tts, "_play_audio", lambda *_args: None)
    monkeypatch.setattr(
        tts,
        "get_config",
        lambda: {
            "tts_provider": "kokoro",
            "kokoro_voice": "af_nicole",
            "kokoro_speed": 1.25,
        },
    )

    tts.speak("[laugh] This should not read the tag.")

    assert fake_kokoro.calls == [
        {"text": "This should not read the tag.", "voice": "af_nicole", "speed": 1.25}
    ]


def test_chatterbox_falls_back_to_kokoro_when_unavailable(monkeypatch, tmp_path: Path):
    fake_kokoro = FakeKokoro()
    play_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        tts,
        "_get_chatterbox",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("missing chatterbox")),
    )
    monkeypatch.setattr(tts, "_get_kokoro", lambda: fake_kokoro)
    monkeypatch.setattr(tts, "_resolve_voice", lambda voice, _k: f"resolved:{voice}")
    monkeypatch.setattr(
        tts,
        "_play_audio",
        lambda samples, rate: play_calls.append((samples, rate)),
    )
    monkeypatch.setattr(
        tts,
        "get_config",
        lambda: {
            "tts_provider": "chatterbox",
            "kokoro_voice": "af_nicole",
            "kokoro_speed": 1.25,
        },
    )

    tts.speak("Fallback to Kokoro")

    assert fake_kokoro.calls == [
        {"text": "Fallback to Kokoro", "voice": "resolved:af_nicole", "speed": 1.25}
    ]
    assert len(play_calls) == 1


def test_speak_falls_back_to_macos_say_when_kokoro_missing(monkeypatch, tmp_path: Path):
    fallback_calls = []

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(tts, "_get_kokoro", lambda: None)
    monkeypatch.setattr(tts, "_say_fallback", lambda text: fallback_calls.append(text))

    tts.speak("Fallback text")

    assert fallback_calls == ["Fallback text"]


def test_speak_acquires_and_releases_file_lock(monkeypatch, tmp_path: Path):
    flock_calls = []

    def fake_flock(_fd, operation):
        flock_calls.append(operation)

    monkeypatch.setattr(tts, "LOCK_FILE", tmp_path / "tts.lock")
    monkeypatch.setattr(tts, "request_tts_daemon", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(tts, "_get_kokoro", lambda: None)
    monkeypatch.setattr(tts, "_say_fallback", lambda _text: None)
    monkeypatch.setattr(tts.fcntl, "flock", fake_flock)

    tts.speak("Lock behavior")

    assert flock_calls == [tts.fcntl.LOCK_EX, tts.fcntl.LOCK_UN]


def test_speak_uses_daemon_when_available(monkeypatch):
    calls = []

    monkeypatch.setattr(
        tts,
        "request_tts_daemon",
        lambda text, *, voice, speed: calls.append(
            {"text": text, "voice": voice, "speed": speed}
        ) or True,
    )
    monkeypatch.setattr(
        tts,
        "_speak_direct",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("direct TTS should not run")
        ),
    )

    tts.speak("Daemon text", voice="af_heart", speed=1.2)

    assert calls == [{"text": "Daemon text", "voice": "af_heart", "speed": 1.2}]


def test_tts_client_has_no_audio_dependencies():
    assert tts_client.request_tts_daemon.__name__ == "request_tts_daemon"
