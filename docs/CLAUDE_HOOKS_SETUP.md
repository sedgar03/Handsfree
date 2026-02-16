# Claude Code Hooks Setup

Handsfree integrates with Claude Code via hook commands configured in Claude's `settings.json`.

## What gets installed

The Handsfree installer adds `hooks/handsfree_hook.py` to these Claude hook events:

1. `Stop`
2. `PreCompact`
3. `Notification` with matcher `idle_prompt`
4. `Notification` with matcher `permission_prompt`

Each entry is:

```json
{
  "type": "command",
  "command": "/absolute/path/to/Handsfree/hooks/handsfree_hook.py",
  "async": true
}
```

## Recommended install command

From repo root:

```bash
uv run hooks/install.py
```

This is idempotent (safe to run multiple times).

## Settings path resolution

`hooks/install.py` resolves Claude `settings.json` in this order:

1. `--settings /path/to/settings.json` (CLI flag)
2. `CLAUDE_SETTINGS_PATH` (environment variable)
3. Existing `~/.claude/settings.json`
4. Existing `~/dotfiles/claude/settings.json`
5. Default `~/.claude/settings.json` (created if missing)

## Agent-friendly commands

Use these exact commands from repo root:

```bash
# Install hooks
uv run hooks/install.py

# Install to an explicit settings file
uv run hooks/install.py --settings ~/.claude/settings.json

# Remove hooks
uv run hooks/install.py uninstall

# Verify install
rg -n "handsfree_hook.py" ~/.claude/settings.json ~/dotfiles/claude/settings.json 2>/dev/null
```

If `claude` is not on PATH, set:

```bash
export HANDSFREE_CLAUDE_BIN="/absolute/path/to/claude"
```

`src/summarizer.py` will use that path when hook summaries call `claude -p`.

## Manual JSON patch (if needed)

If you do not use the installer, add the hook command above under:

1. `hooks.Stop[]`
2. `hooks.PreCompact[]`
3. `hooks.Notification[]` with `"matcher": "idle_prompt"`
4. `hooks.Notification[]` with `"matcher": "permission_prompt"`

Keep existing hooks in place; append Handsfree alongside them.
