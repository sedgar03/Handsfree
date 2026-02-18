# Task Tracker

## Pending

### T013: Voice Command Intercept Layer
- **Priority:** High
- **Role:** Architect — design the command dispatcher
- **Mode:** Cyborg
- **Agent Type:** Claude Code (interactive design)
- **Description:** Add a voice command dispatcher that intercepts transcribed text BEFORE it gets pasted into Claude Code. When the user says a recognized command, handle it locally instead of forwarding to the terminal. This sits in `listener.py` and `auto_listen.py` between transcription and `inject_text()`.
- **Acceptance Criteria:**
  - [ ] `src/voice_commands.py` — registry of command handlers
  - [ ] Commands are checked after transcription, before injection
  - [ ] If a command matches, it runs locally and does NOT inject into Claude Code
  - [ ] If no command matches, normal inject_text flow continues
  - [ ] Commands are case-insensitive and tolerate minor Whisper mishearings

### T014: "Repeat" Voice Command
- **Priority:** High
- **Role:** Developer
- **Mode:** Centaur
- **Agent Type:** Codex
- **Dependencies:** T013
- **Description:** If the only word transcribed is "repeat" (or close to it), replay the last TTS output. Requires caching the last spoken text/audio. TTS cache lives at `/tmp/handsfree-last-tts.txt` (written by tts.py on each speak).
- **Acceptance Criteria:**
  - [ ] `tts.py` writes last spoken text to `/tmp/handsfree-last-tts.txt`
  - [ ] "Repeat" command reads the cache and calls `tts.speak()` again
  - [ ] Tolerates "repeat", "Repeat", "repeat that", "say that again"

### T015: "Action Item" Voice Command
- **Priority:** High
- **Role:** Developer
- **Mode:** Centaur
- **Agent Type:** Codex
- **Dependencies:** T013
- **Description:** If transcribed text starts with "action item" (prefix), extract the rest as the todo text and append it to a configurable todo list file instead of sending to Claude Code. Calls a user-configurable script or appends directly.
- **Acceptance Criteria:**
  - [ ] "Action item buy groceries" → appends "buy groceries" to todo file
  - [ ] Todo file path configurable in voice-config.json (default: `~/todo.md`)
  - [ ] Optional: call a user script instead (`action_item_script` in config)
  - [ ] Speaks confirmation: "Added: buy groceries"
  - [ ] Tolerates "action item", "add action item", "to do"

### T016: Voice Command Config & Extensibility
- **Priority:** Medium
- **Role:** Developer
- **Mode:** Centaur
- **Agent Type:** Codex
- **Dependencies:** T013
- **Description:** Make voice commands configurable. Users can define custom prefix commands in `~/.claude/voice-config.json` that map to shell scripts.
- **Acceptance Criteria:**
  - [ ] Config key `voice_commands` with prefix → script mappings
  - [ ] Example: `"remind me": "~/scripts/add-reminder.sh"`
  - [ ] Built-in commands (repeat, action item) work without config
  - [ ] Custom commands pass remaining text as $1 to the script

### T017: Live Integration Test — Full Handsfree Loop
- **Priority:** High
- **Role:** Tester
- **Mode:** Cyborg
- **Agent Type:** Claude Code (interactive)
- **Description:** End-to-end test of the handsfree loop: enable mode → Claude speaks summaries → user responds via voice → text appears in terminal. Requires Accessibility + Input Monitoring permissions granted.
- **Acceptance Criteria:**
  - [ ] `touch ~/.claude/handsfree` enables TTS on Claude output
  - [ ] TTS speaks through Mac speakers (or AirPods if connected)
  - [ ] Listener captures mic input and transcribes
  - [ ] Transcribed text appears in Claude Code input
  - [ ] Round-trip latency under 3 seconds

---

## In Progress

## Completed

### T020: Debug Stem-Click-to-Stop During Recording
- **Completed:** 2026-02-18
- **Outcome:** Added per-event remote-command diagnostics in `src/media_key_listener.py`, added `src/test_mpremote_inputstream.py` to verify MPRemote callbacks with and without an active `sd.InputStream`, and enabled automatic parallel legacy fallback backends (AppKit + CGEventTap when permission allows) so stem-click stop still works when MPRemote delivery drops during recording.

### T019: Full Test Coverage
- **Completed:** 2026-02-18
- **Outcome:** Added comprehensive unit/integration coverage for hook extraction, config, summarizer, TTS, STT, VAD, and listener/hook pipelines using mocked dependencies and no hardware requirements. Test command now runs as `uv run pytest tests/` and passes.

### T003: Implement src/config.py — config reader
- **Completed:** 2026-02-15
- **Outcome:** Config reader with get_config() and is_handsfree_enabled(). Reads ~/.claude/voice-config.json with defaults.

### T004: Implement src/tts.py — Kokoro TTS wrapper
- **Completed:** 2026-02-15
- **Outcome:** Kokoro TTS with speak(), lazy init, macOS say fallback, file lock serialization.

### T005: Implement src/summarizer.py — claude -p wrapper
- **Completed:** 2026-02-15
- **Outcome:** summarize() calling claude -p with terse/detailed prompts. Stdin and argv support.

### T006: Implement hooks/handsfree_hook.py — main hook
- **Completed:** 2026-02-15
- **Outcome:** Reads stdin JSON, extracts transcript_path, finds last assistant message from JSONL, summarizes, speaks. Zero overhead when disabled.

### T007: Implement hooks/install.py + scripts/setup.sh
- **Completed:** 2026-02-15
- **Outcome:** Idempotent hook installer for settings.json. Setup script downloads Kokoro models, creates config, installs hooks, runs TTS test.

### T010: Implement src/stt.py — Whisper STT wrapper
- **Completed:** 2026-02-15
- **Outcome:** Record from mic via sounddevice, transcribe via mlx-whisper (whisper-large-v3-turbo). Passes numpy array directly to avoid ffmpeg dependency. Tested successfully.

### T011: Implement src/hotkey_listener.py — Global hotkey
- **Completed:** 2026-02-15
- **Outcome:** PyObjC CGEventTap for F18 hold-to-record. Streams audio while held, transcribes on release. Configurable hotkey from config. Needs Accessibility permission for interactive testing.

### T012: Implement src/listener.py — Full loop with text injection
- **Completed:** 2026-02-15
- **Outcome:** Unified listener with clipboard + osascript paste injection. User sees pasted text and presses Enter manually for safety.
