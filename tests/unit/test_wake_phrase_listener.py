from __future__ import annotations

from wake_phrase_listener import (
    is_bare_queue_command,
    looks_like_hallucination,
    parse_wake_phrase,
)


def test_parse_wake_phrase_extracts_command():
    match = parse_wake_phrase(
        "Hey Codex, run the tests.",
        ["handsfree", "hey codex"],
    )

    assert match is not None
    assert match.phrase == "hey codex"
    assert match.command == "run the tests"


def test_parse_wake_phrase_accepts_empty_command():
    match = parse_wake_phrase(
        "hands free",
        ["handsfree", "hands free"],
    )

    assert match is not None
    assert match.phrase == "hands free"
    assert match.command == ""


def test_parse_wake_phrase_ignores_unaddressed_speech():
    assert parse_wake_phrase("run the tests", ["handsfree"]) is None


def test_bare_queue_command_accepts_read_next_only():
    assert is_bare_queue_command("read next") is True
    assert is_bare_queue_command("what's up") is True
    assert is_bare_queue_command("what did I miss?") is True
    assert is_bare_queue_command("latest message") is True
    assert is_bare_queue_command("run the tests") is False


def test_hallucination_filter_rejects_repeated_noise_text():
    assert looks_like_hallucination("below " * 40, duration=2.0) is True
    assert looks_like_hallucination("hey codex run the tests", duration=2.0) is False
