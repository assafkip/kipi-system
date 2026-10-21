---
id: prd-design-chain-seal-reads-verdicts-2026-09-18
title: Design Chain Seal Reads Verdicts
status: approved
created_at: 2026-09-18T20:00:36Z
updated_at: 2026-09-18T20:21:13Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-design-chain-seal-reads-verdicts-2026-09-18-findings.jsonl
codex_reviewed_at: 2026-09-18T20:10:30Z
reviewed_by: claude-adversarial
---

# Design Chain Seal Reads Verdicts

## Problem

Source: `q-system/output/rca/rca-design-chain-trusts-its-own-account-2026-09-18.md` on branch
`fix/candidate-draft-one-definition`, the founder-approved plan of 2026-09-18 (ASK-1796), and
the founder's direction the same day after the adversarial review: "make the changes and also
make sure that we actually have all the design capabilities inside design chain... I want to
only have one slash command for design", clarified as "there needs to be one, and the one is
design-chain."

Measured 2026-09-18 against the live gate on throwaway rounds:

```
A seal: (0, 'sealed 1 page(s)')        readers all say LEAVE, tripwire FAIL, bio_gate BLOCKED
C (control, no standard.json) seal: 2  the gate is alive
B status-page (hand-typed receipt): (0, 'COMPLETE')
```

Two defects explain all ten gaps in the RCA:

1. The gate verifies the builder's account of the work. Checks it computes itself hold.
   Checks that read a file the builder wrote do not.
2. The outside judges are filed, never read. On 2026-09-17/18 three directions sealed against
   51 negative reader verdicts and 1 positive across 23 runs.

Distribution defect: nothing from design-chain is on `origin/main`, so no instance can
receive it, and `.claude/commands/` never syncs. The only fleet-wide home for the command is
`plugins/kipi-core/commands/`.

Entry-point defect: design work can start from at least five other doors (the three
`kipi-design` skills, `design-room`, `deck-ai`, plus third-party `frontend-design`,
`scroll-craft`, `figma` and the motion family), each auto-invoking on its own. Work that
starts there never meets the chain. On 2026-09-18 an animation was imitated from a copied
file while the skill that makes that animation was never loaded, and no check could tell.

CORRECTION to the first draft of this section (review finding-2, verified): the dependency
census read static imports only. The real carry set is 12 files: 8 `design-*.py` scripts
(including `design-ink-coverage.py` and `design-axis-coverage.py`, loaded by filename),
`check_technique_parity.py`, and 3 tests. Dependencies: playwright with chromium, Pillow,
node, the impeccable detector (lives in cole-gtm), the `claude` CLI for readers.

## Goals

- `seal` produces and reads verdicts itself. Round A refuses; round B reads OPEN; control C still refuses. Held by permanent negative-control tests.
- A round the readers rejected cannot be sealed or shown without a founder disposition naming that reader. Every reader run on the current page bytes counts, not the latest.
- Readers judge screenshots the gate took, and each row carries the HTML sha and the PNG sha.
- Receipts list the stages that ran. The passive gate reads that list: a receipt with no stage record is OPEN unless git history shows it was committed before the cutover date.
- `/design-chain` is the only door into design work for sites, brand assets, decks and motion. Other design skills stay installed as engines; a hook refuses them outside an active round, and `seal` requires an invocation record for every engine a technique names.
- One gate, one command, on main, reaching all 26 registered instances. Hook wiring ships LAST, after round A refuses on the branch.
- No issue in this PRD carries the full suite; `issue-check-budget.py` (commit `c7ca5bdb`) holds that at split, issue-start and issue-verify.

## Non-goals

