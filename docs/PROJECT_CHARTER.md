# Project Charter — Handsfree

## Vision

Walk away from your desk with AirPods and stay in the loop while Claude Code works. Claude summarizes what it's doing, speaks when it needs input, and you tap your AirPod stem (or hit a hotkey) to talk back. Fully local — no paid APIs, no cloud TTS/STT.

## Core Hypothesis / Thesis

A lightweight local voice bridge (lightning-whisper-mlx STT + Kokoro TTS + macOS media key / hotkey input) can provide a usable hands-free Claude Code experience with <2s latency, enabling productive "walk around" coding sessions.

## Sub-goals

1. **TTS output via Claude Code hooks** — Summarize Claude's responses via `claude -p` and speak them via Kokoro TTS to AirPods
2. **STT input via AirPod stem-click or global hotkey** — Detect input trigger, capture mic, transcribe locally with Whisper, inject into Claude Code
3. **Smart summarization** — Use `claude -p` with a tuned prompt to generate concise spoken summaries at a configurable detail level
4. **Handsfree mode** — A distinct mode (`~/.claude/handsfree`) that enables voice I/O alongside (not replacing) existing AOE sound effects

## Success Criteria

| Criterion | Measurable Threshold | Status |
|---|---|---|
| TTS speaks summaries on Stop/Notification hooks | Hear spoken summary within 3s of Claude stopping | Not started |
| Summarization via `claude -p` produces useful output | Summary is 1-3 sentences, captures what happened and what's needed | Not started |
| STT captures voice and injects into Claude | Spoken command transcribed and sent to Claude within 3s | Not started |
| Both stem-click and hotkey input work | Either can trigger mic capture, user can switch between them | Not started |
| Fully local — no paid APIs | Works offline after initial model downloads (except `claude -p` for summarization) | Not started |
| Handsfree mode coexists with AOE sounds | AOE sounds still play on computer; voice goes to AirPods | Not started |

## Stakeholders & Roles

| Name/ID | Role | Responsibility |
|---|---|---|
| Steven | Leadership | Vision, gate approvals, UX feel, scope decisions |
| Lead Agent (Claude Code) | Lab | Architecture, prototyping, integration |
| Worker Agents | Crowd | Module implementation |

## Scope

### In Scope

- Claude Code hook integration (Stop, Notification, PreCompact events)
- **Handsfree mode** toggled via `~/.claude/handsfree` file (like existing `~/.claude/mute` and `~/.claude/auto` patterns)
- Local TTS via Kokoro (with macOS `say` as fallback)
- Local STT via lightning-whisper-mlx with whisper-large-v3-turbo
- Summarization via `claude -p` with a carefully tuned prompt
- Configurable verbosity levels (terse / detailed) toggled at runtime
- AirPod stem-click detection via macOS media key events (PyObjC CGEventTap)
- Global hotkey as alternative input trigger
- Switchable input mode (stem-click ↔ hotkey) via config
- TTS queue — new summaries queue behind currently-speaking audio
- Audio routing to Bluetooth (AirPods) output device
- AOE sound effects continue to work normally (handsfree mode layers on top)
- Install script that downloads models and configures hooks

### Out of Scope

- Paid TTS/STT APIs (ElevenLabs, OpenAI TTS, Google Cloud, etc.)
- Android / non-macOS support (v1 is macOS-only)
- Full duplex / always-listening mode (push-to-talk only)
- Custom voice training / voice cloning
- GUI / web interface (CLI + hooks only)
- Replacing Claude Code's text interface (this is additive)

## Handsfree Mode Design

### Activation

```bash
touch ~/.claude/handsfree    # Enable handsfree mode
rm ~/.claude/handsfree       # Disable handsfree mode
```

When `~/.claude/handsfree` exists:
- Stop/Notification/PreCompact hooks trigger voice summaries (in addition to AOE sounds)
- The stem listener / hotkey listener daemon starts (or is already running)
- TTS output routes to AirPods; AOE sounds still play on default output

When `~/.claude/handsfree` does NOT exist:
- Hooks skip all voice logic — zero overhead
- Existing AOE sound behavior unchanged

### Hook Flow (handsfree enabled)

```
Claude stops
  │
  ├──→ notify-sound.sh (AOE spawn sound → computer speakers, unchanged)
  │
  └──→ handsfree-hook.sh
        ├── Check ~/.claude/handsfree exists? No → exit
        ├── Extract assistant response from hook JSON (stdin)
        ├── claude -p "Summarize this for a spoken update: {response}"
        ├── Pass summary text to Kokoro TTS
        ├── Queue audio if TTS is already playing
        └── Play through AirPods output device
```

### Input Flow (stem-click or hotkey)

```
User taps AirPod stem / presses hotkey
  │
  ├── Listener daemon detects event
  ├── Start recording from AirPod mic
  │
User taps again / releases hotkey
  │
  ├── Stop recording
  ├── Transcribe via lightning-whisper-mlx (whisper-large-v3-turbo)
  └── Inject transcribed text into Claude Code session
```

