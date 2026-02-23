from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from conftest_helpers import load_media_key_module


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
    media_key_module = load_media_key_module(monkeypatch)

    # First ~5 chunks are calibration (0.5s / 0.12s per tick ≈ 4-5 ticks).
    # Use low RMS for calibration, then speech above 3x noise floor, then silence.
    # Noise floor ≈ 0.001, so speech threshold ≈ max(0.001*3, 0.002) = 0.003,
    # silence threshold ≈ max(0.001*2, 0.0015) = 0.002.
    rms_values = [
        # Calibration phase (~0.5s worth)
        0.001, 0.001, 0.001, 0.001, 0.001,
        # Speech (above 3x noise floor = 0.003)
        0.010, 0.008, 0.012,
        # Silence (below 2x noise floor = 0.002)
        0.0005, 0.0005, 0.0005,
    ]

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=rms_values,
        silence_timeout=0.2,
    )

    assert finalized == 1
    assert cancelled == 0


def test_vad_cancels_if_speech_never_starts(monkeypatch):
    media_key_module = load_media_key_module(monkeypatch)

    # All values at noise floor level — speech never starts.
    # After calibration, speech threshold ≈ max(0.001*3, 0.002) = 0.003.
    # All subsequent values stay below that.
    rms_values = [
        # Calibration phase
        0.001, 0.001, 0.001, 0.001, 0.001,
        # No speech — stays below speech threshold
        0.0010, 0.0011, 0.0012, 0.0010, 0.0011,
        0.0010, 0.0011, 0.0012, 0.0010, 0.0011,
    ]

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=rms_values,
        max_wait_for_speech=0.8,
    )

    assert finalized == 0
    assert cancelled == 1


@pytest.mark.parametrize(
    "rms_values, expected_finalize, expected_cancel",
    [
        # Below speech threshold after calibration — never starts speaking → cancel
        (
            [0.001, 0.001, 0.001, 0.001, 0.001,   # calibration
             0.0019, 0.0018, 0.0019, 0.0018,        # below 3x noise = 0.003
             0.0019, 0.0018, 0.0019, 0.0018],
            0, 1,
        ),
        # Above speech threshold then drops to silence → finalize
        (
            [0.001, 0.001, 0.001, 0.001, 0.001,   # calibration
             0.010, 0.008,                          # speech (above 0.003)
             0.0005, 0.0005, 0.0005],               # silence (below 0.002)
            1, 0,
        ),
    ],
)
def test_vad_threshold_behavior_includes_airpods_level_signals(
    monkeypatch,
    rms_values,
    expected_finalize,
    expected_cancel,
):
    media_key_module = load_media_key_module(monkeypatch)

    finalized, cancelled = _run_vad_sequence(
        media_key_module,
        monkeypatch,
        rms_values=rms_values,
        max_wait_for_speech=1.0,
        silence_timeout=0.2,
    )

    assert finalized == expected_finalize
    assert cancelled == expected_cancel
