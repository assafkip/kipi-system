---
id: test-the-coverage-invariant-not-each-escape-case
kind: methodology
title: Test the Coverage Invariant, Not Each Escape Case
date: 2026-11-09
---

When a component partitions input into categories (for example, a splitter that decides which text gets checked and which gets skipped), recurring review findings of the form 'here is another shape of input that slips through' are a signal that a global invariant is untested.

1. Assert the conservation property, not the cases. Write one property-style test that says every unit of input (line, record, byte range) ends up in exactly one place: processed, or explicitly reported as skipped with a reason. Run it over many inputs, including real ones. Patching each newly found escape with its own fix and its own test leaves the next shape one review away. The invariant test closes the whole class at once.

2. Prefer explicit inclusion over exclusion. Logic that decides what to drop by ruling things out will silently drop anything it did not anticipate. Make skipped content visible: report what was skipped and why, so silent loss becomes a test failure instead of a review finding.

3. Write down the input format before writing the parser. If the input format is implicit, the parser encodes a guess. Collect real samples of every input variant in use; they often differ in structure, for example a metadata header, separators, trailing appendices, or alternate section layouts. Write a short spec for each variant that says which regions are content and which are not, then build fixtures from those real samples rather than from invented ones. A guessed boundary fails both ways. Cutting too aggressively loses content. Fixing that by cutting less pulls non-content such as notes or appendices into processing, which causes false positives.

4. Watch for fixes that trade one failure mode for its mirror. If a coverage fix suddenly raises false positives or rejections, the boundary definition is wrong. Revisit the format spec rather than adding another special case.

5. Validate scope changes with the target measurement. When you narrow or widen what a gate or check applies to, evaluate it by running it on exactly the inputs the new scope owns, against the real success criterion (for example, 'clean inputs in scope pass, flawed ones fail'). Comparing against how the old scope behaved is the wrong instrument. Use the same measurement every iteration so results are comparable across rounds.

6. Run real-corpus checks after each round. After each fix, re-run the gate over the actual population of inputs and inspect every rejection. Classify each one as a true positive or as an artifact of how the input was segmented.
