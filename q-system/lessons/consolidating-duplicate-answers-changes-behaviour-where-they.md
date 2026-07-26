---
id: consolidating-duplicate-answers-changes-behaviour-where-they
kind: pattern
title: Consolidating duplicate answers changes behaviour exactly where the copies disagreed
date: 2026-07-26
---

When the same question is answered independently in several places, the copies have almost certainly drifted, and that drift is usually the bug you are consolidating to remove. So "this refactor is behaviour-preserving" cannot be true as a blanket statement: at every input where the copies previously disagreed, exactly one of them wins after consolidation, and the other's behaviour necessarily changes. Writing "behaviour must not change" as the acceptance bar therefore sets a target the correct implementation will fail.

Why this hides: the cases where the copies agree are the common ones, so a differential test over ordinary inputs comes back byte-identical and reads as proof. The disagreements live in the rare shapes nobody enumerated. A harness that samples the shapes you thought of confirms the copies agree on the shapes you thought of.

How to apply:

1. State the bar as "behaviour changes ONLY where the duplicated answers previously disagreed, and every such case is enumerated." That is checkable; "no behaviour change" is not.
2. Before editing, run both implementations over a fixture holding every shape you can construct, and diff the outputs. Treat each disagreement as a decision to make deliberately, not a bug to smooth over. Ask which answer is correct rather than which is more common.
3. Expect the fixture to be incomplete. When a differential comes back clean, say which shapes it covered rather than concluding equivalence. The gap between "identical on nine shapes" and "identical" is where the surprise lives.
4. A disagreement that turns out to be a latent bug fix is a good outcome, but it is still a behaviour change: record it, and check whether anything downstream depended on the broken branch.

Scar 2026-07-26 (kipi-update.sh): four sites independently answered "what is a plugin?". A differential over nine path shapes showed the old and new enumerations byte-identical, which read as proof of equivalence. It was not: a dot-named directory under `plugins/` was enumerated by one answer and skipped by the other, so the old code staged a path the syncer never wrote and aborted the whole config sync with `pathspec ... did not match any files`. The consolidation fixed that -- correctly -- but the PRD's "behaviour must not change" bar had already been falsified, and the fixture simply had no dot-named directory in it.
