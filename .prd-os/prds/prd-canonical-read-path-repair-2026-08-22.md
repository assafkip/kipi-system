---
id: prd-canonical-read-path-repair-2026-08-22
title: Canonical Read Path Repair
status: idea
created_at: 2026-08-22T19:37:28Z
updated_at: 2026-08-22T19:37:28Z
owner: sana
reviewers: []
findings_path: .prd-os/findings/prd-canonical-read-path-repair-2026-08-22-findings.jsonl
---

# Canonical Read Path Repair

## Problem

Consulting holds three diverged canonical trees with identical filenames, and every
consumer in the fleet is split cleanly between them: **everything the instance wrote
points at `q-consult/canonical/`; everything the skeleton shipped points at
`q-system/canonical/`.**

Measured, not assumed:

- `q-consult/canonical/` is live: 22 files, 4,478 lines, last written 2026-08-20.
- `q-system/canonical/` in consulting is frozen at 2026-07-01 template stubs. Its
  `pricing-framework.md` is 27 lines and contains no prices; the live one is 416 lines.
- `plugins/kipi-core/kipi-mcp/canonical/` is frozen at 2026-06-10.
- 1,345 founder-typed messages in the consulting transcripts contain 14 "read the
  canonical files" asks and 7 "you missed it, it's in the file". The same patterns
  occur **zero** times across 770 founder-typed messages in kipi-system. The defect is
  consulting-specific, and it is the instance where the trees diverged.

The digest that exists to prevent this is itself pointed at a fourth, empty location.
`kipi_canonical_digest` resolves `canonical_dir` to
`~/.kipi-system/instances/{name}/canonical` (`paths.py:130`), which holds zero files.
It returns every file "not found" and `valid: false`. It exists to save 40-60K tokens
against reading full canonical; when it returns nothing, agents fall back to raw files
and pick from three copies.

**Nothing catches any of this.** `digest["valid"]` is read nowhere outside its own unit
test, and the one verifier check that names `canonical-digest.json`
(`bus_verifier.py:102`) is unreachable dead code — the file is listed in phase 1's
`checks` dict while appearing in neither `required` nor `optional`, so the lambda never
runs. Even if it ran, it is key-presence only (`"talk_tracks" in d`), so the exact empty
digest observed today would pass it.

File length and wrong-file are one chain: 4,478 lines is *why* a digest exists. Digest
broken to raw-file fallback to three copies to wrong answer.

## Goals

- The verifier can fail on an empty digest, and is reached at all.
- Every skeleton-shipped reference to canonical resolves the instance's live tree
  through one tested resolver, never a hardcoded path.
- The dead trees are gone, and the plugin copy stops regenerating on the next sync.
- No consumer breaks as a result of the deletions.

## Non-goals

- **Part 1, repointing `paths.py` `canonical_dir`, is deliberately NOT in this PRD.**
  It is already covered by the approved, Codex-reviewed
  `.prd-os/prds/prd-single-runtime-state-authority-2026-07-24.md` and its open p0 issue
  `.prd-os/issues/srsa-authoritative-path-contract.md`, whose `allowed_files` is exactly
  `[paths.py, test_paths.py]` and whose `required_checks` are already defined. Its
  resolution formula is already decided and reviewed: if `instance_q_dir` is set, use
  `<path>/<instance_q_dir>`; otherwise `<path>/<subtree_prefix>/q-system`; missing or
  ambiguous mappings fail closed. `instance-registry.json` already records
  `"instance_q_dir": "q-consult"` for consulting. Re-specifying it here would duplicate a
  Codex review already paid for. That issue is EXECUTED alongside this PRD, not inside it.
- **Part 5, `my_project_dir`, is executed inside that same srsa issue**, not here.
  `morning_init.py:192` reads `current_state` from `paths.my_project_dir`, which has the
  identical defect and the identical fossil twin (`q-system/my-project/`, same 2026-07-01
  commit). It is a one-property change in the same file that srsa already owns. Splitting
  it out would put two issues in one file. Recorded here because Part 1's own success
  criterion is unreachable without it: `_validate_digest` (`morning_init.py:534-544`)
  needs 5 of 7 checks and one of them is `current_state.works_today`.
- Changing what the canonical files *say*. This is a read-path repair only.
- Consolidating the three trees into one schema. Only the dead copies are removed.

## Proposed approach

Four issues, ordered. The order inside Part 4 is load-bearing: a consumer that hard-codes
a path must stop requiring it *before* the path is deleted, or the deletion is a runtime
failure rather than a cleanup.

