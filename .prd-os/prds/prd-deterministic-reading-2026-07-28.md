---
id: prd-deterministic-reading-2026-07-28
title: Deterministic Reading
status: approved
created_at: 2026-07-28T19:00:31Z
updated_at: 2026-07-28T21:17:14Z
owner: assafkipnis
reviewers: []
findings_path: .prd-os/findings/prd-deterministic-reading-2026-07-28-findings.jsonl
codex_reviewed_at: 2026-07-28T19:35:15Z
---

<!-- prompt-only-enforcement-skip
Reason: known false positive on this file, diagnosed and captured as sp-8f05a182
(wrong line number reported on longer files) and sp-dacb04c7 (blocks lines that
DO name their blocker inline; every such line passes the guard in isolation, only
the assembled block trips it). Flagged lines here are the Goals check list, the
Non-goals deletions, and the Scenarios -- descriptions of behavior, not
enforcement claims. Every mechanism this PRD proposes names its own executable
blocker in Parts A through C.
-->

# Deterministic Reading

> **v3. The measurement that should have come first.**
>
> v1 proposed read tiers plus a new manifest (3 blockers). v2 proposed a
> subsystem loader plus a graph merge (5 blockers). Both were rejected, the
> second harder than the first.
>
> The owner then asked whether this had drifted from the original goal: make the
> agent actually read WHAT IS IN THE INSTANCE before answering confidently. It
> had. v1 and v2 both fixated on the client's remote n8n workflows and designed
> coverage arithmetic for them. Nobody had measured the instance.
>
> **Measured 2026-07-28: `q-prodigy/` is 12 markdown files, 1,054 lines, 53,222
> bytes, roughly 13,000 tokens.** Command in Verification below.
>
> At that size the entire coverage problem is imaginary. You do not need a
> manifest, a graph, globs, groups, tiers, or set arithmetic to read twelve
> files. You read all twelve. v3 is therefore much smaller than v2, and most of
> what v1 and v2 proposed is deleted rather than fixed.
>
> **Still drafted by Claude, not the owner**, and now with a two-for-two record
> of rejected designs on this problem. Weigh the `Resolved decisions`
> accordingly.

## Problem

RCA `rca-conclusions-before-evidence-2026-07-28` (Prodigy_Gold): six conclusions
delivered in settled language, all six reversed later in the same session, one
having already shaped a client email draft.

**Where the refutations actually lived.** Verified by grep, not asserted:

| Reversal | Refuted by | On disk in the instance? |
|---|---|---|
| #5 future-dated Brightspeed row | `q-prodigy/memory/last-handoff.md:64` | YES |
| #6 nobody works in the shared sheet | `q-prodigy/output/outreach/marilyn-data-findings-2026-07-22.md:4,8` | YES |
| #1 staged rollout, reps in ~2 weeks | "a prior session log" per the RCA | **NO** -- not in the 12 instance files |
| #2, #3, #4 | n8n workflow nodes | NO -- remote, not files |

So the instance held the answer to two of six, a session log held a third, and
three needed a remote system. That split is the design, and neither v1 nor v2
had it because neither measured anything.

