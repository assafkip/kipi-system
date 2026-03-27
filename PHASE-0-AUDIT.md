# Phase 0 Audit: Kipi System Separation

> Date: 2026-03-25
> Status: AWAITING FOUNDER REVIEW
> Gate: Do not proceed to Phase 1 until this audit is reviewed and approved.

---

## 1. Repo Inventory & Git State

| Repo | Location | Branch | Clean? | Remote | Type |
|------|----------|--------|--------|--------|------|
| kipi-system | `/Desktop/kipi-system/` | main | Yes | github.com/assafkip/kipi-system | Skeleton |
| KTLYST q-ktlyst | `/Desktop/KTLYST_strategy/q-ktlyst/` | (parent repo) | Dirty | KTLYST_strategy repo | Instance (most developed) |
| kipi-pipeline-plugin | `/Desktop/kipi-pipeline-plugin/` | main | Dirty (24 agents deleted) | github.com/assafkip/kipi-pipeline-plugin | Plugin (TO ELIMINATE) |
| q-founder-os | `/Desktop/q-founder-os/` | main | Clean | github.com/assafkip/kipi-system (same!) | Instance (template) |
| car-research | `/Desktop/car-research/` | main | Dirty | github.com/assafkip/kipi-system (same!) | Instance (specialized) |
| q-education | `/Desktop/q-education/` | N/A | N/A (not git) | None | Instance (lightweight) |
| Pure_spectrum_Q | `/Desktop/Pure_spectrum_Q/` | main | Dirty | github.com/assafkip/Pure-spectrum-Q | Custom (not skeleton-based) |
| q-investigate-osint-bot | `/Desktop/q-investigate-osint-bot/` | main | Clean | github.com/assafkip/q-investigate-osint-bot | Custom (not skeleton-based) |

**Critical finding:** q-founder-os and car-research both point to the kipi-system remote. They're clones, not subtrees. This means `git pull` in those repos pulls kipi-system changes directly. That simplifies Phase 4 but means we need to be careful about their diverged state.

**Scope adjustment:** Pure_spectrum_Q and q-investigate-osint-bot are NOT skeleton-based instances. They're custom systems with different architectures. They should NOT be subtree consumers of kipi-system. That reduces the instance count from 6 to 4:
1. q-founder-os (template, ready for setup)
2. car-research (specialized fork)
3. q-education (lightweight, no git)
4. KTLYST q-ktlyst (most developed)

---

## 2. Skeleton (kipi-system) Assessment

**Grade: A-. Well-sanitized, production-ready skeleton.**

~280 files. All properly templated with `{{}}` placeholders. No instance-specific data detected. Recent commit history shows intentional sanitization ("Sanitize KTLYST-specific data from skeleton").

### Issues Found

| Issue | Severity | Fix |
|-------|----------|-----|
| `build_schedule` MCP tool replaces old build-schedule.sh (deleted) | Minor | Verify MCP tool works |
| `my-project/progress.md` only 7 lines | Minor | Add session log schema |
| Agent files diverged from KTLYST (different naming, missing newer agents) | Major | Phase 1 reconciliation needed |

### What the Skeleton Has That KTLYST Doesn't

The skeleton has been independently developed in some areas:
- Frontmatter on agent files (name, description, model, maxTurns)
- Budget gate and service line tagging in engagement hitlist
- `00-session-bootstrap.md`, `02-x-activity.md`, `03-content-intel.md`, `03-publish-reconciliation.md`, `04-founder-brand-post.md`, `04-marketing-health.md`, `05-connection-mining.md`, `06-client-deliverables.md` - agents that don't exist in KTLYST

### What KTLYST Has That the Skeleton Doesn't

- `_cadence-config.yaml` (YAML format, not just .md)
- `_scoring-config.md`
- `00b-energy-check.md`, `00c-canonical-digest.md`
- `01-data-ingest.md`, `01b-content-metrics.md`, `01c-copy-diff.md`
- `03-dp-pipeline.md`, `03b-linkedin-notifications.md`, `03c-prospect-activity.md`
- `04-kipi-promo.md`, `04-tl-content.md`, `04a-tl-manifest.md`
- `05b-copy-review.md`
- `07b-outreach-queue.md`
- Anti-AI scanner (`scan-draft.py`)
- Voice layering framework
- Content manifest gate
- Adversarial reviewer
- Verification harnesses (`verify-bus.py`, `verify-orchestrator.py`)

