from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest


def _load_media_key_module(monkeypatch):
    """Load media_key_listener with lightweight stubs for macOS-only deps."""
    fake_objc = types.ModuleType("objc")
    fake_objc.ivar = lambda *args, **kwargs: None

    def typed_selector(_signature):
        def decorator(func):
            return func

        return decorator

    fake_objc.typedSelector = typed_selector
    fake_objc.loadBundle = lambda *args, **kwargs: None
    fake_objc.lookUpClass = lambda _name: type("DummyClass", (), {})
    monkeypatch.setitem(sys.modules, "objc", fake_objc)

    fake_foundation = types.ModuleType("Foundation")
    fake_foundation.NSObject = object
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)

    class DummyStream:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = DummyStream
    fake_sd.OutputStream = DummyStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    module_path = Path(__file__).resolve().parents[2] / "src" / "media_key_listener.py"
    spec = importlib.util.spec_from_file_location("media_key_listener_vad_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_vad_sequence(
    media_key_module,
    monkeypatch,
    rms_values: list[float],
    silence_timeout: float = 0.2,
    max_wait_for_speech: float | None = None,
):
    listener = media_key_module.MediaKeyListener(silence_timeout=silence_timeout, max_recording=10.0)
    listener._set_state("recording")
    listener._chunks = []

    finalized = {"count": 0}
    cancelled = {"count": 0}

    def fake_finalize_recording():
        finalized["count"] += 1
        listener._stop_event.set()

    def fake_cancel_recording(clear_pending_question: bool = False):
        _ = clear_pending_question
        cancelled["count"] += 1
        listener._stop_event.set()

    monkeypatch.setattr(listener, "_finalize_recording", fake_finalize_recording)
    monkeypatch.setattr(listener, "_cancel_recording", fake_cancel_recording)

    if max_wait_for_speech is not None:
        monkeypatch.setattr(media_key_module, "MAX_WAIT_FOR_SPEECH", max_wait_for_speech)

    fake_time = {"value": 0.0}

    def fake_monotonic():
        fake_time["value"] += 0.12
        return fake_time["value"]

    idx = {"value": 0}

    def fake_sleep(_seconds):
        if idx["value"] < len(rms_values):
            amp = rms_values[idx["value"]]
            listener._chunks.append(np.full((64, 1), amp, dtype=np.float32))
            idx["value"] += 1
        else:
            listener._stop_event.set()

    monkeypatch.setattr(media_key_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(media_key_module.time, "sleep", fake_sleep)

    listener._vad_monitor()
    return finalized["count"], cancelled["count"]


def test_vad_detects_speech_and_auto_stops_on_silence(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=[0.0026, 0.0024, 0.0010, 0.0010, 0.0010],
        silence_timeout=0.2,
    )

    assert finalized == 1
    assert cancelled == 0


def test_vad_cancels_if_speech_never_starts(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=[0.0010, 0.0011, 0.0012, 0.0010, 0.0011],
        max_wait_for_speech=0.25,
    )

    assert finalized == 0
    assert cancelled == 1


@pytest.mark.parametrize(
    "rms_values, expected_finalize, expected_cancel",
    [
        ([0.0019, 0.0018, 0.0019, 0.0018], 0, 1),
        ([0.0021, 0.0020, 0.0010, 0.0010, 0.0010], 1, 0),
    ],
)
def test_vad_threshold_behavior_includes_airpods_level_signals(
    monkeypatch,
    rms_values,
    expected_finalize,
    expected_cancel,
):
    media_key_module = _load_media_key_module(monkeypatch)

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=rms_values,
        max_wait_for_speech=0.35,
        silence_timeout=0.2,
    )

    assert finalized == expected_finalize
    assert cancelled == expected_cancel
