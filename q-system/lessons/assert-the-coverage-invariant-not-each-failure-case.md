---
id: assert-the-coverage-invariant-not-each-failure-case
kind: pattern
title: Assert the Coverage Invariant, Not Each Failure Case
date: 2026-11-09
---

Pattern: when a component decides what to keep or drop by exclusion (a splitter, filter, parser, or gate that skips some input), repeated review rounds that each uncover one more way input silently escapes are a symptom of a missing invariant test, not a series of unrelated bugs.

How to apply:

1. Name the property every bug violated. For a splitter, it is usually: every unit of input (line, record, byte range) ends up exactly one place, either processed or reported as skipped with a named reason. Write one property-style test that asserts this over many varied inputs. Don't add one more example test per newly found shape. Patching cases one at a time guarantees the next shape is found by the next reviewer instead of by the test suite.

2. Write down the input format before writing the code that splits it. Collect the real files the component will see in production, not only the test fixtures. Different producers often emit different shapes (metadata header blocks, separators, trailing appendices, sectioned samples). Document which regions count as content and which count as annotation. If the boundary is guessed, every fix moves the error somewhere else. Stopping a cut at a separator to fix coverage can turn trailing notes into scored content and create a wave of false refusals.

3. Measure scope changes with the target instrument, every round. If a change narrows or widens what a check owns, don't judge it by side numbers such as how many files the old scope rejected. Run the check on exactly the inputs the new scope owns and confirm the target outcome. For a gate, that outcome is that clean owned inputs pass and dirty ones fail. Use the same measurement each round so results are comparable.

4. Re-measure after every fix on the real corpus, not just the fixtures. Re-measuring is often where the next class of problem shows up.

Checklist before merging a fix to an exclusion-based component: an invariant test covers the property; a written format spec exists, based on real inputs; the change was evaluated on the owned target set with the standard instrument; false-positive and false-negative counts on real data are recorded.
