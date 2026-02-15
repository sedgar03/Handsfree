# Project Charter — ClaudeVoice

## Vision

Walk away from your desk with AirPods and stay in the loop while Claude Code works. Claude summarizes what it's doing, speaks when it needs input, and you tap your AirPod stem to talk back. Fully local — no paid APIs, no cloud TTS/STT.

## Core Hypothesis / Thesis

A lightweight local voice bridge (Whisper STT + Kokoro TTS + macOS media key detection) can provide a usable hands-free Claude Code experience with <2s latency, enabling productive "walk around" coding sessions.

## Sub-goals

1. **TTS output via Claude Code hooks** — Summarize Claude's responses into short spoken updates via local Kokoro TTS, routed to AirPods
2. **STT input via AirPod stem-click** — Detect stem tap/hold via macOS media key events, capture mic audio, transcribe locally with Whisper, inject into Claude Code
3. **Smart summarization** — Don't read code verbatim. Summarize what Claude did, what it needs, and what's next into 1-2 spoken sentences
4. **Seamless toggle** — Easy on/off so it doesn't interfere with normal desk work

## Success Criteria

| Criterion | Measurable Threshold | Status |
|---|---|---|
| TTS speaks summaries on Stop/Notification hooks | Hear spoken summary within 2s of Claude stopping | Not started |
| STT captures voice and injects into Claude | Spoken command transcribed and sent to Claude within 3s | Not started |
| AirPod stem-click triggers mic capture | Media key event detected, mic recording starts/stops | Not started |
| Fully local — no paid APIs | Works offline after initial model downloads | Not started |
| Summarization quality | Summaries are useful, not just truncated text | Not started |

## Stakeholders & Roles

| Name/ID | Role | Responsibility |
|---|---|---|
| Steven | Leadership | Vision, gate approvals, UX feel, scope decisions |
| Lead Agent (Claude Code) | Lab | Architecture, prototyping, integration |
| Worker Agents | Crowd | Module implementation |

## Scope

### In Scope

- Claude Code hook integration (Stop, Notification, PreCompact events)
- Local TTS via Kokoro (with macOS `say` as fallback)
- Local STT via Whisper (whisper.cpp or faster-whisper)
- AirPod stem-click detection via macOS media key events
- Smart summarization of Claude's output (extract key info, skip code blocks)
- Audio routing to Bluetooth (AirPods) output device
- Mute/unmute toggle file (`~/.claude/voice-mute`) consistent with existing mute pattern
- Install script that downloads models and configures hooks

### Out of Scope

- Paid TTS/STT APIs (ElevenLabs, OpenAI TTS, Google Cloud, etc.)
- Android / non-macOS support (v1 is macOS-only)
- Full duplex / always-listening mode (stem-click push-to-talk only)
- Custom voice training / voice cloning
- GUI / web interface (CLI + hooks only)
- Replacing Claude Code's text interface (this is additive)

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Claude Code CLI                     │
│                                                      │
│  Hooks (output — Claude speaks to you):              │
│   Stop ──────→ summarize ──→ kokoro_tts ──→ AirPods │
│   Notification ──→ notify ──→ kokoro_tts ──→ AirPods │
│   PreCompact ──→ compact ──→ kokoro_tts ──→ AirPods │
│                                                      │
│  Input (you speak to Claude):                        │
│   AirPod stem ──→ media_key_listener ──→ mic_capture │
│                  ──→ whisper_stt ──→ Claude stdin     │
└─────────────────────────────────────────────────────┘

Components:
  1. summarizer     — Extracts key info from Claude hook JSON
  2. tts_engine     — Kokoro TTS wrapper (fallback: macOS say)
  3. stt_engine     — Whisper wrapper (faster-whisper)
  4. stem_listener  — macOS media key event tap (PyObjC)
  5. audio_router   — Ensures output→AirPods, input←AirPod mic
  6. hook_scripts   — Shell/Python scripts wired into Claude Code hooks
```

## Tech Stack (Proposed)

| Component | Tool | Why |
|---|---|---|
| TTS | Kokoro (kokoro-onnx) | Free, local, high quality, fast ONNX runtime |
| TTS fallback | macOS `say` | Zero-setup, instant, always available |
| STT | faster-whisper | CTranslate2 backend, fast on CPU, good accuracy |
| Media keys | PyObjC CGEventTap | Detect AirPod stem clicks natively on macOS |
| Audio capture | sounddevice | Low-level control over device selection |
| Summarization | Heuristic extraction from hook JSON | No LLM needed — structured data is already there |
| Language | Python 3.11+ with uv | Fast installs, matches Claude Code hook patterns |

### Summarization Strategy

The Stop hook receives JSON with the assistant's full response. Rather than calling an LLM:

1. **Extract from hook JSON** — tool names used, files modified, errors encountered
2. **First/last sentence** of assistant text (skip code blocks)
3. **Template-based** — "Claude [edited/created/searched] [N files]. [Waiting for input / Done.]"

This keeps latency low and avoids requiring a second model.

## Milestones

| Milestone | Gate | Deliverables |
|---|---|---|
| Project kickoff | G0 | Charter approved, architecture defined, models selected |
| TTS pipeline working | G1 | Hook → summarize → Kokoro → AirPods plays audio |
| STT pipeline working | G2 | Stem click → mic → Whisper → text output |
| Full loop integration | G3 | Claude speaks, user responds, Claude hears |
| Polish and install script | G4 | One-command setup, README, edge cases handled |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AirPod stem-click detection unreliable | Medium | High | Fall back to global hotkey (e.g., double-tap Fn) |
| Kokoro TTS latency too high on CPU | Low | High | Pre-warm model; macOS `say` as instant fallback |
| Whisper accuracy poor for code terms | Medium | Medium | Use whisper-large-v3; custom vocabulary prompt |
| Audio routing to AirPods flaky | Medium | Medium | Use SwitchAudioSource or CoreAudio APIs |
| Hook JSON structure changes across Claude Code versions | Low | Medium | Defensive parsing with fallbacks |

## Open Questions

1. **Stem click vs. global hotkey** — Support both? Stem click is walking-friendly but harder to implement.
2. **Kokoro voice selection** — Which voice sounds best for technical summaries?
3. **Summarization depth** — "Done editing 3 files" vs. "Updated auth.py, added login route, fixed test"?
4. **Queue behavior** — If Claude finishes while TTS is still speaking, queue / interrupt / skip?
5. **Existing hook integration** — Replace current sound hooks with voice, or layer on top?
