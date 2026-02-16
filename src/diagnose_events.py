#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-framework-Quartz",
#   "pyobjc-framework-Cocoa",
# ]
# ///
"""Diagnostic utility for AirPods stem-click event detection on macOS.

Starts four independent backends and logs whichever one receives events:
1) CGEventTap at session level
2) CGEventTap at annotated-session level
3) AppKit NSEvent global monitor
4) MPRemoteCommandCenter

If stem clicks show up in one backend but not another, use that backend in the
listener implementation.
"""

from __future__ import annotations

import signal
import sys

import Quartz
from Foundation import NSDate, NSRunLoop

NX_SYSDEFINED = 14
NX_SUBTYPE_AUX_CONTROL_BUTTONS = 8


def _decode_data1(data1: int) -> tuple[int, int]:
    keycode = (data1 >> 16) & 0xFFFF
    state = (data1 >> 8) & 0xFF
    return keycode, state


def _print_permissions():
    preflight = getattr(Quartz, "CGPreflightListenEventAccess", None)
    request = getattr(Quartz, "CGRequestListenEventAccess", None)
    if not callable(preflight):
        print("Listen-event access API unavailable on this macOS version.")
        return

    granted = bool(preflight())
    print(f"CGPreflightListenEventAccess: {granted}")
    if not granted and callable(request):
        print("Requesting listen-event access prompt...")
        print(f"CGRequestListenEventAccess: {bool(request())}")


def _make_cg_callback(name: str, taps: dict[str, object]):
    def callback(proxy, event_type, event, refcon):
        if event_type in (
            Quartz.kCGEventTapDisabledByTimeout,
            Quartz.kCGEventTapDisabledByUserInput,
        ):
            tap = taps.get(name)
            if tap is not None:
                Quartz.CGEventTapEnable(tap, True)
                print(f"[{name}] tap disabled, re-enabled")
            return event

        if event_type != NX_SYSDEFINED:
            return event

        subtype = Quartz.CGEventGetIntegerValueField(
            event, getattr(Quartz, "kCGEventSubtype", 7)
        )
        data1 = Quartz.CGEventGetIntegerValueField(
            event, getattr(Quartz, "kCGEventData1", 87)
        )
        keycode, state = _decode_data1(int(data1))
        print(
            f"[{name}] type={event_type} subtype={subtype} "
            f"data1={int(data1):#x} keycode={keycode} state={state:#x}"
        )
        return event

    return callback


def _start_appkit_monitor():
    import AppKit

    mask = getattr(
        AppKit,
        "NSEventMaskSystemDefined",
        getattr(AppKit, "NSSystemDefinedMask", None),
    )
    if mask is None:
        print("[appkit] NSEventMaskSystemDefined unavailable")
        return None, None

    system_defined_type = getattr(
        AppKit,
        "NSEventTypeSystemDefined",
        getattr(AppKit, "NSSystemDefined", NX_SYSDEFINED),
    )

    AppKit.NSApplication.sharedApplication()

    def handler(ns_event):
        try:
            if int(ns_event.type()) != int(system_defined_type):
                return
            subtype = int(ns_event.subtype())
            data1 = int(ns_event.data1())
            keycode, state = _decode_data1(data1)
            print(
                f"[appkit] type={int(ns_event.type())} subtype={subtype} "
                f"data1={data1:#x} keycode={keycode} state={state:#x}"
            )
            if subtype != NX_SUBTYPE_AUX_CONTROL_BUTTONS:
                print("[appkit] (non-media system-defined event)")
        except Exception as exc:
            print(f"[appkit] error: {exc}")

    monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
        mask, handler
    )
    if monitor is None:
        print("[appkit] failed to start global monitor")
    return monitor, handler


