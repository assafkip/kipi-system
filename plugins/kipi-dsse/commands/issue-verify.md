---
description: Run all required_checks for the active issue and record the verified receipt
---

**Autonomy contract.** This step is agent-handled, not founder-gated. Verify automatically once `required_checks` have all exited 0. Record the verified receipt without founder confirmation. The receipt itself is the audit signal: the founder reads it after the fact, not before. Founder-gated steps are still: `/issue-approve`, `/prd-approve`, `/prd-split` commit, and any scope amendment mid-issue. This step is not one of them.

Verify the active DSSE issue. Execute in order:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" status`. Confirm an issue is loaded. If `issue_id` is null, stop and tell the founder to run `/issue-start <issue-id>` first.

2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py" verify`.

   This ONE command is the whole step. It runs every check in the spec
   snapshot itself, records each check's exit code and an output hash as
   evidence, and writes the verified receipt only if all of them exit 0.

   Do NOT run the checks by hand first. `verify` runs them from the snapshot
   taken at `/issue-start`, which is the thing the receipt attests to; a check
   you ran yourself from the live spec can differ from that snapshot, and the
   receipt would then describe a run nobody made. There is no way to record
   this receipt without running the checks -- `mark verified` refuses by
   design (ASK-402).

   An issue loaded after ASK-1810 (its state carries `"verify_contract": 2`)
   gets more from the same command, all computed by `verify` and sealed into
   the receipt, never typed:
   - a check that runs the full suite (`verify.sh --full`, bare `pytest`,
     `kipi check`) is refused before anything runs; CI runs it once per PR;
   - `real_path`: which of the issue's non-test `.py` files each check ran at
     its tracked path, seen by `real_path_observer/sitecustomize.py`; a check
     that only runs a copy is refused;
   - `defined_vs_ran`: test functions in each named Python test file, from the
     AST, against the runner's own count; hidden tests are refused;
   - `repeats`: the checks rerun up to 10 times inside a 20-minute budget,
     refused below 5 runs or on any red run.

3. If `verify` exits 0:
   - Report: "verified receipt recorded at <timestamp>."
   - Read `checks` from its JSON output and list them, one per line
     (`checks_run` is the count).
   - Under contract 2, also paste `real_path`, `defined_vs_ran` and `repeats`
     from the same JSON. These are the closeout numbers; do not restate them
     from memory.

4. If `verify` exits 2:
   - It already printed which check failed and its exit code. Report that.
   - The evidence is stored even on a red run; the receipt is withheld.
   - An empty `required_checks` list also exits 2. That is not a passing
     issue, it is a spec with nothing to attest to: tell the founder to add a
     check or amend the spec.
   - Stop. Do not attempt to fix silently. Tell the founder.

Do not run `/codex:review` here. That is `/issue-review`.
Do not edit the spec here. That happens only in `/issue-start` and `/issue-closeout`.
