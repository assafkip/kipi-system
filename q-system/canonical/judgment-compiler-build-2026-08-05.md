# Build Record: The Judgment Compiler (ASK-363), 2026-08-04 → 2026-08-05

Canonical narrative of a two-day build. Written for reuse in building-in-public
content: every number here was measured by running something, and the failures
are recorded at the same resolution as the wins.

Companion artifacts: `decisions.md` RULE-010 → RULE-015 (the durable rules),
`q-system/lessons/` (four published HOW-only patterns), Linear ASK-363.

---

## What was built, in one paragraph

Every time a reviewer objects to something in a plan, someone decides: accept,
reject, defer. Those decisions were being overwritten and lost. A benchmark
showed an AI given only the objection text predicted the founder's decision at
**40% agreement, kappa 0.032** — worse than always guessing "accept" (76.6%
baseline). The diagnosis: a disposition is not a property of an objection, it is
a property of an objection **inside workflow state**, and the ledger destroyed
that state on every write. The fix is an immutable, hash-chained receipt per
decision, freezing the decision *and* the surrounding context.

By the end: **21 real receipts, chain verified, 8 carrying an AI prediction**
alongside the human answer. The calibration that was impossible is now a
volume problem.

---

## The headline number

**23 genuine defects** found by adversarial review across two days, on code that
passed its own test suite every single time.

Not one was caught by the tests. Every one required either an independent
reviewer or someone deliberately trying to break the check itself.

Eight of the 23 landed in a single ~700-line detector across ten review rounds,
which is why that one was split rather than merged whole.

---

## The pattern underneath almost all of it

**A check must be able to fail for the reason you care about.**

Thirteen instances in two days, split roughly evenly between the coordinator and
the engineers. That split is the point: it is not a competence gap, it is the
default outcome of verifying the thing in front of you instead of the thing the
conclusion requires.

A representative sample, all real:

- A test asserted `--allowedTools ""` when the property was tool *availability*,
  controlled by `--tools`. The AI judge could read files the whole time. Had it
  shipped, every measurement afterward would have been worthless and it would
  have looked fine.
- A six-row table of malformed dates where a coarse range guard already rejected
  every row, so the fine-grained parse could be deleted with the suite green.
- A hash-binding test run on the one fixture shape structurally unable to
  exercise the binding.
- A blast-radius measurement read as "this is safe" when the identical number
  meant "this does nothing."
- `cmd | tail` in a gate check: the pipeline's exit status is `tail`'s, so it
  reported success while the gate was red.
- "It was local contention" for a test **66s against a 60s cap**, measured idle.
- A mutation test whose mutant never applied, because backticks executed as
  command substitution. Counting it as a kill would have certified an untested
  check.

Two practices came out of it that are not obvious:

1. **Mutation-test the guard, not just the code.** Twice a guard could have been
   deleted with the entire suite still green.
2. **Distrust the convenient explanation for anything intermittent.** One
   measured run refutes it, and skipping that run converts a real defect into a
   false claim about a gate's state — worse than a wrong conclusion, because it
   looks settled.

Published as `q-system/lessons/a-check-must-be-able-to-fail-for-the-reason-you-care-abou.md`.

---

## The path, in order

**Day 1 opened** with PR #101 after seven review rounds and three options: split,
keep grinding, or park.

**Decision: split.** The deciding evidence was that `evaluate` reads only the
ledger, so the ledger *is* the calibration set and the findings file is
operational state. One half protected the data; the other guarded a mutable copy
against drifting off it, and 3 of its 4 tests existed to stop it false-blocking
legitimate work.

**Then the finding that reframed everything.** No judge-run producer existed. The
triage command never passed `--judge-run`, and `evaluate` counts a case only when
a receipt carries *both* a judge prediction and a human decision. So every
release gate was unreachable by construction, and roughly half the engine had no
wired input. The handoff's closing line — "run a triage and the calibration clock
starts" — was simply wrong.

This was a **recurrence of a documented class**: a consumer with no production
producer, invisible because ~90 tests hand-built the input.

**PR #102** shipped the receipt gate. The design recommended for it — a floor
keyed to the PRD's creation date — was wrong, and the measurement showing it was
in hand and misread. It exempted every *future* decision on any pre-floor PRD,
and 35 of 36 PRDs predated the floor. "Blocks nothing today" was read as *safe*
when it equally meant *inert*. The mechanism was deleted rather than hardened a
fourth time.

**PR #103** took **ten rounds**. Rounds 1–6 and 8–9 each found something
genuinely new. The most consequential:

- The judge was not blind (the flag defect above).
- Judge citations were never resolved, so a fabricated reference scored as
  supported evidence.