### Reuse, do not invent

`q-system/.q-system/scripts/evidence_ledger.py:81-93` already implements the resolver,
and it is tested by `q-system/.q-system/scripts/test_evidence_ledger.py`:

```python
def instance_root(repo=None) -> Path:
    repo = Path(repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    named = [p for p in sorted(repo.glob("q-*"))
             if p.is_dir() and p.name != "q-system" and (p / "canonical").is_dir()]
    return named[0] if named else repo / "q-system"
```

It resolves to `q-consult/` on consulting and `q-system/` on the skeleton. Precedent it
cites: `capability-map-gen.py:390`. Skeleton-shipped references use this. They must never
hardcode `q-consult/`, which is meaningless in the 8 registered instances whose
`instance_q_dir` is null.

For the MCP side (Part 1, srsa), the registry formula wins over a second glob-based
resolver: it is the already-reviewed answer, and it fails closed on ambiguity where a
glob silently picks `sorted()[0]`.

### Part 2 — the verifier can fail

Two steps, in this order, because doing only the second leaves the check unreachable and
doing only the first arms a check that cannot fail:

1. Wire `canonical-digest.json` into phase 1's `required` list. Semantics at
   `bus_verifier.py:42-81`: `False` on a **required** file is a hard fail; `False` on an
   **optional** file is only a warn. A warn is what let this sit.
2. Replace the key-presence lambda with a substantive assertion: the digest is valid only
   if it actually carries content, not merely the keys.

Reproducer first. The exact empty digest observed today goes into a pytest case, red
before the fix:

```json
{"talk_tracks":{},"objections":[],"current_state":{},"discovery":{},
 "decisions":[],"warnings":["...5 not-found messages..."],"valid":false}
```

### Part 3 — skeleton references resolve the live tree

Nine hardcoded `q-system/canonical/` references ship from the skeleton to every instance:

| File | Lines |
|---|---|
| `plugins/kipi-ops/skills/council/SKILL.md` | 37, 38, 39, 53 |
| `plugins/kipi-ops/skills/council/workflows/quick.md` | 15, 16, 17, 77 |
| `plugins/kipi-ops/skills/council/workflows/debate.md` | 15, 17, 18, 201 |
| `plugins/kipi-core/commands/wiring-check.md` | 90 |

Council's own `SKILL.md:44` already describes the resulting behaviour without naming the
cause: "If a canonical file is empty/template, the persona says 'I don't have data to
ground this'." That is the fossil tree being read, reported as a content problem.

`.claude/rules/folder-structure.md:257-264` must be reconciled in the same change. It
actively mandates "All scripts MUST resolve QROOT to `q-system/`" — a direct
counter-precedent. Leaving it makes the rule and the code disagree, which is how the next
person re-introduces the hardcode and passes review. Editing `.claude/` goes through the
sanctioned proposal path (`apply-claude-changes.sh`); the `claude-path-write-guard` hook
blocks anything else, and that is the gate doing its job.

### Part 4 — remove the dead copies, in order

- **(a) FIRST, unhook the consumers.** `verify-containment-export.py:24-28` hard-codes
  `q-system/canonical/discovery.md` and `pricing-framework.md` as REQUIRED export paths.
  Deleting before fixing this is a runtime failure, not a warning. Four skeleton-synced
  rules carry frontmatter globs on the path (`md-hygiene.md:4`,
  `anti-misclassification.md:4`, `sycophancy.md:5`, `folder-structure.md:236`), plus ~20
  agent-pipeline prompts under `q-system/.q-system/agent-pipeline/agents/`.
- **(b) THEN delete `consulting/q-system/canonical/`** (10 tracked files, frozen
  2026-07-01). Safe from the updater: `canonical` is in `INSTANCE_OWNED_SUBTREES`
  (`kipi-update.sh:64`), so it is never restored and never `--delete`d.
- **(c) Delete the plugin canonical copy in the SKELETON**
  (`kipi-system/plugins/kipi-core/kipi-mcp/canonical/`). Deleting it in consulting does
  NOT stick: `plugins/` is mirrored by `rsync -a --delete --delete-excluded`
  (`kipi-update.sh:2460`) with no `canonical` exclude, so it regenerates from the
  skeleton. The skeleton is the only place the deletion holds.
