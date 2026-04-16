# Pause Handoff

Updated: 2026-04-15

This note captures the current Handsfree/HUD/conductor state and the next steps
from the current local conductor toward a Hermes-style tool harness.

## Current State

- Speech is off: `~/.handsfree/speech-enabled` is absent.
- Wake is off: `~/.handsfree/wake-enabled` is absent.
- The listener is stopped.
- The summary LLM daemon is stopped.
- The TTS daemon is stopped.
- The conductor daemon is stopped.
- Current TTS provider in config is Kokoro.
- Current local LLM config is Qwen 2B through MLX.
- OpenWakeWord is configured with `hey jarvis` and `hey rhasspy`.

Verify:

```bash
cd /Users/stevenedgar/Code/handsfree
PYTHONPATH=src uv run python -m broker status
```

Expected when fully paused: `speech_enabled: false`, `wake_enabled: false`, and
`summary`, `tts`, `conductor`, and `listener` all stopped.

## What Changed In This Session

- Added read-only conductor tools in `src/conductor_tools.py`:
  - `list_panes`
  - `read_pane`
- Added a simple JSON tool loop to `src/conductor_daemon.py`.
- Split the conductor internals toward a Hermes-style harness:
  - `src/conductor_harness.py` now owns conversation history, transcript writes,
    JSON tool-call parsing, tool execution rounds, and history bounding.
  - `src/conductor_models.py` now owns MLX and llama.cpp model state, loading,
    chat completion, and llama.cpp server plumbing.
  - `src/conductor_daemon.py` now primarily owns socket/service orchestration
    and delegates chat behavior through the harness/model adapter.
- Updated `prompts/conductor_system.md` to describe the read-only tool ABI.
- Added conductor transcript events for tool calls.
- Added deterministic tmux-pane query handling for common ASR mistakes such as
  `t mux`, `pains`, and `paints`.
- Made deterministic tmux shortcuts write to the conductor transcript as:
  - `user`
  - `tool: list_panes`
  - `assistant`
- Smoothed spoken pane-list responses:
  - Plain phrases such as `what are my panes` now use the deterministic pane
    answer path instead of falling through to the LLM.
  - Large pane lists summarize active windows first and skip the rest unless the
    user asks for the full pane list.
  - The `list_panes` tool result now includes `spoken_summary`, and the harness
    tells the model to prefer that wording for spoken replies.
- Added the first controlled pane actions:
  - `send_text_to_pane` drafts one single-line text into a specific pane with
    `submit=false`.
  - `focus_pane` selects a specific tmux pane.
  - `submit_pane` exists as a guarded boundary but returns confirmation-needed;
    pressing Enter / running commands is intentionally not enabled yet.
  - Write tools validate against the original user utterance, not just model
    arguments, so a model-invented tool call without explicit user intent is
    rejected.
- Tuned wake command capture to avoid cutting the user off too early:
  - Added `wake_silence_timeout: 2.0` to `~/.claude/voice-config.json`.
  - Added `openwakeword_command_timeout: 10.0` to
    `~/.claude/voice-config.json`.
  - This trades a slightly slower end-of-command response for more tolerance of
    natural pauses while speaking to the conductor.
- Updated the expanded HUD mode panel:
  - The speaking-person icon in the mode settings panel is now clickable.
  - Clicking it copies this command to the clipboard:
    `cd /Users/stevenedgar/Code/handsfree && PYTHONPATH=src uv run python -m broker conductor pane --conversation-id voice`
  - Paste that into a tmux pane to open the conductor watcher window.
- Added filters for observed ambient/Whisper hallucinations:
  - `so`
  - `thank you`
  - `cough`
  - `I'm going to go...`
  - `I'm going to put it in the middle of the bag`
  - repeated `next video` phrases
- Fixed the HUD/off-state bug:
  - Turning both speech and wake off now also stops summary LLM, TTS, listener,
    and conductor daemons.
  - The HUD off path now forces cleanup even if the toggle files are already
    absent but warm daemons are still running.

## Important UI Note

If the HUD was already running while these code changes were made, restart it so
the forced off-state cleanup code is loaded:

```bash
cd /Users/stevenedgar/Code/handsfree
uv run --extra hud handsfree-hud
```

## Current Known Issues

- Wake detection is still too eager in noisy environments. OpenWakeWord can
  trigger with high confidence on background audio.
- After a wake trigger, Whisper can still hallucinate fluent non-commands from
  ambient audio.
- The conductor tool loop is now isolated in `src/conductor_harness.py`, but
  Qwen 2B is not reliably precise about tool result formatting. It may summarize
  instead of following a requested shape.
- The HUD status row currently reports service readiness. That is useful, but
  the user expectation is that Off should also mean the warm services are not
  running. The backend fix now enforces that once the HUD is restarted.

## Quick Resume

Start the HUD:

```bash
cd /Users/stevenedgar/Code/handsfree
uv run --extra hud handsfree-hud
```

Start wake:

```bash
PYTHONPATH=src uv run python -m broker enable wake --timeout 300
```

Open the conductor watch:

```bash
PYTHONPATH=src uv run python -m broker conductor watch --conversation-id voice --lines 30
```

Watch listener logs:

```bash
tail -f ~/.handsfree/logs/listener.log
```

Test by voice:

```text
Hey Jarvis.
Use your tools to list my tmux panes.
```

Expected:

- Listener log shows `Wake detected`.
- Listener log shows the command transcript.
- Conductor watch shows `tool: list_panes`.

## Roadmap To Hermes

### 1. Stabilize The Current UX

