---
id: bind-a-check-to-the-property-not-the-nearest-proxy
kind: pattern
title: Bind a check to the property, not the nearest proxy
date: 2026-09-14
---

A check can stay green for a long time while the thing it claims to guard is disconnected. Three independent causes produce this, and they tend to show up together.

**1. The check runs against a proxy, and the real property exists only in prose.**

A docstring, a gate name or a section heading states the claim. The code that actually runs checks something cheaper that sits nearby. Typical shapes:

- A gate documented as "must never reject the style it encodes" is calibrated against a few sample inputs someone typed by hand. It is never run against the real corpus it claims to encode.
- A rendered prompt section has a heading that promises one thing, for example opening lines, above content that is something else, for example whole bodies.
- A test pins a source file against version control as a stand-in for the artifact that file generates. A change in the generated output with no change in the file passes, and a harmless edit to the file fails.

The proxy is not carelessness. It is the nearest thing the author could observe from where they were working. A test written next to a helper calls that helper. A gate registered next to a data module builds its inputs inline. Observing the real property costs an end-to-end run, and the proxy costs one line.

**2. Tests cannot reach external producers, and nothing stands in for them.**

A suite is right to refuse live calls to a model or a paid API, because those calls cost money and are non-deterministic. The side effect is total and easy to miss: every response in every test is typed by hand, so no test anywhere runs against output a real producer emitted. Hand-typed responses carry the author's assumptions about the shape, including the wrong ones, such as a field the author named one way while the real service names it another way.

The fix is captured fixtures with enforced provenance. Record real responses once. Store each with a provenance block saying what produced it, when, and with which version or parameters. Make the fixture loader refuse any fixture that has no provenance block, so an invented fixture cannot be used by accident. Apply this to every external producer, not only the one that already caused an incident.

**3. Partial failure has no floor.**

When a run needs several upstream answers, some can fail, time out or come back empty, and the run carries on with whatever is left. The result looks normal and the report says success. With zero answers, every downstream check becomes a no-op that reads as green.

The fix is an explicit floor. Decide the minimum count or fraction of required answers, fail the run below it, and have the report state how many were attempted, how many succeeded and how many were dropped.

**How to apply:**

1. For each gate or test, write the property it claims in one sentence. Then read the code and name what it actually inspects. If the two differ, the check is bound to a proxy.
2. Rebind the check to the real thing: the real corpus, the rendered artifact, the output of the full path. If that is too expensive to run on every commit, run it on a schedule and keep the cheap proxy as a fast pre-check that is labelled as a proxy.
3. Prove the binding by unplugging it. Disconnect the real input (empty the corpus, skip the render, stub the producer to return nothing) and confirm the check goes red. A check that stays green with its subject removed is decoration.
4. Replace hand-typed external responses with captured fixtures, and make the loader reject any fixture that lacks provenance.
5. Give every step that combines several inputs a floor, and make its report state the denominator.
6. When a docstring or heading makes a promise, find the executable that holds it. If there is none, write one, or reword the prose so it stops claiming more than the code checks.
