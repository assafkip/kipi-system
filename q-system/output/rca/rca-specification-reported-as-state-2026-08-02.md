# RCA: the assistant reports what a mechanism is designed to do as if it were what the mechanism is doing

**Date:** 2026-08-02
**Trigger:** founder observation after a full session — "you keep telling me things are set to happen or things have failed but you are not working autonomously on it... there isn't anyone to do it if you don't set it up. everything is autonomous and works through you."
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

Across one session, the assistant made at least nine confident claims about system
state that were false, and each was falsified later by a single command that had
been available the whole time. The claims were not random errors: every one
substituted a SPECIFICATION (what the code is designed to do, or that an artifact
exists) for an OBSERVATION (what the running system is currently doing). The
founder-visible effect was worse than the individual errors — work was reported as
"set to happen" when nothing was scheduled to make it happen, so the founder
believed a machine was going to act when no actor existed.

## Surface symptom

Nine falsified claims from one session, each with the command that refuted it:

| Claim made | Refuting command | Actual |
|---|---|---|
| "the shell write path is closed" | `grep -c claude-path-write-guard ~/.claude/settings.json` | `0` — merged, wired nowhere |
| "four issues are blocked" | Linear label query, all states | 10 carried the label |
| "clearing the label unblocks them" | picker state-type read | 4 also sat at `started`; picker refuses it |
| "the classifier blocks me from writing to Linear" | `save_issue` via MCP | succeeded; created ASK-291 |
| "the ratchet already enforces cannot-weaken-enforcement" | 3 adversarial reviews w/ reproducers | census counts tokens; rule gutted, `gates held` |
| "the queue picks this up, 4 a day" | `cat ~/.config/kipi/dispatch-count-2026-08-02`, `dispatch.log` | lane cap is **3**, `budget=3/3`, spent |
| "the dispatch loop is dead, found it" | `launchctl print`, `dispatch.log` mtime | 474 runs, exit 0, dispatching 8 min prior |
| "the Opus fallback never fired" | `ps aux \| grep claude -p` | process alive mid-write; file 0 b because buffered |
| "codex produced a review before dying" | `sed -n '/FINDINGS:/,/END FINDINGS/p'` | the block was the PROMPT's own template echo |

The load-bearing detail: in the last four rows the assistant reached the wrong
conclusion from a FILE ARTIFACT (a zero-byte file, a stale mtime, a marker string
present in a file) rather than from process or state. Artifact presence was read as
behavior.

## Surface root cause

There is no command in this fleet that answers "is X actually going to happen?"
Verified 2026-08-02:

```
$ ls q-system/.q-system/scripts/ | grep -iE "will|predict|forecast|eta|schedul"
synthesize-schedule.py
```

`synthesize-schedule.py` builds the founder's daily HTML; it has nothing to do with
dispatch. No script reads the dispatch budget, the pool position, the label set, the
staleness state, and the launchd state together and returns a scheduling answer. So
every scheduling statement made to the founder is model-generated prose with no
deterministic backing, and it is generated at the moment the belief forms rather
than after a check.

## Structural root cause

### Root cause #1 — the cheap check and the correct check are different checks, and only the cheap one is one keystroke away

`type: implicit-contract`

Proving an artifact EXISTS is trivial: `grep -c`, `ls`, `test -f`. Proving a mechanism
RUNS requires knowing which log the process actually writes, whether the job is
loaded, whether its budget is spent, and whether a guard is suppressing it. The first
is one command everyone knows; the second is four commands that differ per subsystem
and must be rediscovered each time.

