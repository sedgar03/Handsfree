# [PROJECT NAME] — Agent Operating System

## Mission

<!-- Replace with your project's one-paragraph thesis or hypothesis. This is the north star for all decisions. -->
[One-paragraph mission statement. What are you building/investigating? Why does it matter? What does success look like?]

## Mandatory Startup Protocol

Every session (Claude Code, Codex, or human) MUST read these files in order before doing any work:

1. **This file** (`CLAUDE.md`) — auto-loaded by Claude Code
2. **`docs/PROJECT_CHARTER.md`** — strategic context: vision, hypothesis, success criteria, scope
3. **`docs/HANDOFF.md`** — operational context: what just happened, what's next, blockers
4. **`docs/WORKSTREAMS.md`** — who is working on what, current status

Only after reading all four should you proceed to task-specific work.

## Your Role in This Project

| Role | Who | Authority |
|---|---|---|
| **Leadership** (Project Owner) | Human | Sets vision, approves gates, makes scope decisions, merges to main |
| **Lab** (Lead Agent) | Primary agent | Prototypes, distributes work, synthesizes findings, proposes decisions |
| **Crowd** (Worker Agents) | Additional agents | Execute assigned tasks, report findings, stay within module boundaries |

**Agents MAY:** Execute tasks within their assigned module. Create branches. Append to shared docs (DECISION_LOG, LEARNINGS). Propose architectural changes via ADRs.

**Agents MAY NOT:** Merge to main. Change project scope. Modify another agent's active files. Skip review gates. Delete data or results.

**Escalation:** When uncertain, document the question in HANDOFF.md and wait for human input. Do not guess on high-stakes decisions.

## Work Modes

Every task in TASKS.md declares one of three collaboration modes:

| Mode | When to Use | How It Works |
|---|---|---|
| **Centaur** | Requirements are clear and unambiguous | Agent executes autonomously → human reviews output |
| **Cyborg** | Ambiguous, creative, or exploratory work | Iterative human-agent co-creation, frequent check-ins |
| **Human-Only** | High-stakes, irreversible, or sensitive | Agent prepares materials and analysis; human executes |

## Repository Map

```
CLAUDE.md                  ← You are here. Agent behavioral rules.
AGENTS.md                  ← Multi-agent coordination protocol
TASKS.md                   ← Kanban task tracker with assignments
README.md                  ← Human-facing project overview
docs/
  PROJECT_CHARTER.md       ← Vision, hypothesis, success criteria, scope, risks
  HANDOFF.md               ← Living session state (updated every session end)
  DECISION_LOG.md          ← Append-only record of significant decisions
  LEARNINGS.md             ← Structured findings and discoveries
  WORKSTREAMS.md           ← Parallel work tracker with ownership
  glossary.md              ← Domain terminology definitions
  adr/                     ← Architecture Decision Records
  contracts/               ← Interface contracts between modules
src/                       ← Source code (see src/README.md for module map)
tests/                     ← Test suite (see tests/README.md for conventions)
scripts/                   ← Utility scripts (see scripts/README.md for index)
data/                      ← Input data (gitignored contents, keep .gitkeep)
results/                   ← Output artifacts
research/
  literature/              ← Paper/source summaries
  hypotheses/              ← Formal hypothesis documents
```

## Agent Protocol

### 1. Start
Read CLAUDE.md (auto) → PROJECT_CHARTER.md → HANDOFF.md → WORKSTREAMS.md → your assigned task in TASKS.md.

### 2. Claim Work
In TASKS.md, move your task from **Pending** to **In Progress** and write your agent ID in the "Assigned" field. One task per agent at a time.

### 3. Work
- Stay focused on your claimed task. Do not drift to unassigned work.
- When you make a significant decision, append to `docs/DECISION_LOG.md`.
- When you discover something important, append to `docs/LEARNINGS.md`.
- Respect module ownership in `AGENTS.md` — do not modify files owned by another agent.

### 4. Finish
Before ending your session:
- Update `docs/HANDOFF.md` with: what you did, next steps, blockers, open questions.
- Update `docs/WORKSTREAMS.md` if workstream status changed.
- Move completed tasks to **Completed** in `TASKS.md`.
- Commit with format: `[workstream] action: description`

## Review Gates

Tasks marked `[GATE]` require human approval before proceeding. Agents MUST stop and wait.

| Gate | Name | When | What Gets Reviewed |
|---|---|---|---|
| **G0** | Kickoff | Project start | Charter, initial architecture, task breakdown |
| **G1** | Design | Before implementation | Technical design, interface contracts, ADRs |
| **G2** | Prototype | After first working version | Core functionality, test coverage, findings |
| **G3** | Integration | Before merging workstreams | Cross-module compatibility, end-to-end tests |
| **G4** | Delivery | Before release/publication | Final output, documentation, reproducibility |

## Conventions

### Branching
- `main` — stable, reviewed work only
- `work/<agent>/<task>` — agent task branches (e.g., `work/claude/T003-auth-module`)
- `research/<topic>` — exploratory research (e.g., `research/caching-strategies`)

### Commits
Format: `[workstream] action: description`
Examples:
- `[core] add: user authentication module`
- `[analysis] fix: off-by-one in pagination logic`
- `[docs] update: handoff after auth implementation session`

### File Naming
- Documents: `UPPER_CASE.md` for living project docs, `lower-case.md` for reference docs
- Code: follow language conventions (snake_case for Python, camelCase for JS/TS, etc.)
- Scripts: descriptive snake_case (e.g., `run_migrations.sh`)

## Guardrails

- **Never** delete data files or results without explicit human approval
- **Never** overwrite another agent's uncommitted work
- **Never** make scope-changing decisions without logging them in DECISION_LOG.md
- **Never** merge to `main` without human review
- **Never** skip a `[GATE]` checkpoint — stop and wait for human approval
- **Never** auto-approve on behalf of the human (even if it seems obvious)
- **Always** cite sources when recording learnings or findings
- **Always** note confidence levels (high/medium/low) on findings and recommendations
- **Always** update HANDOFF.md before ending a session
- **Prefer** appending to shared docs over rewriting them
- **Prefer** creating new files over modifying existing results
- **Prefer** small, focused commits over large batch commits

## Four Operating Principles

1. **Always invite AI to the table.** Attempt every task with AI assistance first. If it doesn't work, document why in LEARNINGS.md — that knowledge has value for future sessions.

2. **Be the human in the loop.** Review gates exist because humans must stay engaged. Never rubber-stamp. If you're the human, actually read the output. If you're the agent, make your output reviewable.

3. **Tell the AI what kind of person it is.** Every task in TASKS.md includes a Role field defining the agent's persona and expertise for that task. Use it.

4. **Assume this is the worst AI you'll ever use.** Build workflows that improve as models improve. Document gaps and limitations. Structure output for easy human verification. Tomorrow's model will be better — make it easy to swap in.

## Build / Test / Lint Commands

<!-- Fill per project -->
```bash
# Build
# TODO: Add build command

# Test
# TODO: Add test command

# Lint
# TODO: Add lint command
```

## Architecture Overview

<!-- Fill per project -->
[Describe the high-level architecture here once the initial design is complete. Reference ADR-001 for the rationale.]

## Key Gotchas

<!-- Append as the project matures -->
<!-- Format: - **[area]**: gotcha description -->