- **(d) Consulting's TWO instance-owned council fossils.** `.claude/skills/council/`
  (`SKILL.md:32-34,48`; `workflows/quick.md:11-13,73`; `workflows/debate.md:11,13,14,197`)
  and the orphaned `.claude/skills/workflows/` pair. `.claude/skills/` is NOT managed by
  the syncer — `config_source_manages` (`kipi-update.sh:1279-1296`) covers only
  `settings.json`, `agents/*.md`, `rules/*.md`, `output-styles/*.md`, `plugins/*/*` — so
  these persist untouched and currently point at the dead tree. Fixing only the plugin
  copy leaves two live wrong copies.

Nothing is silently deleted: every deletion is a tracked `git rm` with the reason in the
commit message, reversible from history.

## Alternatives considered

- **Fold Part 1 into this PRD and mark the 2026-07-24 PRD superseded.** Rejected: that
  PRD is `status: approved` with `codex_reviewed_at: 2026-07-24` and was split into eight
  p0 issue specs. Re-specifying `paths.py` here throws away a paid Codex review and leaves
  eight open issues pointing at a superseded parent.
- **Point the skeleton references at `q-consult/canonical/` directly.** Rejected: these
  files ship fleet-wide via `kipi update`. 8 of the registered instances have
  `instance_q_dir: null`, so the path is meaningless there and would break more consumers
  than it fixes.
- **Write a second resolver for the skeleton side.** Rejected: `instance_root()` already
  exists, is tested, and is cited as precedent by `capability-map-gen.py:390`. A second
  resolver is a second thing to drift.
- **Delete the dead trees first and fix consumers when they break.** Rejected:
  `verify-containment-export.py` treats those two paths as required, so the first
  containment export after the deletion fails closed. Order is the whole point of Part 4.
- **Leave `bus_verifier.py`'s check optional and just make the lambda substantive.**
  Rejected: an optional file that fails the structure check only produces a `warn`
  (`bus_verifier.py:66-81`). A warn is exactly the signal that let an empty digest ship
  for months.
- **Make `morning_init` skip fenced code blocks as part of this work.** Rejected as scope
  creep, captured as spillover instead. It is a real defect (see Scenarios) but it is a
  parser bug, not a read-path bug, and bundling it would put two causes in one issue.

## Scenarios

- **The council persona that had the data all along.** The founder runs a Quick Council on
  a pricing question in consulting. `quick.md:16` sends the Investor persona to
  `q-system/canonical/talk-tracks.md` — the 2026-07-01 stub. The persona reports "I don't
  have data to ground this" exactly as `SKILL.md:44` predicts, while 416 lines of live
  pricing sit in `q-consult/canonical/pricing-framework.md`. After Part 3 the same run
  resolves through `instance_root()` to `q-consult/` and grounds on the live file.

- **The morning run that reported healthy while reading nothing.** Phase 1 writes
  `canonical-digest.json` with every field empty and `valid: false`. `bus_verifier`
  iterates `required` (calendar, gmail, notion), never reaches `canonical-digest.json`
  because it is in no list, and returns `pass: true`. After Part 2 the same digest lands
  the file in `required`, the substantive check returns `False`, and the phase hard-fails
  with a named reason.

- **The containment export that fails closed after a clean deletion.** Without Part 4(a),
  an operator deletes `consulting/q-system/canonical/` and the next
  `verify-containment-export.py` run raises `ContainmentBlocked` on a missing REQUIRED
  path. With (a) shipped first, the same run resolves through `instance_root()`, finds
  `q-consult/canonical/discovery.md`, and exits 0.

- **The plugin copy that comes back.** An operator deletes
  `consulting/plugins/kipi-core/kipi-mcp/canonical/`. The next fleet sync mirrors
  `plugins/` with `rsync -a --delete --delete-excluded` and no `canonical` exclude, and the
  2026-06-10 tree reappears. Part 4(c) deletes it in the skeleton, which is the only copy
  the mirror reads from.

- **The false green.** After Parts 1-5 an engineer calls `kipi_canonical_digest` from
  consulting and sees `valid: true`. This is not sufficient evidence. See Risks.

## Risks and rollback

- **A `valid: true` that comes entirely from fence artifacts.** `morning_init`'s markdown
  parsers (`_split_sections`, `morning_init.py:467-481`) do NOT skip fenced code blocks.
  The `## Format <!-- pin -->` templates inside the real canonical files contain
  `### RULE-XXX: [Name]` and `### "[Objection as they say it]"` inside fences, and these
  parse as real content — `_parse_decisions` matches on `"rule" in heading.lower()`. So a
  `valid: true` can be produced entirely by template scaffolding. **Every acceptance check
  in this PRD asserts on a REAL value** — a known decision ID from
  `q-consult/canonical/decisions.md`, a known objection string — never on `valid` alone. A
  green nobody has seen go red for the right reason is decoration.
