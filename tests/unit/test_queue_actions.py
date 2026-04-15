from __future__ import annotations

import sys
import types

import event_queue
import queue_actions


def _event(*, kind: str = "summary", workflow: str = "USChem", summary: str = "No input needed. Done."):
    return event_queue.AgentEvent(
        id=1,
        created_at=1.0,
        updated_at=1.0,
        source="claude",
        kind=kind,
        priority=0,
        workflow=workflow,
        summary=summary,
        detail="",
        target_pane="%1",
        target_cwd="/tmp",
        transcript_path="",
        session_id="session",
        status="pending",
        payload={},
    )


def test_spoken_event_text_starts_with_workflow_intro():
    text = queue_actions._spoken_event_text(_event())

    assert text == "USChem here. No input needed. Done"


def test_spoken_permission_includes_allow_deny_prompt():
    text = queue_actions._spoken_event_text(
        _event(kind="permission", summary="Claude wants to use Read")
    )

    assert text == "USChem here. Permission needed. Claude wants to use Read. Say allow or deny"


def test_workflow_intro_ignores_empty_label():
    assert queue_actions.workflow_intro_text("") == ""


def test_speak_event_pauses_between_intro_and_body(monkeypatch):
    calls = []

    monkeypatch.setattr(queue_actions, "get_config", lambda: {"tts_provider": "kokoro"})
    monkeypatch.setattr(queue_actions, "_speak", lambda text: calls.append(("speak", text)) or True)
    monkeypatch.setattr(queue_actions.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert queue_actions.speak_event(_event()) is True

    assert calls == [
        ("speak", "USChem here."),
        ("sleep", queue_actions.INTRO_PAUSE_SECONDS),
        ("speak", "No input needed. Done."),
    ]


def test_speak_event_combines_intro_and_body_for_chatterbox(monkeypatch):
    calls = []

    monkeypatch.setattr(queue_actions, "get_config", lambda: {"tts_provider": "chatterbox"})
    monkeypatch.setattr(queue_actions, "_speak", lambda text: calls.append(text) or True)
    monkeypatch.setattr(queue_actions.time, "sleep", lambda _seconds: calls.append("sleep"))

    assert queue_actions.speak_event(_event()) is True

    assert calls == ["USChem here. No input needed. Done"]


def test_speak_event_can_force_split_for_chatterbox(monkeypatch):
    calls = []

    monkeypatch.setattr(
        queue_actions,
        "get_config",
        lambda: {"tts_provider": "chatterbox", "queue_intro_mode": "split"},
    )
    monkeypatch.setattr(queue_actions, "_speak", lambda text: calls.append(("speak", text)) or True)
    monkeypatch.setattr(queue_actions.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    assert queue_actions.speak_event(_event()) is True

    assert calls == [
        ("speak", "USChem here."),
        ("sleep", queue_actions.INTRO_PAUSE_SECONDS),
        ("speak", "No input needed. Done."),
    ]


def test_speak_event_without_intro_speaks_once(monkeypatch):
    calls = []

    monkeypatch.setattr(queue_actions, "get_config", lambda: {"interaction_mode": "on_demand"})
    monkeypatch.setattr(queue_actions, "_speak", lambda text: calls.append(text) or True)
    monkeypatch.setattr(queue_actions.time, "sleep", lambda _seconds: calls.append("sleep"))

    assert queue_actions.speak_event(_event(workflow="")) is True

    assert calls == ["No input needed. Done."]


def test_speak_event_routes_through_conductor_in_conductor_mode(monkeypatch):
    requests = []
    starts = []
    spoken = []
    event = _event(summary="Tests passed. No input needed.")

    monkeypatch.setattr(queue_actions, "get_config", lambda: {"interaction_mode": "conductor"})
    fake_service_control = types.SimpleNamespace(
        start_conductor_daemon=lambda **kwargs: starts.append(kwargs) or {"ok": True}
    )

    def fake_request(text, **kwargs):
        requests.append((text, kwargs))
        return {"ok": True, "response": "USChem finished; tests passed."}

    monkeypatch.setitem(sys.modules, "service_control", fake_service_control)
    monkeypatch.setitem(sys.modules, "conductor_client", types.SimpleNamespace(request_conductor=fake_request))
    monkeypatch.setattr(queue_actions, "_speak", lambda text: spoken.append(text) or True)

    assert queue_actions.speak_event(event) is True

    assert starts == [{"wait": True, "timeout": 120.0}]
    assert len(requests) == 1
    assert "A terminal agent event needs spoken handling." in requests[0][0]
    assert "workflow: USChem" in requests[0][0]
    assert "summary: Tests passed. No input needed." in requests[0][0]
    assert requests[0][1]["conversation_id"] == "event:claude:session"
    assert spoken == ["USChem finished; tests passed."]


def test_speak_event_falls_back_to_direct_when_conductor_unavailable(monkeypatch):
    spoken = []
    event = _event(summary="Tests passed. No input needed.")

    monkeypatch.setattr(
        queue_actions,
        "get_config",
        lambda: {"interaction_mode": "conductor", "tts_provider": "chatterbox"},
    )
    monkeypatch.setitem(
        sys.modules,
        "service_control",
        types.SimpleNamespace(start_conductor_daemon=lambda **_kwargs: {"ok": True}),
    )
    monkeypatch.setitem(
        sys.modules,
        "conductor_client",
        types.SimpleNamespace(request_conductor=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(queue_actions, "_speak", lambda text: spoken.append(text) or True)

    assert queue_actions.speak_event(event) is True

    assert spoken == ["USChem here. Tests passed. No input needed"]


def test_speak_starts_tts_daemon_when_client_is_unavailable(monkeypatch):
    requests = []
    starts = []

    def fake_request(text, **kwargs):
        requests.append((text, kwargs))
        return len(requests) > 1

    fake_tts_client = types.SimpleNamespace(request_tts_daemon=fake_request)
    fake_service_control = types.SimpleNamespace(
        start_tts_daemon=lambda **kwargs: starts.append(kwargs) or {"ok": True}
    )
    monkeypatch.setitem(sys.modules, "tts_client", fake_tts_client)
    monkeypatch.setitem(sys.modules, "service_control", fake_service_control)
    monkeypatch.setitem(
        sys.modules,
        "tts",
        types.SimpleNamespace(
            speak=lambda _text: (_ for _ in ()).throw(
                AssertionError("direct TTS should not run after daemon starts")
            )
        ),
    )

    assert queue_actions._speak("No queued messages.") is True

    assert starts == [{"wait": True, "timeout": 240.0}]
    assert requests == [
        ("No queued messages.", {}),
        ("No queued messages.", {"connect_timeout": 5.0}),
    ]


def test_read_next_event_marks_spoken_event_done(monkeypatch):
    event = _event()
    statuses = []

    monkeypatch.setattr(queue_actions, "queue_consume_after_timestamp", lambda: 123.0)
    monkeypatch.setattr(
        queue_actions,
        "activate_next_event",
        lambda created_after: event if created_after == 123.0 else None,
    )
    monkeypatch.setattr(queue_actions, "speak_event", lambda spoken: spoken == event)
    monkeypatch.setattr(
        queue_actions,
        "update_event_status",
        lambda event_id, status: statuses.append((event_id, status)),
    )

    assert queue_actions.read_next_event() == event
    assert statuses == [(event.id, "done")]


def test_read_next_event_leaves_failed_speech_active(monkeypatch):
    event = _event()
    statuses = []

    monkeypatch.setattr(queue_actions, "queue_consume_after_timestamp", lambda: 123.0)
    monkeypatch.setattr(queue_actions, "activate_next_event", lambda created_after: event)
    monkeypatch.setattr(queue_actions, "speak_event", lambda _event: False)
    monkeypatch.setattr(
        queue_actions,
        "update_event_status",
        lambda event_id, status: statuses.append((event_id, status)),
    )

    assert queue_actions.read_next_event() == event
    assert statuses == []


def test_handle_conductor_text_speaks_conductor_response(monkeypatch):
    starts = []
    requests = []
    spoken = []

    fake_service_control = types.SimpleNamespace(
        start_conductor_daemon=lambda **kwargs: starts.append(kwargs) or {"ok": True}
    )

    def fake_request(text, **kwargs):
        requests.append((text, kwargs))
        return {"ok": True, "response": "You have two panes open."}

    fake_conductor_client = types.SimpleNamespace(request_conductor=fake_request)
    monkeypatch.setitem(sys.modules, "service_control", fake_service_control)
    monkeypatch.setitem(sys.modules, "conductor_client", fake_conductor_client)
    monkeypatch.setattr(
        queue_actions,
        "_tmux_panes_snapshot",
        lambda: "0:1.1 %1 cwd=/tmp command=zsh title=shell",
    )
    monkeypatch.setattr(queue_actions, "_speak", lambda text: spoken.append(text) or True)

    assert queue_actions.handle_conductor_text("help me plan the next step") is True

    assert starts == [{"wait": True, "timeout": 120.0}]
    assert len(requests) == 1
    assert "Current tmux panes:" in requests[0][0]
    assert "0:1.1 %1 cwd=/tmp command=zsh title=shell" in requests[0][0]
    assert "User said: help me plan the next step" in requests[0][0]
    assert requests[0][1]["conversation_id"] == "voice"
    assert spoken == ["You have two panes open."]


def test_handle_conductor_text_answers_tmux_panes_directly(monkeypatch):
    spoken = []
    fake_service_control = types.SimpleNamespace(
        start_conductor_daemon=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("exact tmux inventory should not call conductor")
        )
    )
    monkeypatch.setitem(sys.modules, "service_control", fake_service_control)
    monkeypatch.setattr(
        queue_actions,
        "_tmux_panes_snapshot",
        lambda: "\n".join(
            [
                "0:1.1\t%1\tHands-free\t/Users/me/Code/handsfree\tnode\thandsfree\t1",
                "0:2.1\t%2\tPain\t/Users/me/Code/synapse\tzsh\twork\t1",
            ]
        ),
    )
    monkeypatch.setattr(queue_actions, "_speak", lambda text: spoken.append(text) or True)

    assert queue_actions.handle_conductor_text("what tmux panes do I have open") is True

    assert len(spoken) == 1
    assert spoken[0].startswith("I see 2 tmux panes:")
    assert "Hands-free: handsfree running node" in spoken[0]
    assert "Pain: synapse running shell, work" in spoken[0]


def test_tmux_pane_query_accepts_pains_mishearing(monkeypatch):
    monkeypatch.setattr(
        queue_actions,
        "_tmux_panes_snapshot",
        lambda: "0:1.1\t%1\tHands-free\t/Users/me/Code/handsfree\tnode\thandsfree\t1",
    )

    answer = queue_actions._tmux_panes_answer_if_requested("what are my tmux pains")

    assert answer is not None
    assert answer.startswith("I see 1 tmux pane:")
