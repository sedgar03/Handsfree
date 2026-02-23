# Source Code — Module Map

> This file maps source code modules to their responsibilities.

## Module Map

| Module | Purpose |
|---|---|
| `config.py` | Read `~/.claude/voice-config.json` with defaults, check handsfree toggle |
| `tts.py` | Kokoro TTS wrapper — `speak()`, lazy model init, macOS `say` fallback, file lock serialization |
| `stt.py` | mlx-whisper STT wrapper — record from mic via sounddevice, transcribe audio |
| `summarizer.py` | Summarize Claude output via `claude -p` with terse/detailed prompts |
| `listener.py` | Unified input listener — routes to media_key or hotkey mode, handles text injection and question/permission answering |
| `media_key_listener.py` | AirPods stem-click detection via MPRemoteCommandCenter + CGEventTap fallback, VAD auto-stop, recording state machine |
| `hotkey_listener.py` | Global hotkey detection via PyObjC CGEventTap (F18 hold-to-record) |
| `audio.py` | Audio device discovery and routing (AirPods detection via CoreAudio) |
| `airpods_check.py` | Check if AirPods are connected and print status |
| `diagnose_events.py` | Diagnostic tool — logs all media key backends and decoded event data |
| `test_mpremote.py` | Live test for MPRemoteCommandCenter stem-click callbacks |
| `test_mpremote_inputstream.py` | Test whether MPRemote callbacks drop during active `sd.InputStream` |

## Getting Started

```bash
# Run setup (downloads models, installs hooks, creates config)
./scripts/setup.sh

# Test TTS
uv run src/tts.py "Hello from Handsfree"

# Test STT (record and transcribe)
uv run src/stt.py

# Start listener
PYTHONUNBUFFERED=1 uv run --script src/listener.py
```
