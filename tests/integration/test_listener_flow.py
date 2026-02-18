from __future__ import annotations

import importlib
import sys
import types

import numpy as np


def _load_hotkey_listener(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")

    class DummyInputStream:
        def __init__(self, *args, callback=None, **kwargs):
            self.callback = callback
            self.started = False
            self.stopped = False
            self.closed = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def close(self):
            self.closed = True

    fake_sd.InputStream = DummyInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    sys.modules.pop("hotkey_listener", None)
    return importlib.import_module("hotkey_listener")


def _load_listener(monkeypatch):
    fake_media_key_module = types.ModuleType("media_key_listener")

    class DummyMediaKeyListener:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def run(self):
            return None

    fake_media_key_module.MediaKeyListener = DummyMediaKeyListener
    monkeypatch.setitem(sys.modules, "media_key_listener", fake_media_key_module)

    sys.modules.pop("listener", None)
    return importlib.import_module("listener")


def test_record_transcribe_inject_flow_with_mocked_audio(monkeypatch):
    hotkey_listener = _load_hotkey_listener(monkeypatch)
    listener_module = _load_listener(monkeypatch)

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    subprocess_calls = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append({"cmd": cmd, "kwargs": kwargs})
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    transcribe_inputs = []

    def fake_transcribe(audio):
        transcribe_inputs.append(audio)
        return "draft response"

    monkeypatch.setattr(hotkey_listener.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(hotkey_listener, "transcribe", fake_transcribe)

    monkeypatch.setattr(listener_module, "_try_answer_permission", lambda _text: False)
    monkeypatch.setattr(listener_module, "_try_answer_question", lambda _text: False)
    monkeypatch.setattr(listener_module.subprocess, "run", fake_run)

    hk = hotkey_listener.HotkeyListener(on_transcription=listener_module.inject_text)
    hk._start_recording()

    assert hk._stream.__class__.__name__ == "DummyInputStream"
    hk._stream.callback(np.array([[0.05], [0.1]], dtype=np.float32), 2, None, None)

    hk._stop_recording()

    assert len(transcribe_inputs) == 1
    assert transcribe_inputs[0].ndim == 1

    pbcopy_calls = [call for call in subprocess_calls if call["cmd"][0] == "pbcopy"]
    osascript_calls = [call for call in subprocess_calls if call["cmd"][0] == "osascript"]

    assert len(pbcopy_calls) == 1
    assert pbcopy_calls[0]["kwargs"]["input"] == b"draft response"
    assert len(osascript_calls) == 1