- **`ensure_dirs()` writing into the repo.** `paths.py:218-221` includes `canonical_dir`
  and `my_project_dir` in the `mkdir` loop. Once those resolve from the repo rather than
  plugin-data, an `ensure_dirs()` call with an unset `repo_dir` would create directories
  inside the real plugin dir. `test_paths.py:136` is the case that exercises this. Handled
  in srsa, named here because it is this PRD's Part 5 dependency.
- **Test fixtures with no instance mapping.** `conftest.py:58,66` has NO fixture with a
  non-null `instance_q_dir`, so the registry branch of the new resolver would ship
  untested. Adding one is part of srsa's acceptance.
- **Rollback:** every change is a tracked commit. The deleted trees are frozen content
  recoverable from git history at any time; nothing is removed from the working tree
  without a commit that names it.

## Resolved decisions

Each decision below names the executable that holds it. A decision recorded only as
prose here is not held by anything, so it does not belong in this list.

- **Part 1 stays out of this PRD.** Decided: execute the existing
  `srsa-authoritative-path-contract` issue instead. Held by that issue's own
  `required_checks` entry, `pytest -q plugins/kipi-core/kipi-mcp/tests/test_paths.py`,
  plus its `bypass_check` on the `ambiguous or plugin_cache_write` selector. Rationale:
  it is approved and Codex-reviewed; re-specifying it here throws that review away.
- **Part 5 rides in the srsa issue.** Decided: `my_project_dir` is fixed in the same
  `paths.py` change as `canonical_dir`, under that same pytest check. Rationale: same
  file, same defect. Part 1's success criterion (`valid: true` from consulting) is
  unreachable without it, because `_validate_digest` counts `current_state.works_today`.
- **The skeleton uses `instance_root()`, the MCP uses the registry formula.** Decided:
  two resolvers, deliberately. Held by the pytest suite
  `q-system/.q-system/scripts/test_evidence_ledger.py` on the skeleton side and by
  `test_paths.py` on the MCP side. Rationale: the skeleton side has no registry access at
  read time; the MCP side has the registry and the reviewed fail-closed formula. Neither
  hardcodes an instance name.
- **Order inside Part 4 is (a) consumers, (b) consulting tree, (c) skeleton plugin copy,
  (d) consulting `.claude/skills` fossils.** Held by the issue runner: the
  `crpr-consulting-fossil-cleanup` spec cannot pass its `required_checks` script until
  `crpr-unhook-dead-canonical-consumers` has shipped, because that script asserts the
  fossil is absent AND `verify-containment-export.py` still exits 0. Rationale: (b)
  before (a) is a runtime failure; (c) in consulting instead of the skeleton regenerates
  on the next sync.
- **Nothing is deleted without a tracked commit.** Decided: `git rm`, never `rm`. Held by
  the `destructive-op-deny.sh` hook, which blocks `rm -rf` and `git clean -fd`
  irrespective of any autonomy grant. Rationale: standing rule — never silently delete,
  keep it reversible and auditable.

## Issues

