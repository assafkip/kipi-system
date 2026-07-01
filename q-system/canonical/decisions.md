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

## Active Decisions

### RULE-2026-05-27-A: Design partner arrangement with Ally for kipi-investigations
- **Origin:** [USER-DIRECTED]
- **Decision:** Build kipi-investigations prototype free for Ally as design partner. She supplies reports + design feedback. Loop in Ethan (FBI) once she validates.
- **Reason:** Ally pulled the wedge customer profile from the conversation herself ("I would pay for this"). She's responsive, has real pain (her own Obsidian board), and brings warm channel to Ethan + FBI orbit. Free-for-design-partner is correct positioning, but log so it doesn't drift to "expected to keep building free."
- **Date:** 2026-05-27
- **Revisit:** After prototype validated (Ally's first reaction to handala report ingestion) — re-decide on pricing/scope for v2.

### RULE-2026-05-27-B: kipi-investigations is a new instance, not a kipi-core feature
- **Origin:** [USER-DIRECTED]
- **Decision:** Build kipi-investigations in a new folder (`~/projects/kipi-investigations`) via `kipi new`, not as a feature inside kipi-system.
- **Reason:** Different ICP, different deliverables, different lifecycle. Skeleton stays clean; instance carries investigation-specific scaffolding. Aligns with kipi multi-instance pattern (consulting, multi-instance cluster, etc.).
- **Date:** 2026-05-27
- **Revisit:** Permanent

### RULE-2026-05-27-C: Obsidian graph is the v1 visualization, defer custom UI
- **Origin:** [USER-DIRECTED]
- **Decision:** Ship Obsidian vault export as the visualization layer for v1. No custom web UI until Ally (and later customers) validate the Obsidian-as-deliverable workflow.
- **Reason:** Ally explicitly said the graph in Obsidian is what she wants. Custom UI is two-hour Claude work but adds maintenance surface. Ship what's wanted, not what's possible.
- **Date:** 2026-05-27
- **Revisit:** After 3+ design partners or first paying customer signal demand for a hosted view.

### RULE-2026-05-27-D: Sanitize all customer reports before any external demo
- **Origin:** [USER-DIRECTED]
- **Decision:** Iranian NVE reports + handala reports from Ally are NOT to be raised with FBI, Tova, or any external party. Sanitized derivatives only.
- **Reason:** Ally's explicit ask. Trust preservation overrides demo opportunity.
- **Date:** 2026-05-27
- **Revisit:** Permanent (extends to all design partner data)

### RULE-2026-06-30-A: Instance-specific automation lives at the repo root, never inside q-system/
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** Scripts an instance adds for itself (launchd runners, etc.) go in a repo-root dir (e.g. `<instance>/automation/`), NOT inside the synced `q-system/` tree. Each bundle ships a committed `install-launchd.sh`.
- **Reason:** `kipi update`'s `rsync --delete` deleted the fractional-cxo income scanners from inside `q-system/` (2026-06-24); they exited 127 silently for 6 days. Repo-root is never fanned and stays git-tracked (recoverable + clobber-proof).
- **Date:** 2026-06-30
- **Revisit:** Permanent

### RULE-2026-06-30-B: kipi update = warn + preserve tracked instance-only files (never silent-delete)
- **Origin:** [USER-DIRECTED]
- **Decision:** Before `rsync --delete`, the updater flags tracked instance-only files (ones the skeleton git never tracked) it would remove, snapshots+restores them, and warns. It does not abort and does not delete silently.
- **Reason:** Founder chose warn+preserve over abort/warn-only: no silent data loss, update still proceeds. Skeleton-intended deletions still propagate (discriminator = never-skeleton-tracked).
- **Date:** 2026-06-30
- **Revisit:** Permanent

### RULE-2026-06-30-C: Every kipi launchd job is watched + rebuildable
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** `launchd-health-check.py` Slack-pings on any `com.kipi.*` job exiting non-zero (09:30/21:30); every owned job has a committed installer.
- **Reason:** The two 2026-06-24 failure modes were silent death and lost `~/Library/LaunchAgents`. Cover both. A prompt can't watch launchd; a job can.
- **Date:** 2026-06-30
- **Revisit:** Permanent

### RULE-2026-06-30-D: Cross-instance learning shares EVERY learning; de-identify by scrub, not recurrence
- **Origin:** [USER-DIRECTED]
- **Decision:** The autonomous auto-learn loop shares every instance's learning with all instances (dropped the prior "2+ unrelated instances" rule). Confidentiality is handled by SCRUBBING client data, not by requiring recurrence. Fully autonomous, daily, Slack on change.
- **Reason:** Founder redesign: recurrence-gating missed most of the value; a real HOW-only lesson has no client data anyway. Inverts `prd-cross-instance-learning-2026-06-19`.
- **Date:** 2026-06-30
- **Revisit:** When a scrub miss is observed, or the fleet composition changes materially.

### RULE-2026-06-30-E: A lesson publishes only through a fail-closed client-data gate
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** `lessons_scrub.py` is deterministic hard code: a distilled lesson publishes only if the scrubbed text has zero client-data signals (tokens, paths, emails, URLs, registry codenames) AND an LLM semantic pass confirms no residual real entity. Anything else is HELD (surfaced, never published).
- **Reason:** A cross-client data leak is irreversible for a threat-intel shop; it cannot rest on model judgment. Over-holding is a safe false positive; leaking is not.
- **Date:** 2026-06-30
- **Revisit:** Permanent (tighten the roster/patterns as needed; never loosen fail-closed).
