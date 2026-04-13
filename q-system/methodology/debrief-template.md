# Conversation Debrief Template

This template is the **primary workflow** of the Q Entrepreneur OS. Use it after every conversation with a VC, CISO, design partner, advisor, or potential recruit.

## How to Trigger

Use `/q-debrief [person]` to start a debrief session.

## Raw Source Archival (before extraction)

Before running the template, save the raw conversation transcript:
1. Write the full transcript to `sources/YYYY-MM-DD-person-name.md`
2. Frontmatter: `date`, `person`, `company`, `workflow: debrief`
3. This file is immutable after creation. Never edit it.
4. Proceed with extraction only after the source is saved.
5. Retention: 90 days. Sources older than 90 days auto-deleted on 1st of month via /q-wrap.

## Predict-First Step (before founder describes conversation)

After reading the person's history but BEFORE the founder describes what happened, generate predictions:

```markdown
### Pre-debrief predictions (system-generated):
Based on [person]'s profile, history, and current positioning:

**Likely objections surfaced:**
1. [predicted objection from objections.md]
2. [predicted objection]
3. [predicted objection]

**Likely topics discussed:**
1. [predicted topic based on their interests/role]
2. [predicted topic]
3. [predicted topic]

**Predicted relationship outcome:** [warmer / cooler / same] because [reason]
```

After the founder describes the conversation, compare predictions to reality. Log accuracy to `memory/working/predictions.jsonl` with type `debrief_prediction`. Wrong predictions reveal gaps in canonical files.

## The Template

```markdown
## Debrief: [Person] — [Role] — [Company] — [Date]

### What resonated (exact phrases they used):
-

### What confused them:
-

### What they pushed back on:
-

### What they asked that I couldn't answer:
-

### Misclassification risk (did they think we're X?):
-

### Next step agreed:
-

### Changes to canonical positioning (if any):
-

### Proof gaps exposed:
-

### Signal quality check (failure patterns):
- Did they describe a CURRENT pain or agree with a THEORETICAL problem?
- What do they DO TODAY to solve it (even badly)? Tool/process named:
- Did they express willingness to CHANGE their current process?
- Did they identify specific BLOCKERS to trying something new?
- How many minutes before they "got it" without me explaining? (under 2 = hot, 2-5 = warm, 5-10 = lukewarm, 10+ = educating)
- Next step cost: Does the next step cost THEM something (time, access, internal advocacy) or just me (send deck, send link)?
- Signal level: [Thesis nod / Pain confirmed / Switching intent / Usage commitment]
```

## Signal Quality Routing

After completing the signal quality check, update the prospect's record:
- **Thesis nod:** Log insight, but do NOT invest more time until they show pain. Move to passive monitoring.
- **Pain confirmed:** Priority follow-up. Ask switching friction questions in next conversation.
- **Switching intent:** Top priority. Move toward DPA conversation. This is a real prospect.
- **Usage commitment:** Activate immediately. This is a design partner.

If 3+ consecutive conversations land at "thesis nod" with no "pain confirmed," revisit whether the problem resonates at the operational level or only at the strategic level. That's a category timing signal.

## Strategic Implications Analysis

After the template extraction and signal quality check, run this analysis. Cross-reference what was learned against ALL canonical files, recent debriefs, and current system state. Each lens produces a concrete recommendation or "no change needed."

### 1. Product implications
- Does this conversation validate or invalidate any assumption in `current-state.md`?
- Did they describe a workflow, pain point, or use case we haven't captured?
- Should we reprioritize what we build next? If yes, state the specific change.
- Did they reveal an integration, input type, or output target we're missing?
- **Action:** [specific product change / add to roadmap / no change needed]

### 2. Positioning and narrative implications
- Did our primary metaphor and category language land or miss with this persona type?
- Should we adjust how we describe this to SIMILAR people (not just this person)?
- Is there a new angle, frame, or proof point that should enter the narrative?
- Do any of these need updating: talk tracks, boilerplate, one-pager, deck copy, website language?
- Cross-check: does this conversation confirm or contradict patterns from the last 3-5 debriefs?
- **Action:** [specific narrative change + which files to update / no change needed]