- No model call inside `seal`. The reader gate runs as its own step; `seal` verifies its rows.
- No seal ledger. Dropped after review findings 11 and 12: it moved the forged-receipt hole and broke on every fresh clone and worktree.
- No free-form shell in `design-chain.json`. Checks are a closed registry in the gate's code.
- No deletion of third-party skills and no rewrite of their content. They become engines.
- No merge of the other 130 commits on `fix/candidate-draft-one-definition`.
- Lane-specific MEASURING tools for brand assets, decks and video are out of this PRD. Those lanes get the door, the vision, brief, directions, critique, dispositions, engine records, readers on rendered output, and the seal. `design-standard-check.py` and `design-gap-check.py` measure web pages only. Stated here so it is a named boundary and not a quiet one.

## Proposed approach

Single-instance layout:

| Piece | One home | Reaches instances by |
|---|---|---|
| Gate, producers, reader gate, tests | `q-system/.q-system/scripts/design-*.py` | the updater's rsync of `q-system/` |
| Command | `plugins/kipi-core/commands/design-chain.md` only | marketplace clone plus kipi-core version bump |
| Engine registry | `q-system/.q-system/scripts/design-engines.json`: skill name, lane, stage | same rsync |
| Hook wiring | `settings-template.json` and `.claude/settings.json`, held equal by `settings-template-sync-check.py` | `kipi-settings-merge.py` on every sync |
| Per-site config | `<instance>/design-chain.json` | instance-owned, not synced |

How each review blocker is closed:

- **Old receipts (finding-1, 13, 14).** `sealed_and_unedited()` accepts a receipt only when it carries a `stages` record, or when `git log` shows `receipts.json` committed before the cutover date. Git history is the one thing on disk the builder does not author in the moment. The stage record has a consumer: the passive gate and `status` print it.
- **Serving (finding-3, 17).** `seal` binds a server on an ephemeral port for the round, passes the URL to every producer, and stops it. Producers compare the sha of the SERVED bytes to the local file, so a stale server cannot lend its page.
- **Impeccable (finding-4).** `design-impeccable-check.py` returns a distinct failing code when any page raises an anti-pattern.
- **Screenshots (finding-5).** `design-reader-gate.py` shoots the served page itself at the declared viewports and records both shas per row. Builder-authored shoot scripts stop feeding readers and the ink axes.
- **Citations (finding-6).** A PostToolUse hook on the write of `craft-manifest.json` or `proof.md` has `transcript_path`. It checks each cited repo file was opened this session, reusing `opened()` from `read-first-gate.py`, and writes `citations.json` keyed to the manifest sha. `seal` requires that record to cover the current manifest.
- **Re-rolls (finding-7).** Reader runs append to `gate/reader-runs.jsonl`. `seal` reads every run whose page sha is current.
- **Persona (finding-8).** The persona comes from a file listed under `owners`, and its sha rides on every row. A changed persona voids earlier runs.
- **Checks (finding-9).** A closed registry in the gate (voice-lint, tripwire, bio_gate when the instance has one). Config turns names on and passes paths. Pass criteria live in code.
- **Ordering (finding-10).** Files carry first with no hook wiring. Behavior issues next. The wiring issue is last and its check is round A refusing.
- **Cost (finding-15, 16).** The post-Bash scan walks only roots that hold a `design-chain.json`. Each producer has a timeout, and `seal` prints per-stage duration.

One door:

- A PreToolUse hook on the `Skill` tool reads `design-engines.json`. A listed engine is refused unless a design-chain round is active for this session (the same session ledger the gate already keeps). The refusal names `/design-chain`.
- A PostToolUse hook on `Skill` appends `{skill, session, at}` to the active round's `engines.jsonl`. A technique in `craft-manifest.json` that names an `engine` must have a matching record, or `seal` refuses. This is the check the copied-animation incident lacked.
- Our own design skills get `user-invocable: false` so the menu shows one design command.
- `/design-chain` takes a lane: `site` (default), `brand`, `deck`, `motion`. The registry maps each lane to its engines and the stage that calls them.
- The rule files `design-auto-invoke.md` and `dogfood-gate.md` are rewritten to name the hook script `design-engine-door.py` as what routes design work, with the test `test_design_engine_door.py` as the receipt.

## Alternatives considered

