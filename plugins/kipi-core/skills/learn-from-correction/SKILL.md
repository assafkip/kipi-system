---
name: learn-from-correction
description: "Propose a principle edit to a skill or persona file based on a (agent_output, human_output) correction pair. Outputs a proposal markdown for human review - never auto-edits the target file."
---

# Learn From Correction

You take a correction (what an agent proposed vs. what the human actually did) and propose a principle edit to the skill/persona file that should have caught it. The proposal goes to `q-system/output/skill-proposals/` for the founder to review and merge through normal git flow.

This skill exists because the best prompt today is not the best prompt a month from now. Corrections the founder is already making (rewrites of agent drafts, anti-pattern additions to Skeptic, copy edits) carry the signal needed to keep skills sharp - but only if something captures that signal as a durable principle.

**Before writing anything, read `references/principle-vs-rule.md`.** The guardrails there are load-bearing: principles transfer, rules overfit. A correction turned into a rule produces a brittle decision tree. The same correction turned into a principle reshapes how the agent reasons.

## Constraints (ENFORCED)

- **Never edit the target skill file directly.** Output is always a proposal markdown in `q-system/output/skill-proposals/`. The founder reviews, edits, and merges via normal git flow so Codex review fires on the diff (same gate as any other code change).
- **One correction at a time.** If the founder hands you a batch of corrections, process them sequentially. Each one gets its own proposal file or its own section. Do not bundle unrelated corrections into one principle.
- **Always include the source correction in the proposal.** The founder needs to verify your interpretation. Quote the agent output, the human output, and your inferred diff.
- **If the correction does not generalize, say so.** Not every correction maps to a missing principle. Some are one-off context. The honest answer is sometimes: "this is a one-off, no principle change recommended."

## Inputs

The founder provides three pieces of information. They can come inline in the conversation, as file paths, or as a Phase A proposal markdown (which already has the correction shape built in).

- **agent_output**: what the agent proposed (the draft, the answer, the recommendation).
- **human_output**: what the human actually did (the final post, the rewrite, the accepted Codex finding).
- **target_skill**: which skill should learn from this correction. If not provided, ask the founder. Defaults to whichever skill governs the output type (founder-voice for written copy, skeptic for PRD adversarial review, etc.).

## Workflow

Follow these 7 steps in order. Each step has an "if you cannot answer" exit ramp; use it instead of guessing.

### 1. Identify what changed

Diff the agent output against the human output. State the concrete difference. Quote both sides. If the diff is purely cosmetic (whitespace, ordering with no semantic change), exit with "no principle change recommended."

### 2. Ask why

Name the underlying cause, not the symptom. "Founder shortened the comment" is a symptom. "Agent draft included a CTA the founder removed because the post was venting, not a sales opportunity" is a cause. If you cannot name the cause without speculation, ask the founder one direct question and wait.

### 3. Zoom out to the pattern

Would this apply beyond this one case? Run the test: imagine 5 future situations the agent might face. Would this correction shape the right behavior in 3+ of them? If not, exit with "context-specific, no principle change recommended."

### 4. Check against existing principles

Read the target skill file. Does an existing principle cover this case? Three possible verdicts:

- **Sharpen**: existing principle is close but ambiguous. Propose a sharper restatement.
- **Add**: no existing principle covers the case. Propose a new bullet with clear placement.
- **Delete**: existing principle pushed the agent toward the wrong behavior. Propose removing or revising it.

If multiple principles overlap and the new correction touches the seam, propose a merge.

### 5. Write as a principle, not a rule

A rule says "what to do." A principle says "how to think." See `references/principle-vs-rule.md` for the test. If your proposed text reads like a switch-case ("if X then Y"), rewrite it as a heuristic ("when X, the question is Y").

### 6. Place it in the right section

Skills have structure. Anti-patterns go in the anti-patterns section. Workflow steps go in the workflow section. Read the target skill's table of contents first. If the right section does not exist, propose adding it - and explain why an existing section was not the right home.

### 7. Output the proposal

Write the proposal to `q-system/output/skill-proposals/{target_skill_name}-{ISO-date}.md`. The format is below. Print the path to the founder so they can open it.

## Proposal file format

```markdown
# Principle proposal - {target_skill_name}

Generated: {ISO timestamp}
Target skill: {path to SKILL.md}

## Source correction

**Agent output:**
{quote}

**Human output:**
{quote}

**Inferred diff:**
{concrete description}

## Inferred cause

{one or two sentences naming why the human diverged}

## Pattern test

Five future situations this might apply to:
1. ...
2. ...
3. ...
4. ...
5. ...

Verdict: {applies to N/5}. {one sentence}

## Existing principles touched

{list relevant existing bullets from the target skill, with line refs}

## Proposed edit

**Action:** {add | sharpen | delete | merge}

**Target section:** {section heading in the target skill}

**Proposed text:**
{the new principle, written as a heuristic}

**Why a principle and not a rule:**
{one sentence connecting to references/principle-vs-rule.md}

## How to merge

1. Open {target skill path}
2. Apply the proposed edit in the named section
3. Commit through normal git flow
```

## When this skill returns "no principle change recommended"

It is honest to refuse. The four refusal reasons, in priority order:

1. **Cosmetic diff only.** No semantic change between agent and human.
2. **Context-specific correction.** The diff makes sense only for this one situation; it would not shape the right behavior in 3+ future cases.
3. **Insufficient information.** The founder did not give enough to infer cause without speculation, and the founder did not respond to the clarifying question.
4. **Existing principle already covers it.** The agent failed to apply a principle that already exists. The correction is a reminder to follow existing guidance, not a new principle.

Write the refusal as a short proposal file (1-2 paragraphs) so the founder can see the analysis ran. Refusing silently looks like the skill never executed.

## Anti-patterns this skill watches for in itself

- **Turning corrections into rules.** If the proposed text starts with "always," "never," or "if X then Y," it is a rule. Rewrite as a principle.
- **Over-generalizing from one case.** One correction is not a pattern. The 5-future-situations test (Step 3) is mandatory, not optional.
- **Skipping the source quote.** Without the source quote, the founder cannot verify interpretation. The proposal is incomplete.
- **Auto-applying the edit.** Even when the proposal feels obviously right, the founder reviews and merges manually. The skill writes proposals, not commits.

## Related

- `plugins/prd-os/scripts/propose_skeptic_antipatterns.py` - Phase A consumer of this pattern, specialized to PRD findings.
- `plugins/prd-os/personas/skeptic.md` - one target this skill commonly proposes edits to.
- `plugins/kipi-core/skills/founder-voice/SKILL.md` - another common target (anything written for human readers).
