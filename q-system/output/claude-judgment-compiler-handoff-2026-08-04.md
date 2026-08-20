# Claude implementation brief: bake the Judgment Compiler into Kipi

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

Copy everything below into Claude from the repository root:

---

You are working in `/Users/assafkipnis/projects/kipi-system`.

Build the Kipi Judgment Compiler end to end. This is a system change, not a concept memo. Inspect the repository, create the required PRD, implement it, test it, wire it into the existing PRD review and triage flow, and leave evidence that it works.

Do not stop after producing a plan or PRD. Continue through implementation, deterministic tests, integration verification, Codex review, and wiring checks. Follow every applicable `AGENTS.md`, `CLAUDE.md`, repository rule, and PRD OS contract. Do not overwrite or clean unrelated worktree changes.

## Why this exists

Kipi already has two parts of Airbnb's evaluation framework:

1. Cheap deterministic checks first: hooks, scripts, validators, required checks, tests, and gates.
2. An LLM judge second: Codex review and finding generation.

The missing layer is the decision context required to calibrate that judge against founder decisions.

We tested whether finding text and severity alone could predict Assaf's final workflow disposition. The result was conclusive: they cannot.

Read these artifacts before designing anything. **In the repo:**

- `q-system/output/founder-judge-calibration-v1-report.md`
- `q-system/.q-system/scripts/founder-judge-calibration.py`
- `q-system/output/rca/rca-founder-judge-calibration-context-and-temp-2026-08-03.md`
- `q-system/output/prd-founder-judge-calibration-2026-08-03.md`

**Local run output, NOT in the repo** — these two are the frozen dataset and the
hash-bound run receipt. They live only on the machine that ran v1:

- `q-system/output/founder-judge-calibration-v1.jsonl` (ignored by `.gitignore:36`, `*.jsonl`)
- `q-system/output/founder-judge-calibration-v1-run.json` (ignored by `.gitignore:17`, `q-system/output/*.json`)

So **the v1 benchmark cannot be re-verified or re-run from a fresh clone**, and
the numbers below are read from the report, not reproducible by a reader who does
not have those two files. Do not write a plan whose first step assumes otherwise.

