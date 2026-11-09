# RCA: PR #668 reached round 3 and round 3 still found a permanent comment posted twice

**Date:** 2026-11-09
**Trigger:** round-3 delta review of PR #668 (ASK-3960), `798279fb..0840df26`, verdict REQUEST CHANGES. Review: `~/.config/kipi/pr-reviews/assafkip_kipi-system__pr-668-20261109-102226.md`
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

PR #668 gives an unprobeable `blocked:capability` ticket a route at day 14 (`capability_block_expiry.py route_unprobeable`). Round 1 raised 3 findings plus 3 from Codex. Round 2 raised 4. Round 3 raised 3 more. Round 2's major 2 named one site that posts a permanent Linear comment with no exactly-once gate, the claude-write route. Commit 0840df26 gated that site on `claim-flag`. Round 3 found the same defect at the next site down, the credential route.

## Surface symptom

Round 3, finding 1, the reviewer's two-process repro (one credential park, the founder's ask resolved):

```
unprobeable credential; the founder answered ASK-900:abc: unblocked and requeued
unprobeable credential; the founder answered ASK-900:abc: unblocked and requeued
permanent progress comments posted: 2
requeues: 2
```

Also in round 3:
- finding 2 (major, nonblocking): a `cap-ladder.py --resolve` run from an agent shell (`resolved_ctx.agent_env: ['CLAUDECODE']`, `resolved_by: unnamed`) reads as the founder's answer and un-parks the ticket.
- finding 3 (minor): with no readable `cap-ladder.py`, `ladder_const("DEAD_TYPES")` is None, the closed-ticket guard reads `or ()`, and a completed ticket gets the full claude-write route and comment.

## Surface root cause

`capability_block_expiry.py:511-516`. The credential branch unblocks, checks `_landed(urc)`, then posts. `_landed()` accepts both 0 and linear-sync's `EXIT_NOOP` (another run already removed the label), so the run that lost the race still posts the note. 0840df26 put the exactly-once gate on the claude-write branch only (`:472-495`).

## Structural root cause

### Root cause #1: each round repaired the site it was shown, not the class

type: process

Round 2 finding 2 described a class: a permanent write gated on something that is not an exactly-once verdict. The fix brief even said "before any permanent write". The round-2 fix enumerated one site, the one the reviewer reproduced. Measured on 0840df26:

```
$ grep -n '_sync("progress"' capability_block_expiry.py
495   claude-write route   gated on claim-flag exit 0 (fixed in 0840df26)
516   credential route     gated on _landed() (0 or EXIT_NOOP), NOT exactly-once
992   clear_block          gated on unblock exit 0 (has been right since PR #77)
```

Three sites, one fixed. The red-first test was built from the reviewer's repro (a claude-write park), so it proved that site and said nothing about the next one. The delta review then sees each fix and its neighbours, which surfaces the class one site per round. The same shape is recorded in `rca-founder-ask-outlives-ticket-three-rounds-2026-11-09.md` (per-path fixes of one ask lifecycle) and in the reviewer note `feedback_same_finding_twice_go_structural`.

### Root cause #2: no single chokepoint for "unblock, then the permanent note"

type: code-defect

