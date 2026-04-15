#!/usr/bin/env python3
"""Handsfree queue broker CLI.

Hooks call this to enqueue events and optionally ding/speak. The listener
calls the imported queue action functions directly for low-latency clicks.
"""

from __future__ import annotations

import argparse
import json
import sys

from audio_output import play_notification
from config import is_handsfree_enabled, mark_consume_after, queue_consume_after_timestamp
from event_queue import enqueue_event, list_events, update_event_status
from queue_actions import read_next_event, speak_event
from service_control import (
    disable_speech,
    disable_wake,
    enable_speech,
    enable_wake,
    service_status,
    start_conductor_daemon,
    start_summary_daemon,
    start_tts_daemon,
    stop_conductor_daemon,
    warm_conductor,
    warm_speech,
    warm_wake,
)


def _parse_payload(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _cmd_enqueue(args: argparse.Namespace) -> int:
    event = enqueue_event(
        source=args.source,
        kind=args.kind,
        summary=args.summary,
        detail=args.detail or "",
        priority=args.priority,
        workflow=args.workflow,
        target_pane=args.target_pane,
        target_cwd=args.target_cwd,
        transcript_path=args.transcript_path or "",
        session_id=args.session_id or "",
        payload=_parse_payload(args.payload_json),
    )

    if args.notify:
        play_notification(args.source)

    if args.speak and is_handsfree_enabled():
        speak_event(event)
        if args.complete_after_speak:
            update_event_status(event.id, "done")

    print(json.dumps({"id": event.id, "status": event.status}))
    return 0


def _cmd_read_next(args: argparse.Namespace) -> int:
    event = read_next_event(speak_empty=args.speak_empty)
    if event is None:
        print(json.dumps({"event": None}))
    else:
        print(json.dumps({"event": event.id, "workflow": event.workflow}))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    cutoff = queue_consume_after_timestamp() if args.current else None
    events = list_events(limit=args.limit, created_after=cutoff)
    payload = [
        {
            "id": event.id,
            "status": event.status,
            "source": event.source,
            "kind": event.kind,
            "workflow": event.workflow,
            "summary": event.summary,
            "target_pane": event.target_pane,
        }
        for event in events
    ]
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_mark_unmuted(args: argparse.Namespace) -> int:
    timestamp = mark_consume_after(args.timestamp)
    print(json.dumps({"consume_after": timestamp}))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(service_status(), indent=2))
    return 0


def _cmd_warm(args: argparse.Namespace) -> int:
    timeout = float(args.timeout)
    if args.service == "speech":
        payload = warm_speech(timeout=timeout)
    elif args.service == "wake":
        payload = warm_wake(timeout=timeout)
    elif args.service == "summary":
        payload = start_summary_daemon(wait=True, timeout=timeout)
    elif args.service == "tts":
        payload = start_tts_daemon(wait=True, timeout=timeout)
    elif args.service == "conductor":
        payload = warm_conductor(timeout=timeout)
    else:
        raise ValueError(f"Unknown service: {args.service}")
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    timeout = float(args.timeout)
    if args.service == "speech":
        payload = enable_speech(timeout=timeout)
    elif args.service == "wake":
        payload = enable_wake(timeout=timeout)
    else:
        raise ValueError(f"Unknown service: {args.service}")
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    if args.service == "speech":
        payload = disable_speech()
    elif args.service == "wake":
        payload = disable_wake()
    elif args.service == "conductor":
        payload = stop_conductor_daemon()
    else:
        raise ValueError(f"Unknown service: {args.service}")
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_conductor_chat(args: argparse.Namespace) -> int:
    from conductor_client import request_conductor

    start_conductor_daemon(wait=True, timeout=float(args.start_timeout))
    text = " ".join(args.text).strip()
    payload = request_conductor(
        text,
        conversation_id=args.conversation_id,
        reset=args.reset,
        connect_timeout=5.0,
        response_timeout=float(args.timeout),
    )
    if payload is None:
        print(json.dumps({"ok": False, "error": "conductor unavailable"}))
        return 1
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(str(payload.get("response") or ""))
    return 0 if payload.get("ok") else 1


