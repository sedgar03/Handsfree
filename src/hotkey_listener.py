#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-framework-Quartz",
#   "mlx-whisper",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""Global hotkey listener — press F18 to record, release to transcribe.

Uses PyObjC CGEventTap to detect key events globally. Requires macOS
Accessibility permission (System Settings > Privacy > Accessibility).

On keydown: starts recording from default mic.
On keyup: stops recording, transcribes via mlx-whisper, prints text.
"""

from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import get_config
from stt import SAMPLE_RATE, transcribe

# macOS virtual keycodes
KEYCODE_MAP = {
    "F18": 79,
    "F17": 64,
    "F16": 106,
    "F19": 80,
    "F20": 90,
}


class HotkeyListener:
    """Listens for a global hotkey and records audio while it's held."""

    def __init__(self, hotkey: str = "F18", on_transcription=None):
        self.keycode = KEYCODE_MAP.get(hotkey, 79)
        self.hotkey_name = hotkey
        self.on_transcription = on_transcription or self._default_handler
        self._recording = False
        self._stream = None
        self._chunks: list[np.ndarray] = []

    def _default_handler(self, text: str):
        """Default: print transcription to stdout."""
        print(f"\n[transcription] {text}")

    def _start_recording(self):
        """Begin recording from the default input device."""
        if self._recording:
            return
        self._recording = True
        self._chunks = []

        def callback(indata, frames, time_info, status):
            self._chunks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()
        print("[recording] Started — speak now...", file=sys.stderr)

    def _stop_recording(self):
        """Stop recording, transcribe, and invoke callback."""
        if not self._recording:
            return
        self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            print("[recording] No audio captured.", file=sys.stderr)
            return

        audio = np.concatenate(self._chunks).flatten()
        print(f"[recording] Stopped — {len(audio) / SAMPLE_RATE:.1f}s captured", file=sys.stderr)

        # Transcribe in a thread to not block the event loop
        def do_transcribe():
            print("[transcribing]...", file=sys.stderr)
            text = transcribe(audio)
            if text:
                self.on_transcription(text)
            else:
                print("[transcription] (empty result)", file=sys.stderr)

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _event_callback(self, proxy, event_type, event, refcon):
        """CGEventTap callback — detect keydown/keyup for our hotkey."""
        import Quartz

        keycode = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )

        if keycode != self.keycode:
            return event

        if event_type == Quartz.kCGEventKeyDown:
            # Ignore key repeats
            is_repeat = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventAutorepeat
            )
            if not is_repeat:
                self._start_recording()
        elif event_type == Quartz.kCGEventKeyUp:
            self._stop_recording()

        return event

    def run(self):
        """Start listening for the hotkey. Blocks until interrupted."""
        import Quartz
        from Foundation import NSRunLoop, NSDate

        print(f"Listening for {self.hotkey_name} (keycode {self.keycode})...", file=sys.stderr)
        print("Hold key to record, release to transcribe. Ctrl+C to quit.", file=sys.stderr)

        event_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        )

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            self._event_callback,
            None,
        )

        if tap is None:
            print(
                "ERROR: Could not create event tap. Grant Accessibility permission:\n"
                "  System Settings > Privacy & Security > Accessibility\n"
                "  Add your terminal app (Terminal, iTerm2, etc.)",
                file=sys.stderr,
            )
            sys.exit(1)

        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            run_loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(tap, True)

        # Run the event loop
        try:
            while True:
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.5)
                )
        except KeyboardInterrupt:
            print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    config = get_config()
    hotkey = config.get("hotkey", "F18")

    # Allow override from argv
    if len(sys.argv) > 1:
        hotkey = sys.argv[1]

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    listener = HotkeyListener(hotkey=hotkey)
    listener.run()
