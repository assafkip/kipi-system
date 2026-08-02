---
id: prd-terminal-state-redrive-2026-08-01
title: Terminal State Redrive
status: approved
created_at: 2026-08-01T19:26:38Z
updated_at: 2026-08-01T19:41:17Z
owner: assafkipnis
reviewers:
  - codex-review
findings_path: .prd-os/findings/prd-terminal-state-redrive-2026-08-01-findings.jsonl
codex_reviewed_at: 2026-08-01T19:35:24Z
reviewed_by: codex-review
---

# Terminal State Redrive

> **Revised 2026-08-01 after codex-review returned 16 findings (6 blockers).**
> The v1 premise — "copy the working `needs-scope` consumer" — was FALSE and is
> retracted below. Finding 1 was independently verified against source before
> this rewrite. The problem is larger than v1 stated, and the scope is smaller.

## Problem

The Linear loop's abnormal exits have **zero** working machine consumers. Not
three, as v1 of this PRD claimed. Verified 2026-08-01:

**The one consumer that was believed to work does not exist.**
`linear-worker.sh` tells the operator, on every `needs-scope` refusal, that
*"linear-dor-drafter.py re-scopes this into a Definition of Ready that is
achievable... no action is needed from the founder."* That is false:

- `linear-dor-drafter.py` `needs_dor()` returns `False` when the description
  contains `Definition of Ready`.
- A `needs-scope` issue **has** a DoR. Having a bad one is why Sana refused it.
- The drafter never queries labels at all (zero `labels` references in the file).
- The string `needs-scope` appears **zero** times in the drafter.

So a `needs-scope` refusal is parked permanently, behind a message asserting the
opposite. ASK-148 is in that state now and will never move.

**The founder is not an available actor.** He has stated he does not read or work
on code (2026-08-01, third recurrence; memory `founder-never-the-next-actor`). A
state whose only continuation is "the founder acts" does not continue.

**This class was found before and resolved the wrong way.** `linear-worker.sh:680`
carries the comment *"NOTHING IS TERMINAL WITHOUT A NAMED HUMAN ACTION
(sp-58f0ec83)."* A prior pass noticed the same defect and fixed it by naming the
human more clearly, rather than by naming a machine. That is the correction this
PRD makes.

### The states, classified (they are not one thing)

v1 treated nine sites as one class. They are four, with different semantics, and
conflating them was itself a design error:

| Class | Members | What "consumer" means here |
|---|---|---|
| **Durable queues** | `needs-scope`, `owner:assaf`, `blocked:capability` | A label a worker applies; something must poll and act on it |
| **Selection filters** | out-of-repo (`ready()`), no-DoR (`ready()`) | Never entered a state; excluded at pick time. Needs a *different picker*, not a consumer |
| **Transient** | auto-merge unarmed | Self-heals on the next run. Already correct; no work |
| **Exhausted counters** | stuck (`:680` gate, `:1253` page), drift cap, conflict cap | A budget ran out. Needs either a different actor or an honest terminal |

Line numbers above are indicative only; see Resolved decisions on registry identity.

### Measured cost (verified 2026-08-01)

- 10 issues parked at `blocked:capability`; `dispatch.log` logged
  `nothing ready (0 ready issue)` every 15 min from 14:24Z to 19:10Z.
- 1 issue (ASK-148) parked at `needs-scope` behind a false promise.
- 18 ready-shaped `owner:sana` issues across 14 projects skipped as out-of-repo
  every cycle (`sp-2b59e681`). One dispatch job exists fleet-wide.
- ASK-274 (Urgent, client-blocking, 3 zero-row days on a paid deliverable) sat
  2 days invisible and moved only when the founder asked by hand.

## Goals

- `needs-scope` actually redrives. The promise the worker already prints becomes true.
- A validator that enumerates terminal states **from the source**, not from a
  hand-written list, and proves each named consumer is *live*, not merely present.
- The 18 out-of-repo issues become pickable, without putting client repos at risk.
- Where no machine actor genuinely exists, the state is declared an **honest
  terminal** with a written rationale — not given a fake tier to satisfy a check.

## Non-goals

- No new orchestrator, queue broker, or workflow engine.
- Not granting any agent a permission it lacks (2026-05-17 scar).
- Not clearing the 342-item spillover backlog.
- **Not inventing an escalation tier for every state.** Codex finding 5 is
  accepted: drift rounds already end in a Codex review with an Opus fallback, so
  "add a Codex tier to drift" is a validator-satisfying fiction. It is dropped.
- `owner:assaf` stays a founder queue. It is the designed one.

## Proposed approach

Three sequenced pieces. Each is independently shippable and independently green.
v1's four-piece split was rejected by finding 10 (colliding `allowed_files`).

