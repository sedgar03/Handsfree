from __future__ import annotations

import json
import os
from pathlib import Path

import config


def test_get_config_defaults_when_file_missing(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("HANDSFREE_VOICE", raising=False)
    monkeypatch.delenv("HANDSFREE_SUMMARY_BACKEND", raising=False)
    monkeypatch.delenv("HANDSFREE_CONDUCTOR_BACKEND", raising=False)
    monkeypatch.delenv("HANDSFREE_CONDUCTOR_MODEL", raising=False)

    cfg = config.get_config()

    assert cfg["input_mode"] == "media_key"
    assert cfg["verbosity"] == "detailed"
    assert cfg["summary_backend"] == "mlx"
    assert cfg["summary_model"] == "mlx-community/Qwen3.5-2B-OptiQ-4bit"
    assert cfg["conductor_backend"] == "auto"
    assert cfg["conductor_model"] == "mlx-community/Qwen3.5-2B-OptiQ-4bit"
    assert cfg["conductor_temperature"] == 0.3
    assert cfg["conductor_max_tokens"] == 180
    assert cfg["conductor_history_turns"] == 8
    assert cfg["conductor_llama_server_bin"] == "llama-server"
    assert cfg["conductor_llama_port"] == 8091
    assert cfg["interaction_mode"] == "off"
    assert cfg["last_interaction_mode"] == "direct"
    assert cfg["tts_provider"] == "kokoro"
    assert cfg["chatterbox_voice"] == "default"
    assert cfg["chatterbox_device"] == "cpu"
    assert cfg["chatterbox_style"] == "auto"
    assert cfg["chatterbox_style_strength"] == 0.35
    assert cfg["chatterbox_temperature"] == 0.8
    assert cfg["queue_intro_mode"] == "auto"
    assert cfg["hotkey"] == "F18"
    assert cfg["auto_submit"] is True
    assert "handsfree" in cfg["wake_words"]
    assert cfg["wake_engine"] == "openwakeword"
    assert cfg["openwakeword_models"] == ["hey jarvis"]
    assert cfg["openwakeword_allow_freeform_commands"] is False
    assert cfg["wake_allow_queue_without_prefix"] is True


def test_get_config_merges_custom_values_and_validates_input_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_mode": "hotkey",
                "hotkey": "F19",
                "verbosity": "terse",
                "summary_backend": "claude",
                "kokoro_speed": 1.3,
            }
        )
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("HANDSFREE_VOICE", raising=False)
    monkeypatch.delenv("HANDSFREE_SUMMARY_BACKEND", raising=False)
    monkeypatch.delenv("HANDSFREE_CONDUCTOR_BACKEND", raising=False)
    monkeypatch.delenv("HANDSFREE_CONDUCTOR_MODEL", raising=False)

    cfg = config.get_config()

    assert cfg["input_mode"] == "hotkey"
    assert cfg["hotkey"] == "F19"
    assert cfg["verbosity"] == "terse"
    assert cfg["summary_backend"] == "claude"
    assert cfg["kokoro_speed"] == 1.3

    config_path.write_text(json.dumps({"input_mode": "wake_word"}))
    cfg_wake = config.get_config()
    assert cfg_wake["input_mode"] == "wake_word"

    config_path.write_text(json.dumps({"input_mode": "not-real"}))
    cfg_invalid = config.get_config()
    assert cfg_invalid["input_mode"] == config.DEFAULTS["input_mode"]

    config_path.write_text(json.dumps({"summary_backend": "not-real"}))
    cfg_invalid_backend = config.get_config()
    assert cfg_invalid_backend["summary_backend"] == config.DEFAULTS["summary_backend"]

    config_path.write_text(json.dumps({"verbosity": "tiny"}))
    cfg_tiny = config.get_config()
    assert cfg_tiny["verbosity"] == "tiny"

    config_path.write_text(json.dumps({"verbosity": "not-real"}))
    cfg_invalid_verbosity = config.get_config()
    assert cfg_invalid_verbosity["verbosity"] == config.DEFAULTS["verbosity"]

    config_path.write_text(json.dumps({"wake_engine": "whisper"}))
    cfg_wake_engine = config.get_config()
    assert cfg_wake_engine["wake_engine"] == "whisper"

    config_path.write_text(json.dumps({"wake_engine": "not-real"}))
    cfg_invalid_wake_engine = config.get_config()
    assert cfg_invalid_wake_engine["wake_engine"] == config.DEFAULTS["wake_engine"]


