# Interface Contracts

> Define interfaces between modules BEFORE coding. This prevents integration conflicts when multiple agents work in parallel.

## Why Contracts?

When two agents build modules that need to talk to each other, they need to agree on the interface first. A contract defines:
- **Inputs:** What data the module accepts
- **Outputs:** What data the module returns
- **Errors:** What failure modes exist
- **Constraints:** Performance, security, or data requirements

## How to Define a Contract

1. Create a file in this directory: `<module-a>-<module-b>.md`
2. Use the template below
3. Both module owners review and agree before coding begins
4. Reference the contract in `AGENTS.md` module ownership table

## Contract Template

```markdown
# Contract: [Module A] ↔ [Module B]

## Version: 1.0
## Status: [Draft | Agreed | Implemented]
## Owners: [Agent IDs]

### Interface

[Define the API, function signatures, message format, or data schema]

### Example

[Show a concrete example of the interface in use]

### Error Handling

[How errors are communicated and what the caller should do]

### Constraints

- [Performance: e.g., must respond within 100ms]
- [Data: e.g., maximum payload size 1MB]
```