**Piece A — make `needs-scope` real (the confirmed-broken consumer).**
Extend `linear-dor-drafter.py` to select label-driven rework: fetch labels, and
treat `needs-scope` as a *redraft* input (rewrite the existing DoR) rather than
excluding it for having one. On success, remove the label so the picker offers it
again. Files: `linear-dor-drafter.py` + its test. Touches no worker code, so it
cannot collide with in-flight ASK-281.

**Piece B — the validator, enumerating from source.**
`test-terminal-states.sh` parses `linear-worker.sh` for every exit that removes an
issue from the run (each `continue` in the issue loop, each label-apply, each
`ready()` exclusion predicate) and requires a registry row for each. Findings 2
and 4 are accepted in full: a hand list cannot detect a tenth dead end, and
existence-plus-wiring does not prove continuation. So each row must declare a
`consumer` **and** a `liveness_check` — a command that proves the consumer ran
recently (a launchd job loaded AND with a run inside its interval, not a plist on
disk; finding 14). A row may instead declare `terminal: true` with a
`rationale` — an honest dead end is allowed, an unexamined one is not.

**Piece C — out-of-repo pickup, gated behind a client preflight.**
Deferred until A and B are green. Finding 8 is accepted: opt-in plus a project
filter does not protect Alice or Prodigy_Gold from a dispatcher that runs their
local `./kipi`, pushes branches, and arms auto-merge. C does not start until a
per-repo preflight exists covering control-code version, hook presence, remote
identity, branch protection, dirty state, and a per-repo kill switch. Finding 9
is accepted: selection must be round-robin with a recorded cursor, not
registry-order.

**Prior art (recorded before building, per founder directive).** DLQ + redrive
(SQS/RabbitMQ DLX/Kafka DLT), supervisor escalation (Erlang/OTP), reconcile-requeue
(Kubernetes), ordered escalation policies (PagerDuty). The in-repo claim that this
shape already works here is **retracted** — nothing in this repo implements it
today. The industry pattern is still the right one to copy; the repo simply has no
instance of it yet.

## Alternatives considered

- **Fourteen per-repo launchd jobs.** Rejected: 14 jobs that die quietly is the
  income-scanner failure (6 days dark, 2026-07).
- **A workflow engine (Temporal/Airflow/Step Functions).** Rejected: correct
  semantics, wrong cost, and it would replace a working scheduler and board.
- **Fix each dead end as it bites.** Rejected: the status quo; produced three
  instances of one finding in a single session.
- **A rule file in `.claude/rules/` with no paired checker.** Rejected: it would
  be blocked on write by `q-system/.q-system/scripts/prompt-only-enforcement-guard.py`
  (PostToolUse), and `skill-hook-pairing.md` requires a deterministic rule to ship
  its checker. The deterministic blocker this PRD ships instead is Piece B's
  `test-terminal-states.sh`, run by `kipi check`.
- **A hand-maintained registry (v1's design).** Rejected by finding 4 — it cannot
  see a tenth dead end. Replaced by source enumeration in Piece B.
- **A universal escalation tier on every state.** Rejected by finding 5 — it
  manufactures fake consumers. Replaced by `terminal: true` + rationale.

## Scenarios

- **`needs-scope` redrives.** Sana refuses ASK-148: the DoR is unbounded. The
  drafter's next nightly run selects it *because* of the label, rewrites the DoR,
  drops the label. The picker offers it the following cycle. No founder message.
- **An honest terminal is declared.** "Worktree holds local work and cannot be
  repositioned" has no plausible machine actor. Its registry row sets
  `terminal: true` with a rationale. The validator passes, and the row documents
  that a human really is required — which is different from a state that quietly
  assumed one.
- **A tenth dead end is added.** Someone adds a `continue` in the issue loop with
  no registry row. Piece B's source enumeration finds the unregistered exit and
  `kipi check` goes RED naming the line. A hand list would have missed it.
- **A dead consumer is caught.** `com.kipi.linear-dor` is unloaded by a bad
  `kipi update`. Its `liveness_check` finds no run inside the interval and the
  validator goes RED, instead of certifying a plist that no longer runs.

## Resolved decisions

- **Registry identity is a stable marker, not a line number.** Finding 15
  accepted: v1's cited sites were partly wrong (`:1297` resets variables, `:1295`
  is a comment, the real stuck gate is `:680`), and line numbers drift on the
  first nearby edit. Rows key on a stable token (label name, sentinel filename,
  predicate function name) that the source enumerator locates at runtime.
- **Sequencing over parallelism.** Finding 10 accepted. A → B → C in series.
  Piece A touches only the drafter, so it cannot collide with ASK-281's edits to
  `linear-worker.sh` and `test-worker-refusal.sh`. C waits for B.
