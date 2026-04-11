# TTS Provider Migration — Research Notes

**Date**: 2026-04-11
**Status**: Research complete, implementation paused pending default-provider decision
**Scope**: TTS backend swap (Kokoro → Fish Audio) and summarizer swap (`claude -p` → local model)

This document captures what we learned while scoping a migration of the handsfree TTS and summarization stack, so whoever picks it up next (including future-self) does not have to redo the research.

## Why we were considering this

1. Get expressive TTS with inline emotion tags (`(happy)`, `(whispering)`, etc.) and optional voice cloning.
2. Stop burning Anthropic API tokens on one-line summaries of Claude Code output (`src/summarizer.py` currently subprocesses `claude -p`).
3. Make the TTS layer pluggable so other users adopting the repo can pick their backend at setup time.

## Proposed design (for reference)

Pluggable TTS via flat sibling modules in `src/`:

- `src/tts.py` — thin dispatcher reading `config["tts_provider"]`
- `src/tts_fish_cloud.py` — hosted fish.audio API
- `src/tts_fish_local.py` — self-hosted OpenAudio S1-mini

Public signature `speak(text, voice=None, speed=1.1)` stays identical so `hooks/*.py` don't need to change. Same idea for summarizer: preserve `summarize(text, verbosity=None) -> str` and the existing `PROMPTS` dict; swap internals.

Both the local TTS and the local summarizer model want to stay resident in memory. But `handsfree_hook.py` is spawned fresh per Claude Code Stop event via `uv run --script`, so an in-process model load would pay the cold-load penalty every single hook invocation. Proposed fix: a long-lived `src/voice_daemon.py` process started by `scripts/handsfree.sh` alongside the existing listener, holding both the TTS and summarizer models in memory and exposing a Unix socket. Hook processes become thin socket clients.

## Fish Local on Apple Silicon — findings

**Bottom line**: Fish Speech technically runs on M-series Macs but is not close to real-time. For a voice assistant where response latency matters, Fish-local is not viable as a default today.

### The only benchmark we could find

