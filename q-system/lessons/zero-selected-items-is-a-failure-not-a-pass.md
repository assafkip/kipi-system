---
id: zero-selected-items-is-a-failure-not-a-pass
kind: pattern
title: Zero selected items is a failure, not a pass
date: 2026-08-31
---

When an aggregate check selects a set of sub-checks and then runs them, an empty selection makes the whole check vacuously green. The runner does the filtering correctly, the loop body never executes, the exit code is 0, and every downstream consumer reads that 0 as "everything passed" rather than "nothing was examined."

This shape appears whenever selection and execution are separated: a test runner filtering by tag, a policy engine filtering by rule class, a migration verifier filtering by status, a lint pass filtering by file glob. It survives review because both halves are individually correct. It survives for months because a passing check produces no signal to investigate.

The registration side is usually where the mismatch is born. Items get written with one category value while the runner selects a different one, often because the writer and the runner were built at different times, or because a category field was added later and the default landed on the non-executing value. Nobody notices, because the only observable difference is silence.

How to build against it:

1. Make an empty work set a distinct outcome. If the selection is empty, exit non-zero or emit an explicit UNKNOWN state. Never let zero items collapse into the same signal as "all items passed."

2. Print the denominator, not just the verdict. Report "ran 12 of 47 registered" rather than "all green." A human scanning output can catch a wrong denominator instantly; they cannot catch a missing one.

3. Assert the selection is non-empty when the registry is non-empty. If the source of truth holds records and the runner selects none of them, that is a contradiction worth failing on, independent of what the records say.

4. Validate the category value at write time. If the runner only executes a fixed set of category values, reject registrations carrying anything outside that set, or at minimum warn. A category that no execution path consumes is dead data.

5. Test the aggregate check by making one sub-check fail. If the aggregate cannot be made red by a genuinely broken member, it is not measuring what its name claims. Running it once against a deliberately failing item is the cheapest possible proof that the wiring is live.

The general rule: any check whose result depends on a filter needs to report what the filter kept and treat an empty result as an alarm. Silence from a check that never ran is indistinguishable from success unless the check is built to tell the difference.
