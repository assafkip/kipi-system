---
description: Run all required_checks for the active issue and record the verified receipt
---

**Autonomy contract.** This step is agent-handled, not founder-gated. Verify automatically once `required_checks` have all exited 0. Record the verified receipt without founder confirmation. The receipt itself is the audit signal: the founder reads it after the fact, not before. Founder-gated steps are still: `/issue-approve`, `/prd-approve`, `/prd-split` commit, and any scope amendment mid-issue. This step is not one of them.

Verify the active DSSE issue. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status`. Confirm an issue is loaded. If `issue_id` is null, stop and tell the founder to run `/issue-start <issue-id>` first.

2. Read the spec's `required_checks` list (already in the status output's loaded spec, or re-load the spec file directly).

3. Run every check in the list, one at a time, from the repo root. For each:
   - Echo the command before running.
   - Run it via `Bash`.
   - Capture exit code and the last ~20 lines of output.

4. If every check exits 0:
   - Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" mark verified`.
   - Report: "verified receipt recorded at <timestamp>."
   - List the checks that ran, one per line.

5. If any check fails:
   - Do NOT call `mark verified`.
   - Report which check failed, its exit code, and the relevant output.
   - Stop. Do not attempt to fix silently. Tell the founder.

Do not run `/codex:review` here. That is `/issue-review`.
Do not edit the spec here. That happens only in `/issue-start` and `/issue-closeout`.