- **Land the whole old branch first.** Rejected: 133 ahead and 53 behind with conflict history. Founder chose the clean branch.
- **Call the reader model inside the script `design-chain-gate.py seal`.** Rejected: each run of that script would cost model calls and answer differently on re-run. The script `design-reader-gate.py` runs readers; `seal` verifies its rows.
- **A hash-chained ledger file written by the script `design-chain-gate.py`.** Rejected after review: empty on every fresh clone and worktree, and writable by the agent. The git-history check in `sealed_and_unedited()` replaces it, pinned by the round B test.
- **Delete our design skills and disable third-party ones.** Rejected by the founder 2026-09-18 in favour of one door with engines: nothing is lost and third-party updates keep arriving.
- **Retire slash commands only.** Rejected: skills would still auto-invoke outside the chain, which is the drift.
- **Free-form `checks[]` commands in config.** Rejected after review: the builder would declare both the command and its passing exit code. The closed registry lives in the script `design-chain-gate.py`, pinned by a test.
- **Force the full suite on issues touching fleet-wide files.** Rejected by the founder: CI runs `verify.sh --full` once per PR.

## Scenarios

Every outcome below is an exit code of the script `design-chain-gate.py` (its `seal` and `status-page` subcommands and its hooks wired in `settings-template.json`), of the script `design-reader-gate.py`, or of the new hook script `design-engine-door.py`, each pinned by a test.

- **A rejected round.** Two of three readers answer LEAVE on the current page sha. `design-chain-gate.py seal` exits 2 naming both reader ids; the PreToolUse hook exits 2 on SendUserFile. Re-running the readers appends; the two LEAVE rows still count until a founder disposition names them.
- **A forged receipt.** A `receipts.json` typed by hand. It has no `stages` record and no commit before the cutover, so `status-page` exits 2 with OPEN. Test: round B.
- **A stale server.** A server from an earlier round is still up. `seal` uses its own ephemeral port, and the script `design-standard-check.py` exits 2 when served bytes and local bytes differ.
- **A design skill called directly.** `Skill(frontend-design)` with no active round: the hook script `design-engine-door.py` exits 2 and names `/design-chain`. Inside a round at the build stage it exits 0 and the call is recorded.
- **An imitated technique.** The manifest names engine `hyperframes-animation`; `engines.jsonl` has no such record. `seal` exits 2.
- **A deck.** `/design-chain askconsulting --lane deck`: vision, brief, three directions, `deck-ai` as the recorded engine, readers on the rendered slides, seal. The web-only measuring scripts do not run, and the receipt's stage list says so.
- **An instance with no site.** No `design-chain.json`: gate hooks exit 0 silently. The door hook still routes design skills to `/design-chain`.

## Resolved decisions

- **Landing path.** Clean branch off origin/main (`feat/design-chain-on-main`). Founder, 2026-09-18.
- **Stale PRD.** `prd-morning-board-consulting-not-builds-2026-09-03` archived as abandoned. Founder, 2026-09-18.
- **Check budget.** No issue spec carries the full suite. Founder chose option 1. Commit `c7ca5bdb`.
- **Review changes.** All six blockers accepted with the fixes above. Founder: "Yes, make the changes."
- **One door.** `/design-chain` is the single design command; other skills stay as engines; scope is sites, brand assets, decks, motion and video. Founder, 2026-09-18.
- **Reviewer.** Codex was out of credits on two logins this session; the review ran as `claude-adversarial` and is stamped that way. A Codex pass is added when credits return.

## Risks and rollback

- The door hook fires on every `Skill` call fleet-wide. It reads one small JSON and exits 0 for any skill not in the registry. A broken registry file must fail OPEN for non-design skills and closed for listed ones; both are tests.
- Blocking a design skill outside a round will surprise a session that used to call it directly. The refusal text names the command to run.
- Hiding our skills from the menu changes what 26 instances see after the next sync.
- A stricter `seal` must not be red on its own population: receipts committed before the cutover stay honored.
- Producers need playwright, Pillow, node and the detector. `seal` refuses only for stages the instance declared.
- The fleet sync is a destructive-class operation and is run by the founder.
- Rollback: revert the PRs on main. The settings merge is additive, so removed hook entries need a follow-up removal.

