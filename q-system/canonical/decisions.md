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

### RULE-2026-07-06-A: Fleet organizes under top-level personas; Cole owns ALL GTM
- **Origin:** [USER-DIRECTED]
- **Decision:** ~48 flat projects reorganize under top-level PERSONA folders (a partner per line of work), migrated by the reversible `scripts/persona-reorg.py` (dry-first, per-persona manifest, kipi-check-gated). Cole (`cole-gtm`) is the single GTM brain for the whole fleet: any GTM asset in any instance moves into Cole. Done: `random-stuff-ideas`→`cole-gtm` + 9 GTM projects nested; ASK's `products/` → `cole-gtm/products/`; ASK core → `consulting` persona (Pure_spectrum_Q + 4_points_consulting + Alice cascaded); Cole↔ASK bridge retired both sides.
- **Reason:** Flat pile had no home per line of work; GTM was scattered across ASK + Cole. One brain per function; GTM consolidates in Cole.
- **Date:** 2026-07-06
- **Revisit:** After all personas migrated; then re-evaluate whether the type-grouped fleet-map folds into the persona view.

### RULE-2026-07-06-B: Post-consolidation dedup — one engine per job in Cole
- **Origin:** [USER-DIRECTED]
- **Decision:** Merging ASK's `products/` into Cole exposed duplicates; consolidated. ARCHIVED to `~/projects/_archive/` (reversible): `ai-news-podcast` (dead TTS podcast, superseded by the live NotebookLM `gtm/scripts/podcast/`), `founder-signal-engine` (dormant subset of `competitive-analysis`), the `x/youtube/pinterest` posters + jobs (didn't work), and `refill-engine` (only fed the posters). KEPT: `distribution-engine` (ships repos), the video catalog, `competitive-analysis` (canonical signal superset), `signal-desk` / `vc-signals` / `reddit-build-radar` (distinct jobs). PODCAST (decided 2026-07-06 — PARK, do not merge): live `gtm/scripts/podcast/` and public OSS `projects/notebooklm-daily-podcast/` share only a small STABLE mechanism (dedup.py 4-line diff, make_podcast.sh 7-line diff); their show-specific files diverged hard (fetch_sources 260, build_email_html 377) into two real products. A full merge = reconciling diverged code against a LIVE show for modest payoff; a shared-lib extract = coupling a live branded show to a public repo — both worse than the copy-paste. Boundary declared instead: live = source of truth, repo = sanitized export, sync-on-change note added to the two shared files.
- **Reason:** Founder: no multiple engines doing the same thing / multiple versions of one thing.
- **Date:** 2026-07-06
- **Revisit:** When the podcast one-engine merge is scheduled; and if a shared Reddit-collector lib is extracted (3 copies today).

### RULE-2026-07-06-C: micro-saas persona — anchor-less bucket pattern
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** The 6 $29 micro-SaaS repos (cheapcheck, briefonce, authorvoice, feedbackpin, runreceipts, shipgate) now cascade under a new top-level `micro-saas/projects/` bucket. Named `micro-saas` (not `products`) to avoid overloading `cole-gtm/products/` (the content machine). Unlike cole-gtm/consulting there was no anchor repo to rename, so `persona-reorg.py` gained a `create=True` parent mode: it CREATES an empty bucket + `projects/` + `.gitignore` + a roster `CLAUDE.md`, moves the 6 in, rewrites live self-ref paths (13 refs / 8 files). Zero registry / launchd / bridge / cluster-rule touches — pure Tier-0. Reversible via `persona-reorg-manifest-micro-saas.json`. Also: `consulting` added to the tool's `MIGRATED` set so `run_apply` exits early on a re-run (it was migrated 2026-07-06 but omitted from that set).
- **Reason:** Continues RULE-2026-07-06-A (fleet under personas). Anchor-less personas (Products, Dev-tools, Intel) have no brain repo; the bucket pattern is how they migrate.
- **Date:** 2026-07-06
- **Revisit:** After all personas migrated (per RULE-2026-07-06-A).

