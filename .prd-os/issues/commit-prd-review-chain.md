---
id: commit-prd-review-chain
title: Commit the spec and its source plan so the review chain is substantiable
status: open
priority: p1
parent_prd: prd-terminal-state-redrive-2026-08-01
allowed_files:
  - .prd-os/prds/prd-terminal-state-redrive-2026-08-01.md
  - .prd-os/findings/prd-terminal-state-redrive-2026-08-01-findings.jsonl
  - q-system/output/plans/terminal-state-redrive-2026-08-01.md
disallowed_files: []
required_checks:
  - git ls-files --error-unmatch .prd-os/prds/prd-terminal-state-redrive-2026-08-01.md q-system/output/plans/terminal-state-redrive-2026-08-01.md
required_reviews: []
bypass_exempt: "Committing tracked files has no bypass surface: the required_check IS the invariant (git refuses to match an untracked path), and there is no code path that could satisfy it while leaving the spec untracked."
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-terminal-state-redrive-2026-08-01 finding=finding-16 at=2026-08-01T19:41:22Z -->

# Commit the spec and its source plan so the review chain is substantiable

## Context

Parent PRD: `.prd-os/prds/prd-terminal-state-redrive-2026-08-01.md`

## Acceptance

Both the PRD and its source plan are tracked in git. The frontmatter reviewers field names the review that ran. NOTE the honest limit finding-16 raises and this issue does NOT close: a codex-review stamp is adversarial analysis, it is not proof of independent AUTHORSHIP, and this PRD was drafted by Claude. That limitation is recorded in Resolved decisions and stays true after this issue closes. q-system/output/plans/ is excluded from kipi update sync, so the plan stays instance-local by design.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [ ] Commit the spec and its source plan so the review chain is substantiable
