#!/usr/bin/env python3
"""Chatterbox Turbo — expressivity showcase.

Generates a series of emotionally expressive samples using VCTK p238 as the
cloned voice, and plays each one back in sequence. Saves WAVs to outputs/.

Usage:
    uv run --python 3.11 --with chatterbox-tts scripts/chatterbox_expressivity_demo.py
"""

import time
import sys
import subprocess
from pathlib import Path

# Patch resemble-perth watermarker (native binary missing on Apple Silicon)
import perth
if perth.PerthImplicitWatermarker is None:
    perth.PerthImplicitWatermarker = perth.DummyWatermarker

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = Path.home() / "Code" / "fish-audio-local" / "voices" / "vctk-p238" / "reference.wav"
OUTPUT_DIR = REPO_ROOT / "outputs" / "chatterbox_expressivity"

# Showcase of expressive utterances. Chatterbox Turbo supports inline
# paralinguistic tags like [laugh], [chuckle], [cough]. Community has reported
# varying success with [sigh], [gasp], [sob], [whisper]. Tonal expressivity
# (sarcasm, sadness) also emerges from phrasing, punctuation, and context.
SAMPLES = [
    ("laugh",
     "Wait, you deployed on a Friday afternoon? [laugh] Oh, that's going to be fun on Monday."),

    ("chuckle",
     "[chuckle] I told you that regex was going to cause problems eventually."),

    ("sarcasm_dry",
     "Oh, fantastic. Another meeting that could have been an email. I just love my job."),

    ("sarcasm_sharp",
     "Sure, let's just add another microservice. That'll definitely solve the problem."),

    ("excitement",
     "Oh my god, the tests actually passed on the first try! I can't believe it!"),

    ("sadness",
     "I... I thought we had this working. I spent all weekend on it, and it's still broken."),

    ("sigh_tired",
     "[sigh] Okay, one more deploy, then I'm going home. I've been at this for twelve hours."),

    ("gasp",
     "[gasp] Wait, you're telling me that was in production the whole time?"),

    ("whisper",
     "[whisper] Don't tell anyone, but I think the staging environment is actually pointing at prod."),

    ("mixed_reaction",
     "You rewrote the whole thing in Rust? [laugh] Of course you did. Of course you did."),

    ("frustration",
     "Why. Why is it still failing? I've tried everything. The cache is cleared, the config is right, the deps are pinned!"),

    ("relief",
     "[sigh] Finally. The build is green. We can go home."),
]


def main():
    print("=" * 60)
    print("Chatterbox Turbo — Expressivity Showcase")
    print(f"Voice: VCTK p238 (22F, Northern Irish)")
    print("=" * 60)

    if not REFERENCE.exists():
        print(f"Reference audio not found: {REFERENCE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load
    print("\n[1/3] Loading model...")
    t0 = time.perf_counter()
    import torch
    import torchaudio as ta
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"      Device: {device}")
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    print(f"      Loaded in {time.perf_counter() - t0:.1f}s")

    # Clone voice
    print(f"\n[2/3] Cloning voice from {REFERENCE.name}...")
    t0 = time.perf_counter()
    model.prepare_conditionals(str(REFERENCE))
    print(f"      Voice prepared in {time.perf_counter() - t0:.1f}s")

    # Generate all samples first, then play
    print(f"\n[3/3] Generating {len(SAMPLES)} expressive samples...")
    print(f"      {'Label':<18} {'Gen':>6}  {'Audio':>6}  {'RTF':>5}")
    print(f"      {'-'*18} {'-'*6}  {'-'*6}  {'-'*5}")

    generated = []
    for label, text in SAMPLES:
        t0 = time.perf_counter()
        wav = model.generate(text)
        gen_time = time.perf_counter() - t0
        audio_len = wav.shape[-1] / model.sr
        rtf = gen_time / audio_len

        out_path = OUTPUT_DIR / f"{label}.wav"
        ta.save(str(out_path), wav, model.sr)
        generated.append((label, text, out_path, gen_time, audio_len))
        print(f"      {label:<18} {gen_time:>5.1f}s  {audio_len:>5.1f}s  {rtf:>4.2f}x")

    # Play in sequence with labels
    print("\n" + "=" * 60)
    print("Playback")
    print("=" * 60)
    for label, text, path, _, _ in generated:
        print(f"\n  [{label}]")
        print(f"  \"{text}\"")
        subprocess.run(["afplay", str(path)], check=False)
        time.sleep(0.3)  # small gap between samples

    print(f"\nSaved to: {OUTPUT_DIR}")
    print()


if __name__ == "__main__":
    main()
