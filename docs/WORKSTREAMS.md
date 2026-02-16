# Workstreams

> Tracks parallel lines of work, their owners, and current status. Update when starting, pausing, or completing a workstream.

---

## Active Workstreams

| ID | Workstream | Owner | Status | Branch | Last Updated |
|---|---|---|---|---|---|
| W01 | Project Setup | `human-1` | Complete | `main` | 2026-02-15 |
| W02 | TTS Output Pipeline | `lead-agent` | Complete | `main` | 2026-02-15 |
| W03 | STT Input Pipeline | `lead-agent` | Complete | `main` | 2026-02-15 |

### Status Values
- **Not Started** — Defined but no work begun
- **In Progress** — Actively being worked on
- **Blocked** — Waiting on dependency or decision
- **Paused** — Temporarily deprioritized
- **Complete** — Delivered and reviewed

---

## Workstream Details

### W01 — Project Setup
- **Goal:** Complete initial project setup: charter, architecture, tooling.
- **Key Tasks:** T000
- **Notes:** Bootstrap workstream. Charter and architecture approved.

### W02 — TTS Output Pipeline
- **Goal:** Claude Code hooks → summarize via claude -p → speak via Kokoro TTS through Mac speakers.
- **Key Tasks:** T003, T004, T005, T006, T007
- **Notes:** Phase 1 output side complete. Config, TTS, summarizer, hook, and setup all implemented. Ready for end-to-end testing after `./scripts/setup.sh`.

### W03 — STT Input Pipeline
- **Goal:** Global hotkey → mic capture → Whisper transcription → text injection into Claude Code.
- **Key Tasks:** T010, T011, T012
- **Notes:** Complete. Uses mlx-whisper with whisper-large-v3-turbo. Fixed ffmpeg dep by passing numpy arrays directly. Needs Accessibility permission for hotkey listener.

---

## Completed Workstreams

| ID | Workstream | Completed | Outcome |
|---|---|---|---|
| W01 | Project Setup | 2026-02-15 | Charter, architecture, and project scaffold complete |
| W02 | TTS Output Pipeline | 2026-02-15 | 5 files: config.py, tts.py, summarizer.py, handsfree_hook.py, install.py + setup.sh |
| W03 | STT Input Pipeline | 2026-02-15 | 3 files: stt.py, hotkey_listener.py, listener.py |
