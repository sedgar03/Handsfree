#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["kokoro-onnx==0.4.9", "sounddevice", "soundfile", "numpy"]
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///
"""TTS wrapper — synthesize speech and play through speakers.

Uses the provider selected in ``~/.claude/voice-config.json``.
Falls back to Kokoro/macOS `say` if Chatterbox or Kokoro cannot load.
Uses a file lock to serialize concurrent invocations.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

# Allow imports from src/ when run from anywhere
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from chatterbox_markup import (
    CHATTERBOX_TAGS,
    sanitize_chatterbox_markup,
)
from config import get_config
from tts_client import request_tts_daemon

MODELS_DIR = _repo_root / "models"
KOKORO_MODEL = MODELS_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES = MODELS_DIR / "voices-v1.0.bin"
LOCK_FILE = Path("/tmp/handsfree-audio.lock")
DEFAULT_CHATTERBOX_REFERENCE = (
    Path.home() / "Code" / "fish-audio-local" / "voices" / "vctk-p238" / "reference.wav"
)
VALID_TTS_PROVIDERS = {"kokoro", "chatterbox"}
CHATTERBOX_CHUNK_CHARS = 420
CHATTERBOX_CHUNK_SILENCE_SECONDS = 0.08
# Lazy-initialized Kokoro instance
_kokoro = None
_kokoro_error: str | None = None
_chatterbox = None
_chatterbox_conditioned_ref: str | None = None
_chatterbox_device_name: str | None = None


def _get_kokoro():
    """Lazy-init Kokoro. Returns the Kokoro instance or None if models missing."""
    global _kokoro, _kokoro_error
    if _kokoro is not None:
        return _kokoro

    if not KOKORO_MODEL.exists() or not KOKORO_VOICES.exists():
        _kokoro_error = "Kokoro model files are missing"
        return None

    try:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        _kokoro_error = None
        return _kokoro
    except Exception as e:
        _kokoro_error = str(e)
        print(f"[handsfree] Kokoro init failed: {e}", file=sys.stderr)
        return None


def _patch_chatterbox_watermarker() -> None:
    """Disable Chatterbox's optional Perth watermark when unavailable on Apple Silicon."""

    try:
        import perth
    except ImportError:
        return
    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        perth.PerthImplicitWatermarker = perth.DummyWatermarker


def _chatterbox_device(config: dict) -> str:
    env_device = os.environ.get("HANDSFREE_CHATTERBOX_DEVICE")
    configured = env_device or config.get("chatterbox_device")
    if configured in {"cpu", "mps"}:
        return str(configured)
    # Chatterbox currently hits float64 conversion failures on MPS during
    # voice conditioning on this Mac. Prefer correctness over a silent Kokoro
    # fallback; users can opt back into MPS with HANDSFREE_CHATTERBOX_DEVICE.
    return "cpu"


def _get_chatterbox(device: str = "cpu"):
    """Lazy-init Chatterbox Turbo. Raises so callers can fall back cleanly."""

    global _chatterbox, _chatterbox_conditioned_ref, _chatterbox_device_name
    if _chatterbox is not None and _chatterbox_device_name == device:
        return _chatterbox

    _patch_chatterbox_watermarker()
    if device == "mps":
        import torch
        if not torch.backends.mps.is_available():
            device = "cpu"
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    _chatterbox = ChatterboxTurboTTS.from_pretrained(device=device)
    _chatterbox_conditioned_ref = None
    _chatterbox_device_name = device
    return _chatterbox


def _tts_provider(config: dict) -> str:
    forced = os.environ.get("HANDSFREE_TTS_PROVIDER_FORCE")
    if forced in VALID_TTS_PROVIDERS:
        return str(forced)
    provider = config.get("tts_provider")
    if isinstance(provider, str) and provider in VALID_TTS_PROVIDERS:
        return provider
    return "kokoro"


