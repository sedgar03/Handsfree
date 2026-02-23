# Handsfree

Local voice layer for Claude Code on macOS.

- Claude speaks progress updates through TTS hooks.
- You talk back using AirPods stem click (or hotkey fallback).
- Speech is transcribed locally and submitted back to Claude.

No paid TTS/STT APIs required.

**Platform:** macOS 14+ (Sonoma) on Apple Silicon. Requires AirPods (or built-in mic) and terminal permissions for Accessibility + Input Monitoring.

## Quick Start

```bash
# 1) One-time setup
./scripts/setup.sh

# 2) Start a handsfree session with AirPods controls
./scripts/handsfree.sh --media-key
```

When Claude exits, the launcher cleans up automatically.

## Full Usage Guide

See `docs/HANDSFREE_USER_GUIDE.md` for:

- macOS permission checklist
- daily workflow
- config options
- troubleshooting and diagnostics

See `docs/CLAUDE_HOOKS_SETUP.md` for:

- exactly how Claude Code hooks are installed
- settings path resolution (`~/.claude` vs `~/dotfiles/claude`)
- manual installation and verification commands

## Core Flow (Current Default)

AirPods mode with auto-send enabled:

1. Single click stem to start recording
2. Speak
3. Silence (or manual stop click) ends recording
4. Chime indicates listener is no longer listening
5. Transcription completes
6. Message auto-submits to Claude (whoosh cue)

## Required macOS Permissions

Grant these to the terminal app you use (`Terminal`, `iTerm2`, `Ghostty`, etc.):

1. Microphone
2. Accessibility
3. Input Monitoring (recommended)
4. Automation -> allow controlling `System Events`

## Useful Commands

```bash
# Permission check only
./scripts/handsfree.sh --check

# TTS test
uv run src/tts.py "Handsfree test"

# AirPods remote command test
PYTHONUNBUFFERED=1 uv run src/test_mpremote.py

# Listener only
PYTHONUNBUFFERED=1 HANDSFREE_INPUT_MODE=media_key uv run src/listener.py

# Reinstall Claude hooks
uv run hooks/install.py

# Reinstall to a specific Claude settings file
uv run hooks/install.py --settings ~/.claude/settings.json
```

## Config

Config path:

```bash
~/.claude/voice-config.json
```

Example:

```json
{
  "input_mode": "media_key",
  "verbosity": "detailed",
  "kokoro_voice": "af_heart",
  "voice_presets": {
    "narrator": "af_heart:0.7,af_nicole:0.3",
    "concise": "af_bella"
  },
  "kokoro_speed": 1.1,
  "hotkey": "F18",
  "auto_submit": true,
  "auto_submit_after_transcription": true,
  "silence_timeout": 4.5,
  "max_recording": 300
}
```

Voice options:

- Plain voice: `af_heart`
- Blend spec: `af_heart:0.7,af_nicole:0.3`
- Preset name from `voice_presets`: `narrator`

Per-terminal override (no config edits required):

```bash
export HANDSFREE_VOICE="af_heart:0.7,af_nicole:0.3"
./scripts/handsfree.sh --media-key
```

You can use different `HANDSFREE_VOICE` values in different terminals for quick A/B testing.

## Project Layout

```text
scripts/
  setup.sh            # one-time setup
  handsfree.sh        # launch handsfree Claude session
hooks/
  handsfree_hook.py   # Claude hook: summarize + speak
  install.py          # add/remove hooks in Claude settings
src/
  listener.py         # unified input listener
  media_key_listener.py
  hotkey_listener.py
  stt.py
  tts.py
  summarizer.py
  test_mpremote.py
docs/
  HANDSFREE_USER_GUIDE.md
```

## License

MIT
