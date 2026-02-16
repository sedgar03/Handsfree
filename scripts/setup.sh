#!/usr/bin/env bash
# Handsfree — one-command setup
# Downloads Kokoro models, installs Claude Code hooks, creates default config.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="$REPO_ROOT/models"

echo "=== Handsfree Setup ==="
echo "Repo: $REPO_ROOT"
echo ""

# 1. Check uv is installed
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is not installed. Install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "[✓] uv found: $(uv --version)"

# 2. Download Kokoro models
echo ""
echo "--- Downloading Kokoro models ---"
mkdir -p "$MODELS_DIR"

KOKORO_MODEL="$MODELS_DIR/kokoro-v1.0.onnx"
KOKORO_VOICES="$MODELS_DIR/voices-v1.0.bin"

if [ -f "$KOKORO_MODEL" ]; then
    echo "[✓] kokoro-v1.0.onnx already downloaded"
else
    echo "Downloading kokoro-v1.0.onnx (~82MB)..."
    curl -L -o "$KOKORO_MODEL" \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    echo "[✓] kokoro-v1.0.onnx downloaded"
fi

if [ -f "$KOKORO_VOICES" ]; then
    echo "[✓] voices-v1.0.bin already downloaded"
else
    echo "Downloading voices-v1.0.bin (~300MB)..."
    curl -L -o "$KOKORO_VOICES" \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    echo "[✓] voices-v1.0.bin downloaded"
fi

# 3. Create default config if missing
echo ""
echo "--- Config ---"
CONFIG_PATH="$HOME/.claude/voice-config.json"
if [ -f "$CONFIG_PATH" ]; then
    echo "[✓] Config already exists: $CONFIG_PATH"
else
    mkdir -p "$HOME/.claude"
    cat > "$CONFIG_PATH" << 'EOF'
{
  "input_mode": "media_key",
  "verbosity": "detailed",
  "kokoro_voice": "af_heart",
  "hotkey": "F18",
  "auto_submit": true,
  "auto_submit_after_transcription": true,
  "silence_timeout": 2.5
}
EOF
    echo "[✓] Created default config: $CONFIG_PATH"
fi

# 4. Install Claude Code hooks
echo ""
echo "--- Installing hooks ---"
uv run "$REPO_ROOT/hooks/install.py"

# 5. Make hook executable
chmod +x "$REPO_ROOT/hooks/handsfree_hook.py"

# 6. Test TTS
echo ""
echo "--- Quick test ---"
echo "Testing TTS (you should hear speech)..."
uv run "$REPO_ROOT/src/tts.py" "Handsfree setup complete"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Recommended first run:"
echo "  ./scripts/handsfree.sh --media-key"
echo "  # (runs permission checks automatically before launch)"
echo ""
echo "Or run checks only:"
echo "  ./scripts/handsfree.sh --check"
echo ""
echo "macOS permission checklist:"
echo "  1) Microphone: allow your terminal app"
echo "  2) Accessibility: allow your terminal app"
echo "  3) Input Monitoring: allow your terminal app (recommended)"
echo "  4) Automation: allow terminal -> System Events (on first submit)"
echo ""
echo "Config: $CONFIG_PATH"
