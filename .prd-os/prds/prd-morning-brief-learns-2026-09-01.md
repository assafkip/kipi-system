---
id: prd-morning-brief-learns-2026-09-01
title: Morning brief learns (Phase 2 of the morning-brief overhaul)
status: archived
created_at: 2026-09-01T21:37:44Z
updated_at: 2026-09-02T04:11:09Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-morning-brief-learns-2026-09-01-findings.jsonl
codex_reviewed_at: 2026-09-01T21:43:33Z
reviewed_by: codex-adversarial
---

# Morning brief learns (Phase 2 of the morning-brief overhaul)

Source plan: `q-system/output/plans/morning-brief-overhaul-2026-08-30.md`, Phase 2
and its three amendments (items 2a-2m). Founder-approved execution plan
2026-09-01 (`~/.claude/plans/sorted-questing-pond.md`). Deconflicted the same
day with the voice-loop session and the consulting email session; both replied
NO CONFLICT on every item and added six constraints, all carried below.

Codex adversarial review 2026-09-01: 18 findings (2 blockers, 13 majors, 3
minors). 15 accepted, each with its own manifest entry below; finding-10
rejected as invalid (install-plist.sh resolves templates by label, line 70);
finding-14 and finding-15 folded into finding-2's single brief-core entry.
The approach and rollback sections were rewritten to match.

## Problem

Phase 1 shipped a brief that REPORTS (commit `3abbe15a`, 07:00 Slack message,
09:00 deadman). It gets better only when the founder notices something and says
so. Measured 2026-09-01 in this repo:

- `q-system/.q-system/scripts/route-overrides-to-learn.py` (the draft-vs-sent
  learning stage) has **no registered trigger** (grep over
  `~/Library/LaunchAgents/*.plist`, `.claude/settings.json`, every
  `plugins/*/hooks.json` and every `*.sh`: zero hits), **no test** (`git ls-files
  | grep route` returns only the script), and its input table `copy_edits` in
  `q-system/.q-system/data/metrics.db` holds **0 rows** (file mtime 2026-04-03).
  Its producer is `01c-copy-diff.md`, an agent of the retired 9-phase pipeline.
  Output dir `q-system/output/skill-proposals/_inbox/` holds `.gitkeep` only.
- There is **no friction artifact**: grep for "friction" across scripts and
  plugins finds prose inside SKILL.md bodies and no ledger, collector or
  consumer. Per the lesson `feedback-lands-where-artifacts-exist`, a concern
  with no file cannot absorb a fix; the ~40 lint/guard scripts in this repo are
  the displacement evidence.
- **No context-gap detector.** Nothing scans incoming mail or calendar for terms
  the system does not know.
- **No external-idea intake.** `lessons-inject.py` and `lessons-distill.py` are
  internal-corpus only; the comparison that produced this PRD was hand-rolled
  from a pasted transcript with six ad-hoc greps.
- **"Owed today" is 72 rows.** `collect_owed()` (`morning-brief.py:235-324`)
  renders every open Linear issue assigned to the founder plus every
  `needs_founder` loop, capped only by `MAX_ROWS = 15` at render time with an
  `...and N more` tail that does not distinguish lead from tail. Phase 1's own
  closeout called it "honest and not yet useful".
- **`collect_all()` (`morning-brief.py:441`) has no per-section isolation.**
  Each collector catches inside itself; a new collector that raises aborts the
  whole run. Every addition below therefore needs a call-site boundary first.
- **The founder liked Bloom's Notion morning board** (three buckets, an agent
  narrows into it, he reads only that). The plan excluded a board with no
  reason recorded; founder reversed that 2026-09-01 (item 2m). No Notion
  writer exists in kipi-system (only `harvest_store.queue_notion_write`, drained
  by an MCP session); no Notion token exists under `~/.config/kipi/`.
- **The autonomy contract was broken in at least four consecutive turns** in
  the session that wrote the plan (a pick named, then a menu). The contract
  forbids fixing that with more phrase patches; the honest move is a
  measurement.

## Goals

- Section 3 of the brief shows at most three owed items plus an explicit count
  of what it withheld, split by source from provenance-tagged rows. A
  truncation that hides its own truncation fails.
- Every collector runs behind a call-site boundary: one raising collector costs
  its own section only, rendered as a safe `COULD NOT READ` line (collector
  name and exception type; the message body goes to the local log), never the
  brief.
- Optional sections (unknown terms, board) register through one list in
  `morning-brief.py` and live in their own modules, so no later issue edits
  the core file.
- An unknown-term detector rides the brief's already-pulled mail and calendar
  and names terms absent from `q-system/canonical/`, with normalization and
  allowlists so the five slots are not filled by sentence starts and attendee
  names.
