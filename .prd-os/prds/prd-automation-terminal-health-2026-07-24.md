---
id: prd-automation-terminal-health-2026-07-24
title: Automation Terminal Health
status: approved
created_at: 2026-07-24T21:10:00Z
updated_at: 2026-07-24T21:08:00Z
owner: senior-staff
reviewers: []
findings_path: .prd-os/findings/prd-automation-terminal-health-2026-07-24-findings.jsonl
codex_reviewed_at: 2026-07-24T21:07:28Z
---

# Automation Terminal Health

## Problem

The Kipi watchdog classifies broken jobs but always exits zero
[`q-system/.q-system/scripts/launchd-health-check.py:2-23`,
`q-system/.q-system/scripts/launchd-health-check.py:227-231`]. It watches
Kipi-owned prefixes and external configuration
[`q-system/.q-system/scripts/launchd-health-check.py:48-60`], yet the operating
record does not prove that registered jobs deliver terminal output or remain
recovered after a retry [`AUTONOMOUS-SYSTEMS.md:15-28`,
`AUTONOMOUS-SYSTEMS.md:127-164`].

The heartbeat RCA found a missing completion invariant after a process could
run but omit the final result
[`q-system/output/rca/rca-heartbeat-tail-skip-2026-06-30.md:38-75`].
On 2026-07-24, `launchctl list` reported exit status 256 for
`com.cole.daily-social` and `com.cole.delivery-watch`; their logs showed
repeated lint failure, zero delivered items, missing first comments, retry
tiers, and a stranded draft. The latest fleet environment log reported that
Playwright Chromium was not installed. A read-only
`launchd-health-check.py --dry` run classified daily-social, delivery-watch,
and fleet-env-health as failing, would ping zero, and exited zero.

## Goals

- Define a terminal-output invariant for every Kipi-owned scheduled job.
- Verify dependencies before registration and after environment changes.
- Add completion receipts for content delivery and fleet sweeps.
- Distinguish a successful retry from durable recovery across later scheduled
  runs.
- Bound retry tiers and require one explicit terminal state.
- Add manual-run and launchd-run verification.
- Use current daily-social, delivery-watch, and Playwright failures as
  acceptance scenarios.
- Record external repository fixes as dependencies or spillover, never Kipi
  implementation issues.

## Non-goals

- Editing `/Users/assafkipnis/projects/cole-gtm` or any other external instance
  repository.
- Rewriting an external job's business logic.
- Treating watchdog notification as proof that the underlying work completed.
- Infinite retries or silent healing claims.

## Proposed approach

1. Define terminal states `delivered`, `no-work`, `blocked`, and `failed`.
   Every Kipi-owned job emits exactly one versioned receipt with job ID, run ID,
   start and end timestamps, output count, dependency snapshot, retry history,
   terminal state, and artifact references.
   A committed Kipi-owned job registry enumerates every enforced label,
   adapter, installer, receipt location, and dependency check. An unclassified
   scheduled Kipi job fails validation.
2. Make installers validate executable paths, interpreters, packages, browser
   binaries, permissions, output directories, and receipt locations before
   registration. Rerun the same check after environment changes.
3. Teach the watchdog to read receipts and launchd status separately. A retry
   is `recovered` only after the retry receipt succeeds and the next scheduled
   run also reaches a successful terminal state.
   Gate mode exits nonzero on a failed invariant. Notification mode reports
   alert delivery separately and cannot turn a failed job green.
4. Bound tiers and attempts in executable config. Exhaustion produces `failed`
   with the last error and next operator action.
5. Add a fixture harness that runs each Kipi-owned adapter directly and through
   a temporary launchd plist, then validates the same receipt invariant.
   Compact receipt logs before whole-file reads after 10,000 run records,
   preserving a verified archive and bounded active log.
6. Capture daily-social, delivery-watch, and missing-Playwright repairs as
   external dependencies with evidence references. Kipi tests simulate those
   failures but do not patch their repos.

## Alternatives considered

- **Use launchd exit status alone.** Rejected because a process can exit after
  omitting the promised output. [E2]
- **Treat one retry success as recovery.** Rejected because current logs show a
  job can heal once and fail again.
- **Patch external jobs here.** Rejected by the founder's Kipi-owned scope.

## Scenarios

- **Lint failure.** A daily-social fixture exits after producing no valid draft.
  The receipt says `failed`, output count zero, and names the failed invariant.
- **Zero delivery.** A delivery-watch fixture sees build-radar run without
  delivery. Retry success stays provisional until the next scheduled run.
- **Missing browser.** Installer preflight detects absent Playwright Chromium
  before job registration and emits `blocked`.
- **Manual versus launchd.** The same adapter passes manually but fails under
  launchd environment. The dependency snapshots explain the difference.

## Resolved decisions

- **Terminal output is the health unit.** Rationale: process liveness does not
  prove delivery.
- **Receipts are append-only run records.** Rationale: retry history and durable
  recovery must remain auditable.
- **Recovery needs a later scheduled success.** Rationale: one retry is not
  durable evidence.
- **External fixes stay external.** Rationale: this PRD owns Kipi contracts and
  tooling only.

## Risks and rollback

- Receipt enforcement can classify legacy jobs as failed. Start with fixtures
  and an explicit Kipi-owned registry. Rollback disables registration of the
  new contract without deleting receipts.
- Append-only receipts can grow. Rotate only after a verified archive and keep
  bounded reads for health checks.
- Temporary launchd tests can leave jobs registered. Use unique labels and a
  teardown assertion; rollback unloads only the test label.
- Retry bounds can surface more terminal failures. That is expected visibility,
  not a reason to hide exhaustion.

## Open questions

- Which fields from the executable Kipi-owned job registry should generated
  runbooks expose without duplicating authority?
