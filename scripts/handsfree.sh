#!/usr/bin/env bash
# Launch a handsfree Claude Code session.
#
# What this does:
#   1. Enables handsfree mode (touch ~/.claude/handsfree)
#   2. Starts the input listener in the background
#   3. Launches Claude Code
#   4. On exit: kills listener, disables handsfree mode
#
# Usage:
#   ./scripts/handsfree.sh              # start with configured input mode
#   ./scripts/handsfree.sh --media-key  # force AirPods stem click mode
#   ./scripts/handsfree.sh --hotkey     # force F18 hold-to-talk mode
#   ./scripts/handsfree.sh --check       # run permission checks only
#   ./scripts/handsfree.sh --skip-checks # skip startup permission checks
#   ./scripts/handsfree.sh --no-listen  # TTS only, no STT listener
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-}"
CLAUDE="${CLAUDE:-}"
CONFIG_FILE="$HOME/.claude/voice-config.json"
LISTENER_PID=""
AUTO_SUBMIT_AFTER_TX="true"
CHECK_ONLY=false
RUN_CHECKS=true

if [ -z "$UV" ]; then
    UV="$(command -v uv || true)"
fi
if [ -z "$CLAUDE" ]; then
    CLAUDE="$(command -v claude || true)"
fi

if [ -z "$UV" ] || ! command -v "$UV" &>/dev/null; then
    echo "[handsfree] ERROR: uv not found."
    echo "[handsfree] Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
if [ -z "$CLAUDE" ] || ! command -v "$CLAUDE" &>/dev/null; then
    echo "[handsfree] ERROR: claude binary not found."
    echo "[handsfree] Install Claude Code CLI and ensure 'claude' is on PATH."
    exit 1
fi

# Parse CLI flags
INPUT_MODE_OVERRIDE=""
NO_LISTEN=false
for arg in "$@"; do
    case "$arg" in
        --media-key) INPUT_MODE_OVERRIDE="media_key" ;;
        --hotkey)    INPUT_MODE_OVERRIDE="hotkey" ;;
        --check)     CHECK_ONLY=true ;;
        --skip-checks) RUN_CHECKS=false ;;
        --no-listen) NO_LISTEN=true ;;
    esac
done

# Read input_mode from config (or use override)
if [ -n "$INPUT_MODE_OVERRIDE" ]; then
    INPUT_MODE="$INPUT_MODE_OVERRIDE"
elif [ -f "$CONFIG_FILE" ]; then
    INPUT_MODE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('input_mode', 'media_key'))" 2>/dev/null || echo "media_key")
else
    INPUT_MODE="media_key"
fi

if [ -f "$CONFIG_FILE" ]; then
    AUTO_SUBMIT_AFTER_TX=$(python3 -c "import json; print(str(json.load(open('$CONFIG_FILE')).get('auto_submit_after_transcription', True)).lower())" 2>/dev/null || echo "true")
fi

if [ "$RUN_CHECKS" = true ]; then
    echo "[handsfree] Running permission check..."
    if ! "$REPO_ROOT/scripts/check_permissions.sh"; then
        echo "[handsfree] Permission check failed. Fix the items above and rerun."
        exit 1
    fi
fi

if [ "$CHECK_ONLY" = true ]; then
    echo "[handsfree] Permission check passed."
    exit 0
fi

cleanup() {
    echo ""
    echo "[handsfree] Shutting down..."
    if [ -n "$LISTENER_PID" ] && kill -0 "$LISTENER_PID" 2>/dev/null; then
        kill "$LISTENER_PID" 2>/dev/null
        echo "[handsfree] Listener stopped."
    fi
    rm -f ~/.claude/handsfree
    echo "[handsfree] Handsfree mode disabled."
}
trap cleanup EXIT

# 1. Enable handsfree mode
touch ~/.claude/handsfree
echo "[handsfree] Mode enabled."

# 2. Start listener (unless --no-listen)
if [ "$NO_LISTEN" = false ]; then
    if [ "$INPUT_MODE" = "media_key" ]; then
        echo "[handsfree] Starting media key listener (AirPods stem click)..."
        echo "[handsfree]   Single click → record (VAD auto-stop)"
        if [ "$AUTO_SUBMIT_AFTER_TX" = "true" ]; then
            echo "[handsfree]   Double click → manual stop (submit is automatic after transcription)"
        else
            echo "[handsfree]   Double click → stop recording / submit"
        fi
    else
        echo "[handsfree] Starting hotkey listener (F18 hold-to-talk)..."
        echo "[handsfree]   Hold F18 to record, release to transcribe + paste."
    fi

    # Apply mode override via env var if specified on CLI
    if [ -n "$INPUT_MODE_OVERRIDE" ]; then
        HANDSFREE_INPUT_MODE="$INPUT_MODE_OVERRIDE" "$UV" run --script "$REPO_ROOT/src/listener.py" &>/dev/null &
    else
        "$UV" run --script "$REPO_ROOT/src/listener.py" &>/dev/null &
    fi
    LISTENER_PID=$!
    echo "[handsfree] Listener running (PID $LISTENER_PID)."
else
    echo "[handsfree] Listener skipped (--no-listen)."
fi

# 3. Launch Claude Code
echo "[handsfree] Starting Claude Code..."
echo ""
"$CLAUDE"

# cleanup runs on EXIT via trap