**P1 -- instance content is not read, and it is trivially small.** 13k tokens.
Nothing reads it wholesale today. `canonical-digest.py` already does exactly this
for `canonical/` alone and its docstring says why it exists ("Replaces the
00c-canonical-digest LLM agent with regex-based parsing"). The pattern is present
and simply not applied to the rest of the instance.

**P2 -- remote systems are not on disk, so nothing can read them.** Reversals
2-4 required n8n workflow definitions. `firecrawl-scrape.py` already establishes
this repo's answer to that class: persist the full source to a FILE "instead of
summarizing it into context". No equivalent exists for n8n. Once a workflow is a
file in the instance, P1's loader covers it with no new mechanism.

**P3 -- two provenance vocabularies.** Unchanged from v1 and v2, and the only
part that survived both reviews. `.claude/rules/memory-confidence.md` defines
`confidence` plus a `provenance` enum enforced by
`memory-confidence-validator.py`; `handoff-provenance-lint.py` invented a
different set.

## Goals

- The full instance content is in context before the first answer, without the
  model selecting any of it.
- A remote system that matters becomes a file in the instance, at which point it
  is covered by the same mechanism.
- One provenance vocabulary, from one source both validators read.
- The mechanism states its own limit out loud when it truncates, rather than
  silently delivering part of the instance.
- No regression, each proved by running the named command:
  - `python3 test_evidence_ledger.py` -> 11/11
  - `python3 test_client_output_evidence_gate.py` -> 8/8
  - `python3 test_handoff_provenance_lint.py` -> 10/10 plus new cases
  - `python3 code_claim_grounding_guard.py --self-test` -> passes at its new case count
  - `python3 q-system/.q-system/scripts/settings-template-sync-check.py` -> exit 0
  - `python3 q-system/.q-system/scripts/instruction-budget-audit.py` -> at or under 513
  - `python3 validate-separation.py` -> matches the recorded 25-pass/1-fail baseline

## Non-goals

- Read tiers (v1). Deleted.
- A subsystem loader with prompt and touch triggers (v2). Deleted. Both triggers
  existed to decide WHICH subset to load. There is no subset.
- `system-manifest.json`, `read_groups`, globs, member ceilings, fingerprints,
  staleness thresholds. All deleted. They were coverage arithmetic for a set of
  12 files.
- Session logs. Reversal #1's evidence was in a prior session transcript outside
  the instance. Real gap, named in Open questions, not solved here.
- Making gates smarter about MEANING.

## Proposed approach

### Part A -- `instance-digest.py`: read the whole instance, every session

A SessionStart hook that reads every `.md` under the instance content dir and
injects it via `hookSpecificOutput.additionalContext`. This is
`canonical-digest.py`'s principle applied to the whole instance, and
`voice-dna-loader.py:152` is the proven injection shape.

- **Full content by default.** At ~13k tokens for a real instance this is
  affordable once per session.
- **Ceiling with a loud fallback.** Above a byte ceiling it injects headings plus
  the first N lines per file AND a line naming exactly which files were truncated
  and by how much. Codex's v2 finding stands: truncation is not reading, so the
  truncation must be visible rather than silent.
- **Refuses partial silence.** If any file cannot be read, the injected text says
  so by name. It does not quietly emit the rest.

**What this replaces.** `read-first-gate.py` (shipped `1b49d91`) blocks the first
write until the model reads. If the content is already in context, the gate is
redundant and costs a blocked turn. v3 retires it. `system_manifest.py` and
`code_claim_grounding_guard.py`'s check two are retired with it, since both exist
to compute coverage of a set that is now always fully loaded.

### Part B -- `n8n-export.py`: turn the remote system into instance files

One command that writes each workflow's JSON into the instance
(`q-<instance>/reference/n8n/<workflow>.json`). Then Part A covers reversals 2-4
with no new reading mechanism at all: they stop being remote.

This is `firecrawl-scrape.py`'s pattern, which persists full source to a file
rather than summarizing into context, and fails CLOSED on an empty body. Same
failure posture here: an empty or error response writes nothing and exits
non-zero, so a stale file is never mistaken for a fresh one.

Freshness is a real question and is answered by the file, not by a claim: the
export stamps `exported_at`, and a workflow file older than the engagement's
review cadence is visible as a file date. No fingerprint field, no threshold
config, no verification metadata that proves only that metadata exists.

`{{UNVERIFIED}}` -- whether the n8n API credentials available to this engagement
permit a workflow export. If they do not, Part B is not buildable and reversals
2-4 stay uncovered. The first issue answers this before anything else is built.

### Part C -- one provenance vocabulary

`handoff-provenance-lint.py` and `memory-confidence-validator.py` read one enum
from one data file. Precedence, answering the v2 finding that only `ev-` vs
other was defined:

1. `ev-<id>` (points at an `evidence.jsonl` row carrying command and output)
2. `provenance: validated` > `observed` > `explicit_statement` > `corrected` >
   `imported` > `inferred`
3. `{{UNVERIFIED}}` is exactly equivalent to `provenance: inferred`

When a line carries two forms, the higher-precedence one wins AND `check` emits
the pair it saw, so a downgrade is never silent. `confidence` is orthogonal and
untouched.

## Alternatives considered

- **Keep v2's loader with triggers.** Rejected: triggers pick a subset, and there
  is no subset to pick. Every trigger is a decision, and every decision is a
  place the model or the author can be wrong.
- **Keep the manifest for large instances.** Rejected for now: no instance has
  been measured that needs it. Building set arithmetic for a hypothetical instance
  is what produced v1 and v2. If one appears, its measurement is the trigger.
- **Summarize the instance instead of injecting it.** Rejected: a summary is a
  model read of the instance, which is the thing being removed.
- **Leave reversals 2-4 uncovered.** Rejected: they are half the RCA, and v2 was
  blocked precisely for writing them out of scope. Part B covers them by moving
  them on-disk rather than by excluding them.
- **Keep `read-first-gate.py` alongside the loader.** Rejected: a gate that blocks
  on reading content already in context is pure friction, and friction gets
  bypassed.

## Scenarios

- **Reversal #6 replayed.** Session starts; all 12 instance files are in context,
  including `marilyn-data-findings-2026-07-22.md`. The claim "nobody works in the
  shared sheet" is contradicted by text already present, before any tool call.
- **Reversal #5 replayed.** `last-handoff.md` is in context at turn one, so an
  inherited claim arrives with its correction attached.
- **Reversals #2-4 replayed, Part B shipped.** The five workflow JSONs are files
  under `reference/n8n/`. Part A loads them with everything else.
- **Instance outgrows the ceiling.** Injection truncates and names each truncated
  file with its omitted line count. The operator can see coverage is partial.
- **A file is unreadable.** Injected text names it. No silent partial load.
- **No n8n credentials.** Part B's first issue exits non-zero and reversals 2-4
  are documented as uncovered rather than assumed handled.

## Resolved decisions

- **Measure before designing.** Decided: the instance is 12 files / ~13k tokens,
  so read all of it. Rationale: two designs were rejected for solving a scale
  problem that was never measured and does not exist. Origin: `[USER-DIRECTED]`
  (owner: "ensure you are still working on the original issue and you didnt
  drift. WE are making sure the agent actually reads whats in the instance").
- **Retire `read-first-gate.py`, `system_manifest.py`, and grounding-guard check
  two.** Rationale: all three compute or enforce coverage of a set that is now
  always fully loaded. Shipped three days ago in `1b49d91`; retiring beats
  keeping dead enforcement. Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **Remote systems become files rather than getting their own coverage model.**
  Origin: `[CLAUDE-RECOMMENDED -> PENDING]`.
- **Truncation must be announced in the injected text.** Rationale: v2 review,
  "deterministic truncation is not deterministic reading". Origin:
  `[CLAUDE-RECOMMENDED -> PENDING]`.

## Verification

The measurement this PRD rests on, reproducible:

```
find q-prodigy -type f -name "*.md" | xargs wc -lc | tail -1
  -> 1054 lines, 53222 bytes  (~13,300 tokens)
find q-prodigy -type f | wc -l
  -> 14 files (12 .md + 2 .gitkeep)
grep -n "future-dated" q-prodigy/memory/last-handoff.md
  -> line 64, reversal #5's refutation
grep -n "sheet" q-prodigy/output/outreach/marilyn-data-findings-2026-07-22.md
  -> lines 4 and 8, reversal #6's source
grep -riE "two weeks|leadership|roll ?out" q-prodigy/output/onboarding-call-2026-07-22.md
  -> no match; reversal #1's evidence is NOT in the instance
```

## Risks and rollback

- **13k tokens every session, on every instance.** The largest cost in this PRD
  and it is paid whether or not the session needs it. Mitigation is the ceiling;
  the honest statement is that this trades tokens for correctness deliberately.
  If an instance grows past the ceiling this design needs revisiting, and the
  ceiling breach is the signal.
- **Retiring three shipped scripts.** They fail open when absent, so removal
  degrades to pre-`1b49d91` behavior rather than breaking anything. Rollback:
  `git revert`, then `kipi update`, then `python3
  code_claim_grounding_guard.py --self-test` and `python3 validate-separation.py`
  as per-instance proof.
- **Part B depends on credentials nobody has confirmed.** Sequenced first for
  exactly that reason.
- **Sketched decomposition** (manifest filled at approval): (1) confirm n8n export
  credentials, spike, no shipped code; (2) `instance-digest.py` with ceiling and
  truncation announcement; (3) wire it SessionStart in both settings files;
  (4) retire the three redundant scripts and their tests; (5) `n8n-export.py`,
  gated on (1); (6) Part C enum extraction. Disjoint files except (2) and (3).

## Open questions

- Reversal #1's evidence was in a session log, outside the instance. Session logs
  are large and unbounded, so Part A's approach does not extend to them. Left
  unsolved and named. `{{UNVERIFIED}}`
- What byte ceiling? 13k tokens is comfortable; the number where it stops being
  comfortable is unmeasured. `{{UNVERIFIED}}`
- Do the other 23 instances measure similarly small, or is Prodigy_Gold unusually
  light? One `find | wc` per instance answers it and has not been run.
- Should `instance-digest.py` inject raw content or a structured digest? Raw is
  simpler and provably lossless; a digest is cheaper and reintroduces a
  summarization step this PRD argues against.

## Persona Review

### Skeptic

**Q1: What is the strongest argument against doing this?**

A1: It pays 13k tokens on every session of every instance to fix a failure that
happened once, and the operator's own `token-discipline.md` exists because that
cost is real. A cheaper fix covers most of the value: inject only
`memory/last-handoff.md` and `canonical/`, which is where reversals #5 and #6
lived, for a fraction of the tokens. Second argument: v3's central move is
deleting the work v1 and v2 proposed AND retiring three scripts shipped three days
ago. Three reversals in one day on the same problem is evidence the author should
not be trusted to pick the fourth answer either.

**Q2: What is the smallest experiment that would disprove the thesis?**

A2: Run `find <instance> -type f -name "*.md" | xargs wc -l` across all 24
instances. If several are an order of magnitude larger than Prodigy_Gold, "read
everything" does not generalize and the deleted manifest work was premature
rather than wrong. This is one command and has not been run.

**Q3: What is the cheapest non-build alternative?**

A3: Part C alone (~10 lines), plus adding the instance content dir to the existing
`canonical-digest.py` glob rather than writing a new script. That may be the whole
of Part A already, and Part A should be checked against it before any new file is
created.

## Issues

<!-- One entry per ACCEPTED finding. The reading design these findings were
     raised against is withdrawn (refuted by ev-1fb8c8c931); these four entries
     cover the gate-hardening work that actually shipped. -->

```json
[
  {
    "id": "dr-gate-false-positives-2026-07-28",
    "finding_id": "finding-1",
    "title": "Fix the three false positives that made the shipped grounding gates unusable",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/handoff-provenance-lint.py",
      "q-system/.q-system/scripts/client-output-evidence-gate.py",
      "q-system/.q-system/scripts/evidence_ledger.py",
      "q-system/.q-system/scripts/test_handoff_provenance_lint.py",
      "q-system/.q-system/scripts/test_client_output_evidence_gate.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test_handoff_provenance_lint.py",
      "python3 q-system/.q-system/scripts/test_client_output_evidence_gate.py",
      "python3 q-system/.q-system/scripts/test_evidence_ledger.py"
    ],
    "bypass_check": "grep -q 'HEADER_RE' q-system/.q-system/scripts/handoff-provenance-lint.py && grep -q 'def adopted' q-system/.q-system/scripts/evidence_ledger.py && grep -q 'ISO_DATE_RE' q-system/.q-system/scripts/evidence_ledger.py",
    "acceptance": "Dated markdown headers pass the handoff lint while dated CLAIMS and numbers-in-headers still block; ISO dates and bare years are not measurements while a real count on the same line still blocks; an absent evidence.jsonl is a no-op while one row restores full enforcement. Each fix ships with its negative case. ASK-231, ASK-232, ASK-233."
  },
  {
    "id": "dr-capability-gate-green-2026-07-28",
    "finding_id": "finding-10",
    "title": "Return kipi check to green: declare the six grounding tests, drop the phantom instance",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/capability-manifest.json",
      "instance-registry.json",
      ".claude/rules/evidence-ledger.md"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/capability-gate.py",
      "python3 -c \"import json;d=json.load(open('instance-registry.json'));import os;assert all(os.path.isdir(os.path.expanduser(i['path'])) for i in d['instances'])\""
    ],
    "bypass_check": "test \"$(python3 -c \"import json;print(len(json.load(open('q-system/.q-system/capability-manifest.json'))['expected_tests']))\")\" -ge 84",
    "acceptance": "expected_tests declares all six grounding tests with no pre-existing entry lost; provenance_vocabulary.py resolves via a real wiring surface rather than a false declared_inert; every registered instance path exists. kipi check FAIL 5 -> FAIL 0. ASK-230, ASK-234."
  },
  {
    "id": "dr-fleet-wiring-hold-release-2026-07-28",
    "finding_id": "finding-25",
    "title": "Ship the gates that are proven safe, hold the one that is not, with the hold enforced",
    "priority": "p0",
    "allowed_files": [
      "settings-template.json",
      "q-system/.q-system/scripts/settings-template-sync-check.py",
      "q-system/.q-system/scripts/read-first-gate.py",
      "q-system/.q-system/scripts/test_read_first_gate.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/settings-template-sync-check.py --check",
      "python3 q-system/.q-system/scripts/test_read_first_gate.py"
    ],
    "bypass_check": "test \"$(grep -c 'read-first-gate' settings-template.json)\" -eq 0 && grep -q 'read-first-gate.py' q-system/.q-system/scripts/settings-template-sync-check.py",
    "acceptance": "handoff-provenance-lint and client-output-evidence-gate are wired fleet-wide and their SKELETON_ONLY entries removed; read-first-gate stays out of the template with a measured reason, and sync-check goes RED if that hold is silently dropped. ASK-229, ASK-235."
  },
  {
    "id": "dr-one-provenance-vocabulary-2026-07-28",
    "finding_id": "finding-7",
    "title": "One provenance vocabulary with defined composition, read from one table by both validators",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/provenance_vocabulary.py",
      "q-system/.q-system/scripts/provenance-vocabulary.json",
      "q-system/.q-system/scripts/test_provenance_vocabulary.py",
      ".claude/rules/evidence-ledger.md"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test_provenance_vocabulary.py"
    ],
    "bypass_check": "grep -q 'provenance_vocabulary' q-system/.q-system/scripts/handoff-provenance-lint.py && grep -q 'provenance_vocabulary' q-system/.q-system/scripts/memory-confidence-validator.py",
    "acceptance": "The three forms are ranked rather than merely listed: ev-<id> outranks every enum value, {{UNVERIFIED}} maps to provenance: inferred, and strongest() resolves a line carrying more than one. Both validators import the same module. Shipped 5bed187, extended in ASK-230."
  }
]
```
