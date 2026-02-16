#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyobjc-core",
#   "pyobjc-framework-Quartz",
#   "pyobjc-framework-Cocoa",
#   "mlx-whisper",
#   "sounddevice",
#   "numpy",
# ]
# ///
"""Media key listener — AirPods stem click to record, VAD auto-stop, transcribe.

Intercepts macOS media key events (play/pause, next, previous) from multiple
global event backends. AirPods stem clicks map to these media keys:
  - Single click → play/pause (NX_KEYTYPE_PLAY, keycode 16)
  - Double click → next track (NX_KEYTYPE_NEXT, keycode 17)
  - Triple click → previous track (NX_KEYTYPE_PREVIOUS, keycode 18)

State machine:
  idle → (single click) → recording → (VAD silence / double click) → transcribing → idle
  idle → (double click) → submit (press Enter)

Uses MPRemoteCommandCenter as the primary stem-click source. To receive events
from AirPods in a CLI process, the listener keeps a silent output stream alive
so macOS can route remote commands to this process as now-playing.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import objc
import sounddevice as sd
from Foundation import NSObject

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stt import SAMPLE_RATE, transcribe

# --- Media key constants (from IOKit/hidsystem/ev_keymap.h) ---
NX_KEYTYPE_PLAY = 16
NX_KEYTYPE_NEXT = 17
NX_KEYTYPE_PREVIOUS = 18
NX_SYSDEFINED = 14
NX_SUBTYPE_AUX_CONTROL_BUTTONS = 8
MEDIA_KEY_DOWN = 0x0A

# MPNowPlayingPlaybackStatePlaying (constant value from MediaPlayer headers)
_MP_PLAYBACK_STATE_PLAYING = 1

_MEDIA_PLAYER_LOADED = False
MPRemoteCommandCenter = None
MPNowPlayingInfoCenter = None

# --- Sounds ---
_SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"
SOUND_RECORDING_START = _SOUNDS_DIR / "snapchat-notification.mp3"
# Played when recording stops and listener is no longer listening.
SOUND_LISTENING_STOP = _SOUNDS_DIR / "bereal.mp3"
SOUND_SUBMIT = _SOUNDS_DIR / "mail-sent.mp3"

# --- VAD defaults (can be overridden via config) ---
CHUNK_DURATION = 0.1  # seconds per chunk for energy calculation
SPEECH_THRESHOLD = 0.015  # RMS energy above this = speech
SILENCE_THRESHOLD = 0.008  # RMS below this = silence
MAX_WAIT_FOR_SPEECH = 10.0  # max seconds before giving up
MIN_SPEECH_DURATION = 0.3  # ignore very short bursts
POST_TRANSCRIPTION_SUBMIT_WINDOW = 5.0  # seconds


def _play_sound(path: Path, duration: float | None = None):
    """Play a sound file via afplay (non-blocking in a thread)."""
    def _play():
        cmd = ["afplay", str(path)]
        if duration:
            cmd += ["-t", str(duration)]
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=duration + 1 if duration else 10,
            )
        except subprocess.TimeoutExpired:
            pass
    threading.Thread(target=_play, daemon=True).start()


def _load_media_player_symbols() -> bool:
    """Load MediaPlayer classes from system framework via PyObjC bundle API."""
    global _MEDIA_PLAYER_LOADED, MPRemoteCommandCenter, MPNowPlayingInfoCenter
    if _MEDIA_PLAYER_LOADED:
        return True

    try:
        objc.loadBundle(
            "MediaPlayer",
            bundle_path="/System/Library/Frameworks/MediaPlayer.framework",
            module_globals=globals(),
        )
        MPRemoteCommandCenter = objc.lookUpClass("MPRemoteCommandCenter")
        MPNowPlayingInfoCenter = objc.lookUpClass("MPNowPlayingInfoCenter")
    except Exception as exc:
        print(f"[media-key] Failed to load MediaPlayer framework: {exc}", file=sys.stderr)
        return False

    _MEDIA_PLAYER_LOADED = True
    return True


class _SilentOutputKeepAlive:
    """Continuous zero-valued output stream to keep process in now-playing path."""

    def __init__(self, samplerate: int = 44100, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._stream: sd.OutputStream | None = None

    def start(self):
        if self._stream is not None:
            return

        def callback(outdata, frames, time_info, status):
            outdata.fill(0.0)

        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None


class _RemoteCommandTarget(NSObject):
    """Objective-C target object for MPRemoteCommandCenter callbacks."""

    listener = objc.ivar()

    @objc.typedSelector(b"q@:@")
    def handleTogglePlayPause_(self, event):
        self.listener._on_remote_command("toggle")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePlay_(self, event):
        self.listener._on_remote_command("play")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePause_(self, event):
        self.listener._on_remote_command("pause")
        return 0

    @objc.typedSelector(b"q@:@")
    def handleNextTrack_(self, event):
        self.listener._on_remote_command("next")
        return 0

    @objc.typedSelector(b"q@:@")
    def handlePreviousTrack_(self, event):
        self.listener._on_remote_command("previous")
        return 0


class MediaKeyListener:
    """Listens for media key events and manages recording state machine."""

    def __init__(
        self,
        on_transcription=None,
        on_submit=None,
        silence_timeout: float = 2.5,
        max_recording: float = 60.0,
        auto_submit: bool = True,
        auto_submit_after_transcription: bool = True,
    ):
        self.on_transcription = on_transcription or self._default_transcription_handler
        self.on_submit = on_submit
        self.silence_timeout = silence_timeout
        self.max_recording = max_recording
        self.auto_submit = auto_submit
        self.auto_submit_after_transcription = auto_submit_after_transcription

        # State: idle, recording, transcribing
        self._state = "idle"
        self._state_lock = threading.Lock()

        # Recording state
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._vad_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Legacy event backends (disabled by default; retained for debugging)
        self._tap_ports: dict[str, object] = {}
        self._tap_callbacks: list[object] = []
        self._run_loop_sources: list[object] = []
        self._global_monitor = None
        self._global_monitor_handler = None

        # MPRemoteCommandCenter backend
        self._silent_output = _SilentOutputKeepAlive()
        self._remote_command_bindings: list[tuple[object, str]] = []
        self._remote_target = None
        self._now_playing_center = None

        # Event dedupe across multiple backends (same click can be mirrored)
        self._last_event_key: tuple[int, int] | None = None
        self._last_event_at = 0.0
        self._pending_submit_after_transcription = False
        self._last_remote_pause_at = 0.0
        self._last_transcription_at = 0.0

    @staticmethod
    def _default_transcription_handler(text: str):
        print(f"\n[transcription] {text}")

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new_state: str):
        self._state = new_state
        print(f"[media-key] State → {new_state}", file=sys.stderr)

    def _start_recording(self):
        """Begin recording with VAD monitoring in a background thread."""
        with self._state_lock:
            if self._state != "idle":
                return
            self._set_state("recording")
            self._pending_submit_after_transcription = False

        self._chunks = []
        self._stop_event.clear()

        chunk_samples = int(CHUNK_DURATION * SAMPLE_RATE)

        def audio_callback(indata, frames, time_info, status):
            self._chunks.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=chunk_samples,
            callback=audio_callback,
        )
        self._stream.start()

        _play_sound(SOUND_RECORDING_START, duration=1.0)
        print("[media-key] Recording — speak now...", file=sys.stderr)

        # Start VAD monitor thread
        self._vad_thread = threading.Thread(target=self._vad_monitor, daemon=True)
        self._vad_thread.start()

    def _vad_monitor(self):
        """Monitor audio energy and auto-stop on silence."""
        speech_started = False
        silence_start: float | None = None
        wait_start = time.monotonic()
        recording_start = time.monotonic()

        while not self._stop_event.is_set():
            time.sleep(CHUNK_DURATION)

            # Check state — might have been stopped by double-click
            if self._state != "recording":
                return

            elapsed = time.monotonic() - recording_start
            if elapsed > self.max_recording:
                print("[media-key] Max recording time reached.", file=sys.stderr)
                break

            if not self._chunks:
                continue

            recent = self._chunks[-1].flatten()
            rms = float(np.sqrt(np.mean(recent**2)))

            if not speech_started:
                if rms > SPEECH_THRESHOLD:
                    speech_started = True
                    silence_start = None
                    print("[media-key] Speech detected.", file=sys.stderr)
                elif time.monotonic() - wait_start > MAX_WAIT_FOR_SPEECH:
                    print("[media-key] No speech detected, cancelling.", file=sys.stderr)
                    self._cancel_recording()
                    return
            else:
                if rms < SILENCE_THRESHOLD:
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start > self.silence_timeout:
                        print("[media-key] Silence detected, auto-stopping.", file=sys.stderr)
                        break
                else:
                    silence_start = None

        # Auto-stop triggered — finalize recording
        if self._state == "recording":
            self._finalize_recording()

    def _stop_recording_manual(self):
        """Manual stop via double-click during recording."""
        with self._state_lock:
            if self._state != "recording":
                return
        print("[media-key] Manual stop (double-click).", file=sys.stderr)
        self._stop_event.set()
        self._finalize_recording()

    def _cancel_recording(self):
        """Cancel recording without transcribing (e.g. no speech detected)."""
        with self._state_lock:
            if self._state != "recording":
                return
            self._set_state("idle")
            self._pending_submit_after_transcription = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._chunks = []

    def _finalize_recording(self):
        """Stop stream, transcribe audio, invoke callback."""
        with self._state_lock:
            if self._state != "recording":
                return
            self._set_state("transcribing")

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            print("[media-key] No audio captured.", file=sys.stderr)
            self._set_state("idle")
            return

        audio = np.concatenate(self._chunks).flatten()
        duration = len(audio) / SAMPLE_RATE

        if duration < MIN_SPEECH_DURATION:
            print("[media-key] Audio too short, discarding.", file=sys.stderr)
            self._set_state("idle")
            return

        print(f"[media-key] Captured {duration:.1f}s, transcribing...", file=sys.stderr)
        _play_sound(SOUND_LISTENING_STOP, duration=1.0)

        def do_transcribe():
            try:
                text = transcribe(audio)
                if text and text.strip():
                    self.on_transcription(text.strip())
                    self._last_transcription_at = time.monotonic()
                    if self.auto_submit_after_transcription and self.auto_submit:
                        print("[media-key] Auto-submit after transcription.", file=sys.stderr)
                        self._pending_submit_after_transcription = True
                        self._last_transcription_at = 0.0
                    else:
                        print("[media-key] Transcription ready for submit.", file=sys.stderr)
                else:
                    print("[media-key] Empty transcription.", file=sys.stderr)
            except Exception as e:
                print(f"[media-key] Transcription error: {e}", file=sys.stderr)
            finally:
                self._set_state("idle")
                if self._pending_submit_after_transcription and self.auto_submit:
                    self._pending_submit_after_transcription = False
                    threading.Thread(target=self._handle_submit, daemon=True).start()

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _handle_submit(self):
        """Handle double-click in idle state — submit (press Enter)."""
        if self._state != "idle":
            return
        if self.on_submit:
            _play_sound(SOUND_SUBMIT, duration=1.0)
            print("[media-key] Submitting (Enter).", file=sys.stderr)
            self.on_submit()

    def _should_drop_duplicate(self, keycode: int, state: int) -> bool:
        """Drop duplicate mirrored events from multiple backends."""
        now = time.monotonic()
        key = (keycode, state)
        if self._last_event_key == key and now - self._last_event_at < 0.08:
            return True
        self._last_event_key = key
        self._last_event_at = now
        return False

    @staticmethod
    def _decode_data1(data1: int) -> tuple[int, int]:
        """Decode media key keycode + state from NSEvent data1."""
        keycode = (data1 >> 16) & 0xFFFF
        state = (data1 >> 8) & 0xFF
        return keycode, state

    def _handle_media_key(self, keycode: int, state: int, source: str) -> bool:
        """Dispatch media key to state machine. Returns True when consumed."""
        if state != MEDIA_KEY_DOWN:
            return False
        if self._should_drop_duplicate(keycode, state):
            return False

        if keycode == NX_KEYTYPE_PLAY:
            if self._state == "recording":
                print(
                    f"[media-key] PLAY during recording ({source}) -> manual stop fallback",
                    file=sys.stderr,
                )
                threading.Thread(target=self._stop_recording_manual, daemon=True).start()
                return True
            if self._state == "transcribing" and self.auto_submit:
                print(
                    f"[media-key] PLAY during transcribing ({source}) -> queue submit",
                    file=sys.stderr,
                )
                self._pending_submit_after_transcription = True
                return True
            if self._state == "idle":
                now = time.monotonic()
                if (
                    self.auto_submit
                    and self._last_transcription_at > 0
                    and now - self._last_transcription_at <= POST_TRANSCRIPTION_SUBMIT_WINDOW
                ):
                    print(
                        f"[media-key] PLAY within submit window ({source}) -> submit",
                        file=sys.stderr,
                    )
                    self._last_transcription_at = 0.0
                    threading.Thread(target=self._handle_submit, daemon=True).start()
                    return True
                print(f"[media-key] PLAY from {source}", file=sys.stderr)
                threading.Thread(target=self._start_recording, daemon=True).start()
                return True
            return False

        if keycode == NX_KEYTYPE_NEXT:
            print(f"[media-key] NEXT from {source}", file=sys.stderr)
            if self._state == "recording":
                threading.Thread(target=self._stop_recording_manual, daemon=True).start()
                return True
            if self._state == "transcribing" and self.auto_submit:
                print("[media-key] NEXT during transcribing -> queue submit", file=sys.stderr)
                self._pending_submit_after_transcription = True
                return True
            if self._state == "idle" and self.auto_submit:
                self._last_transcription_at = 0.0
                threading.Thread(target=self._handle_submit, daemon=True).start()
                return True
            return False

        if keycode == NX_KEYTYPE_PREVIOUS:
            if self._state == "recording":
                print(f"[media-key] PREVIOUS from {source} -> cancel recording", file=sys.stderr)
                threading.Thread(target=self._cancel_recording, daemon=True).start()
                return True
            print(f"[media-key] PREVIOUS from {source} (ignored)", file=sys.stderr)
            return False

        return False

    def _on_remote_command(self, command: str):
        """Map MPRemoteCommandCenter events to listener semantics."""
        if command in ("toggle", "play", "pause"):
            now = time.monotonic()
            # Some AirPods/macOS combinations never emit nextTrack for double-click.
            # Treat two pause/toggle/play commands in quick succession as a double-click.
            if now - self._last_remote_pause_at <= 0.6:
                self._last_remote_pause_at = 0.0
                print(
                    f"[media-key] {command} within double-click window -> treating as NEXT",
                    file=sys.stderr,
                )
                self._handle_media_key(NX_KEYTYPE_NEXT, MEDIA_KEY_DOWN, f"mpremote:{command}-dbl")
                return
            self._last_remote_pause_at = now
            self._handle_media_key(NX_KEYTYPE_PLAY, MEDIA_KEY_DOWN, f"mpremote:{command}")
            return
        if command == "next":
            self._last_remote_pause_at = 0.0
            self._handle_media_key(NX_KEYTYPE_NEXT, MEDIA_KEY_DOWN, "mpremote:next")
            return
        if command == "previous":
            self._last_remote_pause_at = 0.0
            self._handle_media_key(NX_KEYTYPE_PREVIOUS, MEDIA_KEY_DOWN, "mpremote:previous")

    def _event_callback(self, tap_name: str, proxy, event_type, event, refcon):
        """CGEventTap callback for NSSystemDefined media key events."""
        import Quartz

        # Re-enable tap if it gets disabled by timeout
        if event_type in (
            Quartz.kCGEventTapDisabledByTimeout,
            Quartz.kCGEventTapDisabledByUserInput,
        ):
            tap = self._tap_ports.get(tap_name)
            if tap is not None:
                print(f"[media-key] Re-enabling {tap_name} tap.", file=sys.stderr)
                Quartz.CGEventTapEnable(tap, True)
            return event

        if event_type != NX_SYSDEFINED:
            return event

        subtype_field = getattr(Quartz, "kCGEventSubtype", 7)
        subtype = Quartz.CGEventGetIntegerValueField(event, subtype_field)
        if subtype != NX_SUBTYPE_AUX_CONTROL_BUTTONS:
            return event

        data1_field = getattr(Quartz, "kCGEventData1", 87)
        data1 = Quartz.CGEventGetIntegerValueField(event, data1_field)
        keycode, state = self._decode_data1(int(data1))
        handled = self._handle_media_key(keycode, state, f"cgtap:{tap_name}")

        return None if handled else event

    def _make_tap_callback(self, tap_name: str):
        """Build a CGEventTap callback bound to a named tap."""
        return lambda proxy, event_type, event, refcon: self._event_callback(
            tap_name, proxy, event_type, event, refcon
        )

    def _start_cg_tap(self, tap_name: str, location: int, event_mask: int) -> bool:
        import Quartz

        callback = self._make_tap_callback(tap_name)
        self._tap_callbacks.append(callback)

        tap = Quartz.CGEventTapCreate(
            location,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            callback,
            None,
        )
        if tap is None:
            print(f"[media-key] Could not create {tap_name} tap.", file=sys.stderr)
            return False

        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(tap, True)

        self._tap_ports[tap_name] = tap
        self._run_loop_sources.append(source)
        return True

    def _start_appkit_monitor(self) -> bool:
        import AppKit

        mask = getattr(
            AppKit,
            "NSEventMaskSystemDefined",
            getattr(AppKit, "NSSystemDefinedMask", None),
        )
        if mask is None:
            print("[media-key] AppKit system-defined mask unavailable.", file=sys.stderr)
            return False

        system_type = getattr(
            AppKit,
            "NSEventTypeSystemDefined",
            getattr(AppKit, "NSSystemDefined", NX_SYSDEFINED),
        )

        # Required for global monitors in command-line tools.
        AppKit.NSApplication.sharedApplication()

        def handler(ns_event):
            try:
                if int(ns_event.type()) != int(system_type):
                    return
                if int(ns_event.subtype()) != NX_SUBTYPE_AUX_CONTROL_BUTTONS:
                    return
                data1 = int(ns_event.data1())
                keycode, state = self._decode_data1(data1)
                self._handle_media_key(keycode, state, "appkit-monitor")
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[media-key] AppKit monitor error: {exc}", file=sys.stderr)

        monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, handler
        )
        if monitor is None:
            print("[media-key] Could not start AppKit global monitor.", file=sys.stderr)
            return False

        self._global_monitor_handler = handler
        self._global_monitor = monitor
        return True

    def _start_remote_command_backend(self) -> bool:
        """Start MPRemoteCommandCenter with silent output keepalive."""
        if not _load_media_player_symbols():
            return False

        try:
            import AppKit

            AppKit.NSApplication.sharedApplication()
        except Exception as exc:
            print(f"[media-key] NSApplication init failed: {exc}", file=sys.stderr)
            return False

        try:
            self._silent_output.start()
        except Exception as exc:
            print(f"[media-key] Silent output keepalive failed: {exc}", file=sys.stderr)
            return False

        try:
            center = MPRemoteCommandCenter.sharedCommandCenter()
            now_playing = MPNowPlayingInfoCenter.defaultCenter()
            self._now_playing_center = now_playing

            # A non-empty now-playing payload + playback state helps routing.
            now_playing_info = {}
            title_key = globals().get("MPMediaItemPropertyTitle")
            playback_rate_key = globals().get("MPNowPlayingInfoPropertyPlaybackRate")
            now_playing_info[title_key or "title"] = "Handsfree Listener"
            if playback_rate_key is not None:
                now_playing_info[playback_rate_key] = 1.0
            now_playing.setNowPlayingInfo_(now_playing_info)
            if hasattr(now_playing, "setPlaybackState_"):
                now_playing.setPlaybackState_(_MP_PLAYBACK_STATE_PLAYING)

            target = _RemoteCommandTarget.alloc().init()
            target.listener = self
            self._remote_target = target

            commands = (
                ("togglePlayPauseCommand", "handleTogglePlayPause:"),
                ("playCommand", "handlePlay:"),
                ("pauseCommand", "handlePause:"),
                ("nextTrackCommand", "handleNextTrack:"),
                ("previousTrackCommand", "handlePreviousTrack:"),
            )

            for attr_name, selector_name in commands:
                command = getattr(center, attr_name)()
                command.setEnabled_(True)
                command.addTarget_action_(target, selector_name)
                self._remote_command_bindings.append((command, selector_name))

            return bool(self._remote_command_bindings)
        except Exception as exc:
            print(f"[media-key] MPRemoteCommandCenter init failed: {exc}", file=sys.stderr)
            self._silent_output.stop()
            return False

    @staticmethod
    def _preflight_event_access() -> bool:
        """Check/request listen-event permission where supported."""
        import Quartz

        preflight = getattr(Quartz, "CGPreflightListenEventAccess", None)
        request = getattr(Quartz, "CGRequestListenEventAccess", None)

        if not callable(preflight):
            return True
        if preflight():
            return True

        print(
            "[media-key] Listen-event access not granted. Requesting permission...",
            file=sys.stderr,
        )
        if callable(request):
            return bool(request())
        return False

    def run(self):
        """Start listening for media key events. Blocks until interrupted."""
        import os
        import AppKit
        import Quartz
        from Foundation import NSRunLoop, NSDate

        print("[media-key] Listening for AirPods stem clicks...", file=sys.stderr)
        print("  Single click → record (VAD auto-stop)", file=sys.stderr)
        if self.auto_submit_after_transcription and self.auto_submit:
            print("  Double click → stop recording (submit is automatic after transcription)", file=sys.stderr)
        else:
            print("  Double click → stop recording / submit", file=sys.stderr)
        print("  Ctrl+C to quit.", file=sys.stderr)
        started_sources: list[str] = []

        if self._start_remote_command_backend():
            started_sources.append("MPRemoteCommandCenter + silent audio")

        legacy_fallback = os.environ.get("HANDSFREE_ENABLE_LEGACY_TAPS") == "1"
        if not started_sources and legacy_fallback:
            has_access = self._preflight_event_access()
            if not has_access:
                print(
                    "[media-key] Access denied. Enable both Accessibility and Input Monitoring for your terminal.",
                    file=sys.stderr,
                )
            event_mask = Quartz.CGEventMaskBit(NX_SYSDEFINED)
            if self._start_cg_tap("session", Quartz.kCGSessionEventTap, event_mask):
                started_sources.append("CGEventTap(session)")
            if self._start_cg_tap("annotated", Quartz.kCGAnnotatedSessionEventTap, event_mask):
                started_sources.append("CGEventTap(annotated)")
            if self._start_appkit_monitor():
                started_sources.append("NSEvent global monitor")
        if not started_sources:
            print(
                "ERROR: Could not start any media-key event backend.\n"
                "Primary backend failed: MPRemoteCommandCenter + silent audio.\n"
                "Optional fallback: set HANDSFREE_ENABLE_LEGACY_TAPS=1 for CGEventTap backends.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(
            f"[media-key] Active backends: {', '.join(started_sources)}",
            file=sys.stderr,
        )

        try:
            while True:
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.5)
                )
        except KeyboardInterrupt:
            print("\n[media-key] Stopped.", file=sys.stderr)
        finally:
            if self._global_monitor is not None:
                AppKit.NSEvent.removeMonitor_(self._global_monitor)
                self._global_monitor = None
            for command, selector_name in self._remote_command_bindings:
                try:
                    command.removeTarget_action_(self._remote_target, selector_name)
                except Exception:
                    pass
            self._remote_command_bindings.clear()
            self._remote_target = None
            if self._now_playing_center is not None:
                try:
                    self._now_playing_center.setNowPlayingInfo_(None)
                except Exception:
                    pass
                self._now_playing_center = None
            self._silent_output.stop()


if __name__ == "__main__":
    from config import get_config

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    config = get_config()

    def _print_text(text: str):
        print(f"\n>>> {text}")

    listener = MediaKeyListener(
        on_transcription=_print_text,
        silence_timeout=config.get("silence_timeout", 2.5),
        max_recording=60.0,
        auto_submit=config.get("auto_submit", True),
        auto_submit_after_transcription=config.get("auto_submit_after_transcription", True),
    )
    listener.run()
