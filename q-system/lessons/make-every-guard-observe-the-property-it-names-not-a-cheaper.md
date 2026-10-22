---
id: make-every-guard-observe-the-property-it-names-not-a-cheaper
kind: methodology
title: Make every guard observe the property it names, not a cheaper proxy
date: 2026-10-04
---

A gate, test or check is only as strong as the thing it actually observes. A recurring failure: the name, docstring or heading states a strong claim ("this gate never rejects valid input", "this section shows the real first lines"), while the code underneath checks something cheaper that happens to sit nearby, such as a few hand-written samples, a file's text instead of the behavior that file produces, or a helper's return value instead of the end result. The proxy is not carelessness. It is the nearest observable thing at the altitude where the author stood, and it costs one line where the real property costs an end-to-end run. The claim then survives only in prose, and the check stays green after the guarded property is unplugged.

A second, structural cause makes this worse. Test suites correctly forbid live calls to non-deterministic or paid dependencies such as a model, a network service or a third-party API. The side effect is total: every answer from that dependency in every test is hand-typed by the author, so nothing ever runs against output the real dependency produced. The author's mental model of the dependency's output shape becomes the oracle, and wrong assumptions about field names or formats stay invisible until production.

What to do:
- For each guard, write down the property it claims in one sentence, then name the observable it actually reads. If they differ, either bind the check to the real property or rename the guard to what it checks.
- Mutation-test the guard: unplug or break the guarded behavior on a copy and confirm the check goes red. A check that stays green is decoration.
- Where live calls are banned, capture real responses once, store them as fixtures, and make the fixture loader refuse any fixture lacking a provenance record (source, capture date, version). Hand-typed answers then cannot masquerade as captured ones.
- Keep a small number of fixtures from real runs for every external dependency the suite fakes, and refresh them on a schedule.
- Define a floor for partial failure: when a required answer from a dependency is missing or malformed for some items, the job must fail loudly or degrade explicitly, never pass with fewer items checked.