- How many later scheduled successes are required before a job is called
  durably recovered?
- What retention and archive threshold applies to completion receipts?

## Evidence

- **E1:** `q-system/.q-system/scripts/launchd-health-check.py:2-23`,
  `q-system/.q-system/scripts/launchd-health-check.py:48-60`,
  `q-system/.q-system/scripts/launchd-health-check.py:90-231`.
- **E2:** `q-system/output/rca/rca-heartbeat-tail-skip-2026-06-30.md:38-98`,
  `q-system/output/rca/rca-heartbeat-tail-skip-2026-06-30.md:112-127`.
- **E3:** `AUTONOMOUS-SYSTEMS.md:15-28`, `AUTONOMOUS-SYSTEMS.md:127-164`;
  `q-system/canonical/autonomous-systems-record-2026-06-30.md:24-29`.
- **E4:** Read-only command results from
  `/Users/assafkipnis/Library/LaunchAgents` and declared external log paths,
  captured 2026-07-24: daily-social and delivery-watch status 256, failing
  content and delivery scenarios, and missing Playwright Chromium.
- **E5:** Command result
  `python3 q-system/.q-system/scripts/launchd-health-check.py --dry`, run
  2026-07-24: three failing jobs, zero pings, exit 0.

## Issues

```json
[
  {
    "id": "ath-terminal-receipt-contract",
    "finding_id": "finding-1",
    "title": "Define terminal-output receipts for Kipi-owned jobs",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/schemas/job-completion-receipt.schema.json", "q-system/.q-system/tests/test_job_completion_receipts.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_job_completion_receipts.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write failing missing, duplicate, and nonterminal receipt tests first. Require exactly one delivered, no-work, blocked, or failed terminal state with output and dependency evidence.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_job_completion_receipts.py -k 'missing or duplicate or nonterminal'"
  },
  {
    "id": "ath-installer-dependency-proof",
    "finding_id": "finding-2",
    "title": "Verify dependencies before registration and after environment change",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/scripts/launchd-dependency-check.py", "q-system/.q-system/tests/test_launchd_dependency_check.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_launchd_dependency_check.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write failing missing-browser, missing-executable, and launchd-environment tests first. Block registration and emit a dependency snapshot on failure.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_launchd_dependency_check.py -k 'browser or executable or environment'"
  },
  {
    "id": "ath-durable-recovery",
    "finding_id": "finding-3",
    "title": "Bound retries and distinguish durable recovery",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/scripts/launchd-health-check.py", "q-system/.q-system/config/retry-tiers.json", "q-system/.q-system/tests/test_durable_recovery.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_durable_recovery.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write failing retry-success-then-failure and exhausted-tier tests first. Require bounded attempts, a clear terminal state, and a later scheduled success before durable recovery.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_durable_recovery.py -k 'provisional or exhausted'"
  },
  {
    "id": "ath-manual-launchd-harness",
    "finding_id": "finding-4",
    "title": "Verify terminal delivery manually and under launchd",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/scripts/test-launchd-terminal-health.py", "q-system/.q-system/tests/test_launchd_terminal_harness.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_launchd_terminal_harness.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write a failing manual-pass launchd-fail fixture first. Use unique temporary labels, validate equal receipt invariants, and assert teardown.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_launchd_terminal_harness.py -k 'environment_delta or teardown'"
  },
  {
    "id": "ath-external-failure-fixtures",
    "finding_id": "finding-5",
    "title": "Lock current external failures as Kipi acceptance fixtures",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/fixtures/automation-failures/**", "q-system/.q-system/tests/test_automation_failure_scenarios.py"],
    "disallowed_files": ["q-system/.q-system/scripts/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_automation_failure_scenarios.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write failing fixtures first for daily-social lint failure, zero delivery, missing first comment, stranded draft, and absent Playwright Chromium. Point external repairs to dependencies or spillover only.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_automation_failure_scenarios.py -k external_repo_untouched"
  },
  {
    "id": "ath-kipi-job-registry",
    "finding_id": "finding-6",
    "title": "Enumerate every Kipi-owned scheduled job",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/config/kipi-jobs.json", "q-system/.q-system/tests/test_kipi_job_registry.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_kipi_job_registry.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write a failing unclassified-label test first. Enumerate labels, adapters, installers, dependencies, receipt paths, and terminal invariants for every Kipi-owned job.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_kipi_job_registry.py -k unclassified"
  },
  {
    "id": "ath-receipt-compaction",
    "finding_id": "finding-7",
    "title": "Bound completion-receipt storage and reads",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/scripts/job-receipt-store.py", "q-system/.q-system/tests/test_job_receipt_compaction.py"],
    "disallowed_files": ["q-system/output/**", "instance-registry.json", ".prd-os/**", "/Users/assafkipnis/projects/cole-gtm/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_job_receipt_compaction.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write a failing 10,001-record boot test first. Compact before whole-file reads, verify archive counts and hashes, and bound the active log.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_job_receipt_compaction.py -k boot_bound"
  },
  {
    "id": "ath-watchdog-exit-modes",
    "finding_id": "finding-8",
    "title": "Separate watchdog gate status from notification delivery",
    "priority": "p1",
    "allowed_files": ["q-system/.q-system/tests/test_launchd_health_exit_modes.py"],
    "disallowed_files": ["q-system/.q-system/scripts/launchd-health-check.py", "q-system/output/**", "instance-registry.json", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_launchd_health_exit_modes.py"],
    "required_reviews": ["automation-owner"],
    "acceptance": "Write a failing red-gate-zero-exit test first. Require gate mode to exit nonzero on failed terminal invariants and report notification success as a separate field.",
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_launchd_health_exit_modes.py -k failed_job_never_green"
  }
]
```