### Input Mode Switching

Config file: `~/.claude/voice-config.json`

```json
{
  "input_mode": "stem-click",
  "verbosity": "detailed",
  "kokoro_voice": "af_heart",
  "hotkey": "F18"
}
```

- `input_mode`: `"stem-click"` | `"hotkey"` — which trigger activates mic capture
- `verbosity`: `"terse"` | `"detailed"` — summary depth (tunable, expect trial and error)
- `kokoro_voice`: which Kokoro voice to use
- `hotkey`: which key for hotkey mode (default F18 or similar unused key)

### Summarization via `claude -p`

Instead of heuristic extraction, use Claude itself to summarize:

```bash
claude -p "You are summarizing Claude Code's work for a spoken audio update to a developer
wearing AirPods who is away from their desk. Be concise (1-3 sentences). Focus on: what was
done, what needs attention, and whether Claude is waiting for input. Skip code details — the
developer will see it when they return. Here is Claude's response: {hook_json}"
```

**Verbosity levels** control the prompt:
- **terse**: "One sentence max. Just say what happened and if you need something."
- **detailed**: "2-3 sentences. Include file names and specific actions taken. Mention any errors or decisions that need input."

This adds ~1-2s latency (API call) but produces much better summaries than heuristics. The tradeoff is acceptable since the developer is walking around, not staring at the screen.

**Note**: `claude -p` uses your existing Claude plan/API credits. This is the one non-local component — everything else (TTS, STT) is fully local.

## Architecture Overview

### Phase 1: Mac speakers + built-in mic

```
┌──────────────────────────────────────────────────────────┐
│                    Claude Code CLI                        │
│                                                           │
│  Hooks (output — Claude speaks to you):                   │
│   Stop ──┬──→ notify-sound.sh (AOE sound, as-is)         │
│          └──→ handsfree_hook.py                           │
│                 ├─ claude -p "summarize..." → summary text│
│                 ├─ kokoro_tts(summary) → audio            │
│                 └─ queue + play → Mac speakers             │
│                                                           │
│   Notification ──→ same pattern (permission/idle prompts) │
│   PreCompact ──→ same pattern (wololo + voice summary)    │
│                                                           │
│  Input (you speak to Claude):                             │
│   Global hotkey (e.g. F18)                                │
│     └──→ listener daemon                                  │
│           ├─ sounddevice → built-in mic                   │
│           ├─ lightning-whisper-mlx STT                    │
│           └─ inject text → Claude Code stdin              │
└──────────────────────────────────────────────────────────┘
```

### Phase 2: AirPods (adds Bluetooth routing + stem-click)

```
  Phase 1 components, plus:
  - audio.py routes TTS output → AirPods (via CoreAudio device selection)
  - audio.py routes mic input ← AirPod mic
  - stem_listener.py detects AirPod stem tap (via CGEventTap media keys)
  - listener.py switches between hotkey and stem-click based on config
```

### Components

This is a flat repo with scripts — not a Python package. Hooks point directly to scripts via absolute paths. Iterate fast, package later.

```
src/
  tts.py             — Kokoro TTS wrapper (queue, play, device routing)
  stt.py             — lightning-whisper-mlx wrapper
  summarizer.py      — claude -p summarization with verbosity levels
  stem_listener.py   — AirPod stem-click detection (PyObjC CGEventTap)
  hotkey_listener.py — Global hotkey detection
  listener.py        — Unified input listener (switches stem/hotkey based on config)
  audio.py           — Audio device discovery + routing (AirPods detection)
  config.py          — Read/write ~/.claude/voice-config.json
  queue.py           — TTS audio queue (FIFO, non-blocking)
hooks/
  handsfree_hook.py  — Main hook script (reads stdin JSON, summarizes, speaks)
  install.py         — Adds/removes hook entries in Claude Code settings.json
scripts/
  download_models.py — Downloads Kokoro + Whisper models
  setup.sh           — One-command setup (deps + models + hooks)
models/              — Downloaded models live here (gitignored)
```

### How hooks connect to the repo

The install script adds entries to `~/dotfiles/claude/settings.json` with absolute paths:

```json
{
  "type": "command",
  "command": "/Users/steven_edgar/Code/Handsfree/hooks/handsfree_hook.py",
  "async": true
}
```

