---
id: judge-the-lane-that-gets-used-not-the-lane-that-was-built-to
kind: pattern
title: Judge the lane that gets used, not the lane that was built to be judged
date: 2026-10-05
---

When a system has several entry paths to the same output, quality checks tend to accumulate on the path the builders designed around, while the path users take most often gets a thinner set. Audit each path against one question: which independent judge sees the output before a person does?

Symptoms to look for:
- The busiest path skips a reviewer that a secondary path runs, because the reviewer was attached to a specific function and never wired to the others.
- The only acceptance signal on that path is structural: the output passed format and rule checks. A passing structural gate says the output is well-formed, not that it is good or correct.
- No one has ever generated a representative batch through that path and read it with a quality judge. Each clean-but-wrong result is treated as a one-off instead of evidence about the path.

What to do:
- List every route that produces the artifact and mark which quality judges (fidelity to source, style or tone review, critic) run on each. Any gap on a high-traffic route is the priority.
- Attach the same judges to every route, or route all paths through one shared function so a judge cannot be missed.
- Treat structural pass as necessary, never sufficient. Record a separate quality verdict alongside it.
- Run a batch through the path and have the judge score it before declaring the path accepted. One sample proves nothing; a batch shows the rate.
- When the same gap appears in a second postmortem, stop restating it and change the code so the gap cannot reopen: a check that fails when a route ships without a judge.
