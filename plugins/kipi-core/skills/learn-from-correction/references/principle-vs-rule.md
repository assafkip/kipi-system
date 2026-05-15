# Principle vs. Rule

This is the load-bearing guardrail of the `learn-from-correction` skill. Read it before proposing any edit.

## The core idea

A rule says **what to do**. A principle says **how to think**.

Rules overfit. They turn every correction into another switch-case in a decision tree. After a year of corrections, the skill is a brittle mess of "if user mentions X, say Y" that breaks the moment a situation appears that the rule did not anticipate.

Principles transfer. They give the agent a frame of reference that handles cases nobody wrote down explicitly. A principle is durable because it tells the agent *how to evaluate*, not what to output.

## Rough test

Read the proposed text out loud. If it would still hold in 3 different situations that look unlike the source correction, it is a principle. If it only makes sense in the exact shape of the source correction, it is a rule.

## Concrete examples

### Bad (rule)

> Never mention pricing in the first sentence of a reply.

Why it's a rule: it's a hard "never," it's about output mechanics, it does not transfer to a situation where pricing is the actual topic.

### Better (principle)

> When the user is venting or asking for help, lead with what they need. Pricing belongs in a conversation about value, not at the top of a reply where it reads as a pitch.

Why it works: it tells the agent how to evaluate the *shape of the user's message*. The same principle correctly handles the case where the user explicitly asks about pricing - lead with that, because that's what they need.

### Bad (rule)

> If the founder edits a comment to be shorter, output shorter comments from now on.

Why it's a rule: it generalizes from one mechanical signal (length change) without naming the cause.

### Better (principle)

> Aim for one idea per reply. If the agent draft mixes acknowledgement, opinion, and a CTA, the founder will rewrite to drop two of them. Pick the most important one before drafting.

Why it works: it names *why* shorter is better (one idea, not three). The agent can apply it to a long reply that has one substantive idea (keep) and a short reply that hedges across three (still cut).

### Bad (rule)

> When Codex flags "non-goals empty," remind the founder to fill in the non-goals section.

Why it's a rule: reactive, mechanical, narrow.

### Better (principle)

> A PRD without non-goals has implicitly unlimited scope. The Skeptic should ask: "what is this PRD deliberately not solving?" before accepting scope as complete.

Why it works: shifts the agent from a checklist response ("did you write non-goals?") to an evaluative stance ("is the scope of this work actually constrained?").

## The 5-future-situations test

Before proposing a principle, list 5 future situations it should apply to. They must be plausibly distinct.

If you cannot name 5 distinct situations, the correction is probably context-specific, not a missing principle.

If your 5 situations are all minor variations of the source correction, the proposal is still a rule in disguise.

## Where principles live in a skill

Principles belong in sections like:
- **"Anti-patterns the X watches for"** - heuristics about what to refuse or flag
- **"Constraints"** or **"How to think about X"** - evaluative frames
- **"When NOT to invoke this"** - the inverse principle, scoping the skill's reach

Rules belong in sections like:
- **"Banned words"** - deterministic checks the linter enforces
- **"Required sections"** - structural checklist items

Both have a place. The mistake is putting a rule where a principle belongs (creates brittle behavior) or putting a principle where a rule belongs (creates non-enforceable wishes).

## When a rule is actually the right answer

Sometimes the founder genuinely wants deterministic behavior - emoji bans, named filler phrases that are always forbidden, specific frontmatter fields that must be present. Those are rules and should stay rules.

The test: if the founder wants the agent to refuse output that violates the constraint, regardless of context, it is a rule. Put it in a banned-list or a pre-publish check. Do not soften it into a principle.

The mistake to avoid is the inverse: turning a judgment call (which is what most corrections are) into a hard rule.

## Source

The principle-vs-rule distinction comes from Warp's writeup on building Buzz, their agent for responding to mentions across social platforms. The exact failure mode they describe: early Buzz had a long checklist of rules ("if X then Y") that turned the prompt into a brittle decision tree. They moved to durable principles ("be helpful, not defensive") and the agent improved on cases nobody had explicitly written rules for.