def _clamped_float(config: dict, key: str, default: float, low: float, high: float) -> float:
    try:
        value = float(config.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _chatterbox_reference_path(config: dict, voice: str | None) -> Path | None:
    configured = config.get("chatterbox_reference_audio")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    if isinstance(voice, str) and voice.strip() not in {"default", "p238", "p238_clone"}:
        candidate = Path(voice).expanduser()
        if candidate.exists():
            return candidate
    return DEFAULT_CHATTERBOX_REFERENCE


def _prepare_chatterbox_voice(model, reference_path: Path | None) -> str:
    global _chatterbox_conditioned_ref

    if reference_path is None or not reference_path.exists():
        return "built-in"
    ref_key = str(reference_path)
    if _chatterbox_conditioned_ref != ref_key:
        model.prepare_conditionals(ref_key)
        _chatterbox_conditioned_ref = ref_key
    return ref_key


def _chatterbox_tag_budget(strength: float) -> int:
    if strength <= 0:
        return 0
    if strength <= 0.4:
        return 1
    if strength <= 0.75:
        return 2
    return 3


def _tile_chatterbox_tags(text: str, tags: list[str], strength: float) -> str:
    budget = _chatterbox_tag_budget(strength)
    selected = tags[:budget]
    if not selected:
        return text

    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    if len(sentences) > 1 and len(selected) > 1:
        for index, tag in enumerate(selected):
            sentence_index = min(index, len(sentences) - 1)
            sentences[sentence_index] = f"[{tag}] {sentences[sentence_index]}"
        return " ".join(sentences)

    prefix = "".join(f"[{tag}]" for tag in selected)
    return f"{prefix} {text}"


def _chatterbox_tagged_text(text: str, config: dict) -> str:
    style = config.get("chatterbox_style")
    strength = _clamped_float(config, "chatterbox_style_strength", 0.0, 0.0, 1.0)
    budget = _chatterbox_tag_budget(strength)
    text = sanitize_chatterbox_markup(
        text,
        allow_tags=style == "auto" and budget > 0,
        max_tags=budget,
    )
    if not isinstance(style, str) or style == "neutral":
        return text
    if style == "auto":
        return text
    if style not in CHATTERBOX_TAGS:
        return text
    return _tile_chatterbox_tags(text, [style], strength)


def _chatterbox_generate_kwargs(config: dict) -> dict[str, float | int]:
    return {
        "temperature": _clamped_float(config, "chatterbox_temperature", 0.8, 0.1, 2.0),
        "top_p": _clamped_float(config, "chatterbox_top_p", 0.95, 0.1, 1.0),
        "repetition_penalty": _clamped_float(
            config,
            "chatterbox_repetition_penalty",
            1.2,
            1.0,
            2.0,
        ),
    }


def _split_chatterbox_chunks(
    text: str,
    *,
    max_chars: int | None = None,
) -> list[str]:
    limit = CHATTERBOX_CHUNK_CHARS if max_chars is None else max_chars
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    for paragraph in re.split(r"\n\s*\n+", text):
        paragraph = re.sub(r"\s+", " ", paragraph.strip())
        if not paragraph:
            continue
        chunks.extend(_split_chatterbox_paragraph(paragraph, limit))
    return chunks


def _split_chatterbox_paragraph(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text) if part]
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)

    split_chunks: list[str] = []
    for chunk in chunks:
        while len(chunk) > limit:
            head = chunk[:limit].rsplit(" ", 1)[0].strip()
            if not head:
                break
            split_chunks.append(head)
            chunk = chunk[len(head) :].strip()
        if chunk:
            split_chunks.append(chunk)
    return split_chunks


def _concat_audio_chunks(
    chunks: list[np.ndarray],
    sample_rate: int,
    *,
    silence_seconds: float = CHATTERBOX_CHUNK_SILENCE_SECONDS,
) -> np.ndarray:
    if not chunks:
        return np.array([], dtype=np.float32)
    if len(chunks) == 1:
        return chunks[0]

    silence_len = max(1, int(sample_rate * silence_seconds))
    pieces: list[np.ndarray] = []
    for index, chunk in enumerate(chunks):
        if index:
            if chunk.ndim == 1:
                pieces.append(np.zeros(silence_len, dtype=np.float32))
            else:
                pieces.append(np.zeros((silence_len, chunk.shape[1]), dtype=np.float32))
        pieces.append(chunk)
    return np.concatenate(pieces, axis=0)


def _resolve_voice(voice_spec: str, kokoro):
    """Resolve a voice spec to a string name or blended numpy array.

    Supports:
      - Plain name:      "af_heart"
      - Preset name:     "audiobook_narrator"  (looked up in config voice_presets)
      - Blend spec:      "af_heart:0.7,af_nicole:0.3"
    """
    # Check if it's a preset name
    if ":" not in voice_spec and "," not in voice_spec:
        presets = get_config().get("voice_presets", {})
        voice_spec = presets.get(voice_spec, voice_spec)

    if ":" not in voice_spec:
        return voice_spec

    parts = [p.strip() for p in voice_spec.split(",")]
    styles = []
    for part in parts:
        name, _, weight = part.partition(":")
        name = name.strip()
        weight = float(weight.strip()) if weight.strip() else 1.0
        styles.append((kokoro.get_voice_style(name), weight))

    # Normalize weights so they sum to 1.0
    total = sum(w for _, w in styles)
    blend = sum(style * (w / total) for style, w in styles)
    return blend


