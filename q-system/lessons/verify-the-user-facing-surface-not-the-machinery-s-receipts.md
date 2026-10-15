---
id: verify-the-user-facing-surface-not-the-machinery-s-receipts
kind: methodology
title: Verify the user-facing surface, not the machinery's receipts
date: 2026-10-04
---

Pattern: a task is reported done because the pipeline's own signals are green (job stamped ok, suites passing, change merged, review receipt filed), while the surface the end user actually reads was never inspected and still showed stale or false content.

Why it happens:
- Done is defined by internal receipts. They prove the pipe ran, not that the water is clean. A render command that costs one invocation goes unused.
- The goal text gets read as 'the plan's steps shipped.' When the same agent wrote the plan, it grades its own homework. The user's real contract (the output is true) lives in their head, not in a check.
- Tests exist per unit (per record, per thread, per row) and on synthetic fixtures. A per-unit rule can pass every test while the aggregate view lies. Real failing cases never became fixtures, and filters had no test for some of the states they should exclude.
- A 'first run proves nothing' rule gets applied to the job but not to the artifact it produces. Two clean runs get treated as proof of the whole system.

What to do instead:
- Before saying done, render the user-facing output the way the user sees it and compare each line to the underlying evidence. Quote what you saw.
- Write the acceptance check from the user's perspective ('is what they see true?') and have it be independent of the plan you authored.
- Add at least one end-to-end test that compares a rendered line to its source evidence, and seed it with real failing cases, not only synthetic ones.
- Test every exclusion state in filters, not just the common ones.
- Apply the 'first run proves nothing' rule to the output surface as well as the process: require a later, independent run to look correct before closing.
- When the user has already said 'that is what I asked for' once, treat it as a signal that your definition of done diverges from theirs, and re-derive the check from their contract.
