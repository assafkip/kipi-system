---
description: Run Codex native + adversarial review against the active issue, scoped to allowed_files, capped per kind
---

Run the required reviews for the active DSSE issue. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status`. Confirm an issue is loaded AND `receipts.verified` is set. If `verified` is null, stop. Tell the founder to run `/issue-verify` first. Reviewing unverified code wastes Codex runtime.

2. Pull the snapshotted scope. The runner stamped `allowed_files` into state at load/approve so mid-issue spec edits cannot expand the review surface:

   ```bash
   ALLOWED=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" allowed-files)
   ISSUE_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status | python3 -c "import sys,json; print(json.load(sys.stdin).get('issue_id',''))")
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

   **`$REVIEW_SOURCE` / `$ADVERSARIAL_SOURCE` name the reviewer that actually ran. Never substitute one for another.**

   | Reviewer that ran | `$REVIEW_SOURCE` | `$ADVERSARIAL_SOURCE` |
   |---|---|---|
   | Codex | `codex-review` | `codex-adversarial` |
   | Claude senior-staff-engineer subagent | `claude-review` | `claude-adversarial` |

   Codex is out of credits until 2026-08-24 and Gemini needs auth, so today the reviewer is the Claude subagent and the sources are `claude-*`. Stamping `codex-*` for a pass Codex did not run puts a false provenance record in the findings ledger, which is worse than being blocked in a repo whose thesis is receipts.

   **Immediately pipe the standard-review findings to disk** (compaction hardening: if the conversation compacts after this point, the findings survive because they are on disk, not in narrative memory). Translate Codex's free-form verdict into `[{severity, body, affected_path}]`. The writer assigns sequential ids, stamps `created_at`, marks `out_of_scope=true` for paths outside `$ALLOWED`, and sets `disposition=pending`:

   ```bash
   echo '<JSON_ARRAY>' | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" \
     add "$ISSUE_ID" --source "$REVIEW_SOURCE" --allowed-files-json "$ALLOWED"
   ```

   If the standard review returned approve with no findings, skip the writer call for this source. Do this before invoking the adversarial pass in step 6.

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
   Recurring gap classes: within the scope filter above, also check the diff for these shapes that repeatedly ship past review (report only those the diff actually introduces): an append-only store without compaction + a bounded read in the same change; per-item enrichment before the filter; a breaking response-shape change instead of additive params/header; a persistence path not on a durable mount; a view/UI hide treated as access control (state not enforced at the action endpoint on every reachable path); one helper used for both a gate (must fail closed) and a filter (may fail open); redaction at a boundary that later code augments past; persisting the raw object instead of a redacted projection; masking by appearance instead of by recipient+necessity, or a fix that breaks the core workflow; hiding a thing that buries an open obligation; a new flag/field that does not reach every reader of the store; an overloaded field that changes meaning for existing consumers; check-then-mutate on shared state without one lock (compaction must use a separate stable lock file; guard shared counters); a health endpoint that can 500 on one bad row; a version/identity hardcoded in more than one place; a test that mutates process-global state (env, module globals) without symmetric teardown; a cross-cutting invariant with no written scope or a guard test that enumerates targets from a hand list instead of the system's routes/registries.
   ```

   Same `--base origin/main --background` pattern. Wait for completion. Paste verdict verbatim.

   **Immediately pipe the adversarial-review findings to disk** (same compaction reason as step 4):

   ```bash
   echo '<JSON_ARRAY>' | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_findings.py" \
     add "$ISSUE_ID" --source "$ADVERSARIAL_SOURCE" --allowed-files-json "$ALLOWED"
   ```

   If the adversarial review returned approve with no findings, skip the writer call for this source.

7. If both reviews completed (regardless of verdict, even if findings exist):
   - For EACH review that returned a verdict, record its completion:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" complete-review standard --verdict "<verdict>"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" complete-review adversarial --verdict "<verdict>"
   ```

   `record-review` in step 3 / step 5 only CLAIMED the slot; it writes no
   receipt, because at that moment the reviewer had not run. `complete-review`
   is what writes `reviewed`, and only after a verdict exists to store
   (Codex, PR #110 round 2: the receipt used to land on the slot claim, so an
   interrupted review left a valid-looking receipt).
   - Report: "reviewed receipt recorded at <timestamp>. Findings now belong to `/issue-closeout` triage."

8. If either review failed to complete (Codex error, timeout, parse error):
   - Do NOT call `complete-review` for a review that did not return a verdict.
     Its slot stays claimed and its receipt stays unwritten, which is the
     honest record: the round was spent, the review did not finish.
   - Note: the slot was already claimed in step 3 / step 5. Re-running `/issue-review` will hit the cap. Tell the founder to retry with `ISSUE_ALLOW_REVIEW_REPEAT=1` if the failure was transient.
   - Report the failure mode. Stop.

Do not fix findings in this command. Codex is the reviewer. Triage and disposition happen in `/issue-closeout`. Do not relaunch `/issue-review` on your own initiative; founder must opt in to a repeat round.