- A Notion morning board (top of mind / this week / inbox) is rewritten during
  the 07:00 run, BEFORE the Slack send, inside a 20-second budget; its status
  (written / COULD NOT READ / timed out) is a line in the brief; items carry a
  stable id and an item the founder moved to another bucket is not re-added;
  a live read-back check exists and closeout requires it to have run.
- The draft-vs-sent learning stage gets a producer that pairs by Gmail draft id,
  stores only a diff projection (no raw bodies, hashed recipients, 90-day
  purge), a runner that triggers producer then learner then weekly pass in
  order, a registered weekly plist, and a first-run check that fails on an
  empty proposal.
- A friction artifact exists; a weekly pass reads it and proposes fixes via
  `slack_founder.deliver`, citing a line id and a masked excerpt, never a
  verbatim line.
- The product/roadmap boundary is ONE deterministic classifier module used by
  every consumer (friction writer, weekly pass, improve skill), fail-closed on
  missing or unknown scope, and proven against a paraphrase suite, not one
  phrase.
- An `improve` skill critiques an outside idea against a declared list of
  corpora (env-driven, missing corpora reported, no sibling path hardcoded)
  and returns skip on anything the classifier calls roadmap.
- Two advisory measurements exist: a permission-ask counter with a ledger, and
  a decision-corpus cost with a stated formula. Neither is a hook; neither
  prints a number when its apparatus is broken.
- Every new job or writer has an explicit off-switch and a test proving the
  off state is a no-op, so rollback is a documented switch per issue, not
  "delete the files".

## Non-goals

- Deciding what to build, sell, publish, or what a client should do. **Hard
  constraint:** every loop here may propose a fix to a stage, a skill for
  manual work, a rule/lint/prompt change, or a context entry. Nothing here
  proposes product. `roadmap_scope.py` enforces this in code for every
  consumer (issues 2 and 3).
- Widening the voice-dna-loader trigger to every turn. This PRD MEASURES the
  cost (issue 14); the widening is a follow-up decision.
- Rebuilding the 9-phase pipeline, changing Phase 1's four sections, or the
  retired-webhook fix for `daily-linear-digest.py`.
