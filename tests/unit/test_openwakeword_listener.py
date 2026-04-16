from __future__ import annotations

from pathlib import Path

import numpy as np

import openwakeword_listener


def test_score_triggered_returns_highest_score_above_threshold():
    detection = openwakeword_listener.score_triggered(
        {"hey jarvis": 0.71, "alexa": 0.2},
        0.5,
    )

    assert detection is not None
    assert detection.model == "hey jarvis"
    assert detection.score == 0.71


def test_score_triggered_ignores_scores_below_threshold():
    assert openwakeword_listener.score_triggered({"hey jarvis": 0.49}, 0.5) is None


def test_float_audio_from_int16_normalizes_samples():
    audio = np.array([-32768, 0, 32767], dtype=np.int16)

    normalized = openwakeword_listener._float_audio_from_int16(audio)

    assert normalized.dtype == np.float32
    assert normalized[0] == -1.0
    assert normalized[1] == 0.0
    assert 0.99 < normalized[2] < 1.0


def test_strip_wake_phrase_consumes_wake_only_transcription():
    matched, command = openwakeword_listener.strip_wake_phrase(
        "Hey, Jarvis.",
        ("hey jarvis",),
    )

    assert matched is True
    assert command == ""


def test_strip_wake_phrase_keeps_followup_command():
    matched, command = openwakeword_listener.strip_wake_phrase(
        "Hey Jarvis, what's up?",
        ("hey_jarvis",),
    )

    assert matched is True
    assert command == "whats up"


def test_detection_reads_queue_without_command_when_current_queue_exists(monkeypatch):
    calls = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "direct"})
    monkeypatch.setattr(listener, "_has_current_queue", lambda: True)
    monkeypatch.setattr(listener, "_read_queue", lambda speak_empty=True: calls.append(speak_empty))
    monkeypatch.setattr(
        listener,
        "_capture_command",
        lambda: (_ for _ in ()).throw(AssertionError("should not capture command")),
    )

    listener._handle_detection(
        openwakeword_listener.WakeDetection(
            model="hey jarvis",
            score=0.8,
            scores={"hey jarvis": 0.8},
        )
    )

    assert calls == [False]


def test_conductor_mode_does_not_auto_read_queue_on_wake(monkeypatch):
    calls = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(listener, "_has_current_queue", lambda: True)
    monkeypatch.setattr(listener, "_read_queue", lambda speak_empty=True: calls.append(speak_empty))
    monkeypatch.setattr(listener, "_capture_command", lambda: None)

    listener._handle_detection(
        openwakeword_listener.WakeDetection(
            model="hey jarvis",
            score=0.8,
            scores={"hey jarvis": 0.8},
        )
    )

    assert calls == []


def test_detection_captures_freeform_command_when_enabled(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
        allow_freeform_commands=True,
    )
    monkeypatch.setattr(listener, "_has_current_queue", lambda: False)
    monkeypatch.setattr(listener, "_capture_command", lambda: np.zeros(16000, dtype=np.float32))
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)
    monkeypatch.setattr(openwakeword_listener, "is_bare_queue_command", lambda _text: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "run the tests"

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    listener._handle_detection(
        openwakeword_listener.WakeDetection(
            model="hey jarvis",
            score=0.8,
            scores={"hey jarvis": 0.8},
        )
    )

    assert commands == ["run the tests"]


def test_handled_command_suppresses_wake_after_tts(monkeypatch):
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: True,
        post_speech_cooldown=4.0,
    )
    monkeypatch.setattr(listener, "_has_current_queue", lambda: False)
    monkeypatch.setattr(listener, "_capture_command", lambda: np.zeros(16000, dtype=np.float32))
    monkeypatch.setattr(listener, "_handle_command_audio", lambda _audio: True)
    monkeypatch.setattr(openwakeword_listener.time, "monotonic", lambda: 100.0)

    listener._handle_detection(
        openwakeword_listener.WakeDetection(
            model="hey jarvis",
            score=0.8,
            scores={"hey jarvis": 0.8},
        )
    )

    assert listener._wake_suppressed() is True


