#!/usr/bin/env bash
# Foreground Handsfree listener for use with usage-hud-app.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/handsfree.sh" --listen-only "$@"