- Item 2f (the second half of consulting's `sales_rules/pulse.py`): every file it
  touches is in `~/projects/consulting`, so it is captured in that lane with the
  two constraints the consulting session gave (every `cmd_*` that PATCHes an
  email DB takes `--owner` and calls `assert_may_mutate` first; no second writer
  of DB1/DB3 rows). Not built here.
- Item 2g (recorded walkthrough as approval artifact): its own PRD later. A
  review-lane change, not a brief change.
- Item 2j (council beside the deliverable): already true by
  `bookkeeping-must-never-gate-the-deliverable`; one decisions.md line, no code.
- The browser record lane. Its parking condition is met (email-watch retired
  2026-09-01, mail-sweep owns discovery). Founder-parked; untouched here.
- Merging consulting's two `open-loops.json` files into the brief. The brief
  reads kipi's `q-system/memory/open-loops.json` only.
- Editing any existing SKILL.md for the changelog convention. The convention
  applies to skills this PRD creates and is documented once; existing skills
  adopt it when they are next edited for their own reasons.
- Writing to any of these, which have single writers in other lanes:
  `q-consult/voice/exemplars.jsonl` (`q-consult/pipeline/voice.py` is THE
  writer; 2k writes `copy_edits` in `metrics.db` only),
  `q-consult/voice/corrections.jsonl`, `q-consult/output/content-route-receipts.jsonl`,
  `q-consult/output/sweep/*` and `held-digest.json`, the consulting Notion email
  DBs (Client Email Log, Email Watch Senders, Client Pulse), consulting's Slack
  poster, the GTM queue, the Run Control heartbeats.
- Importing `q-consult/pipeline/route_classifier.py` from anything here (voice-loop
  constraint: the loader is broad and advisory, the classifier is narrow and
  blocking; PRD R8b withdrew shared vocabulary for this reason).
- Touching `q-system/.q-system/scripts/voice-stop-gate.py` in either repo (a
  staged rewrite in the kipi main checkout and consulting issue ASK-1193 both
  name it).

## Proposed approach

The load-bearing decision, carried from the plan: **these are separately
triggered stages, not steps inside `morning-brief.py`**
(`every-stage-needs-its-own-trigger`). Only the unknown-term detector and the
board ride the brief, because they are properties of today's incoming material
and need its authenticated pull; each is its own module, registered once.

**One owner of `morning-brief.py` (finding-2).** Issue 1 is the only entry that
touches `morning-brief.py` and `test_morning_brief.py`. It ships three things
at once because they are one change to `collect_all()` and `collect_owed()`:
the three-item lead tier over provenance-tagged rows, the `_guarded()` call-site
boundary with a safe error string, and an `OPTIONAL_SECTIONS` registry: a list
of `(module_stem, key, title)`; a module that imports gets a guarded collector,
a module that is absent renders no section and writes one log line (absent is
not "nothing"). Later issues add modules, never edit the core.

**Board timing (finding-4).** The board is an optional section. Its `collect()`
runs where every other collector runs, BEFORE the Slack send, inside a 20-second
budget enforced by the guard. Its result is a row in the brief: `board: written,
read-back ok` / `COULD NOT READ: board timed out (20s)` / `COULD NOT READ: notion
board failed (HTTPError)`. The brief is therefore delayed by at most 20 seconds,
never blocked, and the founder sees the board state in the same message. The
earlier "after Slack answered" wording was impossible and is withdrawn.

**Board identity (finding-5).** Each item line carries its stable id (`ASK-123`
or the loop id) as a suffix. Before writing, the writer reads the page; any id
already present outside top-of-mind is excluded from the rewrite, so a
hand-moved item stays moved. Only the top-of-mind block is ever rewritten.

**Board live proof (finding-6).** `notion_board.py --live-check` writes a
sentinel line, reads it back, deletes it, and exits non-zero on any mismatch or
on a missing token. It is that issue's `bypass_check`, so the issue cannot close
without a real read-back. It stays open until the founder places the token.

**Draft-vs-sent (findings 7, 8, 9).** Pairing is by Gmail identity: a draft's
message id survives sending, so `draft-vs-sent.py` lists recent drafts recorded
in `q-system/output/drafts-ledger.jsonl` (the brief and `/q-create` append an
entry when they write a draft) and looks each up by id in sent mail through the
same `run_claude` seam the brief uses. Unmatched drafts are skipped and counted.
Stored projection: a unified diff of the two bodies, recipient addresses
replaced by a salted hash, no subject, no headers; `--purge` deletes rows older
than 90 days. Trigger: `weekly-improve.sh` runs producer, then
`route-overrides-to-learn.py`, then `weekly-improve.py`, logging each step's
exit code; `com.kipi.weekly-improve.plist` (Monday 06:30) runs that script.

**Roadmap boundary (findings 1, 12).** `roadmap_scope.py` is one deterministic
module: `classify(text, declared_target) -> {"verdict": system|roadmap|unknown,
"matched": [...]}`, pattern lists for product / pricing / publish / client-advice
in code, unknown when neither the text nor the target resolves. Every consumer
refuses on `roadmap` AND on `unknown` (fail-closed). A fixture file holds at
least 12 roadmap paraphrases and at least 6 legitimate system proposals; the
suite runs the SAME fixtures through every consumer.

**Unknown terms (finding-13).** Normalization before the diff: drop sentence-
initial capitalized words unless they recur mid-sentence, drop signature blocks
(lines after `--` or `Sent from`), drop calendar attendee names and email local
parts, drop a stopword list, drop anything present anywhere in
`q-system/canonical/`. Precision fixture: 5 planted unknowns and 10 planted
decoys; at least 4 of 5 surface and 0 decoys.

**Corpora contract (finding-11).** `improve_ground.py` reads
`KIPI_LESSONS_CORPORA` (colon-separated directories; default: this instance's
own `q-system/lessons`). Each corpus is reported as read / missing / unreadable
in the verdict; nothing hardcodes a sibling checkout. This is also the seam
PRD B's item 3d uses for `lessons_recall.py --both`.

**Friction redaction (finding-18).** `friction-note.sh` assigns each line an id
and refuses a line containing an email address. The weekly proposal cites the
id and a 60-character excerpt with emails masked, never the whole line.

**Changelog convention (finding-3).** Documented once in
`plugins/kipi-core/skills/README.md`; a test asserts the `improve` skill (the one
this PRD creates) carries `## Changelog`. No wildcard over existing skills.

**Measurements (finding-16).** The cost script prints bytes and `tokens =
ceil(bytes / 4)` with the formula in its output, so two runs agree by
construction. The counter appends `{date, sample, count, rate}` to a ledger
and exits 3 when the sample dir is unreadable.

**Off-switches (finding-17).** `test_off_switches.py` proves each new piece is
a no-op in its off state: board section absent when the page-id file is
missing; weekly runner does nothing with `--dry-run` and no plist; friction
consumer renders "nothing this week" with no file; improve skill is on-demand
only. Rollback per issue is "flip the switch", then revert the branch.

## Alternatives considered

- **Fold everything into `morning-brief.py` as more steps.** Rejected: that is
  the exact shape of the dead stage this PRD revives (`route-overrides-to-learn.py`
  existed only inside another stage's procedure).
- **One PRD for Phases 2, 3 and 4.** Rejected: Phases 3 and 4 depend on a git
  decision that is Sana's (the skeleton is on a feature branch, so the fan-out
  aborts), and one active issue blocks another; a second PRD
  (`lessons-rail-and-up-rail`) follows this one.
- **Board via the MCP queue (`harvest_store.queue_notion_write`).** Rejected by
  the founder: the write would wait for an interactive session, so "rewritten
  at 07:00" is not met.
- **Board write after the Slack send.** Rejected (finding-4): its status could
  not appear in the message already sent. A bounded pre-send section is the
  only shape where the founder sees the board state.
- **Roadmap boundary as the friction author's declared target.** Rejected
  (finding-1): a product proposal labelled `target=rule` passes. The classifier
  reads the text too and fails closed.
- **A hook to stop permission asks.** Rejected by the autonomy contract itself
  ("hooks are the wrong layer for this"); a measurement is the honest move.

## Scenarios

- **Monday 07:00, healthy.** launchd starts `morning-brief.py`; the four
  sections plus unknown terms and the board section render; section 3 shows
  three items and `withheld 69 more: 64 in Linear, 5 in open-loops`; the board
  row reads `board: written, read-back ok`; Slack answers `ok`; receipt
  written; deadman stays quiet.
- **Board token missing.** Same run; the board collector raises inside the
  guard; the brief carries `COULD NOT READ: notion board failed (FileNotFoundError)`;
  `degraded` is True; Slack still lands within the 20-second budget; exit 1
  so `launchd-health` sees it.
- **Founder moved an item.** Yesterday's `ASK-402` was dragged to "this week".
  Today's run reads the page, sees `ASK-402` outside top-of-mind, and rewrites
  top-of-mind without it; the withheld count still includes it.
- **Friction line to weekly proposal.** Founder runs
  `friction-note.sh "the brief lists Sana's tickets as mine" --target rule`;
  the classifier returns `system`; Monday 06:30 `weekly-improve.sh` runs the
  producer, the learner, then the pass, which proposes a rule change citing
  `fr-2026-09-08-01: "the brief lists Sana's tickets as mine"` and delivers via
  `slack_founder.deliver`. A line reading "we should sell the brief as a
  product" with `--target rule` is refused at write time (classifier says
  roadmap) and again at read time.
