---
id: a-constraint-recorded-at-one-call-site-protects-only-that-ca
kind: pattern
title: A constraint recorded at one call site protects only that call site
date: 2026-09-07
---

A hard limit that lives as a comment next to one call is not a control. It is a note. The second team, the second lane, or the same person eight weeks later sets the same option on a different call and hits the same wall, because nothing executable connected the option to the limit.

This shows up most with expensive-mode flags on shared infrastructure: a richer extraction mode, a deeper crawl, an extra join, a verbose retry. One lane measures it, finds it collides with a shared timeout or quota, writes a careful paragraph of findings above the code, and moves on. The paragraph is correct and complete. It also cannot fire anywhere else.

The diagnostic that tells you this happened: a failure whose signature is a DIFFERENT subset of items failing each run. That is the shape of a cost sitting near a ceiling, not of an unreliable dependency. If a past incident with that signature was closed by turning the expensive option off, the option and the ceiling are already known to collide, somewhere in your history.

Four moves, in order:

1. **Bind the limit to the shared thing, not to the caller.** If several lanes reach the same host, gateway, or runner through a common wrapper, the check belongs in the wrapper: when the expensive option is set, either raise the budget, split the unit of work, or refuse. Every current and future caller inherits it. A comment inherits nothing.

2. **Make the option and the budget one decision in code.** Where the flag is read, the budget is computed from it. If a caller can set the flag without the budget changing, the pairing is a convention and conventions do not survive a second lane.

3. **Before enabling an expensive mode anywhere, grep for the option name across the whole repo, not just your module.** You are looking for a prior measurement, not prior usage. A number someone already paid for is the cheapest evidence available, and it is usually sitting in a file you have no reason to open.

4. **When an incident ends with "we turned the option off", that is a finding without a home.** Turning it off resolves the run and preserves nothing. The durable close is the interlock from move 1, plus a check that fails when the option is on and the budget was not adjusted.

The general form: knowledge that lives only in the file where it was learned has a blast radius of that file. Any knowledge meant to govern more than one caller has to become something the machine evaluates, at a point every caller passes through. Prose scales to readers you can predict. The next caller is by definition the one you did not predict.