def _cmd_conductor_reset(args: argparse.Namespace) -> int:
    from conductor_client import reset_conductor

    start_conductor_daemon(wait=True, timeout=float(args.start_timeout))
    payload = reset_conductor(
        conversation_id=args.conversation_id,
        connect_timeout=5.0,
        response_timeout=float(args.timeout),
    )
    if payload is None:
        print(json.dumps({"ok": False, "error": "conductor unavailable"}))
        return 1
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Handsfree queue broker")
    sub = parser.add_subparsers(dest="command", required=True)

    enqueue = sub.add_parser("enqueue", help="enqueue a hook event")
    enqueue.add_argument("--source", required=True)
    enqueue.add_argument("--kind", required=True)
    enqueue.add_argument("--summary", required=True)
    enqueue.add_argument("--detail", default="")
    enqueue.add_argument("--priority", type=int, default=0)
    enqueue.add_argument("--workflow")
    enqueue.add_argument("--target-pane")
    enqueue.add_argument("--target-cwd")
    enqueue.add_argument("--transcript-path")
    enqueue.add_argument("--session-id")
    enqueue.add_argument("--payload-json")
    enqueue.add_argument("--notify", action="store_true")
    enqueue.add_argument("--speak", action="store_true")
    enqueue.add_argument("--complete-after-speak", action="store_true")
    enqueue.set_defaults(func=_cmd_enqueue)

    read_next = sub.add_parser("read-next", help="speak the next queued event")
    read_next.add_argument("--speak-empty", action="store_true")
    read_next.set_defaults(func=_cmd_read_next)

    list_cmd = sub.add_parser("list", help="list pending/active events")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.add_argument(
        "--current",
        action="store_true",
        help="only show events after the current consumption watermark",
    )
    list_cmd.set_defaults(func=_cmd_list)

    mark_unmuted = sub.add_parser(
        "mark-unmuted",
        aliases=["mark-consume-after"],
        help="mark the current queue-consumption start time",
    )
    mark_unmuted.add_argument("--timestamp", type=float)
    mark_unmuted.set_defaults(func=_cmd_mark_unmuted)

    status = sub.add_parser("status", help="show Handsfree service readiness")
    status.set_defaults(func=_cmd_status)

    warm = sub.add_parser("warm", help="start/warm a Handsfree service")
    warm.add_argument("service", choices=["speech", "wake", "summary", "tts", "conductor"])
    warm.add_argument("--timeout", type=float, default=120.0)
    warm.set_defaults(func=_cmd_warm)

    enable = sub.add_parser("enable", help="warm and enable a Handsfree mode")
    enable.add_argument("service", choices=["speech", "wake"])
    enable.add_argument("--timeout", type=float, default=120.0)
    enable.set_defaults(func=_cmd_enable)

    disable = sub.add_parser("disable", help="disable a Handsfree mode")
    disable.add_argument("service", choices=["speech", "wake", "conductor"])
    disable.set_defaults(func=_cmd_disable)

    conductor = sub.add_parser("conductor", help="talk to the local conductor")
    conductor_sub = conductor.add_subparsers(dest="conductor_command", required=True)

    conductor_chat = conductor_sub.add_parser("chat", help="send a text turn")
    conductor_chat.add_argument("text", nargs="+")
    conductor_chat.add_argument("--conversation-id", default="default")
    conductor_chat.add_argument("--reset", action="store_true")
    conductor_chat.add_argument("--start-timeout", type=float, default=120.0)
    conductor_chat.add_argument("--timeout", type=float, default=120.0)
    conductor_chat.add_argument("--json", action="store_true")
    conductor_chat.set_defaults(func=_cmd_conductor_chat)

    conductor_reset = conductor_sub.add_parser("reset", help="clear a conversation")
    conductor_reset.add_argument("--conversation-id", default="default")
    conductor_reset.add_argument("--start-timeout", type=float, default=120.0)
    conductor_reset.add_argument("--timeout", type=float, default=30.0)
    conductor_reset.set_defaults(func=_cmd_conductor_reset)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
