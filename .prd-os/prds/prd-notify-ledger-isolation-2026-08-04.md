---
id: prd-notify-ledger-isolation-2026-08-04
title: Notify Ledger Isolation
status: in-review
created_at: 2026-08-04T02:04:58Z
updated_at: 2026-08-04T02:08:29Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-notify-ledger-isolation-2026-08-04-findings.jsonl
codex_reviewed_at: 2026-08-04T02:23:29Z
reviewed_by: codex-adversarial
---

## SUPERSEDED 2026-08-05 - not buildable, slot released with `clear` (ASK-363)

This PRD was removed from the prd-os active slot on 2026-08-05. It was NOT
archived, and that distinction is the point.

**Why it cannot be built.** It targets a `slack-notify.sh` carrying
`KIPI_NOTIFY_RECEIPTS` and cites lines :173/:179/:207. Verified 2026-08-05
against every ref in the repo: `origin/main`'s `slack-notify.sh` is 106 lines,
contains zero occurrences of `KIPI_NOTIFY_RECEIPTS`, and NO ref under
refs/heads or refs/remotes carries a version that does. The cited lines cannot
exist in a 106-line file. It was written against an unmerged branch that no
longer exists. Its own codex review reached the same conclusion independently:
all 8 findings accepted, finding-1 and finding-2 as blockers.

**Why `clear` and not `archive`.** `archive` is gated on every accepted finding
having a closed-issue receipt, and the gate refused with all 8 listed as
missing. That refusal is correct and worth stating: these 8 findings are not
work items, they are findings that INVALIDATE this PRD, so no issue will ever
close against them and no receipt can ever exist. Archiving would assert
"done and accounted for" about something never built. `clear` asserts only
"no longer the active context", which is true, and changes no spec and deletes
nothing.

**Nothing was destroyed.** This spec, its findings file (8 records with their
dispositions and rationales), and the codex review stamp all remain on disk as
history. The receipts ledger and `.prd-os/judgments.jsonl` were not touched.

**Successor:** the deployment work is re-specified from current `main` in
`prd-judgment-compiler-not-deployed-2026-08-05`.

The gate/model mismatch this exposed - a finding that invalidates its own PRD
has no receipt-shaped remedy, yet the archive gate demands one - is captured
separately rather than worked around.


# Notify Ledger Isolation

## Problem

The brief for this PRD said 83% of the founder's Slack noise comes from a test
paging his real webhook. **That is false, and the reason it was believed is the
actual defect.**

`test-notify-fixture-guard.sh:78-80` exports `KIPI_SLACK_WEBHOOK` at its own
loopback capture server before the first invocation, and `slack-notify.sh:179`
reads that variable *before* `~/.config/kipi/slack-webhook`. The founder's real
hook file is never opened. No "guard suite probe" has ever reached Slack.

What the suite does not stub is the **receipts ledger**. `slack-notify.sh:207`
resolves `RECEIPTS="${KIPI_NOTIFY_RECEIPTS:-$HOME/.config/kipi/notify-receipts.jsonl}"`,
the suite sets no such variable, so every production-direction case appends a row
to the production ledger with `"delivered": true` — true of the capture server,
read by everyone as true of Slack.

**Measured 2026-08-04** (`~/.config/kipi/notify-receipts.jsonl`, 157 rows):

| kind | delivered | rows |
|---|---|---|
| `unclassified` | yes | 104 |
| `receipt` | no | 40 |
| `decision` | yes | 13 |

91 of those 104 are the literal string `guard suite probe`. **58% of the whole
ledger is one test.** Reproduced with a negative self-test: running the suite
under a redirected `HOME` wrote 7 rows to the default ledger path, all
`delivered: true` (25/25 assertions still passed). 91 rows is ~13 suite runs.

So the founder-visible unclassified traffic is **13 messages, not 104**, and the
ledger cannot tell anyone that, because the field that would distinguish the two
records the capture server as a delivery.

### Why this outranks the noise it was mistaken for

`notify-receipts-surface.py` is the ledger's consumer, wired at SessionStart in
`settings-template.json:138`. It is the machine sink ASK-294 built so that
overnight machine activity reaches the agent instead of the founder. That surface
is currently 58% test noise.

The brief that opened this PRD is the first documented casualty: it was derived
from the ledger, and it named the wrong root cause, the wrong blast radius, and a
~102-call-site migration that does not exist. A polluted measurement surface does
not merely add noise; it manufactures confident wrong conclusions in whoever reads
it next. That is a strictly worse failure than a chatty Slack channel.

### The migration the brief called for is already done

The brief's item 3 ("whatever chokepoint stops call site 108 from being born
unclassified") **already exists and is already wired.** `notify-callsite-audit.py`
is Gate 1.2b in `validate-separation.py:801-816`, run by `kipi check`, added under
ASK-310 with its own scar comment about having previously been 100% built and 0%
wired.