In [fishaudio/fish-speech PR #461](https://github.com/fishaudio/fish-speech/pull/461), a Fish Speech contributor added native MPS support and published numbers from an M1 MacBook Air generating a short Chinese test sentence ("Nahida" sample):

| Method | Token speed | Generation time |
|---|---|---|
| CPU | 1.16 tok/s | ~173 s |
| MPS | 3.28 tok/s | ~69 s |
| MPS + `--compile` | 2.16 tok/s | ~122 s (compile is broken on M1) |

MPS is ~2.5× faster than CPU, but we're still measuring in *tens of seconds* per short sentence. Extrapolating generously to M3 Pro / M3 Max (say 2–3× the M1 Air), you'd still be looking at **~25–35 seconds per short sentence**. Kokoro synthesizes the same output in well under a second.

### The bug history supports a "macOS is tier-3" read

- [Discussion #351](https://github.com/fishaudio/fish-speech/discussions/351) has contradictory replies from different contributors ("Mac is not supported" vs. "We've supported MPS"). Unresolved.
- [Issue #789](https://github.com/fishaudio/fish-speech/issues/789) documents an MPS bug that broke inference across M1 Pro, Mac Mini M2, and M3. Fixed later in [#790](https://github.com/fishaudio/fish-speech/pull/790), but the pattern — MPS ships, breaks, fixed, breaks again — suggests macOS is not on the maintainers' regular test path.
- [Issue #834](https://github.com/fishaudio/fish-speech/issues/834) has users reporting `--compile` makes inference "slooooooow" on macOS.
- [Fish Audio's own self-host docs](https://docs.fish.audio/developer-guide/self-hosting/local-setup) still list Linux/WSL + CUDA as the supported path, with `--compile` requiring manual Triton install on macOS.

### Silence on Reddit is itself a signal

`site:reddit.com` searches for Fish Speech on MacBook / Apple Silicon returned zero results. `r/LocalLLaMA` is active about local TTS on Mac (Kokoro, Piper, Parakeet, XTTS, Chatterbox, Sesame CSM all have threads with benchmarks). The absence of Fish-on-Mac benchmarks is consistent with "technically runs, nobody uses it in anger on a Mac."

### Caveat: OpenAudio S1-mini specifically

All benchmarks above are for Fish Speech 1.x, **not** OpenAudio S1-mini (the 0.5B distilled self-hostable model released in 2025). S1-mini could in theory be meaningfully faster on MPS because it's smaller. But:

- Fish Audio has not published Apple Silicon benchmarks or install instructions specifically for S1-mini.
- Full S1 (4B) is cloud-only per their docs — you cannot self-host the full-fidelity model.
- Their self-host docs still lead with Linux+CUDA as of this research.

Unless someone downloads S1-mini and benchmarks it on the target Mac, assume it's not going to be materially faster than Fish Speech 1.x.

## Cloud vs local trade-off

| Dimension | Fish cloud | Fish local (S1-mini) | Kokoro local (current) |
|---|---|---|---|
| Latency | Low (network + ms synthesis) | 25–70+ s per short sentence on M-series | <1 s |
| Cost | Pennies per chat | Free after one-time ~3 GB download | Free |
| Offline | No | Yes | Yes |
| Expressiveness | High (full S1, emotion tags, voice cloning) | Medium (S1-mini, emotion tags, voice cloning) | Low (neutral voice, blending only) |
| "No paid APIs" promise | Breaks | Holds | Holds |
| macOS maintenance burden | Low (HTTP client) | High (Python env, MPS bugs, model weights) | None (already done) |

## Summarizer migration findings

### MLX + Qwen2.5-1.5B-Instruct-4bit is the recommended default

Initial pick was `mlx-community/Qwen2.5-3B-Instruct-4bit` (~1.74 GB). Codex (see review section) pushed back in favor of the 1.5B variant (~869 MB):

- The summarization task is constrained: 1–3 sentence status summaries, no path/code leakage, flag whether input is needed. 1.5B is enough.
- The existing `PROMPTS` dict in `src/summarizer.py` does most of the instruction-following work.
- Smaller = faster first-load + less resident memory in the daemon.

Avoid Llama-3.2-1B as default — codex flagged it as more likely to violate the "never read paths/code" constraint than Qwen at the same size.

### Required settings at generation time

- `temperature=0` (deterministic)
- `max_tokens <= 80`
- Post-filter the output to strip path-like / code-like substrings the model might leak despite the prompt.
- Fallback when the model fails to load: truncated original text (same behavior as today when `claude -p` fails).

### Why the daemon matters here too

Unlike `claude -p`, which has its own process and loads instantly, MLX models have multi-second cold loads. Without a resident daemon, every Claude Code Stop hook would pay that cold-load penalty. With the daemon, you pay it once per `handsfree.sh` session.

## Codex review highlights

Full review run 2026-04-11 via `codex exec` pointed at the repo. Key findings beyond "Fish local is not viable":

### Daemon fallback must not be an in-process model load

PEP 723 inline deps apply to the *entry script*, not to modules it imports. If `src/summarizer.py` declares `mlx-lm` in its inline header, importing `summarizer` from `hooks/handsfree_hook.py` does **not** install `mlx-lm` in the hook's uv env — the hook's own header governs what's available. Implication:

- **Daemon path**: primary. Models stay warm across invocations.
- **Hook fallback when daemon is down**: must be cheap only. Truncate summary text, or call `say`, or no-op. Never try to load MLX or Fish from the hook process.

### Daemon needs two lanes, not one FIFO

Permission / question speech is *urgent* (fires when Claude Code asks the user something). Stop-event summarization is *background*. A slow summarize call must not block a permission announcement.

- Two queues: `urgent_speech` and `background_summarize_then_speak`.
- Prioritize direct `speak` requests over `summarize+speak`.
- After summarization completes, re-check `/tmp/handsfree-pending-*.json` before speaking the summary. If a permission/question popped up during summarization, suppress the now-stale Stop summary (same spirit as the existing dedup logic at `hooks/handsfree_hook.py:177`).

### `speak` must block until playback finishes

`src/tts.py:84` currently calls `sd.wait()`. `hooks/ask_question_hook.py:109` depends on that blocking cadence for pacing between utterances. The Unix socket client must not return early, or the question hook's pacing breaks. Either:

- The socket protocol has the server hold its response until playback finishes, or
- The client does a follow-up poll/wait op.

### Fish voice cloning needs audio **and** matching text

Both the hosted API and self-host want a reference audio sample *plus* its transcription for voice cloning. Add both config keys:

- `fish_reference_audio: <path to WAV>`
- `fish_reference_text: <transcription>`

Or group them into named profiles (`fish_voices.steven.audio` / `fish_voices.steven.text`). Do **not** silently remap the existing Kokoro-specific `HANDSFREE_VOICE` env var (`src/config.py:45`) or blend syntax (`README.md:128`) into Fish voice IDs.

### If we ever ship Fish local, use Fish's HTTP boundary

Don't embed Fish's model internals into `voice_daemon.py`. Fish's self-host path already exposes `/v1/tts` over HTTP ([Fish docs](https://docs.fish.audio/developer-guide/self-hosting/running-inference)). Our daemon should:

- Own the summarizer model directly (MLX in-process).
- Own playback, queueing, and the urgent/background lanes.
- Talk to Fish as an **external** local HTTP service, same API shape as the cloud provider.

That makes `tts_fish_local.py` and `tts_fish_cloud.py` near-identical HTTP clients differing only in base URL and auth.

### Socket path needs user scoping

Don't use `/tmp/handsfree-voice.sock` — world-writable, collision-prone. Use:

- `/tmp/handsfree-$UID/voice.sock`, parent dir mode `0700`
- Stale-socket cleanup on daemon start
- Request timeouts
- `health` / `prewarm` ops so `scripts/handsfree.sh` can wait for models to finish loading before launching `claude`
- Config reload on every request (or on `~/.claude/voice-config.json` mtime change)

### Docs promise needs updating

`README.md:9` currently promises "No paid TTS/STT APIs required" and `docs/PROJECT_CHARTER.md:5` says "fully local." Any cloud option breaks both. If cloud becomes the default, these need to change to something like "Local-first; optional cloud TTS supported." Also add a model-weight licensing note for whichever local TTS we eventually ship.

## Recommended path forward when we resume

1. **Decide TTS default**: Fish cloud (codex's and my recommendation) vs. research Chatterbox / StyleTTS2 / Sesame CSM-1B as a stay-fully-local alternative vs. stay-on-Kokoro-and-add-Fish-cloud-as-upgrade-tier.
2. **Summarizer migration first** — smaller, contained, stops burning tokens immediately, doesn't depend on TTS decision. Branch: `feat/local-summarizer`.
3. **Daemon scaffold** — Unix socket at `/tmp/handsfree-$UID/voice.sock`, two-lane queue, blocking `speak` protocol, health op. Branch: `feat/voice-daemon`.
4. **Move summarizer into daemon** — MLX + Qwen2.5-1.5B-Instruct-4bit resident, hook calls become socket clients. Fall back to truncate-on-daemon-down.
5. **TTS provider abstraction** — `tts.py` dispatcher + `tts_fish_cloud.py` first (simpler to validate; no local model download to debug).
6. **Optional Fish local** — `tts_fish_local.py` running Fish's `/v1/tts` in a separate local service. Clearly documented as experimental; benchmark on the user's actual Mac before promoting.
7. **Docs sweep** — update README promise, project charter, add user-facing migration guide.
8. **Drop Kokoro** only after the replacement is working and benchmarked. Until then Kokoro stays as a fallback.

## Open decisions

- [ ] Default TTS provider: Fish cloud / Chatterbox (or similar) / stay-on-Kokoro-with-cloud-upgrade
- [ ] If Fish cloud: credential source (proposed env var `HANDSFREE_FISH_KEY`)
- [ ] If Chatterbox or other: which model, which weights, licensing
- [ ] Fish voice: stock voice ID, or clone from a reference of the user's own voice
- [ ] Summarizer model: confirm `mlx-community/Qwen2.5-1.5B-Instruct-4bit` or pick a different 1–2B model
- [ ] Whether to rip out Kokoro immediately once Fish ships, or keep as tier-3 fallback

## References

### GitHub
- [fishaudio/fish-speech PR #461 — Support inference on mps device natively (contains the M1 Air benchmark)](https://github.com/fishaudio/fish-speech/pull/461)
- [fishaudio/fish-speech Discussion #351 — Has anyone tried this on MacOS apple silicon?](https://github.com/fishaudio/fish-speech/discussions/351)
- [fishaudio/fish-speech Issue #356 — Support on MacOS apple silicon](https://github.com/fishaudio/fish-speech/issues/356)
- [fishaudio/fish-speech Issue #789 — MPS bug affecting M1/M2/M3](https://github.com/fishaudio/fish-speech/issues/789)
- [fishaudio/fish-speech Issue #834 — `--compile` slowness on macOS](https://github.com/fishaudio/fish-speech/issues/834)

### Fish Audio docs
- [Local Model Setup](https://docs.fish.audio/developer-guide/self-hosting/local-setup)
- [Running Inference](https://docs.fish.audio/developer-guide/self-hosting/running-inference)
- [Text to Speech core features](https://docs.fish.audio/developer-guide/core-features/text-to-speech)

### Third-party writeups
- [Gist of Rust — Fish Speech M3 install writeup (no perf numbers)](https://book.gist.rs/ml/voices/fish-speech.html)
- [Seaart — How to Install Fish Speech V1.5 Locally](https://www.seaart.ai/news/how-to-install-fish-speech-v-1-5)

### Model candidates
- [mlx-community/Qwen2.5-1.5B-Instruct-4bit on Hugging Face](https://huggingface.co/mlx-community/Qwen2.5-1.5B-Instruct-4bit)
- [mlx-community/Qwen2.5-3B-Instruct-4bit on Hugging Face](https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit)
