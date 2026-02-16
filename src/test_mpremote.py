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
"""MPRemoteCommandCenter diagnostic with silent-audio keepalive.

This script keeps a zero-valued output stream active so macOS can route
AirPods remote commands to this process.
"""

from __future__ import annotations

import signal
import sys

import objc
import sounddevice as sd
from Foundation import NSDate, NSObject, NSRunLoop

import AppKit

# Load MediaPlayer framework from system location.
objc.loadBundle(
    "MediaPlayer",
    bundle_path="/System/Library/Frameworks/MediaPlayer.framework",
    module_globals=globals(),
)

MPRemoteCommandCenter = objc.lookUpClass("MPRemoteCommandCenter")
MPNowPlayingInfoCenter = objc.lookUpClass("MPNowPlayingInfoCenter")


class SilentKeepAlive:
    """Continuously outputs silence to keep process in now-playing route."""

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
        print("[audio] silent keepalive started", flush=True)

    def stop(self):
        if self.stream is None:
            return
        self.stream.stop()
        self.stream.close()
        self.stream = None
        print("[audio] silent keepalive stopped", flush=True)


class CommandHandler(NSObject):
    """Receives MPRemoteCommand events."""

    @objc.typedSelector(b"q@:@")
    def handleTogglePlayPause_(self, event):
        print(">>> SINGLE CLICK (togglePlayPause)", flush=True)
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePlay_(self, event):
        print(">>> PLAY", flush=True)
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePause_(self, event):
        print(">>> PAUSE", flush=True)
        return 0

    @objc.typedSelector(b"q@:@")
    def handleNextTrack_(self, event):
        print(">>> DOUBLE CLICK (nextTrack)", flush=True)
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePreviousTrack_(self, event):
        print(">>> TRIPLE CLICK (previousTrack)", flush=True)
        return 0


def main():
    print("=== MPRemoteCommandCenter Test ===", flush=True)
    print("Click AirPod stem to test while this process is running.", flush=True)
    print("  Single → togglePlayPause | Double → nextTrack | Triple → previousTrack", flush=True)
    print("Ctrl+C to stop.\n", flush=True)

    center = MPRemoteCommandCenter.sharedCommandCenter()
    now_playing = MPNowPlayingInfoCenter.defaultCenter()
    keepalive = SilentKeepAlive()
    AppKit.NSApplication.sharedApplication()

    keepalive.start()

    # Register as now-playing app
    now_playing_info = {}
    title_key = globals().get("MPMediaItemPropertyTitle")
    playback_rate_key = globals().get("MPNowPlayingInfoPropertyPlaybackRate")
    now_playing_info[title_key or "title"] = "Handsfree Listener"
    if playback_rate_key is not None:
        now_playing_info[playback_rate_key] = 1.0
    now_playing.setNowPlayingInfo_(now_playing_info)
    try:
        now_playing.setPlaybackState_(1)  # MPNowPlayingPlaybackStatePlaying
        print("[setup] Playback state = playing", flush=True)
    except Exception as e:
        print(f"[setup] playback state: {e}", flush=True)

    handler = CommandHandler.alloc().init()

    commands = [
        ("togglePlayPauseCommand", "handleTogglePlayPause:"),
        ("playCommand", "handlePlay:"),
        ("pauseCommand", "handlePause:"),
        ("nextTrackCommand", "handleNextTrack:"),
        ("previousTrackCommand", "handlePreviousTrack:"),
    ]

    command_refs = []
    for attr_name, sel_name in commands:
        cmd = getattr(center, attr_name)()
        cmd.setEnabled_(True)
        cmd.addTarget_action_(handler, sel_name)
        command_refs.append((cmd, sel_name))
        print(f"[registered] {attr_name}", flush=True)

    print("\n[listening...]\n", flush=True)

    try:
        while True:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.5)
            )
    except KeyboardInterrupt:
        print("\nDone.", flush=True)
    finally:
        for cmd, sel_name in command_refs:
            try:
                cmd.removeTarget_action_(handler, sel_name)
            except Exception:
                pass
        now_playing.setNowPlayingInfo_(None)
        keepalive.stop()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