def test_get_config_respects_env_voice_override(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(json.dumps({"kokoro_voice": "af_heart"}))
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HANDSFREE_VOICE", "af_bella")

    cfg = config.get_config()

    assert cfg["kokoro_voice"] == "af_bella"


def test_get_config_respects_env_summary_backend_override(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(json.dumps({"summary_backend": "local"}))
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HANDSFREE_SUMMARY_BACKEND", "claude")

    cfg = config.get_config()

    assert cfg["summary_backend"] == "claude"


def test_get_config_respects_env_conductor_overrides(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(
        json.dumps(
            {
                "conductor_backend": "mlx",
                "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            }
        )
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HANDSFREE_CONDUCTOR_BACKEND", "llama.cpp")
    monkeypatch.setenv("HANDSFREE_CONDUCTOR_MODEL", "models/local/model.gguf")

    cfg = config.get_config()

    assert cfg["conductor_backend"] == "llama.cpp"
    assert cfg["conductor_model"] == "models/local/model.gguf"


def test_is_handsfree_enabled_reads_toggle_file(monkeypatch, tmp_path: Path):
    toggle = tmp_path / "handsfree"
    legacy = tmp_path / "legacy-handsfree"
    monkeypatch.setattr(config, "HANDSFREE_TOGGLE", toggle)
    monkeypatch.setattr(config, "LEGACY_HANDSFREE_TOGGLE", legacy)

    assert config.is_handsfree_enabled() is False

    toggle.write_text("")
    assert config.is_handsfree_enabled() is True


def test_is_handsfree_enabled_reads_legacy_toggle(monkeypatch, tmp_path: Path):
    toggle = tmp_path / "handsfree"
    legacy = tmp_path / "legacy-handsfree"
    monkeypatch.setattr(config, "HANDSFREE_TOGGLE", toggle)
    monkeypatch.setattr(config, "LEGACY_HANDSFREE_TOGGLE", legacy)

    legacy.write_text("")

    assert config.is_handsfree_enabled() is True


def test_is_wake_enabled_reads_shared_toggle(monkeypatch, tmp_path: Path):
    toggle = tmp_path / "wake-enabled"
    monkeypatch.setattr(config, "WAKE_TOGGLE", toggle)

    assert config.is_wake_enabled() is False

    toggle.write_text("")
    assert config.is_wake_enabled() is True


def test_queue_consume_after_timestamp_uses_latest_control_marker(monkeypatch, tmp_path: Path):
    speech = tmp_path / "speech-enabled"
    wake = tmp_path / "wake-enabled"
    marker = tmp_path / "consume-after"
    legacy = tmp_path / "legacy-handsfree"
    monkeypatch.setattr(config, "HANDSFREE_TOGGLE", speech)
    monkeypatch.setattr(config, "WAKE_TOGGLE", wake)
    monkeypatch.setattr(config, "CONSUME_AFTER", marker)
    monkeypatch.setattr(config, "LEGACY_HANDSFREE_TOGGLE", legacy)

    assert config.queue_consume_after_timestamp() is None

    speech.write_text("")
    os.utime(speech, (100.0, 100.0))
    wake.write_text("")
    os.utime(wake, (120.0, 120.0))

    assert config.queue_consume_after_timestamp() == 120.0

    marker.write_text("150.5\n")

    assert config.queue_consume_after_timestamp() == 150.5


def test_mark_consume_after_writes_watermark(monkeypatch, tmp_path: Path):
    marker = tmp_path / "consume-after"
    speech = tmp_path / "speech-enabled"
    wake = tmp_path / "wake-enabled"
    legacy = tmp_path / "legacy-handsfree"
    monkeypatch.setattr(config, "CONSUME_AFTER", marker)
    monkeypatch.setattr(config, "HANDSFREE_TOGGLE", speech)
    monkeypatch.setattr(config, "WAKE_TOGGLE", wake)
    monkeypatch.setattr(config, "LEGACY_HANDSFREE_TOGGLE", legacy)

    timestamp = config.mark_consume_after(123.25)

    assert timestamp == 123.25
    assert marker.exists()
    assert config.queue_consume_after_timestamp() == 123.25