### RULE-2026-07-06-D: intel persona + two tool hardenings (runs/ skip, worktree repair)
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** kipi-investigations (registry `investigations`), ktlyst-extract, facebook-ads-library-search cascade under a new anchor-less `intel/projects/` bucket. 1 registry rewrite, 1 live self-ref (`.codex/hooks.json`), 0 launchd/cron/bridge. The KTLYST product you sell (`ktlyst-hub/product`) also belongs in `intel` but stays put until the ktlyst-hub split. Two `persona-reorg.py` hardenings surfaced and landed: (1) `/runs/` added to the forensic path-skip list — 86 facebook-ads scraper capture files + run-manifests are point-in-time evidence, not live code, so the rewriter leaves them intact; (2) a two-step `git worktree repair` after each move — kipi-investigations had 3 nested codex agent worktrees whose absolute-path linkage a move breaks; a bare repair only fixes the main tree, so the tool now re-links each moved worktree at its new path (verified: bare repair left 3 `prunable`, explicit-path repair cleared them).
- **Reason:** Continues RULE-2026-07-06-A. A threat-intel shop's run captures are evidence — falsifying their paths is worse than stale internal refs. Orphaned worktrees are a silent breakage a deterministic step prevents.
- **Date:** 2026-07-06
- **Revisit:** After all personas migrated (per RULE-2026-07-06-A).

### RULE-2026-07-06-E: dev-tools persona — cleanest Tier-0 batch; kipi-system stays meta
- **Origin:** [CLAUDE-RECOMMENDED -> APPROVED]
- **Decision:** The 7 shippable/OSS plugin + dev-tool repos (claude-focus, fable-discipline, kipi-rca, huntkit, tokentrim, founder-voice-kit, interview-coach-public) cascade under a new anchor-less `dev-tools/projects/` bucket (`create=True`, same pattern as micro-saas/intel). Recon proved pure Tier-0: 0 registry, 0 launchd (plist name AND body scan), 0 linked worktrees, 0 bridge. Only rewrite was 3 tokentrim `_setup_*.py` self-refs (absolute build paths inside the moved dir). `kipi-system` is deliberately excluded — it stays top-level/meta because every persona depends on the factory (plan open-decision #3); nesting it under one persona is wrong. Reversible via `persona-reorg-manifest-dev-tools.json`; `dev-tools` added to the tool's `MIGRATED` set (re-apply refused, verified exit 3). *(Superseded in part by RULE-F: interview-coach-public later re-homed to micro-saas — dev-tools now holds 6.)*
- **Reason:** Continues RULE-2026-07-06-A. Dev-tools is the anchor-less bucket pattern with zero automation deps — the low-risk proof that the pattern generalizes cleanly.
- **Date:** 2026-07-06
- **Revisit:** After all personas migrated (per RULE-2026-07-06-A).

### RULE-2026-07-06-F: interview-coach-public re-homed dev-tools -> micro-saas
- **Origin:** [USER-DIRECTED]
- **Decision:** `interview-coach-public` moves out of `dev-tools/projects/` into `micro-saas/projects/`. It is a friend's shipped product (the $29 micro-SaaS class), not an OSS dev-tool plugin. Zero-dep move (0 self-refs / registry / launchd / worktree). Both manifests were rewritten so each bucket's rollback stays honest: the dev-tools manifest drops the record; the micro-saas manifest gains it pointed at the project's TRUE origin (`~/projects/interview-coach-public`), so a micro-saas rollback restores it there, not to dev-tools. PERSONAS map + both rosters + fleet-map updated to match.
- **Reason:** Persona = kind of work, not licensing. It ships to a user like cheapcheck/briefonce, so it belongs with the products.
- **Date:** 2026-07-06
- **Revisit:** With the interview-coach consolidation (5 variants -> 1, fleet-map open item #1).