**Decision needed:** The two agent sets have diverged. We need to pick a canonical set and reconcile. See Section 5.

---

## 3. KTLYST Instance Assessment

~180+ files. 30% generic (skeleton material), 55% instance-specific, 15% mixed.

### Instance-Specific (stays in KTLYST, never goes to skeleton)

| Directory | Content |
|-----------|---------|
| `canonical/` | KTLYST positioning, CISO pains, re-breach thesis, research verdicts, ai-native-founder framing |
| `my-project/` | Assaf's profile, KTLYST current-state, 80+ relationships, competitive landscape, progress |
| `seed-materials/` | 50+ debriefs (VCs, CISOs, design partners) |
| `output/` | All generated content, deliverables, meeting prep, call scripts |
| `marketing/assets/` | KTLYST boilerplate, Assaf's bios, stats sheet, proof points, competitive one-liners |
| `marketing/content-themes.md` | 8 KTLYST-specific themes (CNS, Re-breach, Prevention Engineering, etc.) |
| `marketing/editorial-calendar.md` | KTLYST's rolling 4-week cadence |

### Generic (should flow back to skeleton)

| Item | Notes |
|------|-------|
| Agent pipeline agents (structure) | Generic job descriptions, bus I/O, token budgets |
| orchestrator (deleted, was deprecated) | Generic pipeline execution (now handled by agent pipeline) |
| review-pipeline (deleted, content moved to server.py docstrings) | Content review pipeline |
| `bus-to-log.py`, `session-start.py` | Generic utilities |
| `scan-draft.py` | Generic anti-AI scanner (checks for banned phrases, not KTLYST-specific) |
| `verify-bus.py`, `verify-orchestrator.py` | Generic verification harnesses |
| Marketing templates (email, LinkedIn, X, Medium) | Generic structure |
| Memory directory structure | Generic architecture |
| Methodology (debrief template, modes) | Generic frameworks |

### MIXED Files (need separation - see Section 5)

| File | Generic Part | Instance Part |
|------|-------------|---------------|
| Agent `05-engagement-hitlist.md` | Pipeline logic, action types, output schema, energy compression | CISO pain anchoring (line 39), hardcoded `q-ktlyst/` path (line 44), NIS2 sectors |
| Agent `04-tl-content.md` | Thought leadership generation framework | KTLYST-specific topic anchors |
| Agent `05-lead-sourcing.md` | Sourcing pipeline, Apify integration | Vertical-specific search queries |
| `marketing/brand-voice.md` | Channel voice structure (LinkedIn vs X vs email) | KTLYST banned words, anti-patterns |
| `marketing/content-guardrails.md` | Pre-publish checklist structure | KTLYST-specific claim rules |
| `marketing/README.md` | Marketing system architecture | KTLYST "Head of Marketing" framing |
| `commands.md` | Command definitions and workflows | KTLYST-specific references |

---

## 4. Plugin Assessment

**kipi-pipeline-plugin: CONFIRMED REDUNDANT. Safe to eliminate.**

| What it provides | Where it already lives |
|-----------------|----------------------|
| `agents/` (symlink) | Points to KTLYST q-ktlyst agents |
| `templates/` (symlink) | Points to KTLYST marketing templates |
| `skills/q-morning` | Already in kipi-system `.claude/commands/` |
| `skills/q-debrief` | Already in kipi-system `.claude/commands/` |
| `skills/q-wrap` | Already in kipi-system `.claude/commands/` |
| `scripts/audit-morning.py` | Already in kipi-system `q-system/` |
| `kipi_build_schedule` MCP tool | Replaced old build-schedule.sh (deleted) |

The plugin adds zero unique value. It's a packaging layer with symlinks. Every capability already exists in the instance or skeleton.

**One thing to port:** `build_schedule` functionality is now in the kipi-mcp server as the `kipi_build_schedule` MCP tool. The old `build-schedule.sh` has been deleted.

---

## 5. Architectural Decisions

### 5A. Mixed File Separation Pattern

**Decision: Option (b) - Skeleton agent with instance config overlay**

