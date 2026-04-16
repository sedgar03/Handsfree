from __future__ import annotations

import conductor_harness
from conductor_harness import ConductorHarness


def test_strip_thinking_markup_removes_hidden_reasoning():
    text = "Before. <think>private chain</think> After."

    assert conductor_harness.strip_thinking_markup(text) == "Before.  After."


def test_parse_tool_call_accepts_plain_and_fenced_json():
    assert conductor_harness.parse_tool_call('{"tool":"list_panes","args":{}}') == {
        "name": "list_panes",
        "args": {},
    }
    assert conductor_harness.parse_tool_call(
        '```json\n{"tool_call":{"name":"read_pane","arguments":{"pane_id":"%3"}}}\n```'
    ) == {
        "name": "read_pane",
        "args": {"pane_id": "%3"},
    }


def test_tool_result_message_prefers_spoken_summary():
    message = conductor_harness.tool_result_message(
        "list_panes",
        {"ok": True, "spoken_summary": "I see one tmux pane."},
    )

    assert "spoken_summary" in message
    assert "prefer that wording" in message


def test_harness_history_is_bounded():
    harness = ConductorHarness(
        complete_chat=lambda _messages: "response",
        load_system_prompt=lambda: "system",
        history_turns=2,
        transcript_enabled=False,
    )

    for idx in range(4):
        harness.chat(f"turn {idx}", conversation_id="work")

    history = harness.histories["work"]
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "turn 2"}


def test_harness_writes_transcript_when_enabled():
    events = []
    harness = ConductorHarness(
        complete_chat=lambda _messages: "response",
        load_system_prompt=lambda: "system",
        transcript_enabled=True,
        transcript_writer=lambda conversation_id, event_type, **kwargs: events.append(
            (conversation_id, event_type, kwargs)
        ),
    )

    harness.chat("help me plan", conversation_id="voice")

    assert events == [
        ("voice", "user", {"text": "help me plan"}),
        ("voice", "assistant", {"text": "response"}),
    ]


def test_harness_executes_tool_call_then_answers():
    tool_calls = []
    responses = iter(
        [
            '{"tool":"list_panes","args":{}}',
            "I see one tmux pane: work.",
        ]
    )
    completions = []
    events = []

    def fake_complete(messages):
        completions.append(list(messages))
        return next(responses)

    harness = ConductorHarness(
        complete_chat=fake_complete,
        load_system_prompt=lambda: "system",
        transcript_enabled=True,
        tool_executor=lambda name, args: tool_calls.append((name, args))
        or {
            "ok": True,
            "panes": [{"pane_id": "%3", "window": "work"}],
            "summary": "%3: work",
        },
        transcript_writer=lambda conversation_id, event_type, **kwargs: events.append(
            (conversation_id, event_type, kwargs)
        ),
    )

    response = harness.chat("what tmux panes are open?", conversation_id="voice")

    assert response == "I see one tmux pane: work."
    assert tool_calls == [("list_panes", {})]
    assert "Tool result for list_panes" in completions[1][-1]["content"]
    assert harness.histories["voice"][-1] == {
        "role": "assistant",
        "content": "I see one tmux pane: work.",
    }
    assert [event[1] for event in events] == ["user", "tool", "assistant"]
    assert events[1][2]["data"]["name"] == "list_panes"


def test_harness_passes_original_user_text_to_tool_executor():
    seen = []
    responses = iter(
        [
            '{"tool":"send_text_to_pane","args":{"pane_id":"%3","text":"git status","submit":false}}',
            "Drafted.",
        ]
    )

    harness = ConductorHarness(
        complete_chat=lambda _messages: next(responses),
        load_system_prompt=lambda: "system",
        transcript_enabled=False,
        tool_executor=lambda name, args, **kwargs: seen.append((name, args, kwargs))
        or {"ok": True},
    )

    harness.chat("type git status into pane %3", conversation_id="voice")

    assert seen == [
        (
            "send_text_to_pane",
            {"pane_id": "%3", "text": "git status", "submit": False},
            {"user_text": "type git status into pane %3"},
        )
    ]
