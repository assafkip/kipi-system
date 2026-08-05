# Founder-Judge Context-Free Triage Stress Test v1

## Result

- Cases: 50
- Exact agreement: 20/50 (40.0%)
- Balanced accuracy: 35.0%
- Macro F1: 0.239
- Cohen's kappa: 0.032
- Balanced-set majority baseline: 40.0%
- Historical-ledger majority baseline: 76.6%
- Post-stratified accuracy estimate: 73.3%
- Judge predictions: 45 accepted, 0 rejected, 5 deferred

This is a deliberately balanced stress test. It measures whether finding text and severity alone can predict Assaf's workflow disposition. It does not measure clean-pass quality, objection-finding recall, or factual validity. The historical ledger is not balanced, so the exact agreement above is not an operational accuracy estimate.

## Assessment

- Accepted recall: 95.0%. The judge matched 19 of 20 accepted findings.
- Accepted precision: 42.2%. More than half of the judge's fix-now calls were not accepted by Assaf.
- Rejected recall: 0.0%.
- Deferred recall: 10.0%.
- The judge predicted `accepted` for 45 of 50 supplied objections. It is not a calibrated proxy for founder triage.
- Reweighted to the historical class mix, estimated accuracy is 73.3%, below the 76.6% always-accepted baseline.
- Hidden workflow context sets many labels. Duplicate status, prior remediation, issue ordering, and scope removal are absent from the blind input.
- Near-identical empty-manifest findings received different founder dispositions because the surrounding PRD state differed.

## Confidence calibration

- Mean confidence: 92.2%
- Mean confidence on wrong predictions: 91.1%
- 10-bin expected calibration error: 0.522
- Predictions at or above 90% confidence: 18/38 correct

## Confusion matrix

| Founder \ Judge | accepted | rejected | deferred |
|---|---:|---:|---:|
| accepted | 19 | 0 | 1 |
| rejected | 17 | 0 | 3 |
| deferred | 9 | 0 | 1 |

## Disagreements

