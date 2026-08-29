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
| Any OTHER filer doing the same | PARTLY CODE. `linear-filer-label-lint.py` demands a DECLARED posture, never the label itself |

A gate now exists here, and it is narrower than the row above may suggest. The
original text said no hook could inspect a new script for this, because deciding
"is this call site creating a Linear issue without a human" statically is a
judgment a regex loses. That reasoning was right and the gate does not overturn
it -- it splits the question along `skill-hook-pairing.md`'s decision rule:

- **Deterministic (the script):** does this file construct an `issueCreate`?
- **Judgment (the author):** is a human deciding each of those issues?

The second is never inferred, it is declared once in the file. So a compliant
filer passes one of exactly two ways: it references `needs-triage`, or it carries
`# linear-filer: human-in-the-loop -- <why a person decides each issue>`.
Wired PostToolUse on Edit/Write/MultiEdit in BOTH `.claude/settings.json` and
`settings-template.json`, tested by `test_linear_filer_label_lint.py`.

Measured before it shipped: 8 files in this repo construct `issueCreate`, and one
referenced `needs-triage`. A gate demanding the label outright would have been red
on 7 files the day it landed -- unsatisfiable for its own population, which is how
a gate gets switched off and then protects nothing.

**Do not read its silence as proof.** It matches the string `issueCreate`, so a
filer reaching Linear through some future helper is invisible to it. It cannot
tell whether a posture marker is TRUE: `human-in-the-loop` on a nightly sweep
passes and is a lie the gate cannot see. And it checks the label is REFERENCED,
never that it is attached to the payload on every branch.

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
