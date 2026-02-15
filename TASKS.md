# Task Tracker

## Pending

### T001: [Example] Define project architecture
- **Description:** Design the high-level system architecture. Document module boundaries, data flow, and key interfaces. Produce ADR-001.
- **Acceptance Criteria:**
  - [ ] ADR-001 written and reviewed
  - [ ] Module map documented in `src/README.md`
  - [ ] Interface contracts defined in `docs/contracts/`
- **Assigned:** _unassigned_
- **Mode:** Cyborg
- **Role:** You are a senior software architect responsible for designing a clean, modular system that balances simplicity with extensibility.
- **Priority:** High
- **Dependencies:** Blocked by T000
- **Gate:** `[GATE] G1 — Design review required before implementation`

### T002: [Example] Implement core module
- **Description:** Build the primary module per the architecture defined in T001.
- **Acceptance Criteria:**
  - [ ] Core module implemented per contract
  - [ ] Unit tests passing with >80% coverage
  - [ ] Integration points stubbed for dependent modules
- **Assigned:** _unassigned_
- **Mode:** Centaur
- **Role:** You are a senior developer responsible for writing clean, well-tested production code.
- **Priority:** High
- **Dependencies:** Blocked by T001

---

## In Progress

### T000: Initialize project
- **Description:** Complete project setup: fill in PROJECT_CHARTER.md, define initial architecture, set up build tooling.
- **Acceptance Criteria:**
  - [ ] PROJECT_CHARTER.md filled with real project details
  - [ ] Build/test/lint commands working
  - [ ] Initial architecture documented
- **Assigned:** `human-1`
- **Mode:** Cyborg
- **Role:** Project owner performing initial setup with AI assistance.
- **Priority:** Critical
- **Dependencies:** None
- **Gate:** `[GATE] G0 — Kickoff review: charter + architecture must be approved`

---

## Completed

<!-- Move completed tasks here with completion date -->
<!-- ### T00X: Task title -->
<!-- - **Completed:** YYYY-MM-DD -->
<!-- - **Outcome:** Brief summary of what was delivered -->
