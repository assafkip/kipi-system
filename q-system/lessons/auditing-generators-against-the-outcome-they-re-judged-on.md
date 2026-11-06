---
id: auditing-generators-against-the-outcome-they-re-judged-on
kind: methodology
title: Auditing Generators Against the Outcome They're Judged On
date: 2026-11-06
---

When a system produces artifacts whose quality is judged by a downstream outcome (engagement, conversion, acceptance, pass rate), three independent gaps can each make output that is technically on-spec but fails the outcome. Audit all three; they fail silently and independently.

1) Check that your reference set carries the outcome signal.
If you teach a generator by example ("match these samples"), the examples define the target. Run a field-presence count over the reference corpus for the outcome metric. If zero rows carry it, the generator is matching the population average, not the successes — including samples that failed. Fix by either (a) attaching the outcome metric to every reference row and filtering or weighting by it, or (b) splitting the corpus into a measured high-outcome set and everything else, and pointing the generator only at the former. Then add a test that asserts the reference set is non-empty after the outcome filter, so it fails loudly if the metric stops being collected.

2) Check for entry-point drift between parallel paths.
When the same artifact type can be produced by more than one path (scheduled vs. on-demand, batch vs. interactive, API vs. CLI), improvements get wired into whichever path the author was working in. Enumerate every path that emits the artifact, then list which shared config, rule tables, and post-processing steps each one actually reads. Any config file that is loaded by one path and not another is a live divergence. Remedy: extract the composition logic into a single function that all paths call, and add a test that drives each entry point with the same input and asserts the same controls were applied. Be especially suspicious of paths created by a simplification ruling ("strip it back to the minimum"); minimal paths are the ones later enhancements skip, and the ruling's rationale usually did not survive to the people adding enhancements.

3) Check whether your input source can even contain the right material.
Inputs constrain the output space by construction. If candidate material is extracted from internal artifacts — code, build logs, changelogs, internal docs — the output will be about internals no matter how good the generator is, because nothing about the audience exists in the source. Before blaming generation quality, ask: what is this corpus derived from, and what topics are structurally absent from it? Remedy: make selection pull from at least one audience-side source (stated positioning, user-pain research, or the record of which past artifacts actually hit the outcome) and require each candidate to cite one, so the constraint is enforced at selection time rather than hoped for at generation time.

Cross-cutting method: whenever a requirement is stated in natural language ("make it sound like X"), write down the operational test that would prove the stated requirement implies the real goal. Here the unexamined leap was "sounds like the author" equals "works like the author's successes." If you cannot name a check that would fail when the two diverge, that equivalence is an unverified assumption and belongs in your audit list, not your spec.