Three paths each run unblock, decide whether to post, then requeue. `clear_block` gates on exit 0 and carries the scar comment for exactly this race (PR #77 round 3). The round-1 fix (bc55b0c0) added `_landed()` for the two route branches and re-collapsed the two success codes that `_sync`'s own docstring says must stay apart. With the rule held in three places, it drifted in one.

### Root cause #3: fallback direction picked per call, not from the file's rule

type: implicit-contract

The file's header rule is "FAIL CLOSED, ALWAYS: every ambiguity leaves the block alone". Round 2 added two reads of cap-ladder.py constants. `answered()` fails closed when `JOB` is unreadable (no answer counts). The closed-ticket guard fails open when `DEAD_TYPES` is unreadable (`or ()` means nothing is closed). Same input, opposite directions. The same habit set `answered()`'s trust as a denylist (skip rows the ladder stamped) when cap-ladder already records `resolved_ctx` for the question "who resolved this".

## Verification

- Round 3 reproduced finding 1 at 0840df26 with two real processes: 2 permanent comments, 2 requeues (review file above).
- Round 3 confirmed the round-2 fixes against the pre-delta module: a two-line sentinel was `unknown` and is now `credential`; the first-sight race kept only ASK-802 and now keeps both.
- At 0840df26, with KIPI_TEST=1: `test_capability_route.py` 40 ok, 0 failed (red at 798279fb: 10 of 16 new checks failed; 2 mutants red as required); `test-capability-block-expiry.sh` 61 passed; `test_linear_sync_permanence.py` 5 passed; `test_cap_ladder.py` 107 ok.
- The round-3 findings are NOT fixed in this lane. Their fix and its verification are the first action items below.

## Contributing factors

- The round-2 brief named the claude-write site's line numbers. The class wording was in the same sentence, and the fix followed the line numbers.
- Round-2 recon weighed gating on unblock exit 0 and kept `_landed()` as a round-1 decision, without reading why bc55b0c0 introduced it.
- Delta reviews are scoped to new commits, so a class spread over untouched sites is found one site per round.
- Finding 2's policy (who may answer a founder ask) is channel-wide: cap-ladder's own `ask_resolved()` trusts every resolve the same way. It cannot be settled inside this diff alone.

## Fixes shipped

- Surface fix: pending. Owned by the fresh Sana agent below; this lane stopped at round 3 by rule.
- Structural fix: pending. One chokepoint for unblock-then-note (action 1) plus a site table the test checks against (action 2).

## Recurrence

- rca-founder-ask-outlives-ticket-three-rounds-2026-11-09.md: its action "One reconcile keyed on open asks (`sweep_dead_asks`), red-first" held for the ask lifecycle, but it was scoped to that object. Nothing carried "one owner per class" to this file's permanent-note sites, so per-site repair recurred here. And that reconcile's own output, a row resolved as moot, is what round 2's major 1 found `answered()` misreading: a new writer to the status file changed what `resolved` means for a reader in another PR.

## Action items

- [ ] Route every permanent note through one helper used by `clear_block`, the claude-write route and the credential route: post and requeue only when unblock exits 0 (this run removed the label); EXIT_NOOP posts nothing. Keep `claim-flag` as the claude-write one-shot record; owner: fresh Sana agent the orchestrator starts from this RCA; type: code
- [ ] One two-process race case per permanent-note site, driven from one table, plus a check that the count of `_sync("progress"` sites equals the table length, so a new site without a race case goes red; owner: same fresh Sana agent; type: test
- [ ] Closed-ticket guard fails closed: when `DEAD_TYPES` is unreadable, route nothing and print why; owner: same fresh Sana agent; type: code
- [ ] Decide finding 2's policy (does a resolve whose `resolved_ctx.agent_env` is non-empty count as the founder's answer), record the decision and reason in cap-ladder.py and `answered()`, pin it with a test through the real writer. Nonblocking for #668; if it does not land in #668, the same agent files it as an owner:sana Linear issue for the fleet worker; owner: same fresh Sana agent; type: code
- [ ] Round 4 delta review of PR #668 from the pinned checkout, merge on APPROVE with validate green, install `com.kipi.capability-expiry`, kickstart it, read `~/.config/kipi/capability-expiry.out`; owner: same fresh Sana agent; type: process
- [ ] Before fixing a finding, grep the file for every site of the finding's class and list the sites in the commit message; owner: every Sana lane, starting with the fresh agent's round-3 fix commit; type: process

## Lessons

- "Before any permanent write" is a class. Grep every permanent write in the file before fixing the one in the repro.
- When the reviewer's cheapest fix is one condition, check whether the same condition is missing at its siblings.
- A fallback's direction comes from the file's header rule. Here that rule is fail closed for anything that un-parks.
