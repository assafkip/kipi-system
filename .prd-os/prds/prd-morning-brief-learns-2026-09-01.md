---
id: prd-morning-brief-learns-2026-09-01
title: Morning brief learns (Phase 2 of the morning-brief overhaul)
status: draft
created_at: 2026-09-01T21:37:44Z
updated_at: 2026-09-01T21:40:39Z
owner: assaf
reviewers: []
findings_path: .prd-os/findings/prd-morning-brief-learns-2026-09-01-findings.jsonl
---

# Morning brief learns (Phase 2 of the morning-brief overhaul)

Source plan: `q-system/output/plans/morning-brief-overhaul-2026-08-30.md`, Phase 2
and its three amendments (items 2a-2m). Founder-approved execution plan
2026-09-01 (`~/.claude/plans/sorted-questing-pond.md`). Deconflicted the same
day with the voice-loop session and the consulting email session; both replied
NO CONFLICT on every item and added six constraints, all carried below.

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
  of what it withheld. A truncation that hides its own truncation fails.
- Every collector runs behind a call-site boundary: one raising collector costs
  its own section only, rendered `COULD NOT READ`, never the brief.
- An unknown-term detector rides the brief's already-pulled mail and calendar
  and names terms absent from `q-system/canonical/`, as its own section.
- A Notion morning board (top of mind / this week / inbox) is rewritten at
  07:00 with the same three items and count, with a read-back that proves the
  write landed, and a hand-moved item stays where the founder moved it.
- The draft-vs-sent learning stage gets a live producer, a test, and a
  registered weekly trigger, and its first-run check can fail on content.
- A friction artifact exists, a weekly pass reads it and proposes fixes through
  `slack_founder.deliver`, and that pass **refuses any proposal in
  product/roadmap scope** as a gate, not a paragraph.
- An `improve` skill critiques an outside idea against the current system,
  grounded in `lessons_recall.search()` over BOTH corpora, and returns skip on
  anything about what to build.
- Two measurements exist and are advisory: a permission-ask counter over a
  transcript sample, and the per-turn token cost of loading the decision corpus
  on every turn. Neither is a hook; neither prints a number when its apparatus
  is broken.

## Non-goals

- Deciding what to build, sell, publish, or what a client should do. **Hard
  constraint:** every loop here may propose a fix to a stage, a skill for
  manual work, a rule/lint/prompt change, or a context entry. Nothing here
  proposes product. `weekly-improve.py` enforces this in code (issue 6).
- Widening the voice-dna-loader trigger to every turn. This PRD MEASURES the
  cost (issue 8); the widening is a follow-up decision.
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
(`every-stage-needs-its-own-trigger`). Only 2c and 2m ride the brief, because
they are properties of today's incoming material and need its authenticated
pull; each is its own function behind its own boundary.

Execution order, one issue each. Earlier issues are prerequisites of later ones
where noted.

1. **Owed narrows to three** (2e). Change the lead tier of `collect_owed()`
   (lines 285-323) to emit at most three lead rows and one row
   `withheld N more: M in Linear, K in open-loops`. `_section()` is untouched.
2. **Collector isolation** (prerequisite for 3 and 4). A `_guarded(name, fn)`
   wrapper at `collect_all()` that converts any exception into
   `(rows=[], error="<type>: <msg>")` so `_section()` renders `COULD NOT READ`.
   Reproducer: monkeypatch one collector to raise, assert four sections plus
   the failure line, assert `degraded` is True.
3. **Unknown-term detector** (2c). `collect_unknown_terms(now, payloads, canon)`
   takes the calendar and mail payloads already fetched (no second pull),
   tokenizes proper nouns and capitalized multi-word terms, diffs against the
   vocabulary of `q-system/canonical/*.md`, returns the top unknowns as a
   fifth section `*Terms I do not know*`. Read-only. Offline fixture test with
   a planted unknown; live evidence recorded in the issue.
