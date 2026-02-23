from __future__ import annotations

from conftest_helpers import load_media_key_module


class _ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


def test_single_click_from_idle_starts_recording(monkeypatch):
    media_key_module = load_media_key_module(monkeypatch, "media_key_listener_controls_test_1")

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
    media_key_module = load_media_key_module(monkeypatch, "media_key_listener_controls_test_2")
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
    media_key_module = load_media_key_module(monkeypatch, "media_key_listener_controls_test_3")
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
    media_key_module = load_media_key_module(monkeypatch, "media_key_listener_controls_test_4")
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
