# State Model - Progress Tracking & Guardrails

---

## Progress Tracking Across Modes

### State Variables (tracked in `my-project/progress.md`)

| Variable | Source | Updated by |
|----------|--------|-----------|
| Last mode executed | Progress log | Every mode switch |
| Canonical files changed | Progress log | Every session |
| Open gap questions | `canonical/discovery.md` | CALIBRATE mode |
| Unresolved objections | `canonical/objections.md` | DEBRIEF / CALIBRATE |
| Relationships needing follow-up | `my-project/relationships.md` | PLAN mode |
| Proof gaps | `canonical/objections.md` | DEBRIEF mode |
| Unvalidated claims | `my-project/current-state.md` | CALIBRATE mode |

### Health Indicators

**Healthy state:**
- Debriefs happen within 24 hours of conversations
- `relationships.md` has no entries with "last contact" older than 2 weeks for active relationships
- `objections.md` has crisp answers for all known objections
- `current-state.md` accurately reflects what's demo-able today
- `talk-tracks.md` is updated with language from recent conversations

**Stall indicators:**
- No debrief logged in >1 week despite conversations happening
- Multiple `{{NEEDS_UPDATE}}` placeholders in `relationships.md`
- Objections in `canonical/objections.md` without crisp answers for >2 weeks
- `current-state.md` hasn't been reviewed in >2 weeks
- Same gap questions in `discovery.md` open for >3 weeks

**Regression indicators:**
- Outputs that passed misclassification check now fail (positioning drift)
- Talk tracks that worked are no longer landing (audience changed or language staled)
- Relationships that were warm have gone cold without explanation
- Claims in outputs that aren't in `current-state.md` (overclaiming creep)

---

## Stall / Regression Handling

### When stall is detected:
1. Surface the stall indicator to the founder explicitly
2. Propose a specific `/q-calibrate` session to address it
3. Prioritize: debriefs first, then relationship follow-ups, then gap questions

### When regression is detected:
1. Flag the regression with specific evidence
2. Revert outputs to last-known-good canonical state
3. Run `/q-calibrate` to understand what changed
4. Do NOT ship regressed outputs

---

## Misclassification Detector (ENFORCED)

> **Rule:** If any output resembles a common misclassification from the founder's "What We Are NOT" list, ENFORCE reframing.

### Detection Triggers (if any of these appear, flag for review):

| Trigger | Example | Reframe |
|---------|---------|---------|
| Product described as {{MISCLASSIFICATION_1}} | "{{YOUR_PRODUCT}} does X" | Reframe using correct positioning from talk-tracks.md |
| Only one output type mentioned | "We produce X" | Show the full range of outputs/value |
| Wrong audience assumed | "{{WRONG_AUDIENCE}} uses {{YOUR_PRODUCT}}" | Correct to actual target audience |
| Described as "a dashboard" or "a UI" | "Users log into {{YOUR_PRODUCT}}" | Clarify actual delivery model |
| "AI-powered" without qualifier | "Our AI generates X" | Add specifics about how AI is actually used |

### Enforcement Protocol:
1. **Detect:** Any of the triggers above appear in an output
2. **Flag:** Mark the specific phrase or section
3. **Reframe:** Apply the corrected language
4. **Verify:** Re-check the full output for consistency
5. **Log:** Note the misclassification pattern in `my-project/progress.md` for pattern tracking

---

## Ambiguity Preservation Rule (ENFORCED)

> **Rule:** If the founder hasn't validated a claim, mark it as `{{UNVALIDATED}}` rather than asserting it.

### When to apply:
- Any claim about capabilities not in `my-project/current-state.md` "What works today" section
- Any market size, growth rate, or competitive claim without a source
- Any quote or validation not explicitly confirmed by the named person
- Any future capability described as if it exists today
- Any statistical claim without attribution

### Markers:
- `{{UNVALIDATED}}` - claim made but not confirmed by external party
- `{{NEEDS_PROOF}}` - claim that will be challenged and needs supporting evidence
- `{{NEEDS_FOUNDER_INPUT}}` - question that only the founder can answer
- `{{NEEDS_RESEARCH}}` - claim that can be verified through research
- `{{NEEDS_UPDATE}}` - placeholder for information that should exist but hasn't been provided

### What NOT to do:
- Do NOT assert unvalidated claims as facts
- Do NOT remove ambiguity markers to make outputs "cleaner"
- Do NOT guess at answers to fill placeholders
- Do NOT assume validation by one person extends to claims they didn't specifically confirm
