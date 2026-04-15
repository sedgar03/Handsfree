from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _load_module(monkeypatch):
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    sys.modules.pop("permission_hook", None)
    module = importlib.import_module("permission_hook")
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    return module


def _patch_dedup_paths(module, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        module,
        "_session_path",
        lambda base, session_id: tmp_path / f"{base}-{session_id[:8] if session_id else 'unknown'}.json",
    )
    monkeypatch.setattr(
        module,
        "_dedup_lock_path",
        lambda session_id: tmp_path / f"permission-dedup-{session_id[:8] if session_id else 'unknown'}.lock",
    )


def test_permission_dedup_suppresses_immediate_duplicate(monkeypatch, tmp_path: Path):
    module = _load_module(monkeypatch)
    _patch_dedup_paths(module, monkeypatch, tmp_path)

    assert module._dedup_check("permission:Claude wants to use Read", "session-123") is False
    assert module._dedup_check("permission:Claude wants to use Read", "session-123") is True


def test_permission_dedup_allows_different_message(monkeypatch, tmp_path: Path):
    module = _load_module(monkeypatch)
    _patch_dedup_paths(module, monkeypatch, tmp_path)

    assert module._dedup_check("permission:Claude wants to use Read", "session-123") is False
    assert module._dedup_check("permission:Claude wants to run: pytest", "session-123") is False
