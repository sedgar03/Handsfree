#!/usr/bin/env bash
# Launch Handsfree voice controls.
#
# Default session mode:
#   1. Enables handsfree mode (touch ~/.claude/handsfree)
#   2. Starts the input listener in the background
#   3. Launches Claude Code
#   4. On exit: kills listener, disables handsfree mode
#
# Listener-only mode:
#   Starts the input listener in the foreground and does not launch Claude Code
#   or change the speech toggle. Use this with handsfree-hud as the control UI.
#
# Usage:
#   ./scripts/handsfree.sh              # start with configured input mode
#   ./scripts/handsfree.sh --media-key  # force AirPods stem click mode
#   ./scripts/handsfree.sh --hotkey     # force F18 hold-to-talk mode
#   ./scripts/handsfree.sh --wake-word  # force wake word mode
#   ./scripts/handsfree.sh --listen-only --media-key
#   ./scripts/handsfree.sh --check       # run permission checks only
#   ./scripts/handsfree.sh --skip-checks # skip startup permission checks
#   ./scripts/handsfree.sh --no-listen  # TTS only, no STT listener
set -euo pipefail

# Platform guard — macOS only
if [ "$(uname -s)" != "Darwin" ]; then
    echo "[handsfree] ERROR: Handsfree requires macOS (detected: $(uname -s))."
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-}"
CLAUDE="${CLAUDE:-}"
PYTHON="${PYTHON:-}"
CONFIG_FILE="$HOME/.claude/voice-config.json"
SPEECH_TOGGLE="$HOME/.handsfree/speech-enabled"
LEGACY_TOGGLE="$HOME/.claude/handsfree"
LISTENER_PID=""
AUTO_SUBMIT_AFTER_TX="true"
CHECK_ONLY=false
RUN_CHECKS=true
SPEECH_WAS_ENABLED=false

if [ -z "$UV" ]; then
    UV="$(command -v uv || true)"
fi
if [ -z "$CLAUDE" ]; then
    CLAUDE="$(command -v claude || true)"
fi
if [ -z "$PYTHON" ]; then
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" &>/dev/null && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    done
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
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "[handsfree] ERROR: Python 3.11+ not found."
    exit 1
fi

# Parse CLI flags
INPUT_MODE_OVERRIDE=""
NO_LISTEN=false
LISTEN_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --media-key) INPUT_MODE_OVERRIDE="media_key" ;;
        --hotkey)    INPUT_MODE_OVERRIDE="hotkey" ;;
        --wake-word|--wake) INPUT_MODE_OVERRIDE="wake_word" ;;
        --check)     CHECK_ONLY=true ;;
        --skip-checks) RUN_CHECKS=false ;;
        --no-listen) NO_LISTEN=true ;;
        --listen-only|--listener-only|--no-claude) LISTEN_ONLY=true ;;
    esac
done

# Read input_mode from config (or use override)
if [ -n "$INPUT_MODE_OVERRIDE" ]; then
    INPUT_MODE="$INPUT_MODE_OVERRIDE"
elif [ -f "$CONFIG_FILE" ]; then
    INPUT_MODE=$("$PYTHON" -c "import json; print(json.load(open('$CONFIG_FILE')).get('input_mode', 'media_key'))" 2>/dev/null || echo "media_key")
else
    INPUT_MODE="media_key"
fi

if [ -f "$CONFIG_FILE" ]; then
    AUTO_SUBMIT_AFTER_TX=$("$PYTHON" -c "import json; print(str(json.load(open('$CONFIG_FILE')).get('auto_submit_after_transcription', True)).lower())" 2>/dev/null || echo "true")
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

run_listener_foreground() {
    echo "[handsfree] Starting listener only."
    echo "[handsfree] This does not launch Claude Code or change HUD speech/wake toggles."
    if [ "$INPUT_MODE" = "media_key" ] && [ -z "${HANDSFREE_ENABLE_LEGACY_TAPS:-}" ]; then
        export HANDSFREE_ENABLE_LEGACY_TAPS=force
        echo "[handsfree] Media-key fallback permission request enabled."
    fi
    if [ -n "$INPUT_MODE_OVERRIDE" ]; then
        export HANDSFREE_INPUT_MODE="$INPUT_MODE_OVERRIDE"
    fi
    exec "$UV" run --script "$REPO_ROOT/src/listener.py"
}

if [ "$LISTEN_ONLY" = true ]; then
    if [ "$NO_LISTEN" = true ]; then
        echo "[handsfree] ERROR: --listen-only and --no-listen cannot be combined."
        exit 2
    fi
    run_listener_foreground
fi

cleanup() {
    echo ""
    echo "[handsfree] Shutting down..."
    if [ -n "$LISTENER_PID" ] && kill -0 "$LISTENER_PID" 2>/dev/null; then
        kill "$LISTENER_PID" 2>/dev/null
        echo "[handsfree] Listener stopped."
    fi
    if [ "$SPEECH_WAS_ENABLED" = false ]; then
        rm -f "$SPEECH_TOGGLE"
    fi
    rm -f "$LEGACY_TOGGLE"
    echo "[handsfree] Handsfree session ended."
}
trap cleanup EXIT

# 1. Enable speech for this handsfree session, preserving a pre-existing
# HUD/user preference so cleanup does not unexpectedly turn it off.
if [ -f "$SPEECH_TOGGLE" ]; then
    SPEECH_WAS_ENABLED=true
fi
mkdir -p "$(dirname "$SPEECH_TOGGLE")"
echo "[handsfree] Starting speech services..."
(cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT/src" "$UV" run python -m broker enable speech --timeout 120 >/dev/null)
echo "[handsfree] Speech enabled."

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
    elif [ "$INPUT_MODE" = "wake_word" ]; then
        echo "[handsfree] Starting wake word listener..."
        echo "[handsfree]   Arm/disarm with the HUD wake button"
        echo "[handsfree]   Default wake: hey jarvis"
        echo "[handsfree]   Legacy whisper mode can still use: handsfree read next"
    else
        echo "[handsfree] Starting hotkey listener (F18 hold-to-talk)..."
        echo "[handsfree]   Hold F18 to record, release to transcribe + paste."
    fi

    LISTENER_LOG="/tmp/handsfree-listener.log"
    LISTENER_ENV=()
    # Apply mode override via env var if specified on CLI.
    if [ -n "$INPUT_MODE_OVERRIDE" ]; then
        LISTENER_ENV+=("HANDSFREE_INPUT_MODE=$INPUT_MODE_OVERRIDE")
    fi
    if [ "$INPUT_MODE" = "media_key" ] && [ -z "${HANDSFREE_ENABLE_LEGACY_TAPS:-}" ]; then
        LISTENER_ENV+=("HANDSFREE_ENABLE_LEGACY_TAPS=force")
        echo "[handsfree] Media-key fallback permission request enabled."
    fi
    env "${LISTENER_ENV[@]}" "$UV" run --script "$REPO_ROOT/src/listener.py" >>"$LISTENER_LOG" 2>&1 &
    LISTENER_PID=$!
    echo "[handsfree] Listener running (PID $LISTENER_PID)."
    echo "[handsfree] Listener log: $LISTENER_LOG"
else
    echo "[handsfree] Listener skipped (--no-listen)."
fi

# 3. Launch Claude Code
echo "[handsfree] Starting Claude Code..."
echo ""
"$CLAUDE"

# cleanup runs on EXIT via trap
