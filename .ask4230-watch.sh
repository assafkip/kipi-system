#!/bin/bash
# Emit each PR 714 check as it settles; exit when none are pending. (ASK-4230)
prev=""
for i in $(seq 1 40); do
  s=$(gh pr checks 714 --json name,bucket 2>/dev/null || echo '[]')
  cur=$(printf '%s' "$s" | jq -r '.[] | select(.bucket!="pending") | "\(.name): \(.bucket)"' 2>/dev/null | sort)
  comm -13 <(printf '%s\n' "$prev") <(printf '%s\n' "$cur") 2>/dev/null
  prev="$cur"
  if printf '%s' "$s" | jq -e 'length > 0 and all(.[]; .bucket != "pending")' >/dev/null 2>&1; then
    echo "ALL CHECKS SETTLED"
    exit 0
  fi
  sleep 30
done
echo "WATCH WINDOW ENDED with checks still pending"