Run 2026-08-04, it reports **one** bare call site, not 102:

```
notify-callsite-audit: 1 call site(s) reach the founder with no --kind.
  q-system/.q-system/scripts/fable-escalate.py:357
```

`kipi check` is therefore RED on this today. The migration is ~99% complete and
its last site is already named by a wired gate.

## Goals

- A test can never write the production receipts ledger, on any branch, including
  tests nobody has written yet.
- `delivered: true` in the ledger means delivered to a real endpoint.
- Gate 1.2b goes green: zero bare founder-notification call sites.
- The pollution already in the ledger is quarantined, not deleted, so the
  corrected count is auditable against the original.

## Non-goals

- **Reversing the fail-open behaviour of `slack-notify.sh`.** Its reasoning holds:
  silencing an unmigrated instance-local alert is a worse outage than the noise.
- **A ~102-call-site migration.** It does not exist; the measurement that implied
  it was the pollution.
- **Rewording the `ci-redrive` / `review-redrive` producers** ("still red after
  the machine tried"). Real signal, arguably actionless, and they live in the
  three control-code files that conflict between `origin/main` and
  `sana/ask-352`. Editing them during that conflict is how a control-code merge
  gets resolved by accident. Captured as spillover, not fixed here.
- Deleting any ledger row.

## Proposed approach

**One chokepoint, in the single writer, keyed on a signal that cannot be true in
production.**

`slack-notify.sh` already carries the exact precedent: its fixture guard refuses
to *deliver* when `KIPI_LINEAR_API_URL` resolves to a loopback host, using
`_kipi_loopback_host()` (case-insensitive, four numeric octets in 127.0.0.0/8,
hardened by two opposing PR #58 findings). That guard `exit 0`s at line 173,
*before* the ledger write — which is why the loopback-direction cases pollute
nothing and only the production-direction cases do.

The second signal is already sitting in the same script: **the webhook host.**
A `KIPI_SLACK_WEBHOOK` on loopback is never production. Slack's endpoint is
`hooks.slack.com`; a fixture's is `127.0.0.1:$PORT`. The asymmetry is total in
both directions, which is the same property that made the Linear-URL signal safe
to key on.

So: after the webhook is resolved, if its host is loopback **and**
`KIPI_NOTIFY_RECEIPTS` was not explicitly set, redirect the ledger write to a
deterministic fixture path and say so on stderr.

- **Redirect, not skip.** Every existing assertion shape keeps working — rows are
  still written, just not to the founder's ledger. A test that wants to read them
  back sets `KIPI_NOTIFY_RECEIPTS`, which `test-notify-receipts-surface.py:19`
  already does.
- **Reuses `_kipi_loopback_host()` verbatim.** No second host parser: a
  derivation split between two copies of one rule is its own defect class.
- **Nothing to remember.** It protects branches that do not carry it and tests
  that do not exist yet. Per-test stubbing does neither, which is the argument
  this file's own scar comment already makes at lines 106-114 — applied to the
  webhook then, and to the ledger now.

The 91 existing rows are quarantined by a one-shot script that rewrites them with
`"fixture": true`, appending nothing and deleting nothing.

`fable-escalate.py:357` gets `--kind receipt`.

## Alternatives considered

- **Stub `KIPI_NOTIFY_RECEIPTS` per test.** Rejected: this is verbatim the fix
  that failed on 2026-08-01. `slack-notify.sh:106-114` records the outcome — PR
  #54 stubbed three tests, and while it sat unmerged an agent ran a suite from a
  worktree cut off main, which carried no stub, and the founder was paged live.
  Per-test stubbing protects only branches that carry it and only tests someone
  remembered. Shipping it again for the ledger would be repeating a scar the file
  documents.
- **Key the ledger redirect on `KIPI_LINEAR_API_URL` too.** Rejected: it is the
  variable the suite deliberately *unsets* to drive the production direction, so
  it is absent in exactly the 7 cases that pollute. It cannot see them.
- **Key on `$TMPDIR` / a temp `KIPI_STATE_DIR`.** Rejected for the reason already
  written into `slack-notify.sh:124-128`: a production job may legitimately keep
  state under a temp path (macOS `$TMPDIR` is exactly that), so it would suppress
  real rows.
- **Refuse the ledger write entirely on a fixture run.** Rejected: it silently
  breaks any current or future test that reads rows back, and a guard that
  destroys a diagnostic is the failure `founder-notifications.md` exists to
  prevent. Redirect preserves the diagnostic.
- **Delete the 91 polluted rows.** Rejected: never silently delete. The corrected
  count has to stay checkable against the original, and the rows are the evidence
  that the brief's conclusion was manufactured.
- **Add a `stuck-loop` class to `ALLOWED_CLASSES` for `fable-escalate.py`.**
  Rejected: see Resolved decisions.

## Scenarios

- **The suite runs on a branch that has never heard of this PRD.** CI (or an
  agent) runs `test-notify-fixture-guard.sh`. It exports `KIPI_SLACK_WEBHOOK` at
  `127.0.0.1:$PORT`. `slack-notify.sh` resolves the webhook, sees a loopback host,
  sees no explicit `KIPI_NOTIFY_RECEIPTS`, and appends its 7 rows to the fixture
  path instead. Delivery to the capture server still succeeds, so all 25
  assertions still pass. The production ledger gains zero rows.
- **A test written next month pages the founder.** Same path. The author stubbed
  nothing and read no rule. The chokepoint fires anyway, because it keys on the
  webhook the test necessarily had to point somewhere fake.
- **Production heartbeat fires at 03:00.** `open-loops-heartbeat.sh` calls
  `slack-notify.sh --kind decision --class publish`. The webhook resolves to
  `hooks.slack.com`, which is not loopback, so the ledger path is untouched, the
  row lands in the production ledger, and the founder is paged exactly as today.
- **The agent reads its SessionStart surface.** `notify-receipts-surface.py` shows
  overnight machine activity with no `guard suite probe` rows in it, and the 91
  historical rows carry `"fixture": true` so a reader can tell them apart instead
  of counting them as founder pages.
- **Someone re-derives the noise number.** Filtering `fixture != true` yields 13
  founder-visible unclassified messages, which is the number the brief should have
  had.

## Resolved decisions

- **The active PRD `prd-finding-quality-bar-2026-08-03`.** Decided: parked via
  `prd_runner.py clear`, not archived, not finished. Rationale: `clear` writes
  empty active state and touches no spec (`cmd_clear`, line 371-374); the spec is
  still `status: draft` and `prd_runner.py load prd-finding-quality-bar-2026-08-03`
  restores it exactly. Archiving is terminal and would have discarded a same-day
  PRD; finishing it is gated on the same 10 blocking spillover items this PRD
  cannot clear either. Park is the only reversible option.
- **`fable-escalate.py:357` gets `--kind receipt`, not a new `--class`.** Decided:
  receipt. Rationale: the message is "agent stuck after N Fable escalations". The
  founder cannot unstick an agent — that is `feedback_founder_never_the_next_actor`
  read literally, and ASK-294's own doctrine that a message asking the founder to
  perform a step is a producer defect. The machine consumer already exists
  (`notify-receipts-surface.py` at SessionStart) and is precisely where "the agent
  is stuck" belongs. Adding a sixth allowed class would spend the enum's scarcity
  on the one case that has a machine reader.
- **Work happens in the main checkout, not a git worktree.** Decided: main
  checkout, on a branch cut from `origin/main`. Rationale: `.prd-os/spillover.jsonl`
  and `.prd-os/gates.jsonl` are **gitignored** (`git ls-files` confirms only
  `prds/`, `issues/`, `receipts.jsonl`, `config.json` are tracked). A fresh
  worktree has no spillover ledger, so `prd_runner.py gates run` would report
  GREEN against an empty file — a false green at exactly the closeout step that is
  supposed to be the last line of defence.
- **This PRD does not reach `archived`.** Decided: it stops at merged code with
  `gates run` still RED. Rationale: archive is gated on 10 blocking spillover
  items, none of which this PRD created or can honestly resolve. Claiming archive
  would mean resolving them without fixing them.

## Risks and rollback

- **Blast radius: every `slack-notify.sh` caller in the fleet**, because
  `kipi update` ships this script to 22 instances. Mitigated by the direction of
  the change: it only ever *redirects a local file write*, never suppresses a
  delivery. A misfire costs a ledger row in a temp path, not a missed page.
- **The real risk is a false positive suppressing production ledger rows**, which
  requires an instance whose genuine Slack webhook is on a loopback host. That is
  not reachable: Slack Incoming Webhooks are `https://hooks.slack.com/...` by
  definition, and a loopback webhook cannot leave the machine.
- **A test that asserts on the production ledger path would break.** Checked:
  `test-notify-receipts-surface.py:19` sets `KIPI_NOTIFY_RECEIPTS` explicitly, so
  the explicit-set escape hatch covers it. Any other such test is a finding.
- **Rollback:** revert the commit. The guard is one block in one script; the
  quarantine script is one-shot and additive (adds a key, removes nothing), so the
  rows survive a revert and stay readable either way.
- **Mutation requirement:** this guards a safety property, so each issue carries a
  mutant that must be killed — deleting the guard must turn a test red, and the
  guard must be proven to fire against the pre-fix copy via the suite's existing
  `KIPI_NOTIFY_UNDER_TEST` ref hatch (`test-notify-fixture-guard.sh:25-32`).

## Open questions

- None blocking. The two producer shapes the brief flagged as possibly-defective
  (`ci-redrive` "still red after the machine tried", `review-redrive` "still has
  kipi/codex-approved failing") are deferred to spillover with a named reason, not
  left open here.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: The founder asked for less Slack noise and this PRD delivers approximately
none — the 91 rows it removes were never in Slack. The honest reframe is that the
brief's goal was built on a corrupted measurement, and the founder-visible noise
is 13 messages, most of which are one heartbeat class. Fixing the measurement
first is what makes any future noise decision trustworthy; fixing "noise" against
a 58%-polluted ledger would have produced a migration of ~102 call sites that do
not exist.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Already run, twice, and it is the load-bearing evidence rather than a
formality. (1) `env HOME=$TMP bash test-notify-fixture-guard.sh` wrote 7 rows to
`$TMP/.config/kipi/notify-receipts.jsonl`, all `guard suite probe`, all
`delivered: true` — if the pollution thesis were wrong the file would not exist.
(2) `notify-callsite-audit.py --repo .` exits 1 naming exactly one site — if the
102-site thesis were right it would name ~102.

Q3: What is the cheapest non-build alternative?
A3: Add `export KIPI_NOTIFY_RECEIPTS="$WORK/receipts.jsonl"` to one test file: one
line, fixes 91 of 91 rows today. Rejected because it is the 2026-08-01 scar
verbatim (see Alternatives) — it protects only this test on only the branches that
carry it, and the next suite re-opens the hole.

## Issues

```json
[
  {
    "id": "notify-ledger-fixture-chokepoint",
    "finding_id": "finding-1",
    "title": "A loopback webhook redirects the receipts ledger, so no test can write the production one",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/slack-notify.sh",
      "q-system/.q-system/scripts/test/test-notify-fixture-guard.sh",
      "q-system/.q-system/scripts/test/test-notify-ledger-isolation.sh",
      "q-system/.q-system/capability-manifest.json"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-notify-ledger-isolation.sh",
      "bash q-system/.q-system/scripts/test/test-notify-fixture-guard.sh",
      "env HOME=\"$(mktemp -d)\" bash q-system/.q-system/scripts/test/test-notify-fixture-guard.sh && test ! -e \"$HOME/.config/kipi/notify-receipts.jsonl\""
    ],
    "bypass_check": "The ledger path is resolved in exactly one place in slack-notify.sh, and the loopback decision reuses _kipi_loopback_host rather than a second host parser: grep -c '_kipi_loopback_host()' q-system/.q-system/scripts/slack-notify.sh returns 1 (one definition, no forked copy).",
    "acceptance": "Running the fixture-guard suite under a redirected HOME leaves no production ledger file. Deleting the redirect block turns test-notify-ledger-isolation.sh red (mutant killed). A non-loopback webhook still writes the production ledger."
  },
  {
    "id": "notify-quarantine-fixture-rows",
    "finding_id": "finding-2",
    "title": "Mark the 91 historical test rows as fixture rows, deleting nothing",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/notify-receipts-quarantine.py",
      "q-system/.q-system/scripts/test/test_notify_receipts_quarantine.py",
      "q-system/.q-system/scripts/notify-receipts-surface.py",
      "q-system/.q-system/capability-manifest.json"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_notify_receipts_quarantine.py"
    ],
    "bypass_check": "The quarantine is additive: run against a fixture ledger, the row count before equals the row count after, and no row loses a pre-existing key. Asserted in test_notify_receipts_quarantine.py rather than counted by grep.",
    "acceptance": "Every row whose message contains the suite probe carries fixture=true; total row count is unchanged; notify-receipts-surface.py excludes fixture rows from its founder-facing count and says how many it excluded."
  },
  {
    "id": "notify-fable-escalate-kind",
    "finding_id": "finding-3",
    "title": "The last bare notification call site declares --kind receipt, turning Gate 1.2b green",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/fable-escalate.py",
      "q-system/.q-system/tests/test_fable_escalation.py",
      ".claude/rules/fable-escalation.md"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/notify-callsite-audit.py --repo .",
      "python3 -m pytest q-system/.q-system/tests/test_fable_escalation.py -q"
    ],
    "bypass_check": "notify-callsite-audit.py --repo . exits 0, which is the invariant itself (zero bare call sites) rather than a proxy for it.",
    "acceptance": "Gate 1.2b exits 0. test_escalations_stop_at_the_cap_and_page_once still pins that the cap is recorded, updated to assert a recorded receipt rather than a delivered page, with the rule text in fable-escalation.md updated to match."
  }
]
```
