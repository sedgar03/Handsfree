from __future__ import annotations

import json
from pathlib import Path

import install


def _read_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def test_resolve_settings_path_precedence(monkeypatch, tmp_path: Path):
    explicit = tmp_path / "explicit.json"
    env_path = tmp_path / "env.json"
    candidate_1 = tmp_path / "candidate-1.json"
    candidate_2 = tmp_path / "candidate-2.json"

    monkeypatch.setattr(
        install,
        "CANDIDATE_SETTINGS_PATHS",
        [candidate_1, candidate_2],
    )

    # Explicit path wins.
    assert install._resolve_settings_path(str(explicit)) == explicit

    # Env var is next.
    monkeypatch.setenv("CLAUDE_SETTINGS_PATH", str(env_path))
    assert install._resolve_settings_path() == env_path
    monkeypatch.delenv("CLAUDE_SETTINGS_PATH", raising=False)

    # Existing candidate is next.
    candidate_2.write_text("{}\n")
    assert install._resolve_settings_path() == candidate_2

    # Otherwise default to first candidate path.
    candidate_2.unlink()
    assert install._resolve_settings_path() == candidate_1


def test_install_is_idempotent_and_preserves_existing_hooks(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/other_hook.py",
                                    "async": True,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )

    install.install(settings_path)
    install.install(settings_path)

    settings = _read_json(settings_path)

    stop_hooks = settings["hooks"]["Stop"]
    pretool_hooks = settings["hooks"]["PreToolUse"]
    permission_hooks = settings["hooks"]["PermissionRequest"]

    stop_cmds = [
        Path(h["command"]).name
        for group in stop_hooks
        for h in group.get("hooks", [])
    ]
    pretool_cmds = [
        Path(h["command"]).name
        for group in pretool_hooks
        for h in group.get("hooks", [])
    ]
    permission_cmds = [
        Path(h["command"]).name
        for group in permission_hooks
        for h in group.get("hooks", [])
    ]

    assert stop_cmds.count("other_hook.py") == 1
    assert stop_cmds.count("handsfree_hook.py") == 1
    assert pretool_cmds.count("ask_question_hook.py") == 1
    assert permission_cmds.count("permission_hook.py") == 1

    # AskUserQuestion hook should be installed with the matcher.
    ask_groups = [g for g in pretool_hooks if g.get("matcher") == "AskUserQuestion"]
    assert len(ask_groups) == 1


def test_uninstall_removes_only_handsfree_hooks(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/repo/hooks/handsfree_hook.py",
                                    "async": True,
                                },
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/other_hook.py",
                                    "async": True,
                                },
                            ]
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "AskUserQuestion",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/repo/hooks/ask_question_hook.py",
                                    "async": True,
                                }
                            ],
                        }
                    ],
                    "PermissionRequest": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/repo/hooks/permission_hook.py",
                                    "async": True,
                                }
                            ]
                        }
                    ],
                }
            }
        )
    )

    install.uninstall(settings_path)
    settings = _read_json(settings_path)

    stop_groups = settings["hooks"]["Stop"]
    stop_cmds = [
        Path(h["command"]).name
        for group in stop_groups
        for h in group.get("hooks", [])
    ]
    assert stop_cmds == ["other_hook.py"]

    # Handsfree-only groups are removed once empty.
    assert settings["hooks"]["PreToolUse"] == []
    assert settings["hooks"]["PermissionRequest"] == []


def test_load_settings_backs_up_malformed_json(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not-valid-json")

    loaded = install._load_settings(settings_path)

    assert loaded == {}
    backup_path = settings_path.with_suffix(".json.bak")
    assert backup_path.exists()
