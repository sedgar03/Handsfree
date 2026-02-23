# Handsfree

Local voice layer for Claude Code on macOS.

- Claude speaks progress updates through TTS hooks.
- You talk back using AirPods stem click (or hotkey fallback).
- Speech is transcribed locally and submitted back to Claude.

No paid TTS/STT APIs required.

**Requirements:**
- macOS 14+ (Sonoma) on **Apple Silicon** (M1/M2/M3/M4) — Intel Macs are not supported
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed
- [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.11+
- AirPods (or built-in mic)

## Core Flow (Current Default)

AirPods mode with auto-send enabled:

1. Claude finishes talking or has a question
2. Text to speech triggers and Claude's response is modified and read aloud
3. The listener waits for the user to take an action
4. User single-clicks stem to start recording
5. Speak
6. Silence (or manual stop stem click on AirPod) ends recording
7. Chime indicates listener is no longer listening
8. Transcription completes
9. Message auto-submits to Claude (whoosh cue)

## Quick Start

```bash
# 1) One-time setup
./scripts/setup.sh

# 2) Start a handsfree session with AirPods controls
./scripts/handsfree.sh --media-key
```

When Claude exits, the launcher cleans up automatically.

## Required macOS Permissions

Grant these to the terminal app you use (`Terminal`, `iTerm2`, `Ghostty`, etc.):

1. Microphone
2. Accessibility
3. Input Monitoring (recommended)
4. Automation -> allow controlling `System Events`

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





## Useful Commands

```bash
# Permission check only
./scripts/handsfree.sh --check

# TTS test
uv run --script src/tts.py "Handsfree test"

# AirPods remote command test
PYTHONUNBUFFERED=1 uv run --script src/test_mpremote.py

# Listener only
PYTHONUNBUFFERED=1 HANDSFREE_INPUT_MODE=media_key uv run --script src/listener.py

# Reinstall Claude hooks
uv run --script hooks/install.py

# Reinstall to a specific Claude settings file
uv run --script hooks/install.py --settings ~/.claude/settings.json
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
