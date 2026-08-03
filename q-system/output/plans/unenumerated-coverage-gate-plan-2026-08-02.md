# The one defect class behind all five RCAs, and the gates that close it

**Date:** 2026-08-02
**Inputs:** the five RCAs written tonight, ~20 incidents across one session.

## What/why

Tonight produced about twenty incidents. They are not twenty problems. They are
**five root classes, and the five share one structure.** Fixing them one at a time
is the mistake ASK-122 itself warned about: eleven groomings for one call.

## The structure

Every one of the five is **a claim of coverage that nothing enumerates**, failing
in the direction that looks like success.

| RCA | The unenumerated claim | Failed as |
|---|---|---|
| one-sided-rule-application | "every walker applies this filter" | 6 walkers, filter on some |
| absence-read-as-success | "no findings means nothing is wrong" | silence read as a pass |
| inherited-claim-treated-as-verified | "this is blocked" | 6 claims, 0 checks run |
| unattended-committer | "this commit belongs to this branch" | scope never stated |
| tests-that-pin-nothing | "these tests guard this code" | 9 tests, ~1 binding |

Two properties make the class dangerous rather than merely common:

1. **The failure is silent.** A walker that skips a filter does not error, it
   votes. An empty findings block does not crash, it approves. A test that pins
   nothing does not fail, it passes. In every case the broken state is
   indistinguishable from the healthy one **at the point anybody looks**.
2. **The claim is asserted by memory.** "One predicate for all three consumers"
   was a count produced by recall, and there were four. "Merge is blocked pending
   founder" was a reading, not an API call. The claim is always cheap to check and
   was never checked, because nothing required it to be.

The corrective for all five is the same shape: **make the claim mechanically
enumerable, then prove the enumeration can come back short.** The second half is
not optional — four of the five had a guard of some kind that had never been seen
to fail.

## Approach

Five gates, one per class, ordered by how many of tonight's incidents each would
have caught. All are scripts or hooks, none are prose: `sycophancy-core.md` and
`skill-hook-pairing.md` both already require that, and three of tonight's five
classes had a *written rule* naming the correct behaviour that nobody executed.

| # | Gate | Class | Tonight's incidents caught | Cost |
|---|---|---|---|---|
| 1 | `consumer-parity-check.py` | A | 6 | medium (AST walk) |
| 2 | report-provenance lint | C | 6 | medium (Stop hook + patterns) |
| 3 | `mutation-check.py` | E | 3, plus it is the meta-gate that would have exposed 1 and 4 earlier | high (expensive, run periodic) |
| 4 | fail-open audit (ASK-213) | B | 3 | medium, and the issue already exists |
| 5 | WIP-ref committer | D | 3 | low |

Recommended build order is **5, 1, 4, 2, 3** — not the leverage order. Gate 5 is
an hour of work and stops an active bleed that damaged this very session twice.
Gate 3 is the most valuable and the most expensive, so it lands last and runs on a
schedule rather than per-commit; a per-commit mutation cost gets switched off, and
a gate that is off protects nothing.

## Files to touch

- `q-system/.q-system/scripts/consumer-parity-check.py` (new) + `test/test-consumer-parity.py`
- `q-system/.q-system/scripts/report-provenance-lint.py` (new), wired Stop in
  `.claude/settings.json` AND `settings-template.json` (the settings-template-sync
  gate blocks a hook wired in one and not the other)
- `q-system/.q-system/scripts/mutation-check.py` (new) + a `mutants` key per entry
  in `capability-manifest.json`
- ASK-213's checker (existing issue, unbuilt)
- `auto-commit.py` — target a per-session WIP ref instead of the current branch
- `q-system/.q-system/scripts/fleet-health-daily.py` — add live-vs-template plist
  drift, which is how a spend dial silently disagreed with itself tonight

## Acceptance criteria

- [ ] Each gate ships with a negative self-test: the guard is observed RED against
      a deliberately broken input before its green is trusted. Four of tonight's
      five classes had an unfalsified guard; that is the specific mistake to not
      repeat while fixing it.
- [ ] `consumer-parity-check.py` enumerates walkers by AST rather than by a list,
      so a new walker fails the day it is added, not the day someone notices.
- [ ] Replaying tonight's evidence through the finished gates reproduces tonight's
      findings: the three captured review artifacts, the six unfiltered walkers in
      `capability-map-gen.py` at `d20f412`, and the 9-test suite at `d20f412`.
      A gate that cannot re-find a known past defect is not verified.
- [ ] Every gate is registered in `capability-manifest.json` with its runner, so
      the capability gate fails when one goes missing.
- [ ] No gate is wired in `.claude/settings.json` alone.

## Patterns to follow

From this instance's own code, not generic advice:

- `capability-gate.py`'s `declared_inert` + `spillover_id` shape: a deliberate
  exception is recorded with a reason and a ledger id, never a silent skip.
- `pr-verdict-lib.sh`'s one-reader rule: the predicate lives next to the reader
  that defines it, so the two cannot answer differently. That file's header
  explains why, and tonight proved it right twice.
- `test-severity-floor.sh`'s both-directions assertion: it pins that the primary
  engine CAN post the required context and that the advisory engine CANNOT. Both
  halves, or the contract is only half-held.
- `token-guard.py`'s posture: a proxy that is honest about being a proxy beats a
  measurement that is not available.

## What this plan does not claim

These gates address the five classes observed tonight. They do not make the fleet
correct, and three of them are themselves the "self-enumerating guard" pattern
whose absence caused class A — so each needs the falsification step above or it
becomes the next unenumerated coverage claim.
