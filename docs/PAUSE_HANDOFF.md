# Pause Handoff

Created: 2026-04-13

This note captures the current state of the Handsfree/HUD work so it can be
paused safely and resumed later without replaying the chat history.

## Current State

- No Handsfree listener is currently running.
- Wake mode is disarmed: `~/.handsfree/wake-enabled` is absent.
- Speech mode is off: `~/.handsfree/speech-enabled` is absent.
- Claude and Codex notification sounds are muted:
  - `~/.claude/mute`
  - `~/.codex/mute`
- The durable queue exists at `~/.handsfree/events.sqlite`.
- The queue currently contains pending Claude events from several tmux panes.

To inspect the queue:

```bash
cd /Users/stevenedgar/Code/handsfree
PYTHONPATH=src uv run python -m broker list --limit 20
```

## What Was Added

Handsfree now has a shared HUD/agent control path:

- `~/.handsfree/speech-enabled` controls automatic TTS.
- `~/.handsfree/wake-enabled` arms wake/click retrieval.
- `~/.handsfree/consume-after` marks the earliest queue event that wake/click
  retrieval should consume after re-arming or unmuting.
- `~/.handsfree/events.sqlite` stores queued Claude/Codex events.
- `src/tmux_target.py` captures workflow labels and target tmux panes.
- `src/queue_actions.py` can read the next event and route a spoken response
  back to the original pane.
- `hooks/codex_notify.py` bridges Codex `notify` into the queue.
- `scripts/listener.sh` starts a listener without launching Claude Code.
- `src/wake_phrase_listener.py` adds a first-pass local wake phrase mode.

Related documentation:

- `docs/HUD_QUEUE_WORKFLOW.md`
- `docs/HANDSFREE_USER_GUIDE.md`
- `docs/CLAUDE_HOOKS_SETUP.md`

## HUD State

The button UI lives in the separate repo:

```bash
cd /Users/stevenedgar/Code/model-usage-hud
usage-hud-app
```

The HUD has provider buttons for Claude, Codex, and Gemini, then a spacer, then
notification, speech, and wake controls. The HUD writes the shared Handsfree
toggle files under `~/.handsfree`.

## Known Issues

AirPods stem-click mode is unreliable in the current environment:

- The first click starts recording.
- A follow-up click may not reach the listener while the mic stream is open.
- This can produce long ambient recordings and Whisper hallucinations.

Wake phrase mode is a better direction, but still needs more tuning:

- It uses VAD + local Whisper, not a dedicated wake-word model.
- Short commands like `read next` can be misheard as `Thank you`.
- The current implementation filters obvious repetition hallucinations and
  allows `read next` as a special bare queue command.
- A future pass should either tune input-device handling or evaluate a small
  wake-word engine such as openWakeWord or Porcupine.

macOS permissions:

- Microphone passed.
- Input Monitoring passed after the later checks.
- Automation passed.
- Accessibility still reported a warning from the checker.

## Resume Checklist

1. Start the HUD:

   ```bash
   cd /Users/stevenedgar/Code/model-usage-hud
   usage-hud-app
   ```

2. For wake phrase testing, turn on the HUD Wake button.

3. If resuming manually without the HUD, mark the current unmute point:

   ```bash
   cd /Users/stevenedgar/Code/handsfree
   PYTHONPATH=src uv run python -m broker enable wake
   ```

4. Check service readiness:

   ```bash
   cd /Users/stevenedgar/Code/handsfree
   PYTHONPATH=src uv run python -m broker status
   ```

5. Try phrases near the active input mic:

   ```text
   handsfree read the next message
   hey codex run the tests
   read next
   ```

6. Stop the listener before leaving a noisy environment:

   ```bash
   pkill -f '/Users/stevenedgar/Code/handsfree/src/listener.py'
   rm -f ~/.handsfree/wake-enabled
   ```

## Verification Last Run

The last verification pass after wake phrase changes was:

```bash
cd /Users/stevenedgar/Code/handsfree
bash -n scripts/handsfree.sh scripts/listener.sh scripts/setup.sh
/opt/homebrew/bin/python3.11 -m py_compile src/config.py src/stt.py src/listener.py src/wake_phrase_listener.py
uv run pytest
```

Result: `40 passed`.

HUD checks were also run earlier:

```bash
cd /Users/stevenedgar/Code/model-usage-hud
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_state
```

Result: `6 passed`.

## Design Decisions To Revisit

- Keep Handsfree and model-usage-hud as two cooperating repos for now.
- Use shared files and SQLite as the contract rather than migrating the HUD
  into Handsfree immediately.
- Prefer wake phrase / HUD-driven controls over AirPods stem clicks.
- Keep Codex on the stable `notify` integration for now; richer Codex hooks can
  later reuse the same queue contract.
