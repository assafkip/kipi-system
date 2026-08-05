# RCA: Founder-judge benchmark passed locally but did not survive read-only review

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

**Date:** 2026-08-03
**Trigger:** Read-only Codex methodology review of the completed 50-case run
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

The first benchmark reported 44% agreement and passed its local self-test. The
read-only review showed that the self-test required a writable temporary
directory. The same review showed that the headline number mixed judge behavior
with workflow context that the blind input never supplied.

## Surface symptom

The read-only review produced:

```text
FileNotFoundError: No usable temporary directory found
```

It also found near-identical empty-manifest findings with different founder
dispositions because their surrounding PRD state differed.

## Surface root cause

`selftest()` called `tempfile.TemporaryDirectory()` without handling a read-only
environment. The blind export supplied finding text and severity while the gold
disposition also depended on duplicate status, prior remediation, issue ordering,
and scope changes.

## Structural root cause

### Root cause #1

type: implicit-contract

The benchmark treated workflow disposition as a property of finding text. In the
real workflow, disposition is a decision about a finding inside changing PRD
state. The input contract omitted part of the target.

### Root cause #2

type: missing-test

The self-test was run only where a temporary directory was writable. No test
exercised the same read-only environment used by Codex review.

### Root cause #3

type: process

The first run saved predictions and a report, but not the exact blind input,
prompt, model, schema, session, and content hashes. The claim of blindness was
not independently auditable.

## Verification

- Ran `python3 q-system/.q-system/scripts/founder-judge-calibration.py --selftest` after the fix. Result: `SELFTEST PASS: scoring changes, schema and coverage enforced, blind export clean`.
- Ran `python3 q-system/.q-system/scripts/founder-judge-calibration.py verify --dataset q-system/output/founder-judge-calibration-v1.jsonl`. Result: `VERIFY PASS: 50 unique cases, 20/20/10 balance, all source hashes match`.
- Ran the corrected blind input through `codex exec` with session `019fcb14-613e-7dd0-a3d0-8da1e4fdfc9a`. Result: 50 schema-valid predictions and a hash-bound run receipt.
- Scored the corrected run. Result: 20/50 exact agreement, 35.0% balanced accuracy, kappa 0.032, and 10-bin confidence error 0.522.

**These runs happened; they are not reproducible from a clone.** The dataset
(`...-v1.jsonl`) and the run receipt (`...-v1-run.json`) are run output excluded
by `.gitignore:36` (`*.jsonl`) and `.gitignore:17` (`q-system/output/*.json`), so
the `verify` line above exits 1 for anyone who does not have the original
machine's files. The record is kept in the past tense on purpose — deleting a
true verification because its artifact is not publishable would be the worse
error — but do not read it as an instruction a reader can follow. Why the
artifacts stay out, and the two ways to make v1 reproducible, are in
`q-system/output/prd-founder-judge-calibration-2026-08-03.md` section 5.

## Contributing factors

- The historical ledger is 76.6% accepted, while the stress test is deliberately balanced at 20/20/10.
- Historical finding bodies are mutable and can contain post-adjudication text.
- Prediction validation originally checked labels and IDs but not confidence, reason, or extra fields.

## Fixes shipped

- Surface fix: temp-file integration is best-effort; the core self-test stays fully in memory and passes read-only.
- Structural fix: the blind artifact contains only case ID, severity, and finding text; post-adjudication bodies are excluded; schema validation is enforced; confidence calibration, population baseline, limitations, and a hash-bound run receipt are recorded.

## Action items

- [x] Make the core self-test independent of filesystem writes — owner: Codex — type: test
- [x] Freeze and hash the exact blind input, schema, predictions, prompt, model, and report — owner: Codex — type: process
- [x] Exclude post-adjudication finding bodies from benchmark sampling — owner: Codex — type: code
- [x] Report confidence error and distinguish balanced from historical baselines — owner: Codex — type: code
- [ ] Capture immutable triage-time PRD context if a v2 must predict full founder disposition — owner: Assaf — type: process

## Lessons

- A disposition is not a property of an objection. It is a property of an objection inside workflow state.
- A blind eval needs a receipt for what the judge saw, not a statement that labels were removed.
- A high-confidence model can still be an uncalibrated triage proxy.
