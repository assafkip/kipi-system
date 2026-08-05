# Plan: fleet-wide Fable escalation ("when Opus is stuck, a different model triages")

> **Recovered work-product — a point-in-time snapshot, not current documentation.**
> This file existed only in a dirty checkout and was recovered on 2026-08-05
> (PR #106, ASK-363). Every claim about system state was true at this document's
> own date and may not be true now. In particular, "wired" here means *merged in
> this repository*; whether the RUNNING copy loads it is a separate question that
> `q-system/.q-system/scripts/runtime-plugin-freshness.py` answers, because the
> two came apart for a full day during this very build. Read it as a record of
> what was decided and why, and verify current state against the code.

**Date:** 2026-08-02
**Requested by:** founder, 2026-08-02
**Owner:** Sana (both open engineering decisions are hers, see "Open decisions")
**Status:** research complete, design fork open, nothing built

## What / why

Today `q-system/.q-system/token-guard.py` has exactly two outcomes when Opus
loops: `block()` (exit 2, stop) or `warn()` (exit 0, keep going). Read its
`main()` — every one of the 11 checks lands on one of those two. Neither outcome
changes the *reasoning distribution*, so a pattern that deadlocks Opus deadlocks
it again on the next attempt.

This plan specifies a third outcome: hand the situation to Fable in a **fresh
session** for triage, analysis, and a proposed next path, then come back. Same
applies when the founder has asked the same thing repeatedly, or when the
direction itself is uncertain.

Fable is not the implementer here. Fable is the triage lens. Opus keeps the work.

## Grounding: Fable is reachable (verified 2026-08-02)

```
$ claude -p --model claude-fable-5 "reply with exactly: FABLE_OK"
FABLE_OK
```

Two call paths exist: headless `claude -p --model claude-fable-5` (works from a
script, works in a launchd job) and in-session `Agent(model: "fable")` (fresh
context by construction, no shared history).

## Why a DIFFERENT model and not "Opus tries harder"

From the literature sweep (2026-08-02):

Findings, each paired with the executable in this repo that would carry it (a
finding with no named executable is a note, not a design input):

| Finding | Source | Executable that carries it here |
|---|---|---|
| Different LLMs have complementary failure distributions; a pattern that deadlocks one model often sits outside the other's failure mode, so cross-model escalation breaks cycles same-model retries cannot | [Act or Escalate, arXiv:2604.08588](https://arxiv.org/pdf/2604.08588) | `fable-escalate.py` (new) — the only caller of `claude -p --model claude-fable-5` |
| A critic runs in a fresh session with no shared history, fed only spec + evidence + diff; a critic inside the originating context inherits its framing | [cross-model adversarial review](https://codex.danielvaughan.com/2026/03/28/cross-model-adversarial-review/) | `fable-escalate.py` builds the packet; a test asserts the subprocess receives no transcript |
| Progress detection and stop rules sit outside the model | [multi-model convergence](https://zylos.ai/research/2026-03-01-multi-model-ai-code-review-convergence/) | `q-system/.q-system/token-guard.py`, already live: 6 coded detectors, PreToolUse exit 2 |
| Cap escalations, then route to a human | same | escalation counter in `fable-escalate.py` + `slack-notify.sh` at the cap |

The third row is the load-bearing one: `token-guard.py` is already the
outside-the-model progress detector this fleet needs. Its 6 detectors all
terminate in "stop and tell the founder" today. The escalation is a missing
branch on an existing gate, not a new gate.

## The menu: when to call Fable

### Tier A — deterministic, a detector already fires today

Every one of these is already coded in `q-system/.q-system/token-guard.py`. No
new detection work; the work is adding the escalation branch.

| # | Trigger | Existing enforcer |
|---|---------|-------------------|
| A1 | Exact retry x3 (same tool + same input) | `check_exact_retry`, `RETRY_LIMIT=3` |
| A2 | Edit spiral x3 on one file | `check_edit_spiral`, `EDIT_FAIL_LIMIT=3` |
| A3 | Time stall: 120s + 10 calls, no write | `check_time_stall`, `STALL_TIME_SECONDS=120` |
| A4 | Read spiral 15 / grep drift 5 (exploring, not producing) | `check_read_spiral`, `check_grep_drift` |
| A5 | Agents spawned with no output | `check_agent_no_output` |
| A6 | Volume ceiling 50 calls since last user message | `check_volume`, `VOLUME_CEILING=50` |

Two more deterministic triggers exist outside token-guard:

| # | Trigger | Existing enforcer |
|---|---------|-------------------|
| A7 | A phased-job step exhausts its 3 attempts | `.claude/rules/self-healing-retry.md` rule 4 |
| A8 | A bounded verification loop hits its 3-pass cap still red | CLAUDE.md bounded-loop contract |

### Tier B — the founder repeated themselves

Not currently detected anywhere. This is the signal the founder named first
("I've been asking the same thing over and over").

| # | Trigger |
|---|---------|
| B1 | Same substantive ask 2+ times in a session |
| B2 | "why did you stop" / "why do you keep" / "I already told you" |
| B3 | "that's wrong" / "no" twice on the same artifact |

Scar backing B1/B2: the autonomy-contract entry in the founder's global
CLAUDE.md records the founder pushing back **multiple times in one session** on
the same behavior, and the fix reached for was more hook patches. That note
itself concludes "hooks are the wrong layer for this... each round you find a new
surface." A repeated founder ask is the highest-signal stuck indicator in the
system and nothing consumes it.

### Tier C — epistemic, derived from this repo's own RCAs

Judgment calls. Each is a real, dated failure in `q-system/output/rca/`.

| # | Trigger | Source RCA | What Fable is asked for |
|---|---------|-----------|------------------------|
| C1 | About to report that something IS happening / HAS failed, based on a file artifact rather than an observation | `rca-specification-reported-as-state-2026-08-02.md` — 9 false claims in ONE session, each refuted by a command available the whole time | Name the command that would refute this claim, before it is spoken |
| C2 | Two sides derive one logical value from different sources; all tests green | `rca-autocapture-session-id-disconnect-2026-07-04.md` — producer read `CLAUDE_SESSION_ID`, consumer read the stdin payload; feature shipped live-but-inert with every gate green | Find the derivation path no test exercises |
| C3 | Edited a file and cannot prove the running system loads *that* copy | `rca-derived-copy-drift-2026-06-30.md` — 5 of 6 open spillover items were one class: a truth with multiple stored representations and no check that they agree | Identify which copy actually runs |
| C4 | A test passes but the fixture was invented rather than produced | memory `feedback_fixtures_from_producers` — two green-but-wrong tests shipped in one day, both caught by mutation, neither by review | Mutate the code; does the test still pass |
| C5 | 2+ plausible approaches, no evidence to choose between them | `.claude/rules/quick-plan.md` name-options rule | Triage and rank, do not implement |

C1 deserves emphasis: that RCA is dated **today**. Its structural root cause is
"the cheap check and the correct check are different checks, and only the cheap
one is one keystroke away." A Fable call is a way to make the correct check cheap.

### What Fable returns (proposed contract)

Not a fix. A triage packet:

1. **Diagnosis** — what is actually blocking, stated as a falsifiable claim
2. **What to stop doing** — the approach that is looping, named
3. **Next path** — one concrete action, with the command or file that proves it
4. **The refuting check** — what would show this diagnosis is wrong

## Open decisions (Sana's, not the founder's)

The founder was asked both and routed both to Sana. Sana researches and decides.

### Decision 1: trigger mode for Tier A

- **(a) Advisory** — token-guard's block message gains `run fable-escalate.py
  --trigger edit-spiral`. Cheap, no latency in the hook, no hang risk. Weakness:
  prompt-only at the moment of use, the failure class `skill-hook-pairing.md`
  calls "an aspiration".
- **(b) Automatic** — the hook shells Fable synchronously and returns the triage
  AS the block message. Cannot be skipped. Weakness: a 20-60s network call inside
  a PreToolUse hook; a hang freezes the session, and the hook has no session
  transcript so the packet it can assemble is thin.
- **(c) Hybrid** — auto on the blocking detectors, advisory on the warning
  detectors. Splits the risk, doubles the code paths to test.

Prior art to weigh: the `a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too`
lesson (a fail-closed hook whose own dependency is missing blocks the repair
too), and token-guard's own history of a warn tier that was silently invisible
for weeks because the JSON shape was wrong.

### Decision 2: what holds Tier C

- **(a) Rule + trigger-eval fixtures** — `.claude/rules/fable-escalation.md`
  plus a fixture set in `q-system/.q-system/skill-evals/`, run advisorily by
  `skill-trigger-eval.py`. Exactly how the fleet already handles interpretive
  auto-invoked skills (founder-voice, rca, fable-discipline). Measures whether it
  fires; does not force it.
- **(b) Rule only** — accept Tier C is prompt-only, ship faster, no firing signal.
- **(c) Add a Stop-hook claim scanner for C1** — scan the final message for state
  assertions with no observation command in the turn. Directly targets today's
  RCA. Real detector work, high false-positive risk; likely its own issue.

## Files likely to touch

- `q-system/.q-system/scripts/fable-escalate.py` — new, the single chokepoint
- `q-system/.q-system/token-guard.py` — escalation branch on the stuck detectors
- `.claude/rules/fable-escalation.md` — new, carries the menu (propagates fleet-wide)
- `.claude/settings.json` + `settings-template.json` — if any new hook is wired
  (`settings-template-sync-check.py` blocks a one-sided wiring)
- `q-system/.q-system/skill-evals/fable-escalation.json` — if decision 2 = (a)
- `q-system/output/fable-escalations/` — the ledger destination
- `q-system/lessons/` — one lessons entry (detect-act-learn triad)

## Acceptance criteria

- [ ] A reproducer drives a Tier-A stuck state and shows the escalation firing.
      Show it failing before the fix.
- [ ] The Fable call runs in a **fresh session** — proven, not asserted (the
      packet contains only what was passed in)
- [ ] The escalation is **logged**, one JSONL row per call: trigger, packet hash,
      Fable's diagnosis, whether the next path was taken
- [ ] There is a **cap**: N escalations per session, then stop and surface to the
      founder. Cross-model is a step before the human, not instead of one
- [ ] A failed / timed-out Fable call **degrades to current behavior** (plain
      block), never to a hang
- [ ] `.claude/rules/fable-escalation.md` reaches instances — `kipi update --dry`
      confirms propagation
- [ ] Capability manifest entry + test, per `project_capability_gate`
- [ ] One `q-system/lessons/` entry (detect-act-learn triad: detector + logged
      automated action + lesson)
- [ ] `python3 plugins/prd-os/scripts/prd_runner.py gates run` exits 0

## Patterns to follow (from this repo, not generic advice)

- `token-guard.py`'s `warn()` / `block()` exit-code contract, and its
  `uncount_blocked_attempt` care about not corrupting counters on a blocked call
- `slack-notify.sh` as the only founder-ping channel (`founder-notifications.md`)
- The lint convention in `skill-hook-pairing.md`: self-scope early, fast-exit
  out-of-scope, header comment naming its pair
- `self-healing-retry.md`'s cause taxonomy (`environmental-trigger` vs
  `latent-defect`) — escalating on an environmental failure is waste; stop on
  attempt 1 there
- `evidence-ledger.md`: a Fable diagnosis is an inference until a command backs
  it. It gets stored labelled, not as a measurement.

## Anti-goal

This is not "route hard work to Fable." Opus keeps the work. Fable gets the
situation packet when Opus has demonstrably stopped making progress, and returns
a direction. If this drifts into general-purpose offload, the loop-health metric
in `loop-exits.md` (cost per accepted change) is where that shows up.
