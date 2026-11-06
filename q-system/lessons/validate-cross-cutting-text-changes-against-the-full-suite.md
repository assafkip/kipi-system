---
id: validate-cross-cutting-text-changes-against-the-full-suite
kind: pattern
title: Validate Cross-Cutting Text Changes Against the Full Suite
date: 2026-11-06
---

When a change alters wording, naming, or any string-matching rule, treat it as cross-cutting rather than local, because the same text can appear in assertions, fixtures, snapshots, seed data, and documentation as well as in application code.

How to apply:

1. Classify the change before sizing it. Ask whether the edit affects literal text or a rule that matches text. If yes, assume unknown consumers exist outside the directory you edited, regardless of how few lines changed.
2. Search the whole repository for the old text and the pattern that produces it, including test directories, fixture and snapshot files, data files, configuration, and docs. Grep is cheaper than a review cycle.
3. Run the complete test suite, not just the subset near the change. For slow suites, run the fast full pass locally and let the longer stages run before merge rather than after.
4. Fix every failure inside the same change. Do not split unrelated fixture updates into follow-up work; a partially applied text rule leaves the repository in a state where neither the old nor the new convention is reliable.
5. Re-read each failure before mechanically updating it. A broken assertion sometimes reveals that the new rule is wrong or too broad, not that the test is stale.
6. Record the verification you performed in the change description, so reviewers can see that scope was checked rather than assumed.

Why it pays off: the cost of a full-suite run is measured in minutes, while the cost of a missed consumer is a second review cycle, re-queued pipelines, and reviewer context switching, which can exceed the original work by an order of magnitude. The expected cost is lowest when verification scope matches blast radius, not line count.

Generalization: apply the same rule to renames, log and error message changes, public identifier changes, lint and formatting rule additions, and shared constant edits. Any change whose effect is discovered by matching rather than by typed references deserves full-suite verification before merge.
