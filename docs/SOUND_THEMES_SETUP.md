# Sound Themes Setup

How Claude event sounds and HandsFree voice work together.

## Two Independent Dimensions

**Interaction mode** and **sound theme** are orthogonal:

| Interaction Mode | Event sounds | Handsfree listener | Voice TTS/STT | Toggle |
|---|---|---|---|---|
| Silent | Off | Off | Off | `touch ~/.claude/mute` |
| Sounds | Active (themed) | Off | Off | `rm ~/.claude/mute` + handsfree off |
| HandsFree | Active (themed) | Active | On | `agent/scripts/handsfree.sh on` |

**Sound theme** controls *which* sounds play for Claude events. HandsFree listener sounds (`~/Code/Handsfree/sounds/`) are not themed — they provide recording/transcription feedback independent of the event theme.

## Toggle Files

| File | Purpose |
|---|---|
| `~/.claude/mute` | Exists = all event sounds off (checked by `play-sound.sh`) |
| `~/.claude/handsfree` | Exists = TTS/STT voice + listener active |
| `~/.claude/theme` | Contains theme name (default: `aoe` if missing) |

## Directory Layout

```
~/.claude/hooks/
  play-sound.sh              # Central dispatcher
  sounds/
    aoe/                     # Age of Empires II theme
      complete.mp3
      notify.mp3
      subagent.mp3
      compact.mp3
    zelda/                   # Zelda theme
      complete.mp3
      notify.mp3
      subagent.mp3
      compact.mp3
```

## Event-to-File Mapping

| Event | Trigger | File |
|---|---|---|
| `complete` | Claude finishes a task | `complete.mp3` |
| `notify` | Notification/prompt | `notify.mp3` |
| `subagent` | Subagent spawned | `subagent.mp3` |
| `compact` | Conversation compacted | `compact.mp3` |

## The Dispatcher

`play-sound.sh` is the central sound player. Wrapper scripts (`complete-sound.sh`, etc.) delegate to it with an event name and optional volume:

```bash
# play-sound.sh <event> [volume]
play-sound.sh complete       # full volume
play-sound.sh notify 0.25    # 25% volume
```

The dispatcher:
1. Checks `~/.claude/mute` — exits if present
2. Reads `~/.claude/theme` — defaults to `aoe`
3. Resolves `sounds/<theme>/<event>.mp3`
4. Falls back to `sounds/aoe/<event>.mp3` if theme file missing
5. Plays via `afplay` (backgrounded)

## Adding a New Theme

1. Create directory: `mkdir ~/.claude/hooks/sounds/<name>`
2. Drop 4 mp3 files: `complete.mp3`, `notify.mp3`, `subagent.mp3`, `compact.mp3`
3. Activate: `echo <name> > ~/.claude/theme`

## Quick Start

```bash
# Switch themes
echo zelda > ~/.claude/theme   # Zelda sounds
echo aoe > ~/.claude/theme     # AoE sounds (default)
rm ~/.claude/theme              # Falls back to aoe

# Switch modes
touch ~/.claude/mute            # Silent
rm ~/.claude/mute               # Sounds on
agent/scripts/handsfree.sh on   # HandsFree + sounds

# List available themes
agent/scripts/theme.sh list
```

## Relationship to HandsFree

The sound theme system is orthogonal to HandsFree:
- **Theme** controls which mp3s play for Claude events (complete, notify, subagent, compact)
- **HandsFree** controls TTS/STT voice and the listener recording pipeline
- You can use any theme in any mode (e.g., HandsFree + Zelda sounds)
- HandsFree listener UI sounds (`bereal.mp3`, `snapchat.mp3`, `mail-sent.mp3`) in `~/Code/Handsfree/sounds/` are always the same regardless of theme

See also: [CLAUDE_HOOKS_SETUP.md](CLAUDE_HOOKS_SETUP.md) for the full hooks architecture.
