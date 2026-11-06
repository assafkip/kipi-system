---
id: launch-a-long-pass-only-after-a-control-that-can-fail
kind: methodology
title: Launch a long pass only after a control that can fail
date: 2026-10-19
---

A long unattended pass (a bulk scan, a backfill, a wide crawl) is often gated on nothing. Someone writes a "known answer" expectation into a plan or findings file, starts the pass, and reads the expectation later. If the known answer was wrong, the whole run is wasted and the waste is only visible after it finishes.

Three separate defects make this happen, and each has its own fix.

**1. The control is prose, not a precondition.** A sentence in a document gets read whenever someone gets to it. Turn it into a short pilot run over a pinned control set that exits non-zero when the known answer does not come back, and make the full pass depend on that exit code. Per-item cost is usually measurable from an earlier run, so the pilot's duration is a number you can compute rather than guess.

**2. The control cannot fail.** Watch for a control whose expected result is true by construction: you selected the control items because they already matched, so the pass reproducing them proves only that the selection is deterministic. A real control needs at least one item whose outcome was decided independently of the pass being tested, and the check needs an input that would make it red. If you cannot name that input, it is decoration.

**3. Nobody owns the post-run check.** When the job outlives the worker that launched it (detached process, queue hand-off, agent with a shorter budget than the run), the worker's terminal state becomes "started, verification pending". That verification then lives only in whoever is watching, which is the same as nowhere. Fix it at the job: make the run's own last step execute the control comparison and write a pass/fail artifact, so the check runs whether or not anybody comes back.

One more cheap guard worth adding at launch: a plausibility band from prior runs, not a prior rate recorded as trivia. If you know roughly what fraction of items came back positive last time, encode a floor and a ceiling and abort when the live rate leaves the band. That catches the class of failure where the pass runs correctly against the wrong population, which no single known-answer item will reveal.

The sequencing rule underneath all three: before a run that costs more than a few minutes of wall clock, spend seconds proving the instrument reads correctly on inputs whose answers were established elsewhere, and make that proof a gate in code rather than a line someone intends to read.
