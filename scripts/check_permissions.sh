#!/usr/bin/env bash
# Run macOS permission checks required for handsfree operation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UV="${UV:-/Users/steven_edgar/.local/bin/uv}"

if ! command -v "$UV" &>/dev/null; then
    echo "ERROR: uv is required to run permission checks."
    echo "Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

exec "$UV" run --script "$REPO_ROOT/scripts/check_permissions.py" "$@"