How it works:
- Skeleton agent files contain the generic pipeline logic, I/O schema, token budgets, action types
- Each agent reads an instance config file at runtime for domain-specific rules
- Instance config lives in `canonical/` or `my-project/` (already instance-specific directories)

Example for `05-engagement-hitlist.md`:

```
# In the skeleton agent file:
## Domain-specific targeting (READ FROM INSTANCE CONFIG)
Read `{{QROOT}}/canonical/engagement-playbook.md` for:
- Target persona pain anchoring rules
- Industry-specific messaging constraints
- Gain/loss framing preferences
```

```
# In KTLYST's canonical/engagement-playbook.md:
## Target Persona Rules
- CISO/security leader targets: Anchor in three pains:
  (1) AI board pressure, (2) inefficiency/translation time, (3) intel they can't deploy
- Use GAIN framing: "here's what you gain" not "here's what you lose"
- No fear language.
```

**Why not the other options:**
- (a) Skeleton + overlay file merge is fragile. Two files defining the same agent is confusing.
- (c) Reading instance config at runtime IS what we're doing, but via existing canonical files, not a new config format.

**The pattern:** Agents read `canonical/engagement-playbook.md`, `canonical/verticals.md`, `my-project/founder-profile.md` for domain rules. These files are already instance-specific. No new mechanism needed - just ensure agents reference these files instead of hardcoding domain knowledge.

### 5B. Voice Skill Separation

| Layer | Goes to | Contains |
|-------|---------|----------|
| **Framework** (skeleton) | `kipi-system/.claude/skills/founder-voice/SKILL.md` | Layer loading matrix, anti-AI scanner rules, register-by-channel structure, quality checks |
| **Framework** (skeleton) | `kipi-system/q-system/scripts/scan-draft.py` | Generic anti-AI scanner script (banned phrase detection, pattern matching) |
| **Content** (instance) | `{instance}/.claude/skills/founder-voice/references/voice-dna.md` | Founder's specific voice DNA, words they use/avoid, opening/closing patterns |
| **Content** (instance) | `{instance}/.claude/skills/founder-voice/references/writing-samples.md` | Real writing samples from the founder |
| **Content** (instance) | `{instance}/.claude/skills/founder-voice/references/gotchas.md` | Instance-specific voice gotchas (if exists) |

The skeleton's `voice-dna.md` and `writing-samples.md` are already empty templates with instructions. This is correct. The KTLYST instance populates them with Assaf's voice. No structural change needed.

### 5C. CLAUDE.md Extension Pattern

**Decision: Layered import with `@` references**

```
# Instance CLAUDE.md (e.g., KTLYST_strategy/CLAUDE.md)

# KTLYST Labs - Founder Operating System

## Base System
@q-system/CLAUDE.md

## Instance Identity
- Company: KTLYST Labs
- Product: Cross-Team Nervous System for threat intelligence
- Stage: Pre-seed, $2.5M raise

## Instance-Specific Rules
### Three CISO Pains (ENFORCED)
...

### Anti-Misclassification (populated)
KTLYST is NOT: a SIEM, a SOAR, a TIP, a detection tool
KTLYST IS: Cross-Team Nervous System, prevention engineering platform
```

The skeleton `CLAUDE.md` uses `@q-system/CLAUDE.md` to import the behavioral rules. The instance `CLAUDE.md` imports the skeleton AND adds instance-specific sections. Claude Code's `@` import handles the layering.

**Rule:** Instance CLAUDE.md MUST NOT duplicate skeleton rules. It only adds:
- Instance identity (company, product, stage)
- Populated anti-misclassification lists
- Domain-specific enforced rules (CISO pains, vertical targeting)
- Populated language rules (use/avoid lists)

### 5D. Propagation Workflow

**Decision: `kipi_update` MCP tool that pulls to all instances at once**

Manual `git subtree pull` per instance is error-prone and will be forgotten. The `kipi_update` MCP tool (in kipi-mcp) handles this. It replaces the old `kipi-update.sh` shell script (now deleted).

Configuration reference for the MCP tool:
- Skeleton remote: `https://github.com/assafkip/kipi-system.git`
- Skeleton branch: `main`
- Subtree prefix: `q-system` (or instance-specific)
- Registered instances are managed via `kipi_new_instance` / `kipi://instances`

