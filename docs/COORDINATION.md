# Multi-Agent Coordination Protocol

> Reference document for projects with 2+ agents. Solo projects can skip this.
> For a human-facing setup walkthrough, see `ORCHESTRATION_GUIDE.md`.

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
