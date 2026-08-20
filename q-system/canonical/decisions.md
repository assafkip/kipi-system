# Decision Log

> Active rules governing system behavior. Referenced during morning routine and pipeline management.

## Format <!-- pin -->

```
### RULE-XXX: [Name]
- **Origin:** [USER-DIRECTED] / [CLAUDE-RECOMMENDED -> APPROVED/MODIFIED/REJECTED] / [SYSTEM-INFERRED]
- **Decision:** [what we do]
- **Reason:** [why]
- **Date:** [when decided]
- **Revisit:** [when to reconsider, or "permanent"]
```

Monthly audit (1st of month): count decisions by origin tag. If >60% are rubber-stamped approvals, flag for review.

## Starter Rules <!-- pin -->

### RULE-001: Warm Intro Beats Cold
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** If a warm intro path exists, use it. Do not cold-DM someone you can reach through a connector.
- **Reason:** Warm intros convert 5-10x better. Cold outreach burns goodwill.
- **Revisit:** Permanent

### RULE-002: Auto-Close Dead Loops
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** 3 outreach touches + no response + 14 days = auto-close to "Passed." No founder decision needed.
- **Reason:** Open loops consume working memory. Close them automatically.
- **Revisit:** Permanent

### RULE-003: Max 1 Value Drop Per Person Per Week
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** Never send more than 1 unsolicited value message to any person in a 7-day window.
- **Reason:** Frequency = spam. Quality + spacing = relationship.
- **Revisit:** Permanent

## Git Coverage (2026-07-29) <!-- pin -->

### RULE-004: A Private Remote Is The Default, Local-Only Is A Declaration
- **Origin:** [USER-DIRECTED]
- **Decision:** `kipi new` creates a private GitHub repo by default. Opting out requires
  `KIPI_LOCAL_ONLY=1` AND `KIPI_LOCAL_ONLY_REASON="why"`, written to
  `remote-coverage-allow.json` at creation. Missing reason = exit 1. The push happens
  after the seed commit, since an empty remote reads as covered and is not.
- **Reason:** Inflow was automated, outflow was manual. 12 repos existed on one disk,
  oldest 219 commits, several client engagements. Nothing reported the gap.
- **Date:** 2026-07-29
- **Revisit:** Permanent

### RULE-005: One Fleet-Wide Coverage Gate, Not Per-Instance Copies
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** `remote-coverage-check.py` lives once at kipi-system root, audits
  `~/projects` as a whole, returns the same answer from any cwd. It does not ship
  per-instance. It also flags directories that are not repos at all, and asks git what
  it TRACKS rather than trusting an ancestor `.git`.
- **Reason:** N copies means N identical scans and N allowlists drifting apart. One gate
  that sees every system IS fleet coverage. The tracks-not-ancestor check exists because
  `personal/.gitignore` line 1 is `projects/`, so nested work looked covered and was invisible.
- **Note:** Diverges from the literal instruction ("push this to all of the systems").
  Probe: `kipi check` run from inside instance `thaena` fires the gate. Not yet founder-ratified.
- **Date:** 2026-07-29
- **Revisit:** If an instance ever needs a coverage answer scoped to itself

### RULE-006: Allowlist Reasons Name The Data Class, Never The Data
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** An entry in `remote-coverage-allow.json` states the CLASS of sensitive
  content and the path carrying it. Never the content itself.
- **Reason:** That file is committed to a PUBLIC repo. The first draft explained why the
  family repos stay local by quoting a minor's diagnosis and school materials into
  kipi-system. gitleaks, blocked-paths, and large-files all passed it. Caught by re-reading,
  not by a gate. A reason that quotes the private data defeats the gate it documents.
- **Date:** 2026-07-29
- **Revisit:** Permanent

### RULE-007: Family-Medical Repos Are Never Pushed, Private Included
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** `AUDHD_KIDS` and `travel-agent` stay local-only until their carrier files
  move to gitignored paths.
- **Reason:** Health and education records about a specific minor, re-identifying against
  the owner's public identity. Private on someone else's servers is still off-disk.
- **Probe:** `git remote` returns 0 remotes for both, and `gh repo view` returns not-found,
  re-run after the private-by-default flip.
- **Date:** 2026-07-29
- **Revisit:** Once the carrier paths are gitignored

### RULE-008: History Gets A Parallel Clean Branch, Not A Rewrite
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** `story-podcast` (two committed venv libs, 178MB + 123MB, over GitHub's
  100MB limit) got a fresh orphan `main` with clean source, pushed private. The original
  `master` with full history stays intact locally and unpushed.
- **Reason:** Non-destructive. Source is now off-disk; nothing was destroyed to get there.
- **Open:** The full history still exists only on the laptop, so the repo is covered for
  its source and NOT for its history. A real rewrite is still undecided.