Each hook script uses a shebang with `uv run` to manage its own deps inline:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["kokoro-onnx"]
# ///
```

This way: no venv activation needed, no package install, hooks just work. `uv` handles deps on first run and caches them.

### What lives outside the repo

Only lightweight toggle/config files:
- `~/.claude/handsfree` — mode toggle (touch/rm)
- `~/.claude/voice-config.json` — verbosity, input mode, voice selection
- Hook entries in `~/dotfiles/claude/settings.json` — installed by `scripts/setup.sh`

### Future: packaging

Once the MVP is proven, package as `uv tool install handsfree`. Hooks would reference `handsfree-hook` on PATH instead of absolute paths. But that's a later concern.

## Tech Stack

| Component | Tool | Why |
|---|---|---|
| TTS | Kokoro via kokoro-onnx | 82M params, sub-200ms, best quality/speed ratio, Apache 2.0 |
| TTS fallback | macOS `say` | Zero-setup instant fallback |
| STT | lightning-whisper-mlx + whisper-large-v3-turbo | 10x faster than whisper.cpp on Apple Silicon, purpose-built for M-series |
| Summarization | `claude -p` (Claude Code print mode) | Best summary quality, uses existing Claude plan, ~1-2s latency |
| Media keys | PyObjC CGEventTap | Native macOS media key detection for AirPod stem clicks |
| Global hotkey | PyObjC CGEventTap (same lib) | Same event tap can detect keyboard shortcuts |
| Audio capture | sounddevice | Low-level device selection, works with Bluetooth mic |
| Audio playback | sounddevice or afplay | Route to specific output device (AirPods) |
| Config | JSON file (~/.claude/voice-config.json) | Simple, human-editable, consistent with Claude Code patterns |
| Language | Python 3.11+ with uv | Fast installs, single-file scripts for hooks |

### Alternative considered: mlx-audio

[mlx-audio](https://github.com/Blaizzy/mlx-audio) (5.9k stars) bundles both Kokoro TTS and Whisper STT in one Apple Silicon-optimized package. Could simplify dependencies. Worth evaluating at G1 — if it works well, we could use it as the single audio dependency instead of separate kokoro-onnx + lightning-whisper-mlx.

## Milestones

Build in layers — prove each piece works on default Mac audio before adding Bluetooth complexity.

### Phase 1: Mac speakers + built-in mic (prove the loop)

| Milestone | Gate | Deliverables |
|---|---|---|
| Project kickoff | G0 | Charter approved, architecture defined |
| TTS on Mac speakers | G1 | Hook → `claude -p` summarize → Kokoro → Mac speakers |
| STT from Mac mic | G2 | Global hotkey → built-in mic → Whisper → text output |
| Full loop on Mac | G3 | Claude speaks through speakers, you talk back via hotkey + mic |

### Phase 2: AirPods (add Bluetooth routing)

| Milestone | Gate | Deliverables |
|---|---|---|
| Audio routing to AirPods | G4 | TTS output routes to AirPods, mic captures from AirPod mic |
| Stem-click detection | G5 | AirPod stem tap triggers recording (alternative to hotkey) |
| Polish and install script | G6 | One-command setup, README, verbosity tuning, edge cases |

## Risk Register

### Phase 1 risks (Mac-native)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `claude -p` summarization latency too high | Medium | Medium | Pre-format hook JSON to minimize tokens; use haiku model flag if available; fall back to heuristic extraction |
| Kokoro TTS latency too high on CPU | Low | High | Pre-warm model; macOS `say` as instant fallback; test on M-series |
| Whisper accuracy poor for code terms | Medium | Medium | whisper-large-v3-turbo has good vocabulary; add initial_prompt with common terms |
| Hook JSON structure changes across Claude Code versions | Low | Medium | Defensive parsing; extract just the text content field |
| TTS queue grows too long during rapid Claude activity | Low | Low | Max queue depth (e.g., 3); drop oldest if exceeded |
| `claude -p` costs add up | Low | Low | Summarization uses small token counts; haiku-tier if possible |

### Phase 2 risks (AirPods — deferred)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AirPod stem-click detection unreliable | Medium | High | Global hotkey remains available as fallback |
| Audio routing to AirPods flaky | Medium | Medium | Use CoreAudio APIs to explicitly enumerate and select Bluetooth device |

## Open Questions (Resolved)

1. ~~Stem click vs. global hotkey~~ → **Both, switchable via config**
2. **Kokoro voice selection** — Need to audition voices. `af_heart` is a good starting point.
3. ~~Summarization depth~~ → **Detailed by default, toggleable (terse/detailed) via config. Expect iteration.**
4. ~~Queue behavior~~ → **Queue up. FIFO. Max depth 3, drop oldest.**
5. ~~Existing hook integration~~ → **Layer on top. AOE sounds unchanged. Handsfree is a separate mode.**

## Remaining Open Questions

1. **Kokoro voice selection** — Which voice sounds best for technical summaries? Need to audition.
2. **`claude -p` model selection** — Can we specify haiku for cheaper/faster summaries? Need to test flags.
3. **Injecting STT text into Claude Code** — What's the best mechanism? Write to stdin fd? Named pipe? Prompt queue?
4. **Listener daemon lifecycle** — Should it run as a launchd service? Background process started by the hook? Separate terminal?