### 3. Demo and materials implications
- Did the demo land? What part confused them or failed to impress?
- Should the demo flow change for this persona type?
- Are there missing demo scenarios that would have answered their questions better?
- Do any leave-behinds (deck, one-pager, follow-up email template) need updating based on what they asked?
- **Action:** [specific demo/materials change / no change needed]

### 4. Sales motion and outreach implications
- Did we learn something about how this TYPE of person buys, decides, or evaluates?
- Should we change our approach for similar personas in the pipeline?
- Did we learn about their internal dynamics (who else needs to be convinced, what budget path looks like)?
- Should any outreach templates, DM sequences, or engagement strategies change?
- **Action:** [specific sales motion change / no change needed]

### 5. Pattern detection (cross-conversation)
- Read the last 5 entries in `my-project/progress.md` and recent entries in `canonical/feedback-log.md`
- Is a pattern forming across 3+ conversations that we haven't acted on?
- Are we hearing the same objection repeatedly without improving our answer?
- Are we consistently losing people at the same point in the explanation?
- Is a persona type responding differently than expected?
- **Action:** [pattern identified + recommended response / no pattern detected]

### 6. Competitive intelligence
- Did they mention a competitor, alternative approach, or "we already do this with X"?
- Did they describe a build-vs-buy consideration?
- Update `my-project/competitive-landscape.md` and `marketing/assets/competitive-one-liners.md` if new intel.
- **Action:** [specific competitive update / no change needed]

### 7. Network expansion
- Who did they MENTION by name, role, or team? ("You should talk to our VP of Detection Engineering", "My friend at Palo Alto deals with this")
- Any warm intro opportunities? Add to `my-project/relationships.md` as a lead with source tagged.
- Any new companies or teams revealed that fit our ICP?
- **Action:** [specific people/companies to add + intro path / no new leads]

### 8. Pricing and packaging signals
- Did they react (positively or negatively) to the budget path or pricing model?
- Did they reveal procurement process, budget owner, approval chain, or budget cycle timing?
- Did they compare our pricing to something they already pay for?
- **Action:** [pricing/packaging insight to log / no signal]

### 9. Timing signals
- Are they ready now, next quarter, next year?
- What's driving their timeline? (compliance deadline, recent incident, budget cycle, leadership change, renewal window)
- Is there an external forcing function we should track?
- **Action:** [timing insight + any calendar reminder to set / no signal]

### 10. Founder performance (self-coaching)
- What did I say that clearly worked? (capture the exact framing for reuse)
- What fell flat or got a confused reaction?
- What should I prepare better for next time with this persona type?
- Was there a moment I should have gone deeper but didn't?
- **Action:** [specific prep item for similar future conversations / performed well]

### 11. Pipeline applicability
- Scan `my-project/relationships.md` and active pipeline for similar personas.
- Who else in the pipeline would this learning apply to RIGHT NOW?
- What should change in upcoming conversations with those people?
- **Action:** [specific people + what to change in their approach / no similar personas active]

### 12. Documentation and content implications
- Should this conversation generate a content piece? (LinkedIn post, Medium article, case study angle)
- Did they use language or describe a problem that would resonate with our audience if we wrote about it?
- Should any content in the pipeline be updated or reprioritized based on this?
- **Action:** [specific content idea + add to Content Pipeline / no change needed]

### Implications summary
List only the actions (skip "no change needed" items):
```markdown
| Area | Change | Priority | Files to update |
|------|--------|----------|-----------------|
| [area] | [specific change] | [now/this week/backlog] | [file paths] |
```

If 3+ areas need changes from a single conversation, flag it as a **high-signal conversation** in `my-project/progress.md`.

## Design Partner Conversion (MANDATORY for practitioner/CISO conversations)

> This section closes the loop from conversation to action. Skip ONLY for pure VC conversations where design partnership isn't relevant.

After every conversation with a practitioner, CISO, or potential design partner, answer these questions:

### 1. What did they describe that {{YOUR_PRODUCT}} can do RIGHT NOW?
- Read `my-project/current-state.md` "What Works Today" section
- Map their specific pain points to current capabilities
- Be honest: what works, what partially works, what doesn't exist
- Output a concrete list: "You described X. {{YOUR_PRODUCT}} can do Y today."