- **Outside idea.** Founder pastes a post into `/improve`; `improve_ground.py`
  reports `corpora: q-system/lessons read (161), consulting missing`, cites
  `q-system/lessons/<hit>.md`, names `review-tier.py`; verdict: already built.

## Resolved decisions

- **Two PRDs, in sequence.** Decided: Phase 2 here; Phases 3+4 in
  `lessons-rail-and-up-rail` after this one is split and cleared. Rationale:
  one active PRD and one active issue at a time; 3+4 wait on Sana's git call.
- **2a and 2k are one lane, three issues.** Decided: pairing, projection, and
  runner+trigger are separate entries (finding-9) but ship in that order.
  Rationale: `copy_edits` has 0 rows; a trigger on an empty table passes
  vacuously; three independently failing units get three checks.
- **2m credential.** Decided by the founder 2026-09-01: a new kipi Notion
  integration token at `~/.config/kipi/notion-token`, page id at
  `~/.config/kipi/notion-board-page`. Rationale: the only path that satisfies
  "rewritten at 07:00" from launchd.
- **Single writer of `exemplars.jsonl` is `q-consult/pipeline/voice.py`.**
  Decided with the voice-loop session. 2k writes `copy_edits` only.
- **One owner of `morning-brief.py`.** Decided (finding-2): issue 1 only. Every
  later section is a registered module. Findings 14 and 15 are covered inside
  that entry's acceptance and were dispositioned as duplicates of finding-2.
- **This work runs in the worktree `~/projects/kipi-wt-prd-mbl` on branch
  `prd/morning-brief-learns`, based on `ddad93b1`.** Rationale: Phase 1
  (`morning-brief.py`) exists only on that line, not on `main` or
  `origin/main`; the main checkout carries another session's staged work.
  The base choice and the eventual merge are Sana's call and are recorded
  here, not decided by the founder.

## Risks and rollback

