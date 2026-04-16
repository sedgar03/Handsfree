# Local Resources and Rehydration

This repo is intentionally source-first. Model weights, generated audio, caches,
local virtual environments, and user-specific config stay out of git.

This document is for humans and future agents working in the repo. Before
changing setup or adding model assets, preserve the policy below.

## Policy

`./scripts/setup.sh` must stay minimal. It may install only the resources needed
for the default local voice path to smoke-test on a new Apple Silicon Mac:

- repo-local Kokoro ONNX model and voices
- Whisper STT pre-cache
- default user config
- Claude hooks
- a short TTS smoke test

Do not make `setup.sh` download optional heavyweight or experimental resources
by default. Anything beyond the baseline must be opt-in and clearly labeled with:

- approximate size
- source or acquisition command
- target path
- config keys or environment variables needed to use it
- verification command
- fallback behavior when absent

Do not commit model weights, Hugging Face caches, generated audio, local virtual
envs, or user config.

## Ignored Local State

The repo currently ignores these categories:

| Path | Purpose | Rehydrate status |
|---|---|---|
| `models/` | Repo-local model weights | Baseline Kokoro files are downloaded by `setup.sh`; optional GGUF models are manual/opt-in |
| `outputs/` | Generated audio samples and demos | Not required; recreate by running demo scripts |
| `.venv/` | Local Python environment | Recreated by `uv` as needed |
| `.pytest_cache/`, `__pycache__/`, `*.egg-info/` | Python caches/build output | Recreated automatically |
| `.claude/`, `.codex/` | User/agent local state | Not portable; config belongs in `~/.claude/voice-config.json` |
| `data/`, `results/`, `research/*` contents | Local project data | Structure is tracked, contents are local |

Tracked placeholders such as `models/.gitkeep`, `data/.gitkeep`, and
`results/.gitkeep` keep the directory layout visible without committing local
contents.

## Baseline Rehydrate

On a fresh machine:

```bash
git clone https://github.com/sedgar03/Handsfree.git
cd Handsfree
./scripts/setup.sh
```

That should install the minimal default path:

- Kokoro TTS files under `models/`
- Whisper STT cache via Hugging Face Hub
- `~/.claude/voice-config.json`
- Claude hook integration

Then verify:

```bash
PYTHONPATH=src uv run pytest tests/unit -q
PYTHONPATH=src uv run python -m broker status
uv run --script src/tts.py "Handsfree test"
```

## Runtime Downloads

Some resources are not eagerly downloaded by setup, but may be fetched by the
first warmup or first use:

| Resource | Trigger | Notes |
|---|---|---|
| `mlx-community/Qwen3.5-2B-OptiQ-4bit` | `PYTHONPATH=src uv run python -m broker warm speech` or `warm conductor` when MLX backend is enabled | Default summary/conductor model; cached by MLX/Hugging Face tooling |
| OpenWakeWord built-ins such as `hey jarvis` | `PYTHONPATH=src uv run python -m broker enable wake` or listener warmup | Downloaded by OpenWakeWord utilities |
| Chatterbox weights | `tts_provider: "chatterbox"` plus TTS warmup/use | Large and experimental; keep opt-in |

## Optional Resources

### Local GGUF Models

Optional GGUF models live under ignored `models/` paths. For example, this
machine may have:

```text
models/supergemma4-26b-uncensored-gguf-v2/
```

That path is not rehydrated by default and should not be assumed present. To use
a local GGUF model, install/provide `llama-server`, place exactly one `.gguf`
file in a model directory, and select it explicitly:

```bash
HANDSFREE_CONDUCTOR_MODEL=models/some-local-gguf-dir \
HANDSFREE_CONDUCTOR_BACKEND=llama.cpp \
HANDSFREE_SUMMARY_MODEL=models/some-local-gguf-dir \
HANDSFREE_SUMMARY_MODEL_BACKEND=llama.cpp \
PYTHONPATH=src uv run python -m broker warm conductor --timeout 300
```

If an agent adds a scripted GGUF fetch later, it must be an opt-in command, not
part of baseline setup.

### Chatterbox Voice Clone Reference

Chatterbox can use a reference audio file through `chatterbox_reference_audio` in
`~/.claude/voice-config.json`. The current fallback path in code points at a
developer-local voice sample outside this repo. That sample is not portable and
is not required for default Kokoro operation.

Opt in explicitly:

```json
{
  "tts_provider": "chatterbox",
  "chatterbox_reference_audio": "/absolute/path/to/reference.wav"
}
```

Without a valid reference file, Chatterbox should use its built-in/default voice
or fall back through the normal TTS path.

### Generated Audio Outputs

`outputs/` contains generated demo audio. It is intentionally ignored and not
part of setup. Recreate samples by running the relevant scripts under
`scripts/chatterbox_*.py`.

## Agent Checklist

When changing resource handling:

- Keep baseline setup small and predictable.
- Add opt-in flags or separate scripts for heavy downloads.
- Update this document when a resource path, model ID, source, or config key
  changes.
- Prefer status/verification commands over silent downloads.
- Never add ignored local resources with `git add -f` unless the user explicitly
  asks and licensing/size has been checked.