**Workflow:**
1. Make improvement in kipi-system skeleton, commit + push
2. Use the `kipi_update` MCP tool to pull into all instances
3. If conflicts arise (instance modified a skeleton file), resolve per-instance
4. To push a generic improvement FROM an instance back to skeleton: `kipi_push_upstream` MCP tool

**Frequency:** Manual trigger. Run after meaningful skeleton improvements, not after every commit.

---

## 6. Agent Reconciliation Plan

The skeleton and KTLYST have diverged. Here's the file-by-file mapping for agents:

### Agents in BOTH (need reconciliation - pick best version)

| Agent | Skeleton Version | KTLYST Version | Pick |
|-------|-----------------|----------------|------|
| `_auto-fail-checklist.md` | Has frontmatter | No frontmatter | Merge: KTLYST content + skeleton frontmatter |
| `_cadence-config.md` | Exists | Exists | Compare and merge |
| `00-preflight.md` | Has frontmatter | No frontmatter | Merge |
| `01-calendar-pull.md` | Has frontmatter | No frontmatter | Merge |
| `01-gmail-pull.md` | Has frontmatter | No frontmatter | Merge |
| `01-notion-pull.md` | Has frontmatter | No frontmatter | Merge |
| `01-vc-pipeline-pull.md` | Has frontmatter | No frontmatter | Merge |
| `02-meeting-prep.md` | Has frontmatter | No frontmatter | Merge |
| `02-warm-intro-match.md` | Has frontmatter | No frontmatter | Merge |
| `03-linkedin-dms.md` | Has frontmatter | No frontmatter | Merge |
| `03-linkedin-posts.md` | Has frontmatter | No frontmatter | Merge |
| `04-post-visuals.md` | Has frontmatter | No frontmatter | Merge |
| `04-signals-content.md` | Has frontmatter | No frontmatter | Merge |
| `04-value-routing.md` | Has frontmatter | No frontmatter | Merge |
| `05-engagement-hitlist.md` | Has budget gate, service lines | Has CISO anchoring, anti-AI scan | Merge: skeleton structure + move CISO rules to instance config |
| `05-lead-sourcing.md` | Has frontmatter | No frontmatter | Merge |
| `05-lead-sourcing-chrome.md` | Has frontmatter | No frontmatter | Merge |
| `05-loop-review.md` | Has frontmatter | No frontmatter | Merge |
| `05-pipeline-followup.md` | Has frontmatter | No frontmatter | Merge |
| `05-temperature-scoring.md` | Has frontmatter | No frontmatter | Merge |
| `06-compliance-check.md` | Has frontmatter | No frontmatter | Merge |
| `06-positioning-check.md` | Has frontmatter | No frontmatter | Merge |
| `07-synthesize.md` | Has frontmatter | No frontmatter | Merge |
| `08-visual-verify.md` | Has frontmatter | No frontmatter | Merge |
| `09-notion-push.md` | Has frontmatter | No frontmatter | Merge |
| `10-daily-checklists.md` | Exists | Exists | Merge |
| `step-orchestrator.md` | Exists | Exists | Merge |

### Agents ONLY in Skeleton (keep or drop?)

| Agent | Purpose | Decision |
|-------|---------|----------|
| `00-session-bootstrap.md` | Session initialization | KEEP - useful generic capability |
| `02-x-activity.md` | X/Twitter activity pull | KEEP - KTLYST should add this |
| `03-content-intel.md` | Content intelligence | KEEP - generic content analysis |
| `03-publish-reconciliation.md` | Track what's published | KEEP - generic content ops |
| `04-founder-brand-post.md` | Personal brand content | KEEP - generic founder capability |
| `04-marketing-health.md` | Marketing system health | KEEP - generic dashboard |
| `05-connection-mining.md` | Network expansion | KEEP - generic LinkedIn growth |
| `06-client-deliverables.md` | Client work tracking | KEEP - useful for consulting instances |

### Agents ONLY in KTLYST (port to skeleton as generic?)

