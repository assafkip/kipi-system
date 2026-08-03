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

### RULE-010: The Dispatch Spend Dial Is 10 Issues Per Budget Day
- **Origin:** [USER-DIRECTED]
- **Decision:** `KIPI_DISPATCH_DAILY_MAX` raised 3 -> 10, effective the same budget day
  rather than the next window. Concurrency (`KIPI_DISPATCH_MAX`) stays at 1.
- **Reason:** 66 issues carried the `ready` label; the cap was the binding constraint, not
  the queue. At `ROUNDS=4` this is roughly 80 `claude -p` sessions/day, up from ~24.
- **Open:** Serialized at concurrency 1, ten issues is 4-10 hours of wall clock, so the
  clock may bind before the cap does. Raising concurrency needs file-disjointness
  awareness first (ASK-225).
- **Scar:** The live plist and its repo template disagreed for hours (10 vs 4) because the
  template edit was never committed. A spend control in two places diverges silently.
- **Date:** 2026-08-02
- **Revisit:** When ASK-225 lands, or when a day actually hits the cap

### RULE-011: Fix The Detector, Not Its Call Sites
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** ASK-122 reported 11 dead scripts in one instance. Ten were alive. Rather
  than annotate 22 call sites to quiet the report, the checker was fixed once in the
  skeleton, fleet-wide.
- **Reason:** The alternative ships 22 workarounds for one defect and leaves the same false
  positive live in every other repo. Measured after: that instance went 44 -> 16 UNWIRED,
  and four other instances improved with none regressing.
- **Date:** 2026-08-02
- **Revisit:** Permanent

### RULE-012: A Reviewer On Different Weights Is The Default For Detector-Shaped Changes
- **Origin:** [USER-DIRECTED]
- **Decision:** When a change alters what a checker REPORTS across the fleet, the review
  round goes to a model from outside the implementing agent's own family.
- **Reason:** On PR #74, two same-lab review rounds passed a test suite that a third-party
  reviewer then broke on purpose and found nearly unbound. It returned three blockers the
  same-lab rounds had walked past, two of them in the coordinator's own code. The earlier
  fallback round's single major was something a measurement had already surfaced twenty
  minutes before. Context independence is real; model independence is a different thing and
  only one of them was present.
- **Open:** The reviewer script knows only two engines. A third is a change to the gating
  contract and earns its own issue.
- **Date:** 2026-08-02
- **Revisit:** Permanent

### RULE-013: An Unavailable Optional Tool Is Never Escalated As A Blocker
- **Origin:** [USER-DIRECTED]
- **Decision:** Before reporting any tool outage as blocking, read the fallback path in the
  calling script first. Report the outage; do not convert it into a founder decision.
- **Reason:** Founder's correction, verbatim: "codex is not a blocker, it never has been,
  stop hiding behind it." Both the coordinator and the implementing agent had reported
  "buy credits" as a founder-held blocker on a PR that was never gated on it. The calling
  script documents the outage path in a comment two lines long. Two more claims that night
  had the same shape: a computed roll-up read as policy, and a permission denial on an
  agent's own tool call reported as a property of the object.
- **Date:** 2026-08-02
- **Revisit:** Permanent

### RULE-014: A Gate Is Not Trusted Until It Has Been Observed Failing
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** Every new gate, lint, or safety test ships with a negative self-test: the
  guard is run against a deliberately broken input and seen RED before its green counts.
- **Reason:** One session produced five root classes of defect, and four of them had a
  guard that had never been falsified. The fleet's single required review check went green
  twice for a reviewer that had explicitly declined to start, because an empty findings
  block fell through a severity ladder to APPROVE. Nine tests written reproducer-first
  survived having both of the fixes they guarded deleted.
- **Date:** 2026-08-02
- **Revisit:** Permanent

### RULE-015: An Unenumerated Coverage Claim Is A Defect, Not A Style Note
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** A claim that a rule holds across N sites must be produced by a mechanical
  enumeration, never by recall. Comments stating a count are refreshed from a grep or
  removed.
- **Reason:** The single structure behind all five of the session's root classes. The
  clearest instance: a commit consolidating an exclusion behind one predicate, whose message
  read "one predicate for all three consumers", shipped with a fourth consumer. Three of the
  five classes had a written rule naming the correct behaviour that nobody executed, one of
  them on its fourth recurrence, which is the argument for gates over prose made by the
  prose failing four times in one night.
- **Open:** Five gates filed (ASK-213/314/315/316/317). Until they land this rule is prose,
  and prose is what failed.
- **Date:** 2026-08-02
- **Revisit:** When all five gates are built
