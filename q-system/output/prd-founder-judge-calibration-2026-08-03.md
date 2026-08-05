# PRD: Founder-Judge Calibration

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

**Date:** 2026-08-03
**Author:** Codex
**Status:** Done
**Priority:** P1 (high)

---

## 1. Problem

Kipi records Codex findings and Assaf's dispositions, but it does not measure how
well a fresh judge predicts Assaf's triage decisions.

- **Evidence:** `.prd-os/findings/` contains 342 dispositioned Codex findings
  across 35 PRDs: 262 accepted, 61 rejected, and 19 deferred.
- **Impact:** Judge quality is discussed through individual findings. There is no
  agreement rate, balanced score, or confusion matrix.
- **Root cause:** The findings ledger was built for workflow closeout, not blinded
  calibration.

## 2. Scope

### In Scope

- Freeze 50 traceable historical Codex findings.
- Balance the set across accepted, rejected, and deferred founder decisions.
- Export a blind copy without the founder label or rationale.
- Score fresh predictions with accuracy, balanced accuracy, macro F1, and Cohen's kappa.
- Prove the scorer changes when predictions are corrupted.

### Out of Scope

- Replacing Codex review.
- Measuring clean passes where Codex raised no finding. The current ledger does
  not store claim-level negatives.
- Automatically changing any review threshold.

### Non-Goals

- Claiming this measures general model intelligence.
- Treating workflow disposition as proof that a finding was factually correct.

## 3. Changes

### Change 1: Calibration harness

- **What:** Build, blind, verify, and score a fixed founder calibration dataset.
- **Where:** `q-system/.q-system/scripts/founder-judge-calibration.py`
- **Why:** Turns the existing trail into a repeatable measurement.
- **Exact change:** Add a standard-library CLI with an isolated self-test.
- **Scope:** This repo only.

### Change 2: Frozen 50-case dataset and run receipts

- **What:** Store the selected cases, fresh predictions, and scored report.
- **Where:** `q-system/output/founder-judge-calibration-v1.*`
- **Why:** Makes the result inspectable and rerunnable.
- **Exact change:** Generate artifacts from the harness and a blind Codex CLI run.
- **Scope:** This repo only.

## 4. Change Interaction Matrix

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| Harness | Dataset | Harness owns dataset selection and validation | Dataset stores source hashes and selection rule |
| Harness | Predictions | Scorer refuses missing, duplicate, or unknown case IDs | Predictions must cover all 50 cases exactly once |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `q-system/.q-system/scripts/founder-judge-calibration.py` | Add | 584 | 0 |
| `q-system/output/founder-judge-calibration-v1.jsonl` | Add | 50 | 0 |
| `q-system/output/founder-judge-calibration-v1-blind.json` | Add | 254 | 0 |
| `q-system/output/founder-judge-calibration-v1-schema.json` | Add | 45 | 0 |
| `q-system/output/founder-judge-calibration-v1-predictions.json` | Add | 1 | 0 |
| `q-system/output/founder-judge-calibration-v1-report.md` | Add | 73 | 0 |
| `q-system/output/founder-judge-calibration-v1-run.json` | Add | 29 | 0 |

**Only `founder-judge-calibration.py` and `...-v1-report.md` are in the repo.**
The other five rows are run output and are excluded by standing ignore rules
(`.gitignore:36` `*.jsonl`, `.gitignore:17` `q-system/output/*.json`). They exist
on the machine that ran v1 and nowhere else, so **the v1 benchmark cannot be
re-verified or re-run from a clone** — `founder-judge-calibration.py verify
--dataset .../founder-judge-calibration-v1.jsonl` exits 1 there.

That is deliberate, not a gap in the recovery (codex review of PR #106, major,
raised twice). Each dataset row carries a `founder_rationale` free-text field —
Assaf's own words on 50 real triage decisions — and this repo is PUBLIC.
Overriding two standing run-output ignore rules to publish founder free-text is a
blast-radius decision that earns its own issue. To make v1 reproducible: publish a
redacted dataset (drop `founder_rationale`, keep the labels), or point the checker
at a private location.

## 6. Test Cases

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 1.1 | DET | Build balanced set | Live findings ledger | 20 accepted, 20 rejected, 10 deferred | Exactly 50 unique traceable cases |
| 1.2 | DET | Blind export | Frozen dataset | No label or rationale fields | Leak check returns zero forbidden keys |
| 1.3 | DET | Perfect prediction | In-memory fixture | 100% accuracy and kappa 1 | Exact values returned |
| 1.4 | DET | Negative self-test | One prediction flipped | Score drops below 100% | Corruption changes the result |
| 1.5 | DET | Missing prediction | One case omitted | Scorer exits nonzero | Coverage error is named |
| 1.6 | DET | Read-only review | No writable temp directory | Core self-test passes; integration names its skip | No traceback |

## 7. Regression Tests

| # | What to Verify | How to Verify | Pass Criteria |
|---|----------------|---------------|---------------|
| R-1 | Findings ledger stays read-only | Git diff restricted to new calibration artifacts | No `.prd-os` changes |
| R-2 | No third-party dependency | Inspect imports | Standard library only |

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| Calibration artifacts | Remove the new script, PRD, dataset, predictions, and report | None, all inputs remain untouched |

## 9. Change Review Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Changes are additive | Pass | Read-only against `.prd-os` |
| No conflicts with existing enforced rules | Pass | Output artifact plus standalone script |
| No hardcoded secrets | Pass | Finding text and internal IDs only |
| Propagation path verified | N/A | Repo-local measurement |
| Exit codes preserved | N/A | New standalone command |
| AUDHD-friendly | Pass | One command and one report |
| Test coverage for every change | Pass | Self-test, source verification, schema validation, and negative corruption proof pass |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Traceable cases | 50 | 50 | `founder-judge-calibration.py verify` passed |
| Label balance | 20/20/10 | 20/20/10 | Dataset build summary passed |
| Context-free exact agreement | 40.0% | Measured, not assumed | `founder-judge-calibration.py score` |
| Confidence calibration error | 0.522 | Measured, not assumed | 10-bin ECE in report |
| Negative proof | Pass | Corruption lowers score | `founder-judge-calibration.py --selftest` passed |

## 11. Implementation Order

1. Add the harness and isolated self-test.
2. Build and verify the frozen dataset.
3. Export blind cases and run Codex CLI.
4. Score predictions and write the report.
5. Mark this PRD done after every receipt is green.

## 12. Open Questions

| Question | Owner | Deadline | Resolution |
|----------|-------|----------|------------|
| Should a future v2 add clean-pass negatives and triage-time context? | Assaf | After v1 result | Not part of v1; requires a new immutable ledger shape |

## 13. Wiring Checklist

| Check | Status | Notes |
|-------|--------|-------|
| PRD file saved | Pass | This file |
| Code/config changes implemented and tested | Pass | Self-test, verify, blind run, score, and review completed |
| New files listed in folder structure | N/A | Existing output and scripts directories |
| New conventions referenced in root instructions | N/A | No new convention |
| Memory entry saved | N/A | Measurement artifact is the record |
| Propagation run | N/A | Repo-local |
| PRD Status updated to Done | Pass | Done after corrected blind rerun |