def test_detection_ignores_freeform_command_by_default(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "on_demand"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)
    monkeypatch.setattr(openwakeword_listener, "is_bare_queue_command", lambda _text: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "run the tests"

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    listener._handle_command_audio(np.zeros(16000, dtype=np.float32))

    assert commands == []


def test_detection_routes_freeform_command_in_conductor_mode(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)
    monkeypatch.setattr(openwakeword_listener, "is_bare_queue_command", lambda _text: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "what tmux panes are open"

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is True
    assert commands == ["what tmux panes are open"]


def test_wake_only_command_reads_queue_instead_of_injecting(monkeypatch):
    commands = []
    reads = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "direct"})
    monkeypatch.setattr(listener, "_read_queue", lambda speak_empty=True: reads.append(speak_empty))
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "Hey, Jarvis."

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    listener._handle_command_audio(np.zeros(16000, dtype=np.float32))

    assert commands == []
    assert reads == [True]


def test_wake_only_command_is_ignored_in_conductor_mode(monkeypatch):
    reads = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(listener, "_read_queue", lambda speak_empty=True: reads.append(speak_empty))
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "Hey, Jarvis."

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is False
    assert reads == []


def test_noop_command_is_ignored_after_false_wake(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "Thank you."

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is False
    assert commands == []


def test_short_command_fragment_is_ignored_after_false_wake(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "so"

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is False
    assert commands == []


def test_goodbye_hallucination_is_ignored_after_false_wake(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "I'm going to go."

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is False
    assert commands == []


def test_vocalization_noop_is_ignored_after_false_wake(monkeypatch):
    commands = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda command: commands.append(command) or True,
    )
    monkeypatch.setattr(openwakeword_listener, "get_config", lambda: {"interaction_mode": "conductor"})
    monkeypatch.setattr(openwakeword_listener, "looks_like_hallucination", lambda _text, _duration: False)

    class FakeStt:
        @staticmethod
        def transcribe(_audio):
            return "Cough."

    import sys

    monkeypatch.setitem(sys.modules, "stt", FakeStt)

    assert listener._handle_command_audio(np.zeros(16000, dtype=np.float32)) is False
    assert commands == []


def test_queue_read_suppresses_wake_after_tts(monkeypatch):
    calls = []
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
        post_speech_cooldown=4.0,
    )

    class FakeQueueActions:
        @staticmethod
        def read_next_event(*, speak_empty: bool = False):
            calls.append(speak_empty)

    import sys

    monkeypatch.setitem(sys.modules, "queue_actions", FakeQueueActions)
    monkeypatch.setattr(openwakeword_listener.time, "monotonic", lambda: 100.0)

    listener._read_queue(speak_empty=True)

    assert calls == [True]
    assert listener._wake_suppressed() is True


def test_false_wake_loop_guard_disarms_wake_toggle(monkeypatch, tmp_path: Path):
    wake_toggle = tmp_path / "wake-enabled"
    wake_toggle.write_text("")
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
        false_wake_limit=2,
        false_wake_window=30.0,
        false_wake_disarm=True,
        require_toggle=True,
    )
    timestamps = iter([100.0, 101.0])

    monkeypatch.setattr(openwakeword_listener, "WAKE_TOGGLE", wake_toggle)
    monkeypatch.setattr(openwakeword_listener.time, "monotonic", lambda: next(timestamps))

    assert listener._record_false_wake("no command heard") is False
    assert wake_toggle.exists()
    assert listener._record_false_wake("no command heard") is True
    assert not wake_toggle.exists()


def test_false_wake_counter_resets_after_success():
    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
        false_wake_limit=2,
    )

    assert listener._record_false_wake("ignored command") is False
    listener._record_successful_wake()

    assert listener._record_false_wake("ignored command") is False


def test_warm_reports_loaded_wake_models(monkeypatch):
    class FakeModel:
        models = {"hey jarvis": object()}

    listener = openwakeword_listener.OpenWakeWordListener(
        wake_models=("hey jarvis",),
        on_command=lambda _command: False,
    )
    monkeypatch.setattr(listener, "_load_model", lambda: FakeModel())

    status = listener.warm()

    assert status["ok"] is True
    assert status["wake_engine"] == "openwakeword"
    assert status["models"] == ["hey jarvis"]
