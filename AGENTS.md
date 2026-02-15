# Multi-Agent Coordination Protocol

This document governs how multiple agents (Claude Code, Codex, humans) work in parallel on this project without conflicts.

## Agent Registry

| Agent ID | Type | Module Assignment | Status |
|---|---|---|---|
| `human-1` | Human (Leadership) | All — final authority | Active |
| `claude-1` | Claude Code (Lab) | See module ownership | Active |
<!-- Add worker agents as needed -->
<!-- | `codex-1` | Codex (Crowd) | `src/worker-module` | Active | -->

## Module Ownership

One owner per module at a time. Before working on a module, check this table. If it's owned by another active agent, coordinate or work on something else.

| Module | Owner | Interface Doc | Notes |
|---|---|---|---|
<!-- | `src/auth/` | `claude-1` | `docs/contracts/auth-api.md` | In progress | -->
<!-- | `src/data/` | `codex-1` | `docs/contracts/data-api.md` | Blocked on T003 | -->

Update this table when you claim or release a module.

## Communication Protocol

Agents communicate through **files**, not conversation:

| Channel | File | Purpose | Write Rules |
|---|---|---|---|
| Task assignments | `TASKS.md` | Who does what | Claim by writing your agent ID |
| Session state | `docs/HANDOFF.md` | What happened, what's next | Update at session end |
| Decisions | `docs/DECISION_LOG.md` | Why we chose X over Y | Append-only, never edit past entries |
| Findings | `docs/LEARNINGS.md` | What we discovered | Append-only, never edit past entries |
| Work status | `docs/WORKSTREAMS.md` | Workstream progress | Update your workstream's status |

## Merge Protocol

1. Agent completes work on their branch (`work/<agent>/<task>`)
2. Agent updates all relevant docs (HANDOFF, WORKSTREAMS, TASKS)
3. Agent pushes branch to remote
4. Human reviews changes and merges to `main`
5. Other agents pull `main` before starting new work

**Rule:** Only humans merge to `main`. Agents propose; humans approve.

## Conflict Resolution

- **File conflict:** The module owner's version wins. Non-owners must coordinate.
- **Decision conflict:** Document both positions in DECISION_LOG.md, escalate to human.
- **Task conflict:** First agent to write their ID in TASKS.md "Assigned" field claims it.

## Scaling Guidelines

Adapt the protocol to your team size:

| Team Size | What to Use |
|---|---|
| **1 agent** | TASKS.md + HANDOFF.md sufficient. Module ownership optional. |
| **2-3 agents** | Add module ownership table. Use branching conventions. |
| **4-5 agents** | Full protocol: module ownership + interface contracts + merge reviews. |

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
