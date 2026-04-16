# Source Code — Module Map

> This file maps source code modules to their responsibilities.

## Module Map

| Module | Purpose |
|---|---|
| `config.py` | Read `~/.claude/voice-config.json` with defaults, check handsfree toggle |
| `tts.py` | Kokoro TTS client/wrapper — uses resident daemon when warm, macOS `say` fallback |
| `tts_daemon.py` | Resident Kokoro/macOS speech daemon for warm playback |
| `stt.py` | mlx-whisper STT wrapper — record from mic via sounddevice, warm and transcribe audio |
| `summarizer.py` | Summarize agent output for speech; resident local backend by default with deterministic fallback |
| `summary_daemon.py` | Resident summarizer daemon; supports MLX and local GGUF via llama.cpp |
| `conductor_daemon.py` | Resident local LLM daemon for phase-1 Conductor mode chat; supports MLX and local GGUF via llama.cpp |
| `conductor_client.py` | Dependency-free socket client for the conductor daemon |
| `service_control.py` | Start, warm, enable, disable, and inspect Handsfree services |
| `listener.py` | Unified input listener — routes to media_key or hotkey mode, handles text injection and question/permission answering |
| `media_key_listener.py` | AirPods stem-click detection via MPRemoteCommandCenter + CGEventTap fallback, VAD auto-stop, recording state machine |
| `hotkey_listener.py` | Global hotkey detection via PyObjC CGEventTap (F18 hold-to-record) |
| `airpods_check.py` | Check if AirPods are connected and print status |
| `diagnose_events.py` | Diagnostic tool — logs all media key backends and decoded event data |
| `test_mpremote.py` | Live test for MPRemoteCommandCenter stem-click callbacks |
| `test_mpremote_inputstream.py` | Test whether MPRemote callbacks drop during active `sd.InputStream` |

## Getting Started

```bash
# Run setup (downloads models, installs hooks, creates config)
./scripts/setup.sh

# Test TTS
uv run --script src/tts.py "Hello from Handsfree"

# Warm and inspect speech services
PYTHONPATH=src uv run python -m broker warm speech
PYTHONPATH=src uv run python -m broker status

# Try the phase-1 local conductor
PYTHONPATH=src uv run python -m broker warm conductor --timeout 300
PYTHONPATH=src uv run python -m broker conductor chat "Help me think through this task"

# Test STT (record and transcribe)
uv run --script src/stt.py

# Start listener
PYTHONUNBUFFERED=1 uv run --script src/listener.py
```