### 2. What's the gap between what they need and what exists?
- What output format do they need? (BigQuery, Splunk, Snowflake, KQL, etc.) Do we support it?
- What input types do they need? (threat intel PDFs work. IR postmortems, red team reports = not built)
- What integration do they need? (Slack, Jira, their specific tools)
- What's the smallest build that would close the gap enough to be useful?

### 3. What can we offer them THIS WEEK?
Design one of these (pick the lowest-friction option):
- **Test run:** "Send me 2-3 reports you're already working with. I'll run them through and send back the output. You tell me if it's useful." (Zero integration, zero commitment, 10 min of their time)
- **Recorded demo of their scenario:** Take the exact scenario they described in the conversation, run it through {{YOUR_PRODUCT}}, record a 2-min video showing their use case with real-looking data. Send on their preferred channel.
- **Output sample:** Generate a sample artifact in their format (their query language, their tool) from a public report relevant to their domain. Send it with: "This is what {{YOUR_PRODUCT}} would produce for your team from [public report]. Is this useful?"

### 4. What's the ask?
Write the actual message (copy-paste ready) that the founder sends to convert this conversation into a design partner trial. Rules:
- Lead with THEIR scenario, not our pitch. "You described [X]. I built [Y]. Want to try it?"
- Make the ask tiny. Not "become a design partner." Just "send me a report and I'll show you what comes back."
- Specify what they get (output artifacts) and what it costs them (10 min to send reports, 10 min to review)
- Include the channel (Signal, email, Slack, LinkedIn DM - whatever they prefer)
- No pressure. No timeline. Just "want to see it?"

### 5. Follow-up trigger
- When should we follow up if they don't respond? (Default: 5 days)
- What's the next escalation? (Send the recorded demo unprompted? Ask for a different scenario?)
- Add to Notion Actions DB with Energy: People, Time: 15 min

### Output format:
```markdown
DESIGN PARTNER CONVERSION - [Person] - [Date]

What they described: [their scenario in 1-2 sentences]
What {{YOUR_PRODUCT}} does today that matches: [specific capabilities]
Gap: [what's missing, how hard to close]
Offer: [test run / recorded demo / output sample]
Build needed: [none / small / significant]

MESSAGE (copy-paste, send via [channel]):
"[the actual message]"

Follow-up: [date] if no response
```

## Processing Instructions

After completing the template and implications analysis, route insights to canonical files:

### 1. Resonance phrases → `canonical/talk-tracks.md`
- Capture their exact words, not your paraphrase
- Tag with persona type (CISO, SOC lead, VC, etc.)
- If a phrase is new and strong, add it to the appropriate talk track variant

### 2. Pushback / Objections → `canonical/objections.md`
- Check if the objection already exists
- If new: add with persona tag, crisp answer, proof required, what NOT to say
- If existing: update the response if you found a better answer
- Tag source: "[Person] — [Date]"

### 3. Confusions / Misclassification → `canonical/objections.md`
- Log the specific misclassification (e.g., "thought we were a detection tool")
- Add the reframing language that worked (or note that you need better language)
- Flag in `my-project/current-state.md` if this is a recurring pattern

### 4. Unanswered questions → `canonical/discovery.md`
- Add as a gap question with context on who asked and why it matters
- Prioritize: will this question come up again? With whom?

### 5. Contact context → `my-project/relationships.md`
- Update or create the person's entry
- Include: what they care about, what they pushed back on, next step
- Update relationship status (cold → warm → active → design partner → investor)

### 6. Graph knowledge base → `memory/graph.jsonl`
- Extract entity-relationship triples from the conversation
- Log: who works where, who introduced whom, what they care about, what they objected to, what resonated
- Example triples:
  ```jsonl
  {"s":"Person Name","p":"works_at","o":"Company","t":"2026-03-12"}
  {"s":"Person Name","p":"cares_about","o":"cross-silo coordination","t":"2026-03-12"}
  {"s":"Person Name","p":"objected_to","o":"why not just use Claude","t":"2026-03-12"}
  {"s":"Person Name","p":"resonated_with","o":"nervous system metaphor","t":"2026-03-12"}
  {"s":"Connector Name","p":"introduced","o":"Person Name","t":"2026-03-12"}
  ```

