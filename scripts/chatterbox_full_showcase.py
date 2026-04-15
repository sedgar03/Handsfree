#!/usr/bin/env python3
"""Chatterbox Turbo — full tag showcase with announcements + stacking tests.

For each sample: generates an announcement in the cloned voice saying which
tag(s) will be used, then plays the tagged sample. Also tests whether tags
can be stacked for amplification or combined for hybrid effects.

Usage:
    uv run --python 3.11 --with chatterbox-tts scripts/chatterbox_full_showcase.py
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
OUTPUT_DIR = REPO_ROOT / "outputs" / "chatterbox_full_showcase"

# All 19 tags from the Turbo tokenizer's added_tokens.json (IDs 50257-50275).
# Each entry: (tag_list, announcement, tagged_text)
SAMPLES = [
    # --- 10 emotion tags ---
    (["angry"],
     "This is the angry tag.",
     "[angry] How many times do I have to tell you? Do not push to main!"),

    (["fear"],
     "This is the fear tag.",
     "[fear] Something is wrong. The logs are full of errors I've never seen before."),

    (["surprised"],
     "This is the surprised tag.",
     "[surprised] Wait, it actually deployed? On the first try?"),

    (["whispering"],
     "This is the whispering tag.",
     "[whispering] Don't tell anyone, but I think the staging environment points at prod."),

    (["advertisement"],
     "This is the advertisement tag.",
     "[advertisement] Tired of slow builds? Try our new blazing-fast CI pipeline, starting at just nine dollars a month!"),

    (["dramatic"],
     "This is the dramatic tag.",
     "[dramatic] And then, just as the merge was about to succeed, the pipeline collapsed."),

    (["narration"],
     "This is the narration tag.",
     "[narration] The year is twenty twenty six. Handsfree mode has taken over every terminal in the valley."),

    (["crying"],
     "This is the crying tag.",
     "[crying] All my work. All my work is gone. The branch was force-pushed."),

    (["happy"],
     "This is the happy tag.",
     "[happy] The tests passed! Every single one of them passed!"),

    (["sarcastic"],
     "This is the sarcastic tag.",
     "[sarcastic] Oh sure, let's add another microservice. That'll definitely fix everything."),

    # --- 9 sound effect tags ---
    (["clear throat"],
     "This is the clear throat tag.",
     "[clear throat] Right. So. About that pull request you opened."),

    (["sigh"],
     "This is the sigh tag.",
     "[sigh] Okay, one more deploy, then I'm done for the day."),

    (["shush"],
     "This is the shush tag.",
     "[shush] The production server is finally asleep. Don't wake it."),

    (["cough"],
     "This is the cough tag.",
     "The logs are completely— [cough] sorry, the logs are completely unreadable."),

    (["groan"],
     "This is the groan tag.",
     "[groan] Not another merge conflict. Why does this always happen?"),

    (["sniff"],
     "This is the sniff tag.",
     "[sniff] It's fine. I'm fine. Everything is fine."),

    (["gasp"],
     "This is the gasp tag.",
     "[gasp] Wait, you're telling me that was in production the whole time?"),

    (["chuckle"],
     "This is the chuckle tag.",
     "[chuckle] I told you that regex was going to cause problems eventually."),

    (["laugh"],
     "This is the laugh tag.",
     "Wait, you deployed on a Friday afternoon? [laugh] That's going to be fun on Monday."),

    # --- Stacking experiments ---
    (["angry", "angry", "angry"],
     "Stacking test: angry, angry, angry.",
     "[angry][angry][angry] How many times do I have to tell you? Do not push to main!"),

    (["happy", "happy", "happy"],
     "Stacking test: happy, happy, happy.",
     "[happy][happy][happy] The tests passed! Every single one of them passed!"),

    (["angry", "fear"],
     "Stacking test: angry plus fear.",
     "[angry][fear] The database is on fire and you're telling me we have no backups?"),

    (["happy", "surprised"],
     "Stacking test: happy plus surprised.",
     "[happy][surprised] Wait, we actually hit all our metrics this quarter?"),

    (["whispering", "sarcastic"],
     "Stacking test: whispering plus sarcastic.",
     "[whispering][sarcastic] Oh yeah, this architecture is totally going to scale."),

    (["crying", "laugh"],
     "Stacking test: crying plus laugh.",
     "[crying][laugh] I don't know whether to cry or laugh at this point."),

    (["dramatic", "dramatic"],
     "Stacking test: dramatic, dramatic.",
     "[dramatic][dramatic] And then, the entire cluster went dark."),
]


def safe_label(tags):
    return "_".join(t.replace(" ", "-") for t in tags)


def main():
    print("=" * 60)
    print("Chatterbox Turbo — Full Tag Showcase")
    print(f"Voice: VCTK p238 (22F, Northern Irish)")
    print(f"Samples: {len(SAMPLES)} (19 individual + 7 stacking)")
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

    import os
    os.environ["TQDM_DISABLE"] = "1"

    print(f"\n[3/3] Generating {len(SAMPLES) * 2} clips (announcement + sample each)...")
    generated = []
    for idx, (tags, announcement, text) in enumerate(SAMPLES, 1):
        label = safe_label(tags)

        # Announcement (no tags — plain delivery)
        ann_path = OUTPUT_DIR / f"{idx:02d}_{label}_announce.wav"
        t0 = time.perf_counter()
        wav_ann = model.generate(announcement)
        ann_time = time.perf_counter() - t0
        ta.save(str(ann_path), wav_ann, model.sr)

        # Tagged sample
        sample_path = OUTPUT_DIR / f"{idx:02d}_{label}_sample.wav"
        t0 = time.perf_counter()
        wav_sample = model.generate(text)
        sample_time = time.perf_counter() - t0
        ta.save(str(sample_path), wav_sample, model.sr)

        generated.append((tags, announcement, text, ann_path, sample_path))
        print(f"      {idx:2d}. {label:<35} ann={ann_time:>4.1f}s  sample={sample_time:>4.1f}s")

    # Playback
    print("\n" + "=" * 60)
    print("Playback")
    print("=" * 60)
    for idx, (tags, announcement, text, ann_path, sample_path) in enumerate(generated, 1):
        tag_str = ", ".join(f"[{t}]" for t in tags)
        print(f"\n  {idx:2d}. {tag_str}")
        subprocess.run(["afplay", str(ann_path)], check=False)
        time.sleep(0.2)
        subprocess.run(["afplay", str(sample_path)], check=False)
        time.sleep(0.4)

    print(f"\nSaved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