- **Date:** 2026-07-29
- **Revisit:** When the 300MB history matters enough to rewrite

### RULE-009: Audit The Class, Not The Artifact You Were Handed
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** When hardening one deployed surface, enumerate every surface in the same
  class first. A deployed site with no source on disk is invisible to any gate that walks
  directories.
- **Reason:** The `deliverables` site was hardened while the demos actually emailed to
  prospects sat on two other Vercel projects nobody had looked at, fully indexable, naming
  real organizations. The constraint that drove the original fix ("renaming breaks links
  already shared") was an inference, never probed, and was false. Cole probed it four ways
  and found no link had ever been sent. See `q-system/lessons/prove-a-negative-with-a-live-probe.md`.
- **Date:** 2026-07-29
- **Revisit:** Permanent

### RULE-010: A Clean Review Round Is Not Evidence Of Sufficiency
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** When a defect class has produced a finding every round on one surface,
  restructure regardless of the next round's verdict, and decide it BEFORE that verdict
  arrives so the outcome cannot shape the decision.
- **Reason:** For a property enforced at N independent seams, a quiet round means one
  reviewer did not find the N+1th seam. Blindness was enforced at four seams on the judge
  and three were wrong. Validated twice: after the override, the very next round found a
  real hole in the half already called stable and one commit from shipping.
- **Date:** 2026-08-05
- **Revisit:** Permanent

### RULE-011: Kill A Defect Class By Deleting The Mechanism
- **Origin:** [CLAUDE-RECOMMENDED -> MODIFIED]
- **Decision:** Three successive hardenings of a date inference were retired by deleting
  the exemption mechanism entirely, so the gate consults no date at all.
- **Reason:** A creation-date floor exempted every FUTURE decision on any pre-floor PRD;
  35 of 36 PRDs predated it, making the gate near-permanently inert. The recommendation
  was mine and the measurement showing it was inert was in hand and misread as "safe".
  Codex caught it. Before deleting, the protected set was measured, not assumed.
- **Date:** 2026-08-05
- **Revisit:** Permanent

### RULE-012: The Runtime Is Not The Repo, And The Clone Is Not The Runtime
- **Origin:** [CLAUDE-RECOMMENDED -> MODIFIED]
- **Decision:** Verify the copy that actually loads. Plugins run from a version-pinned
  cache registered in `installed_plugins.json`, not from the marketplace clone and not
  from a project's `plugins/` dir. Refreshing the clone alone changes nothing.
- **Reason:** After two days of merged work, the loaded plugin was version 0.1.0 from
  April. My acceptance criteria targeted the clone, so following them would have gone
  green over five-month-old code. Sana found the second layer. Detector shipped
  (`runtime-plugin-freshness.py`), with the stated gap that version parity alone cannot
  see commit drift.
- **Date:** 2026-08-05
- **Revisit:** When plugin loading changes

### RULE-013: Migration Receipts Carry No Judge Run
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** Re-dispositioning historical decisions to satisfy a receipt gate is done
  WITHOUT a judge run, so the records satisfy the gate while being excluded from
  calibration by construction.
- **Reason:** Freezing today's workflow context against a decision made two months ago
  manufactures precisely the retroactive artifact the whole system exists to prevent.
  A receipt with `human` and no `judge` is excluded from scoring by construction.
- **Date:** 2026-08-05
- **Revisit:** Permanent

### RULE-014: A Gate's Refusal Is Information, Not An Obstacle
- **Origin:** [CLAUDE-RECOMMENDED -> MODIFIED]
- **Decision:** An unbuildable PRD was released with `clear`, not `archive`, after the
  archive gate refused. Its 8 accepted findings were NOT re-triaged to `rejected` to buy
  the transition.
- **Reason:** I recommended archive. Sana ran it to capture the real refusal: the findings
  lack issue receipts and can never have them, because they INVALIDATE the PRD rather than
  describe work. Archiving would assert "done and accounted for" about something never
  built. Re-triaging would have erased a real review's conclusions for a state change.
  Gate/model mismatch captured as `sp-8c286548` instead of papered over.
- **Date:** 2026-08-05
- **Revisit:** When prd-os gains a disposition for self-invalidating findings

### RULE-015: Autonomous Is The Target; CLI Constraints Are Not Blockers
- **Origin:** [USER-DIRECTED]
- **Decision:** Rank runtime paths by who drives them. The agent/plugin/scheduled path is
  the product; a hand-typed CLI is a convenience wrapper. A broken CLI is a footnote, not
  an incident. "Needs a human decision" is a defective deferral, not a terminal state.
- **Reason:** Founder, 2026-08-05: "The way this should work is completely autonomous so
  I dont care about the cli and command constraints." I had elevated a broken CLI to equal
  status with the agent path that actually executes the work. Safety holds (destructive
  ops, another session's uncommitted work, irreversible deletions) are NOT overridden by
  this; they get decided by an agent with evidence rather than escalated as questions.
- **Date:** 2026-08-05
- **Revisit:** Permanent

### RULE-016: A Root That Holds Nested Repos Is Not Dispatchable, Even Outside An Engagement Root
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** ASK-842 option (b). `cole-gtm` (registry `gtm-partner`) and
  `reddit-build-radar` stay OFF for unattended dispatch. Their 4 issues (ASK-127,
  ASK-717, ASK-718, ASK-146) are worked as supervised founder-initiated runs. The
  decision is stored as `dispatch.enabled: false` carrying its issue id and reason,
  not as an absent key, and `test-ask842-dispatch-decision.sh` turns red if either
  row is flipped without editing the record.
- **Reason:** Measured 2026-08-14. `cole-gtm` tracks **0 files under `projects/`**
  while holding **9 nested separate git repos** there, and tracks 3001 files under
  `gtm/`, the live outbound engine. That is the identical shape ASK-754 refused at
  the consulting root: preflight check 5 (dirty) is structurally blind to all nine
  nested repos while a dispatched agent still has filesystem reach into them, so an
  `OK` from the gate would be an OK the gate cannot back. Check 0 does not catch it
  because `cole-gtm` is a persona root, not an engagement root, so the blast-radius
  property is present with no refusal in front of it. `reddit-build-radar` was filed
  as curable control-code *drift*; it is *absence* -- no `linear-worker.sh` and no
  `.claude/settings.json` at all, which follows from its deliberate
  `skeleton_managed: false` (ASK-117). Curing it reverses ASK-117 rather than
  clearing drift, so option (c) is the expensive path, not the cheap one.
  Explicitly NOT decided on cost: every remaining `cole-gtm` preflight failure is
  curable. The reason is blast radius.
- **Date:** 2026-08-14
- **Revisit:** When preflight can see into nested repos a dispatch root does not
  track (`sp` captured), or when the 4 issues are worked and the surfaces go quiet

## A fleet alert is a notification, not dispatch work (ASK-839)

- **Origin:** [SYSTEM-INFERRED]
- **Decision:** Two halves, both shipped together.
  1. `alert-to-linear.py` now sets a `projectId` on every ticket it files,
     derived from the alerting repo through `instance-registry.json`'s
     `linear_project` field. Attribution, so a ticket says which instance raised
     it in a field a query can filter on.
  2. Alert tickets are **excluded from the automatic dispatch queue** by their
     `kipi-alert-fingerprint` marker: `linear-worker.sh` drops them from both
     `ready()` and `ready_ignoring_project()`, and `linear-dor-drafter.py`
     refuses to draft onto them. They stay on the board, labelled `owner:sana`
     and now project-attributed, for a human or a triage pass to convert into a
     real issue. They do not enter the loop as pre-scoped work.
- **The fork this answers:** ASK-839 asked for the 81 existing project-unset
  alert tickets to be BACKFILLED with a project, OR for an explicit decision
  that they are not dispatch work. Backfill was refused on the measurement, not
  on taste: of the 81 open unset alert tickets, only 33 carry a `[label]` prefix
  that names a real project. 22 were raised from a cwd of `/` and 16 more from a
  worktree directory (`.wt-ask791`, `kipi-wt-ask729`, `cleanmain`). A backfill
  invents routing for the majority and then hands a worker a raw alert line
  ("auto-commit left 3 file(s) uncommitted") as if it were a spec.
- **Second question, answered in the same change:** yes, the DoR drafter refuses
  to draft onto a project-unset issue. Drafting a Definition of Ready onto an
  unroutable ticket does not make it executable, it makes it READY-SHAPED, and
  ready-shaped is the only thing the worker queue checks. That promotion is what
  moved these from "not ready" (honest) to "ready and reachable by nobody".
  Refusals of REAL unrouted issues are counted and named on stdout rather than
  silently skipped.
- **Measured 2026-08-15, live ASK board (832 issues):** 81 open alert tickets,
  all project-unset. 19 already drafted onto, and all 19 were ready-shaped and
  unset -- 100% of that population and 43% of the 20-issue UNREACHABLE bucket.
  After the change the worker dry run reports 1 unreachable issue and no
  `(unset)` at all.
- **Date:** 2026-08-15
- **Revisit:** If alert tickets start needing to be worked automatically, the
  right move is a converter that turns one into a scoped issue, not re-admitting
  raw alert bodies to the queue.