- **Escalation flags are not stored in the attempts ledger.** Finding 12
  accepted. `attempts-ledger.py` is out of scope (`sp-626e9452`, founder-deferred)
  and a direct read-then-write from the worker would recreate the race that file
  exists to prevent. Any state Piece C needs goes in its own single-writer store.
- **V1 (why the drafter never reached ASK-274) is promoted to a prerequisite of
  Piece A**, not a verification detail. Finding 13 accepted; the unsorted
  `todo[:limit]` batch at `linear-dor-drafter.py:508-525` is a live starvation
  candidate and Piece A changes that same selection path.
- **The PRD and its source plan get committed before approval.** Finding 16
  accepted: an untracked spec cannot substantiate a review chain.
- **Who authored this PRD.** Drafted by Claude from
  `q-system/output/plans/terminal-state-redrive-2026-08-01.md`, against
  `/prd-start`'s "do not auto-draft" instruction. That instruction exists to stop
  a PRD passing review because Claude agreed with itself. The founder has ruled
  himself out as author of anything code-shaped, so the alternative was no PRD.
  The check was relocated, not dropped — and it worked: Codex returned 6 blockers
  including one that falsified the core premise, and this document was rewritten
  rather than approved. Finding 16 is right that this is adversarial analysis and
  not proof of independent authorship; recorded as a known limit. `[SYSTEM-INFERRED]`

## Risks and rollback

- **Blast radius.** `q-system/.q-system/scripts/` propagates fleet-wide via
  `kipi update`. `kipi-dispatch.sh` is repo-root and does not (RULE-2026-06-30-A).
- **Piece A can rewrite a good DoR.** A redraft loop that keeps producing
  unexecutable specs would cycle an issue between Sana and the drafter. Mitigation:
  cap redrafts per issue and declare the cap's own exhaustion an honest terminal
  with a rationale — not a new fake tier.
- **Piece C is the real risk and is why it is last.** A dispatcher entering client
  repos can push and auto-merge in them. It does not start until the preflight in
  Piece C's own acceptance exists.
- **Rollback.** A is additive to one script plus its test; revert the commit. B is
  a new JSON file and a new test; delete both. C is not started until A and B are
  green, so there is nothing to roll back before then.
- **False green.** Addressed directly by `liveness_check` (finding 14) and source
  enumeration (finding 4) rather than by intent.

## Open questions

- Does `needs-scope` redraft belong in `linear-dor-drafter.py` or in a sibling
  script? One file, two selection modes, is simpler but makes the drafter's
  single responsibility ("issues with no DoR") into two.
- Piece B must decide what counts as "recently ran" per consumer class. A nightly
  job and a 15-minute job need different windows, and a wrong window is a flaky
  gate — the failure mode most likely to get a validator disabled.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: That Piece A alone may fix most of the observed pain, and B and C are
speculation. `needs-scope` being broken is a confirmed, concrete, one-file bug
with real issues stuck behind it. The registry is infrastructure for a class of
future defects, which is a weaker claim than a bug with a name.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Piece A shipped alone. If `needs-scope` redrives and the parked issues start
moving, the thesis holds for durable queues. ASK-281 is the parallel experiment
for `blocked:capability`; `sp-52390281` (the sensitive-path guard blocks any path
containing `.claude/`) is live evidence its Codex tier may not work either. If
both A and ASK-281 fail, the answer is not more tiers — it is that these states
are honest terminals and the loop's real ceiling is narrower than assumed.

Q3: What is the cheapest non-build alternative?
A3: Fix `needs_dor()` to also select on the `needs-scope` label — a few lines in
one function. That is roughly Piece A minus the redraft-cap and the tests. It
would make the existing false promise true, and it is a fraction of this PRD's
cost. It leaves B and C unbuilt, which is a defensible place to stop.

## Issues

Four entries, one per accepted finding. `allowed_files` overlap only on
`capability-manifest.json` (issues 2 and 3), which is safe because prd-os permits
exactly one active issue at a time and the Resolved decisions fix the order
A → B → C. The other twelve findings are rejected with rationale in the findings
file: seven were remedied by removing the design element they attacked, five are
duplicates whose remedy lives inside one of the entries below.

