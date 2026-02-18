#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-core",
#   "pyobjc-framework-Cocoa",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""Diagnose MPRemote delivery while an input stream is active.

Runs three phases and logs stem-click command counts in each phase:
1) baseline (no mic stream)
2) mic-open (sd.InputStream active)
3) post-mic (mic stream closed again)

If phase 1/3 receive events but phase 2 drops to zero, MPRemote delivery is
likely being interrupted by opening the input stream.
"""

from __future__ import annotations

import signal
import sys
import time
from collections import Counter

import objc
import sounddevice as sd
from Foundation import NSDate, NSObject, NSRunLoop

import AppKit

objc.loadBundle(
    "MediaPlayer",
    bundle_path="/System/Library/Frameworks/MediaPlayer.framework",
    module_globals=globals(),
)

MPRemoteCommandCenter = objc.lookUpClass("MPRemoteCommandCenter")
MPNowPlayingInfoCenter = objc.lookUpClass("MPNowPlayingInfoCenter")


PHASES = [
    ("baseline-no-mic", 8.0, False),
    ("mic-open", 12.0, True),
    ("post-mic", 8.0, False),
]


class SilentKeepAlive:
    """Continuously outputs silence to keep this process now-playing."""

    def __init__(self, samplerate: int = 44100, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self.stream: sd.OutputStream | None = None

    def start(self):
        if self.stream is not None:
            return

        def callback(outdata, frames, time_info, status):
            outdata[:] = 0.0

        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        self.stream.start()
        print("[audio] silent output keepalive started", flush=True)

    def stop(self):
        if self.stream is None:
            return
        self.stream.stop()
        self.stream.close()
        self.stream = None
        print("[audio] silent output keepalive stopped", flush=True)


class MicProbe:
    """Holds an InputStream open to test whether MPRemote still delivers."""

    def __init__(self, samplerate: int = 16000, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self.stream: sd.InputStream | None = None
        self.rms = 0.0

    def start(self):
        if self.stream is not None:
            return

        def callback(indata, frames, time_info, status):
            # Track a tiny health signal so we know the callback is running.
            self.rms = float((indata**2).mean() ** 0.5)

        self.stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        self.stream.start()
        print("[audio] mic input stream started", flush=True)

    def stop(self):
        if self.stream is None:
            return
        self.stream.stop()
        self.stream.close()
        self.stream = None
        print("[audio] mic input stream stopped", flush=True)


class CommandHandler(NSObject):
    """Receives MPRemote command callbacks and logs by active phase."""

    phase_name = objc.ivar()
    phase_counts = objc.ivar()
    total_count = objc.ivar()

    def _record(self, label: str):
        now = time.monotonic()
        phase = self.phase_name or "unknown"
        self.total_count[label] += 1
        self.phase_counts[phase] += 1
        print(
            f"[event] t={now:.3f} phase={phase} command={label} "
            f"phase_events={self.phase_counts[phase]} total_{label}={self.total_count[label]}",
            flush=True,
        )

    @objc.typedSelector(b"q@:@")
    def handleTogglePlayPause_(self, event):
        self._record("toggle")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePlay_(self, event):
        self._record("play")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePause_(self, event):
        self._record("pause")
        return 0

    @objc.typedSelector(b"q@:@")
    def handleNextTrack_(self, event):
        self._record("next")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePreviousTrack_(self, event):
        self._record("previous")
        return 0


def _run_phase(name: str, seconds: float, mic_open: bool, handler: CommandHandler, mic: MicProbe):
    handler.phase_name = name
    if mic_open:
        mic.start()
    else:
        mic.stop()

    print(
        f"\n[phase] {name} ({seconds:.0f}s) — click AirPods stem repeatedly now.",
        flush=True,
    )

    end_at = time.monotonic() + seconds
    while time.monotonic() < end_at:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.2)
        )

    print(
        f"[phase] {name} complete — events={handler.phase_counts[name]} "
        f"mic_rms={mic.rms:.5f}",
        flush=True,
    )


def main():
    print("=== MPRemote + InputStream Diagnostic ===", flush=True)
    print("Goal: verify whether stem-click events continue while mic stream is open.", flush=True)
    print("Press stem once/double/triple several times in each phase.", flush=True)
    print("Ctrl+C to stop early.\n", flush=True)

    AppKit.NSApplication.sharedApplication()

    center = MPRemoteCommandCenter.sharedCommandCenter()
    now_playing = MPNowPlayingInfoCenter.defaultCenter()
    keepalive = SilentKeepAlive()
    mic = MicProbe()

    keepalive.start()

    now_playing_info = {}
    title_key = globals().get("MPMediaItemPropertyTitle")
    playback_rate_key = globals().get("MPNowPlayingInfoPropertyPlaybackRate")
    now_playing_info[title_key or "title"] = "Handsfree MPRemote Input Diagnostic"
    if playback_rate_key is not None:
        now_playing_info[playback_rate_key] = 1.0
    now_playing.setNowPlayingInfo_(now_playing_info)
    if hasattr(now_playing, "setPlaybackState_"):
        now_playing.setPlaybackState_(1)  # MPNowPlayingPlaybackStatePlaying

    handler = CommandHandler.alloc().init()
    handler.phase_name = "init"
    handler.phase_counts = Counter()
    handler.total_count = Counter()

    commands = [
        ("togglePlayPauseCommand", "handleTogglePlayPause:"),
        ("playCommand", "handlePlay:"),
        ("pauseCommand", "handlePause:"),
        ("nextTrackCommand", "handleNextTrack:"),
        ("previousTrackCommand", "handlePreviousTrack:"),
    ]

    command_refs: list[tuple[object, str]] = []
    for attr_name, selector_name in commands:
        command = getattr(center, attr_name)()
        command.setEnabled_(True)
        command.addTarget_action_(handler, selector_name)
        command_refs.append((command, selector_name))
        print(f"[registered] {attr_name}", flush=True)

    try:
        for name, seconds, mic_open in PHASES:
            _run_phase(name, seconds, mic_open, handler, mic)
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
    finally:
        mic.stop()
        for command, selector_name in command_refs:
            try:
                command.removeTarget_action_(handler, selector_name)
            except Exception:
                pass
        now_playing.setNowPlayingInfo_(None)
        keepalive.stop()

    baseline = handler.phase_counts.get("baseline-no-mic", 0)
    mic_open_count = handler.phase_counts.get("mic-open", 0)
    post = handler.phase_counts.get("post-mic", 0)

    print("\n=== Summary ===", flush=True)
    print(f"baseline-no-mic: {baseline}", flush=True)
    print(f"mic-open:        {mic_open_count}", flush=True)
    print(f"post-mic:        {post}", flush=True)

    if (baseline > 0 or post > 0) and mic_open_count == 0:
        print(
            "Result: MPRemote callbacks likely stop while InputStream is active.",
            flush=True,
        )
    else:
        print(
            "Result: MPRemote callbacks were observed with mic open in this run.",
            flush=True,
        )


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
