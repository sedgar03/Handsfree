# Testing Conventions

## Test Structure

```
tests/
├── conftest.py           # Shared import path setup (src/ and hooks/)
├── conftest_helpers.py   # Shared test helpers (macOS module stubs)
├── unit/                 # Fast, isolated tests for individual functions
│   ├── test_config.py
│   ├── test_handsfree_hook.py
│   ├── test_media_key_controls.py
│   ├── test_stt.py
│   ├── test_summarizer.py
│   ├── test_tts.py
│   └── test_vad.py
├── integration/          # Tests for module interactions
│   ├── test_hook_pipeline.py
│   └── test_listener_flow.py
└── e2e/                  # End-to-end workflow tests (requires hardware)
```

## Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run unit tests only
uv run pytest tests/unit/

# Run integration tests only
uv run pytest tests/integration/

# Run a specific test file
uv run pytest tests/unit/test_vad.py

# Run tests matching a pattern
uv run pytest tests/ -k "test_vad"

# Verbose output
uv run pytest tests/ -v
```

## Guidelines

- All macOS-only dependencies (PyObjC, sounddevice, MediaPlayer) are stubbed via `conftest_helpers.load_media_key_module()`
- Unit tests run headless — no hardware, no mic, no speakers
- Integration tests mock subprocess calls (`claude -p`, `afplay`, `pbcopy`, `osascript`)
- Test files mirror source files: `src/tts.py` → `tests/unit/test_tts.py`
- Test the contract, not the implementation — tests should survive refactoring
