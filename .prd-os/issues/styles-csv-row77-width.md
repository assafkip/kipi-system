---
id: styles-csv-row77-width
title: Re-align styles.csv row No 77 (Neo Brutalism Mobile) to 22 columns; width gate for the whole file (sp-42f164c5)
status: closed
priority: p3
parent_prd: plan:skillsui-gap-fill-2026-07-02
allowed_files:
  - plugins/kipi-design/skills/ui-ux-pro-max/data/styles.csv
  - q-system/.q-system/scripts/test/test-styles-csv-width.sh
disallowed_files: []
required_checks:
  - bash q-system/.q-system/scripts/test/test-styles-csv-width.sh
required_reviews: []
bypass_check: "bash q-system/.q-system/scripts/test/test-styles-csv-width.sh"
---

# Re-align styles.csv row No 77 to 22 columns (sp-42f164c5)

## Context

Found during the skillsui gap-fill (plan `q-system/output/plans/skillsui-gap-fill-2026-07-02.md`):
row No 77 shipped upstream with unquoted commas in its Implementation Checklist
column, parsing as 31 columns. Every column from index 20 on was misaligned for
that row (checklist items spread across 10 columns, Design System Variables at
index 30), so `csv.DictReader` consumers read wrong values.

## Fix

Merged columns 20-29 back into one properly-quoted checklist cell (restoring the
original comma-separated items, dropping a stray trailing quote artifact) and
moved the variables cell to column 21. Done via `csv` module so quoting is emitted
correctly.

## Verification (reproducer-first)

- Reproducer shown failing: width scan reported row `('77', 31)` before the fix.
- Negative self-test: `test-styles-csv-width.sh` run against a deliberately
  broken copy (row padded to 24 cols) exits 1.
- After fix: `bash q-system/.q-system/scripts/test/test-styles-csv-width.sh`
  → `PASS: 88 rows x 22 columns`, exit 0.

## Amendments

None.
