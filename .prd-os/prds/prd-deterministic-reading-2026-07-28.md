---
id: prd-deterministic-reading-2026-07-28
title: Deterministic Reading
status: in-review
created_at: 2026-07-28T19:00:31Z
updated_at: 2026-07-28T19:07:56Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-deterministic-reading-2026-07-28-findings.jsonl
codex_reviewed_at: 2026-07-28T19:22:16Z
---

<!-- prompt-only-enforcement-skip
Reason: the guard blocks this file on the "No regression" goal, whose sub-bullets
each name an executable command inline. Verified false positive: every one of those
lines PASSES the guard in isolation; only the assembled block trips it, and the
reported line number was wrong on the full file. Both guard defects captured as
sp-8f05a182 and sp-dacb04c7.
-->

# Deterministic Reading

> **v2, re-cut after the v1 Codex review and a prior-art miss.** v1 proposed a
> three-tier read rule plus a new manifest. The reviewer's lead blocker was that
> the model still chose its own tier and could dodge by not naming a subsystem.
> The owner then asked whether a deterministic read mechanism already existed. It
> does, three times over, and v1 had missed all three. v2 extends the existing
> mechanism instead of inventing a parallel one. The v1 findings are answered one
> by one in `## How v2 answers the v1 review`.
>
> **Still drafted by Claude, not the owner.** Two of the three problems were found
> by Claude and Claude would implement all of it. Attack the `Resolved decisions`
> first; each is a proposal until the owner confirms it.

## Problem

RCA `rca-conclusions-before-evidence-2026-07-28` (Prodigy_Gold): six conclusions
about a client's automation were delivered in settled language and reversed later
in the same session by evidence available from the first minute. One shaped a
client email draft. Two of five workflows in the chain had been read; claims were
issued about the chain.

Six gates shipped in response (commits `5f20412`, `1b49d91`, 63/63 green). Three
defects remain in that work.

**P1 -- reading is still a model decision.** `token-discipline.md` caps reads,
`quick-plan.md` requires reads, and the model arbitrates per turn. Founder
directive 2026-07-28: "Deterministic always trumps when we read. we dont trust the
llm to read."

**PRIOR ART v1 MISSED.** This repo already answers P1, three times:

| Mechanism | What it does |
|---|---|
| `voice-dna-loader.py` | UserPromptSubmit hook. Regex-detects a writing request, reads the voice files, injects their CONTENT via `additionalContext`. Docstring: "Injects both as additionalContext so Claude literally cannot draft" without them. |
| `firecrawl-scrape.py` | Persists the FULL source markdown to a file "instead of summarizing it into context". Fails CLOSED on an empty body. |
| `canonical-digest.py` | Regex-parses every canonical file. Docstring: "Replaces the 00c-canonical-digest LLM agent." |

One principle, already proven here: **do not ask the model to read; have a script
read and hand it the bytes.** `read-first-gate.py` (shipped in `1b49d91`) is the
inferior inverse. It blocks until the model reads, which still lets the model pick
what and when, and costs a blocked turn. A loader has nothing to dodge because
there is no trigger phrase to avoid.