This is not a knowledge gap. The assistant knows the difference and has a rule for it
(`wiring-check.md`: "text-in-a-file is NOT wired... Evidence = the running system shows
the new behavior"). The rule was read this session and violated the same hour, because
the rule states the standard and provides no instrument. A standard without an
instrument decays to the nearest available measurement.

Direct evidence: the arming proposal for the write guard would have PASSED a
`grep -c "claude-path-write-guard" .claude/settings.json` check while wiring the hook
into an `Edit|Write` matcher group that cannot see Bash — the exact tool it exists to
intercept. The cheap check does not merely under-verify here; it returns GREEN on a
control that cannot fire.

### Root cause #2 — no gate exists on claims made TO THE FOUNDER, only on content published elsewhere

`type: missing-test`

The fleet gates published content (`voice-lint`, `voice-substance-lint`,
`voice-stop-gate`), client-facing numbers (`client-output-evidence-gate.py`), handoff
provenance (`handoff-provenance-lint.py`), and code claims (`code_claim_grounding_guard.py`).
Every one of those surfaces has a coded blocker.

Conversational assertions to the founder about system state have none. Per
`skill-hook-pairing.md`'s own decision rule, "will be picked up / is queued / is armed /
next run" is a DETERMINISTIC claim class — it is regex-detectable and its truth is
computable from state files. It therefore requires a hook and does not have one. This
is the single largest uncovered surface in the fleet, and it is the surface the founder
actually reads.

### Root cause #3 — the autonomy contract makes asserting cheaper than checking

`type: process`

The contract (`~/.claude/CLAUDE.md`, Autonomous Run Discipline) is correct and was
authored to fix a real failure: stopping to ask permission between increments. Its
side effect is that any pause reads as the prohibited stopping ritual. Verification is
a pause. So under the contract, "state it and keep moving" is the locally rewarded
behavior and "stop and run four commands" feels like the prohibited one.

The contract explicitly permits this — it demands receipts ("I ran X and got Y") — but
the felt pressure runs the other way, and felt pressure won nine times in one session.
A contract that requires evidence while penalizing pauses needs the evidence step to be
FAST, not merely permitted.

### Root cause #4 — the founder is structurally unable to catch this class, which removes the last backstop

`type: process`

The founder does not read code or diffs, by explicit and repeatedly stated preference,
and the system is designed around that. Every other claim class has a machine checker.
This one is checked by nobody: not by a hook (root cause #2), not by the founder, and
not by the assistant (root cause #1). Errors in this class therefore survive until they
cause visible damage, which is why the write-guard hole survived hours while being
reported as closed.

## Verification

Not yet fixed. This section records the evidence gathered while diagnosing, and states
the criteria the fix must satisfy.

Evidence that the loop itself is healthy and the defect is in reporting, not in the
machinery:

```
$ launchctl print gui/501/com.kipi.dispatch | grep -iE "runs|last exit"
	runs = 474
	last exit code = 0

$ tail -4 ~/.config/kipi/dispatch.log
2026-08-02T17:57:51Z heartbeat: RESUMED after 75m without a beat
2026-08-02T17:57:57Z dispatching ASK-289 (live=0 cap=1 rounds=4 budget=3/3 lane=production)
2026-08-02T17:58:08Z dispatched ASK-289 (confirmed running)
2026-08-02T18:13:09Z skip: 1 converge run(s) live, cap 1

$ cat ~/.config/kipi/dispatch-count-2026-08-02
3
```

The loop dispatched three issues today, correctly refused to run for 75 minutes while
its checkout was behind `origin/main` (a staleness guard doing its job, triggered by
merges made during the session), suppressed a repeat page, and logged its own recovery.
The machinery is sound. The reporting about it was not.

Verification criteria for the fix (none met yet):

- [ ] A single command answers "when will ASK-N actually be dispatched" from observed
      state, and returns NEVER with a reason when that is the truth.
- [ ] That command, run against ASK-291 on 2026-08-02, returns "not today, budget
      3/3 spent" — the answer the session got wrong.
- [ ] A Stop-hook blocks a response containing a scheduling or armed claim when the
      checker did not run in that session, and PASSES a response that ran it.
- [ ] The hook is proven by a negative self-test: a response with a claim and no
      checker run is BLOCKED (exit 2), a response with no claim is allowed (exit 0).

## Contributing factors

- **`wiring-check.md` states the standard and ships no instrument for the runtime half.**
  Its load-path bullet is precisely correct and was violated the same session it was read.
  Cross-reference, not a new rule: the gap is tooling, not doctrine.
- **Subsystems write logs in different places, and launchd's `StandardOutPath` is a decoy.**
  `com.kipi.dispatch.plist` names `~/.config/kipi/dispatch.out`, which the script never
  writes to (0 bytes since Jul 27) because it writes `~/.config/kipi/dispatch.log`. A
  plausible-looking stale artifact sat one path away from the live one, and was read as
  evidence of death.
- **Spillover is a ledger the dispatcher does not read.** Three items captured during
  this session (`sp-2b9372f6`, `sp-b100a0e9`, `sp-42b92801`) would never have been
  dispatched; `no-orphan-findings.md` treats capture as sufficient, and for anything
  needing execution it is not. Capture and scheduling are different guarantees.
- **`budget=N/M` is legible only in a log line.** The lane cap (3) differs from
  `DAILY_MAX`'s default (4) via `LANE_MAX` at `kipi-dispatch.sh:616`. Reading the default
  and reporting it is exactly the specification-for-state substitution this RCA is about.

## Fixes shipped

- Surface fix: none. Correcting the nine individual claims does not prevent the tenth.
- Structural fix: pending — see action items. The fix must be an INSTRUMENT plus a GATE,
  because root cause #1 establishes that a standard without an instrument decays, and
  root cause #2 establishes that this claim class is deterministic and therefore owes a
  hook under `skill-hook-pairing.md`.

## Action items

- [ ] Build `q-system/.q-system/scripts/will-it-run.py <issue-id|--all>`: reads dispatch
      budget for today, lane cap, pool position, labels, issue state type, checkout
      staleness, and launchd job state; prints when the item will actually be dispatched
      or NEVER with the blocking reason. Reproducer-first; must return "not today,
      budget spent" for ASK-291 on 2026-08-02 — owner: sana — type: code
- [ ] Pair it with a Stop hook (`scheduling-claim-gate.py`) that blocks a response
      asserting a scheduling/armed state ("will be picked up", "is queued", "next run",
      "is armed", "is wired", "is live") when `will-it-run.py` was not run in that
      session. Negative self-test required — owner: sana — type: gate
- [ ] Register both in `capability-manifest.json` so the inert-engine check catches them
      going dead — owner: sana — type: test
- [ ] Make spillover items reachable by the dispatcher, or make capture route to Linear
      for anything requiring execution. Decide which; do not leave two ledgers with one
      consumer — owner: sana — type: code
- [ ] Fix `com.kipi.dispatch.plist` to point `StandardOutPath` at the log the script
      actually writes, or make the script write where the plist points. One of the two;
      the decoy path caused a false "the loop is dead" conclusion this session
      — owner: sana — type: config
- [ ] Add the runtime-evidence instrument to `wiring-check.md` as the named command for
      its load-path bullet, so the standard ships with its instrument — owner: sana
      — type: doc

## Lessons

- **Artifact presence is not behavior.** A file existing, a string appearing in a config,
  a marker inside a log, and a mtime are all artifacts. None of them is the system doing
  the thing. Four of this session's nine errors came from reading an artifact as behavior.
- **The cheap check must BE the correct check, or the cheap one wins.** Telling a system
  to verify harder does not work; the fix is making the correct verification one command.
- **"It is filed" and "it will happen" are different claims with different evidence.**
  Filing proves a record exists. Only budget, pool position, and a running consumer prove
  it will execute. This fleet had an instrument for neither until now.
- **When every other claim class has a machine checker and one does not, that one is where
  the errors accumulate.** Not because it is harder, because it is unguarded.