## Open questions

- What floor of readers answered is right below n=3 per page.
- Which third-party engines belong in the first registry beyond the ones named here.

<!--
## Persona Review (optional, fill in before /prd-review)

Phase 0 of the prd-os planning-personas experiment (PRD prd-planning-personas-2026-05-13).
For non-trivial PRDs, answer the three Skeptic questions below before invoking /prd-review.
Brief answers are fine. The goal is to force one round of adversarial thinking before Codex.

### Skeptic

Q1: What is the strongest argument against doing this?
A1:

Q2: What is the smallest experiment that would disprove the thesis?
A2:

Q3: What is the cheapest non-build alternative?
A3:

When done with these questions, uncomment this section and move it to live just before `## Issues` below.
-->

## Issues

<!--
After review and approval, populate the fenced JSON block below. The manifest is
read by TWO consumers and every entry must satisfy both:
  - `prd_split.py` materializes one issue spec per entry (needs `id`).
  - the approval gate proves every ACCEPTED finding is covered by an entry (needs
    `finding_id` + a `bypass_check`). One entry per accepted finding.

Required keys per entry (spine-native -- both consumers):
  - id (kebab-case, unique across the repo)            -- prd_split.py
  - finding_id (the accepted finding it covers, e.g. "finding-1") -- approval gate
  - title (non-empty string)
  - allowed_files (non-empty list of glob patterns)
  - required_checks (non-empty list, e.g. ["pytest -q"]). The stop-gate checks
    three receipts (verified, reviewed, findings_triaged); they are meaningless
    unless the spec documents what must be verified, so an empty list is rejected.
  - bypass_check (a command proving no bypass remains) OR
    bypass_exempt: "<reason>"                          -- spine contract

Write bypass_check as an INVARIANT, not a token count. Counting occurrences of
an identifier looks deterministic and is not: prose in a comment inflates it, a
refactor that renames or inlines deflates it, and neither fact says anything
about whether a bypass remains. Prefer "exactly one scan exists", "the byte
compare lives in one place", "the guard is still present" over
`grep -c <name> == N`. If a count really is the invariant, exclude comment lines
(`grep -v '^[[:space:]]*#' | grep -c`) and use `grep -F` for patterns holding
regex metacharacters such as `$`.

Scar 2026-07-26 (prd-updater-consolidation): three of five bypass_checks were
grep-count proxies and each needed a mid-issue amendment. One did real damage --
it demanded three calls to a function, so a redundant dead call was written
purely to satisfy the number, and adversarial review caught it. A check that
shapes the code to fit the check is worse than no check.

Optional keys:
  - priority (default p1)
  - disallowed_files, required_reviews, acceptance

Authoring a manifest with `id` but no `finding_id` (the pre-spine shape) is
rejected at approve. The template-vs-runner contract test enforces this list.
-->

