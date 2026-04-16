# Gemini Hooks Setup

Handsfree integrates with Gemini CLI through the same queue and HUD controls
used by Claude and Codex. Gemini hooks write events into
`~/.handsfree/events.sqlite`, then the shared notification, speech, and wake
buttons decide whether to mute, speak immediately, keep the item queued, or
mark it done.

## Events

The installer registers one hook script on two Gemini events:

| Gemini event | Handsfree behavior |
|---|---|
| `AfterAgent` | Summarize the final Gemini response and enqueue it as a `summary` event |
| `Notification` | Enqueue Gemini alerts; `ToolPermission` alerts become `permission` events |

The hook prints only JSON to stdout because Gemini parses hook stdout as JSON.
Diagnostics go to stderr and the shared hook log.

## Install

```bash
uv run --script hooks/install_gemini.py
```

If Gemini settings live outside `~/.gemini/settings.json`, pass the file
explicitly:

```bash
uv run --script hooks/install_gemini.py --settings /path/to/settings.json
```

To pin the hook to a specific Python interpreter:

```bash
uv run --script hooks/install_gemini.py --python /opt/homebrew/bin/python3.11
```

## Uninstall

```bash
uv run --script hooks/install_gemini.py uninstall
```

## Manual Config

The installer writes entries equivalent to:

```json
{
  "hooks": {
    "AfterAgent": [
      {
        "hooks": [
          {
            "type": "command",
            "name": "handsfree-gemini-afteragent",
            "command": "/path/to/python /Users/stevenedgar/Code/handsfree/hooks/gemini_notify.py",
            "timeout": 300000
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "name": "handsfree-gemini-notification",
            "command": "/path/to/python /Users/stevenedgar/Code/handsfree/hooks/gemini_notify.py",
            "timeout": 300000
          }
        ]
      }
    ]
  }
}
```

## Mute

Gemini notification sound mute uses:

```text
~/.gemini/mute
```
