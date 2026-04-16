#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Install Handsfree Gemini CLI hooks into Gemini settings.json."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GEMINI_HOOK_SCRIPT = REPO_ROOT / "hooks" / "gemini_notify.py"
HANDSFREE_HOOK_NAMES = {
    GEMINI_HOOK_SCRIPT.name,
}
CANDIDATE_SETTINGS_PATHS = [
    Path.home() / ".gemini" / "settings.json",
]
HOOK_EVENTS = ("AfterAgent", "Notification")
DEFAULT_TIMEOUT_MS = 300_000


def _resolve_settings_path(explicit: str | None = None) -> Path:
    """Pick Gemini settings.json path from arg/env/existing defaults."""
    if explicit:
        return Path(explicit).expanduser()

    env_path = os.environ.get("GEMINI_SETTINGS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    existing = [path for path in CANDIDATE_SETTINGS_PATHS if path.exists()]
    if existing:
        return existing[0]

    return CANDIDATE_SETTINGS_PATHS[0]


def _load_settings(settings_path: Path) -> dict:
    """Load existing settings or return empty structure."""
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        backup_path = settings_path.with_suffix(".json.bak")
        try:
            shutil.copy2(settings_path, backup_path)
            print(
                f"Warning: malformed settings.json — backed up to {backup_path}",
                file=sys.stderr,
            )
        except OSError:
            print(
                f"Warning: malformed settings.json and backup failed: {e}",
                file=sys.stderr,
            )
        return {}


def _save_settings(settings_path: Path, settings: dict) -> None:
    """Write settings atomically."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(settings_path.parent), suffix=".json.tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.rename(tmp_path, str(settings_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _hook_command(script: Path = GEMINI_HOOK_SCRIPT, python_bin: str | None = None) -> str:
    """Build a shell command compatible with Gemini CLI hook settings."""
    executable = python_bin or os.environ.get("HANDSFREE_PYTHON_BIN") or sys.executable
    return f"{shlex.quote(executable)} {shlex.quote(str(script))}"


def _hook_entry(
    *,
    event: str,
    script: Path = GEMINI_HOOK_SCRIPT,
    python_bin: str | None = None,
) -> dict:
    """Build a Gemini command hook entry."""
    return {
        "type": "command",
        "name": f"handsfree-gemini-{event.lower()}",
        "command": _hook_command(script, python_bin),
        "timeout": DEFAULT_TIMEOUT_MS,
        "description": "Enqueue Gemini CLI events for Handsfree speech and wake retrieval.",
    }


def _is_handsfree_hook(hook: dict) -> bool:
    command = str(hook.get("command") or "")
    if not command:
        return False
    return any(name in command for name in HANDSFREE_HOOK_NAMES)


def _add_hook_to_event(
    settings: dict,
    event: str,
    *,
    script: Path = GEMINI_HOOK_SCRIPT,
    python_bin: str | None = None,
) -> None:
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    for group in event_hooks:
        for hook in group.get("hooks", []):
            if _is_handsfree_hook(hook):
                hook.update(_hook_entry(event=event, script=script, python_bin=python_bin))
                print(f"  {event}: updated")
                return

    event_hooks.append({
        "hooks": [_hook_entry(event=event, script=script, python_bin=python_bin)]
    })
    print(f"  {event}: added")


def install(settings_path: Path, *, python_bin: str | None = None) -> None:
    """Add Handsfree hooks to Gemini CLI settings."""
    print("Installing Handsfree Gemini hooks...")
    print(f"Settings file: {settings_path}")

    settings = _load_settings(settings_path)
    for event in HOOK_EVENTS:
        _add_hook_to_event(settings, event, python_bin=python_bin)

    _save_settings(settings_path, settings)
    print("Done. Gemini hooks installed.")


def uninstall(settings_path: Path) -> None:
    """Remove Handsfree hooks from Gemini CLI settings."""
    print("Removing Handsfree Gemini hooks...")
    settings = _load_settings(settings_path)

    hooks = settings.get("hooks", {})
    for event in list(hooks.keys()):
        filtered = []
        for group in hooks[event]:
            group_hooks = [h for h in group.get("hooks", []) if not _is_handsfree_hook(h)]
            if group_hooks:
                group["hooks"] = group_hooks
                filtered.append(group)
        hooks[event] = filtered

    _save_settings(settings_path, settings)
    print("Done. Gemini hooks removed.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or uninstall Handsfree Gemini CLI hooks."
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="install",
        choices=["install", "uninstall"],
        help="Action to run (default: install).",
    )
    parser.add_argument(
        "--settings",
        help="Explicit path to Gemini settings.json "
        "(overrides GEMINI_SETTINGS_PATH and auto-detection).",
    )
    parser.add_argument(
        "--python",
        dest="python_bin",
        help="Python executable to use in the hook command "
        "(default: HANDSFREE_PYTHON_BIN or this interpreter).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings_path = _resolve_settings_path(args.settings)
    if args.action == "uninstall":
        uninstall(settings_path)
    else:
        install(settings_path, python_bin=args.python_bin)
