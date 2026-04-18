---
description: Run Codex native + adversarial review against the active issue, scoped to allowed_files, capped per kind
---

Run the required reviews for the active DSSE issue. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status`. Confirm an issue is loaded AND `receipts.verified` is set. If `verified` is null, stop. Tell the founder to run `/issue-verify` first. Reviewing unverified code wastes Codex runtime.

2. Pull the snapshotted scope. The runner stamped `allowed_files` into state at load/approve so mid-issue spec edits cannot expand the review surface:

   ```bash
   ALLOWED=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" allowed-files)
   ```

   `$ALLOWED` is a JSON array (e.g. `["q-ktlyst/.q-system/agent-pipeline/schemas/**","q-ktlyst/.q-system/scripts/**"]`). If empty, stop and tell the founder the spec has no scope.

3. Try to claim a "standard" review slot before invoking Codex:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" record-review standard
   ```

   - Exit 0: slot claimed, proceed to step 4.
   - Exit 2: cap reached (default 2 standard rounds). The runner names the cap and the override env. Stop and ask the founder if they want to opt in via `ISSUE_ALLOW_REVIEW_REPEAT=1` for a single retry, OR triage and close with the existing review.

4. Invoke `codex:review` (Codex native review) against `origin/main`. Build the focus text with the scope filter inline so Codex stays inside the contracted surface:

   ```
   Scope filter: $ALLOWED
   Limit findings to changes inside these paths. Code outside these paths is out of contract for this issue. If a finding requires touching files outside this list, mark it out-of-scope explicitly and do not propose a patch.
   ```

   Use `--base origin/main --background` unless the diff is trivially small (1-2 files). When the command returns, wait for completion via `codex:result` / `codex:status`. Paste the full verdict block to the founder verbatim.

5. Try to claim an "adversarial" review slot:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" record-review adversarial
   ```

   - Exit 0: slot claimed, proceed to step 6.
   - Exit 2: cap reached (default 1 adversarial round per slice). Stop. Ask the founder if they want to opt in via `ISSUE_ALLOW_REVIEW_REPEAT=1` OR proceed straight to closeout.

6. Invoke `codex:adversarial-review` against `origin/main` with focus text built from `$ALLOWED` plus the contract directive:

   ```
   Scope filter: $ALLOWED
   Contract slice: this issue ships ONLY the change visible in the diff above. Limit findings to defects inside these paths. Do not raise edge cases that would require new follow-up issues. Do not flag pre-existing patterns in unchanged code. Do not propose architectural rewrites. If you have no defect inside the contract slice, return approve.
   ```

   Same `--base origin/main --background` pattern. Wait for completion. Paste verdict verbatim.

7. Pipe each review's findings into the per-finding writer. Codex output may be free-form; translate to `[{severity, body, affected_path}]`. The writer assigns sequential ids, stamps `created_at`, marks `out_of_scope=true` for paths outside `$ALLOWED`, and sets `disposition=pending`:

   ```bash
   echo '<JSON_ARRAY>' | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" \
     add <issue-id> --source codex-review --allowed-files-json "$ALLOWED"
   ```

   Repeat with `--source codex-adversarial` for the adversarial pass. If a review returned approve with no findings, skip the writer call for that source.

8. If both reviews completed (regardless of verdict, even if findings exist):
   - Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" mark reviewed`.
   - Report: "reviewed receipt recorded at <timestamp>. Findings now belong to `/issue-closeout` triage."

9. If either review failed to complete (Codex error, timeout, parse error):
   - Do NOT call `mark reviewed`.
   - Note: the slot was already claimed in step 3 / step 5. Re-running `/issue-review` will hit the cap. Tell the founder to retry with `ISSUE_ALLOW_REVIEW_REPEAT=1` if the failure was transient.
   - Report the failure mode. Stop.

Do not fix findings in this command. Codex is the reviewer. Triage and disposition happen in `/issue-closeout`. Do not relaunch `/issue-review` on your own initiative; founder must opt in to a repeat round.
