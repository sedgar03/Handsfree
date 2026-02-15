# Orchestration Guide — How to Actually Run This

> This guide is for the human project owner. It explains what to run, how many agents, and how coordination actually works in practice.

## Prerequisites

Install the agent CLIs you plan to use. You only need the ones relevant to your setup.

| Agent Type | Install | Authenticate | Docs |
|---|---|---|---|
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` | Runs auth flow on first launch | [claude.ai/claude-code](https://claude.ai/claude-code) |
| **Codex CLI** | `npm install -g @openai/codex` | `codex auth` or set `OPENAI_API_KEY` | [github.com/openai/codex](https://github.com/openai/codex) |

**Verify installation:**
```bash
claude --version   # Claude Code
codex --version    # Codex CLI
```

**Other agent types:** Any tool that can read files and write to a git branch works with this template. The coordination is file-based, so the agent just needs filesystem access and the ability to follow written instructions (CLAUDE.md, TASKS.md). Future CLI agents slot in the same way — install, authenticate, point at the repo.

## The Mental Model

You are a **manager running a small team**. The agents are your reports. They don't talk to each other directly — they coordinate through shared documents, just like an async remote team using a shared wiki. Your job is to:

1. **Shape the work with your lead agent** — describe what you need, the lead agent drafts tasks, acceptance criteria, and assignments. You refine together.
2. **Launch worker agents** — each one opens the project, reads CLAUDE.md, self-orients from the docs
3. **Stay in the loop** — review gates, merge branches, resolve conflicts
4. **Close out sessions** — make sure handoff docs are current for the next round

The worker agents never coordinate themselves. You and your lead agent are the orchestrators.

## How Task Preparation Works

Task preparation is a **Cyborg activity** — you and your lead agent do it together. You don't need to fill out TASKS.md by hand.

**Typical flow:**
1. Open the project in Claude Code (your lead agent). Run `/start-session`.
2. Describe what you want in plain language: *"We need an auth module, a data pipeline, and a dashboard."*
3. The lead agent drafts the tasks — title, description, acceptance criteria, role field, work mode, dependencies, and gate markers — and writes them to TASKS.md.
4. You review, adjust, and approve. This is Gate G0.
5. Together, you assign agent IDs and update AGENTS.md with module ownership.

**The lead agent's job is to turn your intent into structured delegation docs.** You describe the *what* and *why*; it produces the *how*, the task breakdown, and the acceptance criteria. You approve.

**For worker agents** (the ones you launch separately), the task is already fully specified in TASKS.md before they start. They read it and execute. No negotiation needed — the lead agent already did the planning with you.

## How Role Assignment Works

Roles are **not auto-detected** — they're assigned during task preparation.

- The **lead agent** is whichever Claude Code instance you're working with interactively. It has the Lab role by default.
- **Worker agents** get their assignments through TASKS.md ("Assigned" field) and AGENTS.md (module ownership). You and the lead agent set these up together before launching workers.
- Each worker agent starts, reads CLAUDE.md → PROJECT_CHARTER → HANDOFF → WORKSTREAMS → TASKS.md, finds its assigned task, and begins.

If you want a worker to self-select from available tasks, leave multiple tasks with `_unassigned_` and include an instruction like "Claim one pending task that matches your strengths." But pre-assignment (done during your planning session with the lead agent) is more predictable.

## Setups by Team Size

### Solo: 1 Claude Code Instance (Most Common)

This is the default for most projects. You and one Claude Code session working interactively. The single agent plays both the Lab and Crowd roles — it helps you plan tasks *and* executes them.

**What to do:**
- Open the project in Claude Code — CLAUDE.md auto-loads
- Run `/start-session` to get oriented
- Describe what you want to accomplish — the agent drafts tasks in TASKS.md
- Work interactively (Cyborg mode for most tasks)
- Run `/end-session` when you're done

**What you can skip:**
- AGENTS.md module ownership (you're the only one)
- Interface contracts (no cross-agent boundaries)
- Branch-per-task (just work on `main` or a single feature branch)

**What still matters:**
- TASKS.md — even solo, having the agent write out tasks keeps you both focused and creates a record
- HANDOFF.md — continuity between sessions (Claude Code loses context between sessions)
- DECISION_LOG.md — you'll forget why you made choices
- Review gates — resist the urge to skip, especially G0 and G4

### Duo: 1 Claude Code + 1 Codex (or 2 Claude Code)

You have two agents working on different parts of the project simultaneously. This is where the coordination protocol starts to earn its keep.

**Planning phase (you + lead agent, Cyborg):**
1. Run `/start-session` in your interactive Claude Code session
2. Describe the work: *"I need an auth module and a data pipeline built in parallel."*
3. The lead agent drafts tasks in TASKS.md with assignments — e.g., T003 for `claude-1`, T004 for `codex-1`
4. The lead agent updates AGENTS.md with module ownership — **one module per agent, no overlap**
5. If modules interact, the lead agent drafts an interface contract in `docs/contracts/`
6. You review and approve the plan (Gate G1)

**Launch phase:**
- **Claude Code (lead):** Already running. It works on its own assigned task, or you tackle it together.
- **Codex (worker):** Point it at the repo with a prompt like: "Read CLAUDE.md, then docs/PROJECT_CHARTER.md, then docs/HANDOFF.md. Your agent ID is `codex-1`. Work on task T004 in TASKS.md."
- Each agent works on its own branch: `work/claude-1/T003-auth` and `work/codex-1/T004-data`

**Coordination is file-based:**
- Agents don't know about each other at runtime
- They find their assignment by reading TASKS.md
- They respect module boundaries by reading AGENTS.md
- If one finishes early, you merge their branch and update TASKS.md before the other agent might need their output

**Merge flow:**
1. Agent pushes branch
2. You review the diff
3. You merge to `main`
4. You tell the other agent to pull (or it pulls at the start of its next session)

### Squad: 3-5 Agents (Full Protocol)

Multiple Claude Code instances, Codex tasks, or a mix. This is where everything in the template is used.

**Planning phase (you + lead agent, Cyborg):**
1. Run `/start-session` in your interactive Claude Code session (the lead agent)
2. Describe the overall work and how you want it divided
3. The lead agent drafts the full AGENTS.md registry, TASKS.md entries, interface contracts, and WORKSTREAMS.md groupings
4. You review and refine together — this is the most important step at this scale
5. Approve the plan (Gate G0/G1) before launching any workers

**How to launch (example with 3 Claude Code instances):**

Terminal 1 (interactive — you + lead agent):
```bash
cd /path/to/project
claude  # CLAUDE.md auto-loads
# Run /start-session, work on T001 interactively (Cyborg mode)
```

Terminal 2 (autonomous worker):
```bash
cd /path/to/project
claude --print "Read CLAUDE.md, then PROJECT_CHARTER.md, then HANDOFF.md. \
  You are agent claude-2. Work on task T002 in TASKS.md. \
  When done, update HANDOFF.md and push your branch."
