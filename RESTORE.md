# Handsfree -- Setup Guide

Local voice layer for Claude Code on macOS.

## Quick Start

```bash
git clone https://github.com/sedgar03/Handsfree.git
cd Handsfree
./scripts/setup.sh
```

`setup.sh` is intentionally minimal. It downloads only baseline resources needed
for the default Kokoro/Whisper path, installs hooks, and writes config. Optional
heavy resources such as Chatterbox weights, local GGUF models, custom voice
references, and generated outputs are opt-in; see `docs/LOCAL_RESOURCES.md`.

## Editable Install

```bash
pip install -e .
```
