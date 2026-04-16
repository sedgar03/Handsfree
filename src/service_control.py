"""Start and inspect long-lived Handsfree audio/model services."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from config import (
    CONDUCTOR_PID,
    CONDUCTOR_SOCKET,
    HANDSFREE_TOGGLE,
    LEGACY_HANDSFREE_TOGGLE,
    LISTENER_PID,
    LOG_DIR,
    REPO_ROOT,
    SERVICE_STATUS_DIR,
    SUMMARY_PID,
    SUMMARY_SOCKET,
    TTS_PID,
    TTS_SOCKET,
    WAKE_TOGGLE,
    get_config,
    is_handsfree_enabled,
    is_wake_enabled,
    mark_consume_after,
)
from llama_cpp_server import normalize_model_backend


VALID_TTS_PROVIDERS = {"kokoro", "chatterbox"}


def _uv_bin() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError("uv not found on PATH")
    return uv


def _pid_is_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    if result.returncode == 0 and result.stdout.strip().startswith("Z"):
        return False
    return True


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def _remove_stale_pid(path: Path) -> None:
    pid = _read_pid(path)
    if pid is None or not _pid_is_running(pid):
        path.unlink(missing_ok=True)


def service_status_path(name: str) -> Path:
    return SERVICE_STATUS_DIR / f"{name}.json"


def write_service_status(name: str, state: str, **extra: Any) -> None:
    SERVICE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "state": state,
        "pid": os.getpid(),
        "updated_at": time.time(),
        **extra,
    }
    service_status_path(name).write_text(json.dumps(payload, sort_keys=True) + "\n")


def read_service_status(name: str) -> dict[str, Any]:
    path = service_status_path(name)
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"name": name, "state": "unknown"}
    if not isinstance(payload, dict):
        return {"name": name, "state": "unknown"}
    return payload


def _request_socket(socket_path: Path, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    if not chunks:
        raise RuntimeError("empty service response")
    line = b"".join(chunks).split(b"\n", 1)[0]
    response = json.loads(line.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("bad service response")
    return response


def _ping_socket(socket_path: Path, timeout: float = 0.25) -> dict[str, Any] | None:
    try:
        response = _request_socket(socket_path, {"command": "ping"}, timeout)
    except (OSError, TimeoutError, RuntimeError, json.JSONDecodeError):
        return None
    return response if response.get("ok") else None


def _wait_for_socket(socket_path: Path, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "service did not become ready"
    while time.monotonic() < deadline:
        response = _ping_socket(socket_path, timeout=0.5)
        if response is not None:
            return response
        time.sleep(0.25)
    raise TimeoutError(last_error)


def _wait_for_status(name: str, timeout: float, *, state: str = "ready") -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = read_service_status(name)
    while time.monotonic() < deadline:
        last = read_service_status(name)
        if last.get("state") == state:
            return last
        if last.get("state") == "error":
            raise RuntimeError(str(last.get("error") or f"{name} failed"))
        time.sleep(0.25)
    raise TimeoutError(f"{name} did not become {state}: {last}")


def _desired_summary_identity() -> tuple[str, str]:
    config = get_config()
    model = str(config.get("summary_model") or "mlx-community/Qwen3.5-2B-OptiQ-4bit")
    backend = normalize_model_backend(
        config.get("summary_model_backend"),
        model,
        REPO_ROOT,
    )
    return backend, model


def _desired_conductor_identity() -> tuple[str, str]:
    config = get_config()
    model = str(config.get("conductor_model") or "mlx-community/Qwen3.5-2B-OptiQ-4bit")
    backend = normalize_model_backend(
        config.get("conductor_backend"),
        model,
        REPO_ROOT,
    )
    return backend, model


def _desired_tts_engine() -> str:
    provider = get_config().get("tts_provider")
    if isinstance(provider, str) and provider in VALID_TTS_PROVIDERS:
        return provider
    return "kokoro"


def _tts_daemon_script() -> Path:
    if _desired_tts_engine() == "chatterbox":
        return REPO_ROOT / "src" / "tts_chatterbox_daemon.py"
    return REPO_ROOT / "src" / "tts_daemon.py"


def _annotate_summary_status(payload: dict[str, Any]) -> dict[str, Any]:
    backend, model = _desired_summary_identity()
    desired_tts_provider = _desired_tts_engine()
    annotated = dict(payload)
    annotated["desired_backend"] = backend
    annotated["desired_model"] = model
    annotated["desired_prompt_tts_provider"] = desired_tts_provider
    actual_backend = annotated.get("backend")
    actual_model = annotated.get("model")
    actual_tts_provider = annotated.get("prompt_tts_provider")
    stale = (
        annotated.get("state") == "ready"
        and (
            (actual_backend is not None and actual_backend != backend)
            or (actual_model is not None and actual_model != model)
            or actual_tts_provider != desired_tts_provider
        )
    )
    annotated["stale"] = bool(stale)
    return annotated


def _annotate_conductor_status(payload: dict[str, Any]) -> dict[str, Any]:
    backend, model = _desired_conductor_identity()
    annotated = dict(payload)
    annotated["desired_backend"] = backend
    annotated["desired_model"] = model
    actual_backend = annotated.get("backend")
    actual_model = annotated.get("model")
    stale = (
        annotated.get("state") == "ready"
        and (
            (actual_backend is not None and actual_backend != backend)
            or (actual_model is not None and actual_model != model)
        )
    )

    status = read_service_status("conductor")
    if status.get("state") == "error" and status.get("pid") == annotated.get("pid"):
        annotated["ok"] = False
        annotated["state"] = "error"
        if status.get("error"):
            annotated["error"] = status["error"]

    annotated["stale"] = bool(stale)
    return annotated


def _annotate_tts_status(payload: dict[str, Any]) -> dict[str, Any]:
    desired = _desired_tts_engine()
    annotated = dict(payload)
    annotated["desired_engine"] = desired
    engine = annotated.get("engine")
    requested = annotated.get("requested_engine")
    fallback = bool(annotated.get("fallback_reason"))
    stale = False
    if annotated.get("state") == "ready":
        if isinstance(requested, str):
            stale = requested != desired
        elif isinstance(engine, str):
            stale = engine != desired
        fallback = fallback or (requested == desired and engine != desired)
    annotated["fallback"] = bool(fallback)
    annotated["stale"] = bool(stale)
    return annotated


def _status_without_ping(name: str, pid_path: Path) -> dict[str, Any]:
    pid = _read_pid(pid_path)
    running = _pid_is_running(pid)
    status = read_service_status(name)
    state = status.get("state")
    if running and state in {"ready", "active", "starting", "error"}:
        payload = dict(status)
        payload["pid"] = pid
        payload["ok"] = state in {"ready", "active"}
        return payload
    return {
        "ok": False,
        "state": "starting" if running else "stopped",
        "pid": pid,
    }


def _start_uv_script(
    script: Path,
    *,
    pid_path: Path,
    log_name: str,
    env: dict[str, str] | None = None,
) -> int:
    _remove_stale_pid(pid_path)
    existing_pid = _read_pid(pid_path)
    if _pid_is_running(existing_pid):
        return int(existing_pid)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    merged_env = {**os.environ, **(env or {})}
    cmd = [_uv_bin(), "run", "--script", str(script)]
    with open(log_path, "a") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {' '.join(cmd)}\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=merged_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_pid(pid_path, proc.pid)
    return proc.pid


def start_summary_daemon(*, wait: bool = True, timeout: float = 90.0) -> dict[str, Any]:
    ready = _ping_socket(SUMMARY_SOCKET)
    if ready is not None:
        ready = _annotate_summary_status(ready)
        if not ready.get("stale"):
            return ready
        stop_pid(SUMMARY_PID, name="summary")
    _start_uv_script(
        REPO_ROOT / "src" / "summary_daemon.py",
        pid_path=SUMMARY_PID,
        log_name="summary-daemon.log",
    )
    if not wait:
        return {"ok": True, "state": "starting"}
    return _annotate_summary_status(_wait_for_socket(SUMMARY_SOCKET, timeout))


def start_tts_daemon(*, wait: bool = True, timeout: float = 30.0) -> dict[str, Any]:
    ready = _ping_socket(TTS_SOCKET)
    if ready is not None:
        ready = _annotate_tts_status(ready)
        if not ready.get("stale"):
            return ready
        stop_pid(TTS_PID, name="tts")
    _start_uv_script(
        _tts_daemon_script(),
        pid_path=TTS_PID,
        log_name="tts-daemon.log",
    )
    if not wait:
        return {"ok": True, "state": "starting"}
    return _annotate_tts_status(_wait_for_socket(TTS_SOCKET, timeout))


def start_conductor_daemon(*, wait: bool = True, timeout: float = 90.0) -> dict[str, Any]:
    ready = _ping_socket(CONDUCTOR_SOCKET)
    if ready is not None:
        ready = _annotate_conductor_status(ready)
        if ready.get("ok") and not ready.get("stale"):
            return ready
        stop_pid(CONDUCTOR_PID, name="conductor")
    _start_uv_script(
        REPO_ROOT / "src" / "conductor_daemon.py",
        pid_path=CONDUCTOR_PID,
        log_name="conductor-daemon.log",
    )
    if not wait:
        return {"ok": True, "state": "starting"}
    return _annotate_conductor_status(_wait_for_socket(CONDUCTOR_SOCKET, timeout))


def _pgrep_listener() -> int | None:
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(REPO_ROOT / "src" / "listener.py")],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != os.getpid() and _pid_is_running(pid):
            return pid
    return None


def start_listener(
    *,
    input_mode: str = "wake_word",
    warm_stt: bool = True,
    wait: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    _remove_stale_pid(LISTENER_PID)
    existing_pid = _read_pid(LISTENER_PID) or _pgrep_listener()
    if _pid_is_running(existing_pid):
        if existing_pid is not None:
            _write_pid(LISTENER_PID, existing_pid)
        status = read_service_status("listener")
        return {
            "ok": True,
            "state": "running",
            "pid": existing_pid,
            "status": status,
        }

    write_service_status("listener", "starting", input_mode=input_mode)
    env = {
        "HANDSFREE_INPUT_MODE": input_mode,
        "HANDSFREE_WARM_STT": "1" if warm_stt else "0",
    }
    pid = _start_uv_script(
        REPO_ROOT / "src" / "listener.py",
        pid_path=LISTENER_PID,
        log_name="listener.log",
        env=env,
    )
    if not wait:
        return {"ok": True, "state": "starting", "pid": pid}

    listener = _wait_for_status("listener", timeout, state="ready")
    stt = _wait_for_status("stt", timeout, state="ready") if warm_stt else {}
    return {"ok": True, "state": "running", "pid": pid, "listener": listener, "stt": stt}


def warm_speech(*, timeout: float = 120.0) -> dict[str, Any]:
    summary = start_summary_daemon(wait=True, timeout=timeout)
    tts = start_tts_daemon(wait=True, timeout=timeout)
    return {"ok": True, "summary": summary, "tts": tts}


def warm_conductor(*, timeout: float = 120.0) -> dict[str, Any]:
    conductor = start_conductor_daemon(wait=True, timeout=timeout)
    return {"ok": True, "conductor": conductor}


def stop_conductor_daemon() -> dict[str, Any]:
    stopped = stop_pid(CONDUCTOR_PID, name="conductor")
    return {"ok": True, "stopped": stopped}


def _stop_voice_stack_if_idle() -> dict[str, bool]:
    """Stop warm voice/model services once speech and wake are both disabled."""

    if is_handsfree_enabled() or is_wake_enabled():
        return {
            "summary_stopped": False,
            "tts_stopped": False,
            "conductor_stopped": False,
        }
    return {
        "summary_stopped": stop_pid(SUMMARY_PID, name="summary"),
        "tts_stopped": stop_pid(TTS_PID, name="tts"),
        "conductor_stopped": stop_pid(CONDUCTOR_PID, name="conductor"),
    }


def enable_speech(*, timeout: float = 120.0) -> dict[str, Any]:
    warmed = warm_speech(timeout=timeout)
    HANDSFREE_TOGGLE.parent.mkdir(parents=True, exist_ok=True)
    HANDSFREE_TOGGLE.write_text("")
    timestamp = mark_consume_after()
    return {"ok": True, "enabled": True, "consume_after": timestamp, **warmed}


def disable_speech() -> dict[str, Any]:
    for path in (HANDSFREE_TOGGLE, LEGACY_HANDSFREE_TOGGLE):
        path.unlink(missing_ok=True)
    stopped = _stop_voice_stack_if_idle()
    return {
        "ok": True,
        "enabled": False,
        "kept_reader_warm": is_wake_enabled(),
        **stopped,
    }


def warm_wake(*, timeout: float = 120.0) -> dict[str, Any]:
    summary = start_summary_daemon(wait=True, timeout=timeout)
    tts = start_tts_daemon(wait=True, timeout=timeout)
    listener = start_listener(input_mode="wake_word", warm_stt=True, wait=True, timeout=timeout)
    return {
        "ok": True,
        "summary": summary,
        "tts": tts,
        "listener": listener,
        "stt": read_service_status("stt"),
    }


def enable_wake(*, timeout: float = 120.0) -> dict[str, Any]:
    warmed = warm_wake(timeout=timeout)
    WAKE_TOGGLE.parent.mkdir(parents=True, exist_ok=True)
    WAKE_TOGGLE.write_text("")
    timestamp = mark_consume_after()
    return {"ok": True, "enabled": True, "consume_after": timestamp, **warmed}


def disable_wake() -> dict[str, Any]:
    WAKE_TOGGLE.unlink(missing_ok=True)
    listener_stopped = stop_pid(LISTENER_PID, name="listener")
    write_service_status("stt", "stopped")
    stopped = _stop_voice_stack_if_idle()
    return {
        "ok": True,
        "enabled": False,
        "listener_stopped": listener_stopped,
        **stopped,
    }


def service_status() -> dict[str, Any]:
    summary_ping = _ping_socket(SUMMARY_SOCKET)
    tts_ping = _ping_socket(TTS_SOCKET)
    conductor_ping = _ping_socket(CONDUCTOR_SOCKET)
    listener_pid = _read_pid(LISTENER_PID) or _pgrep_listener()

    return {
        "speech_enabled": is_handsfree_enabled(),
        "wake_enabled": is_wake_enabled(),
        "summary": _annotate_summary_status(summary_ping)
        if summary_ping
        else _annotate_summary_status(_status_without_ping("summary", SUMMARY_PID)),
        "tts": _annotate_tts_status(tts_ping)
        if tts_ping
        else _annotate_tts_status(_status_without_ping("tts", TTS_PID)),
        "conductor": _annotate_conductor_status(conductor_ping)
        if conductor_ping
        else _annotate_conductor_status(_status_without_ping("conductor", CONDUCTOR_PID)),
        "listener": {
            "ok": bool(_pid_is_running(listener_pid)),
            "state": "running" if _pid_is_running(listener_pid) else "stopped",
            "pid": listener_pid,
            "status": read_service_status("listener"),
        },
        "stt": read_service_status("stt"),
    }


def stop_pid(path: Path, *, name: str, timeout: float = 5.0) -> bool:
    pid = _read_pid(path)
    if not _pid_is_running(pid):
        path.unlink(missing_ok=True)
        return True
    assert pid is not None
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            path.unlink(missing_ok=True)
            write_service_status(name, "stopped")
            return True
        time.sleep(0.1)
    return False


def main(argv: list[str] | None = None) -> int:
    del argv
    print(json.dumps(service_status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