def _start_remote_command_monitor():
    """Monitor AirPods commands through MPRemoteCommandCenter."""
    try:
        import MediaPlayer
    except Exception as exc:
        print(f"[mpremote] MediaPlayer unavailable: {exc}")
        return None, [], []

    try:
        center = MediaPlayer.MPRemoteCommandCenter.sharedCommandCenter()
        now_playing = MediaPlayer.MPNowPlayingInfoCenter.defaultCenter()

        now_info = {}
        title_key = getattr(MediaPlayer, "MPMediaItemPropertyTitle", None)
        rate_key = getattr(MediaPlayer, "MPNowPlayingInfoPropertyPlaybackRate", None)
        if title_key is not None:
            now_info[title_key] = "Handsfree Diagnostic"
        if rate_key is not None:
            now_info[rate_key] = 1.0
        if now_info:
            now_playing.setNowPlayingInfo_(now_info)

        state_playing = getattr(MediaPlayer, "MPNowPlayingPlaybackStatePlaying", None)
        if state_playing is not None and hasattr(now_playing, "setPlaybackState_"):
            now_playing.setPlaybackState_(state_playing)

        status_success = getattr(MediaPlayer, "MPRemoteCommandHandlerStatusSuccess", 0)
        handlers = []
        tokens = []

        def _command(attr_name: str):
            attr = getattr(center, attr_name, None)
            if attr is None:
                return None
            return attr() if callable(attr) else attr

        def _register(attr_name: str, label: str):
            command = _command(attr_name)
            if command is None:
                return
            if hasattr(command, "setEnabled_"):
                command.setEnabled_(True)

            def handler(event):
                print(f"[mpremote] {label}")
                return status_success

            token = command.addTargetWithHandler_(handler)
            handlers.append(handler)
            tokens.append((command, token))

        _register("togglePlayPauseCommand", "togglePlayPauseCommand")
        _register("playCommand", "playCommand")
        _register("pauseCommand", "pauseCommand")
        _register("nextTrackCommand", "nextTrackCommand")
        _register("previousTrackCommand", "previousTrackCommand")

        if not tokens:
            print("[mpremote] no command handlers were registered")
            return None, [], []

        print("[mpremote] started")
        return now_playing, tokens, handlers
    except Exception as exc:
        print(f"[mpremote] init failed: {exc}")
        return None, [], []


def main():
    print("=== AirPods Stem Click Diagnostic ===")
    print("Click AirPods stem while this runs.")
    print("Expected media-key subtype is 8 (NX_SUBTYPE_AUX_CONTROL_BUTTONS).")
    print("State 0x0a = key down, 0x0b = key up.\n")

    _print_permissions()
    print("")

    taps: dict[str, object] = {}
    callbacks: list[object] = []
    run_loop_sources: list[object] = []
    active = []

    event_mask = Quartz.CGEventMaskBit(NX_SYSDEFINED)
    for name, location in (
        ("cgtap-session", Quartz.kCGSessionEventTap),
        ("cgtap-annotated", Quartz.kCGAnnotatedSessionEventTap),
    ):
        cb = _make_cg_callback(name, taps)
        callbacks.append(cb)
        tap = Quartz.CGEventTapCreate(
            location,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            event_mask,
            cb,
            None,
        )
        if tap is None:
            print(f"[{name}] failed to create")
            continue

        taps[name] = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        run_loop_sources.append(source)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(tap, True)
        active.append(name)
        print(f"[{name}] started")

    monitor, monitor_handler = _start_appkit_monitor()
    if monitor is not None:
        active.append("appkit")
        print("[appkit] started")
    remote_center, remote_tokens, remote_handlers = _start_remote_command_monitor()
    if remote_tokens:
        active.append("mpremote")

    if not active:
        print("\nERROR: no backend started.")
        print("Grant terminal access in:")
        print("  1) Privacy & Security > Accessibility")
        print("  2) Privacy & Security > Input Monitoring")
        sys.exit(1)

    print(f"\n[listening on: {', '.join(active)}]")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.5)
            )
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        if monitor is not None:
            import AppKit

            AppKit.NSEvent.removeMonitor_(monitor)
            _ = monitor_handler
        for command, token in remote_tokens:
            try:
                command.removeTarget_(token)
            except Exception:
                pass
        if remote_center is not None:
            try:
                remote_center.setNowPlayingInfo_(None)
            except Exception:
                pass
        _ = remote_handlers


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
