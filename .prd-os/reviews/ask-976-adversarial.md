# Adversarial review: ask-976-digest-parsers-live-shape

VERDICT: APPROVE

Adversarial pass 2026-08-23. Mutation: swapped in origin/main's
morning_init.py inside an isolated temp copy of kipi-mcp (src + tests), ran the
five targeted cases:

```
FAILED test_h3_children_parse_into_their_h2_section
FAILED test_gap_sections_accumulate_never_overwrite
FAILED test_superseded_source_is_recorded_not_parsed
FAILED test_valid_false_names_its_failed_checks
FAILED test_retired_sources_drop_out_of_validity
5 failed, 34 deselected
```

Each mechanism's test dies when its fix is removed, so no case is decoration.

Schema-decision check: valid=True is reachable ONLY from sources still alive;
the retired path labels instead of parses. The loosening failure mode named in
sp-8804dee7 ("fix validity by weakening a parser toward retired content") is
structurally closed, not just currently green.
