#!/usr/bin/env python3
"""Benchmark Chatterbox Turbo TTS on this Mac.

Usage:
    uv run --python 3.11 scripts/benchmark_chatterbox.py [--ref path/to/reference.wav]

First run will download ~3.9 GB of model weights from HuggingFace.
"""

import argparse
import time
import sys
from pathlib import Path

# Patch resemble-perth watermarker if the native binary isn't available
# (common on Apple Silicon). The watermarker is cosmetic — it embeds an
# imperceptible audio watermark. Not needed for benchmarking.
try:
    import perth
    if perth.PerthImplicitWatermarker is None:
        perth.PerthImplicitWatermarker = perth.DummyWatermarker
except ImportError:
    pass

# VCTK p238 (22F, Northern Irish) — the voice selected during Fish Audio eval
DEFAULT_REF = Path.home() / "Code" / "fish-audio-local" / "voices" / "vctk-p238" / "reference.wav"


def main():
    parser = argparse.ArgumentParser(description="Benchmark Chatterbox Turbo TTS")
    parser.add_argument("--ref", type=Path, default=DEFAULT_REF,
                        help="Reference audio for voice cloning (default: VCTK p238)")
    parser.add_argument("--no-ref", action="store_true",
                        help="Use default built-in voice instead of cloning")
    parser.add_argument("--play-all", action="store_true",
                        help="Play all samples instead of just the first")
    args = parser.parse_args()

    ref_path = None if args.no_ref else args.ref
    if ref_path and not ref_path.exists():
        print(f"Reference audio not found: {ref_path}")
        print("Run with --no-ref to use the built-in default voice.")
        sys.exit(1)

    print("=" * 60)
    print("Chatterbox Turbo TTS — Apple Silicon Benchmark")
    print("=" * 60)
    if ref_path:
        print(f"  Voice: cloned from {ref_path.name}")
    else:
        print("  Voice: built-in default")

    # --- Step 1: Import & detect device ---
    print("\n[1/5] Importing torch...")
    t0 = time.perf_counter()
    import torch
    import torchaudio as ta
    print(f"      torch {torch.__version__} imported in {time.perf_counter() - t0:.1f}s")

    if torch.backends.mps.is_available():
        device = "mps"
        print(f"      Device: MPS (Apple Silicon GPU)")
    else:
        device = "cpu"
        print(f"      Device: CPU (MPS not available)")

    # --- Step 2: Load model ---
    print("\n[2/5] Loading Chatterbox Turbo (first run downloads ~3.9 GB)...")
    t0 = time.perf_counter()
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    load_time = time.perf_counter() - t0
    print(f"      Model loaded in {load_time:.1f}s")

    # --- Step 3: Pre-bake voice conditionals ---
    if ref_path:
        print(f"\n[3/5] Preparing voice from reference audio...")
        t0 = time.perf_counter()
        model.prepare_conditionals(str(ref_path))
        cond_time = time.perf_counter() - t0
        print(f"      Voice prepared in {cond_time:.1f}s")
    else:
        cond_time = 0
        print("\n[3/5] Using built-in default voice (no conditioning)")

    # --- Step 4: Benchmark generation ---
    test_cases = [
        ("Short", "Hello from Handsfree."),
        ("Medium", "The build completed successfully with no warnings. All 47 tests passed."),
        ("Long", "I've finished reviewing the pull request. There are three issues to address: "
                 "the retry logic needs a backoff, the error message could be more specific, "
                 "and there's a missing null check on line 42."),
        ("Expressive", "Oh wow, that actually worked! [laugh] I did not expect that to compile on the first try."),
    ]

    print("\n[4/5] Running generation benchmarks...")
    print(f"      {'Label':<12} {'Chars':>5}  {'Gen time':>9}  {'Audio len':>9}  {'RTF':>6}")
    print(f"      {'-'*12} {'-'*5}  {'-'*9}  {'-'*9}  {'-'*6}")

    wavs = []
    for label, text in test_cases:
        t0 = time.perf_counter()
        wav = model.generate(text)
        gen_time = time.perf_counter() - t0
        audio_len = wav.shape[-1] / model.sr
        rtf = gen_time / audio_len  # real-time factor: <1 means faster than real-time
        wavs.append((label, text, wav, gen_time, audio_len))
        print(f"      {label:<12} {len(text):>5}  {gen_time:>8.2f}s  {audio_len:>8.2f}s  {rtf:>5.2f}x")

    # --- Step 5: Play samples ---
    import tempfile
    import subprocess
    import os

    play_list = wavs if args.play_all else wavs[:1]
    print(f"\n[5/5] Playing {'all samples' if args.play_all else 'short sample'}...")
    for label, text, wav, _, _ in play_list:
        print(f"      [{label}] \"{text[:50]}{'...' if len(text) > 50 else ''}\"")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            ta.save(f.name, wav, model.sr)
            subprocess.run(["afplay", f.name], check=False)
            os.unlink(f.name)

    # --- Summary ---
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    avg_gen = sum(w[3] for w in wavs) / len(wavs)
    avg_audio = sum(w[4] for w in wavs) / len(wavs)
    avg_rtf = avg_gen / avg_audio
    print(f"  Voice:            {'p238 clone' if ref_path else 'built-in default'}")
    print(f"  Model load:       {load_time:.1f}s (one-time, daemon keeps warm)")
    if ref_path:
        print(f"  Voice prep:       {cond_time:.1f}s (one-time per voice)")
    print(f"  Avg generation:   {avg_gen:.2f}s")
    print(f"  Avg audio length: {avg_audio:.2f}s")
    print(f"  Avg RTF:          {avg_rtf:.2f}x {'(faster than real-time!)' if avg_rtf < 1 else '(slower than real-time)'}")
    print(f"  Device:           {device}")
    print()

    if avg_rtf < 1.0:
        print("  Verdict: Fast enough for interactive use.")
    elif avg_rtf < 2.0:
        print("  Verdict: Usable but noticeable delay. Short utterances OK.")
    else:
        print("  Verdict: Too slow for interactive voice assistant use.")

    print()


if __name__ == "__main__":
    main()
