from __future__ import annotations

import json
from pathlib import Path

import config


def test_get_config_defaults_when_file_missing(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("HANDSFREE_VOICE", raising=False)

    cfg = config.get_config()

    assert cfg["input_mode"] == "media_key"
    assert cfg["verbosity"] == "detailed"
    assert cfg["hotkey"] == "F18"
    assert cfg["auto_submit"] is True


def test_get_config_merges_custom_values_and_validates_input_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_mode": "hotkey",
                "hotkey": "F19",
                "verbosity": "terse",
                "kokoro_speed": 1.3,
            }
        )
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("HANDSFREE_VOICE", raising=False)

    cfg = config.get_config()

    assert cfg["input_mode"] == "hotkey"
    assert cfg["hotkey"] == "F19"
    assert cfg["verbosity"] == "terse"
    assert cfg["kokoro_speed"] == 1.3

    config_path.write_text(json.dumps({"input_mode": "not-real"}))
    cfg_invalid = config.get_config()
    assert cfg_invalid["input_mode"] == config.DEFAULTS["input_mode"]


def test_get_config_respects_env_voice_override(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "voice-config.json"
    config_path.write_text(json.dumps({"kokoro_voice": "af_heart"}))
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HANDSFREE_VOICE", "af_bella")

    cfg = config.get_config()

    assert cfg["kokoro_voice"] == "af_bella"


def test_is_handsfree_enabled_reads_toggle_file(monkeypatch, tmp_path: Path):
    toggle = tmp_path / "handsfree"
    monkeypatch.setattr(config, "HANDSFREE_TOGGLE", toggle)

    assert config.is_handsfree_enabled() is False

    toggle.write_text("")
    assert config.is_handsfree_enabled() is True
