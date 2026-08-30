# Session handoff, Aug 23 evening [verified: date]. READ THIS FIRST.

## State

Two Sana sessions have run on the spillover queue. Blocking items: 43 -> 36
(35 original + sp-a7846d3d filed this session). Census 963 open.

Landed on origin/main (all merged, CI green):
- PR #246: ASK-975/976/977/984/985 stack (bypass_check runs at close, digest
  parser, guard reader stages, uv-collectible suite). Resolved sp-50db1764,
  sp-0cf100b3, sp-b82fda60, sp-8804dee7, sp-7e42845e, sp-dcd84af1; voided
  sp-eea17567, sp-d120853a, sp-ca9351e4, sp-4c0b19ba.
- PR #247: ASK-988 / sp-4c5a00f3 (crtc-test-manifest check commands point at
  the harness entrypoint). Also shipped: receipts.jsonl gained `reopened_at`
  (allowlist + ISO contract), accept-rate.load_receipts and prd_runner's
  archive coverage now resolve state by parsed event timestamp with
  same-second ties going to REOPEN. Pinned in
  q-system/.q-system/scripts/test/test-accept-rate-receipts.py (manifest-declared).
- crtc-test-manifest itself is REOPENED (status: open in its spec): the
  enumeration deliverable is NOT done. Do not re-close it for check-command
  work.

## Next pick (Sana's call, but the recon is done)

sp-a7846d3d is the natural next item: capability-manifest.json does not
enumerate plugin tests (65+ files under plugins/*/tests; manifest references
plugins/ only 12 times) and gate scan scope excludes plugin test discovery.
This is the defect class that makes other verdicts untrustworthy.

Recon notes for sp-32b3438d (audit --dry-run), measured this session:
- The flag already exists: prd_runner.py spillover promoted-audit --dry-run
  ("report only; write nothing", parser line ~2824).
- Under --dry-run it still queries Linear read-only, prints WOULD RESOLVE,
  and keeps the SAME exit-code contract (1 on transport failure or fully-blind
  sweep). See _spillover_promoted_audit, lines ~2160-2243.
- The fix is one argv element in fleet-health-daily.py detect_promoted_audit
  (~line 1542): append "--dry-run" to the subprocess.run list.
- RED first via a source-inspection check appended to
  q-system/.q-system/scripts/test/test-fleet-health-daily.py (house style:
  main()-based check() helpers, inspect.getsource assertion like line ~141).

## Mechanics that burned time this session (do not rediscover)

- Landing: main is protected. Branch off fresh origin/main, PR, then BOTH
  required checks: `validate` (CI, ~12 min) and `kipi/reviewer-approved`
  (posted by q-system/.q-system/scripts/pr-review-agent.sh <pr> --engine
  codex --post). Reviewer takes ~9 min; timeout of YOUR shell does not mean
  it failed - check the commit status before assuming anything.
- Codex review rounds are real: r1-r6 on PR #247 each found a legitimate
  defect. Fix, do not argue. Expect findings about: parent PRDs retaining
  what generated specs fixed, receipts/metrics consistency when reopening,
  union-merge row ordering, UTC-offset timestamps, same-second ties.
- Every commit touching plugins/** needs a version bump IN THAT COMMIT
  (plugin-version-bump gate compares per-commit vs HEAD).
- Commit messages need an ASK-nn reference or [no-issue: reason]
  (linear-issue-ref hook blocks otherwise).
- receipts.jsonl has a CLOSED key allowlist (receipts-ledger-check.py,
  ALLOWED_KEYS); reopen rows use reopened_at + issue_id + prd_id +
  finding_id + commit_sha. No free text; it ships to a PUBLIC repo.
- New test files must be declared in q-system/.q-system/capability-manifest.json
  ({path, runner}) or the capability gate goes undeclared-artifact RED.
- kipi-mcp tests run under `uv run pytest tests/` from plugins/kipi-core/kipi-mcp.
- Subagent dispatch was broken all session at the provider level
  (network_error / instant cancel) while four other opencode sessions ran.
  If dispatch dies instantly again, execute inline rather than retrying.

## Standing rules that decided everything today

Reproducer first, RED before GREEN. Never trust a green you have not seen go
red. Verify against the installed clone the server actually starts. Quote the
tool line and sha next to any verdict. Anything real found and not fixed goes
to spillover add. Engineering calls belong to Sana; publish/spend/delete stay
with the founder. Pull or rebase, never reset.
