from __future__ import annotations

import pytest

window = pytest.importorskip("model_usage_hud.app.window")


def test_compact_handsfree_error_uses_traceback_exception_line() -> None:
    message = "\n".join(
        [
            "Traceback (most recent call last):",
            '  File "broker.py", line 1, in <module>',
            "RuntimeError: tts daemon failed to start",
        ]
    )

    assert (
        window._compact_handsfree_error(message)
        == "RuntimeError: tts daemon failed to start"
    )


def test_compact_handsfree_error_uses_first_nonempty_non_traceback_line() -> None:
    assert window._compact_handsfree_error("\nplain failure\nmore detail") == "plain failure"


def test_compact_handsfree_error_handles_empty_messages() -> None:
    assert window._compact_handsfree_error(" \n") == "unknown error"


def test_append_hud_action_log_records_command_and_streams(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "hud-actions.log"
    monkeypatch.setattr(window, "HUD_ACTION_LOG_PATH", log_path)

    window._append_hud_action_log(
        action="enable-speech",
        command=["uv", "run", "python", "-m", "broker"],
        returncode=1,
        stdout="out",
        stderr="err",
    )

    contents = log_path.read_text()
    assert "action=enable-speech returncode=1" in contents
    assert "$ uv run python -m broker" in contents
    assert "--- stderr ---\nerr" in contents
    assert "--- stdout ---\nout" in contents


def test_forced_disable_speech_runs_even_when_toggle_is_absent() -> None:
    calls = []

    class FakeWindow:
        mode_button = object()

        def _is_speech_enabled(self) -> bool:
            return False

        def _start_handsfree_action(self, action, broker_args, **kwargs):
            calls.append((action, broker_args, kwargs))

    window.HudWindow._disable_speech_if_needed(FakeWindow(), force=True)

    assert calls[0][0] == "disable-speech"
    assert calls[0][1] == ["disable", "speech"]


def test_forced_disable_wake_runs_even_when_toggle_is_absent() -> None:
    calls = []

    class FakeWindow:
        wake_button = object()

        def _is_wake_enabled(self) -> bool:
            return False

        def _start_handsfree_action(self, action, broker_args, **kwargs):
            calls.append((action, broker_args, kwargs))

    window.HudWindow._disable_wake_if_needed(FakeWindow(), force=True)

    assert calls[0][0] == "disable-wake"
    assert calls[0][1] == ["disable", "wake"]


def test_global_mute_toggle_includes_gemini(tmp_path, monkeypatch) -> None:
    mute_paths = {
        "claude": tmp_path / "claude" / "mute",
        "codex": tmp_path / "codex" / "mute",
        "gemini": tmp_path / "gemini" / "mute",
    }
    marked = []
    monkeypatch.setattr(window, "MUTE_PATHS", mute_paths)
    monkeypatch.setattr(window, "_mark_consume_after", lambda: marked.append(True))

    class FakeWindow:
        def __init__(self) -> None:
            self.refreshed = 0
            self.errors: list[str] = []

        def _is_any_muted(self) -> bool:
            return window.HudWindow._is_any_muted(self)

        def _refresh_mute_icon(self) -> None:
            self.refreshed += 1

        def _show_error(self, message: str) -> None:
            self.errors.append(message)

    fake = FakeWindow()
    window.HudWindow._toggle_mute_all(fake)

    assert all(path.exists() for path in mute_paths.values())
    assert fake.errors == []

    window.HudWindow._toggle_mute_all(fake)

    assert all(not path.exists() for path in mute_paths.values())
    assert marked == [True]
    assert fake.refreshed == 2


def test_conductor_watcher_tmux_command_quotes_repo_root(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "hands free"
    monkeypatch.setattr(window, "HANDSFREE_REPO_ROOT", repo)

    command = window.HudWindow._conductor_watcher_tmux_command()

    assert command.startswith("cd ")
    assert command.split(" && ", 1)[0].endswith("/hands free'")
    assert "PYTHONPATH=src uv run python -m broker conductor pane" in command
    assert "--conversation-id voice" in command


def test_copy_conductor_watcher_command_sets_clipboard(monkeypatch) -> None:
    copied = []

    class FakeClipboard:
        def setText(self, text: str) -> None:
            copied.append(text)

    class FakeApplication:
        @staticmethod
        def instance():
            return FakeApplication()

        def clipboard(self):
            return FakeClipboard()

    class FakeWindow:
        messages: list[str]

        def __init__(self) -> None:
            self.messages = []

        def _show_error(self, message: str) -> None:
            self.messages.append(message)

        def _conductor_watcher_tmux_command(self) -> str:
            return "cd /repo && PYTHONPATH=src uv run python -m broker conductor pane --conversation-id voice"

    monkeypatch.setattr(window, "QApplication", FakeApplication)
    fake = FakeWindow()

    window.HudWindow._copy_conductor_watcher_command(fake)

    assert copied == [
        "cd /repo && PYTHONPATH=src uv run python -m broker conductor pane --conversation-id voice"
    ]
    assert fake.messages == ["Copied conductor watcher tmux command."]
