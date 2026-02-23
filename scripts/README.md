# Scripts Index

> Utility scripts for development, deployment, and maintenance tasks.

| Script | Purpose | Usage |
|---|---|---|
| `setup.sh` | One-time setup: models, config, Claude hooks, smoke test | `./scripts/setup.sh` |
| `handsfree.sh` | Launch handsfree Claude session (listener + hooks mode toggle) | `./scripts/handsfree.sh --media-key` |
| `check_permissions.sh` | Wrapper to run permission diagnostics | `./scripts/check_permissions.sh` |
| `check_permissions.py` | Detailed permission checks (called by shell wrapper) | `uv run --script scripts/check_permissions.py` |

## Guidelines

- Scripts should be idempotent where possible (safe to run multiple times)
- Include a usage comment at the top of each script
- Use descriptive snake_case naming
