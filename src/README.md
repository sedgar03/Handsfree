# Source Code — Module Map

> This file maps source code modules to their owners and responsibilities. Update when modules are created or ownership changes.

## Module Map

| Module | Owner | Purpose | Interface Contract |
|---|---|---|---|
<!-- | `src/core/` | `claude-1` | Business logic | `docs/contracts/core-api.md` | -->
<!-- | `src/api/` | `codex-1` | HTTP interface | `docs/contracts/api-core.md` | -->

## Getting Started

<!-- Add language-specific setup instructions here -->
```bash
# TODO: Add setup instructions
```

## Module Guidelines

- Each module should have a single clear responsibility
- Cross-module communication goes through defined interfaces (see `docs/contracts/`)
- Module owner is responsible for tests within their module
- Do not import directly from another module's internals — use the public interface