- **Fan-out blast radius.** New scripts under `q-system/.q-system/scripts/`
  reach 25 instances on the next `kipi update`. Each has an off-switch tested
  in `test_off_switches.py` (issue 15): the board needs a page-id file, the
  weekly runner needs an installed plist, the friction consumer needs a file,
  the improve skill is on-demand. Off is the shipped default on every instance
  but this one.
- **Rollback per issue** (finding-17): issue 1 revert the commit (Phase 1's
  brief is unchanged by every other issue); board: remove
  `~/.config/kipi/notion-board-page`, the section disappears; weekly runner:
  `launchctl bootout gui/$UID/com.kipi.weekly-improve`; friction:
  stop writing lines, the pass renders "nothing this week"; improve skill:
  remove its CLAUDE.md line; measurements: on-demand, nothing to roll back.
  `CLAUDE.md`, `plugins/kipi-core/skills/README.md`, tests and the plan file
  are reverted with the branch. There is no "delete the files" rollback.
- **Content tripwire.** `kipi-push-upstream.sh:26-34` refuses any file under
  `q-system/` naming the founder or `/Users/`. Every new file uses `__HOME__`
  / `Path.home()` and no founder name.
- **Second Notion writer in the fleet.** Partitioned by parent page and token;
  a test asserts `notion_board.py` never reads `NOTION_TOKEN_ASK` and never
  names an ASK page id.
- **Unknown-term detector on real mail.** Read-only; the risk is noise, bounded
  by the precision fixture and the five-term cap.
- **Draft bodies are personal mail.** Only a diff projection is stored, no
  recipients in clear, purged at 90 days (finding-8).

## Open questions

- The transcript sample source for the permission-ask counter: the local
  `~/.claude/projects/*/` JSONL is the obvious input. It sits under `.claude/`,
  where `claude-path-write-guard.py` (PreToolUse, ASK-282) blocks writes and
  not reads, so the counter can read it. Verified at issue time by running
  the counter over it.

## Persona Review

### Skeptic

Q1: What is the strongest argument against doing this?
A1: That self-improvement loops are theatre (Carson: "kind of a joke" with
product). Answer: every loop here is scoped to fixing the system, the roadmap
boundary is one coded classifier with a paraphrase suite (issues 2 and 3), and
the two measurements (issue 14) are advisory by construction.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run `weekly-improve.sh` for four Mondays. If zero friction lines are ever
written, the artifact did not absorb anything and the displacement diagnosis
was wrong. That number is visible in `friction.jsonl` line count.

Q3: What is the cheapest non-build alternative?
A3: Keep writing friction into lessons by hand via `lesson-note.sh`. Rejected
because a lesson is HOW-only and fleet-wide, and friction is a local
annoyance with a target; the two have different consumers.

## Issues

