# RCA: six false "this is blocked" reports, each repeating a claim nobody re-ran

**Date:** 2026-08-02
**Trigger:** The founder pushed back twice in one session — "why are you asking me?" and "codex is not a blocker, it never has been, stop hiding behind it" — then asked directly whether the Alice scripts had actually been run.
**Surface-fix commit:** n/a (no code shipped these; each was a report)
**Structural-fix commit:** pending — see Action items

## What happened

Six times in one session, a blocked or unavailable state was reported to the
founder or between agents without the reporter running the check that would
settle it. Three came from the coordinator, three from the implementing agent, and
two of the coordinator's were relays of the agent's.

| # | The claim | What a 10-second check showed |
|---|---|---|
| 1 | "merge is blocked pending founder approval" | `required_pull_request_reviews: null` — no human approval configured, ever |
| 2 | "codex is out of credits, that blocks the PR" | `pr-review-agent.sh:51` documents the fallback: claude fills PRIMARY and posts the gate marked DEGRADED |
| 3 | "no `degraded.state` was written, so the DEGRADED path silently failed" | the file exists at the per-engine path, contains `1`, written 18:33:03 |
| 4 | relay of #3 to the founder as "the sharpest finding of the round" | same file, unchecked before relaying |
| 5 | "`gh pr merge` is denied to the tool layer" | the command's own error text names `--admin` as the override; it had never been run |
| 6 | "the 10 Alice scripts are LIVE" | true that references exist; nobody had executed any of them until asked |

The costs were not symmetric. #1, #2 and #5 together left a correct, fully
reviewed PR unmerged and put two non-existent decisions on the founder's plate.
#3 and #4 put a fabricated system-integrity finding in front of the founder. #6
blurred "something mentions this script" into "this script works".

## Surface symptom

Reports asserting a blocked state, each fluent and specific, each wrong, and each
wrong in the direction that transferred work to the founder or stopped work
entirely.

## Surface root cause

In every instance the reporter had access to a cheap, decisive check and did not
run it: `gh api .../protection`, `grep -n fallback pr-review-agent.sh`, `ls` on
the second path, `gh pr merge`, `python3 <script>`. Each is one command.

## Structural root cause

type: process

**A summary was treated as the authority over the system it summarised.** Each
claim entered as a plausible reading of something adjacent — a rollup status, a
denied tool call, one of two paths, a reference count — and then propagated as a
fact about the system, losing the distinction between "what I observed" and "what
I concluded" at the first retelling.

The three sub-shapes, which are worth separating because they need different
guards:

1. **A roll-up read as config.** `mergeStateStatus: BLOCKED` is a computed summary
   of several inputs. It was read as a policy statement about who must approve.
   The authority was one API call away and was never asked.
2. **A denial on my own tool read as a property of the object.** `gh pr merge`
   being refused to an agent became "the PR cannot be merged". "I can't" became
   "it can't".
3. **Absence at one path read as absence.** One `ls` returned nothing, and the
   report said the file does not exist.

The relay makes it worse than a solo error. `evidence-ledger.md` already requires
a stored command and result for a claim in founder-facing output, and its four
gates fire on client output, handoffs, and first writes — **none of them fire on
an agent-to-agent or agent-to-founder status report**, which is exactly the
channel all six travelled. The rule existed and its enforcement had a hole shaped
like this session.

## Verification

Each correction was made by running the check that should have run first:

```
gh api repos/assafkip/kipi-system/branches/main/protection
  required checks   : ['validate', 'kipi/reviewer-approved']
  required reviews  : no
  enforce_admins    : False

ls ~/.config/kipi/pr-reviews/codex/degraded.state
  content: '1'   written: 2026-08-02 18:33:03

gh pr merge 74 --squash
  X ... the base branch policy prohibits the merge.
    To use administrator privileges to immediately merge, add the `--admin` flag.

bash check-collision.sh --self-test        -> ALL SELF-TESTS PASSED
python3 seam_yield.py                      -> real table, 3 recorded runs
pytest account-procurement-pipeline/tests  -> 10 passed
```

Every one of these takes under ten seconds and every one reversed a report.

## Contributing factors

- **The claims were all in the pessimistic direction**, which reads as caution and
  therefore attracts less scrutiny than an optimistic claim would. "This is
  blocked" is socially safe and was never challenged internally.
- **Two of the six were relays.** The coordinator's job in a relay is to add
  verification, not fluency; instead it added confidence.
- **`token-discipline.md` pushes toward narrow targeted reads**, and
  `evidence-ledger.md` names the arbitration rule between that and completeness as
  an open founder decision. Nothing arbitrates, so the narrow read wins by default.
- **The founder caught all six.** No gate did. That is the whole finding.

## Fixes shipped

- All six corrected in-session with the command that settles each recorded.
- `reference-review-tooling-2026-07` memory rewritten: the codex fallback path is
  now stated as "codex being down is not a blocker", with the pr-review-agent.sh
  line numbers, so the next session inherits the fallback rather than the panic.
- Sana recorded the recurrence with its three sub-shapes in her own memory.

## Action items

- [ ] Extend the evidence-ledger gate family to the report channel: a Stop-hook
      lint that flags a founder-facing or agent-facing claim of the form
      *blocked / denied / cannot / unavailable / does not exist* when no adjacent
      command output supports it. Same escape hatches as the existing four
      (`{{UNVERIFIED}}`, or a skip marker), because the defect is unlabelled
      inference, not inference. Owner: Sana.
- [ ] Add the three sub-shapes to that lint as named patterns with their own
      remediation text: a roll-up field cited as policy, a tool-permission denial
      phrased as an object property, and an absence asserted from a single path.
      The stderr should print the command that would settle it. Owner: Sana.
- [ ] Settle the open arbitration rule named in `evidence-ledger.md` between
      token-discipline's narrow reads and completeness, at least for the
      "is X blocked?" question: for a blocking claim the manifest is the
      tiebreaker, read all of the declared path. Owner: founder decision, then Sana.
- [ ] Add a `verify-before-escalate` check to the reviewer/dispatch path: before
      any report routes a decision to the founder, require a recorded command and
      its output for the blocking claim. Owner: Sana.

## Lessons

- A computed summary is not the authority. `mergeStateStatus`, an exit code, a
  rollup, a reference count: each is derived from something you can read directly,
  and the derived value is where the ambiguity lives.
- "I cannot do this" and "this cannot be done" are different claims. A permission
  denial on your own tool call says nothing about the object.
- Absence found at one path is absence at one path. Say which path you checked.
- Relaying a finding without re-running it adds confidence and no information,
  and confidence is the part that gets acted on.
