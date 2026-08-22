---
id: prd-canonical-read-path-repair-2026-08-22
title: Canonical Read Path Repair
status: approved
created_at: 2026-08-22T19:37:28Z
updated_at: 2026-08-22T20:07:33Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-canonical-read-path-repair-2026-08-22-findings.jsonl
codex_reviewed_at: 2026-08-22T20:00:02Z
reviewed_by: codex-adversarial
---

# Canonical Read Path Repair

## Problem

Consulting holds three diverged canonical trees with identical filenames, and every
consumer in the fleet is split cleanly between them: **everything the instance wrote
points at `q-consult/canonical/`; everything the skeleton shipped points at
`q-system/canonical/`.**

Measured, not assumed:

- `q-consult/canonical/` is live: 22 markdown files, last written 2026-08-20.
- `q-system/canonical/` in consulting is frozen at 2026-07-01 template stubs: exactly
  10 tracked files. Its `pricing-framework.md` is 27 lines and contains no prices; the
  live one is 416 lines.
- `plugins/kipi-core/kipi-mcp/canonical/` is frozen at 2026-06-10.
- 1,345 founder-typed messages in the consulting transcripts contain 14 "read the
  canonical files" asks and 7 "you missed it, it's in the file". The same patterns
  occur **zero** times across 770 founder-typed messages in kipi-system.

The digest that exists to prevent this is pointed at a fourth, empty location.
`kipi_canonical_digest` resolves `canonical_dir` to
`~/.kipi-system/instances/{name}/canonical` (`paths.py:130`), which holds zero files.
It returns every file "not found" and `valid: false`.

**Nothing catches it.** `digest["valid"]` is read nowhere outside its own unit test, and
the one verifier check naming `canonical-digest.json` (`bus_verifier.py:102`) is
unreachable dead code -- the file sits in phase 1's `checks` dict but in neither
`required` nor `optional`. Even reached, it is key-presence only.

## Goals

- The canonical-digest check is reached, is substantive, and cannot pass on an empty,
  scaffold-only, or `error`-bearing digest.
- Exactly ONE resolver decides where an instance's canonical tree lives, and it fails
  closed rather than guessing.
- Every skeleton-shipped reference resolves through that resolver.
- The dead trees are gone, the plugin copy stops regenerating, and no consumer breaks.

## Non-goals

- **Part 1 (`paths.py` `canonical_dir`) is NOT in this PRD.** It is covered by the
  approved, Codex-reviewed `prd-single-runtime-state-authority-2026-07-24` and its open
  p0 issue `srsa-authoritative-path-contract` (`allowed_files` exactly
  `[paths.py, test_paths.py]`). That issue is EXECUTED alongside this PRD.
- **Part 5 (`my_project_dir`) rides in that same srsa issue** -- same file, same defect.
  **Correction (finding-28, measured):** the earlier claim that `valid: true` is
  *unreachable* without it was WRONG. `_validate_digest` needs 5 of 7 checks; dropping
  `current_state.works_today` still leaves 6 available. So Part 5 can stay broken while
  the headline signal goes green. That is precisely why the acceptance criteria below
  assert `current_state` explicitly instead of trusting `valid`.
- Changing what canonical files *say*. Read-path only.
- Consolidating the three trees into one schema.

## Proposed approach

### One resolver, not two (finding-16, finding-17, finding-18)

The first draft said "the skeleton uses `instance_root()`, the MCP uses the registry
formula -- two resolvers, deliberately." **That was wrong, and measuring it proved it.**
Running both over the 20 registered instances that exist on disk:

| Instance class | `instance_q_dir` | `instance_root()` | registry formula | agree |
|---|---|---|---|---|
| named domain dir, registry agrees | set | that dir | same dir | yes |
| **named domain dir, registry stale** | `null` | that dir | `q-system` | **NO (4 instances)** |
| no domain dir | `null` | `q-system` | `q-system` | yes |
| **`q-system` has no `canonical/`** | `null` | `q-system` | `q-system` | agree, both wrong (2) |