| Agent | Purpose | Decision |
|-------|---------|----------|
| `_cadence-config.yaml` | YAML config format | PORT - better than .md for config |
| `_scoring-config.md` | Lead scoring rules | PORT - generic capability |
| `00b-energy-check.md` | AUDHD energy assessment | PORT - generic AUDHD support |
| `00c-canonical-digest.md` | Canonical file summary | PORT - generic capability |
| `01-data-ingest.md` | Unified data collection | PORT - generic orchestration |
| `01b-content-metrics.md` | Content performance | PORT - generic marketing |
| `01c-copy-diff.md` | Copy change tracking | PORT - generic quality gate |
| `03-dp-pipeline.md` | Design partner pipeline | PORT - generic sales capability |
| `03b-linkedin-notifications.md` | LinkedIn notification scan | PORT - generic LinkedIn capability |
| `03c-prospect-activity.md` | Prospect behavior tracking | PORT - generic pipeline capability |
| `04-kipi-promo.md` | Self-promotion content | RENAME to `04-product-promo.md`, PORT |
| `04-tl-content.md` | Thought leadership content | PORT - generic content capability |
| `04a-tl-manifest.md` | Content manifest gate | PORT - generic quality gate |
| `05b-copy-review.md` | Adversarial copy review | PORT - generic quality gate |
| `07b-outreach-queue.md` | Outreach staging | PORT - generic pipeline capability |

---

## 7. Other Instance Status

### q-founder-os
- Clone of kipi-system (same remote)
- Clean state, `{{SETUP_NEEDED}}` in founder-profile
- **Action:** Convert to subtree consumer. Currently a direct clone, so we need to restructure. The q-system/ content IS the skeleton.

### car-research
- Clone of kipi-system (same remote) + untracked car-specific files
- Dirty state (CLAUDE.md modified, car-negotiator skill added)
- **Action:** Commit car-specific changes first. Then convert to subtree consumer. Car-specific content (car-spec.json, car-negotiator skill, Voss playbook) stays outside the subtree prefix.

### q-education
- NOT a git repo. Has skeleton structure but missing `steps/` and `commands.md`
- Founder profile is POPULATED (Assaf + school context)
- **Action:** Initialize git. Add kipi-system as subtree. Lightweight instance (no full agent pipeline needed).

### Pure_spectrum_Q
- Custom consulting engagement hub. NOT skeleton-based.
- **Action:** EXCLUDE from subtree plan. Different architecture, different purpose.

### q-investigate-osint-bot
- Standalone OSINT system. NOT skeleton-based.
- **Action:** EXCLUDE from subtree plan. Self-contained, already released.

---

## 8. Subtree Prefix Decision

**Decision needed:** What directory in each instance holds the skeleton?

Option A: `q-system/` (current structure in most instances)
- Pro: Matches existing layout, minimal moves
- Con: In KTLYST, the q-system content is under `q-ktlyst/`, not `q-system/`

Option B: `.kipi/` (hidden directory)
- Pro: Clear separation, won't confuse users
- Con: New convention, requires path updates everywhere

**Recommendation:** Option A (`q-system/`). For KTLYST, the subtree prefix would be `q-ktlyst/` since that's the existing directory name. Each instance can pick its own prefix. The propagation script handles the mapping.

---

## 9. Execution Order Summary

```
Phase 0: THIS DOCUMENT (audit)           <- YOU ARE HERE
Phase 1: Update skeleton (reconcile agents, port KTLYST improvements)
Phase 2: Restructure KTLYST as subtree consumer
Phase 3: Eliminate plugin
Phase 4: Update other instances (q-founder-os, car-research, q-education)
Phase 5: Document and verify
```

---

## 10. Questions for Founder Before Phase 1

1. **Agent reconciliation strategy:** The skeleton has 8 agents KTLYST doesn't, and KTLYST has 15 agents the skeleton doesn't. Do we merge everything into one canonical set? Or keep the skeleton lean and let KTLYST add its extras as instance-specific agents?

2. **Frontmatter convention:** The skeleton uses YAML frontmatter on agent files (name, model, maxTurns). KTLYST doesn't. Should we standardize on frontmatter for all agents?

3. **Pure_spectrum_Q and q-investigate:** Confirmed exclusion from subtree plan? They're architecturally different.

4. **q-education:** Should it get the full agent pipeline, or stay lightweight (just canonical + marketing, no morning routine)?

5. **Subtree prefix for KTLYST:** Use `q-ktlyst/` as the subtree prefix (matching current directory name), or rename to `q-system/` for consistency?

6. **build_schedule:** Now implemented as the `build_schedule` MCP tool in kipi-mcp. The old shell script is no longer needed.
