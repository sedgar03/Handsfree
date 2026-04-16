from __future__ import annotations

import service_control


def test_summary_status_marks_ready_model_mismatch_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {
            "summary_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "summary_model_backend": "mlx",
        },
    )

    status = service_control._annotate_summary_status(
        {
            "ok": True,
            "state": "ready",
            "backend": "llama.cpp",
            "model": "models/supergemma4-26b-uncensored-gguf-v2",
        }
    )

    assert status["desired_backend"] == "mlx"
    assert status["desired_model"] == "mlx-community/Qwen3.5-2B-OptiQ-4bit"
    assert status["stale"] is True


def test_conductor_status_marks_ready_model_mismatch_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {
            "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "conductor_backend": "mlx",
        },
    )
    monkeypatch.setattr(
        service_control,
        "read_service_status",
        lambda _name: {"state": "ready"},
    )

    status = service_control._annotate_conductor_status(
        {
            "ok": True,
            "state": "ready",
            "pid": 123,
            "backend": "llama.cpp",
            "model": "models/supergemma4-26b-uncensored-gguf-v2",
        }
    )

    assert status["desired_backend"] == "mlx"
    assert status["desired_model"] == "mlx-community/Qwen3.5-2B-OptiQ-4bit"
    assert status["stale"] is True


def test_conductor_status_reports_matching_service_error(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {
            "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "conductor_backend": "mlx",
        },
    )
    monkeypatch.setattr(
        service_control,
        "read_service_status",
        lambda _name: {
            "state": "error",
            "pid": 123,
            "error": "llama.cpp chat failed",
        },
    )

    status = service_control._annotate_conductor_status(
        {
            "ok": True,
            "state": "ready",
            "pid": 123,
            "backend": "mlx",
            "model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
        }
    )

    assert status["ok"] is False
    assert status["state"] == "error"
    assert status["error"] == "llama.cpp chat failed"
    assert status["stale"] is False


def test_tts_status_marks_previous_provider_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {"tts_provider": "kokoro"},
    )

    status = service_control._annotate_tts_status(
        {"ok": True, "state": "ready", "engine": "chatterbox"}
    )

    assert status["desired_engine"] == "kokoro"
    assert status["stale"] is True
    assert status["fallback"] is False


def test_summary_status_marks_prompt_provider_mismatch_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {
            "summary_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "summary_model_backend": "mlx",
            "tts_provider": "kokoro",
        },
    )

    status = service_control._annotate_summary_status(
        {
            "ok": True,
            "state": "ready",
            "backend": "mlx",
            "model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "prompt_tts_provider": "chatterbox",
        }
    )

    assert status["desired_prompt_tts_provider"] == "kokoro"
    assert status["stale"] is True


def test_tts_status_marks_configured_fallback_without_restart(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {"tts_provider": "kokoro"},
    )

    status = service_control._annotate_tts_status(
        {
            "ok": True,
            "state": "ready",
            "engine": "say",
            "requested_engine": "kokoro",
            "fallback_reason": "Kokoro model files are missing",
        }
    )

    assert status["desired_engine"] == "kokoro"
    assert status["stale"] is False
    assert status["fallback"] is True


def test_tts_daemon_script_is_provider_specific(monkeypatch) -> None:
    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {"tts_provider": "kokoro"},
    )
    assert service_control._tts_daemon_script().name == "tts_daemon.py"

    monkeypatch.setattr(
        service_control,
        "get_config",
        lambda: {"tts_provider": "chatterbox"},
    )
    assert service_control._tts_daemon_script().name == "tts_chatterbox_daemon.py"


def test_disable_wake_stops_warm_stack_when_speech_is_off(monkeypatch, tmp_path) -> None:
    stopped = []
    wake_toggle = tmp_path / "wake-enabled"
    wake_toggle.write_text("")

    monkeypatch.setattr(service_control, "WAKE_TOGGLE", wake_toggle)
    monkeypatch.setattr(service_control, "LISTENER_PID", tmp_path / "listener.pid")
    monkeypatch.setattr(service_control, "SUMMARY_PID", tmp_path / "summary.pid")
    monkeypatch.setattr(service_control, "TTS_PID", tmp_path / "tts.pid")
    monkeypatch.setattr(service_control, "CONDUCTOR_PID", tmp_path / "conductor.pid")
    monkeypatch.setattr(service_control, "is_handsfree_enabled", lambda: False)
    monkeypatch.setattr(service_control, "is_wake_enabled", lambda: False)
    monkeypatch.setattr(
        service_control,
        "stop_pid",
        lambda path, *, name, timeout=5.0: stopped.append(name) or True,
    )
    monkeypatch.setattr(service_control, "write_service_status", lambda *_args, **_kwargs: None)

    payload = service_control.disable_wake()

    assert payload["enabled"] is False
    assert payload["summary_stopped"] is True
    assert payload["tts_stopped"] is True
    assert payload["conductor_stopped"] is True
    assert stopped == ["listener", "summary", "tts", "conductor"]


def test_disable_speech_keeps_stack_warm_when_wake_is_on(monkeypatch, tmp_path) -> None:
    stopped = []
    speech_toggle = tmp_path / "speech-enabled"
    legacy_toggle = tmp_path / "legacy-speech"
    speech_toggle.write_text("")
    legacy_toggle.write_text("")

    monkeypatch.setattr(service_control, "HANDSFREE_TOGGLE", speech_toggle)
    monkeypatch.setattr(service_control, "LEGACY_HANDSFREE_TOGGLE", legacy_toggle)
    monkeypatch.setattr(service_control, "is_handsfree_enabled", lambda: False)
    monkeypatch.setattr(service_control, "is_wake_enabled", lambda: True)
    monkeypatch.setattr(
        service_control,
        "stop_pid",
        lambda path, *, name, timeout=5.0: stopped.append(name) or True,
    )

    payload = service_control.disable_speech()

    assert payload["enabled"] is False
    assert payload["kept_reader_warm"] is True
    assert payload["summary_stopped"] is False
    assert payload["tts_stopped"] is False
    assert payload["conductor_stopped"] is False
    assert stopped == []
    assert not speech_toggle.exists()
    assert not legacy_toggle.exists()
