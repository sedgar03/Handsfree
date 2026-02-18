from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _load_media_key_module(monkeypatch):
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
    spec = importlib.util.spec_from_file_location("media_key_listener_controls_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def test_single_click_from_idle_starts_recording(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)
    listener = media_key_module.MediaKeyListener()

    starts = {"count": 0}

    def fake_start_recording():
        starts["count"] += 1

    monkeypatch.setattr(media_key_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(listener, "_start_recording", fake_start_recording)

    listener._on_remote_command("toggle")

    assert starts["count"] == 1
    assert listener._event_counter == 1
    assert listener._last_remote_event_at > 0


def test_single_click_while_recording_stops_recording(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)
    listener = media_key_module.MediaKeyListener()
    listener._set_state("recording")

    stops = {"count": 0}

    def fake_stop_recording_manual():
        stops["count"] += 1

    monkeypatch.setattr(media_key_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(listener, "_stop_recording_manual", fake_stop_recording_manual)

    listener._on_remote_command("play")

    assert stops["count"] == 1
    assert listener._event_counter == 1


def test_double_click_window_maps_to_next_and_stops(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)
    listener = media_key_module.MediaKeyListener()
    listener._set_state("recording")

    stops = {"count": 0}

    def fake_stop_recording_manual():
        stops["count"] += 1

    monkeypatch.setattr(media_key_module.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(listener, "_stop_recording_manual", fake_stop_recording_manual)

    listener._on_remote_command("toggle")
    listener._on_remote_command("pause")

    # First event maps to PLAY during recording; second event maps to NEXT.
    assert stops["count"] == 2
    assert listener._event_counter == 2


def test_play_during_transcribing_keeps_auto_submit_behavior(monkeypatch):
    media_key_module = _load_media_key_module(monkeypatch)
    listener = media_key_module.MediaKeyListener(auto_submit=True)
    listener._set_state("transcribing")
    listener._pending_submit_after_transcription = False

    handled = listener._handle_media_key(
        media_key_module.NX_KEYTYPE_PLAY,
        media_key_module.MEDIA_KEY_DOWN,
        "test",
    )

    assert handled is True
    assert listener._pending_submit_after_transcription is True
