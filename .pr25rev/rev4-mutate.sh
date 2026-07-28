#!/usr/bin/env bash
# Are the new sections real tests? Mutate the FIXED code and see if they go red.
# Mutation: pr_merge_state always answers empty (the "gh could not tell us" path),
# which is the single change that would silently switch the whole feature off.
set -uo pipefail
SRC="/Users/assafkipnis/.config/kipi/worktrees/ask-212"
M="/Users/assafkipnis/projects/kipi-system/.pr25rev/mut"
rm -rf "$M"; mkdir -p "$M/q-system/.q-system"
cp -R "$SRC/q-system/.q-system/scripts" "$M/q-system/.q-system/scripts"
export TMPDIR="/Users/assafkipnis/projects/kipi-system/.pr25rev/tmp/"; mkdir -p "$TMPDIR"

echo "=== control: unmutated copy ==="
bash "$M/q-system/.q-system/scripts/test/test-severity-floor.sh" 2>&1 | tail -3

echo
echo "=== mutation: pr_merge_state() { echo ''; } ==="
"$(command -v python3)" - "$M/q-system/.q-system/scripts/pr-verdict-lib.sh" <<'PY'
import re,sys
p=sys.argv[1]; s=open(p).read()
s=s.replace('''pr_merge_state() {
  gh pr view "$1" --json mergeStateStatus -q .mergeStateStatus 2>/dev/null | tr -d '[:space:]'
}''','''pr_merge_state() {
  echo ""
}''')
open(p,'w').write(s)
PY
grep -A2 '^pr_merge_state()' "$M/q-system/.q-system/scripts/pr-verdict-lib.sh" | sed 's/^/    /'
bash "$M/q-system/.q-system/scripts/test/test-severity-floor.sh" 2>&1 | tail -6
echo "MUTANT RC above"
