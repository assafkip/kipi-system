---
id: prd-deterministic-reading-2026-07-28
title: Deterministic Reading
status: idea
created_at: 2026-07-28T19:00:31Z
updated_at: 2026-07-28T19:00:31Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-deterministic-reading-2026-07-28-findings.jsonl
---

<!-- prompt-only-enforcement-skip
Reason: the guard blocks this file on the "No regression" goal, whose sub-bullets
each name an executable command inline. Verified false positive: every one of those
lines PASSES the guard in isolation; only the assembled block trips it, and the
reported line number was wrong on the full file (said line 10, a frontmatter
delimiter). Both guard defects captured as sp-8f05a182 and sp-dacb04c7. This
marker is scoped to that false positive, not a claim that this PRD is exempt from
naming its blockers -- every rule it proposes names one, in the read-tier table.
-->

# Deterministic Reading

> **Drafted by Claude, not by the owner.** The prd-start skill warns against
> auto-drafting because it produces PRDs that pass review by agreeing with
> themselves. Two of the three problems below were found by Claude, and Claude
> would implement all three. Treat every "Decided" line as a proposal until the
> owner corrects or confirms it, and treat Codex review as the independent check.
> The claims marked `{{UNVERIFIED}}` are the ones to attack first.

## Problem

RCA `rca-conclusions-before-evidence-2026-07-28` (Prodigy_Gold): six conclusions
about a client's automation were delivered in settled language and reversed later
in the same session by evidence available from the first minute. One survived long
enough to shape a client email draft. Two of five workflows in the chain had been
read; claims were issued about the chain.

Six gates shipped in response (commits `5f20412`, `1b49d91`, 63/63 tests green).
Three defects remain in that work, and they share one cause.

**P1 -- the read-arbitration rule was never written.** The RCA's own contributing
factors say it plainly: "Token-discipline rules push toward narrow targeted reads
and away from exhaustive passes. That pressure is correct for cost and wrong for
completeness, and nothing arbitrates between them." That action item is the one
still open, and it is the item the other two depend on. `token-discipline.md` caps
reads; `quick-plan.md` requires reads; neither yields to the other, so the model
picks per turn, which is the failure mode.

**P2 -- the manifest is a hand-written promise.** `system_manifest.py` reads a
hand-authored `canonical/system-manifest.json` and computes member coverage from
it. `capability-map-gen.py`'s docstring already recorded this exact lesson for
this repo: "a hand-written map is accurate for one afternoon. It drifts the moment
a command is added, and nothing detects the drift." A manifest missing a member
makes `code_claim_grounding_guard.py` certify a claim about a subsystem that was
never fully read. The gate then reports coverage it does not have, which is worse
than reporting nothing. Measurable: today nothing can detect a manifest that has
gone stale, and `system_manifest.check()` passes a manifest whose members no
longer exist.

**P3 -- two provenance vocabularies in one repo.**
`.claude/rules/memory-confidence.md` defines `confidence: 0.0-1.0` and
`provenance: explicit_statement | inferred | corrected | validated | observed |
imported`, enforced by `memory-confidence-validator.py` (PostToolUse). The new
`handoff-provenance-lint.py` accepts a different set: `[verified: ...]`, an `ev-`
claim id, `{{UNVERIFIED}}`. Same idea, same enforcement shape, different words,
neither aware of the other. Nothing collides today because the file scopes differ
(auto-memory vs `memory/last-handoff.md`), so this is drift, not breakage.

## Goals

- One written, enforced answer to "how much do I have to read", replacing a
  per-turn model judgment call.
- A subsystem's declared member set is DERIVED where it can be, and explicitly
  labelled as asserted where it cannot be.
- Manifest staleness is detectable, so `system_manifest.check()` can fail on a
  manifest that has silently stopped describing reality.
