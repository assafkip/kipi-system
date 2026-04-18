---
description: Approve the planned DSSE issue and transition it from open to in-progress
---

Approve the active DSSE issue after the founder has signed off on the plan. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" approve`. This reads the active issue spec, confirms its status is currently `open`, and flips it to `in-progress`. The command writes the spec directly — do not use the `Edit` tool for this.

2. If approve exits non-zero:
   - No active issue: tell the founder to run `/issue-start <issue-id>` first.
   - Status already in-progress: safe to proceed, the runner is idempotent on re-approval.
   - Any other error: report it verbatim. Do not edit the spec manually to work around it.

3. Confirm in one line: "Issue $ISSUE_ID is now in-progress. Stop-time gate is armed."

After approval, proceed with the first concrete change from the plan. All edits must target `allowed_files`. Normal DSSE flow resumes: `/issue-verify`, `/issue-review`, `/issue-closeout`.
