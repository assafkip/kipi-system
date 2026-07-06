---
id: prd-reorg-stale-ref-remediation-2026-07-06
title: Reorg Stale Ref Remediation
status: approved
created_at: 2026-07-06T21:53:40Z
updated_at: 2026-07-06T22:35:36Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-reorg-stale-ref-remediation-2026-07-06-findings.jsonl
codex_reviewed_at: 2026-07-06T22:08:03Z
---

# Reorg Stale Ref Remediation

<!-- prompt-only-enforcement-skip: design spec. This PRD's enforcement is
executable and named — scripts/reorg-stale-ref-audit.py (exit-code gate), a
rewriter unit test, and `kipi check`. The prose discusses guards/blocks/gates
descriptively, which trips the proximity guard as a false positive. -->

## Problem

The fleet persona-reorg (phases 1-5, 2026-07-06; RULE-2026-07-06-A..F) moved ~28
projects into 5 persona buckets. `scripts/reorg-stale-ref-audit.py` (the
reproducer, exits 1 today) measures the fallout:

- **41 stale references in 17 executable/config files** (the gating set — code
  that breaks at runtime). Concrete failures:
  - `cole-gtm/.mcp.json:27-28` — an MCP server command points at
    `4_points_consulting/.../osint-infra-mcp/` (moved to consulting). The MCP
    will not launch.
  - `kipi-system/lefthook.yml:78` — a git hook runs
    `$HOME/projects/cheapcheck/q-design/sync-from-kipi.sh` (moved to micro-saas).
  - `intel/projects/kipi-investigations/run-analyze.sh:10` + `serve-debug.sh:15`
    — `ROOT="$HOME/projects/kipi-investigations"` self-ref, dead path.
  - `runreceipts/.artdir-tools/dogfood.mjs` + `cdp-shot.mjs` — absolute self-refs
    in `.mjs` files.
  - `reddit-build-radar/launch/products.json` — 7 product repo paths, all moved.
  - `~/.claude/plugins/installed_plugins.json` — 13x `ASK_AI_consultant`
    projectPath (renamed to consulting); orphaned plugin-install records.
- **56 more in prose/docs/regenerating state** (informational; do not gate).

Root cause is `scripts/persona-reorg.py`'s self-ref rewriter, three coverage gaps:

1. `rewrite_selfrefs_in` replaces only the absolute `/Users/...` form (`old_abs`);
   it never matches `~/projects/X`, `$HOME/projects/X`, or `$PROJECTS/X`.
2. `SELFREF_EXTS` (line ~542) omits `.mjs`/`.cjs`, so those files are skipped.
3. There is no cross-project pass: the tool only rewrites a moved dir's refs to
   its OWN old path, never a reference FROM another project TO a moved sibling
   (reddit-build-radar -> product repos; cole-gtm -> 4_points MCP).

Left unfixed, gap 1+2 recur on the final persona (ktlyst-hub, Tier-2).

## Goals

- The reproducer `scripts/reorg-stale-ref-audit.py` exits 0 (zero gating refs).
- `persona-reorg.py`'s rewriter covers all four path forms + `.mjs`/`.cjs`,
  proven by a unit test with a fixture holding all four forms and a `.mjs` file.
- A cross-project remediation mode fixes A->moved-B references deterministically.
- `kipi check` stays at baseline (FAIL=2). No new registry/launchd breakage.
- ktlyst-hub inherits the hardened tool (its future move needs no hand-patching).

## Non-goals

- Rewriting dated point-in-time records (podcast `distribution/` logs), session
  cache, rollback manifests, or `.bak` files — those are correct as history.
- The pre-existing wrong-user ref (`/Users/assafkip/...` in `4_points/.codex/`)
  — predates the reorg; out of scope, captured separately if real.
- Fixing prose docs is in scope but NON-gating (a stale `cd` line in an operator
  guide is not a runtime break).
- ktlyst-hub's actual migration (separate, founder taxonomy decision pending).

## Proposed approach

Three issues, reproducer-gated:

1. **Harden the rewriter.** In `persona-reorg.py`: add `.mjs`/`.cjs` to
   `SELFREF_EXTS`; generalize `rewrite_selfrefs_in` to rewrite all four
   path-prefix forms (absolute, `~`, `$HOME`, `$PROJECTS`) in one pass, mapping
   each old form to the matching new form. Unit test with a fixture file
   containing all four + a `.mjs`; assert every form is rewritten and a negative
   self-test (old path absent post-rewrite).
2. **Cross-project remediation pass.** A new mode that, given the full old->new
   map, rewrites references to moved siblings across the fleet's live code/config
   (the gating set), `.bak`-backed and dry-run-first, skipping the noise buckets
   the audit already defines. Repoint `installed_plugins.json` projectPaths.
3. **Run the sweep + verify.** Execute passes 1+2 across the 5 migrated buckets
   and fleet config; re-run the audit to 0 gating; fix the prose docs
   (non-gating) in the same pass; `kipi check` at baseline.

## Alternatives considered

- **One-off `sed` sweep of the 17 files by hand** — Rejected: fixes symptoms,
  not the tool. gap 1+2 would recur verbatim on ktlyst-hub; the founder's
  standing preference is a deterministic tool fix over a hand edit. A hand sweep
  also has no reproducer to prove completeness.
