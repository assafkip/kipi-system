---
id: crpr-digest-asserts-real-canonical
title: Prove the digest read the live canonical tree, by named value
status: open
priority: p0
parent_prd: prd-canonical-read-path-repair-2026-08-22
allowed_files:
  - q-system/.q-system/scripts/test/test-canonical-digest-real-values.py
disallowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py
  - .claude/**
  - .prd-os/**
required_checks:
  - python3 q-system/.q-system/scripts/test/test-canonical-digest-real-values.py --self-test
required_reviews:
  - runtime-owner
bypass_check: "python3 q-system/.q-system/scripts/test/test-canonical-digest-real-values.py --self-test"
gate_lifecycle: historical-receipt
deliverables_count: 1
---
<!-- added-by: sana prd=prd-canonical-read-path-repair-2026-08-22 finding=finding-14 at=2026-08-22T21:10:00Z -->
<!-- Added AFTER the original split. finding-14 (blocker) and finding-9 were deferred
     because no entry in the original six could close them: all six are fixture-level
     and structurally cannot prove a live canonical tree was read. This entry exists
     to make that claim executable rather than deferred. -->

# Prove the digest read the live canonical tree, by named value

## Context

Parent PRD: `.prd-os/prds/prd-canonical-read-path-repair-2026-08-22.md`

Closes Codex finding-14 (blocker) and finding-9 (major), which name the same hole
from two sides: the PRD claimed every acceptance check asserts a real canonical
value, while no manifest criterion named a decision id or objection string. Codex's
counterexample was a digest of
`{"talk_tracks":{"metaphor":"placeholder"},"objections":[],"decisions":[],...}` --
nonempty, and therefore accepted by any "some field is set" assertion, while having
read nothing.

## Acceptance

Calls `canonical_digest` against a REAL instance tree and asserts NAMED values.

- **Never assert `digest["valid"]`.** Measured 2026-08-22, the LIVE tree returns
  `valid: false` (3 of 7 `_validate_digest` checks) because those files were retired
  to pointer docs whose headings no longer match the template the parsers target. So
  `valid` is not a signal in either direction. (Shape mismatch: `sp-8804dee7`.)
- **Never assert mere non-emptiness.** That is finding-14 verbatim.
- **Derive the expected value; never hardcode it.** This repo is PUBLIC. An
  independent reader (raw regex for `RULE-\d{4}-\d{2}-\d{2}` over the instance's own
  `decisions.md`) produces the expectation; the shipping parser must then return the
  same id. Two independent implementations agreeing on a value present only in that
  tree is what proves the tree was read, and it keeps the checker instance-agnostic.
- **Negative control, wired into `--self-test` so the required_check exercises it.**
  Measured: the live `decisions.md` carries exactly 1 dated rule id; the fossil
  `q-system/canonical/decisions.md` carries 0 (only `RULE-XXX` / `RULE-001..003`
  template scaffolding). The checker MUST pass against live and MUST fail against
  both a synthetic template tree and the real fossil. `--self-test` exits nonzero if
  either fossil case passes.
- **Refuse, never skip,** when no qualifying instance is found. A skip is a false green.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] Prove the digest read the live canonical tree, by named value

## Evidence

Ran: `python3 q-system/.q-system/scripts/test/test-canonical-digest-real-values.py --self-test` -> rc=0

```
[load-path] canonical_digest imported from .../plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py
[control:synthetic-fossil] ... -> FAIL: no dated RULE-YYYY-MM-DD id (template scaffolding)
[control:real-fossil]      ... -> FAIL: no dated RULE-YYYY-MM-DD id (template scaffolding)
[subject:live]             ... -> PASS: both readers agree on ['RULE-2026-08-18-A'] (valid=False, not asserted)
PASS: live tree proved read by name; both fossil controls correctly failed.
```

Mutation test (the check must be able to fail for the right reason): replacing
`_parse_decisions` with a nonempty placeholder -- Codex finding-14's exact shape --
flips the live case to FAIL via the readers-disagree branch. Control passes, mutant
killed.

Shown RED first: the initial version resolved `REPO` with `parents[3]` instead of
`parents[4]`, could not import the digest, and exited 3 (REFUSED) rather than
passing. The refusal path was therefore exercised before the pass path.