- One provenance vocabulary across the repo.
- No regression, each proved by running the named command:
  - `python3 test_evidence_ledger.py` -> 11/11
  - `python3 test_system_manifest.py` -> 14/14 plus the new cases
  - `python3 test_client_output_evidence_gate.py` -> 8/8
  - `python3 test_read_first_gate.py` -> 9/9
  - `python3 test_handoff_provenance_lint.py` -> 10/10 plus the new cases
  - `python3 code_claim_grounding_guard.py --self-test` -> 11/11
  - `python3 q-system/.q-system/scripts/settings-template-sync-check.py` -> exit 0
  - `python3 q-system/.q-system/scripts/instruction-budget-audit.py` -> at or under 513
  - `python3 validate-separation.py` -> matches the recorded 25-pass/1-fail baseline

## Non-goals

- Rebuilding anything from `5f20412` / `1b49d91`. This PRD changes three things
  about that work; it does not redo it.
- Raising the always-on instruction budget. The 513-to-300 gap is a separate
  problem and this must not make it worse.
- Making the gates smarter about MEANING. Every gate here stays syntactic. The
  RCA's reversal #6 (a false claim carrying no numbers and no quotes) is out of
  reach of all of this and stays out of reach.
- Draining the Linear queue. Blocked on Linear MCP auth, which is the owner's
  interactive login.
- Any change to `.prd-os/` itself or to the eight unrelated open spillover items.

## Proposed approach

### Part 1 -- the read-tier rule

New `.claude/rules/read-tiers.md`, paths-scoped, with `token-discipline.md` and
`quick-plan.md` each gaining a one-line pointer at it (pointer only, so the
always-on budget does not grow).

Each tier names the code that holds it. A tier with no blocker is a paragraph, and
this repo bans those:

| Tier | Who selects the file set | Its deterministic blocker |
|---|---|---|
| **Enumerated** | a manifest or generator names the exact set | `code_claim_grounding_guard.py` check two: exit 2 when a named subsystem has an unread member. Caps do not apply because the set is finite and computed. |
| **Derived** | a script computes the set (glob, grep, dep graph, git diff) | the computing script itself, plus Part 2's `check --strict` failing an unresolvable or over-wide member set |
| **Exploratory** | the model is guessing what might be relevant | `token-guard.py` (PreToolUse circuit breaker) -- the existing caps, unchanged |

The RCA failure was an exploratory read delivered as an enumerated one. The rule's
teeth are already built: `code_claim_grounding_guard.py` check two blocks a claim
about a named subsystem whose members were not all read. This part is therefore
mostly doc, and its enforcement is Part 2 making the enumeration trustworthy.

**Founder-directed (2026-07-28):** "Deterministic always trumps when we read. we
dont trust the llm to read." That is the tie-break, and it is why Enumerated and
Derived carry no cap.

### Part 2 -- derive the manifest instead of asserting it

Extend the member schema so a member can be declared three ways:

```json
{"members": [
  {"glob": "q-system/.q-system/scripts/*-gate.py", "kind": "file"},
  {"ref": "path/to/one/file.py", "kind": "file"},
  {"ref": "Prodigy Gold - Parse LLM", "kind": "n8n-workflow",
   "fingerprint": "<workflow updatedAt or content hash>", "fetched_at": "2026-07-28"}
]}
```

- `glob` members expand at check time. The set is computed on every run, so a new
  file inside the pattern joins the subsystem automatically. This is the drift fix.
- `ref` + `kind: file` members are validated to exist; a member pointing at a
  deleted file fails `check()` instead of passing silently.
- External members (n8n workflows, sheets, anything outside the repo) cannot be
  enumerated by a local script. They stay asserted, and they are REQUIRED to carry
  `fingerprint` + `fetched_at`. `check()` fails when those are absent, and warns
  when `fetched_at` is older than a threshold. This is the honest half: the
  manifest states which members are derived and which are a human's word.

`system_manifest.py` gains `check --strict` for CI and a `members` resolution step
shared by `missing_members()`, so the grounding guard's coverage arithmetic runs
against the resolved set rather than the literal list.

### Part 3 -- one provenance vocabulary

