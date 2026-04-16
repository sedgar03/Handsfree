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

## Current Repo State

Handsfree is now a HUD-controlled local voice layer, not only an AirPods
launcher. The current working stack has:

- Local STT through Whisper/MLX.
- Local TTS through Kokoro or Chatterbox, selected by `tts_provider`.
- Resident daemons for summary, TTS, and phase-1 conductor chat.
- A broker CLI for service status, warmup, speech/wake toggles, queued events,
  and conductor chat.
- A SQLite event queue shared by Claude hooks, Codex notify hooks, the HUD, and
  wake-mode actions.
- Wake-word mode using OpenWakeWord with the default phrase `hey jarvis`.
- Conductor mode routing for spoken commands and terminal event speech.

The latest verified state before pausing this session:

- Unit tests: `PYTHONPATH=src uv run pytest tests/unit` -> `117 passed`.
- Runtime intentionally paused: speech and wake toggles are off, and the listener
  is stopped.
- `conductor_daemon.py` may remain warm after a pause. That is okay; stop it
  with `PYTHONPATH=src uv run python -m broker disable conductor` if needed.

The current conductor implementation is phase 1 plus some practical routing. It
is useful for local chat and voice routing, and it gets host-provided tmux pane
snapshots for context. It is not yet a full tool-executing agent harness. It
does not safely spawn, steer, or write into arbitrary tmux panes without more
confirmation and tool-work.

## Resume Checklist

```bash
# Check service/toggle state
PYTHONPATH=src uv run python -m broker status

# Warm local speech services
PYTHONPATH=src uv run python -m broker warm speech

# Warm the local conductor model
PYTHONPATH=src uv run python -m broker warm conductor --timeout 300

# Re-enable speech or wake from the CLI
PYTHONPATH=src uv run python -m broker enable speech
PYTHONPATH=src uv run python -m broker enable wake

# Start only the listener if the HUD is not managing it
./scripts/listener.sh --wake-word

# Smoke-test conductor text chat
PYTHONPATH=src uv run python -m broker conductor chat "Give me a one sentence status check."
```

For conductor-mode voice, set `interaction_mode` to `conductor` in the HUD or
in `~/.claude/voice-config.json`, then enable wake.

Good wake-mode smoke test:

```text
Hey Jarvis, what tmux panes do I have open?
```

Expected behavior: the listener logs the transcript, routes the command through
conductor mode when enabled, and answers exact tmux pane inventory questions
through the deterministic tmux snapshot formatter instead of asking the small
local model to guess.

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

# 2a) Start a handsfree Claude session with AirPods controls
./scripts/handsfree.sh --media-key

# 2b) Or start only the listener, for use with handsfree-hud
./scripts/listener.sh --media-key

# 2c) Or avoid AirPods stem clicks and use wake phrase mode
./scripts/listener.sh --wake-word

# 2d) Launch the integrated usage + handsfree control HUD
uv run --extra hud handsfree-hud
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

See `docs/HUD_QUEUE_WORKFLOW.md` for:

- shared HUD toggle files for speech and wake mode
- the SQLite event queue contract
- tmux pane routing for spoken responses
- Codex notify integration notes

See `docs/HUD_SETTINGS_PANEL_SPEC.md` for:

- the HUD settings drawer and top-bar controls
- speech, wake, TTS voice, and conductor mode controls
- the copied-in `model_usage_hud/` app boundary

See `docs/CONDUCTOR_MODE_SPEC.md` for:

- the conductor/orchestrator design
- local model and tool-harness plans
- phase breakdown for tmux orchestration and escalation

See `docs/PAUSE_HANDOFF.md` for:

- current pause/resume state
- known AirPods and wake phrase issues
- commands to restart or stop the listener safely
- verification status from the last work session

## Useful Commands