Instance names are omitted on purpose: this repo is public and the client-name guard
blocks them. Enumerate the affected set locally with the resolver itself rather than a
hand-maintained list (finding-11):

```bash
python3 q-system/.q-system/scripts/evidence_ledger.py --audit-instance-roots
```

**4 of 20 disagree**, and in all four the registry is the stale one: those instances
have a real domain dir containing `canonical/` while `instance_q_dir` is null. Two
authorities that disagree on 20% of the fleet is a defect, not a design. Two more
resolve to a directory with no `canonical/` at all.

So: one resolver, registry-backed, failing closed. It reconciles by (a) filling in the
missing `instance_q_dir` values the glob already proves, and (b) refusing rather than
guessing when the registry and the filesystem still disagree, when two named `q-*` dirs
both carry `canonical/` (today `sorted()[0]` silently wins -- finding-17), or when the
resolved directory has no `canonical/` (finding-18).

### The verifier can fail (finding-13)

Three defects, not one, and each needs its own mutation-sensitive test:

1. **Unreachable.** `canonical-digest.json` is in no list, so the lambda never runs.
2. **Not substantive.** Key-presence passes an all-empty digest.
3. **The `error` short-circuit.** `bus_verifier.py:46-52` checks `"error" in data`
   BEFORE the structure check and emits `warn` -- without setting `all_pass = False`.
   So a required file `{"error": "canonical digest unavailable"}` yields `pass: true`
   today and would still do so after fixes 1 and 2. This is the one the first draft
   missed entirely.

### Sequencing is a production hazard, not a preference (finding-27)

Making `canonical-digest.json` **required** while `canonical_dir` still points at the
empty plugin-data path turns **every phase-1 run red fleet-wide**. The bus-verifier work
therefore must not land before srsa. This is encoded as an executable precondition in
the issue's own `required_checks`, not as a sentence in this PRD.

### The false-green risk, re-aimed (finding-15, measured)

The first draft warned that fenced `## Format` templates in "the real canonical files"
could manufacture a `valid: true`. **Measured, the artifacts are in the FOSSIL tree, not
the live one:**

| Tree | decisions | discovery | objections | talk-tracks |
|---|---|---|---|---|
| fossil `q-system/canonical/` | 1 fenced heading | 1 | 1 | 1 |
| live `q-consult/canonical/` | 0 | 0 | 0 | 0 |

Across all 22 live files there is exactly **one** heading-shaped line inside a fence, in
`market-intelligence.md`, which the digest does not parse. So the scaffold-green risk is
a property of reading the fossil -- the state the fix moves away from.

That does not make the parser safe. `_split_sections` still does not recognize fences,
`_parse_decisions` matches any heading containing `rule` (so `Starter Rules` counts), and
`_parse_objections` accepts every non-empty heading. The mitigation stays: **assert real
values.** `q-consult/canonical/decisions.md:219` carries the real heading
`RULE-2026-08-18-A`, which exists in no template and in no fossil file. That string is
the assertion.

### The live tree does NOT yield `valid: true` (measured 2026-08-22, corrects this PRD)

Running `canonical_digest` directly against the live tree
(`q-consult/canonical/` + `q-consult/my-project/`) returns **`valid: False`**, with all
five files found and `warnings: []`. Only 3 of the 7 `_validate_digest` checks pass:

| check | live result | why |
|---|---|---|
| `talk_tracks.metaphor` | FAIL | talk-tracks.md was retired to a pointer doc; no `metaphor` heading |
| `talk_tracks.definition` | FAIL | same |
| `objections` non-empty | pass | 5 headings, all from the retirement note |
| `current_state.works_today` | FAIL | heading is `What is true now`, not `works today` |
| `discovery.questions` | FAIL | items sit under `###` children; `## Unanswered Questions` has an empty body |
| `decisions` non-empty | pass | 10, incl. `RULE-2026-08-18-A` |
| `warnings < 3` | pass | 0 |

