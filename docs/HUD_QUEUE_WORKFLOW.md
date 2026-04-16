# HUD, Queue, and Agent Routing

Handsfree now exposes a small shared control plane that can be driven by the
model usage HUD, Claude hooks, Codex/Gemini notify hooks, and local broker
commands.

## Shared Toggles

The canonical toggle files live under `~/.handsfree` so multiple agents can
read the same state:

| File | Meaning |
|---|---|
| `~/.handsfree/speech-enabled` | Speak queued/hook events automatically |
| `~/.handsfree/wake-enabled` | Keep events queued for click/wake retrieval |
| `~/.handsfree/consume-after` | Queue-consumption watermark for ignoring old muted-era events |

For migration compatibility, `~/.claude/handsfree` is still treated as speech
enabled, but new UI writes should use `~/.handsfree/speech-enabled`.

Notification mute still follows provider-specific files:

| File | Meaning |
|---|---|
| `~/.claude/mute` | Mute Claude notification sounds |
| `~/.codex/mute` | Mute Codex notification sounds |
| `~/.gemini/mute` | Mute Gemini notification sounds |

Notification audio and TTS share `/tmp/handsfree-audio.lock` so a ding and a
spoken message do not play over each other.

When a control surface unmutes or re-arms the workflow, it should also touch
or write the current Unix timestamp to `~/.handsfree/consume-after`. Wake and
click retrieval only consume events created after the newest of that marker,
`speech-enabled`, and `wake-enabled`.

## Event Queue

Events are stored in SQLite at:

```text
~/.handsfree/events.sqlite
```

Each row records:

- source agent, such as `claude`, `codex`, or `gemini`
- event kind, such as `notification`, `question`, or `permission`
- workflow label
- summary/detail text
- target tmux pane and cwd
- status: `pending`, `active`, or `done`

Broker commands:

```bash
PYTHONPATH=src uv run python -m broker status
PYTHONPATH=src uv run python -m broker warm speech
PYTHONPATH=src uv run python -m broker enable speech
PYTHONPATH=src uv run python -m broker enable wake
PYTHONPATH=src uv run python -m broker list
PYTHONPATH=src uv run python -m broker list --current
PYTHONPATH=src uv run python -m broker read-next
PYTHONPATH=src uv run python -m broker enqueue --source test --kind notification --summary "Test message"
PYTHONPATH=src uv run python -m broker mark-unmuted
```

`enable speech` starts the resident local summarizer and TTS daemon before it
writes `~/.handsfree/speech-enabled`. `enable wake` starts the listener in wake
phrase mode and warms Whisper STT before it writes `~/.handsfree/wake-enabled`.

## Runtime Behavior

Run the integrated HUD button UI from this repo:

```bash
uv run --extra hud handsfree-hud
```

Run the voice listener without launching Claude Code when you want manual
media-key control:

```bash
./scripts/listener.sh --media-key
```

The HUD wake button starts wake phrase mode itself. For manual fallback, run:

```bash
PYTHONPATH=src uv run python -m broker enable wake
```

Wake mode listens only while `~/.handsfree/wake-enabled` exists. By default it
uses OpenWakeWord as a lightweight first-stage detector with the built-in
`hey jarvis` model, then uses Whisper only for the follow-up command. If a
queued message exists, saying `hey jarvis` reads it immediately. The legacy
Whisper-only phrase matcher is still available with `"wake_engine": "whisper"`.

When speech is enabled:

1. Hooks enqueue the event.
2. Notification audio plays if that provider is not muted.
3. The event is spoken immediately.
4. The event is marked `done`.

When wake is enabled and speech is disabled:

1. Hooks enqueue the event.
2. Notification audio plays if that provider is not muted.
3. The event remains `pending`.
4. An idle AirPods click or wake phrase reads the next queued event.
5. After successful TTS playback, the event is marked `done` so the same item
   is not read again.

When neither speech nor wake is enabled:

1. Hooks may enqueue briefly for uniform handling.
2. Notification audio plays if that provider is not muted.
3. The event is marked `done`.

## Tmux Routing

Hooks capture tmux context with `src/tmux_target.py`. The workflow label is
chosen in this order:

1. tmux window name, if it looks human-authored
2. tmux pane title
3. basename of the pane cwd

The reader speaks this label as a short context marker before the event, for
example: `USChem here. No input needed...`

Responses are sent back to the captured pane with:

1. `tmux load-buffer`
2. `tmux paste-buffer`
3. `tmux send-keys Enter`

This avoids fragile shell quoting and keeps multi-line text intact.

## Codex Integration

Codex is wired through `~/.codex/config.toml`:

```toml
notify = ["/opt/homebrew/bin/python3.11", "/Users/stevenedgar/Code/handsfree/hooks/codex_notify.py"]
```

The current notify payload is intentionally treated as a coarse notification.
It is reliable today, but it does not yet expose the same rich turn transcript
that Claude Stop hooks provide. A later Codex hook integration can use the same
queue and tmux routing contract.

## Gemini Integration

Gemini is wired through `~/.gemini/settings.json`:

```bash
uv run --script hooks/install_gemini.py
```

The installer registers the same queue hook for Gemini `AfterAgent` and
`Notification` events. Those events use the same HUD notification, speech, and
wake buttons as Claude and Codex.