- **Re-run `persona-reorg.py --apply` per persona after patching** — Rejected:
  the `MIGRATED` set makes `run_apply` exit 3 (executable code in the script),
  and re-moving already-moved dirs is pointless. The dirs are in place; only the
  missed rewrites remain. A dedicated remediation mode over in-place dirs fits.
- **Delete the stale files / regenerate** — Rejected: they hold real content
  (working launchers, self-ref scripts); regeneration is not free and loses git
  history.

## Scenarios

- **Rewriter hardening.** A dev moves a repo with `persona-reorg.py`; a `.mjs`
  build script inside it references `~/projects/<old>`; the hardened rewriter
  matches the `~` form and the `.mjs` extension and repoints it; the unit test's
  negative self-test confirms no old-form ref survives.
- **Cross-project remediation.** `reddit-build-radar/launch/products.json` lists
  `~/projects/cheapcheck`; the cross-project pass maps `cheapcheck ->
  micro-saas/projects/cheapcheck`, `.bak`s the file, rewrites the ref; the audit
  drops that gating hit to 0.
- **Acceptance.** Operator runs `scripts/reorg-stale-ref-audit.py`; exit 0;
  `kipi check` FAIL=2; the launcher, MCP, git hook, and self-ref scripts resolve.

## Resolved decisions

- **Reproducer is the gate.** Decided: `reorg-stale-ref-audit.py` exit 0 defines
  done. Rationale: deterministic, re-runnable, prevents "looks fixed" claims.
- **Gating vs informational split.** Decided: executable/config files gate;
  prose/regenerating-state do not. Rationale: a stale `cd` in a doc is not a
  runtime break; a stale MCP command is.

## Risks and rollback

- **Blast radius:** rewrites touch live code/config across 5 buckets + fleet
  config. Mitigation: every rewrite `.bak`-backed (same mechanism as the reorg),
  dry-run-first, and gated by the audit + `kipi check`.
- **Over-rewrite:** a greedy regex could corrupt a legitimately-old path in
  history. Mitigation: reuse the audit's noise-bucket skip list; operate only on
  the gating set for code/config.
- **Rollback:** restore from `.bak` files (per-file) or `git checkout` the
  affected repos. No dir moves in this PRD, so rollback is content-only.

## Open questions

- The 49 `.persona-reorg.bak` + 5 reorg manifests: clear now (reorg final) or
  hold (rollback still wanted)? — founder call, not blocking this PRD.
- Fix all 56 informational prose refs, or only the operator-facing docs
  (kipi-investigations `docs/`)? Default: fix operator docs + `current-state.md`
  fan-out, leave dated records.

<!--
## Persona Review (optional, fill in before /prd-review)

Phase 0 of the prd-os planning-personas experiment (PRD prd-planning-personas-2026-05-13).
For non-trivial PRDs, answer the three Skeptic questions below before invoking /prd-review.
Brief answers are fine. The goal is to force one round of adversarial thinking before Codex.

### Skeptic

Q1: What is the strongest argument against doing this?
A1:

Q2: What is the smallest experiment that would disprove the thesis?
A2:

Q3: What is the cheapest non-build alternative?
A3:

When done with these questions, uncomment this section and move it to live just before `## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {
    "id": "harden-audit-gate",
    "finding_id": "finding-6",
    "title": "Harden reorg-stale-ref-audit.py: single-source map, new-path existence, ${HOME} form, wider gating set, docstring (consolidates findings 2/4/5/10)",
    "allowed_files": ["scripts/reorg-stale-ref-audit.py", "scripts/persona-reorg.py"],
    "required_checks": ["python3 scripts/reorg-stale-ref-audit.py"],
    "bypass_check": "python3 scripts/reorg-stale-ref-audit.py"
  },
  {
    "id": "harden-rewriter-and-bak",
    "finding_id": "finding-7",
    "title": "rewrite_selfrefs_in covers all four path forms + .mjs/.cjs; _bak gains a distinct remediation backup namespace",
    "allowed_files": ["scripts/persona-reorg.py", "scripts/test_persona_reorg.py"],
    "required_checks": ["python3 scripts/test_persona_reorg.py"],
    "bypass_check": "python3 scripts/reorg-stale-ref-audit.py"
  },
  {
    "id": "cross-project-remediation-mode",
    "finding_id": "finding-8",
    "title": "New --remediate mode: cross-project sweep over already-moved dirs, dry-first, .remediation.bak-backed, with a fixture unit test",
    "allowed_files": ["scripts/persona-reorg.py", "scripts/test_persona_reorg.py"],
    "required_checks": ["python3 scripts/test_persona_reorg.py"],
    "bypass_check": "python3 scripts/reorg-stale-ref-audit.py"
  },
  {
    "id": "remediate-and-fix-prose",
    "finding_id": "finding-9",
    "title": "Run the remediation to 0 gating refs and fix operator-facing prose (kipi-investigations docs + current-state fan-out); leave dated records",
    "allowed_files": ["scripts/reorg-stale-ref-audit.py", "**/current-state.md", "**/kipi-investigations/docs/*.md"],
    "required_checks": ["python3 scripts/reorg-stale-ref-audit.py"],
    "bypass_check": "python3 scripts/reorg-stale-ref-audit.py"
  }
]
```
