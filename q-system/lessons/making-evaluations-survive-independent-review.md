---
id: making-evaluations-survive-independent-review
kind: methodology
title: Making Evaluations Survive Independent Review
date: 2026-10-31
---

Use this when you build an internal benchmark or eval whose result will later be re-run or audited by someone else (a reviewer, a CI job, a different agent, or a sandboxed verifier). Three failure modes make a locally-passing eval collapse under review: an incomplete input contract, an untested execution environment, and an unauditable run record. Close all three before claiming a result.

1. Derive the input contract from the decision, not from the text you happen to have.
- Write down the decision the system under test actually makes in production, as a function: what does the real decision-maker read before deciding?
- List every input in that set, including mutable state (current document/record state, prior decisions, configuration, time, upstream status). Mark each as present or absent in your eval payload.
- If the real decision depends on state that evolves across steps, the eval unit must be (item + state snapshot), not item alone. An eval that scores item text alone is measuring a different function than the one you ship.
- Encode the contract as a schema and validate every sample against it, so a missing field fails loudly instead of silently degrading to an easier task.

2. Run the eval under the harshest environment it will ever face, first.
- Enumerate the environments where the eval may execute: your dev machine, CI, a container, a read-only or network-restricted sandbox, a reviewer's constrained runtime.
- Take the intersection of their capabilities as your baseline: no writable working directory, no network, no ambient credentials, no shell tools beyond a declared list.
- Make the eval write nothing by default. Send results to stdout or to an explicitly passed output path; never assume a temp directory is writable. If scratch space is required, take it as a required argument and fail with a clear message when it is absent.
- Add a test that executes the eval in that minimal environment (read-only filesystem mount, network disabled) and assert it still produces a complete result. Treat passing only in the permissive environment as not passing.

3. Make blindness and reproducibility auditable artifacts, not claims.
- Before scoring, persist the exact blind input that was presented, byte for byte, separate from any answer key.
- Record alongside it: the full prompt or invocation text, the model/tool identifier and version, the output schema, the run or session identifier, all parameters affecting determinism, and a content hash of each of these plus the input set.
- Store the answer key separately, with its own hash, and record the timestamp or commit ordering showing the key was fixed before predictions were produced.
- Publish a verification procedure: given the saved artifacts, a third party can recompute the hashes, re-present the identical blind input, and compare. If a reviewer cannot reproduce the comparison from the artifacts alone, the result is a self-report, not a benchmark.

Checklist before reporting a score: the eval unit matches the production decision's full input set; the eval has passed in the most restricted target environment; the blind input, prompt, model, schema, parameters, and hashes are saved; and the key's precedence over the predictions is evidenced. Downgrade the claim explicitly for any unchecked item rather than reporting the number unqualified.
