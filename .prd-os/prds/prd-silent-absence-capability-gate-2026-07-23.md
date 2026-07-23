---
id: prd-silent-absence-capability-gate-2026-07-23
title: Silent Absence Capability Gate
status: archived
created_at: 2026-07-23T20:46:57Z
updated_at: 2026-07-23T22:07:38Z
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

### Contracts (v1, binding — added at triage, findings 4/5/6/8/10/13)

- **Manifest schema:** top-level `schema_version` (int, v1=1) + the four set
  keys. Unknown top-level keys, duplicate paths within a set, malformed JSON,
  or a missing `schema_version` → gate RED (fail closed). Paths are
  repo-root-relative, normalized, no globs in `expected_tests` (exact paths;
  discovery uses conventions, declaration is literal). `timeout_s` bounds:
  5-600.
- **Overlay is add-only:** `capability-manifest.local.json` may only ADD
  `expected_tests` and `required_data` entries. Any key colliding with a
  canonical entry, any `skeleton_only`/`declared_inert`/quarantine content in
  an overlay → gate RED. The overlay cannot weaken anything.
- **Quarantine expires:** each quarantine entry requires `reason`,
  `spillover_id`, and `expires` (ISO date). Past `expires` → gate RED.
  Quarantine count is printed in every run summary.
- **Wiring-detector surface (F2 class), textual-reference contract:** a file in
  `q-system/.q-system/` matching `*.py` with the executable bit or a
  `__main__` guard is "referenced" iff its basename appears in any of:
  `.claude/settings.json`, `settings-template.json`, `plugins/*/hooks.json`,
  `validate-separation.py`, `.github/workflows/*.yml`, repo-root `kipi*` +
  `*.sh`, `q-system/.q-system/scripts/*.sh`, or another scanned `.py` file
  (import or subprocess string). Unreferenced + not in `declared_inert` → RED.
  This is declared as a textual heuristic, not full reachability; false
  positives are resolved by a `declared_inert` entry or a real call site —
  both loud.
- **Runner contract:** cwd = repo root; env = inherited + `QROOT` set to
  `q-system/`; per-test timeout default 60s (`timeout_s` override); stdout+
  stderr captured, last 20 lines printed on failure; rc!=0 or timeout → RED.
  No network assumptions; a test needing live services gets quarantined with
  reason + expiry.
- **Mode detector:** skeleton iff `instance-registry.json` exists at repo root.
  Registry parse failure → RED (never silently instance mode). Paths under
  `.claude/worktrees/` refuse to run (exit 3, "run from the primary checkout").
- **Coverage boundary (v1, loud):** scan roots are
  `q-system/.q-system/scripts/` (recursive) + `q-system/.q-system/*.py` tests.
  `plugins/*/tests` and repo-root test files are OUT of v1 scope and are
  listed in the manifest under `uncovered_known` so the boundary itself is
  declared (finding-9, deferred).

### Quick-fix bounds (finding-11)

Repairing a newly-executed failing test is in scope ONLY within: the test file
itself, or a ≤5-line fix in the module under test. Anything larger →
quarantine with reason + expiry + spillover capture. `allowed_files` in the
issue specs enforce the file boundary.

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

- Blast radius: five additive files (capability-gate.py, capability-manifest.json,
  test_capability_gate.py, test_token_guard_observation.py,
  fleet-capability-verify.py) + small diffs in validate.yml,
  validate-separation.py, kipi, kipi-update.sh + token-guard.py edits.
  Rollback = revert the diffs, delete the five new files.
