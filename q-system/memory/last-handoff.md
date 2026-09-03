<!-- prompt-only-enforcement-skip: this handoff DESCRIBES state and names the executables
     holding each claim (prompt-audit-ledger.py, fleet-replica-divergence.py, the preflight
     fixture). It asserts no enforcement of its own. -->
# Last handoff

**Session:** 2026-09-02, kipi-system. Prompt audit of the whole instruction surface, then the fleet-divergence work it turned into.

## Where things stand

**Owner of everything open: Sana (the person).** Founder, verbatim: "If anything else needs to be done, it should be done by Sana autonomously." `provenance: explicit_statement`

Handed over as **ASK-1214**, filed into her Linear triage. `[verified: bash q-system/.q-system/scripts/slack-notify.sh "<handoff>" -> alert-to-linear: filed ASK-1214]` She also holds ASK-1212 (merge order) and ASK-1213 (divergence diagnosis). `provenance: imported` from consulting-4d.

**The record lives at repo ROOT, tracked**, not under `q-system/`, because that subtree fans to every instance and this audit is about one repo:
- `audits/prompt-audit-2026-09-02.md` — evidence and paste-ready replacement text per finding `provenance: observed`
- `audits/prompt-audit-2026-09-02-ledger.json` — status per finding, plus a `mandate` block naming scope and rules `provenance: observed`

```
python3 q-system/.q-system/scripts/prompt-audit-ledger.py --render   # rebuild the checklist
python3 q-system/.q-system/scripts/prompt-audit-ledger.py --check    # reds if ledger and report disagree
```
`--check` derives finding ids from the report rather than restating them. Both its branches were mutation-tested.

**111 findings, 22 done, 89 open, 5 of those high.** `[verified: python3 q-system/.q-system/scripts/prompt-audit-ledger.py --check -> "report ids: 80  ledger ids: 111  PASS"]`

## What shipped

Rules and styles via `apply-claude-changes.sh` (ab42cf3c, dd7770bf, f935fb65). Skills, MCP tool descriptions, headless model pins, the compaction hook (240a11db). The shared voice loader, two sessions' edits committed together by agreement (6394fb64). Preflight agent tool allowlist through a newly guarded path (7ac9410e). Audit tracked (bcd2b322). Divergence detector built (7c5df122) and **armed into the updater preflight** (94b3fa68).

## Read this before touching the fleet updater

`kipi update` now aborts on replica divergence, and it aborts **today**.

`[verified: python3 q-system/.q-system/scripts/fleet-replica-divergence.py -> exit 1, "fleet replica divergence: DIVERGED 1/3 path(s)", odd copy /Users/assafkipnis/projects/consulting]`

`[verified: bash q-system/.q-system/scripts/test/test-kipi-update-replica-divergence-preflight.sh -> exit 0; runs the real updater against a synthetic fleet; divergence aborts, deleted/zero-byte/comment-only gate each abort, agreeing replicas continue]`

`[verified: python3 q-system/.q-system/scripts/fleet-replica-divergence.py --claim "only:two" -> exit 3, "REFUSED (1 claim(s) requested, 0 evaluable)"]` — a malformed spec fails closed rather than reporting green.

**Why it matters:** the consulting instance holds `_reject_unrunnable_gate`, the fleet's only copy, and an update run would delete it. That function is the sole enforcer of the lesson `a-gate-that-cannot-run-must-not-pass`. `[verified: scratchpad lesson_vs_code.py over instance-registry.json -> lesson file in 26 of 27 roots, enforcer in 1 of 26 copies]`

Replica half blocks. Claim half is deliberately **not** wired: 26 roots hold the lesson and 1 holds the enforcer, so blocking on a months-long backlog is how a gate gets switched off. Flip it on when the enforcer ships to the skeleton. `provenance: explicit_statement` (agent run's stated reasoning, reviewed here).

**Nothing protects main yet.** `origin/main` carries no reference to the gate; this branch is 65 ahead. `provenance: imported` (agent run; not re-measured here). Branch is 22 behind main `[verified: git rev-list --count HEAD..origin/main -> 22]`. `sp-5e988721` stays open, correctly.

## Open highs

- **P-1** `no-orphan-findings.md` promises `gates run` fails while any item is open; the runner blocks only on blocker/major/high and `spillover add` defaults to minor. `[verified: grep SPILLOVER_BLOCKING_SEVERITIES plugins/prd-os/scripts/prd_runner.py; gates run -> "[REPORT] 1,109 open minor-or-untriaged item(s), not blocking"]`
- **P-2** That constant is defined twice at module level with different values; the later wins. `[verified: python3 -c "import prd_runner; print(prd_runner.SPILLOVER_BLOCKING_SEVERITIES)" -> ('blocker','major','high')]`
- **P-3** `prd_runner.py` diverged in 1 of 26 instances. `[verified: scratchpad plugin_drift.py -> 25 identical at 2877L, ASK_AI_consultant at 3050L]` Strictly ahead and committed at 7393e170, so recoverable. `provenance: imported`.
- **P-4** A fleet lesson travels further than the code enforcing it. `[verified: scratchpad lesson_vs_code.py -> lesson file present in 26 of 27 roots, _reject_unrunnable_gate present in 1 of 26 copies]`
- **P-5** Spillover owner-routing exists in 1 of 26 copies, so 25 instances file blocking items with no owner and no ticket. `[verified: scratchpad lesson_vs_code.py -> DEFAULT_SPILLOVER_OWNER present in 1 of 26]`
- **P-7** The detector is armed on this branch only.

## Method notes worth carrying

Every real catch today came from **two accounts of the same artifact disagreeing**, not from anyone being more careful. Seven instances, including two sessions quoting different line numbers for one constant, which is what exposed the fleet plugin drift. The detector exists to produce that second account mechanically. `provenance: observed`

Three traps hit repeatedly this session:

- **A check can pass for the wrong reason.** My abuse probes against the new write guard were refused twice by a schema parser before reaching any guard, and both refusals read as green. Only the third attempt tested anything.
- **`.claude/` hand-edits get reverted** by `claude-integrity-tripwire.py --enforce` on the next tool call, AFTER the writing script prints success. Edit and commit must be one action, or go through `apply-claude-changes.sh`. Cost two sessions an hour each.
- **State the absolute path with any size or count.** Three sessions measured four different files named `MEMORY.md` and reported three different numbers. Nobody was wrong; everyone was underspecified.

## Uncommitted, other sessions' work, left alone

`browser_session.py`, `capability_manifest.py`, `test_browser_session.py`, `test_destructive_op_mcp_namespace.py` (7 failures, pre-existing), `fix-perm-wildcards.py`, `mcp-denylist-namespace-check.py`. `provenance: observed`
