---
id: prd-enforced-claim-verification-2026-08-21
title: Enforced Claim Verification
status: archived
created_at: 2026-08-21T17:13:00Z
updated_at: 2026-08-21T19:23:14Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-enforced-claim-verification-2026-08-21-findings.jsonl
codex_reviewed_at: 2026-08-21T17:18:55Z
reviewed_by: codex-adversarial
---

# Enforced Claim Verification

> Authorship note: prd-start says "do not auto-draft PRD content." The founder's
> brief for this work overrides it explicitly ("plan, then write and execute a
> PRD end to end... You own the engineering calls. Do not ask me to approve
> intermediate steps."). Recorded rather than silently ignored.
>
> Revision note: this body is v2, rewritten after the `codex-adversarial` review
> returned 5 blockers and 9 majors. The design below is materially different
> from v1 in five places, each traceable to a finding. v1's approach is preserved
> in Alternatives so the reviewer can see what was rejected and why.

## Problem

In this repo the word ENFORCED inside a `.claude/rules/*.md` heading is a string
an author typed. Nothing checks it. Measured 2026-08-21 over
`/Users/assafkipnis/projects/kipi-system`:

- 38 rule files. 30 claim ENFORCED, carrying 118 normative directives.
- Of those 30: 16 name at least one executable wired to a hook config; 8 name an
  executable wired NOWHERE; 6 name no executable at all.
- 2 of 30 have a test pinning the ENFORCED claim itself
  (`test-voice-enforcement-rule-wired.sh`, `test-token-discipline-rule-wired.sh`).
  So 93% of ENFORCED claims are unverified strings.
- The 16 "wired" ones are wired at FILE level. A file naming nine scripts with
  two wired scores green while its other clauses float.
- `prompt-only-enforcement-guard.py` is wired PostToolUse and DOES fire, but it
  matches vocabulary, not existence. Verified by running it: the sentence
  "enforced by the `totally-imaginary-lint.py` hook, a PostToolUse validator"
  exits 0. A bare `# Foo (ENFORCED)` heading never trips it.

The rot is in the CLAIMS, not the wiring: all 58 script references in
`.claude/settings.json` resolve to files that exist.

Why it matters more than a docs defect: rules propagate fleet-wide via the
skeleton updater. A false ENFORCED claim teaches every instance that a behaviour
is gated when nothing gates it, and people stop checking. That is the exact scar
already written into `wiring-check.py` lines 20-33: "A claim stronger than the
code behind it is worse than no claim, because people trust the claim and stop
checking."

Second, separable problem in the same session: `q-system/hooks/lessons-index.py`
has `CAP = 20` (line 18) and sorts by a date-only key (line 63), injecting titles
only at SessionStart. The skeleton has 146 lessons, so 126 are invisible every
session (86%). Write rate since 2026-08-01 is 2.61/day, giving a 7.7-day shelf
life. At the cutoff date 12 lessons compete for 4 slots and 8 are evicted by
ALPHABETICAL FILENAME ORDER (Python's stable sort on a date-only key). Measured
in `/Users/assafkipnis/projects/consulting` (153 lessons): the four lessons that
exactly describe the 2026-08-20 failures rank 93, 27, 57 and 24. Cutoff is 20.
All four aged out.

## Goals

- A three-value enforcement vocabulary that a script can substantiate or refuse:
  ENFORCED (an executable that exists at a resolved path, is referenced in the
  NAMED hook config unneutered, has a non-zero exit path, and has a named test
  pinning the claim), DETECTED (wired and runs, surfaces only, never blocks),
  ADVISORY (no executable, said out loud).
- Coverage is checked per ENFORCED MARKER, and the directive population under
  each marker is ratcheted so new directives cannot inherit an old disposition.
- ADVISORY is never silently legal under a heading still carrying the marker.
- The claim is gated at write time AND at commit time AND in the whole-tree
  validator, not only PostToolUse.
- `skill-hook-audit.py` stops printing "not onboarded" on the skeleton and stops
  treating the untracked `settings.local.json` as authoritative wiring.
- Every lesson title reaches every session; date-only eviction dies, and the
  payload gets a measured ceiling that fails loudly rather than growing silently.
- Every lint condition has its own mutation. The matrix is enumerated, not one
  hand-built case.

## Non-goals

- Relevance ranking for lessons. A wrong rank looks identical to a right one and
  fails silently. Titles-only injection of the full corpus is the ask.
- Judging whether a rule's prose is TRUE, or whether the named script implements
  THIS clause. See Risks: that residue is real and stated, not closed.
- Removing the ENFORCED marker from any heading. The sanctioned write path
  refuses it by construction; where the honest status is ADVISORY, this PRD
  produces a TICKETED discrepancy instead of a silent pass.
- The lesson to rule to checker promotion path. Split to its own PRD.

## Proposed approach

### The disposition block (v2: JSON, not a flat mapping)

Each rule file carries one fenced block, opened as ```json and immediately
preceded by the line `<!-- enforcement -->`. Its content is a JSON ARRAY, one
object per ENFORCED marker in the file. JSON because v1's flat `key: value`
mapping had no record delimiter, so two entries would repeat keys with undefined
parser behaviour (finding-2).

```json
[
  {
    "clause": "Cleanup / Migration Rule",
    "status": "ENFORCED",
    "exec": "q-system/.q-system/token-guard.py",
    "config": ".claude/settings.json",
    "test": "q-system/.q-system/scripts/test/test-token-discipline-rule-wired.sh",
    "directives": 4
  }
]
```

Field rules:
- `exec` is a REPO-RELATIVE PATH, never a basename (finding-9). Basename matching
  is what `skill-hook-audit.py` lines 58-75 does and it can pair a wired command
  with a different same-named file. A path has one referent or it does not exist.
- `config` names ONE hook config, and the exec must be referenced in THAT file
  (finding-8). v1 asked only whether the exec appeared in any config, so a false
  `config` value passed.
- `test` is required for `status: ENFORCED` (finding-5). This is the half of the
  posture question that IS decidable: a named test file that exists. It is
  modelled on the two rules that already do this in the repo.
- `directives` is the count of normative directive lines in the marker's section
  (finding-3). See below.
- `note` is required for ADVISORY. `marker_removal_ref` is additionally required
  when an ADVISORY entry sits under a heading still carrying the marker.

### Coverage unit: the marker, ratcheted by directive count

v1 keyed coverage to a heading, which Codex correctly called heading-level
wearing a clause-level label: one disposition greens every directive beneath a
broad heading. The fix is not one entry per directive (118 entries keyed on line
text that changes constantly) but a RATCHET on the population:

`directives` declares how many normative directive lines (MUST / NEVER / ALWAYS /
required / do not, case-insensitive, one count per line) sit in the marker's
section. The lint recounts and blocks on any mismatch. Adding a new MUST under a
dispositioned heading therefore trips the gate and forces the author to
re-examine the disposition rather than inherit it silently.

This is a growth detector, not a per-directive proof, and it is labelled as such
in Risks.

### ADVISORY under a live marker is a TICKETED discrepancy, never a pass

Finding-4 is the sharpest: v1 let an author satisfy a missing disposition by
declaring ADVISORY while the heading kept its ENFORCED marker, so the false claim
stayed visible and mechanically accepted. But making it a hard block creates an
unsatisfiable population, because the sanctioned write path REFUSES marker
removal (`_rule_marks`, line 682), and a gate red on files nobody can fix is a
gate that gets switched off (the `automated-filer-marking.md` measurement).

So: ADVISORY under a live marker requires `marker_removal_ref` naming an OPEN
spillover item id, and the lint resolves it against `.prd-os/spillover.jsonl`
locally (no network). The discrepancy is recorded, countable, and blocks
`gates run` until a founder-authorised marker removal closes it. Honest label
now, marker removal on the founder's turn.

### The lint

`q-system/.q-system/scripts/enforced-claim-lint.py`. Two modes:
- PostToolUse on Edit/Write, self-scoped to `.claude/rules/**/*.md`, fast-exit
  otherwise. Wired in BOTH `.claude/settings.json` and `settings-template.json`.
- `--all`, walking the whole rules tree, wired into lefthook `pre-commit` and
  into `validate-separation.py` (finding-10, finding-11). PostToolUse is feedback
  AFTER the write lands; the commit-time gate is what makes the invariant
  persistent, and it also covers direct shell writes, updater propagation and
  pre-existing files that no PostToolUse hook ever sees.

Blocking conditions, each with its own mutation (finding-14):

| # | Condition | Finding |
|---|---|---|
| 1 | heading carries the marker, no entry with matching clause | base |
| 2 | two entries normalize to the same clause key | 7 |
| 3 | an entry's clause matches no heading in the file (orphan disposition) | 7 |
| 4 | malformed JSON, unknown key, or bad status value | 2 |
| 5 | `exec` path does not exist | 9 |
| 6 | `exec` not referenced in the NAMED `config` | 8 |
| 7 | ENFORCED and the wired command is neutered (`\|\| true`, `\|\| exit 0`) | 5 |
| 8 | ENFORCED and the exec source has no non-zero exit path | 5 |
| 9 | ENFORCED and `test` is missing or its file is absent | 5 |
| 10 | DETECTED while the exec both can exit non-zero and is wired unneutered | base |
| 11 | ADVISORY under a live marker without an OPEN `marker_removal_ref` | 4 |
| 12 | declared `directives` != recounted directives in the section | 3 |

Clause key normalization (finding-7), stated exactly so it is implementable:
lowercase, strip the trailing marker and any parenthetical, collapse internal
whitespace, drop every character outside `[a-z0-9 ]`, strip. Duplicates after
normalization are condition 2, not a silent collapse.

### Un-orphaning skill-hook-audit

`plugins/kipi-core/scripts/skill-hook-audit.py` is already invoked by
`validate-separation.py:1011` and is manifest-gated: no
`.claude/skill-hook-manifest.json` means "not onboarded", exit 0, downgraded to
WARN. Writing the skeleton manifest turns five coded, tested invariants on. 15
skills on disk to triage.

One correction ships with it (finding-13): `wired_config_files` at lines 52-55
includes `settings.local.json`, which `apply_claude_changes.py` lines 512-532
documents as untracked, machine-local and outside the auditable path. A skeleton
hook could be reported wired on the strength of one developer's local override.
It comes out of the reader.

### Lessons injector

Drop `CAP`. Inject every title. Then give the payload a MEASURED CEILING with a
test that fails above it (finding-12): unbounded growth is the same silent
failure as the CAP, one direction reversed. The ceiling is set from the measured
cost at 146 lessons plus headroom, and breaching it is a decision the test forces
rather than a drift nobody sees. Keep the fail-closed exit-0 contract.

## Alternatives considered

- **Disposition as a frontmatter key (`enforcement:`).** Rejected:
  `apply_claude_changes.py::_guard_frontmatter` (line 562) refuses ANY
  frontmatter change by ANY op, including additive ones. Unreachable.
- **Relabel the heading marker to DETECTED.** Rejected: `_rule_marks` (line 682)
  censuses marker occurrences and marker-carrying headings as ratchet members
  that may only grow. Its docstring names this case: "Demoting a rule to advisory
  is enforcement-weakening whether or not the prose is honest."
- **v1: a flat `key: value` disposition block keyed to headings (this PRD's own
  first draft).** Rejected on review: no record delimiter for multiple entries
  (finding-2), coverage keyed to headings reproduces the file-level hole one
  notch narrower (finding-3), ADVISORY silently legal under a live marker
  (finding-4), basename exec matching (finding-9), unvalidated `config`
  (finding-8), and no gate outside PostToolUse (finding-10, 11).
- **One disposition entry per normative directive (118 entries).** Rejected: the
  key would be directive line text, which changes on every editorial pass, so
  dispositions orphan constantly and the gate becomes noise. The directive-count
  ratchet gets the anti-inheritance property without the unstable key.
- **Hard-block ADVISORY under a live marker.** Rejected: unsatisfiable for its own
  population, because marker removal is refused by the sanctioned path. A gate red
  on files nobody can fix gets switched off, and a switched-off gate protects
  nothing (`automated-filer-marking.md`, measured before it shipped).
- **Extend `prompt-only-enforcement-guard.py` instead of a new lint.** Rejected:
  that guard matches vocabulary; this needs existence and wiring resolution.
  Bolting it on makes one script fail two ways for two reasons.
- **Infer the status instead of declaring it.** Rejected: whether a clause is
  meant to be gated is judgment. `automated-filer-marking.md` settled this shape
  here: split deterministic from judgment, DECLARE the judgment half once.
- **Execute each named script to prove its exit posture.** Rejected: running
  arbitrary hook scripts from inside a lint is a live-data path and the
  fable-discipline lint exists to stop exactly that. The `test` field is the
  proxy: a named test that exists and is expected to go red.

## Scenarios

- **New rule claiming enforcement.** An agent writes `.claude/rules/new-thing.md`
  with a heading carrying the marker and no block. PostToolUse fires the lint,
  condition 1 hits, exit 2, stderr names the clause and the three statuses. The
  author declares a status. If the honest answer is ADVISORY, condition 11 demands
  a `marker_removal_ref`, so the discrepancy is ticketed rather than absorbed.
- **Script named but never wired.** A rule declares `status: ENFORCED`,
  `exec: q-system/.q-system/scripts/model-allocation-check.py`,
  `config: .claude/settings.json`. The file exists; the config does not reference
  it. Condition 6 hits: "claimed ENFORCED but not referenced in the named config
  -- it is an ORPHAN, it never fires."
- **Surfacing detector labelled as blocking.** A rule declares ENFORCED with
  `exec: q-system/.q-system/scripts/wiring-check.py`, which exits 0 on every path
  by documented contract. Condition 8 hits and names DETECTED as the honest label.
- **Directive added under a dispositioned heading.** Someone appends a new
  "NEVER ..." line under a section whose entry declares `directives: 4`. The
  recount returns 5, condition 12 hits, and the author must re-examine the
  disposition instead of inheriting it.
- **Commit-time catch.** A rule file is written by a shell heredoc (no PostToolUse
  hook fires) with a false ENFORCED claim. `git commit` runs the lefthook
  pre-commit stage, `enforced-claim-lint.py --all` exits non-zero, the commit is
  refused. This is the persistence half that PostToolUse structurally cannot give.
- **Mutation matrix.** One fabricated input per condition in the table, each shown
  RED before the real tree is shown GREEN. Both pasted into the wiring report.

## Resolved decisions

- **The disposition is a fenced JSON array in the rule BODY.** Rationale: both
  other locations are mechanically refused (`_guard_frontmatter`; the marker
  ratchet). JSON because a flat mapping has no record delimiter (finding-2). Body
  text is additive, so `insert_after`/`append` reach it.
- **Coverage unit is the marker plus a directive-count ratchet, not the heading
  and not the directive.** Rationale: finding-3 is right that heading-keyed
  coverage inherits; per-directive keys are unstable. The ratchet gets the
  anti-inheritance property with a stable key.
- **ADVISORY under a live marker is legal only with an open spillover ref.**
  Rationale: finding-4 vs. the unsatisfiable-population failure mode. Ticketed
  beats both silently-accepted and unfixably-red.
- **ENFORCED requires a named test.** Rationale: finding-5 is right that "source
  contains a non-zero exit" does not prove reachability. The repo's own two good
  examples (`test-voice-enforcement-rule-wired.sh`,
  `test-token-discipline-rule-wired.sh`) are the pattern.
- **A commit-time `--all` gate ships with the PostToolUse hook.** Rationale:
  findings 10 and 11. PostToolUse is feedback after the fact and misses every
  write it does not mediate.
- **Lesson to rule to checker promotion is split to its own PRD.** Rationale: a
  corpus-lifecycle feature with its own producer, consumer and ageing policy. It
  shares no code with a labelling lint.
- **Default to DETECTED when unsure.** Rationale: rules fan out fleet-wide, a
  false block hits every instance, and a switched-off gate protects nothing.

## Risks and rollback

- **Blast radius: every instance.** The lint ships via `settings-template.json`
  and the lefthook stage, so it fires on every rule-file write and commit
  fleet-wide. Mitigation: self-scoped by path with a fast exit; a rule carrying NO
  marker is untouched. Instances are blocked only where they carry a marker,
  which is the population this exists to catch.
- **False block on an instance-local rule.** Instance rules the skeleton has never
  seen will block on first edit until dispositioned. Intended, and the main reason
  to err DETECTED.
- **`exec` swaps are refused by the ratchet (finding-6, ACCEPTED as a real
  limitation, and v1's text claiming otherwise was wrong).** `_rule_marks` lines
  748-749 ratchet every referenced `.py`/`.sh` basename, and 809-815 refuse any
  mark disappearing. So replacing an obsolete enforcer with a differently-named
  one CANNOT go through the sanctioned path: the old basename must remain
  somewhere in the file. The workable form is to keep the retired name in a
  superseded-by line and add the new one. Stated here because v1 promised
  free rewording and that promise was false.
- **The directive count is a growth detector, not a per-directive proof.** A
  disposition still covers a whole section. What it can no longer do is silently
  absorb a NEW directive.
- **Residue, stated not papered over:** the lint proves a named script exists at a
  path, is referenced in a named config unneutered, has a non-zero exit path, and
  has a named test file. It does NOT prove that script enforces THIS clause, nor
  that the named test actually goes red. A rule can name a real, wired, blocking,
  tested script that gates something else entirely and pass. Same class of residue
  that `wiring-check.py` and `automated-filer-marking.md` already state out loud.
- **Rollback:** removing a hook is out of reach of the sanctioned path by design.
  Backing this out means a direct founder-authorised edit to both settings files
  plus the lefthook config. Real cost, stated rather than hidden.

## Open questions

- None blocking. The `kipi check` integration question from v1 is now resolved
  (yes, via the `--all` mode) by finding-10.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: It adds ceremony to every rule file to solve a documentation-accuracy
problem, and the ceremony cannot verify the thing that matters -- that the named
script enforces THIS clause. So it risks converting an obviously-unverified claim
into a plausibly-verified one, which is the more dangerous state. The answer is
that the residue is named in Risks, in the rule text, and in the script docstring,
which is the posture `wiring-check.py` and `automated-filer-marking.md` already
take, and that the `test` requirement moves the proof from "a script exists" to
"a test that pins this claim exists" -- which is what the repo's two honest rules
already do.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run `--all` against the real tree before the disposition pass. If it flags
materially fewer than the 14 files the forensics predicts, the parser is wrong
about how claims are written and the whole clause model is unsound.

Q3: What is the cheapest non-build alternative?
A3: Write the skeleton `skill-hook-manifest.json` only, which turns on five
already-coded invariants for the price of one JSON file, and delete the word
ENFORCED from the 14 files by hand. The second half is unavailable: the sanctioned
write path refuses marker removal, which is why the lint approach exists at all.

## Issues

```json
[
  {
    "id": "enforcement-block-json-grammar",
    "finding_id": "finding-2",
    "title": "Disposition block is a fenced JSON array with a defined schema and a rejecting parser",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k grammar"
    ],
    "bypass_check": "grep -c 'def parse_block' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
  },
  {
    "id": "enforcement-directive-count-ratchet",
    "finding_id": "finding-3",
    "title": "Directive-count ratchet so a new normative line cannot inherit an existing disposition",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k directive"
    ],
    "bypass_check": "exactly one directive-counting function exists: grep -c 'def count_directives' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
  },
  {
    "id": "enforcement-advisory-under-marker-blocked",
    "finding_id": "finding-4",
    "title": "ADVISORY under a live ENFORCED marker requires an open spillover ref; disposition pass over the 14 files",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py",
      "q-system/.q-system/proposals/*.json"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k advisory",
      "python3 q-system/.q-system/scripts/enforced-claim-lint.py --all"
    ],
    "bypass_check": "no ADVISORY entry can pass under a live marker without a resolving ref: the advisory mutation case exits 2"
  },
  {
    "id": "enforcement-test-receipt-required",
    "finding_id": "finding-5",
    "title": "ENFORCED requires a named existing test file; exit-posture claim narrowed to what is decidable",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k posture"
    ],
    "bypass_check": "the lint never executes a named enforcer: grep -E 'subprocess|os.system|popen' q-system/.q-system/scripts/enforced-claim-lint.py | grep -v '^[[:space:]]*#' | wc -l | grep -qx 0"
  },
  {
    "id": "enforcement-exec-swap-residue-documented",
    "finding_id": "finding-6",
    "title": "Document that the basename ratchet refuses enforcer swaps, in the lint docstring and the rule text",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py"
    ],
    "required_checks": [
      "grep -q 'ratchet' q-system/.q-system/scripts/enforced-claim-lint.py"
    ],
    "bypass_check": "the docstring names the limitation rather than promising free rewording: grep -q 'cannot be swapped' q-system/.q-system/scripts/enforced-claim-lint.py"
  },
  {
    "id": "enforcement-clause-key-normalization",
    "finding_id": "finding-7",
    "title": "Exact clause-key normalization, duplicate keys rejected, orphan dispositions rejected",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k clause_key"
    ],
    "bypass_check": "normalization lives in exactly one function: grep -c 'def clause_key' q-system/.q-system/scripts/enforced-claim-lint.py | grep -qx 1"
  },
  {
    "id": "enforcement-config-specific-resolution",
    "finding_id": "finding-8",
    "title": "Resolve the exec against the NAMED config, not any config",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k named_config"
    ],
    "bypass_check": "a wrong config value fails even when another config references the exec: the named_config mutation exits 2"
  },
  {
    "id": "enforcement-exec-path-not-basename",
    "finding_id": "finding-9",
    "title": "exec is a repo-relative path with one referent, never a basename",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k exec_path"
    ],
    "bypass_check": "a bare basename in exec is rejected rather than resolved: the exec_path mutation exits 2"
  },
  {
    "id": "enforcement-whole-tree-gate",
    "finding_id": "finding-10",
    "title": "--all mode wired into lefthook pre-commit and validate-separation, plus both settings files",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/enforced-claim-lint.py",
      "q-system/.q-system/scripts/test_enforced_claim_lint.py",
      "lefthook.yml",
      "q-system/.q-system/proposals/*.json",
      "plugins/kipi-core/scripts/validate-separation.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/enforced-claim-lint.py --all",
      "python3 -m pytest q-system/.q-system/scripts/test_enforced_claim_lint.py -q -k whole_tree"
    ],
    "bypass_check": "the lint is reachable outside PostToolUse: lefthook.yml references enforced-claim-lint and the hook is present in both settings files"
  },
  {
    "id": "lessons-payload-ceiling",
    "finding_id": "finding-12",
    "title": "Uncap lesson titles and give the SessionStart payload a measured ceiling with a failing test",
    "priority": "p1",
    "allowed_files": [
      "q-system/hooks/lessons-index.py",
      "q-system/.q-system/scripts/test_lessons_index.py"
    ],
    "required_checks": [
      "python3 -m pytest q-system/.q-system/scripts/test_lessons_index.py -q"
    ],
    "bypass_check": "no unconditional slice of the item list remains and a ceiling constant is asserted by the test"
  },
  {
    "id": "skill-hook-audit-drop-local-settings",
    "finding_id": "finding-13",
    "title": "Skeleton skill-hook-manifest.json, and stop treating settings.local.json as authoritative wiring",
    "priority": "p0",
    "allowed_files": [
      "plugins/kipi-core/scripts/skill-hook-audit.py",
      "q-system/.q-system/proposals/*.json",
      "q-system/.q-system/scripts/test_skill_hook_audit_local.py"
    ],
    "required_checks": [
      "python3 plugins/kipi-core/scripts/skill-hook-audit.py",
      "python3 -m pytest q-system/.q-system/scripts/test_skill_hook_audit_local.py -q"
    ],
    "bypass_check": "settings.local.json is not read as wiring: grep -c 'settings.local.json' plugins/kipi-core/scripts/skill-hook-audit.py returns only commentary lines, and the audit prints PASS not 'not onboarded'"
  },
  {
    "id": "enforcement-lint-mutation-matrix",
    "finding_id": "finding-14",
    "title": "One enumerated mutation per blocking condition, each shown red before the tree is shown green",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/test_enforced_claim_lint.py",
      "q-system/.q-system/scripts/test/enforced-claim-mutation-matrix.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/enforced-claim-mutation-matrix.sh"
    ],
    "bypass_check": "the matrix derives its case list from the lint's own condition table rather than a hand-written list, and every condition has a case"
  }
]
```