def _play_audio_with_afplay(samples, sample_rate: int) -> bool:
    """Play samples through macOS afplay, matching notification playback."""

    try:
        import soundfile as sf
    except ImportError:
        return False

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = Path(tmp.name)
    tmp.close()
    try:
        sf.write(path, np.asarray(samples, dtype=np.float32), int(sample_rate))
        result = subprocess.run(
            ["afplay", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False
    finally:
        path.unlink(missing_ok=True)


def _play_audio(samples, sample_rate: int):
    """Play audio samples through the default output device."""
    if sys.platform == "darwin" and _play_audio_with_afplay(samples, sample_rate):
        return

    import sounddevice as sd

    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def _say_fallback(text: str):
    """macOS say command as TTS fallback."""
    subprocess.run(["say", text], check=False)


def _warm_kokoro() -> dict:
    kokoro = _get_kokoro()
    if kokoro is None:
        return {
            "ok": True,
            "engine": "say",
            "requested_engine": "kokoro",
            "fallback_reason": _kokoro_error or "Kokoro unavailable",
            "ready": True,
        }
    return {"ok": True, "engine": "kokoro", "requested_engine": "kokoro", "ready": True}


def _warm_chatterbox(config: dict) -> dict:
    voice = str(config.get("chatterbox_voice") or "default")
    model = _get_chatterbox(_chatterbox_device(config))
    reference_path = _chatterbox_reference_path(config, voice)
    voice_source = _prepare_chatterbox_voice(model, reference_path)
    return {
        "ok": True,
        "engine": "chatterbox",
        "requested_engine": "chatterbox",
        "voice": voice,
        "voice_source": voice_source,
        "ready": True,
    }


def warm() -> dict:
    """Warm the local TTS engine in the current process."""

    config = get_config()
    if _tts_provider(config) == "chatterbox":
        try:
            return _warm_chatterbox(config)
        except Exception as exc:  # noqa: BLE001
            print(f"[handsfree] Chatterbox init failed: {exc}", file=sys.stderr)
            fallback = _warm_kokoro()
            fallback["requested_engine"] = "chatterbox"
            fallback["fallback_reason"] = str(exc)
            return fallback
    return _warm_kokoro()


def _speak_kokoro(
    text: str,
    *,
    voice: str | None,
    speed: float,
    config: dict,
) -> str:
    text = sanitize_chatterbox_markup(text, allow_tags=False)
    if voice is None:
        voice = str(config.get("kokoro_voice", "af_heart"))
    if speed == 1.1:  # default — allow config override
        speed = float(config.get("kokoro_speed", 1.1))

    kokoro = _get_kokoro()
    if kokoro is None:
        _say_fallback(text)
        return "say"

    resolved_voice = _resolve_voice(voice, kokoro)
    samples, sample_rate = kokoro.create(text, voice=resolved_voice, speed=speed)
    _play_audio(samples, sample_rate)
    return "kokoro"


def _chatterbox_samples_to_numpy(wav) -> np.ndarray:
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().numpy()
    samples = np.asarray(wav)
    if samples.ndim == 2:
        if samples.shape[0] == 1:
            samples = samples[0]
        elif samples.shape[0] <= 2:
            samples = samples.T
    return samples.astype(np.float32, copy=False)


def _speak_chatterbox(text: str, *, voice: str | None, config: dict) -> str:
    if voice is None:
        voice = str(config.get("chatterbox_voice") or "default")
    model = _get_chatterbox(_chatterbox_device(config))
    reference_path = _chatterbox_reference_path(config, voice)
    _prepare_chatterbox_voice(model, reference_path)
    generate_kwargs = _chatterbox_generate_kwargs(config)
    audio_chunks = []
    for chunk in _split_chatterbox_chunks(_chatterbox_tagged_text(text, config)):
        wav = model.generate(chunk, **generate_kwargs)
        audio_chunks.append(_chatterbox_samples_to_numpy(wav))
    if audio_chunks:
        sample_rate = int(model.sr)
        _play_audio(_concat_audio_chunks(audio_chunks, sample_rate), sample_rate)
    return "chatterbox"


def _speak_direct(text: str, voice: str | None = None, speed: float = 1.1):
    """Synthesize and speak text in this process."""
    if not text or not text.strip():
        return None

    config = get_config()
    provider = _tts_provider(config)

    # Acquire file lock to serialize concurrent TTS calls
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        if provider == "chatterbox":
            try:
                return _speak_chatterbox(text, voice=voice, config=config)
            except Exception as exc:  # noqa: BLE001
                print(f"[handsfree] Chatterbox speak failed: {exc}", file=sys.stderr)
        return _speak_kokoro(text, voice=voice, speed=speed, config=config)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def speak(text: str, voice: str | None = None, speed: float = 1.1):
    """Synthesize and speak text. Uses a warm daemon when available."""

    if not text or not text.strip():
        return
    if request_tts_daemon(text, voice=voice, speed=speed):
        return
    _speak_direct(text, voice=voice, speed=speed)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Speak text via the configured TTS provider")
    parser.add_argument("text", nargs="*", default=["Hello from Handsfree"])
    parser.add_argument("--voice", default=None, help="Voice name, preset, or blend spec")
    parser.add_argument("--speed", type=float, default=1.1, help="Speech speed (default: 1.1)")
    args = parser.parse_args()
    speak(" ".join(args.text), voice=args.voice, speed=args.speed)
