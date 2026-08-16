---
description: Any code that files Linear issues without a human in the loop marks them needs-triage, so machine inflow is a filterable set instead of indistinguishable backlog.
paths:
  - "**/scripts/**"
  - "**/hooks/**"
  - "**/*.py"
  - "**/*.sh"
---

# Automated filers mark their own output (ENFORCED for the alert path, ADVISORY elsewhere)

Read the heading narrowly, because this repo has been burned by a rule claiming
ENFORCED while naming no executable. What is actually enforced today:

| Piece | Status |
|---|---|
| `alert-to-linear.py` writes `needs-triage` on every ticket it creates | CODE, and `test_linear_triage_health.py` pins it |
| `linear-triage-health.py` measures the resulting queue and alerts on a breach | CODE, wired via `com.kipi.linear-triage-health.plist` |
| Any OTHER filer doing the same | ADVISORY. No hook inspects a new script for this |

There is no gate that catches a future filer which skips the mark. Writing one
would mean statically deciding "is this call site creating a Linear issue without
a human", which is a judgment a regex loses. So this is a convention with one
worked reference implementation, not a checked invariant. If it drifts, nothing
will say so.

## The rule

Any code path that creates a Linear issue **without a human deciding it should
exist** adds the `needs-triage` label alongside its owner label.

```python
label_ids = _label_ids(ln, team_id, [OWNER_LABEL, TRIAGE_LABEL])
if label_ids:
    payload["labelIds"] = label_ids
```

Three properties matter more than the label name:

1. **Additive, never a gate.** The issue still lands in a `backlog`-type state.
   `linear-worker.sh:546` and `linear-dor-drafter.py:194` both refuse anything
   whose state type is not `("backlog", "unstarted")`, so moving automated inflow
   into a different state stops the drain, not the flood.
2. **On CREATE only.** A repeat or an update must not re-mark an issue a human
   already routed. In `alert-to-linear.py` this is structural: repeats return
   from an earlier branch and never reach the label code.
3. **Cleared by routing, not by a person remembering.** The mark comes off when
   the issue gets a project or gets closed. Nothing asks the founder to clear it.

## Why this and not Linear's Triage feature

Team Triage is real and it IS reachable from the API: `TeamUpdateInput
.triageEnabled` exists, and team ASK reads `triageEnabled: false` /
`triageIssueState: null` (introspected 2026-08-16, so this is measured, not
inherited from a doc). It is a live option, not a blocked one.

It was still the wrong instrument here:

- A triage-type state is invisible to both drains, per the filter above. Enabling
  the flag without teaching those two consumers first is an outage wearing a
  feature's name.
- Linear Triage terminates in a human pressing accept or decline. The measured
  problem on 2026-08-16 was 229 issues with no project -- not that inflow was
  invisible, but that outflow is manual while inflow is not. A queue whose exit
  is a person does not fix a queue whose problem is that its exit is a person.

If Triage is ever enabled, both consumers need the triage state type added to
their accepted set in the same change, and this convention becomes redundant
rather than wrong.

## What the marking is NOT for

- **Not a junk flag.** Volume from one detector is a signal about the detector,
  not N separate problems. 44 issues from one scanner may be 44 real jobs; the
  mark says "nobody routed this yet", never "this is noise".
- **Not a reason to skip triage.** A marked issue still gets a decision recorded
  on it (`linear-triage.py` writes the verdict and the why).
- **Not a founder queue.** Nothing in this design routes to the founder's desk.

## Measuring it

```bash
python3 q-system/.q-system/scripts/linear-triage-health.py            # report
python3 q-system/.q-system/scripts/linear-triage-health.py --apply    # flag dormant
```

Reports unrouted count, `needs-triage` depth, oldest untouched, and dormancy past
`--dormant-days` (default 75). It flags dormant work with a comment and never
closes it: a bot that silently closes real work teaches people the tracker lies.

It alerts through `slack-notify.sh` only on a threshold breach. That path files a
Linear ticket rather than sending to Slack, so the script excludes its own
tickets from its own counts -- otherwise a backlog monitor reports the backlog it
just created.

## Cross-references

`founder-notifications.md` (the single alert sink) · `linear-first.md` (work that
is not recorded did not happen) · `no-orphan-findings.md` (a mention is not a
capture) · `skill-hook-pairing.md` (why the advisory half stays advisory).
