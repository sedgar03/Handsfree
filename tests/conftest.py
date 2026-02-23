from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
HOOKS = ROOT / "hooks"
TESTS = ROOT / "tests"

for path in (SRC, HOOKS, TESTS):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