- Restart the HUD and confirm the Off button makes Voice, LLM, TTS, and Mic
  indicators go muted after the backend stops.
- Add a clearer HUD distinction between:
  - enabled/armed
  - warming
  - ready but idle
  - actively speaking/listening
  - stopped
  - error
- Add a small visible event when the listener ignores a hallucination, so it is
  clear that the system heard noise and intentionally dropped it.

### 2. Make Wake Reliable

- Raise or expose `openwakeword_threshold` in the HUD for noisy rooms.
- Consider using only one wake model during testing, likely `hey jarvis`, to
  reduce false positives.
- Add live listener debug telemetry:
  - wake model name
  - wake score
  - command duration
  - ignored reason
- Keep expanding no-op and hallucination filters only for patterns observed in
  logs.
- If false wakes remain common, add a second-stage confirmation gate before
  freeform conductor routing.

### 3. Harden The Local Tool Harness

- Keep phase 1 read-only:
  - `list_panes`
  - `read_pane`
- Store every tool attempt and result in the conductor transcript.
- Add stricter output shaping after tool calls:
  - no markdown for spoken replies
  - short responses by default
  - deterministic formatting for pane lists
- Make the tool ABI model-agnostic:
  - current JSON object format
  - future Hermes/native tool-call format
  - future llama.cpp OpenAI-compatible tool calls if supported cleanly

### 4. Introduce A Hermes-Style Harness

The first harness boundary now exists. The next clean step is to keep tightening
the split without changing the socket protocol:

- Harness currently owns:
  - conversation state
  - current JSON tool-call parsing and validation
  - transcript/memory writes
  - tool execution rounds
  - history bounding
- Model adapter now owns:
  - model loading
  - MLX chat
  - llama.cpp chat
  - llama.cpp server plumbing
- Tools own:
  - read-only tmux inspection
  - later controlled tmux writes
  - later agent/event queue actions

Target modules:

- `src/conductor_harness.py` exists.
- `src/conductor_models.py` exists.
- `src/conductor_tools.py`
- `src/conductor_memory.py` is still future work; transcript persistence remains
  in `src/conductor_transcript.py`.

Next harness-specific work:

- Move tool registry metadata out of prompt prose and into structured tool
  definitions.
- Add model-adapter parsing hooks for future Hermes/native tool-call formats.
- Add explicit retry behavior for malformed tool-call JSON.
- Add a small `conductor_memory.py` facade before adding summaries or durable
  preferences.

### 5. Pane Control

Current controlled tools:

- `send_text_to_pane(pane_id, text, submit=false)` drafts one single-line text
  into a pane without pressing Enter.
- `focus_pane(pane_id)` focuses/selects a pane.
- `submit_pane(pane_id)` is present but disabled until a confirmation layer is
  added.

Next tools / behavior:

- Add a real confirmation state for `submit_pane`.
- Add deterministic voice shortcuts for common phrasing such as `type git status
  into pane %3` if the LLM path is too inconsistent.
- Teach the conductor to resolve human pane names to pane IDs safely.

Guardrails:

- Write tools require explicit user intent.
- Destructive commands need confirmation.
- Voice commands should prefer drafting text into a pane before submitting.
- Drafting rejects newline characters so pasted text cannot implicitly submit.

### 6. Add Persistent Memory

Current persistent memory is transcript-based:

- `~/.handsfree/conductor/transcripts/*.jsonl`

Next:

- Session summaries.
- Per-tmux-window notes.
- Recent tool outcomes.
- User preferences such as preferred wake word, verbosity, and whether direct
  tmux shortcuts should bypass the LLM.

### 7. Hermes Model Experiment

With the harness boundary in place:

- Add a Hermes model adapter behind the same tool ABI.
- Start with read-only tools only.
- Compare against Qwen 2B on:
  - tool-call reliability
  - refusal to invent actions
  - spoken brevity
  - recovery after bad ASR input
- Only then enable write tools.

### 8. Local Speech-To-Speech Evaluation

Do not make OpenAI or Gemini Realtime the default path for this project; the
target is local execution on the Mac Studio to avoid cloud API cost and keep the
voice loop private.

Evaluation goal:

- Find out whether a local realtime speech-to-speech model can replace or
  augment the current `OpenWakeWord -> STT -> conductor -> TTS` voice frontend
  while keeping the existing conductor harness as the authority for tools,
  transcripts, and safety policy.

Candidate direction:

- Start with local/open models that support realtime or full-duplex spoken
  dialogue on Apple Silicon, especially Moshi / Kyutai MLX or related local
  speech models.
- Treat cloud realtime APIs only as design references, not implementation
  targets.

Comparison tasks:

- Long command with natural pauses.
- Barge-in / interruption.
- `what are my panes`
- `type git status into pane %3`
- `focus pane %3`
- False wake / background noise.
- Latency from end of speech to audible response.

Architecture constraint:

- The realtime speech model may own turn-taking and natural audio interaction,
  but it should not directly own tmux or shell actions.
- Tool calls still route through `src/conductor_harness.py` and
  `src/conductor_tools.py` so the same guardrails apply.

## Verification Last Run

```bash
cd /Users/stevenedgar/Code/handsfree
PYTHONPATH=src uv run pytest tests/unit -q
```

Result: 223 passed in 0.31s.

## Stop Point

Work paused after adding the first guarded pane-control tools, increasing wake
command capture timing, making the HUD mode-panel icon copy the conductor
watcher command, and adding the local speech-to-speech evaluation track. On next
resume, verify whether the 2.0 second silence window feels right in real use
before changing thresholds.
Restart the HUD after code changes so the clickable mode-panel icon is loaded.
