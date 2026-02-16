# Handoff — Living Session State

> This file is updated at the end of every work session. It is the primary mechanism for continuity between sessions and agents.

## Last Updated
- **Date:** 2026-02-16
- **By:** codex-1

## Current State

Phase 1 is fully implemented — both output (TTS) and input (STT) sides. All 9 files are written and tested. Setup has been run: uv installed, Kokoro models downloaded (~380MB), whisper model cached (~800MB from HF), hooks installed in settings.json. TTS speaks through Mac speakers. STT records from built-in mic and transcribes via mlx-whisper. Hotkey listener and text injection ready but need interactive testing (requires Accessibility permission for CGEventTap).

## What Was Done (This Session)

**Output side (Steps 1-5):**
- Created `src/config.py` — config reader with get_config() and is_handsfree_enabled()
- Created `src/tts.py` — Kokoro TTS wrapper with speak(), macOS say fallback, file lock
- Created `src/summarizer.py` — claude -p summarizer with terse/detailed modes
- Created `hooks/handsfree_hook.py` — main Claude Code hook (stdin JSON → transcript → summarize → speak)
- Created `hooks/install.py` — idempotent hook installer for settings.json
- Created `scripts/setup.sh` — one-command setup (models, config, hooks, test)

**Input side (Steps 6-8):**
- Created `src/stt.py` — mlx-whisper STT (record + transcribe, passes numpy array directly to avoid ffmpeg dep)
- Created `src/hotkey_listener.py` — PyObjC CGEventTap for F18 hold-to-record
- Created `src/listener.py` — unified listener with clipboard + osascript text injection

**Testing:**
- `setup.sh` ran successfully (uv, models, hooks, TTS test)
- TTS speaks through Mac speakers (Kokoro TTS working)
- Hook end-to-end test passed (fake transcript → summarize → speak)
- STT recorded and transcribed audio (ambient noise → "Yeah. Yeah. Yeah.")
- Fixed: stt.py passes numpy array directly to mlx_whisper (avoids ffmpeg dependency)
- Fixed: install.py matcher-aware dedup for Notification hooks
- Fixed: added `from __future__ import annotations` to all files for Python 3.9 compat

**Docs:**
- Updated TASKS.md, WORKSTREAMS.md, DECISION_LOG.md

## Next Steps

1. **Interactive test of hotkey listener** — `uv run src/hotkey_listener.py` (needs Accessibility permission)
2. **Live test** — `touch ~/.claude/handsfree` → use Claude Code → hear summaries → press F18 → speak back
3. Tune summarization prompts based on real output quality
4. Tune Kokoro voice selection (audition alternatives to af_heart)

## Blockers

- Hotkey listener needs macOS Accessibility permission for the terminal app

## Open Questions

- Which Kokoro voice sounds best for technical summaries? Need to audition alternatives to af_heart.
- Can `claude -p` use a faster/cheaper model (haiku)? Need to test `--model` flag.
- Is the clipboard + osascript text injection reliable enough, or should we explore named pipes / claude-commander?

## Session Update (2026-02-16, codex-1)

- Updated `src/media_key_listener.py` to use layered media-command backends:
  - CGEventTap (session + annotated session)
  - AppKit `NSEvent` global monitor (`NSEventMaskSystemDefined`)
  - MediaPlayer `MPRemoteCommandCenter` fallback (toggle/play/next/previous)
- Added explicit listen-event permission preflight/request (`CGPreflightListenEventAccess`, `CGRequestListenEventAccess`) and clearer guidance for both Accessibility + Input Monitoring.
- Updated `src/diagnose_events.py` to log all four backends above and print decoded `subtype/data1/keycode/state` for stem clicks.
- Added `pyobjc-framework-MediaPlayer` to inline uv dependencies in `src/media_key_listener.py`, `src/diagnose_events.py`, and `src/listener.py`.
- Local validation completed: syntax check via `python3 -m py_compile` for modified scripts. Runtime validation of PyObjC backends must be performed on a machine with network-enabled uv dependency resolution and macOS permissions granted.

## Session Update (2026-02-16, codex-1 follow-up)

