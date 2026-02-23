from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def hook_module(monkeypatch):
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    sys.modules.pop("handsfree_hook", None)
    module = importlib.import_module("handsfree_hook")
    monkeypatch.delenv("HANDSFREE_ACTIVE", raising=False)
    return module


def _write_transcript(tmp_path: Path, entries: list[dict]) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    with open(transcript, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return transcript


def test_extract_last_assistant_text_missing_or_empty_transcript(tmp_path: Path, hook_module):
    missing = tmp_path / "missing.jsonl"
    assert hook_module._extract_last_assistant_text(str(missing)) is None

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert hook_module._extract_last_assistant_text(str(empty)) is None


def test_extract_last_assistant_text_returns_last_text(tmp_path: Path, hook_module):
    transcript = _write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Earlier update"},
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Final text block"},
                        "and trailing string",
                    ]
                },
            },
        ],
    )

    result = hook_module._extract_last_assistant_text(str(transcript))
    assert result == "Final text block\nand trailing string"


def test_extract_last_assistant_text_ignores_tool_use(tmp_path: Path, hook_module):
    """AskUserQuestion tool_use blocks are ignored — handled by ask_question_hook."""
    ask_input = {
        "questions": [
            {
                "question": "Proceed?",
                "options": [{"label": "Yes"}, {"label": "No"}],
            }
        ]
    }
    transcript = _write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "AskUserQuestion",
                            "input": ask_input,
                        }
                    ]
                },
            }
        ],
    )

    # No text blocks → returns None
    result = hook_module._extract_last_assistant_text(str(transcript))
    assert result is None


def test_extract_last_assistant_text_with_mixed_content(tmp_path: Path, hook_module):
    """Text blocks are extracted; tool_use blocks are ignored."""
    transcript = _write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I did both things."},
                        {
                            "type": "tool_use",
                            "name": "AskUserQuestion",
                            "input": {"questions": []},
                        },
                    ]
                },
            }
        ],
    )

    result = hook_module._extract_last_assistant_text(str(transcript))
    assert result == "I did both things."


def test_extract_last_assistant_text_returns_newest(tmp_path: Path, hook_module):
    """Always returns the text from the most recent assistant message."""
    transcript = _write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Old text"}]},
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Newer plain text response"},
                    ]
                },
            },
        ],
    )

    result = hook_module._extract_last_assistant_text(str(transcript))
    assert result == "Newer plain text response"