- The prediction printed into the founder's transcript *before* they decided —
  next to a note saying not to show it.
- Cross-PRD duplicates broke the hash binding outright, falsifying a premise the
  coordinator had written into the plan and told the engineer not to re-derive.
- A lost-update race: two writers, two successful receipts, one disposition
  silently reverted, exit 0 on both.
- A phantom receipt when the anchor write failed after the append.

**The structural turn.** After round 4 it was decided — *before* the verdict
arrived, so the outcome could not shape it — that the fix would be a refactor
regardless. Reasoning: blindness was enforced at **four independent seams** and
three were wrong. A property enforced at N sites is not a chokepoint. One
constructor now owns the judge's entire view, built from an **allowlist**, so a
field a future contributor adds is invisible by default.

**The enumeration that validated itself.** Round 9 found an ambient reference
accepted as duplicate evidence. Rather than patch instance nine, the class was
enumerated: every source feeding the citable set classified as finding-dependent
or ambient. The derived rule then **independently rediscovered a hole closed by
hand several rounds earlier**, which it was never told about. A classifier
reproducing known truth it was not given is the strongest evidence produced in
the whole build.

**Day 2 opened** with an adversarial test of everything, assuming nothing worked.

**It didn't.** Not one line of two days' work was reachable. Plugins execute from
a cached copy, and the registry pinned the plugin at **version 0.1.0, installed
in April**. Five months stale, not the one day assumed. Worse: the acceptance
criteria written for the fix pointed at the *downloaded* copy, not the *loaded*
one — so following them literally would have turned everything green over
five-month-old code. The lesson landed on the plan written about deployment.

**Five follow-on PRs** landed the runtime fix, a freshness detector, 17 recovered
work-product files that existed only in a dirty checkout, 537 scratch files
untracked from git, and the root cause behind a review that had read the wrong
directory entirely.

---

## Numbers worth quoting

- **23** genuine defects, none caught by tests
- **13** instances of "a check that cannot fail for the reason you care about"
- **10** review rounds on one PR; **8** defects in one ~700-line detector
- **40% / kappa 0.032** — the blind judge benchmark that started it
- **35 of 36** PRDs exempted by the floor design that was recommended and wrong
- **88 of 112** copies of one script resolved to the wrong root; that is why a
  review ran against a directory that was not a repository, read no diff, and
  produced a verdict from the prompt alone
- **102 → 112** copies of that script *during a single session* — the generator
  is still running
- **537** scratch files silently committed by an unattended auto-commit
- **21** receipts, **8** judged, **3** scoreable cases against a 50-case gate
- Version parity alone still cannot see commit drift: one plugin reports the same
  version string from a different commit. Stated in the PR body, not implied away.

---

## What the first real use found

The plan under review turned out to be **unbuildable**. It targeted a script
present in **no git ref**, citing line numbers past the end of the file that
exists. It had been written against a branch that no longer exists.

Eight findings accepted, two of them blockers. Notably, findings 2–8 were
deliberately **not** marked duplicates of finding 1 despite a shared root cause,
because `duplicate` maps to `rejected` and five of them survive a rebase. That
distinction is exactly what the old ledger destroyed on every write, and it is
now frozen in a receipt.

---

## Honest ledger of what the coordinator got wrong

Recorded at the same resolution as the wins, because a build record that only
lists wins is not calibrated and cannot be trusted on the wins.

1. Recommended a floor design that protected almost nothing, holding the
   measurement that said so.
2. Specified a lock boundary covering the write but not the read — trading a
   loud recoverable failure for silent data loss.
3. Wrote a false premise into a plan and instructed the engineer not to
   re-derive it.
4. Approved a nine-row classification table, verified two rows, missed the one
   carrying the defect just guarded against one field over.
5. Reported that existing receipts carried reason codes, inferred from a metric
   structurally incapable of reporting on them.
6. Said "seven open items" when the ledger held 524.
7. Wrote acceptance criteria pointing at the wrong copy of the runtime.
8. Passed the founder a decision that was never theirs — a false binary
   inherited from a handoff and never tested.
9. Amplified a refutation as good judgment before it had been checked; the next
   round disproved it.

Every one was caught by someone verifying rather than trusting.

---

## The mechanic that made it work

**Nobody accepted anyone else's "verified" as verified.**

Each party was wrong in a way only another could see. The coordinator's
measurement was corrected by the engineer; the engineer's classification was
corrected by the coordinator; both were corrected by an independent adversarial
reviewer; and the reviewer itself asserted, once, a consequence the code did not
have — refuted with an executed reproducer rather than complied with.

That is not redundancy. It is the only reason 23 defects surfaced before a
permanently dishonest dataset existed.
