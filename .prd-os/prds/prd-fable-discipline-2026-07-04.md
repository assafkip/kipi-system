---
id: prd-fable-discipline-2026-07-04
title: Fable Discipline
status: archived
created_at: 2026-07-04T01:37:52Z
updated_at: 2026-07-04T02:42:40Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-fable-discipline-2026-07-04-findings.jsonl
codex_reviewed_at: 2026-07-04T01:39:59Z
---

# Fable Discipline: merge fable-discipline into prd-os as its execution-discipline layer

Content source: founder brief, 2026-07-03. Sections below transcribe that brief;
nothing here is Claude-drafted positioning.

## Problem

Two discipline layers exist today and they overlap:

1. **prd-os** (`plugins/prd-os/`): the gated work-item OS. PRD -> review ->
   split -> issue execution -> receipts -> closeout. Deterministic core is
   `plugins/prd-os/scripts/prd_runner.py` with `.prd-os/gates.jsonl` (gates
   only grow) and `.prd-os/spillover.jsonl` (no orphan findings). Paired
   kipi-dsse issue flow: issue-start/approve/verify/review/closeout.
2. **fable-discipline** (kipi-core plugin): the per-edit coding procedure
   skill. Recon before edit, verify-against-a-copy with a negative self-test,
   single-writer chokepoints, scar-anchored why-comments. Enforced slice:
   fable-discipline-lint hook (test isolation). Auto-invoked via
   `.claude/rules/fable-discipline-auto-invoke.md`. Also published standalone
   at github.com/assafkip/fable-discipline (public, MIT).

They are two systems saying one thing: work has a procedure and the procedure
has receipts. Maintaining them as siblings means duplicated cross-references,
drift risk, and two load paths to prove.

A second, sharper problem comes from reviewing Leonxlnx/taste-skill (MIT), a
prompt-only anti-slop skill whose production lesson transfers directly: rules
phrased as "use sparingly" were ignored by the model in production; only
binary phrasing (zero-or-fail) and mechanical counts held. That matches this
repo's own scars (autonomy-contract phrase patching, hook blind spots).

## Goals

- One discipline system: fable-discipline becomes the execution-discipline
  layer INSIDE prd-os, loaded at issue-start (quick-plan fast path for non-PRD
  work keeps working).
- Binary phrasing: every actually-binary rule in the merged skill prose is
  zero-or-fail, and every regex/count-checkable rewrite gets a lint detector.
- Mechanical/judgment split: every mechanical checklist item is promoted into
  the lint hook and removed from the checklist; the remaining checklist is
  judgment-only; detector coverage enumerated in the hook header.
- Deliverable-count lock: issue spec schema gains a deliverables count locked
  at issue-start; closeout refuses to close on receipt/count mismatch.
- Skill versioning: current fable-discipline SKILL.md frozen as -v1;
  CHANGELOG.md added to the prd-os plugin; this merge is the first entry.
- Override-in-place: every hard ban states its legitimate override condition
  and skip marker in the same paragraph; one marker per hook, no stacking.

## Non-goals

- No scope expansion beyond the six work items. Adjacent finds go to
  spillover (`prd_runner.py spillover add`), never just mentioned.
