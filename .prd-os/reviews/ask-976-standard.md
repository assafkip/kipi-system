# Standard review: ask-976-digest-parsers-live-shape

VERDICT: APPROVE

Checked 2026-08-23:

- Boundary rule: shallowest REPEATED heading depth; fallback to deepest heading
  when no level repeats; `#`-only documents unchanged. Verified by the five new
  cases plus the pre-existing digest suite (39 passed).
- Accumulation is bounded (`[:10]` applied after concat), matching the old cap.
- `retired_sources` detection reads only the first 30 lines and requires either
  a `SUPERSEDED ... (ASK-nnn)` marker or `status: superseded` frontmatter, so
  ordinary content cannot be misclassified as retired.
- `_validate_digest` now returns (valid, failed-check-names); every failed name
  corresponds to a real check that can fail while its source is live.

# Adversarial notes (merged artifact for the same issue)

Mutation pass: origin/main's morning_init.py in an isolated temp clone fails
all five new cases (5 failed, 34 deselected), so each case guards its own
mechanism.

Residual risk, not blocking: a live file that HAPPENS to quote "SUPERSEDED ...
(ASK-510)" in its first 30 lines would be treated as retired. The retired
pointer docs in consulting canonical all carry it as a blockquote header; a
false positive ships labelled retirement instead of stale content, which is the
safer wrong state, and `validation_failed` still names whatever else is
missing.
