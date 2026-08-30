---
description: Top rule - all work is recorded in Linear. Every commit names its issue id or a logged bypass. Enforced by a commit-msg gate, so it holds whether or not this file is loaded.
paths:
  - "**/*.py"
  - "**/*.sh"
  - "**/*.md"
  - "**/*.json"
  - "**/*.yml"
---

# Linear-First: work that isn't recorded didn't happen (ENFORCED)

Founder directive 2026-07-26, top rule, all repos and instances: work is recorded
in Linear, with a status matching reality and the command that proves it. Blocker:
`linear-issue-ref-check.py` (lefthook `commit-msg`, exits 1 with no issue id);
test `test-linear-issue-ref-check.sh`, 17 cases, in the capability manifest. Add
`(ASK-51)` anywhere in the message, or `[no-issue: reason]` which is allowed and
appended to `q-system/output/linear-bypass.jsonl` so bypasses stay countable. The
gate's own stderr carries the full fix, so it teaches on failure. Holes:
`--no-verify` skips all lefthook hooks; presence of an id is checked, not its
existence or status; uncommitted work is outside the gate. `auto-commit.py`
declares the hatch by design (unattended, cannot know the issue). kipi-system only
for now; fleet needs the lefthook stage in the instance template.

<!-- enforcement -->
```json
[
  {
    "clause": "Linear-First: work that isn't recorded didn't happen",
    "status": "ENFORCED",
    "exec": "q-system/.q-system/scripts/linear-issue-ref-check.py",
    "config": "lefthook.yml",
    "test": "q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh",
    "directives": 0
  }
]
```
