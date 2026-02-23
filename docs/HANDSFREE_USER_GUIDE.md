# Handsfree User Guide

This guide is the practical "how do I actually use this?" doc for running Claude Code handsfree with AirPods on macOS.

## Goal

Use Claude Code without staring at the screen:

1. Claude speaks updates (TTS hook).
2. You single-click AirPods stem to talk.
3. Speech transcribes locally.
4. Text is auto-submitted to Claude.

## One-Time Setup

1. Clone this repo.
2. Run:

```bash
./scripts/setup.sh
```

This downloads models, installs hooks, and writes a default config.

Hook details and manual install format are documented in:

- `docs/CLAUDE_HOOKS_SETUP.md`

## Required macOS Permissions

Grant permissions to the terminal app you use to launch Claude (`Terminal`, `iTerm2`, `Ghostty`, etc.).

1. `Microphone`
2. `Accessibility`
3. `Input Monitoring` (recommended; needed for legacy event fallback paths)
4. `Automation` -> allow terminal controlling `System Events` (prompt appears on first submit attempt)

## Daily Use

Start a handsfree Claude session:

```bash
./scripts/handsfree.sh --media-key
```

If Claude settings live in a non-default location, reinstall hooks explicitly:

```bash
uv run --script hooks/install.py --settings /path/to/settings.json
```

The launcher will:

1. Enable handsfree mode (`~/.claude/handsfree`)
2. Start the listener in the background
3. Launch `claude`
4. Stop listener + disable handsfree mode when Claude exits

Permission checks run automatically before startup. To run checks only:

```bash
./scripts/handsfree.sh --check
```

## AirPods Workflow (Default)

Current default is fully handsfree send:

1. Single click stem -> start recording
2. Speak
3. Stop by silence (or manual click)
4. Chime indicates listener is no longer listening
5. Transcription completes
6. Message auto-submits to Claude (whoosh send cue)

No second click is required when `auto_submit_after_transcription` is enabled.

## Config

Config file:

```bash
~/.claude/voice-config.json
```

Recommended baseline:

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

Useful toggles:

- `input_mode`: `media_key` or `hotkey`
- `auto_submit`: enable/disable Enter submit behavior
- `auto_submit_after_transcription`: if `true`, submit immediately after STT result is injected
- `silence_timeout`: seconds of silence before auto-stop
- `kokoro_speed`: speaking rate (default `1.1`)

Voice syntax:

- Plain voice name: `af_heart`
- Blend: `af_heart:0.7,af_nicole:0.3`
- Preset alias: `narrator` (resolved from `voice_presets`)

## Per-Terminal Voice Override

Set voice per shell/terminal tab with `HANDSFREE_VOICE`:

```bash
export HANDSFREE_VOICE="af_heart:0.7,af_nicole:0.3"
./scripts/handsfree.sh --media-key
```

Examples:

```bash
# Terminal A (warmer blend)
export HANDSFREE_VOICE="af_heart:0.8,af_nicole:0.2"

# Terminal B (single voice)
export HANDSFREE_VOICE="af_bella"
```

To clear override:

```bash
unset HANDSFREE_VOICE
```

## Fast Sanity Tests

1. Test MPRemote AirPods event path:

```bash
PYTHONUNBUFFERED=1 uv run --script src/test_mpremote.py
```

2. Test full listener only:

```bash
PYTHONUNBUFFERED=1 HANDSFREE_INPUT_MODE=media_key uv run --script src/listener.py
```

3. Test TTS:

```bash
uv run --script src/tts.py "Handsfree test"
```

## Troubleshooting

### I hear recording chimes but nothing sends

- Verify `auto_submit` is `true`.
- Confirm Automation permission to `System Events` is granted.
- Run listener directly and watch for:
  - `[submit] Enter pressed via ...`

### AirPods clicks do nothing

- Ensure AirPods are connected and active output device.
- Run `src/test_mpremote.py` and confirm command callbacks print.
- Re-check permissions list above.

### Hooks are not speaking

- Ensure handsfree mode is enabled (`~/.claude/handsfree`).
- Reinstall hooks:

```bash
uv run --script hooks/install.py
```

- If Claude CLI is not on PATH for hook subprocesses, set:

```bash
export HANDSFREE_CLAUDE_BIN="/absolute/path/to/claude"
```

### Return to manual-submit behavior

Set:

```json
{
  "auto_submit_after_transcription": false
}
```

Then double-click idle submit behavior remains available.
