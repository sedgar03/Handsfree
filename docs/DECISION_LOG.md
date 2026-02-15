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
