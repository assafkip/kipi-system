---
id: verify-the-rendered-surface-not-the-pipeline-that-feeds-it
kind: methodology
title: Verify the rendered surface, not the pipeline that feeds it
date: 2026-09-07
---

## The failure shape

A task is judged done because the machinery reported success: the job exited clean, the suite was green, the change merged, the review receipt existed. Every one of those is a statement about the pipe. The request was about the water.

The tell is that the artifact a person actually looks at was never opened. It costs one command to render it and read the lines against the evidence behind them, and that command is skipped because the upstream signals all agree.

## Why the green signals do not cover it

- **Ran is not correct.** A run can succeed on schedule, with a healthy external connection, and still emit stale or fabricated lines.
- **Per-item tests do not see aggregate lies.** When rules are written and tested per record, a rule can pass on every record and still produce a false statement at the level where records combine into one view.
- **Synthetic fixtures miss the live pairs.** A rule tested only on invented inputs has never met the real ones. The cases that fail in production were never fixtures.
- **Filters get partial coverage.** A predicate that excludes several categories usually has tests for the categories someone thought of, and none for the rest.
- **A self-written plan grades itself.** When the same actor writes the step list and then checks the step list, completion measures the plan, not the request.

## The method

**1. Name the surface before starting.** In one line, write which rendered output a human will read and what would make it true. Do this before the first change, not at the end. If the goal text says "complete, nothing hanging", the acceptance object is the surface, not the step list.

**2. Make the last check a render-and-compare.** Produce the artifact the way the consumer sees it, then trace at least a few of its lines back to the evidence that should support each one. A line with no supporting evidence, or evidence contradicting it, is a failure regardless of upstream status.

**3. Write one test at the level the claim is made.** If the claim spans several records, the assertion has to span them too. Per-item tests stay, but they do not substitute for one that renders the composite and asserts against known evidence.

**4. Pull fixtures from live inputs.** Take failing real cases into the fixture set as they are found. An invented fixture tests the assumption, not the world.

**5. Enumerate a filter's excluded categories explicitly.** List every category the predicate is meant to drop, and give each one a case. Uncovered categories are the ones that leak.

**6. Apply the day-two rule to the surface, not just the job.** If a first clean run proves nothing for the pipeline, it proves nothing for the rendered output either. Two clean runs of the producer are not evidence about the consumer's view.

## The repeat signal

When this shape appears twice in one stretch of work, and the second time is acknowledged as the same mistake, that is not a lapse in attention. It means the acceptance condition still lives only in someone's head and in scattered background notes, where no check can reach it. The fix is to move it into an executable comparison. Until it is a check that can fail, the whole set of gates can be green while the deliverable is false.

## Checks that prove the method took

- Corrupt the evidence behind one rendered line and confirm the new comparison goes red.
- Add a record in a category the filter is supposed to exclude and confirm a case covers it.
- Confirm at least one fixture in the set came from a real input that failed, not from an invented pair.