```json
[
  {
    "id": "needs-scope-redrive",
    "finding_id": "finding-1",
    "title": "Piece A: linear-dor-drafter consumes needs-scope, so the promise the worker already prints becomes true",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/linear-dor-drafter.py",
      "q-system/.q-system/scripts/test/test-linear-dor-drafter*.sh",
      "q-system/.q-system/scripts/test/test_linear_dor_drafter*.py"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh"
    ],
    "bypass_check": "A fixture issue carrying BOTH a '## Definition of Ready' heading AND the needs-scope label is SELECTED by the drafter's selection predicate. This is the exact case needs_dor() excluded, so a green here means the exclusion is gone rather than renamed.",
    "acceptance": "Observed RED first against current needs_dor(), which returns False for any description containing 'Definition of Ready'. Drafter fetches labels (it queries none today). A needs-scope issue is redrafted, not skipped, and the label is removed on success so the picker offers it again. Redraft attempts are capped per issue and the cap's exhaustion is recorded as an honest terminal with a rationale, never a new tier. PREREQUISITE (finding-13): determine why the drafter never reached ASK-274 and pin the answer with a test; the unsorted todo[:limit] batch at linear-dor-drafter.py:508-525 is the live starvation candidate and this issue changes that same selection path. Touches no worker code, so it cannot collide with in-flight ASK-281."
  },
  {
    "id": "terminal-states-validator",
    "finding_id": "finding-2",
    "title": "Piece B: a validator that enumerates exits from source and proves each consumer is live, not merely present",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/terminal-states.json",
      "q-system/.q-system/scripts/test/test-terminal-states.sh",
      "q-system/.q-system/capability-manifest.json"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-terminal-states.sh"
    ],
    "bypass_check": "The validator has a negative self-test that FAILS on a fixture row whose only actor is the founder, and a second that FAILS on a row naming a consumer whose liveness_check reports no run inside its interval. A gate that cannot be shown failing is not a gate.",
    "acceptance": "Exits are enumerated FROM q-system/.q-system/scripts/linear-worker.sh at runtime (every continue in the issue loop, every label-apply, every ready() exclusion predicate), never from a hand list -- finding-4. An unregistered exit makes kipi check RED and names the site. Each row declares a consumer AND a liveness_check proving the consumer ran inside its interval, not a plist present on disk -- finding-14. A row may instead declare terminal:true with a written rationale; an honest dead end passes, an unexamined one does not. Rows key on stable markers (label name, sentinel filename, predicate function name), never line numbers -- finding-15, whose mis-cited sites (:1297 resets variables, :1295 is a comment, the real stuck gate is :680) are the evidence. Registered in capability-manifest.json and wired into kipi check."
  },
  {
    "id": "fleet-dispatch-preflight",
    "finding_id": "finding-8",
    "title": "Piece C: no repo is dispatched into until a preflight passes, and selection is round-robin",
    "priority": "p2",
    "allowed_files": [
      "kipi-dispatch.sh",
      "instance-registry.json",
      "q-system/.q-system/scripts/repo-preflight.sh",
      "q-system/.q-system/scripts/test/test-repo-preflight.sh",
      "q-system/.q-system/capability-manifest.json"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-repo-preflight.sh"
    ],
    "bypass_check": "The dispatcher REFUSES a registry repo whose preflight fails, proven by a fixture repo that fails one preflight item and is then absent from the dispatcher's dry-run pick list. There is no flag, env var, or registry field that skips the preflight.",
    "acceptance": "STARTS ONLY after needs-scope-redrive and terminal-states-validator are green. Preflight covers control-code version, hook presence, remote identity, branch protection, credentials, dirty state, and a per-repo kill switch -- opt-in plus a project filter is NOT protection for Alice or Prodigy_Gold, which this dispatcher would otherwise push to and auto-merge in. Selection is round-robin with a recorded cursor, not registry order, so a nonempty early repo cannot starve later client repos -- finding-9. 'Lists ready issues from two repos' is explicitly NOT sufficient; the check must show eventual pickup of a repo that sorts last."
  },
  {
    "id": "commit-prd-review-chain",
    "finding_id": "finding-16",
    "title": "Commit the spec and its source plan so the review chain is substantiable",
    "priority": "p1",
    "allowed_files": [
      ".prd-os/prds/prd-terminal-state-redrive-2026-08-01.md",
      ".prd-os/findings/prd-terminal-state-redrive-2026-08-01-findings.jsonl",
      "q-system/output/plans/terminal-state-redrive-2026-08-01.md"
    ],
    "required_checks": [
      "git ls-files --error-unmatch .prd-os/prds/prd-terminal-state-redrive-2026-08-01.md q-system/output/plans/terminal-state-redrive-2026-08-01.md"
    ],
    "bypass_exempt": "Committing tracked files has no bypass surface: the required_check IS the invariant (git refuses to match an untracked path), and there is no code path that could satisfy it while leaving the spec untracked.",
    "acceptance": "Both the PRD and its source plan are tracked in git. The frontmatter reviewers field names the review that ran. NOTE the honest limit finding-16 raises and this issue does NOT close: a codex-review stamp is adversarial analysis, it is not proof of independent AUTHORSHIP, and this PRD was drafted by Claude. That limitation is recorded in Resolved decisions and stays true after this issue closes. q-system/output/plans/ is excluded from kipi update sync, so the plan stays instance-local by design."
  }
]
```
