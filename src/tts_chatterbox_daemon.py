#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["sounddevice", "soundfile", "numpy", "chatterbox-tts>=0.1.7"]
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///
"""Resident Chatterbox TTS daemon.

Chatterbox currently requires ``numpy<2`` while Kokoro v1 voices require a
newer ``kokoro-onnx`` stack. Keep this as a separate script environment so
provider selection does not force incompatible dependencies into one daemon.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["HANDSFREE_TTS_PROVIDER_FORCE"] = "chatterbox"

from tts_daemon import main


if __name__ == "__main__":
    raise SystemExit(main())
