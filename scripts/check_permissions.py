#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-core",
#   "pyobjc-framework-Quartz",
#   "sounddevice",
# ]
# ///
"""Check macOS permissions required for handsfree operation."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass

import Quartz
import sounddevice as sd


@dataclass
class CheckResult:
    name: str
    status: str  # PASS, WARN, FAIL
    details: str
    fix: str | None = None


def check_microphone() -> CheckResult:
    """Check microphone access by opening an input stream briefly."""
    stream = None
    try:
        stream = sd.RawInputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            blocksize=256,
        )
        stream.start()
        time.sleep(0.05)
        stream.stop()
        return CheckResult("Microphone", "PASS", "Input stream opened successfully.")
    except Exception as exc:
        return CheckResult(
            "Microphone",
            "FAIL",
            f"Could not open input stream: {exc}",
            "System Settings > Privacy & Security > Microphone: allow your terminal app.",
        )
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def check_accessibility() -> CheckResult:
    """Check accessibility trust required for some event paths."""
    fn = getattr(Quartz, "AXIsProcessTrusted", None)
    if not callable(fn):
        return CheckResult(
            "Accessibility",
            "WARN",
            "AXIsProcessTrusted API unavailable.",
            "System Settings > Privacy & Security > Accessibility: allow your terminal app.",
        )

    trusted = bool(fn())
    if trusted:
        return CheckResult("Accessibility", "PASS", "Process is trusted for accessibility.")
    return CheckResult(
        "Accessibility",
        "WARN",
        "Process is not trusted for accessibility.",
        "System Settings > Privacy & Security > Accessibility: allow your terminal app.",
    )


def check_input_monitoring() -> CheckResult:
    """Check listen-event permission (Input Monitoring path)."""
    fn = getattr(Quartz, "CGPreflightListenEventAccess", None)
    if not callable(fn):
        return CheckResult(
            "Input Monitoring",
            "WARN",
            "CGPreflightListenEventAccess API unavailable.",
            "System Settings > Privacy & Security > Input Monitoring: allow your terminal app.",
        )

    allowed = bool(fn())
    if allowed:
        return CheckResult("Input Monitoring", "PASS", "Listen-event access is granted.")
    return CheckResult(
        "Input Monitoring",
        "WARN",
        "Listen-event access is not granted.",
        "System Settings > Privacy & Security > Input Monitoring: allow your terminal app.",
    )


def check_automation_system_events() -> CheckResult:
    """Check AppleScript automation permission for System Events."""
    cmd = [
        "osascript",
        "-e",
        'tell application "System Events" to get name of first process',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return CheckResult(
            "Automation (System Events)",
            "PASS",
            "AppleScript access to System Events is available.",
        )

    details = (result.stderr or result.stdout or "").strip()
    return CheckResult(
        "Automation (System Events)",
        "FAIL",
        f"AppleScript call failed (rc={result.returncode}): {details}",
        "System Settings > Privacy & Security > Automation: allow your terminal app to control System Events.",
    )


def main() -> int:
    checks = [
        check_microphone(),
        check_accessibility(),
        check_input_monitoring(),
        check_automation_system_events(),
    ]

    print("=== Handsfree Permission Check ===")
    print("App target: terminal used to launch Claude/handsfree\n")

    has_fail = False
    has_warn = False
    for check in checks:
        print(f"[{check.status}] {check.name}: {check.details}")
        if check.fix:
            print(f"  Fix: {check.fix}")
        if check.status == "FAIL":
            has_fail = True
        elif check.status == "WARN":
            has_warn = True

    print("")
    if has_fail:
        print("Result: FAIL (fix required items above).")
        return 1
    if has_warn:
        print("Result: PASS with WARNINGS (recommended fixes listed above).")
        return 0
    print("Result: PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
