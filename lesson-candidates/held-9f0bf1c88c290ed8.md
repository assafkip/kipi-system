# HELD lesson (not published)

reason: LLM semantic check flagged a residual real entity
source: [rca-crm-six-lies-2026-08-18.md](../consulting/q-system/output/rca/rca-crm-six-lies-2026-08-18.md)

proposed title: Stored verdicts go stale silently

Any value a system writes after classifying something is a dated verdict, not a fact. Once it is in a store, nothing re-examines it, and it keeps being served long after the classifier that produced it changed. Five habits keep that from turning into a wall of confidently wrong rows.

**Re-prove derived state on a schedule, not only on new input.** If a record is re-judged only when fresh input arrives on it, then any record whose input stream went quiet is frozen at whatever the old classifier decided. Add a version stamp (classifier version plus timestamp) to every derived row, and re-run rows whose stamp predates the current version. Worse than staleness: a record can become permanently unreachable when its lookup key stops resolving (the entity it now keys on is unknown to the system), so it is never revisited by any path. Enumerate rows by store scan, not by lookup, so unmatched rows are still reachable.

**Classify normalized content, not the raw payload.** Raw payloads carry inherited context: quoted history, forwarded material from third parties, boilerplate, salutations addressed to someone else. Length checks, punctuation checks, and addressee checks all read that inherited text as if the current author wrote it. Strip to the author's own contribution first, then classify. Enumerate the payload shapes that break the naive read (short acknowledgment riding a long quoted chain, automated replies, forwards, content addressed to a third party) and make each one its own class with its own fixture.

**Never assert state from a search or list endpoint.** Search returns a subset chosen by relevance, not the full record. Any claim of the form "X never happened" or "nothing since date D" requires the full-fetch call for that record. If a code path or a report makes an absence claim, it must be reading a complete fetch.

**Check where safety code physically sits.** A helper appended below a module's entry guard never runs in scripted invocation, so the witness or audit step it performs is silently absent while the downstream consumer keeps refusing or degrading. Assert the side effect exists after a run, not that the function is defined.

**Isolate per-item failures in batches.** One unresolvable item aborting a whole batch converts a small data gap into total non-execution. Catch per item, record the skip, keep going.

**Capture fixtures with full bodies.** A fixture recorded without payload content pins only routing behavior and leaves the content logic untested. If the fixture cannot fail for the reason you care about, it is not covering that reason.
