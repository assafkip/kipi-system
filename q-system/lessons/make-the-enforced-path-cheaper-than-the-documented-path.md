---
id: make-the-enforced-path-cheaper-than-the-documented-path
kind: methodology
title: Make the enforced path cheaper than the documented path
date: 2026-11-10
---

Symptom: a team or system is explicitly designed to turn important rules into executable checks, yet rulings that should become code keep landing as written guidance instead. The guidance reads as enforced. Nothing actually enforces it.

Two causes usually work together. Fix both.

1. Guards that check for words instead of executables.
A common meta-guard says: block any 'this is enforced' claim unless an enforcement word appears nearby, such as hook, script, test, lint, validator, or code change. This binds the check to the nearest proxy, a word, rather than to the property you care about, which is an executable that exists, is wired in, and fires.

Such a guard is worse than none. It trains writers to add the magic word next to a prose rule, so the rule passes review and looks enforced.

The fix is to verify the referent, not the vocabulary:
- Require the claim to name a concrete artifact by identifier.
- Check mechanically that the artifact exists.
- Check that it is registered or wired into the place it must run, whether that is a hook config, CI job, or pre-commit list.
- Ideally, check that a known-bad input makes it fail.
- If any of these cannot be verified, label the claim 'advisory', not 'enforced'.
- Audit your existing gates for this same proxy-binding flaw. Gates are rarely held to the standard they impose.

2. Recording is the cheapest legal action, and coding is the most expensive.
Compare the two paths.

The prose path:
- one write to a guidance, memory, or config file
- no review
- picked up automatically next time

The code path:
- an isolated branch or worktree
- a PR
- slow CI
- capped review rounds
- a merge restricted to one person
- a deploy that merges don't trigger
- sometimes a wiring step that fails outright in some environments

Under that gradient, rational actors write prose and move on. The 'make it hard-coded' requests stall in the queue.

The fix is to reshape the cost gradient deliberately:
- Price prose up. A new rule that claims to be binding must either link a merged, wired check or be filed as an open item with an owner and due date. Unenforced rules expire or are listed visibly as debt.
- Price code down. Provide a template or generator for the common enforcement shapes. Give small guard changes a fast lane with lighter review. Remove single-person bottlenecks for low-risk merges. Make deploy follow merge automatically. Ensure the wiring path works in every target environment, and test that wiring itself.
- Measure it. Track rulings marked 'must be enforced' against those that have a verified, wired check, and track the age of each gap. A growing gap means the gradient still favors prose.

General principle: if the system's goal is 'rules become code', then both the verification gates and the effort gradient must point toward code. A gate that accepts a description of enforcement, combined with a process where describing is cheap and implementing is costly, will reliably produce well-described, unenforced rules.
