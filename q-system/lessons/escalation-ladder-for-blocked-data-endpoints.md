---
id: escalation-ladder-for-blocked-data-endpoints
kind: pattern
title: Escalation Ladder for Blocked Data Endpoints
date: 2026-10-31
---

When an endpoint that serves secondary or derived content (transcripts, metadata, attachments, rendered fragments) starts returning empty payloads or throttling errors, treat retrieval as a ladder of increasingly human-like execution contexts rather than a single method to be fixed.

How to apply it:

1. Establish the cheap path first. Call the endpoint directly over plain HTTP and record a per-run counter of successful responses. Cheap calls are the fastest and should stay the default for as long as they work.

2. Instrument for the failure signature, not just the error code. Soft blocks often present as HTTP 200 with an empty or stub body, so assert on payload shape (non-empty content, expected field presence) and classify an empty success as a failure. Log the index of the request where degradation begins; a consistent threshold across runs is strong evidence of a request-count quota rather than a bug in your parsing.

3. Add rungs in order of increasing cost and fidelity:
   - direct HTTP calls
   - automated browser in headless mode
   - automated browser with a visible, rendered session and a persistent profile
   Do not assume a headless browser is a superset of plain HTTP. Detection commonly keys on headless-specific signals, so headless can fail where both the raw call and the visible session succeed. Verify each rung independently against the same sample before trusting it.

4. Promote and demote automatically. On classified failure, fall through to the next rung for the remaining items; on a configurable number of consecutive successes, consider dropping back to the cheaper rung to recover throughput. Cache every successful fetch keyed by item identifier so a restart never re-spends quota on work already done.

5. Budget by scale before building. A visible-session rung typically costs several UI interactions per item, which is acceptable for tens of items and untenable for thousands. Measure seconds-per-item on each rung, multiply by the real backlog, and decide explicitly whether the fallback is a completion mechanism or merely a gap-filler for the residue the cheap path could not cover.

6. Make the degradation visible in output. Emit which rung produced each record, plus counts per rung, so downstream consumers and future runs can tell complete data from partially recovered data.

Design notes: keep the parsing and normalization layer identical across rungs so results are interchangeable and the fallback cannot silently change schema. Serialize the heavyweight rung to a single worker since a visible session is usually not safe to parallelize. Persist progress incrementally rather than at the end, because the slow rung is long-running and interruption-prone. Finally, record the observed quota threshold as a tunable constant with a safety margin, and stop the cheap path just short of it instead of discovering the wall on every run.
