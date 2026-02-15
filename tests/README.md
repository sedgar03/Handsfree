# Testing Conventions

## Test Structure

```
tests/
├── unit/           # Fast, isolated tests for individual functions
├── integration/    # Tests for module interactions
└── e2e/            # End-to-end workflow tests
```

## Running Tests

```bash
# TODO: Add test commands per project
# Example:
# pytest tests/                    # Run all tests
# pytest tests/unit/               # Run unit tests only
# pytest tests/ -k "test_auth"     # Run specific tests
```

## Guidelines

- Every module in `src/` should have corresponding tests
- Unit tests: fast, no external dependencies, mock at module boundaries
- Integration tests: test module interactions through contracts
- Name test files to mirror source files (e.g., `src/core/auth.py` → `tests/unit/test_auth.py`)
- Test the contract, not the implementation — tests should survive refactoring