```json
[
  {
    "id": "crpr-bus-verifier-can-fail",
    "title": "Make the canonical-digest check reachable and able to fail",
    "finding_id": "finding-1",
    "priority": "p0",
    "allowed_files": [
      "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_verifier.py",
      "plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py"
    ],
    "disallowed_files": [
      "plugins/kipi-core/kipi-mcp/src/kipi_mcp/paths.py",
      "q-system/canonical/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 -m pytest -q plugins/kipi-core/kipi-mcp/tests/test_bus_verifier.py"
    ],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Write the failing test FIRST, using the exact empty digest captured 2026-08-22: {\"talk_tracks\":{},\"objections\":[],\"current_state\":{},\"discovery\":{},\"decisions\":[],\"warnings\":[5 not-found messages],\"valid\":false}. Show it RED before any fix. Then (1) add canonical-digest.json to phase 1 `required` so the check is reached at all, and (2) replace the key-presence lambda at bus_verifier.py:102 with an assertion on CONTENT. Prove reachability separately from the assertion: a mutation that reverts only step (1) must turn a test red, and a mutation that reverts only step (2) must turn a different test red. A required-file False is a hard fail per bus_verifier.py:42-81; assert `pass` is False, not merely that a warn was emitted."
  },
  {
    "id": "crpr-skeleton-resolves-live-canonical",
    "title": "Skeleton-shipped references resolve the instance's live canonical tree",
    "finding_id": "finding-2",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-ops/skills/council/SKILL.md",
      "plugins/kipi-ops/skills/council/workflows/quick.md",
      "plugins/kipi-ops/skills/council/workflows/debate.md",
      "plugins/kipi-core/commands/wiring-check.md",
      "q-system/.q-system/scripts/test_evidence_ledger.py"
    ],
    "disallowed_files": [
      ".claude/rules/**",
      "q-system/canonical/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/scripts/test_evidence_ledger.py",
      "bash -c '! grep -rn \"q-system/canonical/\" plugins/kipi-ops/skills/council/ plugins/kipi-core/commands/wiring-check.md'"
    ],
    "required_reviews": ["runtime-owner"],
    "acceptance": "All nine hardcoded q-system/canonical/ references (council SKILL.md:37,38,39,53; quick.md:15,16,17,77; debate.md:15,17,18,201; wiring-check.md:90) resolve through instance_root() from evidence_ledger.py:81-93. NEVER a hardcoded q-consult/ - 8 registered instances have instance_q_dir null and that path is meaningless there. Add a test case to test_evidence_ledger.py proving instance_root() resolves a non-q-system domain dir, since that is the case the skeleton's own fixtures never exercise. The grep check is a negative control: it must FAIL on the current tree before the edit."
  },
  {
    "id": "crpr-unhook-dead-canonical-consumers",
    "title": "Stop requiring the dead tree, then delete the skeleton's plugin copy",
    "finding_id": "finding-3",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/verify-containment-export.py",
      "q-system/.q-system/scripts/test/test-verify-containment-export.sh",
      "plugins/kipi-core/kipi-mcp/canonical/**"
    ],
    "disallowed_files": [
      ".claude/rules/**",
      "q-system/canonical/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/verify-containment-export.py"
    ],
    "required_reviews": ["runtime-owner"],
    "acceptance": "STEP ORDER IS LOAD-BEARING. First: verify-containment-export.py:24-28 stops hard-coding q-system/canonical/discovery.md and pricing-framework.md as REQUIRED export paths and resolves them through instance_root() instead; prove it by running the script from consulting (where q-system/canonical/ is the fossil) and getting exit 0 against q-consult/canonical/. Only then: git rm the skeleton's plugins/kipi-core/kipi-mcp/canonical/ tree - the skeleton copy, because plugins/ is mirrored with rsync -a --delete --delete-excluded (kipi-update.sh:2460) with no canonical exclude, so deleting it anywhere else regenerates it. Enumerate and report the ~20 agent-pipeline prompts under q-system/.q-system/agent-pipeline/agents/ that reference the path; if any are left pointing at a tree that still exists in the skeleton, say so explicitly rather than implying coverage."
  },
  {
    "id": "crpr-consulting-fossil-cleanup",
    "title": "Delete consulting's frozen canonical tree and its two council fossils",
    "finding_id": "finding-4",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh"
    ],
    "disallowed_files": [
      ".claude/rules/**",
      "plugins/**",
      ".prd-os/**"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/test/test-canonical-fossil-absent.sh"
    ],
    "required_reviews": ["runtime-owner"],
    "acceptance": "Runs LAST, after crpr-unhook-dead-canonical-consumers has shipped. In /Users/assafkipnis/projects/consulting: git rm the 10 tracked files under q-system/canonical/ (frozen 2026-07-01; safe because `canonical` is in INSTANCE_OWNED_SUBTREES at kipi-update.sh:64, so the updater neither restores nor --deletes it), and repoint the TWO instance-owned council fossils under .claude/skills/ - .claude/skills/council/ (SKILL.md:32-34,48; workflows/quick.md:11-13,73; workflows/debate.md:11,13,14,197) and the orphaned .claude/skills/workflows/ pair. .claude/skills/ is NOT covered by config_source_manages (kipi-update.sh:1279-1296), so these persist untouched and fixing only the plugin copy leaves two live wrong copies. The check in this repo is a fossil-absence assertion that must be shown RED against consulting before the deletion. Then re-run the fleet updater in DRY mode against consulting and confirm no restore of the deleted trees and no reversion of the skeleton edits."
  }
]
```
