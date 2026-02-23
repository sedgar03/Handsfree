# Claude Code Hooks Setup

Handsfree integrates with Claude Code via hook commands configured in Claude's `settings.json`.

## What gets installed

The installer registers three hooks on three events:

| Event | Hook Script | Purpose |
|---|---|---|
| `Stop` | `hooks/handsfree_hook.py` | Summarize assistant output via `claude -p` and speak it |
| `PreToolUse` (matcher: `AskUserQuestion`) | `hooks/ask_question_hook.py` | Speak the question and options so the user can answer by voice |
| `PermissionRequest` | `hooks/permission_hook.py` | Speak the permission prompt so the user can allow/deny by voice |

Each entry looks like:

```json
{
  "type": "command",
  "command": "/absolute/path/to/Handsfree/hooks/<hook>.py",
  "async": true
}
```

All hooks are async to avoid blocking Claude Code.

## Recommended install command

From repo root:

```bash
uv run hooks/install.py
```

This is idempotent (safe to run multiple times).

## Uninstall

```bash
uv run hooks/install.py uninstall
```

This also removes the legacy `auto_listen_hook.py` if present.

## Settings path resolution

`hooks/install.py` resolves Claude `settings.json` in this order:

1. `--settings /path/to/settings.json` (CLI flag)
2. `CLAUDE_SETTINGS_PATH` (environment variable)
3. Existing `~/.claude/settings.json`
4. Existing `~/dotfiles/claude/settings.json`
5. Default `~/.claude/settings.json` (created if missing)

## Example commands

Use these exact commands from repo root:

```bash
# Install hooks
uv run hooks/install.py

# Install to an explicit settings file
uv run hooks/install.py --settings ~/.claude/settings.json

# Remove hooks
uv run hooks/install.py uninstall

# Verify install
rg -n "handsfree_hook.py\|ask_question_hook.py\|permission_hook.py" ~/.claude/settings.json 2>/dev/null
```

If `claude` is not on PATH, set:

```bash
export HANDSFREE_CLAUDE_BIN="/absolute/path/to/claude"
```

`src/summarizer.py` will use that path when hook summaries call `claude -p`.

## Manual JSON patch (if needed)

If you do not use the installer, add the hook entries under:

1. `hooks.Stop[]` — `handsfree_hook.py`
2. `hooks.PreToolUse[]` with `"matcher": "AskUserQuestion"` — `ask_question_hook.py`
3. `hooks.PermissionRequest[]` — `permission_hook.py`

Keep existing hooks in place; append Handsfree alongside them.
