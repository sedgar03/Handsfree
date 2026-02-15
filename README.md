# ClaudeVoice

> Hands-free voice layer for Claude Code. Walk away from your desk with AirPods — Claude speaks summaries of what it's doing, you tap to talk back. Fully local, no paid APIs.

## Quick Start

```bash
# Clone and enter project
git clone <repo-url>
cd ClaudeVoice

# Install dependencies (requires uv)
uv sync

# Download models (Kokoro TTS + Whisper)
uv run python scripts/download_models.py

# Install Claude Code hooks
uv run python scripts/install_hooks.py

# Test TTS
uv run python -m claudevoice.tts "Hello from ClaudeVoice"
```

## How It Works

**Claude → You (TTS):** Claude Code hooks fire when Claude stops, needs permission, or compacts. A summarizer extracts key info from the hook JSON and speaks it through Kokoro TTS to your AirPods.

**You → Claude (STT):** A background listener detects AirPod stem-clicks via macOS media key events. When you tap, it captures mic audio, transcribes it locally with Whisper, and sends the text to Claude.

## Toggle

```bash
touch ~/.claude/voice-mute    # Mute voice
rm ~/.claude/voice-mute       # Unmute voice
```

## Tech Stack

| Component | Tool |
|---|---|
| TTS | Kokoro (local ONNX) / macOS `say` fallback |
| STT | faster-whisper (local) |
| Media keys | PyObjC CGEventTap |
| Audio | sounddevice |
| Language | Python 3.11+ / uv |

## Project Structure

```
CLAUDE.md          — Agent operating system (AI reads this first)
docs/              — Project charter, handoff, decisions, learnings
src/claudevoice/   — Source code
  tts.py           — Kokoro TTS engine
  stt.py           — Whisper STT engine
  summarizer.py    — Hook JSON → spoken summary
  stem_listener.py — AirPod stem-click detection
  audio.py         — Audio device routing
  hooks/           — Claude Code hook scripts
tests/             — Test suite
scripts/           — Setup and install scripts
```

## Status

**Current Phase:** G0 — Kickoff (charter review)

## License

MIT