### 7. Positioning changes → `my-project/current-state.md`
- If the conversation revealed that a claim is invalid, update "claimed but unproven"
- If the conversation validated something new, move it to "validated (by whom)"

### 8. Market intelligence → `canonical/market-intelligence.md`
- If the person shared market trends, competitor experiences, buyer process details, or how their team evaluates tools, route to the appropriate section
- If they used language to describe the problem that's different from ours, capture it in Problem Language
- If they mentioned competitors or alternatives, capture in Competitive Intel
- If they described procurement, budget, or timeline details, capture in Buyer Process
- Tag source: "[Person] - [Date] - conversation"

### 9. Competitive landscape → `my-project/competitive-landscape.md`
- If the person mentioned a competitor, alternative approach, or "we already do this with X"
- If they described build-vs-buy considerations
- Update competitive one-liners in `marketing/assets/competitive-one-liners.md` if new intel

### 10. Network expansion → `my-project/relationships.md`
- Add any new people mentioned by name as leads with source tagged
- Log intro paths: "[Person] mentioned [New Lead] as someone we should talk to"
- Add to graph.jsonl: `{"s":"Person","p":"suggested_intro","o":"New Lead","t":"date"}`

### 11. Progress log → `my-project/progress.md`
- Log that the debrief happened, key takeaway, and any canonical changes made

## Quality Checklist

- [ ] Every section of the template is filled (or explicitly marked "N/A - not discussed")
- [ ] Resonance phrases are verbatim (their words)
- [ ] Objections have a proposed response (even if imperfect)
- [ ] Next step is concrete (not "follow up" - specify what, when, via what channel)
- [ ] Misclassification risk is assessed even if none detected ("None - they understood SLCP framing")
- [ ] Signal quality check completed with signal level assigned
- [ ] If "thesis nod" only: noted, no over-investment in follow-up
- [ ] If "pain confirmed" or higher: switching friction questions queued for next conversation
- [ ] Strategic implications analysis completed (all 12 lenses)
- [ ] Implications summary table produced with specific actions and file paths
- [ ] Any "now" priority implications are executed immediately (file updates made)
- [ ] Any "this week" implications are added to Notion Actions DB
- [ ] All routing to canonical files is complete
- [ ] **Design Partner Conversion completed** (for practitioner/CISO conversations only):
  - [ ] Current capabilities mapped to their specific pain (read current-state.md)
  - [ ] Gap identified (output format, input type, integration)
  - [ ] Copy-paste message drafted and shown to founder
  - [ ] Follow-up Action created in Notion Actions DB (Energy: People, Time: 15 min, due in 5 days)
- [ ] **Loop opened for every outbound action from this debrief:**
  - [ ] If next step involves sending something (deck, email, DM): `python3 q-system/.q-system/loop-tracker.py open <materials_sent|email_sent|dm_sent> "Person" "What was sent" "" "" "Follow-up text..."`
  - [ ] If next step involves waiting for their response: `python3 q-system/.q-system/loop-tracker.py open debrief_next_step "Person" "What we're waiting for"`
  - [ ] If design partner conversion message was sent: `python3 q-system/.q-system/loop-tracker.py open dp_offer_sent "Person" "DP offer context" "" "" "Follow-up if no reply..."`
  - [ ] Debrief is NOT complete until all outbound actions have corresponding loops opened
  - [ ] If VC-only conversation: marked "N/A - VC conversation"
- [ ] **Ripple verification complete:**
  - [ ] Every canonical file edit logged via `python3 q-system/.q-system/scripts/changelog-write.py <file> debrief "<summary>" --source "<person> - <date> - conversation"`
  - [ ] `python3 q-system/.q-system/scripts/ripple-verify.py q-system/canonical/changelog.md YYYY-MM-DD`
  - [ ] If exit 0: done
  - [ ] If exit 1 (soft gate): address missing targets or log skip reason in changelog. Do NOT block debrief completion.
