---
description: Load a DSSE issue spec and begin structured work
argument-hint: <issue-id>
---

You are starting a DSSE issue. The issue id is: $ARGUMENTS

Execute the following, in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" load $ARGUMENTS`. The output is JSON describing the loaded spec. If the command exits non-zero, stop and report the error. Do not invent an issue spec.

2. Read the full spec file at the `spec_path` returned by step 1.

3. Present a plan to the founder:
   - One line summarizing the title and priority.
   - The full `allowed_files` list exactly as loaded. State explicitly: "all edits must target one of these paths."
   - The full `required_checks` list. State: "these must all exit 0 before `/issue-verify` will record the verified receipt."
   - The full `required_reviews` list.
   - The first concrete change you plan to make, in one sentence.

4. Wait for the founder to approve the plan or redirect. Do not flip the spec status and do not start editing until they confirm.

5. On approval, run `/issue-approve`. That command flips the spec status from `open` to `in-progress` and arms the stop-time gate. Planning before this step is intentionally gate-exempt so a loaded spec does not spam the Stop hook while the plan is being reviewed.

Rules while the issue is loaded:
- Every edit you make must target a path that matches `allowed_files`.
- The PreToolUse scope hook will block out-of-scope edits automatically.
- Do not mark the issue verified, reviewed, or closed yourself. Use `/issue-verify`, `/issue-review`, `/issue-closeout`.
- If you discover mid-issue that the scope is wrong, update the spec file's `allowed_files` first, explain why, then continue.