**P2 -- coverage is declared by hand, in a second graph.** `system_manifest.py`
reads a hand-authored `canonical/system-manifest.json`. Two problems.
(a) `capability-map-gen.py` already recorded that hand-written maps "drift the
moment a command is added, and nothing detects the drift"; a manifest missing a
member makes `code_claim_grounding_guard.py` certify coverage it does not have.
(b) `ripple-graph.json` already declares file-level related-set edges (12 sources,
enforced by `ripple-verify.py`). It answers write-time ripple ("I changed X, what
else must change"); this work needs read-time coverage ("I am claiming about X,
what must I have read"). Same graph shape, opposite direction, currently two files.

**P3 -- two provenance vocabularies.** `.claude/rules/memory-confidence.md`
defines `confidence: 0.0-1.0` and `provenance: explicit_statement | inferred |
corrected | validated | observed | imported`, enforced by
`memory-confidence-validator.py`. `handoff-provenance-lint.py` accepts a different
set. Same idea, different words, neither aware of the other.

## Goals

- Required reading arrives in context WITHOUT the model choosing it, by extending
  the loader pattern rather than adding a rule about it.
- One graph of related files, not two.
- A gate that is absent behaves differently from a gate that is broken.
- One provenance vocabulary, from one source both validators read.
- No regression, each proved by running the named command:
  - `python3 test_evidence_ledger.py` -> 11/11
  - `python3 test_system_manifest.py` -> 14/14 plus new cases
  - `python3 test_client_output_evidence_gate.py` -> 8/8
  - `python3 test_read_first_gate.py` -> 9/9
  - `python3 test_handoff_provenance_lint.py` -> 10/10 plus new cases
  - `python3 code_claim_grounding_guard.py --self-test` -> 11/11
  - `python3 q-system/.q-system/scripts/ripple-verify.py` -> exit 0
  - `python3 q-system/.q-system/scripts/settings-template-sync-check.py` -> exit 0
  - `python3 q-system/.q-system/scripts/instruction-budget-audit.py` -> at or under 513
  - `python3 validate-separation.py` -> matches the recorded 25-pass/1-fail baseline

## Non-goals

- The three-tier read rule from v1. Deleted, not deferred. A loader removes the
  decision the tiers described, so the rule would be prose about a choice nobody
  makes. This is the v1 reviewer's lead blocker, accepted in full.
- External (non-file) members in the schema. v1 required a `fingerprint` on n8n
  workflows with no command to fetch or verify one, which the reviewer correctly
  called metadata theatre. Deferred until a fetch path exists.
- Rebuilding anything from `5f20412` / `1b49d91` beyond the changes named here.
- Raising the always-on instruction budget.
- Making gates smarter about MEANING. RCA reversal #6 (a false claim carrying no
  numbers and no quotes) is out of reach of all of this and stays out of reach.

## Proposed approach

### Part A -- `subsystem-loader.py`, modeled on `voice-dna-loader.py`

A script decides; the model never votes. Two deterministic triggers, neither
requiring the model to declare or name anything:

1. **Prompt trigger** (UserPromptSubmit, exactly `voice-dna-loader.py`'s shape):
   the USER's prompt names a declared group, matched by the existing
   `system_manifest.mentions()`. Inject the group's member list and content.
2. **Touch trigger** (PostToolUse on Read/Grep/Bash): a tool call touched a member
   of a declared group. Inject the group's REMAINING members. This is the RCA case,
   where the founder asked "why does the form have no traffic", named no subsystem
   at all, and a prompt-only trigger would have missed it.

`{{UNVERIFIED}}` -- that PostToolUse supports `hookSpecificOutput.additionalContext`
the way UserPromptSubmit does. `voice-dna-loader.py:152` proves the
UserPromptSubmit path only. If PostToolUse cannot inject, trigger 2 degrades to
emitting the sibling list to stderr, which is weaker and must be said out loud
rather than assumed. The first issue verifies this before anything is built on it.

**Injection budget.** A group whose members exceed a byte ceiling injects the
member list plus each member's first N lines, not full content, and says so in the
injected text. A loader that blows the context window is a loader that gets turned
off.

### Part B -- one graph, two edge types

Rather than a second file, extend `ripple-graph.json` with a read-time edge type,
keeping `ripple-verify.py`'s existing write-time behavior untouched:

```json
{"_version": 2,
 "graph": {"canonical/objections.md": ["canonical/talk-tracks.md"]},
 "read_groups": {
   "groupme-to-sheet": {
     "name": "GroupMe order intake",
     "members": [{"glob": "workflows/prodigy-*.json"}]}}}
```

- **`glob` is the only member form for files.** v1 allowed a bare `ref`, which the
  reviewer noted leaves hand-written drift available by default. A single file is a
  glob matching one path. `check` REJECTS a bare file `ref`.
- **Ceiling.** A glob resolving past a member ceiling fails `check` and names the
  glob, so a group cannot silently become "read the repo".
- **Honest scope.** A glob detects additions only inside a pattern someone chose.
  It does not prove the pattern describes the subsystem. That is a real residual
  gap, stated here rather than claimed away, and it is why Part A matters more than
  Part B: the loader helps on every fire without needing the group to be complete.

### Part C -- absent is not broken

`code_claim_grounding_guard.py`, `system_manifest.py` and the loader currently exit
0 on absent manifest, missing module, AND unreadable JSON. The reviewer's second
blocker: that fails open exactly when the evidence path is corrupt.

Split the two cases:

| Condition | Behavior | Why |
|---|---|---|
| No `read_groups` declared | exit 0, silent | The feature is not in use. Every instance starts here. |
| Module missing / import fails | exit 0, silent | An older instance mid-`kipi update`. |
| `read_groups` present but unparseable, or a glob unresolvable | **exit 2** | Something that was working is now broken. Failing open here certifies coverage nobody computed. |

### Part D -- one provenance vocabulary

The enum moves to a single data file both validators read at runtime (this repo's
own "allowlists load from a table at runtime" pattern), and composition is defined
rather than left to collide:

| Form | Means | Precedence |
|---|---|---|
| `ev-<id>` | points at an `evidence.jsonl` row carrying the command and its output | strongest; satisfies the line alone |
| `provenance: validated \| observed \| explicit_statement` | the `memory-confidence.md` enum, a verified-ish category with no command attached | satisfies the line |
| `provenance: inferred \| corrected \| imported` | explicitly not a measurement | satisfies the line, and surfaces at recall as today |
| `{{UNVERIFIED}}` | shorthand, equivalent to `provenance: inferred` | satisfies the line |

Conflict rule: when a line carries more than one form, the strongest wins and
`check` warns on the mismatch rather than silently picking. `confidence` stays
orthogonal and untouched; it is a number about trust, not a claim about source.

## Alternatives considered

- **Keep v1's tier rule as documentation.** Rejected: the reviewer showed the model
  selects its own tier, so it documents a judgment call instead of removing it.
  Prose about a decision a script now makes is budget, not enforcement.
- **Keep `system-manifest.json` as a second file.** Rejected: two graphs of related
  files in one repo is the drift class this repo writes rules against, and
  `ripple-graph.json` already has a validator and 12 populated sources.
- **Generate `read_groups` by structural recon, `capability-map-gen.py` style.**
  Rejected as the whole answer: the real subsystems are client n8n workflows
  outside this repo, so a local generator cannot enumerate them. Globs give the
  generator's property where it is achievable; the rest is deferred in Non-goals.
- **Keep `read-first-gate.py` as the mechanism.** Rejected: it is the loader's
  inferior inverse. Kept as a backstop only, for when no group is declared.
- **Fail closed on every error including an absent manifest.** Rejected: that
  blocks every instance that has not adopted this, which is all of them on day one.
- **Migrate `memory-confidence-validator.py` to the newer markers.** Rejected: the
  incumbent has a rule file, a surfacing hook, and a decay model. The younger thing
  moves.

## Scenarios

- **The RCA case, replayed.** Founder asks why a form has no traffic, naming no
  subsystem. Claude reads `Parse LLM`. The touch trigger fires: `Parse LLM` is in
  `groupme-to-sheet`, so the loader injects the four remaining members. Claude
  answers from five workflows instead of two. No gate fired and none needed to.
- **Prompt names the group.** Founder says "walk me through the ingest chain". The
  prompt trigger fires before any tool call; the group arrives in context.
- **Group too large.** The glob resolves to 40 files, past the ceiling. `check`
  fails, naming the glob, before the loader ever runs.
- **Broken manifest.** Someone leaves a trailing comma in `ripple-graph.json`.
  `read_groups` is present but unparseable: the guard exits 2 rather than
  certifying coverage. Under v1 and under today's code, this exits 0.
- **Fresh instance.** No `read_groups` key. Loader and guard exit 0, silent.
  Nothing changes for 23 of 24 instances on day one.
- **Handoff line with two forms.** A bullet carries both `ev-a1b2c3d4e5` and
  `provenance: inferred`. The `ev-` id wins; `check` warns on the mismatch.

## Resolved decisions

- **Deterministic reading is a LOADER, not a gate or a rule.** Decided: extend
  `voice-dna-loader.py`'s mechanism. Rationale: founder directive plus three
  working precedents in this repo. Origin: `[USER-DIRECTED]` (mechanism named by
  the owner: "dont we already have a deterministic scrape read mechanism").
- **The v1 tier rule is deleted, not deferred.** Rationale: v1 review blocker,
  accepted in full. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **One graph.** Decided: extend `ripple-graph.json` to `_version: 2` with
  `read_groups`. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **Absent exits 0; present-but-broken exits 2.** Origin:
  `[CLAUDE-RECOMMENDED -> PENDING]`.
- **File members must be globs.** Rationale: a bare `ref` leaves hand-written drift
  available by default. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **External members are out of scope.** Rationale: v1 required a fingerprint with
  no command to produce or verify one. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.

## How v2 answers the v1 review

| v1 finding | v2 |
|---|---|
| blocker: model picks its own tier, dodges by not naming | Tier rule deleted. Loader fires on the USER's prompt and on tool touches, neither of which the model controls. |
| blocker: fails open on corrupt evidence | Part C splits absent from broken; broken exits 2. |
| blocker: empty `## Issues` manifest | Still empty, by template contract ("populated after review and approval"). Decomposition sketched under Risks so atomicity can be judged now. |
| major: glob overstated as a drift fix | Stated as a residual gap in Part B, and Part A is made primary precisely because it does not need a complete group. |
| major: fingerprint with no fetch command | External members removed from scope. |
| major: staleness contract contradictory | Removed with external members. No threshold is asserted anywhere in v2. |
| major: three provenance forms, composition undefined | Part D defines precedence and a conflict rule. |
| major: bare `ref` leaves drift available | `check` now rejects a bare file `ref`. |
| minor: fleet rollback has no verification command | Risks names one. |

## Risks and rollback

- **Injection is the new blast radius.** A loader that fires too often burns
  context on every turn. Mitigations: the byte ceiling; the group ceiling at
  `check`; and the loader emits nothing when the resolved set is already present in
  session evidence.
- **`ripple-graph.json` schema bump touches a working validator.**
  `ripple-verify.py` must ignore `read_groups` entirely. The first schema issue's
  `required_check` is `ripple-verify.py` exit 0 against a `_version: 2` file.
- **Rollback, with a command.** `git revert <sha> && kipi update --dry` to show the
  fan, then `kipi update`, then per-instance proof:
  `python3 q-system/.q-system/scripts/ripple-verify.py` exit 0 and
  `python3 code_claim_grounding_guard.py --self-test` 11/11. `kipi rollback` is the
  documented one-step revert of a skeleton sync if the fan itself is wrong.
- **Sketched decomposition** (for atomicity judgement now; manifest filled at
  approval): (1) verify PostToolUse injection capability, spike only;
  (2) `ripple-graph.json` v2 schema plus `check` rejecting bare refs and
  over-ceiling globs; (3) `subsystem-loader.py` prompt trigger; (4) touch trigger,
  gated on issue 1's result; (5) Part C exit-code split; (6) Part D enum
  extraction. Files are disjoint except (2) and (5), which both touch
  `system_manifest.py` and must serialize.

## Open questions

- Does PostToolUse support `additionalContext` injection? Blocks the touch
  trigger's design. `{{UNVERIFIED}}`
- What member ceiling makes a group a wall rather than a help? No data exists to
  pick a number yet. `{{UNVERIFIED}}`
- Should `read-first-gate.py` be retired once the loader ships, or kept as the
  no-group-declared backstop?
- Does the loader belong in the skeleton at all before one instance has a real
  `read_groups` entry proving it helps?

## Persona Review

### Skeptic

**Q1: What is the strongest argument against doing this?**

A1: The loader only helps once someone writes a correct `read_groups` entry, and
nobody has written one. The RCA subsystem is five n8n workflows that are not files
in this repo, so the very case that motivated all of this may not be expressible in
the schema, which is file-globs only. If that is true, this ships a mechanism for a
case it cannot serve, and the honest first step is one real group entry, not six
issues. Second argument: this is still Claude auditing Claude's three-day-old work,
and v2's main move is deleting v1's centerpiece, which is evidence that v1's
judgment was wrong and therefore evidence about v2's judgment too.

**Q2: What is the smallest experiment that would disprove the thesis?**

A2: Write one `read_groups` entry for the actual Prodigy_Gold subsystem and see
whether it can be expressed at all. If the members are five remote n8n workflows
with no local file, the file-glob schema cannot hold them and Part B needs
rethinking before any code. That is one JSON edit and no shipped code.

**Q3: What is the cheapest non-build alternative?**

A3: Part D alone (extract the enum, roughly ten lines), plus deleting the v1 tier
rule from the plan. Everything else waits for the Q2 experiment to say whether a
loader can serve the motivating case.

## Issues

<!-- Empty by template contract: populated after /prd-review and /prd-approve, one
     entry per accepted finding. Decomposition is sketched under Risks. -->

```json
[]
```
