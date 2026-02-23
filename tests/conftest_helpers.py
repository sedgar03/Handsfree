"""Shared test helpers for loading macOS-only modules with stubs."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def load_media_key_module(monkeypatch, module_alias: str = "media_key_listener_test"):
    """Load media_key_listener with lightweight stubs for macOS-only deps.

    Shared across test_vad.py and test_media_key_controls.py to avoid
    duplicating ~40 lines of PyObjC/sounddevice stub setup.
    """
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

    module_path = Path(__file__).resolve().parents[1] / "src" / "media_key_listener.py"
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