- Instance rollback (finding-12): instances receive ONLY synced-tree files via
  `kipi update` (rsync overwrite). Rollback = revert skeleton, re-run
  `kipi update` — the rsync restores every instance's synced tree to the
  reverted state. This PRD creates no instance-local overlays and no
  instance-repo-root files, so no per-instance cleanup exists to miss. The
  updater's auto-commit in each instance records both directions.
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
[
  {
    "id": "sag-core-gate-build",
    "finding_id": "finding-1",
    "title": "Build capability-gate.py + capability-manifest.json + paired tests + token-guard fixes (atomic decomposition anchor)",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/capability-manifest.json", "q-system/.q-system/scripts/test_capability_gate.py", "q-system/.q-system/token-guard.py", "q-system/.q-system/scripts/test_token_guard_observation.py", "q-system/.q-system/scripts/**"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py", "python3 q-system/.q-system/scripts/test_token_guard_observation.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only",
    "acceptance": "Gate discovers all three conventions, runs them as subprocesses, diffs both directions; manifest declares all four sets; token-guard has observation exemption + stall-warn rate limit with paired tests."
  },
  {
    "id": "sag-manifest-schema-validation",
    "finding_id": "finding-4",
    "title": "Manifest validation contract: schema_version, unknown-key/duplicate/malformed = RED",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only schema"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-overlay-add-only",
    "finding_id": "finding-5",
    "title": "Overlay is add-only: local overlay cannot remove/quarantine/reclassify canonical entries",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only overlay"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-quarantine-expiry",
    "finding_id": "finding-6",
    "title": "Quarantine entries require reason + spillover_id + expires; expired = RED; count always printed",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/capability-manifest.json", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only quarantine"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-wiring-detector-contract",
    "finding_id": "finding-8",
    "title": "F2 wiring detector: enumerated textual surfaces incl. repo-root kipi/*.sh and py imports; declared heuristic",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/capability-manifest.json", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only wiring"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-runner-contract",
    "finding_id": "finding-10",
    "title": "Runner contract: cwd=repo root, QROOT env, 60s default timeout, tail-20 on fail, no network assumptions",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only runner"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-mode-detector",
    "finding_id": "finding-13",
    "title": "Mode detector: registry-present=skeleton, parse-failure=RED, worktree paths refuse (exit 3)",
    "allowed_files": ["q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only mode"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-callsite-instance-check",
    "finding_id": "finding-2",
    "title": "Instance-side call site designed end-to-end: kipi check runs gate in the TARGET repo + kipi update runs gate per instance post-sync",
    "priority": "p0",
    "allowed_files": ["validate-separation.py", "kipi-update.sh", "kipi", "q-system/.q-system/scripts/capability-gate.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["sh -c 'grep -q capability-gate validate-separation.py'", "sh -c 'grep -q capability-gate kipi-update.sh'"],
    "bypass_check": "python3 q-system/.q-system/scripts/capability-gate.py --check-only"
  },
  {
    "id": "sag-callsite-single-execution",
    "finding_id": "finding-15",
    "title": "CI executes the gate exactly once: validate.yml owns the direct invocation; validate-separation gate section is skippable via env for CI",
    "allowed_files": [".github/workflows/validate.yml", "validate-separation.py", "q-system/.q-system/scripts/test_capability_gate.py"],
    "required_checks": ["sh -c 'grep -c capability-gate .github/workflows/validate.yml'"],
    "bypass_check": "sh -c 'grep -q capability-gate .github/workflows/validate.yml'"
  },
  {
    "id": "sag-fleet-verify-semantics",
    "finding_id": "finding-3",
    "title": "fleet-capability-verify.py: per-instance green/red/SKIPPED(standalone, reason printed); standalone entries (no q-system/.q-system) never silently pass",
    "allowed_files": ["fleet-capability-verify.py"],
    "required_checks": ["python3 fleet-capability-verify.py --self-test"],
    "bypass_exempt": "fleet verifier is skeleton-local tooling; its own --self-test is the no-bypass proof and gates.jsonl must not depend on 24 external repos being reachable"
  },
  {
    "id": "sag-fleet-red-schema",
    "finding_id": "finding-16",
    "title": "No instance-level acceptable-red: statuses are green/red/skipped(standalone) only; reasons exist per-test (quarantine), never per-instance",
    "allowed_files": ["fleet-capability-verify.py"],
    "required_checks": ["python3 fleet-capability-verify.py --self-test"],
    "bypass_exempt": "schema-definition slice of sag-fleet-verify-semantics; same self-test covers it"
  },
  {
    "id": "sag-quickfix-bounds",
    "finding_id": "finding-11",
    "title": "Quick-fix bounds encoded: test file itself or <=5-line fix in module under test; larger = quarantine + spillover",
    "allowed_files": [".prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md", "q-system/.q-system/scripts/**"],
    "required_checks": ["sh -c 'grep -q \"Quick-fix bounds\" .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md'"],
    "bypass_exempt": "scope-bounding text + per-issue allowed_files enforce it; no runtime surface to bypass"
  },
  {
    "id": "sag-rollback-instances",
    "finding_id": "finding-12",
    "title": "Rollback covers propagated instances: revert skeleton + re-run kipi update restores synced trees; no instance-local artifacts created",
    "allowed_files": [".prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md"],
    "required_checks": ["sh -c 'grep -q \"Instance rollback\" .prd-os/prds/prd-silent-absence-capability-gate-2026-07-23.md'"],
    "bypass_exempt": "rollback procedure documentation; enforcement is the kipi update rsync itself"
  },
  {
    "id": "sag-negative-proof-matrix",
    "finding_id": "finding-7",
    "title": "Negative proof is a matrix, not any-one: F1 undeclared-caught, F3 skeleton-only skip + undeclared-fails-in-instance, F2 unwired-caught, token-guard tests green — ALL before propagation",
    "priority": "p0",
    "allowed_files": ["q-system/.q-system/scripts/test_capability_gate.py", "q-system/.q-system/scripts/capability-gate.py"],
    "required_checks": ["python3 q-system/.q-system/scripts/test_capability_gate.py --only negative-proof"],
    "bypass_check": "python3 q-system/.q-system/scripts/test_capability_gate.py --only negative-proof"
  }
]
```