4. **Board writer** (2m). New `q-system/.q-system/scripts/notion_board.py`:
   `write_top_of_mind(items, withheld, opener=None)` and `read_back(opener=None)`
   over the Notion REST API, token from `~/.config/kipi/notion-token`, page id
   from `~/.config/kipi/notion-board-page` (both founder-created, never in the
   repo; the founder approved the new credential 2026-09-01). The 07:00 run
   rewrites the top-of-mind bucket with the same three items and count the
   Slack brief shows, then reads the page back and reports agreement or
   `COULD NOT READ`. Items the founder moved to "this week" or "inbox" are
   left alone (the writer only owns top-of-mind). The brief never waits on
   the board: the board step runs after the Slack send answered. Refuses under
   `PYTEST_CURRENT_TEST` like `slack_founder.deliver`. This is the fleet's
   second Notion REST writer; the first (consulting `board_sync.py`) is
   partitioned by parent page and token, and this one never touches the ASK
   parent page.
5. **Draft-vs-sent producer + trigger** (2k + 2a, one item because the trigger
   is dead wire without the producer). `q-system/.q-system/scripts/draft-vs-sent.py`
   pairs a draft (from `q-system/output/` drafts the brief or `/q-create`
   wrote) with the sent version (Gmail sent mail, read-only via the same
   `run_claude` seam the brief uses) and inserts rows into `copy_edits` through
   the existing `copy-diff.py` schema. Then `route-overrides-to-learn.py` gets
   `q-system/.q-system/tests/test_route_overrides_to_learn.py` (red first: an
   empty `copy_edits` must produce exit 2 and an empty-body file, and that
   file must be REPORTED as empty, not counted as a proposal) and a
   `com.kipi.weekly-improve.plist` template (Monday 06:30, `__KIPI_REPO__`
   shape, `install-plist.sh weekly-improve`). Proof: `launchctl kickstart`
   from a bare environment, then a proposal file whose body is not
   `_render_empty_body()`.
6. **Friction artifact + weekly pass** (2b + 2l). `q-system/memory/friction.jsonl`
   (instance-owned, never propagated), `friction-note.sh` (shape of
   `lesson-note.sh`; creates its own file on a fresh instance because the
   script fans out to 25 instances and the file does not),
   `weekly-improve.py` reads friction lines plus the proposals inbox, emits one
   Slack message via `slack_founder.deliver`, and **refuses** any proposal whose
   `target` is in `{product, roadmap, pricing, client-advice, publish}` (a
   classifier over the proposal's declared target field, not over prose; the
   author of a friction line declares the target). Empty file renders "nothing
   this week"; a read failure renders `COULD NOT READ`. Adds a `## Changelog`
   header to every SKILL.md it touches, with the convention documented in
   `plugins/kipi-core/skills/README.md`.
7. **Improve skill** (2d). `plugins/kipi-core/skills/improve/SKILL.md` plus
   `scripts/improve_ground.py` that calls `lessons_recall.search()` over the
   kipi corpus and, when it exists, the consulting corpus, and reads
   `capability_manifest.py` declarations. Verdict is adopt / skip / already
   built, and cites a lesson path or a named file every time. Negative
   self-test: hand it "risk-scored auto-merge" and assert the verdict is
   already built with `review-tier.py` named. Registered in `CLAUDE.md`
   commands as `/improve`.
8. **Two measurements** (2i + 2h). `permission-ask-counter.py`: on-demand,
   advisory, reads a transcript sample, counts turns that end in a question
   after a pick was named, appends `{date, sample, count, rate}` to
   `q-system/output/permission-ask-ledger.jsonl`, exits 3 when the sample dir
   is unreadable (never prints 0.00, copying `skill-trigger-eval.py:71-73`).
   `decision-corpus-cost.py`: measures the byte and token size of
   `pov.md + identity.md + scars.md` at `$KIPI_VOICE_DIR` and writes the number
   into the plan file's 2h section. No trigger is widened here.

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
- **Roadmap boundary as a prompt instruction in the weekly pass.** Rejected:
  `wire-a-hard-constraint-into-the-done-gate-and-halt-when-a-plan-quietly-relaxes-it`;
  a constraint with no failing input is decoration.
