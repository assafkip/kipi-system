---
paths:
  - "**/*.ts"
  - "**/*.tsx"
---

# TypeScript Testing Rules

- Always use TDD: write a failing test first, then implement the minimum code to pass, then refactor.
- Use Vitest as the test framework.
- Use React Testing Library for component tests. Never use Enzyme.
- Test behavior, not implementation details. Query by role/label, not by class/id.
- Mock external dependencies at module boundaries, not deep internals.
- Use `describe` blocks to group related tests. Use clear test names that read as sentences.
- Aim for 90%+ coverage on all new code.
- Prefer `userEvent` over `fireEvent` for simulating user interactions.
