#!/bin/bash
# Play AOE2 farm exhausted sound when agent dispatch is requested
# Mute:   touch ~/.claude/mute
# Unmute: rm ~/.claude/mute
[ -f ~/.claude/mute ] && exit 0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
afplay "$SCRIPT_DIR/aoe-farm-exhausted.mp3" &
