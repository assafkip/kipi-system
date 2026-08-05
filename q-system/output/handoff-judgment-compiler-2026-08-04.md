# Handoff: Judgment Compiler (ASK-363) — updated 2026-08-05

Supersedes the 2026-08-04 14:51 version, which described a state that no longer
exists. If you are reading that version anywhere, discard it: it says zero
receipts exist and that PR #101 is the open question. Both are wrong.

---

## Current state (verified 2026-08-05 by running, not recalling)

**The work is DONE and MERGED. Nothing is in flight.**

- `main` at `eaf8047`, prd-os **0.16.5**
- **PR #102** merged (`a30311f`) — receipts required at `advance approved`
- **PR #103** merged (`eaf8047`) — the judge runner + the `judge_view` chokepoint
- **PR #101 CLOSED** as superseded by the split (see "the decision that was made")
- **The ledger EXISTS**: `.prd-os/judgments.jsonl`, **21 receipts**, `VERIFY PASS,
  chain intact`
- `evaluate`: `judged_receipts 8`, `cases 3`, `needs_human 5`,
  `population {accepted 16, rejected 4, deferred 1}`, **release gates FALSE**

Red gates are the CORRECT result: 3 cases against a 50-case threshold, and kappa
0 because the scoreable population is single-class. A green gate today would
mean something was lying.

---

## What is wired (verified, not assumed)

`/prd-triage` runs the blind judge BEFORE the author decides, once per finding,
then passes `--judge-run` to `set-disposition`. The judge runs with tools OFF
(`--tools ""`, NOT `--allowedTools`) and sees only the frozen context packet.
If the judge call fails, triage continues WITHOUT a judge run rather than
blocking the author.

`judge_view(packet) -> (view, citable)` is the single constructor for both what
the judge may perceive and what it may cite. The view is built from an
ALLOWLIST, so a field a future assembler starts copying is invisible by default.
Citable refs are a closed set derived from that same view, so relevance is
structural: the judge can only cite what it was shown.

---

## The decision that was made, and why

PR #101 was split. Its integrity half (chain verification, fail-closed on an
unreadable ledger, exact prd_id match, reading under the writer's lock) shipped
as blocking. Its field-level decision comparison was demoted to a counted
warning.

The deciding evidence: `evaluate` reads ONLY the ledger, so the ledger IS the
calibration set and the findings file is operational state. The integrity half
protects the data; the agreement half only guarded a mutable copy against
drifting off it, and three of its four tests existed to stop it false-blocking
legitimate work.

**A design that was recommended and turned out wrong:** a receipt-requirement
floor keyed to the PRD's creation date. It exempts every FUTURE decision on any
pre-floor PRD, and 35 of 36 PRDs predated the floor, so the gate was
near-permanently inert. The measurement showing "blocks nothing today" was read
as *safe* when it equally meant *does nothing*. The mechanism was deleted
entirely rather than hardened a fourth time.

---

## Known limits, stated plainly

- **`gates run` is RED**: 524 open spillover items across 667 unique ids,
  overwhelmingly pre-existing. A closeout claiming a clean ledger would be false.
- **`capability-gate` is RED (1)**: a review-invoker provenance shell test takes
  **66s against a 60s cap**, measured uncontended with all 7 sub-checks passing.
  A timing problem in an unrelated test, not a correctness failure.
- **`verify --cross-check` FAILS**: 659 dispositioned findings across ~34 other
  PRDs have no receipts. All pre-date the compiler. Zero belong to the two PRDs
  triaged here, and the approval gate filters by exact prd_id prefix, so approval
  is unaffected. This is the system correctly reporting the historical gap it
  exists because of.
- **All 21 receipts froze a misleading `repo_state`** (`sp-8355de5b`): every one
  records a branch that was merged and abandoned, at an old head, dirty. The
  triage ran against `main` in a clean worktree. Cause: `repo_state` resolves to
  the checkout that owns the ledger via git-common-dir, not the tree the work
  happened in. Finding-specific context is correct; only `repo_state` is wrong.
- **The ledger follows git-common-dir, NOT repo_root**, so one ledger serves a
  whole worktree set and a sandbox that copies a `.git` writes the MAIN
  checkout's ledger. Use a temp dir for tests, never the live `.prd-os/`.
- **`owned-by-other-prd` now converts to `needs-human` 100% of the time by
  construction** (`sp-4d545276`). A blind judge cannot know which issue owns a
  finding. This is a capability boundary, not a model failure, and it puts a
  permanent floor under the conversion rate.
- The tip anchor is tamper-EVIDENT, not tamper-proof: the same writer owns both
  files. Only `verify --cross-check` is independent.
- `reanchor` refuses a MISSING anchor by design (`sp-3d2c8255`), so the first
  receipt in a brand-new ledger has no automated recovery. It did not fire here.

---

## Open work

**Linear ASK-363** is still open. **ASK-378** tracks everything gated on reaching
50 cases. **ASK-379** was labelled a founder decision in the previous handoff and
**is not one** — preserving the benchmark dataset anywhere private removes the
single-disk risk with no disclosure decision at all. The public-repo framing was
a false binary.

**Spillover opened by this work** (all open; `resolve` requires a closed issue
reference, so none could be cleared): `sp-320d30e3`, `sp-0c725cde`,
`sp-f3aed16e`, `sp-892b1575`, `sp-c08e07ec`, `sp-2fc42d21`, `sp-f1d9c2b1`,
`sp-5169a276`, `sp-b274084f`, `sp-1c92c78f`, `sp-9755c728`, `sp-cd46fd96`,
`sp-4d545276`, `sp-3d2c8255`, `sp-a7b9d9ea`, `sp-33e98c0b`, `sp-8355de5b`.

The highest-value ones: the class-diversity precondition on the release gates
(`sp-f1d9c2b1`), the human-path self-citation gap (`sp-2fc42d21`), the
misattributed `repo_state` (`sp-8355de5b`), and the stale review runners
(`sp-5169a276`, `sp-b274084f`).

---

## What the first real triage found

The PRD under review is **unbuildable as written**. No git ref in this repo
contains the notifier script it targets; it cites line numbers past the end of
the file that exists on `main`. It was written against an unmerged branch that no
longer exists. All 8 findings accepted, two of them blockers.

Findings 2 through 8 were deliberately NOT marked duplicates of finding 1 despite
sharing a root cause, because `duplicate` maps to `rejected` and five of them
survive a rebase. That distinction is exactly what the old ledger destroyed on
every write, and it is now frozen in a receipt.

The 13 findings on the older PRD were migrated WITHOUT judge runs. Those
decisions were made in June; pairing today's workflow context to a June decision
would manufacture the precise retroactive artifact this issue exists to prevent.
A receipt with `human` and no `judge` satisfies the receipt gate while being
excluded from calibration by construction.

---

## Lessons published

Four written to `q-system/lessons/` (HOW-only, de-identified, validator-clean):

- a check must be able to fail for the reason you care about
- kill a defect class by deleting the mechanism, not by guarding it
- a safety property enforced at N sites is not a chokepoint
- an artifact must carry its own provenance, never inherit it

The first has twelve instances from this work alone, split evenly between author
and reviewer. That split is the point: it is not a competence gap, it is the
default outcome of verifying the thing in front of you instead of the thing the
conclusion requires.

---

## The single next action

Nothing is blocked and nothing is running. The calibration clock is live, so the
next meaningful event is **volume**: more real triage through the normal flow.
At roughly 50 cases, ASK-378's questions become answerable. Until then the gates
stay red, correctly, and the honest reading of a red gate here is
"not yet measurable", not "failing".
