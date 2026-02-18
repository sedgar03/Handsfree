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


def test_extract_last_assistant_missing_or_empty_transcript(tmp_path: Path, hook_module):
    missing = tmp_path / "missing.jsonl"
    assert hook_module._extract_last_assistant(str(missing)) is None

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert hook_module._extract_last_assistant(str(empty)) is None


def test_extract_last_assistant_text_only_entries(tmp_path: Path, hook_module):
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

    result = hook_module._extract_last_assistant(str(transcript))
    assert result == {
        "text": "Final text block\nand trailing string",
        "ask_question": None,
    }


def test_extract_last_assistant_tool_use_only_entry(tmp_path: Path, hook_module):
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

    result = hook_module._extract_last_assistant(str(transcript))
    assert result == {"text": None, "ask_question": ask_input}


def test_extract_last_assistant_mixed_content_same_entry_prefers_text(tmp_path: Path, hook_module):
    ask_input = {
        "questions": [{"question": "Pick one", "options": [{"label": "A"}, {"label": "B"}]}]
    }
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
                            "input": ask_input,
                        },
                    ]
                },
            }
        ],
    )

    result = hook_module._extract_last_assistant(str(transcript))
    assert result == {"text": "I did both things.", "ask_question": None}


def test_extract_last_assistant_prefers_newer_question_over_older_text(tmp_path: Path, hook_module):
    ask_input = {
        "questions": [{"question": "Need input", "options": [{"label": "A"}, {"label": "B"}]}]
    }
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
                        {
                            "type": "tool_use",
                            "name": "AskUserQuestion",
                            "input": ask_input,
                        }
                    ]
                },
            },
        ],
    )

    result = hook_module._extract_last_assistant(str(transcript))
    assert result == {"text": None, "ask_question": ask_input}


def test_extract_last_assistant_prefers_newer_text_over_older_question(tmp_path: Path, hook_module):
    ask_input = {
        "questions": [{"question": "Old question", "options": [{"label": "A"}, {"label": "B"}]}]
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

    result = hook_module._extract_last_assistant(str(transcript))
    assert result == {"text": "Newer plain text response", "ask_question": None}
