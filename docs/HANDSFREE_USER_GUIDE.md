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

Start only the listener, without opening Claude Code or changing the HUD
speech/wake toggles:

```bash
./scripts/listener.sh --media-key
```

Avoid AirPods stem-click routing entirely and use wake phrase mode:

```bash
./scripts/listener.sh --wake-word
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

The listener-only command runs in the foreground. Use it when `usage-hud-app`
is your control surface and Claude/Codex are already running in tmux panes.
Wake phrase mode is armed by the HUD wake button.

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

## Wake Phrase Workflow

Wake word mode avoids AirPods media-key routing:

1. Start `usage-hud-app`.
2. Turn on the wake button.
3. Wait for the loading icon to switch to the enabled microphone.
4. Say the OpenWakeWord phrase, then a command.

If you are not using the HUD, run `./scripts/listener.sh --wake-word` manually
and arm the mode with `PYTHONPATH=src uv run python -m broker enable wake`.

Examples:

```text
hey jarvis
hey jarvis ... what's up
```

The default OpenWakeWord model is `hey jarvis`, because OpenWakeWord does not
ship a built-in `handsfree` model. If a queued message exists, saying the wake
word alone reads the message. If the queue is empty, the listener captures the
next utterance with Whisper and only acts on queue-read commands by default.
Freeform command injection is disabled unless explicitly enabled:

```json
{
  "openwakeword_allow_freeform_commands": true
}
```

To use the old Whisper-only phrase matcher instead, set:

```json
{
  "wake_engine": "whisper"
}
```

In that mode, bare queue phrases like `what's up` and `what did I miss` still
work without saying `hey jarvis`.

Queue retrieval is gated by a consumption watermark. When you re-arm or unmute
the workflow, old pending rows are ignored; `read next` only consumes events
created after the newest of `~/.handsfree/consume-after`,
`~/.handsfree/speech-enabled`, and `~/.handsfree/wake-enabled`.

Spoken queue items start with the captured workflow label, usually the tmux
window name, so you can hear context like `USChem here` before the message.

To reset the watermark manually:

```bash
PYTHONPATH=src uv run python -m broker mark-unmuted
PYTHONPATH=src uv run python -m broker list --current
```

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
  "summary_backend": "mlx",
  "summary_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
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
  "max_recording": 300,
  "wake_engine": "openwakeword",
  "openwakeword_models": ["hey jarvis"],
  "openwakeword_threshold": 0.5,
  "openwakeword_inference_framework": "onnx",
  "openwakeword_allow_freeform_commands": false,
  "wake_words": ["handsfree", "hands free", "hey codex", "hey claude"],
  "wake_speech_threshold": 0.008,
  "wake_silence_threshold": 0.004,
  "wake_silence_timeout": 1.2,
  "wake_max_utterance": 20.0,
  "wake_min_utterance": 0.4,
  "wake_allow_queue_without_prefix": true
}
```

Useful toggles:

- `input_mode`: `media_key` or `hotkey`
- `summary_backend`: `mlx` for the resident local Qwen summarizer, `local` for deterministic summaries only, or `claude` for legacy `claude -p`
- `summary_model`: MLX model used by the resident summary daemon
- `auto_submit`: enable/disable Enter submit behavior
- `auto_submit_after_transcription`: if `true`, submit immediately after STT result is injected
- `silence_timeout`: seconds of silence before auto-stop
- `wake_engine`: `openwakeword` for lightweight first-stage wake detection, or `whisper` for legacy phrase matching
- `openwakeword_models`: OpenWakeWord built-in model names or custom model paths
- `openwakeword_threshold`: activation threshold for OpenWakeWord scores
- `openwakeword_allow_freeform_commands`: if `true`, non-queue follow-up speech after the wake word can be injected into the active app
- `wake_words`: phrases that arm a spoken command in wake phrase mode
- `wake_speech_threshold`: mic energy threshold for wake phrase capture
- `wake_silence_timeout`: seconds of silence before wake phrase capture stops
- `wake_allow_queue_without_prefix`: allow `read next` without a wake phrase
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

### Single click starts recording, but another click will not stop it

Grant Input Monitoring to the terminal app and restart the listener. The primary
AirPods backend can miss clicks while the microphone stream is active; the
Input Monitoring fallback is what keeps manual stop/cancel reliable during
recording.

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
