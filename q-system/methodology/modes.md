# Operating Modes

The Q Entrepreneur OS operates in **4 independent modes**. There is no sequential dependency. The founder switches between modes as the situation demands.

---

## Mode 1: CALIBRATE

**When to use:** After conversations, feedback, market changes, or when canonical understanding feels stale or drifted.

**Files to read:**
- `my-project/current-state.md`
- `canonical/discovery.md`
- `canonical/objections.md`
- `my-project/competitive-landscape.md`

**Files to update:**
- `my-project/current-state.md` - update "what works today" if capabilities changed
- `canonical/discovery.md` - add new validated answers; add new gap questions
- `my-project/competitive-landscape.md` - update substitute bucket intelligence
- `canonical/objections.md` - flag new misclassification risks

**Quality checks:**
- [ ] No basics re-asked (check `canonical/discovery.md` first)
- [ ] New questions target genuine gaps, not already-known information
- [ ] Ambiguities preserved with `{{UNVALIDATED}}` markers, not guessed at
- [ ] Misclassification risks explicitly flagged

---

## Mode 2: CREATE

**When to use:** Need a specific output - talk track, email, slide text, diagram, memo, one-pager.

**Files to read:**
- `canonical/talk-tracks.md` - proven language to reuse
- `canonical/objections.md` - anticipated pushback for the audience
- `my-project/current-state.md` - what can be claimed today
- `my-project/founder-profile.md` - founder context and constraints
- `canonical/research.md` - supporting evidence and analogies (if exists)

**Files to update:**
- `output/drafts/` - ad-hoc outputs go here
- `canonical/talk-tracks.md` - if new proven language emerges

**Quality checks:**
- [ ] Output is "drop-in ready" (usable in a deck, email, or doc without editing)
- [ ] No claims beyond `current-state.md` without `{{UNVALIDATED}}` marker
- [ ] Anti-misclassification guardrails passed
- [ ] Audience-specific (not generic)

---

## Mode 3: DEBRIEF

**When to use:** After ANY conversation with an investor, prospect, design partner, advisor, or potential recruit.

**This is the highest-priority workflow.**

**Files to read:**
- `methodology/debrief-template.md` - use the full template
- `my-project/relationships.md` - existing context on this person
- `canonical/objections.md` - check if objection is new or known

**Files to update:**
- `my-project/relationships.md` - update contact entry with new context
- `canonical/objections.md` - add new objections with crisp answers
- `canonical/talk-tracks.md` - add resonance phrases that landed
- `my-project/progress.md` - log the debrief
- `my-project/current-state.md` - if positioning changes are flagged

**Quality checks:**
- [ ] Debrief template fully completed (no empty sections without explanation)
- [ ] Objections routed to `canonical/objections.md` with persona tag
- [ ] Resonance phrases captured verbatim (their words, not ours)
- [ ] Next step is concrete and actionable (not "follow up")
- [ ] Misclassification risk assessed
- [ ] `relationships.md` entry updated

---

## Mode 4: PLAN

**When to use:** Deciding what to do next - who to reach out to, what to build, what to test, what proof to generate.

**Files to read:**
- `my-project/relationships.md` - who needs follow-up, who's gone cold
- `canonical/objections.md` - which proof gaps are most urgent
- `my-project/current-state.md` - what's possible today
- `my-project/progress.md` - what's already been decided

**Files to update:**
- `my-project/progress.md` - log decisions and prioritized actions

**Quality checks:**
- [ ] Actions are prioritized (not a flat list)
- [ ] Each action has a clear "why now" tied to a relationship, objection, or proof gap
- [ ] No waterfall plans - propose 2-3 next moves, not a 12-week roadmap
- [ ] Blockers identified with workarounds where possible

---

## Modifier: RESEARCH MODE

**Not a mode -- a constraint layer.** Can be active during any mode. Toggle on with `/q-research`, off with "exit research mode."

When active, every factual claim must cite a source (local file, web search result, named paper). Uses a 4-level source cascade to keep token costs low. See the research-mode skill in kipi-core for full rules.

Useful during:
- **CALIBRATE** -- verifying claims before writing them to canonical files
- **CREATE** -- grounding investor briefs, decks, or technical content in cited sources
- **PLAN** -- validating market assumptions with evidence before committing to a direction
