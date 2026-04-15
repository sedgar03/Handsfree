from __future__ import annotations

import audio_output


def test_notification_sound_path_uses_theme_notify_file(monkeypatch, tmp_path):
    theme_path = tmp_path / "theme"
    sound_root = tmp_path / "sounds"
    zelda_notify = sound_root / "zelda" / "notify.mp3"
    zelda_notify.parent.mkdir(parents=True)
    zelda_notify.write_text("sound")
    theme_path.write_text("zelda\n")

    monkeypatch.setattr(audio_output, "SOUND_THEME_PATH", theme_path)
    monkeypatch.setattr(audio_output, "SOUND_THEME_ROOT", sound_root)
    monkeypatch.setattr(audio_output, "DEFAULT_NOTIFICATION_SOUND", tmp_path / "legacy.mp3")

    assert audio_output.notification_sound_path() == zelda_notify


def test_notification_sound_path_falls_back_to_legacy(monkeypatch, tmp_path):
    legacy = tmp_path / "notification.mp3"
    legacy.write_text("sound")

    monkeypatch.setattr(audio_output, "SOUND_THEME_PATH", tmp_path / "missing-theme")
    monkeypatch.setattr(audio_output, "SOUND_THEME_ROOT", tmp_path / "missing-sounds")
    monkeypatch.setattr(audio_output, "DEFAULT_NOTIFICATION_SOUND", legacy)

    assert audio_output.notification_sound_path() == legacy
