---
id: prd-lessons-hardening-2026-06-20
title: Lessons Hardening
status: archived
created_at: 2026-06-20T01:12:12Z
updated_at: 2026-06-20T01:24:35Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-lessons-hardening-2026-06-20-findings.jsonl
codex_reviewed_at: 2026-06-20T01:18:02Z
---

# Lessons Hardening

<!-- PROVENANCE: scoped from Goal 1 review of the H0 commit (609dd6e), a 22-agent
wiring/junk/conflict/deferred review. It confirmed H0 is functionally wired and tested,
but found one real integrity hole + a cluster of doc-sync gaps. The other 11 review
items were verified as honest no-ops/deferrals (deliberate parser divergence, accepted
provenance residual risk, nits) and are NOT in scope. -->

## Problem

The H0 cross-instance lessons feature (commit 609dd6e) is functionally wired and its four test suites pass, but the Goal 1 review surfaced concrete gaps:

1. **Integrity hole (major):** the push-guard's lessons compare is forward-only (`for rel, blob in inst.items()` in `kipi-push-upstream.sh`), so a committed `git rm q-system/lessons/x.md` (a DELETION) is never compared against the skeleton and reaches the subtree push silently. The PRD spec requires blocking add/edit/DELETE; deletion bypasses it.
2. **Self-conflict with an ENFORCED rule (minor):** `q-system/lessons/` is absent from `folder-structure.md`'s canonical tree, which itself forbids files outside the tree without founder approval. Commit 609dd6e created the dir without updating the rule.
3. **Discoverability gap (minor):** there is no findable instruction for how a founder ADDS a lesson (the v1 path is "hand-write a file"; nothing documents it).
4. **DX wiring gap (minor):** `lessons-index.py` is registered in `settings-template.json` (so it propagates to instances) but NOT in the skeleton's own `.claude/settings.json`, so a founder authoring lessons in the skeleton does not see the title index at SessionStart.

## Goals

- Close the deletion bypass so the push guard blocks add/edit/DELETE of lessons, and fails CLOSED when the skeleton state cannot be verified (fetch failure).
- Re-sync the docs/wiring so H0 stops self-conflicting with its own ENFORCED rules and is authorable + visible in the skeleton.

## Non-goals

- The 11 verified no-op/deferred items (parser de-duplication, source_instances provenance ledger, validator path-substring scope, multi-line YAML message, test depth, rmdir cleanup, the `kipi lesson` helper, the matcher='startup' house pattern). All confirmed honest deferrals by the Goal 1 verifier.
- Touching `memory-freshness-check.py`'s parallel skeleton-settings gap (noted but explicitly NOT bundled).
- Broadening any SessionStart matcher (must be done uniformly across all hooks, separately).

## Proposed approach

Two atomic issues:

1. **lessons-push-guard-deletion:** the existing guard already builds normalized `lessons/<tail>` blob dicts for HEAD (`inst`) and FETCH_HEAD (`skel`) -- layout-agnostic (handles skeleton `q-system/lessons/` vs instance `q-system/q-system/lessons/`), and already fails CLOSED when `skel is None` (fetch failure). It currently checks only the FORWARD direction (`inst` lessons whose blob differs from `skel` = add/modify). Add the REVERSE check: `for rel in skel: if rel not in inst: <fail: deletion of a skeleton lesson>`. This catches A/M/D using data the guard already computes, needs NO merge-base. (Merge-base was REJECTED by adversarial review: archive+rsync and `git subtree add --squash` instances share no history with the skeleton, so `git merge-base HEAD FETCH_HEAD` is empty for EVERY real instance and fail-closed-on-empty would refuse every legitimate push -- strictly worse than the deletion bug. `git diff --name-status` also cannot do the layout-agnostic path normalization the dict-compare does.) Add a `git rm` deletion case to `test-lessons-push-guard.sh` asserting non-zero exit + the skeleton-authored message; the existing clone-based instance setup is faithful enough for the reverse check (a deleted lesson is absent from `inst` but present in `skel` regardless of how the instance was built).
2. **lessons-doc-wiring-sync:** (a) add `q-system/lessons/` to `folder-structure.md`'s canonical tree (sibling of `canonical/`, contents README.md + `<lesson>.md`) and a Placement Rule line; (b) add an authoring instruction to `q-system/lessons/README.md` pointing at the seed lesson as a copy template; (c) wire the `lessons-index.py` SessionStart line into the skeleton's `.claude/settings.json` mirroring `settings-template.json` (advisory `2>/dev/null || true` form). A deterministic test greps all three for the required content.

## Risks and rollback

- Risk: an instance merely BEHIND on `kipi update` lacks a newly-added skeleton lesson, which the reverse check reads as a deletion and refuses the push. Accepted: this is the same fail-safe behind-instance behavior the existing FORWARD check already has for modifications; it never leaks (refuses, does not push), and the founder resolves it by running `kipi update` first -- the guard message says so. Merge-base was rejected (empty for every real instance; would block all pushes).
- Risk: doc edits drift from reality. Mitigation: the doc-wiring test greps for the required strings so the docs stay in sync.
- Blast radius: one shell guard rewrite + 3 doc/config edits + 1 new test. Back out = git revert.

## Open questions

Resolved (owner-delegated, autonomous): all four items are confirmed worth doing now by the Goal 1 verifier; the rest are confirmed no-ops. No open questions.

## Issues

<!--
After review and approval, prd_split materializes one issue spec per entry.
Required: id, title, finding_id, allowed_files, required_checks, bypass_check|bypass_exempt.
-->

```json
[
  {
    "id": "lessons-push-guard-deletion",
    "title": "Push guard must block committed lesson DELETION via a reverse skeleton-dict check (for rel in skel: if rel not in inst), layout-agnostic, no merge-base, with a git-rm deletion test",
    "finding_id": "finding-1",
    "allowed_files": ["kipi-push-upstream.sh", "q-system/.q-system/scripts/test/test-lessons-push-guard.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-lessons-push-guard.sh"
  },
  {
    "id": "lessons-doc-wiring-sync",
    "title": "Sync H0 docs/wiring: add q-system/lessons/ to folder-structure.md tree + Placement Rule, add authoring instruction to README, wire lessons-index.py into skeleton .claude/settings.json; a grep test keeps them in sync",
    "finding_id": "finding-2",
    "allowed_files": [".claude/rules/folder-structure.md", "q-system/lessons/README.md", ".claude/settings.json", "q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh"],
    "required_checks": ["bash q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh"],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-lessons-doc-wiring.sh"
  }
]
```
