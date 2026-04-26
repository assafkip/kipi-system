---
description: Triage Codex findings via per-finding dispositions, mark findings_triaged, close the active issue
---

**Autonomy contract.** This step is agent-handled, not founder-gated. Once every pending in-scope finding has a non-pending disposition (accepted/rejected/deferred) AND every accepted patch has been applied with required_checks green, close the issue automatically without founder confirmation. The founder is notified post-closeout via the final report (step 6). Founder-gated steps remain: `/issue-approve`, `/prd-approve`, `/prd-split` commit, and any mid-issue scope amendment. Disposition rationale text and patch correctness still need to meet the merge-blocker rules in step 3. Autonomy is about removing the gate prompt, not lowering the bar.

Close the active DSSE issue. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status`. Confirm `receipts.verified` and `receipts.reviewed` are both set. If either is null, stop and tell the founder which step is missing. Do not relaunch `/issue-review` on your own initiative; that command has its own iteration cap.

2. Pull the snapshotted scope and the pending findings:

   ```bash
   ALLOWED=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" allowed-files)
   ISSUE_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status | python3 -c "import sys,json; print(json.load(sys.stdin).get('issue_id',''))")
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" list "$ISSUE_ID" --only-pending
   ```

   The list output is JSON: each finding has `id`, `source`, `severity`, `body`, `affected_path`, `out_of_scope`. Show them to the founder one by one. Out-of-scope findings are already filtered from the gate but are still in the list for visibility.

3. Triage each pending in-scope finding using these merge-blocker rules. The disposition is the verb. Use the writer; do NOT hand-edit the JSONL:

   - **accepted** -> correctness bug introduced by this issue's diff. Patch it now in `allowed_files`. After the patch lands, mark accepted (the `resolved_at` stamp is the receipt that the patch happened):

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" set-disposition "$ISSUE_ID" <finding-id> accepted
     ```

     If the patch requires re-running checks, re-run `/issue-verify`. Do NOT auto-relaunch `/issue-review`. The runner's review-rounds cap exists to break loops; you must respect it. The founder opts in if they want another adversarial pass.

   - **deferred** -> valid finding but out of contract for this issue (architectural debt, unchanged-code patterns, follow-up work). Rationale REQUIRED. Optional `--followup-issue-id` if a tracking issue exists:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" set-disposition "$ISSUE_ID" <finding-id> deferred \
       --rationale "tracked for follow-up: applies to all 09 agents, not just this slice"
     ```

   - **rejected** -> Codex misread scope or hallucinated the issue. Rationale REQUIRED:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" set-disposition "$ISSUE_ID" <finding-id> rejected \
       --rationale "codex flagged a config value that is intentionally null; design doc says null disables the feature"
     ```

4. After every pending in-scope finding has a non-pending disposition (the runner's gate counts these), check the count:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" count "$ISSUE_ID" --in-scope-pending
   ```

   Must print `0`. If non-zero, the gate will block close. Re-triage the remaining findings.

5. Mark and close:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" mark findings_triaged
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" close
   ```

   `close` re-runs the gate as a final check (receipts present + zero in-scope pending findings + no invalid dispositions), flips `status: closed` in the spec, and clears the state file. Do not edit the spec or state file manually to bypass it.

6. Produce a final report for the founder:
   - Issue id + title
   - Files changed (git diff summary against `origin/main` for the issue branch or merge commit range)
   - Checks that passed (the `required_checks` list)
   - Review rounds used (from state's `review_rounds`)
   - Triage summary: count of accepted / deferred / rejected, and how many of those were out-of-scope (informational only)
   - Next suggested action (merge, open follow-up issue from any deferred finding's `followup_issue_id`, next issue in queue)

If `close` exits non-zero, the runner names what is missing (receipt or pending finding id). Re-run `status` and `issue_findings.py list --only-pending` and report. Do not edit the spec or state file manually to bypass the gate.

The closeout command never re-runs Codex on its own. If the founder wants another review pass after patches, they explicitly invoke `/issue-review` (which will block at the iteration cap unless `ISSUE_ALLOW_REVIEW_REPEAT=1` is set).
