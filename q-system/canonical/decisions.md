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
