---
paths:
  - "**/*.py"
---

# Python Testing Rules

- Always use TDD: write a failing test first, then implement the minimum code to pass, then refactor.
- Use pytest as the test framework. Never use unittest directly.
- Use pytest-mock for mocking. Avoid unittest.mock.
- Use fixtures for shared test setup. Prefer factory fixtures over complex setup methods.
- Aim for 90%+ coverage on all new code.
- Name tests descriptively: `test_<function>_<scenario>_<expected_result>`.
- Keep tests isolated — no shared mutable state between tests.
- Use parametrize for testing multiple inputs against the same logic.