**This corrects the PRD's own premise.** The read-path fix alone cannot make the headline
signal green, because the parsers were written against the 2026-07-01 template shape and
the live files no longer have that shape. Three consequences, all load-bearing:

1. **`valid` is unusable as an acceptance signal in either direction.** It was already
   wrong to assert `valid: true` (finding-14). It is now also wrong to treat `valid:
   false` as proof the path is broken. Every acceptance criterion asserts named strings.
2. **Loosening a parser to make `valid` go green is forbidden.** That is precisely the
   false-green this PRD exists to eliminate, and it would be the easiest way to fake a
   pass on any criterion below.
3. **The parser/live-shape mismatch is a real defect and is NOT in this PRD.** Read-path
   only. Captured as its own spillover item rather than absorbed here.

The discriminator that survives all of this is a **dated** rule id. Measured across both
trees: the live `decisions.md` has exactly 1 heading matching
`RULE-\d{4}-\d{2}-\d{2}`; the fossil `q-system/canonical/decisions.md` has **0** (it
carries `RULE-XXX`, `RULE-001`, `RULE-002`, `RULE-003` -- template scaffolding only).
The fossil is therefore a genuine negative control: a checker asserting a dated rule id
passes against the live tree and fails against the fossil, which is the exact distinction
this PRD is about.

### Deletions, in order

Unchanged from the first draft and still load-bearing: unhook consumers, then delete
consulting's fossil tree, then delete the plugin copy **in the skeleton** (`plugins/` is
mirrored by `rsync -a --delete --delete-excluded`, `kipi-update.sh:2460`, with no
`canonical` exclude, so deleting it anywhere else regenerates it), then the two
instance-owned council fossils under consulting's `.claude/skills/` (not covered by
`config_source_manages`, `kipi-update.sh:1279-1296`).

Two consumers the first draft missed:

- `RECEIPT_RELATIVE_PATH = "q-system/canonical/.containment-receipt.json"`
  (`verify-containment-export.py:30-32`) -- loaded before any export path is checked, so
  the deletion breaks it first (finding-22).
- `_validate_file_receipt` enforces `source_path == destination_path` and both must be in
  `EXPECTED_EXPORT_PATHS`, while the source is read as a git blob from the skeleton
  commit and the destination from the instance owner root. Repointing both to `q-consult`
  makes the skeleton source blob absent; repointing one violates the equality check. The
  receipt schema needs an explicit source/destination split (finding-7, finding-23).

### Cross-repo and `.claude/` work cannot ride an issue's `allowed_files`

Two structural limits the first draft ignored:

- **Cross-repo (finding-1, finding-26).** The issue runner receipts paths in THIS repo.
  Consulting's deletions cannot be authorized by an `allowed_files` list here. The
  kipi-system-side deliverable is a checker that inspects consulting and fails when the
  fossil is present; the deletions themselves are performed in consulting and *proved* by
  that checker running against a real path (finding-25 -- a checker that is merely
  `exit 0` must not be able to pass).
- **`.claude/` (finding-21, finding-5).** Every entry disallows `.claude/rules/**`, so no
  entry could reconcile `folder-structure.md:257-264` or the four frontmatter globs. That
  work goes through `apply-claude-changes.sh`, the sanctioned proposal path the
  `claude-path-write-guard` hook enforces, as its own entry.

## Alternatives considered

- **Fold Part 1 into this PRD.** Rejected: `prd-single-runtime-state-authority` is
  approved and Codex-reviewed with eight split issues; re-specifying discards that.
