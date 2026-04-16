from __future__ import annotations

import importlib
import json
from pathlib import Path


install_gemini = importlib.import_module("install_gemini")


def _read_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def test_resolve_settings_path_precedence(monkeypatch, tmp_path: Path):
    explicit = tmp_path / "explicit.json"
    env_path = tmp_path / "env.json"
    candidate = tmp_path / "candidate.json"

    monkeypatch.setattr(install_gemini, "CANDIDATE_SETTINGS_PATHS", [candidate])

    assert install_gemini._resolve_settings_path(str(explicit)) == explicit

    monkeypatch.setenv("GEMINI_SETTINGS_PATH", str(env_path))
    assert install_gemini._resolve_settings_path() == env_path
    monkeypatch.delenv("GEMINI_SETTINGS_PATH", raising=False)

    candidate.write_text("{}\n")
    assert install_gemini._resolve_settings_path() == candidate

    candidate.unlink()
    assert install_gemini._resolve_settings_path() == candidate


def test_install_is_idempotent_and_preserves_existing_hooks(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "AfterAgent": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python /usr/local/bin/other_hook.py",
                                    "name": "other",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )

    install_gemini.install(settings_path, python_bin="/usr/bin/python3")
    install_gemini.install(settings_path, python_bin="/usr/bin/python3")

    settings = _read_json(settings_path)
    after_agent_hooks = settings["hooks"]["AfterAgent"]
    notification_hooks = settings["hooks"]["Notification"]

    after_cmds = [
        h["command"]
        for group in after_agent_hooks
        for h in group.get("hooks", [])
    ]
    notification_cmds = [
        h["command"]
        for group in notification_hooks
        for h in group.get("hooks", [])
    ]

    assert sum("other_hook.py" in command for command in after_cmds) == 1
    assert sum("gemini_notify.py" in command for command in after_cmds) == 1
    assert sum("gemini_notify.py" in command for command in notification_cmds) == 1
    assert all(command.startswith("/usr/bin/python3 ") for command in after_cmds if "gemini_notify.py" in command)


def test_install_updates_existing_handsfree_hook_command(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "AfterAgent": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/tmp/uv-env/bin/python /repo/hooks/gemini_notify.py",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )

    install_gemini.install(settings_path, python_bin="/opt/homebrew/bin/python3.11")

    settings = _read_json(settings_path)
    hooks = settings["hooks"]["AfterAgent"][0]["hooks"]
    assert len(hooks) == 1
    assert hooks[0]["command"].startswith("/opt/homebrew/bin/python3.11 ")
    assert hooks[0]["name"] == "handsfree-gemini-afteragent"


def test_uninstall_removes_only_handsfree_hooks(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "AfterAgent": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python /repo/hooks/gemini_notify.py",
                                },
                                {
                                    "type": "command",
                                    "command": "python /usr/local/bin/other_hook.py",
                                },
                            ]
                        }
                    ],
                    "Notification": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python /repo/hooks/gemini_notify.py",
                                }
                            ]
                        }
                    ],
                }
            }
        )
    )

    install_gemini.uninstall(settings_path)
    settings = _read_json(settings_path)

    after_cmds = [
        Path(h["command"].split()[-1]).name
        for group in settings["hooks"]["AfterAgent"]
        for h in group.get("hooks", [])
    ]
    assert after_cmds == ["other_hook.py"]
    assert settings["hooks"]["Notification"] == []


def test_load_settings_backs_up_malformed_json(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not-valid-json")

    loaded = install_gemini._load_settings(settings_path)

    assert loaded == {}
    assert settings_path.with_suffix(".json.bak").exists()
