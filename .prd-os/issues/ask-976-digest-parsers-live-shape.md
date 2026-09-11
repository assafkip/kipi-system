---
id: ask-976-digest-parsers-live-shape
title: canonical_digest parses the live canonical shape and names validity failures (sp-8804dee7, sp-7e42845e)
status: closed
priority: p0
allowed_files:
  - plugins/kipi-core/kipi-mcp/src/kipi_mcp/morning_init.py
  - plugins/kipi-core/kipi-mcp/tests/test_morning_init.py
  - plugins/kipi-core/.claude-plugin/plugin.json
disallowed_files: []
required_checks:
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_morning_init.py'
  - bash -c 'cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_paths.py'
required_reviews: []
deliverables_count: 3
---
<!-- generated-by: prd_split.py prd=prd-manual finding=sp-8804dee7 at=2026-08-23T02:12:00Z -->

# canonical_digest parses the live canonical shape and names validity failures

## Context

Measured 2026-08-22 against `consulting/q-consult/canonical` through the
installed kipi-core 1.7.19 clone (the copy the MCP server actually starts):
three mechanisms, all in `morning_init.py`.

1. `_split_sections` split at ANY heading, so H3 children became peers of their
   H2 parent. `## Unanswered Questions` held 28 real questions under five ###
   verticals and shipped `discovery.questions=[]` (sp-7e42845e mechanism 1).
2. Parser assignment was last-match-wins. `## Validation Gaps` (0 direct items)
   was overwritten by `## Website Positioning Gap` (8 items), shipping March
   website-positioning notes labelled as validation gaps. A consumer could not
   tell (sp-7e42845e mechanism 2).
3. `_validate_digest` returned `valid=False` with `warnings=[]`: it knew it
   failed and named no reason (sp-7e42845e mechanism 3).

## The schema decision (recorded here because it needs a decision, not a patch)

ASK-510 retired talk-tracks.md / objections.md / current-state.md to pointer
docs on 2026-08-08. The digest schema still asked for metaphor / definition /
wedge / works_today, which live only in retired sources. Decision (Sana,
engineering call, data attached): the fields STAY in the schema; a source whose
body carries a SUPERSEDED marker is recorded in the new `retired_sources` map
with its retiring ASK id instead of being parsed as live content; while
retired, that source's checks drop out of the validity accounting. This keeps
`valid=True` honest: it can only be earned by sources that still live, never by
loosening a parser toward retired content. A consumer distinguishes three
states: parsed content present, `retired_sources[name]` set, or the check named
in `validation_failed`.

## Evidence

RED before the fix, against `origin/main`'s morning_init.py in an isolated
temp copy (2026-08-23), the five new cases:

```
FAILED test_h3_children_parse_into_their_h2_section
FAILED test_gap_sections_accumulate_never_overwrite
FAILED test_superseded_source_is_recorded_not_parsed
FAILED test_valid_false_names_its_failed_checks
FAILED test_retired_sources_drop_out_of_validity
5 failed, 34 deselected
```

GREEN after the fix on this branch:

```
$ cd plugins/kipi-core/kipi-mcp && PYTHONPATH=src python3 -m pytest -q tests/test_morning_init.py
39 passed
```

Section boundary rule after the fix: split at the shallowest heading depth that
REPEATS in the document; when no level repeats (a title plus one section),
fall back to the deepest heading present. Documents sectioning with # alone
behave exactly as before.

Plugin version bumped kipi-core 1.7.19 -> 1.7.21 so deployed clones can tell
the copies apart.

Load-path note (sp-eea17567 / sp-d120853a): the LIVE MCP tool keeps serving
1.7.19 until the marketplace clone updates AND Claude Code restarts; this
issue's evidence is from the repo suite plus the temp-copy mutation, not from
the pinned session server.

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals deliverables_count (locked at issue-start). -->
- [x] `_split_sections` splits at the document's own repeated section level, so H2 parents keep their H3 children's items
- [x] discovery parsers accumulate across same-family headings instead of last-match-wins
- [x] `_validate_digest` returns named failed checks (`validation_failed`) and retired ASK-510 sources are labelled via `retired_sources` and exempted from validity while retired
