---
description: Re-snapshot the active issue's scope from the spec, clear verified and reviewed receipts, and record the change as a permanent amendment
---

Use this when you realize mid-build that the spec was wrong. The flow:

1. The founder edits the issue spec in `q-ktlyst/.q-system/issues/<id>.md` (or the instance-equivalent path). Typical edits: widen `allowed_files`, adjust `required_checks`, add a new `disallowed_files` entry.

2. Run amend with a short reason explaining what changed and why:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" amend \
     --reason "realized the bug also lives in helpers/*, widening scope"
   ```

   The runner does four things:
   - Re-reads the spec from disk.
   - Re-snapshots `allowed_files`, `required_checks`, and `disallowed_files` into state.
   - Clears `receipts.verified` and `receipts.reviewed` (forces re-verify + re-review).
   - Appends an entry to `state.amendments` with timestamp, reason, old snapshot, new snapshot.

   What amend does NOT change:
   - `review_rounds` counter (the cap still governs; amending does not reset review budget).
   - Spec `status` (stays `in-progress`).
   - `findings_triaged` receipt (that receipt only matters at closeout).

3. Exit 0 means the amendment is logged. Exit 2 means either no active issue or missing `--reason`.

4. Re-run `/issue-verify` to regenerate the verified receipt against the new scope. Then `/issue-review` for the reviewed receipt. The runner's review-rounds cap still applies; amending does not grant extra review budget. If a full standard + adversarial pair already ran pre-amend, `ISSUE_ALLOW_REVIEW_REPEAT=1` is the override knob.

5. On `/issue-closeout`, `close` flushes all entries from `state.amendments` into an `## Amendments` section at the bottom of the spec file. That becomes the permanent audit record. After close, the spec shows exactly what was amended, when, why, and what the scope looked like before and after each amendment.

Guardrails:

- Amend is for genuine mid-build spec corrections. It is not a retry button after a bad review. If the issue as specified was fine but the implementation was wrong, fix the implementation. Do not amend.
- Amend requires a non-empty `--reason`. Empty strings are rejected.
- Amend does not create or modify files other than `.claude/state/active-issue.json`. The spec edit is a separate manual step before amend.
- Repeated amendments are fine. Each one records its own before/after snapshot and adds its own entry to the permanent footer on close.
