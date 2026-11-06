---
id: validate-your-ground-truth-before-calibrating-against-it
kind: methodology
title: Validate Your Ground Truth Before Calibrating Against It
date: 2026-10-31
---

When you calibrate a new check, classifier, threshold, or heuristic against known examples, verify the labels on those examples by hand before using them. An unverified reference is an assumption, not a fact, and every downstream judgment inherits its error.

How to do it:

1. Before using any example as ground truth, independently establish why it has the label it has. Derive the label from primary evidence or first principles rather than accepting it because it was provided, named, or stored in a folder implying the answer.
2. Confirm labels on both sides of the boundary. A reference set that only pins down one class gives you no way to detect that your anchor is on the wrong side.
3. Count your references. Compute how much a single mislabeled example moves your result. With one or two anchors, one bad label flips everything, so the verification effort must scale up as the reference set shrinks.
4. Prefer three or more independently verified references over one convenient one. Redundancy lets contradictions surface instead of propagating silently.
5. Separate the person or process that produced the labels from the one that validates them where possible, so a single misunderstanding does not pass through unchallenged.
6. Record the verification reasoning next to each reference, not just the label. Later readers need to know what the label rests on in order to re-audit it.
7. When a batch of results comes back uniformly one way, treat that uniformity as a signal to re-audit the anchor rather than as confirmation that the method works. Systematic agreement is as consistent with a broken reference as with a correct method.
8. After any surprising run of results, re-verify the reference set first, before adjusting the logic being calibrated. Fixing the method against a bad anchor encodes the error more deeply.

Why it works: calibration transfers the properties of the reference onto every later decision. Effort spent validating a small number of anchors is cheap relative to re-doing an entire batch of judgments, and it is the only step that can catch an error which otherwise looks like consistency.
