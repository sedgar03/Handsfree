#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-framework-Quartz",
#   "pyobjc-framework-Cocoa",
# ]
# ///
"""Raw event diagnostic — dumps ALL fields of NSSystemDefined events.

Run this, click AirPod stem (single, double, triple), and see the raw data.
"""

from __future__ import annotations

import signal
import sys

import Quartz
from Foundation import NSDate, NSRunLoop


def callback(proxy, event_type, event, refcon):
    if event_type in (
        Quartz.kCGEventTapDisabledByTimeout,
        Quartz.kCGEventTapDisabledByUserInput,
    ):
        return event

    if event_type != 14:  # NSSystemDefined
        return event

    # Dump multiple field indices to find the right ones
    fields = {}
    for field_idx in range(90, 100):
        try:
            val = Quartz.CGEventGetIntegerValueField(event, field_idx)
            if val != 0:
                fields[field_idx] = val
        except Exception:
            pass

    # Also check the traditional ones
    for field_idx in [7, 8, 85, 86, 87, 88, 89]:
        try:
            val = Quartz.CGEventGetIntegerValueField(event, field_idx)
            fields[field_idx] = val
        except Exception:
            pass

    # Traditional decode of field 87
    data1_87 = fields.get(87, 0)
    kc_87 = (data1_87 >> 16) & 0xFFFF
    st_87 = (data1_87 >> 8) & 0xFF

    # Try field 86 too
    data1_86 = fields.get(86, 0)
    kc_86 = (data1_86 >> 16) & 0xFFFF
    st_86 = (data1_86 >> 8) & 0xFF

    print(f"--- NSSystemDefined event ---")
    print(f"  field[87] = {data1_87:#018x}  keycode(>>16)={kc_87}  state(>>8)={st_87:#x}")
    print(f"  field[86] = {data1_86:#018x}  keycode(>>16)={kc_86}  state(>>8)={st_86:#x}")

    # Print all non-zero fields
    for idx in sorted(fields):
        if idx not in (86, 87):
            print(f"  field[{idx}] = {fields[idx]:#018x} ({fields[idx]})")
    print(flush=True)

    return event


def main():
    print("=== Raw Event Dump ===", flush=True)
    print("Click AirPod stem: single, double, triple.", flush=True)
    print("Also try pressing play/pause on keyboard if you have one.", flush=True)
    print("Ctrl+C to stop.\n", flush=True)

    event_mask = Quartz.CGEventMaskBit(14)

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGAnnotatedSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        event_mask,
        callback,
        None,
    )

    if tap is None:
        print("ERROR: Could not create event tap.", flush=True)
        sys.exit(1)

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes
    )
    Quartz.CGEventTapEnable(tap, True)

    print("[listening...]\n", flush=True)

    try:
        while True:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.5)
            )
    except KeyboardInterrupt:
        print("\nDone.", flush=True)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