```json
[
  {
    "id": "dc-01-carry-the-real-file-set",
    "finding_id": "finding-2",
    "title": "Carry the 12 design-chain files onto main with a dependency census taken by code",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/check_technique_parity.py",
      "q-system/.q-system/scripts/design-*.py",
      "q-system/.q-system/scripts/test/test_dc_dependency_census.py",
      "q-system/.q-system/scripts/test/test_design_chain_vision_stage.py",
      "q-system/.q-system/scripts/test_design_chain_gate.py",
      "q-system/.q-system/scripts/test_design_standard_check.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_dependency_census.py",
      "python3 q-system/.q-system/scripts/test_design_chain_gate.py",
      "python3 q-system/.q-system/scripts/test/test_design_chain_vision_stage.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_dependency_census.py",
    "acceptance": "All 8 design-*.py scripts, check_technique_parity.py and the 3 tests exist on the branch with NO hook wiring. test_dc_dependency_census.py follows static imports AND _load_sibling / spec_from_file_location loads, fails when a loaded sibling is absent, and pins the declared third-party set (playwright, Pillow). Mutation: delete design-ink-coverage.py, the census goes red."
  },
  {
    "id": "dc-02-seal-runs-the-producers",
    "finding_id": "finding-18",
    "title": "seal runs the standard and gap producers itself and uses their exit codes",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_seal_runs_producers.py",
    "acceptance": "seal invokes design-standard-check.py and design-gap-check.py (when craft.require_gap_check) and refuses on a nonzero exit; a standard.json or gap.json typed by hand with pass true does not seal. Exit 2 from a producer prints 'could not measure' and refuses."
  },
  {
    "id": "dc-03-seal-owns-the-served-round",
    "finding_id": "finding-3",
    "title": "seal serves the round on an ephemeral port and producers prove they measured the local bytes",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-gap-check.py",
      "q-system/.q-system/scripts/design-standard-check.py",
      "q-system/.q-system/scripts/test/test_dc_served_round.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_served_round.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_served_round.py",
    "acceptance": "seal binds port 0, passes the URL to every producer, and stops the server in a finally. Producers compare the sha of the served bytes with the local file and exit 2 on a mismatch. Test: a decoy server serving different bytes cannot produce a pass. No literal port remains in the gate or the producers."
  },
  {
    "id": "dc-04-impeccable-exit-says-what-the-pages-did",
    "finding_id": "finding-4",
    "title": "design-impeccable-check.py fails when a page raises an anti-pattern",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-impeccable-check.py",
      "q-system/.q-system/scripts/test/test_dc_impeccable_exit.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_impeccable_exit.py",
    "acceptance": "Exit contract: 0 control fired and pages clean; 1 control did not fire; 2 could not run; 3 at least one page flagged. The value computed at worst = max(worst, rc) is consumed. seal refuses on 1, 2 and 3. Test drives the script with a stub detector."
  },
  {
    "id": "dc-05-seal-has-a-time-budget",
    "finding_id": "finding-16",
    "title": "Each producer run has a timeout and seal prints per-stage duration",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_seal_budget.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_seal_budget.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_seal_budget.py",
    "acceptance": "Every producer subprocess carries a timeout read from config with a coded default; a timeout is a refusal naming the stage. seal prints one duration line per stage. Test uses a sleeping stub producer."
  },
  {
    "id": "dc-06-reader-gate-takes-its-own-screenshots",
    "finding_id": "finding-5",
    "title": "design-reader-gate.py lives in the skeleton, shoots the served page itself, and rows carry the HTML and PNG shas",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-reader-gate.py",
      "q-system/.q-system/scripts/test/test_dc_reader_gate.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_reader_gate.py",
    "acceptance": "New script in the skeleton. It renders each page at the configured viewports with playwright, hashes the PNG, and writes html_sha256 and png_sha256 into every row plus a _provenance block (model, persona sha, at). It never reads a PNG the round supplied. The model call is injectable so the test never spends one (PYTEST_CURRENT_TEST and an explicit runner argument)."
  },
  {
    "id": "dc-07-reader-verdicts-are-read",
    "finding_id": "finding-19",
    "title": "Reader rows carry a forced-choice verdict and seal refuses on LEAVE without a founder disposition",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-reader-gate.py",
      "q-system/.q-system/scripts/test/test_dc_reader_verdicts.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_reader_verdicts.py",
    "acceptance": "Each row has verdict in {STAY, LEAVE} and a what_he_sells label parsed from a forced-choice final question; an unparseable answer counts as not answered. seal applies a floor (answered out of attempted, from config) and refuses on any LEAVE or a label in the narrow list unless '- reader <id>: FOUNDER <reason>' exists. Negative control: RCA round A refuses naming the readers."
  },
  {
    "id": "dc-08-reader-runs-append",
    "finding_id": "finding-7",
    "title": "Reader runs append to one file and every run on the current page bytes counts",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-reader-gate.py",
      "q-system/.q-system/scripts/test/test_dc_reader_runs.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_reader_runs.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_reader_runs.py",
    "acceptance": "design-reader-gate.py opens gate/reader-runs.jsonl in append mode only. seal reads every row whose html_sha256 matches the current page, so a later all-STAY run does not erase an earlier LEAVE. Test: run LEAVE then STAY, seal still refuses."
  },
  {
    "id": "dc-09-reader-persona-comes-from-an-owner",
    "finding_id": "finding-8",
    "title": "The reader persona is read from an owners file and its sha rides on every row",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-reader-gate.py",
      "q-system/.q-system/scripts/test/test_dc_reader_persona.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_reader_persona.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_reader_persona.py",
    "acceptance": "design-chain.json names readers.persona_file, which must be one of the files under owners; anything else is refused. Rows carry persona_sha256 and seal ignores rows whose persona sha differs from the live file."
  },
  {
    "id": "dc-10-receipts-say-what-ran",
    "finding_id": "finding-1",
    "title": "Receipts record the stages that ran, and the passive gate honors a bare receipt only when git shows it predates the cutover",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_receipts.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_receipts.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_receipts.py",
    "acceptance": "seal writes a stages list per page (floor, vision, craft, gap, impeccable, readers, checks, engines) with each producer's output sha. sealed_and_unedited() accepts a receipt with a stages record, or one whose receipts.json has a git commit dated before the coded cutover; status and the hook block message print the stages. Negative control: RCA round B (hand-typed receipt, uncommitted) reads OPEN. Population check: every sealed round committed before the cutover still reads COMPLETE."
  },
  {
    "id": "dc-11-checks-are-a-closed-registry",
    "finding_id": "finding-9",
    "title": "Outside checks run from a closed registry in the gate, and the tripwire says when it skipped",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-design/.claude-plugin/plugin.json",
      "plugins/kipi-design/hooks/dogfood_gate.py",
      "plugins/kipi-design/hooks/test_dogfood_gate.py",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_check_registry.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_check_registry.py",
      "python3 plugins/kipi-design/hooks/test_dogfood_gate.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_check_registry.py",
    "acceptance": "design-chain.json lists check NAMES with path arguments; commands and pass criteria live in the gate. An unknown name is refused. seal runs each and reads the exit code; checks/ being non-empty no longer counts. dogfood_gate.py gains a distinguishable result for 'skipped as internal' (ASK-1746) that the registry treats as not run."
  },
  {
    "id": "dc-12-citations-are-checked-where-the-transcript-is",
    "finding_id": "finding-6",
    "title": "A hook verifies cited repo files were opened this session and seal requires that record",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_citations.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_citations.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_citations.py",
    "acceptance": "The PostToolUse branch on a write of craft-manifest.json or proof.md imports opened() from read-first-gate.py, checks every repo path in reference fields, and writes citations.json keyed to the manifest sha with the session id. No transcript means no record, never a pass. seal refuses when the record is missing or stale. Test feeds a fixture transcript."
  },
  {
    "id": "dc-13-proof-has-a-shape",
    "finding_id": "finding-24",
    "title": "proof.md is parsed against a minimal schema",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_proof_schema.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_proof_schema.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_proof_schema.py",
    "acceptance": "Each artifact block names a proof kind from the closed list (problem, capability, reliability, outcome, pedigree) and a record id that resolves in the index file the config names. A one-character proof.md refuses."
  },
  {
    "id": "dc-14-founder-findings-close",
    "finding_id": "finding-20",
    "title": "A FOUNDER-FINDING[tag] line needs a disposition before seal",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_founder_findings.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_founder_findings.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_founder_findings.py",
    "acceptance": "Reuses WEAK_RE and DISPOSITION_RE machinery. An undisposed FOUNDER-FINDING[tag] in any round file refuses the seal."
  },
  {
    "id": "dc-15-exemplars-fail-loudly",
    "finding_id": "finding-21",
    "title": "A malformed exemplars.json refuses, and exemplar citation has a floor",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_exemplars.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_exemplars.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_exemplars.py",
    "acceptance": "The except ValueError: named = [] branch becomes a refusal. directions.md must cite at least the configured floor of exemplars (default: all of them up to 3)."
  },
  {
    "id": "dc-16-decoration-is-measured-then-removed",
    "finding_id": "finding-22",
    "title": "The critique line count and byte-copy brief checks are measured, then deleted or re-bound",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-core/commands/design-chain.md",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_decoration.py",
      "q-system/.q-system/scripts/test_design_chain_gate.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_decoration.py",
      "python3 q-system/.q-system/scripts/test_design_chain_gate.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_decoration.py",
    "acceptance": "First a script counts, across the sealed rounds on disk, what each check would have caught. Then each is deleted with its docs, or re-bound to an input the builder did not write. A test asserts the removed names stay gone."
  },
  {
    "id": "dc-17-scan-only-design-roots",
    "finding_id": "finding-15",
    "title": "The post-Bash scan walks only roots that hold a design-chain.json",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/test/test_dc_scan_scope.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_scan_scope.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_scan_scope.py",
    "acceptance": "scan_roots() drops any registered instance root with no design-chain.json and prunes nested worktrees (.wt-*, .claude/worktrees). Test builds a fake registry with one design root and one large non-design root and asserts the second is never walked."
  },
  {
    "id": "dc-18-one-door",
    "finding_id": "finding-25",
    "title": "design-engine-door.py refuses a design engine outside an active round",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-engine-door.py",
      "q-system/.q-system/scripts/design-engines.json",
      "q-system/.q-system/scripts/test/test_design_engine_door.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_design_engine_door.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_design_engine_door.py",
    "acceptance": "PreToolUse on the Skill tool. Reads design-engines.json (skill, lane, stage). A listed skill with no active round for the session exits 2 naming /design-chain; an unlisted skill exits 0; an unreadable registry exits 0 for unlisted names and 2 for the coded core list. Under 50 ms on the no-match path, asserted."
  },
  {
    "id": "dc-19-engines-leave-a-record",
    "finding_id": "finding-26",
    "title": "Engine invocations are recorded and seal requires one for every engine a technique names",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-engine-door.py",
      "q-system/.q-system/scripts/test/test_dc_engine_records.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_engine_records.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_engine_records.py",
    "acceptance": "PostToolUse on Skill appends {skill, session, at} to the active round's engines.jsonl. A technique with an engine field and no matching record refuses the seal. Test: the copied-animation case."
  },
  {
    "id": "dc-20-lanes",
    "finding_id": "finding-27",
    "title": "/design-chain takes a lane and the receipt says which stages a lane does not run",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-core/commands/design-chain.md",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-gate.py",
      "q-system/.q-system/scripts/design-engines.json",
      "q-system/.q-system/scripts/test/test_dc_lanes.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_lanes.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_lanes.py",
    "acceptance": "craft-manifest.json declares lane in {site, brand, deck, motion}; default site. Non-site lanes skip the web-only measuring stages and the stages list records them as 'not applicable: lane', never as passed. Readers run on the rendered output the reader gate shoots or is handed by the lane's engine record."
  },
  {
    "id": "dc-21-fixtures-come-from-producers",
    "finding_id": "finding-23",
    "title": "Test fixtures carry provenance and the negative controls are permanent",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/test/dc_fixtures.py",
      "q-system/.q-system/scripts/test/fixtures/design-chain/*",
      "q-system/.q-system/scripts/test/test_dc_negative_controls.py",
      "q-system/.q-system/scripts/test_design_chain_gate.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py",
      "python3 q-system/.q-system/scripts/test_design_chain_gate.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py",
    "acceptance": "dc_fixtures.load() refuses a fixture with no _provenance block (producer, command, captured_at). The ten hand-typed verdict lines are replaced. Rounds A, B, C and the bland control are tests that must never seal (A, B, bland) or must refuse (C)."
  },
  {
    "id": "dc-22-one-design-command-in-the-menu",
    "finding_id": "finding-28",
    "title": "Our design skills leave the menu and the design rules name the door",
    "priority": "p1",
    "allowed_files": [
      ".claude/rules/design-auto-invoke.md",
      ".claude/rules/dogfood-gate.md",
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-core/skills/deck-ai/SKILL.md",
      "plugins/kipi-design/.claude-plugin/plugin.json",
      "plugins/kipi-design/skills/*/SKILL.md",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/test/test_dc_one_door_menu.py",
      "q-system/output/claude-proposals/*.json"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_one_door_menu.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_one_door_menu.py",
    "acceptance": "The four in-repo design skills carry user-invocable: false. Both rule files name design-engine-door.py and test_design_engine_door.py (edited through apply-claude-changes.sh). The test reads every SKILL.md the registry lists as ours and fails if one is user-invocable, and fails if a design skill exists in the plugins tree that the registry does not list."
  },
  {
    "id": "dc-23-docs-match-the-code",
    "finding_id": "finding-29",
    "title": "The command doc matches the code and every RCA box is closed or voided",
    "priority": "p1",
    "allowed_files": [
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-core/commands/design-chain.md",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/test/test_dc_command_doc.py"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_command_doc.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_command_doc.py",
    "acceptance": "test_dc_command_doc.py asserts every script path the command names exists, every stage the gate's stages list knows appears in the doc, and the doc has no step whose only holder is prose. The three RCAs' boxes are closed or voided against the code in the closeout note."
  },
  {
    "id": "dc-24-wiring-ships-last",
    "finding_id": "finding-10",
    "title": "Hook entries and the plugin command ship only after round A refuses",
    "priority": "p2",
    "allowed_files": [
      ".claude/settings.json",
      "plugins/kipi-core/.claude-plugin/plugin.json",
      "plugins/kipi-core/commands/design-chain.md",
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/settings-template-sync-check.py",
      "q-system/.q-system/scripts/test/test_dc_negative_controls.py",
      "q-system/.q-system/scripts/test/test_dc_wiring.py",
      "q-system/output/claude-proposals/*.json",
      "settings-template.json"
    ],
    "required_checks": [
      "python3 q-system/.q-system/scripts/test/test_dc_wiring.py",
      "python3 q-system/.q-system/scripts/test/test_dc_negative_controls.py",
      "python3 q-system/.q-system/scripts/settings-template-sync-check.py"
    ],
    "bypass_check": "python3 q-system/.q-system/scripts/test/test_dc_wiring.py",
    "acceptance": "Adds the gate's three hook entries and the door's two to settings-template.json and .claude/settings.json (the latter through apply-claude-changes.sh). test_dc_wiring.py runs each wired command the way the harness does (stdin JSON, CLAUDE_PROJECT_DIR set) and asserts the exit codes, and asserts no .claude/commands/design-chain.md exists. Depends on every other issue being closed."
  },
  {
    "id": "dc-25-rollout-proof",
    "finding_id": "finding-30",
    "title": "A script proves the fleet load path end to end",
    "priority": "p2",
    "allowed_files": [
      "q-system/.q-system/capability/expected_tests/*",
      "q-system/.q-system/scripts/design-chain-rollout-proof.sh"
    ],
    "required_checks": [
      "bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest"
    ],
    "bypass_check": "bash q-system/.q-system/scripts/design-chain-rollout-proof.sh --selftest",
    "acceptance": "The script checks: the marketplace clone holds the command; an instance root passed as an argument holds all design scripts and the hook entries; the gate hook run with CLAUDE_PROJECT_DIR set to that instance exits 2 on an unsealed page. --selftest runs it against a temp instance. The founder runs the fleet sync; this script is run against consulting afterwards and its output is pasted in the closeout."
  }
]
```