```

Terminal 3 (autonomous worker):
```bash
cd /path/to/project
claude --print "Read CLAUDE.md, then PROJECT_CHARTER.md, then HANDOFF.md. \
  You are agent claude-3. Work on task T003 in TASKS.md. \
  When done, update HANDOFF.md and push your branch."
```

**Your job while agents work:**
- Monitor branches: `git branch -a` and check for pushes
- Review completed work before merging
- Resolve any conflicts between agent branches
- Update TASKS.md as work completes
- Feed results from one agent's work into the next agent's task

## What About Hooks?

Hooks are **not used for coordination** in this template. Here's why:

- Hooks run shell commands in response to Claude Code events — they're great for linting, formatting, or running tests automatically
- But they can't coordinate between separate Claude Code instances (each instance is its own process)
- File-based coordination (TASKS.md, HANDOFF.md, branches) works across any agent type — Claude Code, Codex, humans, future tools

**Hooks you might add per-project:**
- Pre-commit: run linter/formatter
- Post-tool-call: auto-run tests after file edits
- But these are per-agent quality guardrails, not cross-agent coordination

## What About `/start-session`?

`/start-session` is designed for **one agent at a time**. When you run it:

1. It reads the charter, handoff, workstreams, and tasks
2. It produces a briefing summarizing current state
3. It asks "What would you like to work on?"

For the **lead agent** (the one you're working with interactively), this is great — run it at the start of every session.

For **worker agents** (autonomous), skip `/start-session` and instead give them explicit instructions: "You are agent X, work on task Y." They still read the same files during startup (CLAUDE.md mandates it), but you don't need the interactive briefing flow.

## Practical Tips

**Start simple, scale up:**
Don't start with 5 agents on day one. Begin with solo (1 Claude Code), get the project shaped, then add agents when you have cleanly separable work.

**The bottleneck is always task decomposition:**
Agents are fast. The important work is defining clear, non-overlapping tasks — but you don't do this alone. Describe what you need to your lead agent and iterate on the task breakdown together. Spend time getting the plan right before launching workers.

**Pull before you push:**
Before launching a new agent session, make sure `main` has all merged work. Stale branches cause merge pain.

**One module, one owner, one branch:**
The simplest conflict-prevention rule. If two agents need to touch the same file, that's a sign you need to split the module or define a contract.

**Don't run parallel agents on coupled work:**
If task B depends on task A's output, run them sequentially. Parallel agents work best on independent modules.

**Codex vs Claude Code:**
- **Claude Code** is better for interactive/Cyborg work — you and the agent iterate together
- **Codex** is better for well-defined Centaur tasks — clear input, clear acceptance criteria, agent runs and delivers
- Use both: Claude Code for the lead agent role, Codex for worker tasks with crisp specs
