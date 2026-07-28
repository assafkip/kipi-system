#!/usr/bin/env bash
# Falsify the comment at linear-worker.sh:285 -- "The flag is claimed in the same
# write that reports it, so two runs cannot both read 'not paged yet'."
# claim_page_once is read-modify-write on a plain JSON file with no lock.
set -uo pipefail
BASE="/Users/assafkipnis/projects/kipi-system/.pr25rev/race-$$"; mkdir -p "$BASE"
ATTEMPTS="$BASE/linear-worker-attempts.json"
printf '{"ASK-AAA":{"conflict_rounds":2}}\n' > "$ATTEMPTS"

# verbatim body of claim_page_once from linear-worker.sh (28ae526), $ATTEMPTS bound
claim_page_once() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{})
first = not e.get(sys.argv[2])
e[sys.argv[2]]=True
json.dump(d,open('$ATTEMPTS','w'),indent=2)
raise SystemExit(0 if first else 1)" "$1" "$2"; }

: > "$BASE/pages.txt"
for i in 1 2 3 4 5 6 7 8; do
  ( claim_page_once ASK-AAA conflict_paged && printf 'PAGE from proc %s\n' "$i" >> "$BASE/pages.txt" ) &
done
wait
echo "pages emitted for ONE issue, ONE flag, 8 concurrent runs: $(grep -c . "$BASE/pages.txt")"
cat "$BASE/pages.txt" | sed 's/^/    /'
echo "ledger: $(cat "$ATTEMPTS" | tr -d '\n ')"
