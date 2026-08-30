---
id: a-write-only-integration-cannot-report-state
kind: pattern
title: A write-only integration cannot report state
date: 2026-08-17
---

Any integration that can send data to an external destination but never read it back can only prove that a request left the process. It cannot prove what the destination now contains. When such a component reports counts, deltas, or before-and-after numbers, those figures come from a locally cached snapshot that no code path refreshes, so they drift out of sync the moment anything changes on the other side, and nothing in the system can notice.

How to apply:

1. For each external destination your code touches, list the operations it performs. If the list contains only writes, tag the integration write-only.
2. Treat every state claim about a write-only destination as unverified, including claims already recorded in the component's own docs, comments, dashboards, or status output. Documentation inherits the blindness of the code it describes.
3. Build the read path before trusting any such claim: a fetch or list call that returns the destination's current contents, run against the live destination, not against a local mirror.
4. Make the reader the source of reported numbers. If a cached snapshot stays for performance reasons, stamp it with the time of the last successful read and surface that stamp wherever the numbers appear, so staleness is visible instead of silent.
5. Add a check that compares what the writer believes it sent against what the reader observes. A mismatch is a real defect signal; without the reader there is no input that could ever turn the check red.

The general rule: verification requires a return path. A one-way channel supports statements about actions taken, never statements about resulting state.
