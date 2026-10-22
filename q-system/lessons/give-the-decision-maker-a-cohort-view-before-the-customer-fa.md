---
id: give-the-decision-maker-a-cohort-view-before-the-customer-fa
kind: methodology
title: Give the decision-maker a cohort view before the customer-facing report
date: 2026-10-04
---

When a multi-item check runs across a whole group in only one place, and that place is the outbound deliverable, the deliverable stops being a rendering of a reviewed result. It becomes the computation itself. Every internal view then shows one item at a time, so the people who should judge the group have no surface to do it on.

Two symptoms follow.

- The decision happens after the customer's document already exists. Making that document faster does not fix the order.
- A slow or failing report goes unnoticed for a long time, because nobody waits on that screen to do their job. The screen was never part of the job.

A second flaw hides behind the first: the loop over the group had a cost cap in money and no cap in wall-clock time. A budget in one unit does not bound another. A per-item cost limit leaves the total duration open, and the first slow dependency turns it into a timeout.

How to apply:

1. Grep for every call site of the group-level check. If the only one is an outbound artifact, the internal users have no view of it.
2. Build the cohort surface for the reviewer first. Let the report read the result the reviewer already saw instead of recomputing it.
3. Bound every loop in each unit that can hurt you: dollars, items, and seconds. Enforce the time bound in code with a deadline, and return partial results labelled as partial.
4. Before trusting a placeholder phase, record why it is empty. Missing inputs upstream can leave a whole stage inert while everything downstream looks finished.
5. When a doc and an automated audit disagree about whether code is live, check the call path by hand. Aliased or module-qualified imports can make live code look unreachable.
