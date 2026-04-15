# Conductor Mode — Spec

**Status**: Draft v0; Phase 1 scaffold started
**Date**: 2026-04-14
**Author**: Steven + Claude

## Vision

A voice-first, always-on local orchestrator that you talk to like a collaborator. It doesn't have to be the smartest model — it has to be **resident, responsive, and know when to delegate**. It handles casual brainstorming itself, and for heavier work it dispatches to specialized sub-agents (Claude Code sessions in tmux panes, Claude API for hard reasoning, other tools).

Think of it as a conductor in front of an orchestra of AI agents. You talk to the conductor. The conductor decides what gets played and by whom.

## Why this is a different interaction model

Today's `handsfree` pipeline is **one-way summarization**:

```
Claude Code output → summarizer → TTS → your ears
```

It's excellent for passive monitoring of a coding session, but it's not conversational. You can't bounce ideas, ask follow-ups, redirect focus, or hand a task off to a new agent without leaving voice context.

Conductor mode inverts the relationship. The orchestrator is the **primary interface**, and Claude Code (and anything else) becomes a tool the orchestrator can wield:

```
        you ⇄ Conductor (local LLM, voice-first)
                     │
        ┌────────────┼────────────┬──────────────┐
        ▼            ▼            ▼              ▼
   tmux panes   Claude Code   Claude API     other tools
   (watched)   (dispatched)   (escalation)   (shell, web)
```

The conductor maintains state across the whole session: what's open, what's running, what we just talked about, what we're trying to accomplish.

## Core capabilities

### 1. Conversational (the baseline)

Casual chat, brainstorming, rubber-ducking. The conductor responds directly, leveraging expressive TTS (Chatterbox tags: `[laugh]`, `[sigh]`, `[sarcastic]`, `[happy]`, etc.) to sound like a collaborator rather than a narrator.

Example:
> *"Hey, I'm thinking about how to handle rate limiting on the new endpoint."*
> → Conductor answers directly. No Claude Code invocation.

### 2. Dispatch

The conductor can spawn and direct Claude Code (or Codex) instances in tmux panes with specific prompts, then monitor their output and summarize back.

Example:
> *"Open a Claude Code session in pane 2 and have it look at the auth middleware for the token storage bug legal flagged."*
> → Conductor: `tmux split-window` → launches `claude-code` → types the prompt → watches the pane → speaks summary when Claude finishes.

### 3. Status awareness

The conductor knows what's running in every tmux pane and can report on it unprompted or on request.

Example:
> *"What's happening in my other terminals?"*
> → *"Pane 3 finished the test run — all green. Pane 5's Claude Code session is still working on the migration, it's about 40% through the files."*

### 4. Escalation

When a query exceeds the local model's ability, the conductor knows to hand off to a bigger model (Claude Opus via API, or a resident Claude Code instance).

Example:
> *"I need a second opinion on whether this migration is safe under concurrent writes."*
> → Conductor: *"Let me ask Claude Opus."* → API call → speaks the Opus response back.

### 5. Inter-pane routing

The conductor can pipe voice input into a specific terminal, relay its output, and switch focus — all without you touching the keyboard.

Example:
> *"Tell Claude Code in pane 4 to also add a retry with exponential backoff."*
> → Conductor injects the prompt into pane 4, confirms delivery, starts watching for response.

## Architectural components

### The conductor LLM

**Requirements**:
- Small enough to stay resident (<10GB memory)
- Fast enough for conversational latency (<2s to first token)
- Strong instruction-following + tool use (JSON function calling)
- Runs locally (MLX on Apple Silicon)

**Candidates** (to audition):
- `mlx-community/Qwen2.5-7B-Instruct-4bit` — strong tool use, good reasoning
- `mlx-community/Llama-3.3-8B-Instruct-4bit` — good conversation, solid function calling
- `mlx-community/gemma-3-9b-it-4bit` — newer, mixed reviews on tool use
- `mlx-community/Qwen2.5-3B-Instruct-4bit` — fallback if 7B is too slow

### Tool interface

The conductor sees these as callable tools (JSON function calls):

| Tool | Purpose |
|---|---|
| `list_panes()` | Enumerate tmux panes with their titles / current command |
| `read_pane(id, lines=50)` | Capture recent output from a pane |
| `send_to_pane(id, text, press_enter=True)` | Inject input into a pane |
| `spawn_claude_code(prompt, pane=None)` | New pane + launch `claude-code` with prompt |
| `focus_pane(id)` | Switch active pane |
| `summarize(text, verbosity)` | Existing summarizer daemon |
| `speak(text, emotion=None)` | Existing TTS daemon (w/ Chatterbox tag injection) |
| `ask_claude_api(prompt, model="opus")` | Escalate to Anthropic API |
| `remember(key, value)` | Write to session memory |
| `recall(key)` | Read from session memory |

All tools are local Python functions the orchestrator harness exposes — the LLM just emits structured JSON.

### State the conductor owns

- **Pane registry**: which tmux panes exist, what's running in each, last output, last activity time
- **Session memory**: project context, in-flight tasks, recent conversation turns
- **Escalation ledger**: which hard questions went to the API and what came back
- **User preferences**: verbosity, voice choice, which panes are "muted"

### Integration with existing handsfree stack

Reuse, don't replace:

