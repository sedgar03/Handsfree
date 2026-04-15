#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["kokoro-onnx", "sounddevice", "soundfile", "numpy", "chatterbox-tts>=0.1.7"]
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
from pathlib import Path

import numpy as np

# Allow imports from src/ when run from anywhere
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from chatterbox_markup import (
    CHATTERBOX_TAGS,
    extract_chatterbox_tags,
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
# Lazy-initialized Kokoro instance
_kokoro = None
_chatterbox = None
_chatterbox_conditioned_ref: str | None = None
_chatterbox_device_name: str | None = None


def _get_kokoro():
    """Lazy-init Kokoro. Returns the Kokoro instance or None if models missing."""
    global _kokoro
    if _kokoro is not None:
        return _kokoro

    if not KOKORO_MODEL.exists() or not KOKORO_VOICES.exists():
        return None

    try:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
        return _kokoro
    except Exception as e:
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


def _text_matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _infer_chatterbox_tags(text: str, strength: float) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    if strength < 0.15:
        return []

    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    if _text_matches(normalized, (r"\b(sorry|apologize|apologies|unfortunately)\b",)):
        add("sigh")
    if _text_matches(
        normalized,
        (
            r"\b(error|failed|failure|failing|broken|blocked|timeout|exception|crash|denied)\b",
            r"\bcould not\b",
            r"\bcan't\b",
            r"\bunable\b",
        ),
    ):
        add("sigh")
        if strength > 0.55:
            add("dramatic")
    if _text_matches(normalized, (r"\b(permission|allow or deny|needs approval)\b",)):
        add("clear throat")
    if _text_matches(
        normalized,
        (
            r"\b(passed|green|success|succeeded|complete|completed|done|fixed|merged|deployed)\b",
            r"\ball tests\b",
        ),
    ):
        add("happy")
    if _text_matches(
        normalized,
        (
            r"\b(wait|unexpected|surprising|surprised|actually worked|first try)\b",
            r"\?",
        ),
    ):
        add("surprised")
    if _text_matches(normalized, (r"\b(lol|haha|funny|laugh|hilarious)\b",)):
        add("laugh" if strength > 0.65 else "chuckle")
    if _text_matches(
        normalized,
        (
            r"\b(of course|classic|sure, let's|totally going to|what could go wrong)\b",
        ),
    ):
        add("sarcastic")
    if _text_matches(normalized, (r"\b(secret|quietly|don't tell|do not tell)\b",)):
        add("whispering")
    if _text_matches(
        normalized,
        (
            r"\b(production|prod|database|cluster|security|leak|on fire|no backups)\b",
        ),
    ):
        add("dramatic")
        if strength > 0.75:
            add("fear")

    if _text_matches(
        normalized,
        (
            r"\b(all my work is gone|lost everything|force-pushed|branch is gone)\b",
        ),
    ):
        add("crying")

    return tags


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


def _auto_chatterbox_tagged_text(text: str, strength: float) -> str:
    budget = _chatterbox_tag_budget(strength)
    if budget <= 0:
        return text

    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    if not sentences:
        return text

    remaining = budget
    rendered: list[str] = []
    for sentence in sentences:
        tags = _infer_chatterbox_tags(sentence, strength)
        if tags and remaining > 0:
            tag_count = 1
            if strength > 0.75:
                tag_count = min(2, len(tags), remaining)
            selected = tags[:tag_count]
            sentence = "".join(f"[{tag}]" for tag in selected) + f" {sentence}"
            remaining -= len(selected)
        rendered.append(sentence)
    return " ".join(rendered)


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
        if extract_chatterbox_tags(text):
            return text
        return _auto_chatterbox_tagged_text(text, strength)
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


def _play_audio(samples, sample_rate: int):
    """Play audio samples through the default output device."""
    import sounddevice as sd
    sd.play(samples, samplerate=sample_rate)
    sd.wait()


def _say_fallback(text: str):
    """macOS say command as TTS fallback."""
    subprocess.run(["say", text], check=False)


def _warm_kokoro() -> dict:
    kokoro = _get_kokoro()
    if kokoro is None:
        return {"ok": True, "engine": "say", "ready": True}
    return {"ok": True, "engine": "kokoro", "ready": True}


def _warm_chatterbox(config: dict) -> dict:
    voice = str(config.get("chatterbox_voice") or "default")
    model = _get_chatterbox(_chatterbox_device(config))
    reference_path = _chatterbox_reference_path(config, voice)
    voice_source = _prepare_chatterbox_voice(model, reference_path)
    return {
        "ok": True,
        "engine": "chatterbox",
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
    wav = model.generate(
        _chatterbox_tagged_text(text, config),
        **_chatterbox_generate_kwargs(config),
    )
    _play_audio(_chatterbox_samples_to_numpy(wav), int(model.sr))
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
