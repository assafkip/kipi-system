#!/usr/bin/env bash
# Gate for issue styles-csv-row77-width (spillover sp-42f164c5):
# every data row in ui-ux-pro-max styles.csv must have exactly the header's
# column count (22). Row No 77 shipped with unquoted commas in its checklist
# column and parsed as 31 columns, silently misaligning DictReader output.
# Runs from repo root (gates run convention). Accepts an override path for
# negative self-testing against a deliberately broken copy.
set -euo pipefail
CSV="${1:-plugins/kipi-design/skills/ui-ux-pro-max/data/styles.csv}"
python3 - "$CSV" << 'EOF'
import csv, sys
p = sys.argv[1]
with open(p, newline='') as f:
    rows = list(csv.reader(f))
want = len(rows[0])
bad = [(r[0] if r else '?', len(r)) for r in rows[1:] if len(r) != want]
if bad:
    print(f"FAIL: {p}: header has {want} columns; misaligned rows (No, width): {bad}")
    sys.exit(1)
print(f"PASS: {p}: {len(rows)-1} rows x {want} columns")
EOF