- **A hook to stop permission asks.** Rejected by the autonomy contract itself
  ("hooks are the wrong layer for this"); a measurement is the honest move.

## Scenarios

- **Monday 07:00, healthy.** launchd starts `morning-brief.py`; four sections
  plus unknown terms render; section 3 shows three items and `withheld 69
  more: 64 in Linear, 5 in open-loops`; Slack answers `ok`; the board writer
  rewrites top-of-mind and the read-back matches; receipt written; deadman
  stays quiet.
- **Board token missing.** Same run; Slack lands on time; the board section
  renders `COULD NOT READ: notion-token missing`; `degraded` is True; exit 1
  so `launchd-health` sees it. The founder still has the brief.
- **Friction line to weekly proposal.** Founder runs
  `friction-note.sh "the brief lists Sana's tickets as mine" --target rule`;
  Monday 06:30 `weekly-improve.py` reads it, proposes a rule change naming
  that line, delivers via `slack_founder.deliver`. A line with
  `--target product` is refused at write time and again at read time.
- **Outside idea.** Founder pastes a post into `/improve`; the skill runs
  `improve_ground.py`, which cites `q-system/lessons/<hit>.md` and names
  `review-tier.py`; verdict: already built. Nothing about what to build is
  ever returned as adopt.

## Resolved decisions

- **Two PRDs, in sequence.** Decided: Phase 2 here; Phases 3+4 in
  `lessons-rail-and-up-rail` after this one is split and cleared. Rationale:
  one active PRD and one active issue at a time; 3+4 wait on Sana's git call.
- **2a and 2k are one issue.** Decided: producer first, trigger second, content
  check third. Rationale: `copy_edits` has 0 rows; a trigger on an empty table
  passes vacuously.
- **2m credential.** Decided by the founder 2026-09-01: a new kipi Notion
  integration token at `~/.config/kipi/notion-token`, page id at
  `~/.config/kipi/notion-board-page`. Rationale: the only path that satisfies
  "rewritten at 07:00" from launchd.
- **Single writer of `exemplars.jsonl` is `q-consult/pipeline/voice.py`.**
  Decided with the voice-loop session. 2k writes `copy_edits` only.
- **This work runs in the worktree `~/projects/kipi-wt-prd-mbl` on branch
  `prd/morning-brief-learns`, based on `ddad93b1`.** Rationale: Phase 1
  (`morning-brief.py`) exists only on that line, not on `main` or
  `origin/main`; the main checkout carries another session's staged work.
  The base choice and the eventual merge are Sana's call and are recorded
  here, not decided by the founder.

## Risks and rollback

- **Fan-out blast radius.** `friction-note.sh`, `weekly-improve.py`,
  `draft-vs-sent.py`, `notion_board.py` and the plist template live under
  `q-system/.q-system/scripts/` and reach 25 instances on the next
  `kipi update`. Each script creates its own state, refuses without its
  credential, and is inert without its plist installed. Rollback: delete the
  files; `kipi update` propagates the deletion.
- **Content tripwire.** `kipi-push-upstream.sh:26-34` refuses any file under
  `q-system/` naming the founder or `/Users/`. Every new file uses `__HOME__`
  / `Path.home()` and no founder name.
- **Second Notion writer in the fleet.** Partitioned by parent page and token;
  a test asserts `notion_board.py` never reads `NOTION_TOKEN_ASK` and never
  names an ASK page id.
- **Unknown-term detector on real mail.** Read-only; the risk is noise, not
  damage. Capped at five terms per day.
- **Rollback of the whole PRD:** revert the branch; Phase 1's brief keeps
  running unchanged because every change is additive behind a boundary.

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
boundary is a coded refusal with a failing input (issue 6), and the two
measurements (issue 8) are advisory by construction.