| Existing component | Role in Conductor mode |
|---|---|
| `src/media_key_listener.py` / wake-word listener | Captures user voice → STT → sends to conductor |
| `src/stt.py` (Whisper) | Unchanged |
| `src/summary_daemon.py` | Available to conductor as the `summarize` tool |
| `src/tts_daemon.py` | Available as the `speak` tool; upgraded to support Chatterbox tags |
| `hooks/handsfree_hook.py` / `codex_notify.py` | Still fire on Stop events — but now write into the conductor's pane registry instead of speaking directly |
| `src/broker.py` / `src/event_queue.py` | Conductor consumes the same event stream |

The new piece is a `src/conductor_daemon.py` that holds the LLM, the tool registry, and a Unix socket interface — architecturally identical to the existing `summary_daemon` and `tts_daemon`.

## Interaction modes

Conductor mode should coexist with existing modes, not replace them:

1. **Passive summary mode** (today): hooks fire, summaries get spoken. No conductor needed.
2. **Conductor mode** (new): you press-to-talk or say a wake word, voice goes to conductor, conductor decides what to do.
3. **Hybrid**: conductor is running, but hooks still fire summaries when you're not talking. Conductor merges those events into its state so follow-up questions work.

## Open decisions

- [ ] **Name**: "Conductor" is a working title. Alternatives: "Orchestra", "Maestro", "Head"
- [ ] **Which local model**: audition 3B vs 7B vs 8B for latency/quality tradeoff
- [ ] **Escalation source**: Claude API only, or also a resident Claude Code session as a "smart tool"
- [ ] **Persistence**: session-scoped memory, or SQLite-backed across restarts
- [ ] **Pane discovery**: conductor polls tmux, or subscribes to tmux hooks, or both
- [ ] **Emotion tag strategy**: model emits tags directly vs a post-processing layer infers them from content
- [ ] **Interrupt model**: can you talk over the conductor mid-sentence, or wait for it to finish
- [ ] **Multi-pane talk-to-Claude**: if multiple Claude Code sessions are running, how does the conductor disambiguate "Claude" references
- [ ] **Fallback when local model is down**: degrade to current handsfree-summary pipeline, or refuse to start
- [ ] **Security**: the conductor can execute shell commands via `send_to_pane` — does it need confirmation for destructive operations, a blocklist, a sandboxed shell

## Phased delivery (proposed)

Small, independently useful steps. Each phase ships something working.

**Phase 1 — Local LLM daemon**
Minimal `conductor_daemon.py`: loads a model, exposes Unix socket, takes text in → text out. No tools yet. Prove latency is acceptable.

Initial implementation uses the already-cached `mlx-community/Qwen3.5-2B-OptiQ-4bit`
as the smallest practical smoke-test conductor model. The model is configurable
via `conductor_model` in `~/.claude/voice-config.json`.

`conductor_backend: "auto"` keeps the MLX path for MLX/Hugging Face model IDs
and selects the llama.cpp path for local `.gguf` files or directories containing
one `.gguf`. The llama.cpp backend starts Homebrew `llama-server` as a child of
the conductor daemon, then sends chat turns through the OpenAI-compatible
`/v1/chat/completions` endpoint.

Commands:

```bash
PYTHONPATH=src uv run python -m broker warm conductor --timeout 300
PYTHONPATH=src uv run python -m broker conductor chat "Talk me through the next step"
PYTHONPATH=src uv run python -m broker conductor reset
```

**Phase 2 — Pane awareness (read-only)**
Add `list_panes` and `read_pane` tools. Conductor can answer "what's in pane 3?" No actions yet.

**Phase 3 — Voice loop integration**
Wire listener → conductor → TTS. Now you can have a voice conversation with the local model about what's happening in your terminals.

**Phase 4 — Write actions**
Add `send_to_pane`, `spawn_claude_code`, `focus_pane`. Now the conductor can actually direct work. Add confirmation for destructive actions.

**Phase 5 — Escalation**
Add `ask_claude_api` tool. Conductor learns to delegate hard questions.

**Phase 6 — Expressive TTS**
Wire Chatterbox as the `speak` tool. Teach the conductor when to emit emotion tags.

**Phase 7 — Persistent memory**
SQLite-backed state. Conductor remembers projects and context across sessions.

## Non-goals

- **Replacing Claude Code**: the conductor is not meant to do heavy coding work itself. It's an orchestrator.
- **A general assistant**: scope is coding, project context, and terminal orchestration. Not calendar, email, etc.
- **Cloud-first**: the orchestrator is local by default. Cloud is only an escalation path the user opts into.
- **Beating the summarization pipeline on summarization**: existing summary flow keeps working. Conductor leverages it, doesn't replace it.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Local 7B model too slow for conversation on M5 | Benchmark before committing; fall back to 3B |
| Local model bad at tool use | Use Qwen/Llama known to be tool-use-trained; write robust JSON parser with recovery |
| Conductor accidentally runs destructive commands | Explicit confirmation for any `rm`, `git push --force`, writes to shared infra |
| User talks too fast for the local model | Buffer STT output; conductor can say "give me a second" and use `[sigh]` tag to sound natural |
| Memory grows unbounded | Bounded context window + SQLite with aging-out |

## Related work

- `docs/TTS_MIGRATION_RESEARCH.md` — the summarizer migration to MLX Qwen-1.5B is a precursor; same daemon pattern applies
- `docs/HUD_QUEUE_WORKFLOW.md` — the event queue the conductor consumes
- `docs/PAUSE_HANDOFF.md` — interaction with pause/resume semantics
- Chatterbox demos in `scripts/chatterbox_*.py` — the expressive voice layer the conductor speaks through