- Switched `src/media_key_listener.py` primary backend to `MPRemoteCommandCenter` via `objc.loadBundle` with a silent `sounddevice` output keepalive so AirPods stem commands route to the CLI process on macOS 16.
- Added `src/test_mpremote.py` live test path (target/action handlers) to verify single/double/triple stem clicks.
- Hardened submit behavior in `src/listener.py`:
  - multiple Enter delivery strategies (`key code 36`, `keystroke return`, ASCII 13)
  - slight timing delay before Enter
- Added event fallback logic in `src/media_key_listener.py` for inconsistent remote-command delivery (e.g., pause/play-only patterns).
- Implemented fully handsfree mode:
  - new config key `auto_submit_after_transcription` (default `true`) in `src/config.py`
  - single click → speak → silence/manual stop → transcribe → auto-send (no second click required)
- Adjusted audio cues:
  - chime now indicates recording stopped / no longer listening
  - whoosh still indicates submit/send
- Live validation performed with AirPods:
  - successful transcription injection
  - successful auto-submit/Enter and message send in conversation.

## Session Update (2026-02-16, codex-1 docs hardening)

- Rewrote `README.md` to reflect current AirPods-capable flow and point users to a single operations guide.
- Added `docs/HANDSFREE_USER_GUIDE.md` with:
  - install + launch workflow
  - explicit macOS permission checklist (Microphone, Accessibility, Input Monitoring, Automation/System Events)
  - configuration reference
  - diagnostics and troubleshooting commands
- Updated `scripts/setup.sh` default config to align with current behavior:
  - `input_mode: media_key`
  - `auto_submit: true`
  - `auto_submit_after_transcription: true`
  - `silence_timeout: 2.5`
- Updated `scripts/handsfree.sh` startup messaging to reflect auto-submit-after-transcription mode when enabled.

## Session Update (2026-02-16, codex-1 permission checks)

- Added `scripts/check_permissions.py` (uv script) to validate:
  - Microphone access (sounddevice input stream open)
  - Accessibility trust (`AXIsProcessTrusted`)
  - Input Monitoring listen access (`CGPreflightListenEventAccess`)
  - Automation to `System Events` (AppleScript probe)
- Added `scripts/check_permissions.sh` wrapper as the user-facing permission check command.
- Integrated checks into `scripts/handsfree.sh` startup:
  - checks run automatically before launching session
  - `--check` runs checks only and exits
  - `--skip-checks` bypasses checks
- Updated user-facing docs (`README.md`, `docs/HANDSFREE_USER_GUIDE.md`, `scripts/setup.sh`) to include the new check-first workflow.

## Session Update (2026-02-16, codex-1 voice docs)

- Documented Kokoro voice blending and per-terminal voice overrides.
- Updated `README.md` and `docs/HANDSFREE_USER_GUIDE.md` with:
  - blend syntax (e.g. `af_heart:0.7,af_nicole:0.3`)
  - `voice_presets` usage
  - `HANDSFREE_VOICE` env-var override examples
  - `unset HANDSFREE_VOICE` reset flow
- Updated `scripts/setup.sh` default config template to include `voice_presets` and `kokoro_speed`.

## Session Update (2026-02-16, codex-1 portability + installability)

- Made scripts portable for other machines/users by removing hardcoded local paths:
  - replaced user-specific `uv` shebangs with `#!/usr/bin/env -S uv run --script`
  - updated launch wrappers to resolve `uv` and `claude` via `PATH` (with env overrides)
  - added `HANDSFREE_CLAUDE_BIN` fallback support in `src/summarizer.py`
- Hardened hook installation for varied Claude setups:
  - `hooks/install.py` now supports `--settings`
  - supports `CLAUDE_SETTINGS_PATH` environment override
  - auto-detects `~/.claude/settings.json` and `~/dotfiles/claude/settings.json`
- Added `docs/CLAUDE_HOOKS_SETUP.md` with:
  - exact hook events and JSON shape
  - copy/paste install/uninstall/verify commands
  - agent-friendly instructions for Codex/Claude to apply config changes directly
- Updated user docs (`README.md`, `docs/HANDSFREE_USER_GUIDE.md`, `scripts/README.md`) to link and use the new hook setup guidance.