```bash
# Permission check only
./scripts/handsfree.sh --check

# Listener only; does not open Claude or change speech/wake toggles
./scripts/listener.sh --media-key

# Wake phrase listener; arm/disarm with the HUD wake button
./scripts/listener.sh --wake-word

# Full service status
PYTHONPATH=src uv run python -m broker status

# Warm resident daemons
PYTHONPATH=src uv run python -m broker warm speech
PYTHONPATH=src uv run python -m broker warm conductor --timeout 300

# Enable/disable HUD-controlled speech and wake toggles
PYTHONPATH=src uv run python -m broker enable speech
PYTHONPATH=src uv run python -m broker enable wake
PYTHONPATH=src uv run python -m broker disable speech
PYTHONPATH=src uv run python -m broker disable wake

# Stop conductor daemon
PYTHONPATH=src uv run python -m broker disable conductor

# Talk to the phase-1 local conductor
PYTHONPATH=src uv run python -m broker conductor chat "Help me think through the next step"
PYTHONPATH=src uv run python -m broker conductor reset

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

# Inspect queued agent events
PYTHONPATH=src uv run python -m broker list
PYTHONPATH=src uv run python -m broker list --current

# Usage HUD from this repo
uv run --extra hud handsfree-hud
uv run usage-hud --help
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
  "summary_backend": "mlx",
  "summary_model_backend": "auto",
  "summary_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
  "interaction_mode": "off",
  "last_interaction_mode": "direct",
  "conductor_backend": "auto",
  "conductor_model": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
  "conductor_temperature": 0.3,
  "conductor_max_tokens": 180,
  "conductor_llama_port": 8091,
  "conductor_llama_ctx_size": 8192,
  "conductor_llama_gpu_layers": "auto",
  "tts_provider": "chatterbox",
  "chatterbox_voice": "default",
  "chatterbox_device": "cpu",
  "chatterbox_style": "auto",
  "chatterbox_style_strength": 0.35,
  "chatterbox_temperature": 0.8,
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
HANDSFREE_CONDUCTOR_MODEL=models/supergemma4-26b-uncensored-gguf-v2 \
  HANDSFREE_CONDUCTOR_BACKEND=llama.cpp \
  HANDSFREE_SUMMARY_MODEL=models/supergemma4-26b-uncensored-gguf-v2 \
  HANDSFREE_SUMMARY_MODEL_BACKEND=llama.cpp \
  PYTHONPATH=src uv run python -m broker warm conductor --timeout 300
```

`summary_model_backend: "auto"` and `conductor_backend: "auto"` use MLX for
normal MLX/Hugging Face model IDs and Homebrew `llama-server` for a local
`.gguf` file or a directory containing one `.gguf` file.

```bash
export HANDSFREE_VOICE="af_heart:0.7,af_nicole:0.3"
./scripts/handsfree.sh --media-key
```

You can use different `HANDSFREE_VOICE` values in different terminals for quick A/B testing.

Summary options:

- `summary_backend: "mlx"`: default resident local summarizer with deterministic fallback
- `summary_backend: "local"`: deterministic only, no model process
- `summary_backend: "claude"`: legacy `claude -p` summarizer
- `verbosity: "expanded"`: fuller document/research readouts; `detailed` remains the normal spoken update
- `summary_model_backend: "auto"`: use MLX for MLX/Hugging Face model IDs and llama.cpp for local GGUF
- Per-terminal override: `export HANDSFREE_SUMMARY_BACKEND=local`

Interaction and TTS options:

- `interaction_mode: "off"`: HUD/conductor routing is off; a manually started listener can still use its direct path.
- `interaction_mode: "direct"`: spoken input goes to the direct listener path.
- `interaction_mode: "on_demand"`: wake/STT can read queued terminal events when asked.
- `interaction_mode: "conductor"`: wake/STT routes freeform speech through the local conductor before TTS.
- `tts_provider: "kokoro"`: fast local Kokoro voices, controlled by `kokoro_voice` and `kokoro_speed`.
- `tts_provider: "chatterbox"`: expressive Chatterbox voice clone path, currently safest on CPU.
- `chatterbox_style: "auto"`: lets existing Chatterbox tags pass through and can layer tags based on text.
- `chatterbox_style_strength`: emotional tag budget/load, `0.0` to `1.0`.
- `chatterbox_temperature`: generation variability; lower values are usually steadier.

Warm/status commands:

```bash
PYTHONPATH=src uv run python -m broker status
PYTHONPATH=src uv run python -m broker warm speech
PYTHONPATH=src uv run python -m broker enable speech
PYTHONPATH=src uv run python -m broker enable wake
```

## Project Layout

```text
scripts/
  setup.sh            # one-time setup
  handsfree.sh        # launch handsfree Claude session
  listener.sh         # foreground listener only for HUD-driven workflows
hooks/
  handsfree_hook.py   # Claude hook: summarize + speak
  codex_notify.py     # Codex notify bridge into the shared queue
  install.py          # add/remove hooks in Claude settings
src/
  listener.py         # unified input listener
  summary_daemon.py   # resident local summarizer, MLX or GGUF via llama.cpp
  tts_daemon.py       # resident Kokoro/macOS speech daemon
  conductor_daemon.py # resident local LLM conductor daemon
  conductor_client.py # socket client for conductor chat/reset
  media_key_listener.py
  openwakeword_listener.py
  wake_phrase_listener.py
  broker.py           # CLI for queued events
  event_queue.py      # durable SQLite event queue
  queue_actions.py    # read/respond queue actions
  tmux_target.py      # workflow labeling + targeted tmux paste
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