- No archiving or freezing of the public repo: founder decision 2026-07-03 is
  that assafkip/fable-discipline MIRRORS the merged version going forward
  (each behavior change gets a de-kipi'd export). This PRD does not re-open
  that decision.
- No rewrite of the prd-os PRD flow itself (start/review/approve/split stay
  as-is); changes are confined to the discipline layer, issue schema, and
  closeout cross-check.

## Proposed approach

Six work items, one issue per item (or grouped where scope-safe):

1. **MERGE.** Fold fable-discipline into prd-os. Skill content becomes
   prd-os's execution-discipline layer, loaded at issue-start (and by the
   quick-plan fast path for non-PRD work; the fast path must keep working).
   fable-discipline-lint moves into the prd-os plugin's hooks.json. Update
   `.claude/rules/fable-discipline-auto-invoke.md` and every rule that
   cross-references fable-discipline (rca-mode.md, skill-hook-pairing.md,
   wiring-check.md, no-orphan-findings.md, CLAUDE.md). Public repo mirrors
   the merged version (founder decision, see Non-goals).

   **Public mirror mechanism (fix for finding-2):** a deterministic export
   script, `plugins/prd-os/scripts/export-fable-mirror.sh`, produces the
   de-kipi'd public tree (strips kipi-only paths/wiring, keeps the generic
   skill + lint + tests) and has a `--check` mode that diffs the export
   output against a local clone of assafkip/fable-discipline and exits
   non-zero on divergence. Owner: assafkipnis (pushes to the public repo run
   under the founder's own gh auth; the script never pushes). Verification:
   `--check` is a required_check on the merge issue and re-runs at every
   CHANGELOG entry to the discipline layer (item 5 is the trigger).
2. **BINARY PHRASING AUDIT.** Grep the merged skill + prd-os skill prose for
   graduated verbs ("prefer", "avoid", "sparingly", "minimize", "keep
   minimal", "usually", "generally") applied to rules that are actually
   binary. Rewrite each to zero-or-fail. Any rewritten rule that is
   regex/count-checkable gets a lint detector, not just new prose.
3. **MECHANICAL/JUDGMENT SPLIT.** Walk every checklist item in the merged
   skill. Tag each: mechanical (count, regex, file inspection) or judgment.
   Every mechanical item is PROMOTED into the lint hook and REMOVED from the
   checklist. The checklist that remains is judgment-only. Enumerate detector
   coverage explicitly in the hook header (hook-blind-spots scar).
4. **DELIVERABLE-COUNT LOCK.** Add a deliverables count to the issue spec
   schema (locked at issue-start, like allowed_files). Closeout cross-checks
   receipts against the count and refuses to close on mismatch.
   Deterministic, in prd_runner.py / the kipi-dsse scripts, not prose.

   **Compatibility behavior (fix for finding-3):** the field is additive and
   opt-in by generation. Specs WITHOUT `deliverables_count` (every
   pre-existing spec) close under the current rules — the cross-check is
   skipped entirely, no warning, no failure. Specs WITH the field get the
   hard mismatch refusal at closeout. `prd_split.py` writes the field on
   every spec it generates from this PRD onward, so all new work gets the
   lock and no old spec is retro-broken. A malformed value (non-integer,
   < 1) on a spec that has the field is rejected at issue-start, not at
   closeout.
5. **SKILL VERSIONING.** Before the merged skill ships: freeze the current
   fable-discipline SKILL.md as a preserved -v1 copy and record this merge
   in the prd-os plugin's CHANGELOG.md with rationale. (Recon 2026-07-04:
   `plugins/prd-os/CHANGELOG.md` already exists — the item adds the entry,
   not the file.) Every future behavior change to the discipline layer gets
   a CHANGELOG entry. Fleet instances get the new version via kipi update.
6. **OVERRIDE-IN-PLACE.** Every hard ban in the merged skill states its
   legitimate override condition and its skip marker in the same paragraph as
   the ban. No ban without a documented escape hatch. One marker per hook, no
   stacking (per skill-hook-pairing.md).

Constraints (non-negotiable):

- Enforcement is code. A prompt or skill alone enforces nothing; every
  deterministic rule pairs with a hook/script (skill-hook-pairing.md).
- Load-path proof. Plugins run from the marketplace clone, NOT this repo's
  plugins/ dir. Prove the running system loads what was edited
  (wiring-check.md scar 2026-06-20).
- settings-template-sync-check stays green: any hook wiring change lands in
  settings-template.json too, or the fleet ships a dead switch.
- `python3 plugins/prd-os/scripts/prd_runner.py gates run` exits 0 at the
  end. Out-of-scope findings go to spillover, never just mentioned.
- Verification loops: for every deterministic change, write the failing
  reproducer first, show it red, then green.
- `kipi update --dry` after the change set to confirm clean fleet
  propagation.

## Risks and rollback

- **Load-path miss (highest-probability failure):** editing this repo's
  `plugins/` while the runtime loads the marketplace clone leaves the merge
  inert. Mitigation: load-path proof is a per-issue required check, not an
  end-of-run afterthought.
- **Dead switch shipped to fleet:** hook moved into prd-os hooks.json but
  settings-template.json not updated (or vice versa). Mitigation:
  settings-template-sync-check must be green per issue.
- **Fast-path regression:** quick-plan (non-PRD) work loses its discipline
  layer when the skill moves. Mitigation: explicit acceptance criterion that
  the quick-plan path still loads the merged skill.
- **Public mirror drift:** the mirror decision adds a recurring de-kipi'd
  export step; if skipped, the public repo silently diverges. Mitigation:
  CHANGELOG entry (item 5) is the trigger for the export; recorded as part of
  the item-1 wiring.
- **Rollback:** the -v1 frozen SKILL.md (item 5) plus git revert of the merge
  commits restores the sibling arrangement. Hooks are removable by reverting
  hooks.json + settings-template.json in the same commit. No data migration;
  issue specs gain an additive field (deliverables count), old specs stay
  readable.

## Open questions

- None. The single open decision (fate of the public repo) was resolved by
  the founder 2026-07-03: mirror the merged version.

## Issues

<!--
After review and approval, populate the fenced JSON block below with one
entry per atomic issue. `prd_split.py` reads this block verbatim and writes
one issue spec per entry.

Required keys per entry:
  - id (kebab-case, unique across the repo)
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The runner's
    stop-gate checks that three receipts are marked (verified, reviewed,
    findings_triaged). Those receipts are meaningless unless the spec
    documents what must be verified, so an empty list is rejected.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

IDs must match the repo's issue naming convention and must not collide with
existing issue specs.
-->

Execution order: `discipline-skill-versioning` first (the -v1 freeze exists
before the merge ships — deterministic backstop: the merge issue's
`diff -q` required_check fails if the frozen copy is absent or stale), then
`fable-merge-into-prd-os`, then the three skill-refinement issues, then
`dsse-deliverable-count-lock`. Overlapping `plugins/prd-os/skills/**`
allowed_files across issues carry no concurrent-edit risk: the executable
blocker is `plugins/kipi-dsse/scripts/concurrency.py`, which rejects starting
a second issue while one is active.

```json
[
  {
    "id": "discipline-skill-versioning",
    "bypass_exempt": "Pure preservation + documentation (frozen -v1 copy, CHANGELOG entry). Introduces no gate, skip, or no-verify bypass.",
    "finding_id": "finding-4",
    "title": "Freeze fable-discipline SKILL.md as -v1; record merge in prd-os CHANGELOG",
    "priority": "p0",
    "allowed_files": [
      "plugins/prd-os/CHANGELOG.md",
      "plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md"
    ],
    "required_checks": [
      "test -f plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md",
      "diff -q plugins/kipi-core/skills/fable-discipline/SKILL.md plugins/prd-os/skills/prd-os/references/fable-discipline-v1.md",
      "grep -q 'fable-discipline' plugins/prd-os/CHANGELOG.md"
    ],
    "acceptance": "Current SKILL.md preserved verbatim as fable-discipline-v1.md inside the prd-os plugin; CHANGELOG.md Unreleased section records the merge with rationale (one discipline system; taste-skill binary-phrasing lesson). No behavior change in this issue."
  },
  {
    "id": "fable-merge-into-prd-os",
    "bypass_check": "bash -c 'grep -q fable-discipline-lint plugins/prd-os/hooks/hooks.json && ! grep -q fable-discipline-lint plugins/kipi-core/hooks/hooks.json'",
    "finding_id": "finding-2",
    "title": "Fold fable-discipline into prd-os as its execution-discipline layer",
    "priority": "p0",
    "allowed_files": [
      "plugins/prd-os/skills/**",
      "plugins/prd-os/hooks/hooks.json",
      "plugins/prd-os/scripts/export-fable-mirror.sh",
      "plugins/prd-os/tests/**",
      "plugins/kipi-core/skills/fable-discipline/**",
      "plugins/kipi-core/hooks/hooks.json",
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-dsse/commands/issue-start.md",
      ".claude/rules/fable-discipline-auto-invoke.md",
      ".claude/rules/rca-mode.md",
      ".claude/rules/skill-hook-pairing.md",
      ".claude/rules/wiring-check.md",
      ".claude/rules/no-orphan-findings.md",
      ".claude/rules/quick-plan.md",
      "CLAUDE.md",
      "settings-template.json"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests",
      "bash plugins/prd-os/scripts/export-fable-mirror.sh --check",
      "python3 plugins/prd-os/scripts/prd_runner.py gates run",
      "bash -c '! grep -rn \"kipi-core/skills/fable-discipline\" .claude/rules/ CLAUDE.md'"
    ],
    "acceptance": "Skill content lives in the prd-os plugin, loaded at issue-start; quick-plan fast path still loads it for non-PRD work (load-path proof required: verify the marketplace clone serves the merged copy, not this repo's plugins/). fable-discipline-lint wired in prd-os hooks.json, removed from kipi-core hooks.json, settings-template-sync-check green. All cross-referencing rules updated; no rule refers to fable-discipline and prd-os as separate peers. export-fable-mirror.sh exists with --check mode; founder pushes the mirror manually."
  },
  {
    "id": "fable-binary-phrasing-audit",
    "bypass_check": "pytest -q plugins/prd-os/tests",
    "finding_id": "finding-5",
    "title": "Rewrite graduated phrasing to zero-or-fail in merged skill + prd-os prose",
    "allowed_files": [
      "plugins/prd-os/skills/**",
      "plugins/prd-os/hooks/**",
      "plugins/prd-os/tests/**"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests",
      "bash plugins/prd-os/scripts/export-fable-mirror.sh --check"
    ],
    "acceptance": "Grep for graduated verbs (prefer/avoid/sparingly/minimize/keep minimal/usually/generally) applied to actually-binary rules; each rewritten to zero-or-fail. Every regex/count-checkable rewrite gains a lint detector with a red-then-green reproducer. Judgment rules keep graduated phrasing; the audit log in the issue notes which hits were left as judgment and why."
  },
  {
    "id": "fable-mechanical-judgment-split",
    "bypass_check": "pytest -q plugins/prd-os/tests",
    "finding_id": "finding-6",
    "title": "Promote every mechanical checklist item into the lint hook; checklist becomes judgment-only",
    "allowed_files": [
      "plugins/prd-os/skills/**",
      "plugins/prd-os/hooks/**",
      "plugins/prd-os/tests/**"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests",
      "bash plugins/prd-os/scripts/export-fable-mirror.sh --check"
    ],
    "acceptance": "Every checklist item tagged mechanical or judgment. Mechanical items exist as lint detectors and are absent from the checklist. Hook header enumerates detector coverage explicitly, including what it does NOT detect (hook-blind-spots scar)."
  },
  {
    "id": "fable-override-in-place",
    "bypass_check": "pytest -q plugins/prd-os/tests",
    "finding_id": "finding-7",
    "title": "Every hard ban states its override condition and skip marker in the same paragraph",
    "allowed_files": [
      "plugins/prd-os/skills/**",
      "plugins/prd-os/tests/**"
    ],
    "required_checks": [
      "pytest -q plugins/prd-os/tests",
      "bash plugins/prd-os/scripts/export-fable-mirror.sh --check"
    ],
    "acceptance": "No ban without a documented escape hatch in the same paragraph. One marker per hook, no stacking (skill-hook-pairing.md). A test walks the skill text and fails on any ban paragraph lacking an override clause + marker."
  },
  {
    "id": "dsse-deliverable-count-lock",
    "bypass_check": "pytest -q plugins/kipi-dsse",
    "finding_id": "finding-3",
    "title": "deliverables_count in issue spec schema; closeout refuses on receipt mismatch",
    "allowed_files": [
      "plugins/kipi-dsse/scripts/**",
      "plugins/kipi-dsse/hooks/**",
      "plugins/kipi-dsse/commands/**",
      "plugins/prd-os/scripts/prd_split.py",
      "plugins/prd-os/templates/issue.md",
      "plugins/prd-os/tests/**"
    ],
    "required_checks": [
      "pytest -q plugins/kipi-dsse",
      "pytest -q plugins/prd-os/tests"
    ],
    "acceptance": "deliverables_count locked at issue-start like allowed_files; closeout cross-checks receipts against the count and refuses on mismatch. Compat: specs without the field close under current rules (check skipped); prd_split.py writes the field on all new specs; malformed values rejected at issue-start. Red-then-green reproducer for the refusal path."
  }
]
```