- **Keep two resolvers (the first draft's choice).** Rejected on measurement: they
  disagree on 4 of 20 instances. Recorded here rather than deleted because the PRD
  originally shipped this and the reversal is the point.
- **Point skeleton references at `q-consult/` directly.** Rejected: 8 registered
  instances have `instance_q_dir: null`; the path is meaningless there.
- **Delete first, fix consumers when they break.** Rejected: the containment receipt is
  loaded before anything else, so the first export after deletion fails closed.
- **Let the fossil-absence checker be a plain script in this repo.** Rejected as a
  false-green shape: an `exit 0` body would satisfy both its own checks (finding-25).

## Scenarios

- **The council persona that had the data all along.** Quick Council on pricing in
  consulting; `quick.md:16` reads the 2026-07-01 stub and the persona says "I don't have
  data to ground this", exactly as `SKILL.md:44` predicts, while 416 lines of live pricing
  sit one directory over. After the resolver work the same run grounds on `q-consult/`.
- **The morning run that reported healthy while reading nothing.** Phase 1 writes an
  all-empty `canonical-digest.json`; `bus_verifier` never reaches the check and returns
  `pass: true`. Afterwards the same digest hard-fails with a named reason.
- **The digest that reports an error and still passes.** Phase 1 writes
  `{"error": "canonical digest unavailable"}`. The `error` branch emits `warn` and leaves
  `all_pass` untouched, so `pass: true`. This survives the reachability and substance
  fixes; only the `error`-branch fix catches it.
- **The fleet outage from a correct fix in the wrong order.** Bus-verifier work lands
  before srsa. `canonical-digest.json` is now required, `canonical_dir` still resolves to
  the empty plugin-data path, and every phase-1 run goes red on 23 instances.
- **The green that proves nothing.** A council file is edited to
  `q-system//canonical/discovery.md`. The literal-substring bypass check passes; the dead
  tree is still being read (finding-19).

## Risks and rollback

- **A `valid: true` from scaffolding.** Mitigated by asserting `RULE-2026-08-18-A`, a
  real value present in no template. Never assert `valid` alone.
- **A bypass check that matches a string instead of an invariant.** The Part 3 check
  asserts the resolver is *called* by the council workflows, not merely that a substring
  is absent.
- **`ensure_dirs()` writing into the repo.** `paths.py:218-221` mkdirs `canonical_dir`
  and `my_project_dir`; once repo-derived, an unset `repo_dir` would create directories
  inside the real plugin dir. `test_paths.py:136` exercises it. Owned by srsa.
- **`conftest.py:58,66` has no fixture with a non-null `instance_q_dir`**, so the
  registry branch would ship untested. Owned by srsa.
- **Rollback:** every change is a tracked commit; the deleted trees stay recoverable from
  history. Deletions use `git rm`, never `rm`.

## Resolved decisions

Each decision names the executable that holds it. A decision held only by prose here is
not held by anything.

- **Part 1 stays out; execute the existing srsa issue.** Held by that issue's own
  `required_checks` (`pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py`) and its
  `bypass_check`. Rationale: it is approved and Codex-reviewed.
- **Part 5 rides in srsa, and its success is asserted separately.** Held by the same
  pytest check plus this PRD's explicit `current_state` assertion. Rationale: finding-28
  proved `valid: true` alone does not require it.
- **ONE resolver, registry-backed, fail-closed.** Held by the pytest suite named in
  `crpr-one-canonical-resolver`. Rationale: measured disagreement on 4 of 20 instances.
  This reverses the first draft.
- **Sequencing is executable.** Held by a precondition inside
  `crpr-bus-verifier-can-fail`'s `required_checks` that refuses while `canonical_dir`
  still resolves to plugin-data. Rationale: the alternative is a 23-instance outage.
- **Cross-repo and `.claude/` work get their own entries.** Held by the
  `claude-path-write-guard` hook (which blocks any unsanctioned `.claude/` write) and by
  a consulting-inspecting checker script. Rationale: an `allowed_files` list cannot
  authorize either.
- **Nothing is deleted without a tracked commit.** Held by the `destructive-op-deny.sh`
  hook, which blocks `rm -rf` and `git clean -fd` regardless of any autonomy grant.

## Issues

```json
[
  {
    "id": "crpr-one-canonical-resolver",
    "title": "One fail-closed resolver for an instance canonical root",
    "finding_id": "finding-16",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/evidence_ledger.py",
      "q-system/.q-system/scripts/test_evidence_ledger.py",
      "instance-registry.json"
    ],
    "disallowed_files": [
      ".claude/**",
      "plugins/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test_evidence_ledger.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test_evidence_ledger.py",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "Write the failing cases FIRST and show them RED. instance_root() must FAIL CLOSED, not guess, on all three measured gaps: (a) two named q-* dirs both containing canonical/ (today sorted()[0] silently wins, finding-17); (b) a resolved directory with no canonical/ subdir, measured on the two instances whose q-system holds no canonical/ (finding-18); (c) registry instance_q_dir disagreeing with the filesystem, the four instances where the registry says null while a real domain dir containing canonical/ exists (finding-16); enumerate them with the --audit-instance-roots command in the PRD rather than hardcoding names, since this repo is public. Fill in those four instance_q_dir values in instance-registry.json (the registry is gitignored-safe to name locally, the PRD is not) so registry and filesystem agree, and make the resolver read the registry as authority with the filesystem as a cross-check that RAISES on mismatch. NOTE the harness convention: this suite is main-based with case_* functions and pytest collects ZERO tests from it (finding-3, finding-29), so the required_check invokes it directly with python3; do NOT convert it to pytest as a way of making a check go green."
  },
  {
    "id": "crpr-bus-verifier-can-fail",
    "title": "Make the canonical-digest check reachable, substantive, and error-proof",
    "finding_id": "finding-13",
    "priority": "p0",
    "allowed_files": [
      "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_verifier.py",
      "plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py"
    ],
    "disallowed_files": [
      "plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py",
      ".claude/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py"
    ],
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py -k 'reachable or substantive or error_key'",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "THREE independent defects, THREE independent tests, each shown RED first and each killed by its own mutation. (1) REACHABLE: canonical-digest.json is in phase 1 required; reverting only this must turn a test red. (2) SUBSTANTIVE: the exact empty digest captured 2026-08-22 must be rejected - talk_tracks {}, objections [], current_state {}, discovery {}, decisions [], warnings 5 not-found messages, valid false; reverting only the lambda must turn a DIFFERENT test red. (3) ERROR SHORT-CIRCUIT (finding-13): bus_verifier.py:46-52 tests 'error' in data BEFORE the structure check and emits warn WITHOUT setting all_pass=False, so a required canonical-digest.json of exactly {\"error\":\"canonical digest unavailable\"} yields pass:true even after (1) and (2). Assert verify() returns pass False for that input. A required-file failure is a hard fail per bus_verifier.py:42-81, so assert on pass, never on the presence of a warn. SEQUENCING (finding-27): making this file required while canonical_dir still resolves to ~/.kipi-system/instances/<name>/canonical turns every phase-1 run red on 23 instances. Add a precondition test asserting canonical_dir does NOT resolve under the plugin-data base; it fails until srsa lands, which is the intended block. (4) NON-EMPTINESS IS NOT SUBSTANCE (finding-14, finding-9): a fixture-level test CANNOT prove the live tree was read, so this entry must not claim it does. The structure check must reject Codex's exact nonempty placeholder {\"talk_tracks\":{\"metaphor\":\"placeholder\"},\"objections\":[],\"current_state\":{},\"discovery\":{},\"decisions\":[],\"warnings\":[],\"valid\":false} -- assert on that literal, not on 'some field is nonempty'. NEVER assert valid alone in either direction: measured 2026-08-22, the LIVE tree also returns valid:false (3 of 7 checks), so valid:true is not the success signal and valid:false is not the failure signal. Proving a real tree was read belongs to crpr-digest-asserts-real-canonical, which owns that assertion end to end. Do NOT loosen any parser in morning_init.py to move valid; that file is not in allowed_files precisely so this cannot happen."
  },
  {
    "id": "crpr-digest-asserts-real-canonical",
    "title": "Prove the digest read the live canonical tree, by named value",
    "finding_id": "finding-14",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-canonical-digest-real-values.py"
    ],
    "disallowed_files": [
      "plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py",
      ".claude/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test-canonical-digest-real-values.py --self-test"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test-canonical-digest-real-values.py --self-test",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "Closes finding-14 and finding-9, which no other entry can: every other entry is fixture-level and structurally cannot prove a live tree was read. This checker calls canonical_digest against a REAL instance tree and asserts NAMED values. Rules: (a) NEVER assert valid -- measured 2026-08-22 the live tree returns valid:false (3 of 7), so valid is not a signal in either direction; (b) NEVER assert mere non-emptiness -- that is the exact false green finding-14 names. (c) DERIVE the expected value, do not hardcode it: this repo is PUBLIC, so grep the instance's own decisions.md for a dated rule id matching RULE-[0-9]{4}-[0-9]{2}-[0-9]{2} with an INDEPENDENT reader (regex over the raw file), then assert canonical_digest's parsed decisions[] contains that same id. Two independent readers agreeing on a value present in that one tree is what proves the tree was read; it also keeps the checker instance-agnostic and leaks no client content into a public repo. (d) NEGATIVE SELF-TEST, non-optional and wired as --self-test so the required_check exercises it: the FOSSIL tree is the control. Measured: live decisions.md has exactly 1 dated rule id, fossil q-system/canonical/decisions.md has 0 (it carries only RULE-XXX / RULE-001 / RULE-002 / RULE-003 template scaffolding). The checker MUST pass against the live tree and MUST fail against the fossil; --self-test asserts BOTH and exits nonzero if the fossil case passes. A checker that cannot fail against the fossil is the defect this PRD exists to remove. (e) Show it RED first: run it before the resolver work lands and record the failure reason. (f) If the named instance is absent, REFUSE (exit nonzero) rather than skip -- a skip is a false green."
  },
  {
    "id": "crpr-skeleton-resolves-live-canonical",
    "title": "Council and wiring-check call the resolver instead of hardcoding a path",
    "finding_id": "finding-19",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-ops/skills/council/SKILL.md",
      "plugins/kipi-ops/skills/council/workflows/quick.md",
      "plugins/kipi-ops/skills/council/workflows/debate.md",
      "plugins/kipi-core/commands/wiring-check.md",
      "q-system/.q-system/scripts/test/test-council-resolves-canonical.sh"
    ],
    "disallowed_files": [
      ".claude/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-council-resolves-canonical.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-council-resolves-canonical.sh",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "THIRTEEN references, not nine (finding-12, finding-30, recounted: SKILL.md 4, quick.md 4, debate.md 4, wiring-check.md 1). The check must assert the resolver is REACHED, not that a substring is absent: a literal negated grep on q-system/canonical/ is a false green because q-system//canonical/ or a concatenated path keeps the dead tree while passing (finding-19). Write test-council-resolves-canonical.sh to (a) assert every one of the 13 sites names the resolver, and (b) run a positive control against a fixture instance whose domain dir is NOT q-system and assert the resolved path is that dir. Show it RED before the edit. NEVER hardcode q-consult/: 8 registered instances have instance_q_dir null. ALSO IN SCOPE (finding-20): council's q-system/my-project/ references (SKILL.md:37,39 relationships.md and competitive-landscape.md) are the same defect in the same files and are left pointing at a fossil if only canonical is fixed."
  },
  {
    "id": "crpr-unhook-dead-canonical-consumers",
    "title": "Stop requiring the dead tree, then delete the skeleton's plugin copy",
    "finding_id": "finding-22",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/verify-containment-export.py",
      "q-system/.q-system/scripts/test/test-verify-containment-export.sh",
      "plugins/kipi-core/kipi-mcp/canonical/**"
    ],
    "disallowed_files": [
      ".claude/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-verify-containment-export.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-verify-containment-export.sh",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "THREE hardcoded consumers, not two. Beyond EXPECTED_EXPORT_PATHS:24-28, RECEIPT_RELATIVE_PATH:30-32 is q-system/canonical/.containment-receipt.json and is loaded BEFORE any export path is validated, so the deletion breaks it first (finding-22). Define the receipt schema change explicitly (finding-7, finding-23): _validate_file_receipt requires source_path == destination_path AND membership in EXPECTED_EXPORT_PATHS, while the source is read as a git blob from the skeleton commit and the destination from the instance owner root - so repointing both to q-consult makes the source blob absent and repointing one violates the equality check. The spec must state the new source/destination split and bump the receipt schema_version. The required_check is a NEW harness because the bare script cannot run: it requires --instance and exits 2 on argparse (finding-2, finding-24); the harness must invoke it with a real instance and must FAIL if given a default. Prove exit 0 against an instance whose canonical lives outside q-system/. Only after that: git rm the SKELETON plugins/kipi-core/kipi-mcp/canonical/ tree, because plugins/ is mirrored with rsync -a --delete --delete-excluded (kipi-update.sh:2460) and deleting it elsewhere regenerates it."
  },
  {
    "id": "crpr-reconcile-claude-rules",
    "title": "Reconcile the rules that mandate the dead path, via the sanctioned path",
    "finding_id": "finding-21",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh"
    ],
    "disallowed_files": [
      "plugins/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-claude-rules-canonical-reconciled.sh",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "folder-structure.md:257-264 actively mandates that all scripts MUST resolve QROOT to q-system/, a direct contradiction of this PRD; four skeleton-synced rules carry frontmatter globs on the dead path (md-hygiene.md:4, anti-misclassification.md:4, sycophancy.md:5, folder-structure.md:236). No other entry can touch these: every one disallows .claude/** (finding-21, finding-5). The EDITS go through apply-claude-changes.sh, the sanctioned proposal path enforced by the claude-path-write-guard hook - do NOT write .claude/ directly and do NOT weaken the hook. This entry allowed_files holds only the checker, which asserts the contradiction is gone and the four globs resolve through the resolver. Show it RED first. Also enumerate the ~20 agent-pipeline prompts under q-system/.q-system/agent-pipeline/agents/ that reference the path and report them explicitly; if this entry does not repoint them, say so rather than implying coverage (finding-11)."
  },
  {
    "id": "crpr-consulting-fossil-cleanup",
    "title": "Delete consulting frozen canonical tree and its two council fossils",
    "finding_id": "finding-25",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh"
    ],
    "disallowed_files": [
      ".claude/**",
      "plugins/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh",
    "required_reviews": [
      "runtime-owner"
    ],
    "acceptance": "RUNS LAST, after crpr-unhook-dead-canonical-consumers has shipped. SCOPE LIMIT, stated plainly (finding-1, finding-26): the issue runner receipts paths in THIS repo only, so it cannot authorize or receipt the consulting deletions. The kipi-system deliverable is the checker; the deletions are performed in /Users/assafkipnis/projects/consulting as tracked git rm commits and are PROVED by this checker. The checker must not be able to pass vacuously (finding-25): an exit 0 body must fail its own negative self-test, so it takes the consulting path as an argument, refuses if that path does not exist, asserts the 10 tracked files under q-system/canonical/ are gone, asserts q-consult/canonical/ still has its 22 files, and asserts the two instance-owned council fossils (.claude/skills/council/ SKILL.md plus workflows/quick.md and workflows/debate.md, and the orphaned .claude/skills/workflows/ pair) no longer name the dead tree. Those .claude/skills/ copies are NOT covered by config_source_manages (kipi-update.sh:1279-1296) so they persist untouched; fixing only the plugin copy leaves two live wrong copies. Deleting consulting/q-system/canonical/ is safe from the updater because canonical is in INSTANCE_OWNED_SUBTREES (kipi-update.sh:64). Show the checker RED against consulting BEFORE the deletion. Afterwards run the fleet updater in DRY mode against consulting and confirm no restore and no reversion of skeleton edits."
  }
]
```
