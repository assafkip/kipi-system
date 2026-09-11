---
id: when-two-rules-collide-say-so-before-you-pick
kind: methodology
title: When two rules collide, say so before you pick
date: 2026-08-17
---

A silent resolution of a rule conflict is itself the defect, separate from whichever side you picked.

## The shape

Two instruction sources both apply to the same action. One says the work needs a specific owner or reviewer. The other says don't invoke that path unless asked. Both are live. You pick one, drop the other, and ship. Nobody who set those rules learns a conflict existed, so nobody gets the chance to say "use the other one this time." Either pick was defensible. Not surfacing was not.

## How to work

**1. Name the conflict out loud, then proceed.**
When two applicable rules point in opposite directions: state both, state which you're following, state what you're dropping, and continue. One sentence. This is not a permission ask and it is not a blocker. It restores the choice to whoever owns the rules without stopping the work.

The tell you missed one: you reasoned about a rule and then didn't mention it in the output. If it was worth weighing, it was worth naming.

**2. Verify against the goal, not against the checks that happen to exist.**
Running every available check and reporting "all clean" answers "did it violate anything measurable?" It does not answer "is this good?" Those are different questions and only one of them is the goal. Automated checks describe properties of an artifact. They cannot tell you what the artifact IS or whether it should exist.

Before reporting clean, ask the goal question in plain words and answer it separately from the check results. If you can't answer it yourself, that is the signal to route it to whoever can, not to substitute the green checks for the answer.

**3. A warning that names the defect is a finding, not noise.**
Advisory severity describes the tool's confidence, not the importance of what it found. Read the warning text, not the severity label. If a warning's own words restate the actual problem, it has escalated itself; summarizing it as "advisory, moving on" overrules a correct detection with a formatting convention.

Decision rule: for each warning, write one line on what it claims and whether that claim is true here. "Warn-level" is not that line.

**4. Check whether you already wrote the lesson.**
The same failure repeating within a short window, once in a pipeline and once in a human review of that pipeline, means the fix was recorded as knowledge and never converted into a step someone performs. A lesson that lives only in a document about a past incident does not run. Move it into the sequence: a required question in the review, a field in the report, a gate that cannot be summarized past.

## Success test

The output states which rules conflicted and how it was resolved; the report separates "passed the checks" from "answers the goal"; every warning has a one-line verdict against it.
