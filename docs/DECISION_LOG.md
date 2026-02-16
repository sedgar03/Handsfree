# Decision Log

> Append-only record of significant project decisions. Never edit past entries. For architectural/technical decisions, also create an ADR in `docs/adr/`.

---

## Entry Format

```markdown
### D[NNN] — [Decision Title]
- **Date:** YYYY-MM-DD
- **Decided by:** [human/agent ID]
- **Context:** [Why this decision was needed]
- **Decision:** [What was decided]
- **Alternatives considered:** [What else was considered and why it was rejected]
- **Consequences:** [Expected impact, trade-offs]
```

---

<!-- Append new decisions below this line -->

### D001 — Project initialized from NewProject_Template
- **Date:** [YYYY-MM-DD]
- **Decided by:** [human-1]
- **Context:** Needed a structured project setup with multi-agent coordination support.
- **Decision:** Used NewProject_Template as the starting scaffold.
- **Alternatives considered:** Starting from scratch (slower), other templates (less suited to AI-assisted workflows).
- **Consequences:** Project inherits the template's coordination protocol and review gate structure. Can be customized as needed.

### D002 — Use mlx-whisper instead of lightning-whisper-mlx for STT
- **Date:** 2026-02-15
- **Decided by:** human-1 + lead-agent
- **Context:** The charter specified lightning-whisper-mlx for STT, but it does not support whisper-large-v3-turbo (the intended model). Needed to pick an STT library that works with the target model on Apple Silicon.
- **Decision:** Use `mlx-whisper` instead. It supports whisper-large-v3-turbo and is actively maintained.
- **Alternatives considered:** lightning-whisper-mlx (doesn't support target model), whisper.cpp (slower on M-series), mlx-audio (bundles too much, evaluate later).
- **Consequences:** Different pip package name in inline deps. No other code impact — the API is similar. Phase 1 STT implementation will use mlx-whisper.

### D003 — Build output side first (TTS before STT)
- **Date:** 2026-02-15
- **Decided by:** human-1 + lead-agent
- **Context:** Need to decide build order for Phase 1. Both TTS output and STT input are needed for the full loop.
- **Decision:** Build output side first (config → TTS → summarizer → hook → setup), then input side (STT → hotkey → listener).
- **Alternatives considered:** Input first (less immediately useful), parallel (more complex coordination).
- **Consequences:** TTS delivers value immediately — hear Claude working. Input side deferred to follow-up session.