- `fjc-v1-001` None/finding-1: founder `rejected`, judge `accepted`. The restoration would remove required schema structure, so the current PRD should preserve those sections with safe placeholders.
- `fjc-v1-005` prd-voice-refresh-monthly-2026-07-04/finding-10: founder `rejected`, judge `deferred`. Freshness and growth targets are useful operational metrics, but they are not necessary to establish the current automation flow.
- `fjc-v1-008` prd-memory-autocapture-2026-07-04/finding-7: founder `rejected`, judge `accepted`. The fallback changes the meaning of a core measurement proxy without defined validation, so its semantics need coverage.
- `fjc-v1-010` prd-capability-approval-token-2026-06-16/finding-8: founder `rejected`, judge `deferred`. Broader portability and migration across tool layouts are valid concerns but likely outside a PRD targeting the founder's current environment.
- `fjc-v1-013` None/finding-1: founder `deferred`, judge `accepted`. An uncalled semantic scanner leaves the advertised production validation unenforced.
- `fjc-v1-014` prd-cross-instance-learning-2026-06-19/finding-3: founder `deferred`, judge `accepted`. The rollback contract must address already-propagated sensitive data, not only the repository copy.
- `fjc-v1-015` prd-terminal-state-redrive-2026-08-01/finding-6: founder `rejected`, judge `accepted`. A rebase changes the reviewed diff, so approval must be refreshed and pinned to the final head.
- `fjc-v1-019` prd-build-craft-2026-06-15/finding-3: founder `rejected`, judge `accepted`. The issue combines several independently testable responsibilities and should be decomposed within the PRD.
- `fjc-v1-020` prd-voice-refresh-monthly-2026-07-04/finding-1: founder `rejected`, judge `accepted`. The empty formal manifest prevents splitting and omits required execution boundaries.
- `fjc-v1-021` prd-capability-token-signing-2026-06-16/finding-5: founder `rejected`, judge `accepted`. The signer must bind visible approval to the exact payload or the proposed authorization mechanism remains vulnerable to prompt confusion.
- `fjc-v1-022` prd-capability-token-signing-2026-06-16/finding-7: founder `rejected`, judge `accepted`. The install and migration sequence needs deterministic recovery behavior for partial failure and stale-token states.
- `fjc-v1-023` prd-capability-approval-token-2026-06-16/finding-2: founder `rejected`, judge `accepted`. The legacy environment bypass directly contradicts the one-approval-per-command security target.
- `fjc-v1-024` None/finding-1: founder `deferred`, judge `accepted`. A required bypass check that fails against the PRD's own gate invalidates current acceptance.
- `fjc-v1-026` prd-terminal-state-redrive-2026-08-01/finding-5: founder `rejected`, judge `accepted`. The escalation does not add an independent actor or mitigation and therefore cannot satisfy the claimed recovery behavior.
- `fjc-v1-027` prd-planning-personas-2026-05-13/finding-4: founder `rejected`, judge `accepted`. The command's core behavior depends on an active-PRD contract that must be defined or explicitly required.
- `fjc-v1-028` prd-cross-instance-learning-2026-06-19/finding-2: founder `deferred`, judge `accepted`. The primary promotion rule is not implementable or auditable until instance relatedness is defined and recorded.
- `fjc-v1-030` prd-planning-personas-2026-05-13/finding-6: founder `deferred`, judge `accepted`. The experiment needs a defined way to identify superficial answers or it cannot test the command's core thesis.
- `fjc-v1-031` prd-memory-autocapture-2026-07-04/finding-1: founder `rejected`, judge `accepted`. The empty Issues manifest omits the independently executable units required for approval.
- `fjc-v1-032` prd-canonical-writeback-contract-2026-07-24/finding-8: founder `accepted`, judge `deferred`. Graph compaction and large-scale boot-cost bounds are valid lifecycle concerns but can follow an initial bounded implementation.
- `fjc-v1-033` prd-capability-approval-token-2026-06-16/finding-3: founder `deferred`, judge `accepted`. The admitted filesystem-write bypass contradicts the PRD's core phase-one security claim and must be resolved or the claim narrowed.
- `fjc-v1-036` prd-enforcement-instruction-contract-2026-07-24/finding-7: founder `rejected`, judge `deferred`. The implementation already belongs to an existing P0 issue; this PRD should retain only the dependency and enforcement contract.
- `fjc-v1-038` prd-reorg-stale-ref-remediation-2026-07-06/finding-10: founder `rejected`, judge `accepted`. Conflicting evidence counts weaken the PRD's factual basis and should be reconciled in the current document.
- `fjc-v1-040` prd-reorg-stale-ref-remediation-2026-07-06/finding-3: founder `rejected`, judge `accepted`. The audit map structurally misses a class of in-scope moves and can incorrectly return success.
- `fjc-v1-042` prd-cross-instance-learning-2026-06-19/finding-1: founder `deferred`, judge `accepted`. The enforceable validator does not substantiate the PRD's central confidentiality guarantee.
- `fjc-v1-043` prd-silent-absence-capability-gate-2026-07-23/finding-9: founder `deferred`, judge `accepted`. The advertised repository-wide invariant is materially broader than actual discovery and must be expanded or explicitly narrowed.
- `fjc-v1-045` prd-silent-absence-capability-gate-2026-07-23/finding-14: founder `rejected`, judge `accepted`. Required-data scope should encode the intended capability contract rather than merely mirror today's observed file placement.
- `fjc-v1-046` prd-build-craft-2026-06-15/finding-12: founder `deferred`, judge `accepted`. The detector produces an in-scope false positive because substring matching does not establish actual fixture isolation.
- `fjc-v1-047` prd-lint-hook-ownership-dedupe-2026-07-02/finding-1: founder `rejected`, judge `accepted`. The empty manifest lacks all required execution, verification, and bypass-check structure.
- `fjc-v1-048` prd-fable-discipline-2026-07-04/finding-1: founder `rejected`, judge `accepted`. The PRD fails atomic decomposition requirements because its Issues manifest is empty.
- `fjc-v1-049` prd-lint-hook-ownership-dedupe-2026-07-02/finding-3: founder `rejected`, judge `accepted`. The cross-cutting hook invariant needs canonical path-resolution semantics or it will be both bypassable and prone to overblocking.