That exclusion is deliberate, not an oversight in the recovery (codex review of
PR #106, major). Each dataset row carries a `founder_rationale` free-text field —
Assaf's own words on 50 real triage decisions — and this repo is PUBLIC. Two
standing ignore rules already cover run output; overriding both to publish
founder free-text is a blast-radius decision that earns its own issue, not a
side effect of recovering work-product docs. If v1 must become reproducible, the
options are a redacted dataset (drop `founder_rationale`, keep the labels) or a
private location the checker can point at. Both are real work; neither is this PR.

The verified v1 result:

- 50 cases, balanced as 20 accepted, 20 rejected, and 10 deferred
- 40% exact agreement
- 35% balanced accuracy
- 0.239 macro F1
- 0.032 Cohen's kappa
- Judge predictions: 45 accepted, 0 rejected, 5 deferred
- Accepted recall: 95%
- Rejected recall: 0%
- Deferred recall: 10%
- Mean confidence: 92.2%
- Mean confidence on wrong predictions: 91.1%
- 10-bin expected calibration error: 0.522
- 18 of 38 predictions at or above 90% confidence were correct
- Post-stratified accuracy estimate: 73.3%
- Historical accept-all baseline: 76.6%

The judge was confident and worse than the historical accept-all baseline. The issue was not simply the prompt. The input contract was incomplete.

Assaf's disposition depends on state the blind judge did not receive:

- Whether the finding duplicates another finding or issue
- Whether the problem was already fixed
- Whether a different PRD already owns the work
- Whether scope changed after the finding was written
- Whether the relevant issue was removed, reordered, or superseded
- Which remediation receipts exist
- Which commit, PRD revision, and issue manifest were current at decision time
- Whether the objection is technically valid but belongs later

The core lesson is:

> A disposition is not a property of an objection. It is a property of an objection inside workflow state.

## Objective

Build an append-only Judgment Compiler that captures the complete decision episode, separates technical judgment from workflow disposition, evaluates agreement against prospective human decisions, and turns repeated override patterns into deterministic policy candidates.

The loop must be:

```text
agent finding
  -> deterministic checks
  -> decision context assembler
  -> LLM technical judgment + workflow recommendation
  -> human calibration sample
  -> append-only decision receipt
  -> repeated-pattern detection
  -> reviewed executable gate
  -> deterministic checks
```

Human decisions calibrate the judge. Humans should not manually grade every output. Repeated decisions should reduce future human work by becoming deterministic checks.

## Required system behavior

### 1. Immutable triage episode receipt

Create a versioned, append-only receipt for each adjudicated finding. Use the repository's existing receipt and ledger patterns where possible. Do not create a competing storage convention without proving the current one cannot support this.

Each receipt must freeze at least:

- Receipt ID and schema version
- Capture timestamp
- Finding ID, exact finding text, severity, and hash
- Review provider and review run ID
- Repository, branch, commit SHA, and dirty-state marker
- PRD path, PRD hash, PRD status, and revision identity
- Issue ID and exact issue-manifest snapshot or hash
- Current scope declaration
- Dependency and issue-ordering state
- Candidate duplicate findings and their stable IDs
- Existing remediation receipts and evidence references
- Related PRDs or issues that may own the work
- Deterministically assembled context facts
- Missing-context markers
- Judge model, prompt hash, input hash, and output hash
- Human actor or founder identity
- Human decision timestamp
- Human disposition
- Structured human reason code
- Evidence IDs supporting the disposition
- Previous receipt hash or another integrity mechanism consistent with Kipi's ledger design

Never mutate old receipts to reflect current state. A later correction must append a superseding receipt that points to the original.

### 2. Deterministic decision-context assembler

Before asking an LLM for a workflow recommendation, assemble repository state with deterministic code.

At minimum, resolve or explicitly mark unknown:

- Duplicate or cross-PRD ownership matches
- Existing remediation evidence
- Current in-scope or out-of-scope status
- PRD and issue status
- Issue ordering and dependencies
- Superseding decisions
- Receipt state
- Exact source revisions and hashes

Do not let the LLM invent these facts. The LLM may reason over recorded facts. It may not manufacture missing workflow state.

Every context fact must include its source path, stable ID, query, or receipt reference. Missing evidence must remain `unknown`, not become `false`.

### 3. Split the judge output into two decisions

The judge contract must produce separate fields:

```json
{
  "technical_validity": "valid | invalid | uncertain",
  "technical_reason": "...",
  "workflow_disposition": "fix-now | already-remediated | duplicate | scope-removed | out-of-scope | defer | invalid | needs-human",
  "workflow_reason_code": "...",
  "evidence_refs": ["..."],
  "missing_context": ["..."],
  "confidence": 0.0
}
```

Technical validity and workflow disposition cannot be collapsed into one accepted, rejected, or deferred label. A finding can be technically valid and still be a duplicate, already fixed, out of scope, or intentionally deferred.

Use one canonical reason-code enum. Start with:

- `valid-fix-now`
- `already-remediated`
- `duplicate`
- `owned-by-other-prd`
- `scope-removed`
- `out-of-scope`
- `superseded`
- `defer-dependency`
- `defer-ordering`
- `invalid-finding`
- `insufficient-context`
- `needs-human`

Change this list only when repository evidence proves a different taxonomy is required. Record the reason in the PRD.

### 4. Deterministic disposition evidence gate

Unsupported workflow dispositions must not pass as facts.

Enforce at least:

- `already-remediated` requires a remediation receipt or exact code/test evidence.
- `duplicate` requires a stable reference to the owning finding or issue.
- `owned-by-other-prd` requires a stable PRD and issue reference.
- `scope-removed` and `out-of-scope` require a cited scope record.
- `superseded` requires the superseding decision receipt.
- A missing required reference converts the recommendation to `needs-human` or causes deterministic validation to fail. Choose the behavior based on the existing Kipi contract and document it.
- Confidence must be finite and between 0 and 1.
- Extra fields, missing fields, unknown enums, stale hashes, duplicate receipt IDs, and broken references must fail validation.

Prompt instructions alone are not enforcement. Implement the contract in code with tests.

### 5. Prospective calibration dataset

Create a v2 dataset from new, immutable, context-complete decisions.

Do not reconstruct current context for the old 50 cases and claim it was the context available at the historical decision. Keep v1 as a context-free stress-test and regression artifact.

The v2 dataset must bind:

- Exact judge input
- Context snapshot
- Schema
- Prompt
- Model
- Prediction
- Human disposition
- Evidence references
- All relevant hashes

The evaluator must report:

- Exact agreement
- Cohen's kappa
- Balanced accuracy
- Macro F1
- Per-class precision and recall
- Confusion matrix
- Confidence calibration and 10-bin ECE
- Human-review rate
- Unsupported-disposition rate
- Missing-context rate
- Results by reason code
- Population baseline and class distribution

The evaluator must work in a read-only environment. Preserve and extend the current hash verification and blind-run protections.

### 6. Human calibration and live sampling

Wire calibration into the real review workflow.

- During initial calibration, collect at least 50 prospective context-complete human decisions.
- After calibration, deterministically sample 5% of live eligible decisions for human review.
- Sampling must be reproducible and auditable, not `random()` with no seed or receipt.
- Escalate all `needs-human`, missing-context, invalid-schema, and unsupported-evidence cases regardless of the 5% sample.
- Never silently auto-decide a class that has not passed its release threshold.

Use these as Kipi release gates, not as claims about Airbnb's exact thresholds:

- At least 88% exact agreement
- Cohen's kappa at least 0.80
- At least 80% recall for every automated workflow disposition
- No schema or evidence-gate bypasses
- Every automated disposition produces a valid receipt

Until all applicable gates pass, the judge recommends. It does not make the final workflow decision.

### 7. Repeated-pattern detector and policy candidates

Analyze human overrides by structured reason code and context fact.

When the same deterministic pattern recurs, produce a policy candidate containing:

- Pattern definition
- Supporting receipt IDs
- Case count
- Counterexamples
- Proposed deterministic rule
- Proposed tests
- Expected false-positive risk
- Exact integration point

Do not automatically install a new gate from model output. Policy promotion requires repository review, deterministic tests, and the existing approval path. Once approved, the new rule must execute before the LLM judge.

## Integration requirements

- Find the existing PRD review, Codex review, finding ledger, remediation receipt, delivery truth, and command wiring before selecting file locations.
- Extend existing canonical paths and schemas where they fit.
- Add CLI commands only through the existing Kipi command architecture.
- Prefer names that express behavior. Recommended user-facing concept: `Judgment Compiler`.
- Suggested command shapes are `kipi judgment capture`, `kipi judgment evaluate`, `kipi judgment verify`, and `kipi judgment policy-candidates`. Use different names if the existing CLI grammar requires them.
- The real integration point is the PRD finding disposition flow. A standalone script with no caller is not done.
- Update folder-structure rules, command discovery, help text, schemas, and propagation wiring when applicable.
- If skeleton-owned files change, run the required `kipi update --dry`, propagation, and validation flow defined by repository rules.
- Preserve backward compatibility for v1 benchmark artifacts.

## PRD and implementation discipline

Create the product/system PRD using:

`q-system/marketing/templates/prd.md`

Save it as:

`q-system/output/prd-judgment-compiler-2026-08-04.md`

The PRD must explicitly include:

- Evidence from the verified v1 benchmark
- The incomplete-input-contract root cause
- In-scope and out-of-scope boundaries
- Receipt schema
- Context assembler contract
- Judge schema
- Evidence gate
- Prospective v2 calibration
- Sampling behavior
- Policy-candidate behavior
- Migration and backward compatibility
- Negative and bypass tests
- Wiring checklist
- Rollback plan

Do not add unrelated refactors or general eval infrastructure. Build only what this closed loop requires.

## Required test-first verification

Before implementation, add deterministic repros for the current gaps. They must demonstrate that the current system cannot:

1. Preserve immutable decision-time workflow context.
2. Distinguish technical validity from workflow disposition.
3. Reject `duplicate`, `already-remediated`, or `out-of-scope` without evidence.
4. Reproduce and verify a context-complete judge run from hashes.
5. Sample live decisions reproducibly.

Then implement until the repros pass.

Required negative tests include:

- Duplicate without an owning reference
- Already remediated without a receipt
- Scope removal without a scope record
- Missing context represented as false
- Changed PRD after receipt capture
- Mutated historical receipt
- Duplicate receipt ID
- Broken previous-receipt hash
- Unknown reason code
- Confidence outside 0 to 1
- Judge output with extra fields
- Reconstructed historical context presented as original context
- A policy candidate with no counterexample search
- A policy candidate becoming an active gate without review

Required regression checks include:

- Existing v1 self-test still passes.
- Existing v1 dataset verification still passes.
- Existing PRD review behavior remains available.
- Existing finding and remediation receipt readers still work.
- New tests pass in a read-only execution environment.
- `kipi check` passes.
- The repository wiring check passes.

## Definition of done

This work is done only when all of these are true:

- The PRD is complete and marked Done.
- The context assembler is deterministic and source-backed.
- The receipt is append-only, versioned, hash-verifiable, and supersedable without mutation.
- Technical validity and workflow disposition are separate contracts.
- Unsupported dispositions are blocked by executable validation.
- The v2 evaluator can score context-complete prospective cases.
- Live sampling is reproducible and recorded.
- Policy candidates are evidence-backed and cannot self-install.
- The feature is called by the real PRD triage workflow.
- All new and regression tests pass.
- The implementation survives read-only verification.
- Codex review returns clean or every finding has a recorded disposition and receipt.
- The mandatory wiring checklist is complete.
- A concise operator guide shows Assaf the exact commands and outputs.

At completion, report only:

- What changed
- Exact files changed
- Commands run and their results
- Where the Judgment Compiler enters the existing workflow
- Current calibration status and how many prospective cases exist
- Anything still blocked by missing real human decisions

Do not claim the judge is calibrated before prospective evidence meets the gates.

---