Q2: What is the smallest experiment that would disprove the thesis?
A2: Run `weekly-improve.py` for four Mondays. If zero friction lines are ever
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
    "id": "mbl-owed-narrows-to-three",
    "title": "Owed today shows at most three items plus an explicit withheld count",
    "finding_id": "TBD-after-review",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/morning-brief.py",
      "q-system/.q-system/tests/test_morning_brief.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_morning_brief.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-system/.q-system/scripts/voice-stop-gate.py"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py -k withheld",
    "acceptance": "RED first: stage five owed items (mix of DUE, owner:assaf and needs_founder loops), assert the lead tier renders exactly three rows and one row stating the withheld count split by source. _section() is not modified. Also add the missing capability fragment for test_morning_brief.py so the capability gate sees the file it never declared."
  },
  {
    "id": "mbl-collector-isolation",
    "title": "A raising collector costs its own section only",
    "finding_id": "TBD-after-review",
    "priority": "p0",
    "allowed_files": [
      "q-system/.q-system/scripts/morning-brief.py",
      "q-system/.q-system/tests/test_morning_brief.py"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py -k isolation",
    "acceptance": "RED first: monkeypatch one collector to raise RuntimeError, assert build() still renders the other sections, the raising one renders COULD NOT READ with the exception text, and degraded is True. Every collector in collect_all() goes through the same guard; a test enumerates SECTIONS and asserts each key is guarded."
  },
  {
    "id": "mbl-unknown-term-detector",
    "title": "The brief names terms absent from canonical, as its own guarded section",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/morning-brief.py",
      "q-system/.q-system/scripts/unknown_terms.py",
      "q-system/.q-system/tests/test_morning_brief.py",
      "q-system/.q-system/tests/test_unknown_terms.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_unknown_terms.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-system/canonical/**"],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py q-system/.q-system/tests/test_morning_brief.py"
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_unknown_terms.py -k planted",
    "acceptance": "Pure function over already-fetched payloads; no second network pull. RED first: a fixture with a planted proper noun absent from a tmp canonical dir surfaces it; the same noun present in canonical does not. Read-only on mail and calendar. Capped at five terms. Live evidence (one real unknown from the founder's inbox) is recorded in the issue closeout, not asserted by pytest."
  },
  {
    "id": "mbl-board-writer",
    "title": "Notion morning board rewritten at 07:00 with read-back, never delaying the Slack brief",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/notion_board.py",
      "q-system/.q-system/scripts/morning-brief.py",
      "q-system/.q-system/tests/test_notion_board.py",
      "q-system/.q-system/tests/test_morning_brief.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_notion_board.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py q-system/.q-system/tests/test_morning_brief.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_notion_board.py -k 'read_back or pytest_refuses or never_ask'",
    "acceptance": "RED first with a fake opener: (1) write then read_back agree on the three items and the count; (2) a failed write renders COULD NOT READ in the brief and the Slack send has already answered before the board step runs; (3) deliver-style refusal under PYTEST_CURRENT_TEST; (4) the module never reads NOTION_TOKEN_ASK and never names an ASK page id (source-text test); (5) items outside top-of-mind are not touched by the writer. Token and page id are read from ~/.config/kipi/ via Path.home(); no literal /Users/ path. Live proof (a real read-back) needs the founder's token and is recorded when it exists, never faked."
  },
  {
    "id": "mbl-draft-vs-sent-producer",
    "title": "Draft-vs-sent producer, a test for route-overrides-to-learn.py, and its weekly trigger",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/draft-vs-sent.py",
      "q-system/.q-system/scripts/route-overrides-to-learn.py",
      "q-system/.q-system/scripts/com.kipi.weekly-improve.plist",
      "q-system/.q-system/tests/test_draft_vs_sent.py",
      "q-system/.q-system/tests/test_route_overrides_to_learn.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_draft_vs_sent.py.json",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_route_overrides_to_learn.py.json"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/data/metrics.db"],
    "required_checks": [
      "python3 -m pytest -q q-system/.q-system/tests/test_draft_vs_sent.py q-system/.q-system/tests/test_route_overrides_to_learn.py",
      "python3 -m pytest -q q-system/.q-system/tests/test_morning_brief.py -k plist"
    ],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_route_overrides_to_learn.py -k empty_is_not_a_proposal",
    "acceptance": "RED first, three tests: (a) draft-vs-sent.py inserts a copy_edits row into a tmp_path metrics.db from one draft/sent pair and skips identical pairs; (b) route-overrides-to-learn.py on an empty table exits 2 and the inbox file it writes is reported as EMPTY by a checker, so a dated file alone can never satisfy the trigger proof; (c) the plist template carries __KIPI_REPO__/__HOME__/__USER__ and no /Users/ literal. Single writer note: exemplars.jsonl in consulting is never written; copy_edits only. Live proof: install-plist.sh weekly-improve, launchctl kickstart from a bare environment, a proposal file whose body is not _render_empty_body()."
  },
  {
    "id": "mbl-friction-artifact",
    "title": "Friction artifact, weekly pass via slack_founder, roadmap refusal in the gate, changelog headers",
    "finding_id": "TBD-after-review",
    "priority": "p1",
    "allowed_files": [
      "q-system/.q-system/scripts/friction-note.sh",
      "q-system/.q-system/scripts/weekly-improve.py",
      "q-system/.q-system/tests/test_weekly_improve.py",
      "q-system/.q-system/capability/expected_tests/q-system__.q-system__tests__test_weekly_improve.py.json",
      "plugins/kipi-core/skills/README.md",
      "plugins/kipi-core/skills/*/SKILL.md"
    ],
    "disallowed_files": [".claude/**", "plugins/prd-os/**", ".prd-os/**", "q-consult/**", "q-system/.q-system/scripts/slack-notify.sh"],
    "required_checks": ["python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py"],
    "bypass_check": "python3 -m pytest -q q-system/.q-system/tests/test_weekly_improve.py -k roadmap_refused",
    "acceptance": "RED first: (1) a friction line with target=product is refused by friction-note.sh (exit 1) AND by weekly-improve.py if it appears in the file anyway; (2) an empty friction.jsonl renders 'nothing this week', an unreadable one renders COULD NOT READ, and the two are distinct strings; (3) one real friction line produces a proposal that names that line verbatim; (4) delivery goes through slack_founder.deliver and a source-text test asserts slack-notify.sh is never referenced. friction.jsonl lives under q-system/memory/ (instance-owned); the writer creates the file. Every SKILL.md touched gains a ## Changelog header; the convention is written once in plugins/kipi-core/skills/README.md."
  },
  {
    "id": "mbl-improve-skill",
    "title": "The improve skill: an outside idea critiqued against both corpora, never about what to build",
    "finding_id": "TBD-after-review",
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
    "bypass_check": "python3 -m pytest -q plugins/kipi-core/skills/improve/scripts/test_improve_ground.py -k already_built",
    "acceptance": "RED first: improve_ground.py given 'risk-scored auto-merge' returns verdict already-built and names review-tier.py; given a product idea ('sell a Notion template') returns skip with the reason 'roadmap scope'; every verdict carries at least one lessons path or named file. It calls lessons_recall.search() as an import over the kipi corpus and, if ~/projects/consulting/q-system/lessons exists, that one too, and prints which corpora it read. /improve is listed in CLAUDE.md commands."
  },
  {
    "id": "mbl-two-measurements",
    "title": "Permission-ask counter and decision-corpus cost, both advisory, neither prints a number when broken",
    "finding_id": "TBD-after-review",
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
    "acceptance": "RED first: (1) the counter over a fixture transcript with two pick-then-menu turns reports count 2 and appends one ledger line; over an unreadable sample dir it exits 3 and appends nothing; (2) the cost script over a tmp voice dir reports bytes and an approximate token count and refuses (exit 3) when KIPI_VOICE_DIR is unset. The measured live cost is written into the plan file's 2h section as the deliverable; voice-dna-loader.py is NOT modified (disallowed) and route_classifier.py is never imported."
  }
]
```
