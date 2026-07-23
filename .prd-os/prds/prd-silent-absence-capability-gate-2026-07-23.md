---
id: prd-silent-absence-capability-gate-2026-07-23
title: Silent Absence Capability Gate
status: in-review
created_at: 2026-07-23T20:46:57Z
updated_at: 2026-07-23T20:52:34Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-silent-absence-capability-gate-2026-07-23-findings.jsonl
codex_reviewed_at: 2026-07-23T20:52:34Z
---

# Silent Absence Capability Gate

## Problem

Nothing declares what is supposed to exist in this repo, so nothing can detect
what is missing. Four findings, all reproduced 2026-07-23 in this session:

- **F1 (sp-2bc86be1):** 38 test artifacts exist in `q-system/.q-system/scripts`
  (15 `test_*.py`, 2 `test-*.py`, 21 `test-*.sh`); CI (`.github/workflows/validate.yml`)
  hardcodes 4; `validate-separation.py` runs 0; pytest collection crashes on a
  module-level `sys.exit(0)` in `test_launchd_health_check.py`. 34/38 (89.5%)
  never execute anywhere.
- **F2 (sp-72b60bff):** `stat-verify.py` is 802 lines, has zero references in
  `.claude/settings.json`, and its required `stat-registry.json` exists in 1/24
  instances (KTLYST_strategy). Its own suite passes; the engine is inert and
  nothing flags that.
- **F3 (sp-155afe5b):** `test_autocapture_wiring.py` reads the skeleton-only
  `settings-template.json`, yet propagates via `kipi update` to all 24 instances
  and crashes `FileNotFoundError` in 23. Nothing marks an artifact skeleton-only.
- **F4+A (sp-7a06b0f2):** `token-guard.py` advances `last_write_time` only on
  Edit/Write (`token-guard.py:188-192`), so a read-only audit trips
  `check_time_stall` (`:317-325`), which re-fires on EVERY subsequent call —
  demonstrated live this session (9+ warns in a row). `check_exact_retry`
  (`:219-228`) has no read-only observation exemption, so repeated identical
  screenshots (the only way to verify a LinkedIn compose overlay) get blocked
  (cole-gtm sp-ff7611cd; file is byte-identical skeleton↔instance, skeleton-owned).

Root cause is shared: every finding is a silent absence, and silent absences are
invisible to exit codes. Same disease traced end-to-end in cole-gtm (ledger
claiming 27 scheduled posts that exist nowhere). Nothing diffs declared against
actual.

Re-measured, not a goal here: `prd_runner.py gates run` = 280.77s wall, rc=1
(22 pre-existing open spillover items) — slow, not hung (sp-ff44a6af).

## Goals

- One manifest (`capability-manifest.json`) declaring: expected test artifacts,
  required data files (with instance scope), skeleton-only artifacts, and
  declared-inert scripts (present-but-unwired, each with a reason).
- One gate script that discovers test artifacts by the three naming conventions,
  runs all three types as subprocesses (not pytest), and fails in BOTH
  directions: declared-but-missing AND present-but-undeclared.
- Two call sites: `validate.yml` (replacing the 4-file hardcoded loop) and
  `validate-separation.py` (so `kipi check` enforces it fleet-side).
- `token-guard.py`: read-only observation exemption in `check_exact_retry`;
  rate-limit on `check_time_stall` re-fire.
- Negative proof BEFORE propagation: the gate catches at least one of F1-F4 on
  real repo state.
- Fleet propagation with deterministic per-instance verification: the gate runs
  in every registered instance; result per instance is green or loudly red.

## Non-goals

- Making `gates run` exit 0 globally (22 pre-existing open spillover items stay open).
- Wiring `stat-verify.py` into hooks — which events it fires on is a founder
  product decision (sp-72b60bff). This PRD makes its inertness DECLARED, not silent.
- Promoting cole-gtm receipt rules to the skeleton (explicit founder decision, per brief).
- Fixing every failing test among the 34 never-run ones: quick fixes yes;
  otherwise quarantine-with-reason in the manifest + spillover capture (loud, not silent).
- `gates run` performance (sp-ff44a6af).

## Proposed approach

Founder-authored design (from the task brief), refined where the 3-set version
had a detection hole:

1. **`capability-manifest.json`** lives in the synced tree
   (`q-system/.q-system/capability-manifest.json`) — one canonical skeleton copy,
   fleet-homogeneous via `kipi update`. Sets:
   - `expected_tests`: every test artifact, with `runner` (python3/bash),
     optional `timeout_s`, optional `quarantined: "<reason + spillover-id>"`.
   - `required_data`: path + `scope` (`"skeleton"` | `"all"` | explicit instance
     list). v1: `stat-registry.json` scoped to `["KTLYST_strategy"]` (the only
     place it exists; widening is the founder's call).
   - `skeleton_only`: artifacts that must not run in instances (v1:
     `test_autocapture_wiring.py`, and any test reading `settings-template.json`
     or `instance-registry.json`).
   - `declared_inert`: executable scripts deliberately not wired anywhere, each
     with reason + spillover ref (v1: `stat-verify.py` → sp-72b60bff). This is
     the F2 detector the 3-set design lacked: an executable script with zero
     references across wiring surfaces (`.claude/settings.json`,
     `plugins/*/hooks.json`, `validate-separation.py`, `.github/workflows/*.yml`)
     and not in `declared_inert` → RED.
   - Instance-local additions: optional overlay `capability-manifest.local.json`
     at instance REPO ROOT (not in synced q-system/, per RULE-2026-06-30-A);
     gate merges skeleton manifest + overlay.
2. **Gate script** `q-system/.q-system/scripts/capability-gate.py`:
   - Discovers `test_*.py`, `test-*.py`, `test-*.sh` under
     `q-system/.q-system/scripts` (rglob) + declared extra paths
     (e.g. `q-system/.q-system/token-guard.py` tests).
   - Diffs discovered vs declared, fails BOTH directions.
   - Runs each non-quarantined, in-scope artifact as a subprocess with timeout;
     rc!=0 → RED with the artifact name and captured tail.
   - Mode detect: skeleton iff repo root basename + `instance-registry.json`
     self-reference match (same trick as `instance-automation-guard`). Instance
     mode skips `skeleton_only`, applies `required_data` scope.
   - Wiring check for the F2 class as described above.
   - Output: deterministic summary (counts per set, per-direction diffs,
     quarantines WITH reasons — no silent caps), exit 0/1.
3. **Call sites:** `validate.yml` step runs `python3 q-system/.q-system/scripts/capability-gate.py`;
   `validate-separation.py` gains a gate section shelling the same script
   (single implementation, two callers).
4. **`token-guard.py`:** `OBSERVATION_EXEMPT` matcher (screenshot/read_page/
   get_page_text/browser_snapshot tool shapes) consulted by `check_exact_retry`
   only — volume/other counters unaffected; `check_time_stall` re-fires at most
   once per `STALL_TIME_SECONDS`. Paired tests added to `expected_tests`.
5. **Fleet verify:** `fleet-capability-verify.py` (skeleton repo root, not
   synced) iterates `instance-registry.json`, runs the gate in each instance,
   prints per-instance rc table, exits non-zero if any instance missing the
   gate/manifest or red without a declared reason.

## Alternatives considered

- **Fix `sys.exit(0)` + conftest, let pytest be the runner** — Rejected: pytest
  cannot discover 21 `.sh` + 2 hyphen-py artifacts; declaration (F3) stays
  unsolved; explicitly forbidden by the brief as a done-claim (converts loud
  failure to quiet one).
- **rsync-exclude skeleton-only files in `kipi-update.sh`** — Rejected as the
  primary fix: stops future shipping but leaves stale copies in instances
  (exclude without `--delete-excluded` never removes), and detects nothing for
  F1/F2. May complement later (open question).
- **Repurpose `run-step-audit.py`** — Rejected: built for run-log step auditing,
  different schema; pointing it at artifact sets means a second bespoke format.
  The gate borrows its declared-vs-actual philosophy, not its code.
- **CI-only gate (skip `kipi check` site)** — Rejected: instances do not run this
  repo's CI; 24 instances would stay dark. Two call sites are load-bearing.

## Scenarios

- **New test, forgotten declaration.** Dev adds `test_foo.py`; gate RED
  "present-but-undeclared: test_foo.py — add to expected_tests" in CI and in
  `kipi check`. One-line fix named in the message.
- **F3 recurrence attempt.** A new skeleton-only test lands undeclared; skeleton
  gate RED before any `kipi update` can ship it. Declared correctly, instance
  runs skip it by name.
- **Vanished artifact.** A declared test is deleted in a refactor; gate RED
  "declared-but-missing".
- **F2 recurrence attempt.** A new 500-line engine lands with zero wiring refs
  and no `declared_inert` entry; gate RED "executable script unreferenced and
  not declared inert".
- **Instance run.** `kipi check` in consulting: skeleton-only skipped,
  `stat-registry.json` not demanded (out of scope list), remaining tests run.

## Resolved decisions

- **Runner = subprocess per artifact, not pytest.** Rationale: honors the
  standalone-script style these tests were written in; immune to collection
  landmines; covers all three conventions uniformly.
- **Undeclared artifact fails the gate.** Rationale: the declaration IS the
  contract; one line of friction at authoring time is the feature.
- **Manifest in synced tree, overlay at instance repo root.** Rationale:
  fleet-homogeneity for the canonical set; RULE-2026-06-30-A for instance-local.
- **stat-verify stays unwired in v1, declared inert.** Rationale: hook events
  for it are a product decision; the gate's job is making inertness loud.

## Risks and rollback

- Blast radius: additive files (gate, manifest, fleet-verify) + 2 small diffs
  (validate.yml step, validate-separation.py section) + token-guard.py edits.
  Rollback = revert the two diffs, delete the three new files.
- 38 tests in CI may be slow or env-dependent → per-test timeout, quarantine
  with reason (loud in output), measured runtime reported in B6.
- Post-propagation instance breakage → fleet-verify surfaces per instance;
  brief's constraint honored: NO propagation until the gate catches ≥1 of F1-F4
  on real state in the skeleton.
- token-guard exemption could mask a real screenshot retry loop → exemption is
  scoped to check_exact_retry only; volume ceiling still catches runaway loops.

## Open questions

- Widen `stat-registry.json` scope beyond KTLYST_strategy, or wire stat-verify
  hooks? (founder; sp-72b60bff)
- Complement with rsync-exclude of `skeleton_only` in kipi-update.sh?
- `gates run` 280s runtime: acceptable baseline or optimize? (sp-ff44a6af)

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: A declaration file devs must maintain can rot into ritual; if the gate is
slow or noisy it gets bypassed like the rules that preceded it, adding a fifth
silent absence. Mitigations: bidirectional diff makes manifest rot loud in the
same run; failure messages name the exact one-line fix; runtime measured and
bounded by per-test timeouts.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run the gate on today's untouched repo state. If it does not catch F1 (34
unrun artifacts) and a simulated F3 (undeclared skeleton-only artifact in an
instance), the design is dead. This is mandated as the pre-propagation proof.

Q3: What is the cheapest non-build alternative?
A3: A prose rule "declare your tests" — prompt-only enforcement, which this
repo's own `prompt-only-enforcement-guard.py` exists to block, and which 31
RCAs demonstrate does not hold.

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
-->

```json
[]
```