```json
[
  {
    "id": "mbl-brief-core",
    "title": "One owner of morning-brief.py: three-item lead tier, guarded collectors, optional-section registry",
    "finding_id": "finding-2",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/morning-brief.py",
      "q-system/.q-system/tests/test_morning_brief.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_morning_brief.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-system/.q-system/scripts/voice-stop-gate.py", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py -k 'withheld or isolation or registry'",
    "acceptance": "The ONLY entry that edits morning-brief.py or test_morning_brief.py. RED first, three groups: (1) WITHHELD: stage five owed items across DUE / owner:assaf / needs_founder loops; collect_owed returns provenance-tagged rows (source in {linear, loops}); the lead tier renders exactly three rows plus one row 'withheld N more: M in Linear, K in open-loops' derived from the tags (covers finding-15). (2) ISOLATION: monkeypatch one collector to raise RuntimeError('token=abc'); the other sections render; the failing one renders 'COULD NOT READ: <collector> failed (RuntimeError)' with NO exception message in the brief and the message in the local log (covers finding-14); degraded is True. (3) REGISTRY: OPTIONAL_SECTIONS = [(module_stem, key, title), ...]; a present module runs through the same guard within a 20-second budget; an absent module renders no section and writes one log line; a test enumerates SECTIONS + OPTIONAL_SECTIONS and asserts each is guarded. Add the missing capability fragment for test_morning_brief.py."
  },
  {
    "id": "mbl-roadmap-scope-classifier",
    "title": "One deterministic roadmap-scope classifier, fail-closed, shared by every consumer",
    "finding_id": "finding-1",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/roadmap_scope.py",
      "q-system/.q-system/tests/test_roadmap_scope.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_roadmap_scope.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope.py -k 'fail_closed or labelled_rule'",
    "acceptance": "RED first: classify(text, declared_target) returns roadmap for a product proposal labelled target=rule (the exact bypass finding-1 names); returns unknown for empty text or an unrecognised target, and unknown is a refusal for every consumer; returns system for a rule/lint/trigger/context proposal. Pattern lists for product, pricing, publish, client-advice live in this module only. No LLM call, no network, importable, and a CLI `roadmap_scope.py --target X` that exits 0/2/3 for system/roadmap/unknown so friction-note.sh can call it."
  },
  {
    "id": "mbl-roadmap-scope-paraphrase-suite",
    "title": "The roadmap boundary holds against a paraphrase suite run through every consumer",
    "finding_id": "finding-12",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/tests/fixtures/roadmap_scope_cases.json",
      "q-system/.q-system/tests/test_roadmap_scope_suite.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_roadmap_scope_suite.py.json",
      "q-system/.q-system/scripts/roadmap_scope.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope_suite.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_roadmap_scope_suite.py -k paraphrases",
    "acceptance": "A fixture file with at least 12 roadmap paraphrases covering product, pricing, publishing and client advice (none containing the literal words 'product' or 'roadmap') and at least 6 legitimate system proposals. RED first: the suite runs the SAME fixtures through roadmap_scope.classify AND through each consumer's refusal path (weekly-improve, improve_ground) by import, asserting every roadmap case is refused and every system case passes. Pattern lists may be extended in roadmap_scope.py to make the suite green; a case may not be deleted to make it green."
  },
  {
    "id": "mbl-friction-artifact",
    "title": "Friction artifact with ids and redaction, weekly pass via slack_founder, empty distinct from broken",
    "finding_id": "finding-18",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/friction-note.sh",
      "q-system/.q-system/scripts/weekly-improve.py",
      "q-system/.q-system/tests/test_weekly_improve.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_weekly_improve.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/slack-notify.sh", "plugins/kipi-core/skills/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py -k 'masked or refused'",
    "acceptance": "RED first: (1) friction-note.sh assigns an id fr-<date>-<n>, refuses a line containing an email address (exit 1), and refuses when roadmap_scope says roadmap or unknown; (2) weekly-improve.py over an empty friction.jsonl renders 'nothing this week', over an unreadable one renders COULD NOT READ, and the two strings differ; (3) one friction line yields a proposal citing its id and a 60-character excerpt with emails masked, and a source-text assertion that the whole line never appears in the delivered message; (4) delivery goes through slack_founder.deliver; a source-text test asserts slack-notify.sh is never referenced; (5) a roadmap line that reached the file anyway is refused at read time. friction.jsonl lives under q-system/memory/ (instance-owned); the writer creates it on a fresh instance. Tests use tmp_path, never the live memory dir."
  },
  {
    "id": "mbl-changelog-convention",
    "title": "Changelog header convention documented once and asserted on the skill this PRD creates",
    "finding_id": "finding-3",
    "priority": "p2",
    "allowed_files": [
      "plugins/kipi-core/skills/README.md",
      "q-system/.q-system/tests/test_skill_changelog.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_skill_changelog.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "plugins/kipi-core/skills/*/SKILL.md"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_skill_changelog.py -k no_wildcard",
    "acceptance": "README.md states the convention (a '## Changelog' section with dated lines, newest first). RED first: the test asserts plugins/kipi-core/skills/improve/SKILL.md carries the header once it exists (skips with an explicit reason until issue mbl-improve-skill lands) and asserts, by reading git-tracked paths, that NO existing SKILL.md was modified by this issue. No wildcard allowed_files; existing skills are untouched."
  },
  {
    "id": "mbl-unknown-term-detector",
    "title": "Unknown-term section with normalization, allowlists and a precision fixture",
    "finding_id": "finding-13",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/unknown_terms.py",
      "q-system/.q-system/tests/test_unknown_terms.py",
      "q-system/.q-system/tests/fixtures/unknown_terms_precision.json",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_unknown_terms.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/canonical/**", "q-system/.q-system/scripts/morning-brief.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py -k precision",
    "acceptance": "A registered optional section (module stem unknown_terms, added to OPTIONAL_SECTIONS by issue mbl-brief-core in advance; this issue only provides the module). collect(now, payloads, canonical_dir) is pure over already-fetched calendar and mail payloads: no second pull. Normalization: drop sentence-initial capitalized words unless they recur mid-sentence, drop signature blocks, drop calendar attendee names and email local parts, drop a stopword list, drop any term present in canonical_dir. RED first: precision fixture with 5 planted unknowns and 10 planted decoys (attendee names, sentence starts, signature lines, common brands present in canonical); at least 4 of 5 surface and 0 decoys; cap is 5. Live evidence (one real unknown) recorded at closeout, not asserted by pytest."
  },
  {
    "id": "mbl-board-section-bounded",
    "title": "Notion board as a bounded pre-send section whose status is a line in the brief",
    "finding_id": "finding-4",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/notion_board.py",
      "q-system/.q-system/tests/test_notion_board.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_notion_board.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/morning-brief.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py -k 'budget or pytest_refuses or never_ask'",
    "acceptance": "A registered optional section (module stem notion_board). collect(now, owed_rows, opener=None, budget_s=20) writes top-of-mind then reads it back and returns rows ['board: written, read-back ok'] or error text; the caller's guard renders COULD NOT READ on raise or on exceeding the budget. RED first with a fake opener: (1) write then read-back agree on three items and the count; (2) an opener that sleeps past the budget yields 'board timed out (20s)'; (3) refuses under PYTEST_CURRENT_TEST like slack_founder.deliver; (4) source-text test: never reads NOTION_TOKEN_ASK, never names an ASK page id; (5) token and page id are read via Path.home() / '.config/kipi/', no /Users/ literal; missing page-id file means the section is absent, not an error."
  },
  {
    "id": "mbl-board-item-identity",
    "title": "Board items carry a stable id and a hand-moved item is never re-added",
    "finding_id": "finding-5",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/notion_board.py",
      "q-system/.q-system/tests/test_notion_board.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/morning-brief.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py -k moved_stays_moved",
    "acceptance": "Every item line ends with its stable id (Linear identifier or open-loop id). Before writing, the writer reads the whole page; any id found outside the top-of-mind block is excluded from the rewrite. RED first: fake page with ASK-402 in 'this week'; today's owed rows include ASK-402; after collect(), top-of-mind does not contain ASK-402 and 'this week' still does. Only the top-of-mind block is ever rewritten; a test asserts the other two blocks' request payloads are never sent."
  },
  {
    "id": "mbl-board-live-readback",
    "title": "A live read-back check that fails closed without the token, required to close",
    "finding_id": "finding-6",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/notion_board.py",
      "q-system/.q-system/tests/test_notion_board.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/morning-brief.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py"],
    "bypass_check": "python3 q-system/.q-system/scripts/notion_board.py --live-check",
    "acceptance": "notion_board.py --live-check writes a sentinel line to top-of-mind, reads it back, removes it, prints the page id and the round-trip time, and exits non-zero on missing token, missing page id, permission error, or mismatch. The bypass_check IS that live command, so this issue cannot close on a fake opener: it stays open until the founder places ~/.config/kipi/notion-token and notion-board-page. A pytest with a fake opener covers the mismatch and missing-credential branches RED first."
  },
  {
    "id": "mbl-draft-sent-pairing",
    "title": "Draft-vs-sent pairing by Gmail identity, unmatched drafts counted not guessed",
    "finding_id": "finding-7",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/draft-vs-sent.py",
      "q-system/.q-system/tests/test_draft_vs_sent.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_draft_vs_sent.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/data/metrics.db"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py -k 'by_id or unmatched'",
    "acceptance": "Pairing is by Gmail message id only: drafts are read from q-system/output/drafts-ledger.jsonl (entries carry the Gmail draft message id; this issue defines the schema and the append helper the brief and /q-create will call) and each id is looked up in sent mail through the injectable runner seam. Subject, recipient or time similarity is never used. RED first: a fixture with two drafts sharing a subject pairs only the one whose id appears in sent mail; the other is reported in the output as unmatched with a count. Writes copy_edits rows into a tmp_path metrics.db in tests; never exemplars.jsonl."
  },
  {
    "id": "mbl-draft-sent-projection",
    "title": "Only a diff projection is stored: no raw bodies, hashed recipients, 90-day purge",
    "finding_id": "finding-8",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/draft-vs-sent.py",
      "q-system/.q-system/tests/test_draft_vs_sent.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/data/metrics.db"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py -k 'no_raw_body or purge'",
    "acceptance": "The stored copy_edits row holds a unified diff of draft vs sent, recipient addresses replaced by a salted hash, no subject and no headers; original/edited columns receive the diff halves, never the full bodies. RED first: a test plants a recipient address and a unique body sentence and asserts neither appears anywhere in the stored row; --purge deletes rows older than 90 days and reports the count, and a test proves a 91-day-old row goes and an 89-day-old row stays."
  },
  {
    "id": "mbl-weekly-improve-runner",
    "title": "Weekly runner triggers producer, learner and pass in order; plist template; empty is not a proposal",
    "finding_id": "finding-9",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/weekly-improve.sh",
      "q-system/.q-system/scripts/com.kipi.weekly-improve.plist",
      "q-system/.q-system/scripts/route-overrides-to-learn.py",
      "q-system/.q-system/tests/test_route_overrides_to_learn.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_route_overrides_to_learn.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/data/metrics.db", "q-system/.q-system/scripts/install-plist.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_route_overrides_to_learn.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_route_overrides_to_learn.py -k 'empty_is_not_a_proposal or order'",
    "acceptance": "weekly-improve.sh runs draft-vs-sent.py, then route-overrides-to-learn.py, then weekly-improve.py, in that order, logging each step's exit code to q-system/output/weekly-improve.log (the self-healing-retry contract: every attempt logged); a failing producer does not skip the pass. The plist template runs that script Monday 06:30 with __KIPI_REPO__/__HOME__/__USER__ and no /Users/ literal (install-plist.sh already resolves templates by label, finding-10). RED first: (1) route-overrides-to-learn.py over an empty copy_edits exits 2 and writes an empty-body file, and a checker in the runner reports that file as EMPTY so a dated file alone never counts as a proposal; (2) the runner's order is asserted from a dry-run trace; (3) plist template placeholders asserted. Live proof at closeout: install-plist.sh weekly-improve, launchctl kickstart from a bare environment, one log line per step."
  },
  {
    "id": "mbl-improve-skill",
    "title": "The improve skill with an explicit corpora contract and the shared roadmap classifier",
    "finding_id": "finding-11",
    "priority": "p2",
    "allowed_files": [
      "plugins/kipi-core/skills/improve/SKILL.md",
      "plugins/kipi-core/skills/improve/scripts/improve_ground.py",
      "plugins/kipi-core/skills/improve/scripts/test_improve_ground.py",
      "q-system/.q-system/capability/expected_tests/plugins__kipi-core__skills__improve__scripts__test_improve_ground.py.json",
      "CLAUDE.md"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py"],
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py -k 'corpora or already_built'",
    "acceptance": "improve_ground.py reads KIPI_LESSONS_CORPORA (colon-separated directories; default: this instance's q-system/lessons resolved relative to the script) and reports each corpus as read (with count) / missing / unreadable in its output; nothing hardcodes a sibling checkout. RED first: (1) with one missing corpus the verdict still prints and names it missing; (2) 'risk-scored auto-merge' returns already-built naming review-tier.py; (3) any case the roadmap classifier calls roadmap or unknown returns skip with that reason (uses roadmap_scope.py by import, no second classifier). SKILL.md carries a ## Changelog header. /improve is listed in CLAUDE.md commands."
  },
  {
    "id": "mbl-two-measurements",
    "title": "Permission-ask counter with a ledger, and decision-corpus cost with a stated formula",
    "finding_id": "finding-16",
    "priority": "p2",
    "allowed_files": [
      "q-system/.q-system/scripts/permission-ask-counter.py",
      "q-system/.q-system/scripts/decision-corpus-cost.py",
      "q-system/.q-system/tests/test_permission_ask_counter.py",
      "q-system/.q-system/tests/test_decision_corpus_cost.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_permission_ask_counter.py.json",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_decision_corpus_cost.py.json",
      "q-system/output/plans/morning-brief-overhaul-2026-08-30.md"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/voice-dna-loader.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_permission_ask_counter.py q-system/.q-system/tests/test_decision_corpus_cost.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_permission_ask_counter.py -k broken_apparatus_exits_3",
    "acceptance": "RED first: (1) the counter over a fixture transcript with two pick-then-menu turns reports count 2 and appends one ledger line to q-system/output/permission-ask-ledger.jsonl; over an unreadable sample dir it exits 3 and appends nothing; (2) the cost script prints bytes and tokens = ceil(bytes / 4) with that formula in its output (finding-16: reproducible by construction; no tokenizer dependency) and exits 3 when KIPI_VOICE_DIR is unset. The measured live cost is written into the plan file's 2h section; voice-dna-loader.py is NOT modified and route_classifier.py is never imported."
  },
  {
    "id": "mbl-off-switches",
    "title": "Every new job and writer has an off-switch, proven a no-op in the off state",
    "finding_id": "finding-17",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/tests/test_off_switches.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_off_switches.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/morning-brief.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_off_switches.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_off_switches.py",
    "acceptance": "Runs LAST. RED first against each module by import with tmp_path homes: (1) notion_board with no page-id file yields no section and no network call (fake opener asserts zero requests); (2) weekly-improve.sh --dry-run with no plist installed performs no writes; (3) weekly-improve.py with no friction.jsonl renders 'nothing this week' and sends nothing (slack_founder refuses under pytest and the test asserts refused, not delivered); (4) improve_ground.py is importable without side effects. A test that sets its own precondition is not enough (lesson): each case asserts the absence of the artifact the on-state would have produced."
  }
]
```
