---
id: scope-every-claim-to-what-you-actually-read
kind: methodology
title: Scope every claim to what you actually read
date: 2026-08-03
---

A claim can be grounded in real sources and still be wrong, because grounding checks that you opened something, not that what you opened covers what you said. Three failure modes compound, and each needs its own mechanism.

**1. A read-first rule that only exists as prose does not execute.**
If your process says "read prior context, then write a plan, then act," nothing enforces it unless something fails when the read is skipped. Make the read produce an artifact: a written plan, a checklist of sources with what each one said, a receipt file. Then gate the work on that artifact existing and referencing the sources by name. Prose instructions get skipped silently under time pressure; a missing file does not.

**2. Putting a reference into context is not delivering it.**
Printing a list of relevant prior lessons, doc titles, or index entries at session start feels like delivery. It is not. Titles entering context does not mean the content was opened, and no one notices the gap because the titles look like knowledge. Fix: require an explicit open plus a one-line restatement of what the reference says before it counts as consulted. If a reference is important enough to auto-surface, it is important enough to require a receipt that it was read.

**3. The dangerous seam is over-generalizing from a partial read.**
Automated grounding checks typically catch "you asserted something about a source you never opened." They cannot catch "you opened two of five components in a chain and issued a conclusion about the chain." That seam is where reversals live.

The working discipline for that seam:

- Before stating a conclusion, name its scope: how many units (files, workflows, services, records) the claim covers versus how many you inspected. If those numbers differ, either inspect the rest or rewrite the claim to the subset you inspected.
- Prefer narrow true claims to broad plausible ones. "Two of the five stages do X" survives review; "the pipeline does X" gets reversed.
- Sampling supports an existence claim, never a universal one. One instance proves the thing can happen. It never proves the thing always happens, and it never proves absence.
- Escalate rigor by blast radius. A note to yourself can carry a partial read. Anything leaving the system (a report, an external message, a decision others act on) needs the coverage gap closed or stated inline.

**Design note on the gates themselves.** When an automated check documents its own blind spot in a comment and calls it "behavioral," treat that comment as a live defect report, not as an excuse. A documented uncovered seam that keeps producing incidents is a specification for the next gate. Either extend the check, or add a cheap structural forcing function: for example, require every claim to carry its coverage denominator, which makes an unbounded generalization visible on the page instead of leaving it to judgment.
