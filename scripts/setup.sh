#!/usr/bin/env bash
# Handsfree — one-command setup
# Downloads Kokoro models, installs Claude Code hooks, creates default config.
set -euo pipefail

# Platform guard — macOS only
if [ "$(uname -s)" != "Darwin" ]; then
    echo "ERROR: Handsfree requires macOS (detected: $(uname -s))."
    exit 1
fi

# Architecture guard — Apple Silicon only (mlx-whisper requires it)
if [ "$(uname -m)" != "arm64" ]; then
    echo "ERROR: Handsfree requires Apple Silicon (M1/M2/M3/M4)."
    echo "  Detected architecture: $(uname -m)"
    echo "  mlx-whisper (used for speech-to-text) only runs on Apple Silicon."
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="$REPO_ROOT/models"

echo "=== Handsfree Setup ==="
echo "Repo: $REPO_ROOT"
echo ""

# 1. Pre-flight checks
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is not installed. Install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "[✓] uv found: $(uv --version)"

# Check Python 3.11+
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ is required (found: $PYTHON_VERSION)."
    echo "  Install via Homebrew: brew install python@3.12"
    exit 1
fi
echo "[✓] Python $PYTHON_VERSION"

# Check Claude Code CLI
if ! command -v claude &>/dev/null; then
    echo "ERROR: Claude Code CLI (claude) not found."
    echo "  Install it first: https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi
echo "[✓] claude found: $(claude --version 2>/dev/null | head -1)"

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
    curl --fail -L -o "$KOKORO_MODEL" \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    echo "[✓] kokoro-v1.0.onnx downloaded"
fi

if [ -f "$KOKORO_VOICES" ]; then
    echo "[✓] voices-v1.0.bin already downloaded"
else
    echo "Downloading voices-v1.0.bin (~300MB)..."
    curl --fail -L -o "$KOKORO_VOICES" \
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    echo "[✓] voices-v1.0.bin downloaded"
fi

# 3. Pre-download Whisper model (cached by HuggingFace Hub)
echo ""
echo "--- Pre-downloading Whisper model ---"
if uv run python3 -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo', local_files_only=True)" &>/dev/null; then
    echo "[✓] whisper-large-v3-turbo already cached"
else
    echo "Downloading whisper-large-v3-turbo (~800MB, cached by HuggingFace Hub)..."
    uv run python3 -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')" || echo "[!] Whisper model download failed — will download on first use"
fi

# 4. Create default config if missing (renumbered after Whisper step)
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
  "voice_presets": {
    "narrator": "af_heart:0.7,af_nicole:0.3"
  },
  "kokoro_speed": 1.1,
  "hotkey": "F18",
  "auto_submit": true,
  "auto_submit_after_transcription": true,
  "silence_timeout": 4.5,
  "max_recording": 300
}
EOF
    echo "[✓] Created default config: $CONFIG_PATH"
fi

# 5. Install Claude Code hooks
echo ""
echo "--- Installing hooks ---"
uv run "$REPO_ROOT/hooks/install.py"

# 6. Make hook executable
chmod +x "$REPO_ROOT/hooks/handsfree_hook.py"

# 7. Test TTS
echo ""
echo "--- Quick test ---"
echo "Testing TTS (you should hear speech)..."
uv run "$REPO_ROOT/src/tts.py" "Handsfree setup complete"

echo ""
echo "=== Setup Complete ==="
echo ""

echo "--- Permission Self-Check ---"
if "$REPO_ROOT/scripts/check_permissions.sh"; then
    echo "[✓] Permission self-check passed."
else
    echo "[!] Permission self-check reported issues."
    echo "    You can re-run anytime with:"
    echo "      ./scripts/handsfree.sh --check"
fi
echo ""

echo "Recommended first run:"
echo "  ./scripts/handsfree.sh --media-key"
echo "  # (runs permission checks automatically before launch)"
echo "  # Optional per-terminal voice override:"
echo "  # export HANDSFREE_VOICE='af_heart:0.7,af_nicole:0.3'"
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