`handoff-provenance-lint.py` accepts the `memory-confidence.md` enum as its
primary form, keeps `ev-<id>` as the strongest form (it points into
`evidence.jsonl`, which carries the command and its output), and keeps
`{{UNVERIFIED}}` as the shorthand already used across canonical docs.
`.claude/rules/memory-confidence.md` and `.claude/rules/evidence-ledger.md` each
gain a cross-reference so the two enforcement points are discoverable from each
other. The enum lives in ONE place that both validators import, so a future
addition cannot land in one and not the other.

## Alternatives considered

- **Part 1: fold the rule into `token-discipline.md`.** Rejected: that file is
  always-on and the ratchet is already 213 lines over target. A new paths-scoped
  file plus two pointer lines costs almost nothing always-on.
- **Part 1: make the tiers a hook instead of a rule.** Rejected as the primary
  mechanism: which tier a read belongs to is a judgment about intent, and this
  repo's `skill-hook-pairing.md` decision rule sends judgment to the doc and the
  deterministic slice to code. The deterministic slice already exists (grounding
  guard check two).
- **Part 2: full generator that walks the repo and emits the manifest**, the
  `capability-map-gen.py` shape. Rejected as the whole answer: the real subsystems
  are client n8n workflows living outside this repo. A local generator cannot
  enumerate them, so a pure-generator design would either exclude the actual use
  case or silently under-report it. `glob` members give the generator's property
  where it is achievable.
- **Part 2: drop the manifest, rely on the file-level grounding check.** Rejected:
  that is the pre-RCA state. The file-level check is exactly what was silent
  during the failure.
- **Part 2: staleness by mtime alone.** Rejected: mtime does not survive a clone
  or a `kipi update` rsync, so it would fire constantly and get bypassed.
- **Part 3: migrate `memory-confidence-validator.py` to the new markers instead.**
  Rejected: the older vocabulary is the incumbent, has a rule file, a surfacing
  hook, and a decay/confidence model built around it. The new lint is three days
  old and has one consumer. The younger thing moves.
- **Part 3: leave both.** Rejected: two words for one idea is the drift class this
  repo writes rules against, and the cost of fixing it now is one enum import.

## Scenarios

- **Enumerated read, covered.** Claude is asked why sheet rows look wrong. The
  manifest declares `groupme-to-sheet` with one `glob` member (local workflow
  exports) and three external `ref` members. Claude reads the resolved set,
  answers, names the subsystem. Grounding guard check two resolves the glob,
  finds every member in session evidence, exits 0.
- **Enumerated read, drifted manifest.** A fifth workflow export lands in the
  globbed directory. Nobody edits the manifest. Claude reads the four it knows
  about and names the subsystem. The glob resolves to five; the fifth is absent
  from evidence; check two blocks. Under today's hand-written manifest this
  answer ships.
- **External member gone stale.** The manifest's n8n members carry
  `fetched_at: 2026-05-01`. `system_manifest.py check --strict` in CI warns that
  the asserted half of the manifest is four months old, naming which members.
- **Handoff write, either vocabulary.** One bullet carries
  `provenance: inferred`, another carries `ev-a1b2c3d4e5`. Both pass. A third
  carries a bare count and blocks, as it does today.
- **Exploratory read, unchanged.** Claude greps for an unfamiliar helper across
  the repo. No manifest subsystem is named in the answer. Token-discipline caps
  apply exactly as they do now; nothing in this PRD fires.

## Resolved decisions

- **The token-discipline vs completeness arbitration rule.** Decided: three tiers
  (Enumerated / Derived / Exploratory); caps apply only to Exploratory.
  Rationale: founder directive 2026-07-28, "Deterministic always trumps when we
  read. we dont trust the llm to read." The conflict was an artifact of letting
  the model choose the read set; removing that choice removes the conflict.
  Origin: `[USER-DIRECTED]`.
