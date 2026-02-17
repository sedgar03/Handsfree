#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Install handsfree hooks into Claude Code settings.json.

Adds handsfree_hook.py to Stop, Notification, and PreCompact events,
and ask_question_hook.py to PreToolUse (AskUserQuestion) event,
alongside existing hooks (AOE sounds, etc). Idempotent — safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "hooks" / "handsfree_hook.py"
ASK_QUESTION_HOOK_SCRIPT = REPO_ROOT / "hooks" / "ask_question_hook.py"
PERMISSION_HOOK_SCRIPT = REPO_ROOT / "hooks" / "permission_hook.py"
HANDSFREE_HOOK_NAMES = {HOOK_SCRIPT.name, ASK_QUESTION_HOOK_SCRIPT.name, PERMISSION_HOOK_SCRIPT.name}
CANDIDATE_SETTINGS_PATHS = [
    Path.home() / ".claude" / "settings.json",
    Path.home() / "dotfiles" / "claude" / "settings.json",
]


def _resolve_settings_path(explicit: str | None = None) -> Path:
    """Pick Claude settings.json path from arg/env/existing defaults."""
    if explicit:
        return Path(explicit).expanduser()

    env_path = os.environ.get("CLAUDE_SETTINGS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    existing = [path for path in CANDIDATE_SETTINGS_PATHS if path.exists()]
    if existing:
        if len(existing) > 1:
            print(
                f"Warning: multiple settings files found, using: {existing[0]}",
                file=sys.stderr,
            )
        return existing[0]

    return CANDIDATE_SETTINGS_PATHS[0]


def _load_settings(settings_path: Path) -> dict:
    """Load existing settings or return empty structure."""
    if settings_path.exists():
        with open(settings_path) as f:
            return json.load(f)
    return {}


def _save_settings(settings_path: Path, settings: dict):
    """Write settings back to disk."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def _hook_entry(script: Path = HOOK_SCRIPT) -> dict:
    """Build the hook entry for a handsfree script."""
    return {
        "type": "command",
        "command": str(script),
        "async": True,
    }


def _is_handsfree_hook(hook: dict) -> bool:
    """Check if a hook entry is any of our handsfree hooks."""
    command = hook.get("command", "")
    if not command:
        return False
    try:
        return Path(command).name in HANDSFREE_HOOK_NAMES
    except Exception:
        return "handsfree" in command


def _add_hook_to_event(
    settings: dict,
    event: str,
    matcher: str | None = None,
    script: Path = HOOK_SCRIPT,
):
    """Add a handsfree hook to an event, preserving existing hooks."""
    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    # Check if already installed in a group with matching matcher
    label = f"{event}[{matcher}]" if matcher else event
    for group in event_hooks:
        if group.get("matcher") != matcher:
            continue
        for hook in group.get("hooks", []):
            cmd = hook.get("command", "")
            try:
                if Path(cmd).name == script.name:
                    print(f"  {label}: already installed")
                    return
            except Exception:
                pass

    # Build hook group
    entry = {"hooks": [_hook_entry(script)]}
    if matcher:
        entry["matcher"] = matcher

    event_hooks.append(entry)
    print(f"  {label}: added")


def install(settings_path: Path):
    """Add handsfree hooks to Claude Code settings."""
    print(f"Installing handsfree hooks...")
    print(f"Settings file: {settings_path}")

    settings = _load_settings(settings_path)

    # Add to Stop, PreCompact, and Notification events
    _add_hook_to_event(settings, "Stop")
    _add_hook_to_event(settings, "PreCompact")
    _add_hook_to_event(settings, "Notification", matcher="idle_prompt")
    _add_hook_to_event(settings, "Notification", matcher="permission_prompt")

    # AskUserQuestion TTS alert (must be async to avoid bug #12031)
    _add_hook_to_event(
        settings, "PreToolUse", matcher="AskUserQuestion",
        script=ASK_QUESTION_HOOK_SCRIPT,
    )

    # PermissionRequest TTS alert (no matcher — covers all tools)
    _add_hook_to_event(
        settings, "PermissionRequest",
        script=PERMISSION_HOOK_SCRIPT,
    )

    _save_settings(settings_path, settings)
    print("Done. Hooks installed.")


def uninstall(settings_path: Path):
    """Remove handsfree hooks from Claude Code settings."""
    print("Removing handsfree hooks...")
    settings = _load_settings(settings_path)

    hooks = settings.get("hooks", {})
    for event in list(hooks.keys()):
        original = hooks[event]
        filtered = []
        for group in original:
            group_hooks = [h for h in group.get("hooks", []) if not _is_handsfree_hook(h)]
            if group_hooks:
                group["hooks"] = group_hooks
                filtered.append(group)
        hooks[event] = filtered

    _save_settings(settings_path, settings)
    print("Done. Hooks removed.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or uninstall Handsfree Claude Code hooks."
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
        help="Explicit path to Claude settings.json "
        "(overrides CLAUDE_SETTINGS_PATH and auto-detection).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings_path = _resolve_settings_path(args.settings)
    if args.action == "uninstall":
        uninstall(settings_path)
    else:
        install(settings_path)
