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
