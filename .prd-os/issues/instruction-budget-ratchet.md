---
id: instruction-budget-ratchet
title: Resurrect the dead instruction-budget commit gate as a ratchet in lefthook (sp-b417481b)
status: closed
priority: p3
parent_prd: plan:skillsui-gap-fill-2026-07-02
allowed_files:
  - q-system/.q-system/scripts/instruction-budget-audit.py
  - q-system/.q-system/instruction-budget-baseline.json
  - lefthook.yml
disallowed_files: []
required_checks:
  - python3 q-system/.q-system/scripts/instruction-budget-audit.py --ratchet
required_reviews: []
bypass_check: "python3 q-system/.q-system/scripts/instruction-budget-audit.py --ratchet"
---

# Resurrect the dead instruction-budget commit gate (sp-b417481b)

## Context

The instruction-budget-audit pre-commit hook sat dead in `.git/hooks/pre-commit.old`
(displaced by the gitleaks/lefthook chain), so CLAUDE.md/rules bloat was ungated at
commit time. Meanwhile the always-on total drifted to 514 against a 300-line target,
so rewiring it as an absolute gate would have frozen every commit.

## Fix

`--ratchet` mode added to `instruction-budget-audit.py`: absolute cap kept for
CLAUDE.md (52/200, passes), regression-only gate for the always-on total against
`instruction-budget-baseline.json` (baseline 514, auto-tightens on shrink, growth
exits 1). Wired as the `instruction-budget` job in lefthook.yml pre-commit.
Default (no-flag) behavior unchanged for manual audits. The 514->300 trim is
tracked as spillover sp-<trim> (open by design).

## Verification (reproducer-first)

- Reproducer: `.git/hooks/` contained no live hook running the audit; the audit
  itself exits 1 at 514/300, proving an absolute gate would block all commits.
- Bootstrap: no baseline -> creates at 514, exit 0.
- Negative self-test: baseline forced to 500 -> "grew 500 -> 514 (+14)", exit 1.
- Tighten: baseline forced to 600 -> rewritten to 514, exit 0.
- Default mode: still exits 1 (absolute report), unchanged.
- Real commit of this change runs the job live via lefthook pre-commit.

## Amendments

None.