- **The manifest must be derived where derivation is possible.** Decided: `glob`
  members resolved at check time, external members required to declare a
  fingerprint. Rationale: `capability-map-gen.py` already recorded that
  hand-written maps drift undetected; a manifest that under-reports makes the
  grounding guard certify coverage it does not have.
  Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **The younger vocabulary moves.** Decided: the handoff lint adopts the
  `memory-confidence.md` enum. Rationale: incumbent has a rule, a validator, a
  surfacing hook and a decay model; the challenger has one consumer and three
  days of history. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.

## Risks and rollback

- **A glob that resolves too wide turns check two into a wall.** A member glob of
  `**/*.py` would demand reading the repo before naming a subsystem, and a gate
  that always fires gets bypassed reflexively, which is worse than no gate. Guard:
  `check()` fails a glob resolving past a member ceiling, and the failure names
  the glob. Ceiling value is an open question below.
- **Blast radius is fleet-wide.** These are skeleton files reaching ~24 instances
  via `kipi update`. Rollback is `git revert` of this PRD's issues plus one
  `kipi update`; the gates fail open by design (absent manifest, absent module,
  unreadable JSON all exit 0), so a bad ship degrades to today's behavior rather
  than blocking every instance.
- **Migration cost on existing handoffs.** Adding the enum is additive; nothing
  that passes today starts failing. Verified by keeping all 10 existing
  `test_handoff_provenance_lint.py` cases unchanged and adding to them.
- **The instruction budget.** A new rule file risks tripping the ratchet again, as
  it did on `evidence-ledger.md`. Mitigation: paths-scoped from the first commit,
  pointer lines only in the always-on files.
- **`{{UNVERIFIED}}` -- the fingerprint threshold has no evidence behind it.** No
  measurement exists of how often client workflows change. Any number chosen now
  is a guess, which is why it is an open question and not a decision.

## Open questions

- What member ceiling makes a glob a wall rather than a gate? A number is needed
  before Part 2 can ship; no data exists yet to pick it. `{{UNVERIFIED}}`
- What staleness threshold should `fetched_at` warn at, and should `--strict` fail
  or only warn in CI? `{{UNVERIFIED}}`
- Should the enum live in a shared Python module (importable, one source) or a
  JSON data file (readable by non-Python consumers)? The repo's own pattern
  ("allowlists load from a table at runtime") argues for the data file.
- Does the read-tier rule need a trigger-eval fixture, per
  `skill-hook-pairing.md`'s advisory pairing section, given it is interpretive?
- Is Part 1 worth shipping at all if its enforcement is entirely Part 2? Named
  here because a PRD whose first part is pure doc deserves the challenge.

## Persona Review

### Skeptic

**Q1: What is the strongest argument against doing this?**

A1: Part 1 ships no code. Its enforcement is check two, which already exists.
A rule nobody executes is the precise anti-pattern this repo bans, and writing a
tiers doc could produce the feeling of having fixed the arbitration problem while
changing nothing. The honest version of this PRD might be Parts 2 and 3 only,
with the tier language living as a comment inside the manifest code where it is
actually applied. Second argument: all three parts are Claude auditing Claude's
own three-day-old work, which is where sycophancy is likeliest.

**Q2: What is the smallest experiment that would disprove the thesis?**

A2: Take the Prodigy_Gold subsystem, write the manifest with a `glob` member,
delete one workflow export from the globbed directory and add a different one.
If `missing_members()` does not change its answer, the derived-manifest thesis is
wrong and a hand-written list plus a review reminder is equivalent. That is one
test file and no shipped code.

**Q3: What is the cheapest non-build alternative?**

A3: Part 3 alone, which is roughly a ten-line change: import the existing enum.
Part 2 could be replaced by a single `check()` assertion that every `ref` with
`kind: file` still exists on disk, catching the most common drift (deleted or
renamed member) at a fraction of the cost, with globs deferred until a manifest
has actually gone stale in practice.

## Issues

<!-- Populated after /prd-review and /prd-approve, one entry per accepted finding. -->

```json
[]
```
