#!/usr/bin/env python3
"""Chatterbox Turbo — vocal/physical sounds showcase.

Tests non-emotion vocal effects: panting, deep breaths, yawns, throat-clearing,
hesitation, stammering, etc. These are generally harder than pure emotion and
may or may not be honored depending on the tag.

Usage:
    uv run --python 3.11 --with chatterbox-tts scripts/chatterbox_vocal_sounds_demo.py
"""

import time
import sys
import subprocess
from pathlib import Path

import perth
if perth.PerthImplicitWatermarker is None:
    perth.PerthImplicitWatermarker = perth.DummyWatermarker

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = Path.home() / "Code" / "fish-audio-local" / "voices" / "vctk-p238" / "reference.wav"
OUTPUT_DIR = REPO_ROOT / "outputs" / "chatterbox_vocal_sounds"

# Physical/vocal effects to audition. Chatterbox officially documents only
# [laugh], [chuckle], [cough]. We're testing how far the model generalizes.
# Fallback technique: write the effect as onomatopoeia in the prose itself.
SAMPLES = [
    # --- Breath / breathing ---
    ("deep_breath_tag",
     "[deep breath] Okay. Let me think about this for a second."),

    ("deep_breath_prose",
     "Hhhhh... okay. Let me think about this for a second."),

    ("sigh_deep",
     "[sigh] I don't even know where to start with this codebase."),

    ("exhale",
     "[exhale] Fine. Let's just roll back the release and start over."),

    # --- Panting / out of breath ---
    ("panting_tag",
     "[panting] I— I ran all the way here. The server's down. It's down!"),

    ("panting_prose",
     "I— huh— I ran all the way here. The server's— huh— it's down!"),

    # --- Yawn ---
    ("yawn_tag",
     "[yawn] Sorry, what were we debugging again?"),

    ("yawn_prose",
     "Ahhhwwwn... sorry, what were we debugging again?"),

    # --- Throat clearing ---
    ("throat_clear_tag",
     "[clears throat] Right. So. About that pull request you opened."),

    ("ahem",
     "Ahem. Right. So. About that pull request you opened."),

    # --- Cough (officially supported) ---
    ("cough",
     "The logs are completely— [cough] sorry, the logs are completely unreadable."),

    # --- Hesitation / stammering ---
    ("hesitation",
     "Uh, well, I— I think maybe the, um, the config might be, you know, wrong?"),

    ("stammer",
     "W- w- wait, you— you actually merged that? Without review?"),

    # --- Groan / grunt ---
    ("groan",
     "Ugggggh. Not another merge conflict. Why does this always happen to me?"),

    ("grunt",
     "Hmph. Fine. I'll rebase it manually."),

    # --- Sniff / scoff ---
    ("sniff",
     "Hmph— *sniff*— no, I'm fine. Really. Everything is fine."),

    ("scoff",
     "Pfft. You really think that's going to scale past ten users?"),

    # --- Pause / trailing ---
    ("trailing",
     "I... I don't know anymore. Maybe we should just... start over."),

    # --- Mixed: breath + laugh ---
    ("breath_laugh",
     "[deep breath] [laugh] Okay, I needed that. Let's do this."),
]


def main():
    print("=" * 60)
    print("Chatterbox Turbo — Vocal Sounds Showcase")
    print(f"Voice: VCTK p238 (22F, Northern Irish)")
    print("=" * 60)

    if not REFERENCE.exists():
        print(f"Reference audio not found: {REFERENCE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/3] Loading model...")
    t0 = time.perf_counter()
    import torch
    import torchaudio as ta
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"      Device: {device}")
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    print(f"      Loaded in {time.perf_counter() - t0:.1f}s")

    print(f"\n[2/3] Cloning voice from {REFERENCE.name}...")
    t0 = time.perf_counter()
    model.prepare_conditionals(str(REFERENCE))
    print(f"      Voice prepared in {time.perf_counter() - t0:.1f}s")

    # Suppress generation progress bars for cleaner output
    import os
    os.environ["TQDM_DISABLE"] = "1"

    print(f"\n[3/3] Generating {len(SAMPLES)} vocal samples...")
    generated = []
    for label, text in SAMPLES:
        t0 = time.perf_counter()
        wav = model.generate(text)
        gen_time = time.perf_counter() - t0
        audio_len = wav.shape[-1] / model.sr
        rtf = gen_time / audio_len

        out_path = OUTPUT_DIR / f"{label}.wav"
        ta.save(str(out_path), wav, model.sr)
        generated.append((label, text, out_path))
        print(f"      {label:<22} gen={gen_time:>4.1f}s  audio={audio_len:>4.1f}s  rtf={rtf:.2f}x")

    # Playback
    print("\n" + "=" * 60)
    print("Playback")
    print("=" * 60)
    for label, text, path in generated:
        print(f"\n  [{label}]")
        print(f"  \"{text}\"")
        subprocess.run(["afplay", str(path)], check=False)
        time.sleep(0.3)

    print(f"\nSaved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
