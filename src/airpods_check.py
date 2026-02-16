"""Check if AirPods are connected via Bluetooth.

Queries system_profiler for connected Bluetooth devices and looks for AirPods.
Returns connection status — informational only, not a hard requirement.
"""

from __future__ import annotations

import json
import subprocess
import sys


def check_airpods_connected() -> tuple[bool, str | None]:
    """Check if AirPods are connected.

    Returns (connected, device_name) — device_name is None if not found.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPBluetoothDataType", "-json"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(result.stdout)

        bt_info = data.get("SPBluetoothDataType", [])
        for section in bt_info:
            devices = section.get("device_connected", [])
            for device_group in devices:
                for name, info in device_group.items():
                    if "airpod" in name.lower():
                        return True, name
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError):
        pass

    return False, None


def print_status():
    """Print AirPods connection status to stderr."""
    connected, name = check_airpods_connected()
    if connected:
        print(f"[airpods] {name} connected.", file=sys.stderr)
    else:
        print("[airpods] No AirPods detected. Stem clicks may not work.", file=sys.stderr)
        print("[airpods] Media key listener will still work with keyboard play/pause.", file=sys.stderr)
    return connected


if __name__ == "__main__":
    connected = print_status()
    sys.exit(0 if connected else 1)
