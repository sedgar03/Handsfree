# Agent Instructions

> **This file is auto-read by Codex CLI.** Claude Code auto-reads `CLAUDE.md` instead, which contains the full operating system. If you're Codex or another non-Claude agent, this file is your primary instruction set.

## Startup Protocol

Before doing any work, read these files in order:

1. **`CLAUDE.md`** — Master operating doc: mission, guardrails, conventions, review gates
2. **`docs/PROJECT_CHARTER.md`** — Strategic context: vision, hypothesis, success criteria, scope
3. **`docs/HANDOFF.md`** — Operational context: what just happened, what's next, blockers
4. **`docs/WORKSTREAMS.md`** — Who is working on what, current status
5. **`TASKS.md`** — Find your assigned task (search for your agent ID)

Then begin work on your assigned task. If no task is assigned to you, report back and wait.

## Key Rules

These are extracted from CLAUDE.md. Read the full version for details.

- **Never** merge to `main` — only humans merge
- **Never** modify files owned by another agent (check module ownership in `docs/COORDINATION.md`)
- **Never** skip a `[GATE]` checkpoint — stop and wait for human approval
- **Always** update `docs/HANDOFF.md` before ending your session
- **Always** work on a branch: `work/<your-agent-id>/<task-id>`
- **Always** commit with format: `[workstream] action: description`

## Agent Registry

| Agent ID | Type | Role | Module Assignment | Status |
|---|---|---|---|---|
| `human-1` | Human | Leadership | All — final authority | Active |
| `claude-1` | Claude Code | Lab (Lead) | See module ownership | Active |
<!-- Add worker agents as needed -->
<!-- | `claude-2` | Claude Code | Crowd (Worker) | `src/api/` | Active | -->
<!-- | `codex-1` | Codex | Crowd (Worker) | `src/data/` | Active | -->

## Module Ownership

One owner per module at a time. Before working on a module, check this table. If it's owned by another active agent, coordinate or work on something else.

| Module | Owner | Interface Doc | Notes |
|---|---|---|---|
<!-- | `src/auth/` | `claude-1` | `docs/contracts/auth-api.md` | In progress | -->
<!-- | `src/data/` | `codex-1` | `docs/contracts/data-api.md` | Blocked on T003 | -->

Update this table when you claim or release a module.

## Multi-Agent Protocol

For detailed coordination rules (communication channels, merge protocol, conflict resolution, scaling guidelines), see **`docs/COORDINATION.md`**.

## Coding Style

<!-- Fill per project. Examples: -->
<!-- - Python: Black formatter, type hints, docstrings on public functions -->
<!-- - TypeScript: Prettier, strict mode, JSDoc on exports -->
<!-- - General: Functions under 50 lines, files under 300 lines -->

## PR Guidelines

<!-- Fill per project. Examples: -->
<!-- - PR title matches commit format: [workstream] action: description -->
<!-- - PR description includes: what changed, why, how to test -->
<!-- - All tests must pass before review -->
<!-- - At least one human approval required -->
