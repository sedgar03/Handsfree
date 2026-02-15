# Handsfree

> Walk away from your desk with AirPods. Claude speaks summaries of what it's doing, you tap to talk back. Fully local TTS/STT, no paid APIs.

## Quick Start

```bash
cd ~/Code/Handsfree

# Setup: install deps, download models, configure hooks
./scripts/setup.sh

# Enable handsfree mode
touch ~/.claude/handsfree

# Disable handsfree mode
rm ~/.claude/handsfree
```

## How It Works

**Claude → You (TTS):** Claude Code hooks fire when Claude stops or needs input. A `claude -p` call summarizes the response, then Kokoro TTS speaks it through your AirPods.

**You → Claude (STT):** Tap your AirPod stem (or press a hotkey). A listener captures mic audio, transcribes it locally with Whisper, and sends the text to Claude.

**Handsfree mode** layers on top of your existing setup. AOE sound effects still play on your computer. Voice output routes to AirPods. Toggle it with a file, just like `~/.claude/mute`.

## Config

Edit `~/.claude/voice-config.json`:

```json
{
  "input_mode": "stem-click",
  "verbosity": "detailed",
  "kokoro_voice": "af_heart",
  "hotkey": "F18"
}
```

- `input_mode`: `"stem-click"` or `"hotkey"`
- `verbosity`: `"terse"` (1 sentence) or `"detailed"` (2-3 sentences with file names)
- `kokoro_voice`: Kokoro voice ID
- `hotkey`: key for hotkey mode

## Project Structure

```
hooks/             — Claude Code hook scripts (pointed to by settings.json)
src/               — Core modules (TTS, STT, summarizer, listeners, audio)
scripts/           — Setup and model download scripts
models/            — Downloaded models (gitignored)
docs/              — Charter, handoff, decisions, learnings
tests/             — Test suite
```

## Tech Stack

| Component | Tool |
|---|---|
| TTS | Kokoro (kokoro-onnx) / macOS `say` fallback |
| STT | lightning-whisper-mlx (whisper-large-v3-turbo) |
| Summarization | `claude -p` with tuned prompts |
| Input | AirPod stem-click (PyObjC) or global hotkey |
| Audio | sounddevice |
| Deps | uv (inline script dependencies, no venv needed) |

## Status

**Current Phase:** G0 — Kickoff (charter review)

## License

MIT
