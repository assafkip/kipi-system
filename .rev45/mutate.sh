#!/usr/bin/env bash
# Do the new tests actually refuse? Copy linear-sync.py + its test into a scratch
# dir, break one behaviour per mutant, and record the suite's exit code.
# The repo is never touched.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/q-system/.q-system/scripts"
run_mutant() {
  local name="$1" py="$2"
  local d; d="$(dirname "$0")/mut-$name"; mkdir -p "$d"
  cp "$SRC/linear-sync.py" "$SRC/test_linear_sync_agent.py" "$d/"
  command python3 - "$d/linear-sync.py" "$py" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); src = p.read_text()
old, new = sys.argv[2].split("|||")
assert old in src, f"mutation anchor missing: {old[:60]!r}"
p.write_text(src.replace(old, new, 1))
PY
  [ $? -eq 0 ] || { echo "$name: ANCHOR MISSING (mutation not applied)"; return; }
  command python3 "$d/test_linear_sync_agent.py" > "$d/out.txt" 2>&1
  local rc=$?
  printf '%-28s rc=%s  %s\n' "$name" "$rc" "$(grep -m1 '^== ' "$d/out.txt")"
  grep '^  FAIL' "$d/out.txt" | head -2 | sed 's/^/      /'
}

echo "== baseline (unmutated) =="
command python3 "$SRC/test_linear_sync_agent.py" >/dev/null 2>&1
echo "baseline rc=$?"
echo
echo "== mutants =="
run_mutant parse-all-blocks     'for line in blocks[-1]:|||for line in [l for b in blocks for l in b]:'
run_mutant drop-allowlist       'if len(parts) >= 2 and parts[0].strip().lower() in SEVERITY_RANK:|||if len(parts) >= 2 and parts[0].strip():'
run_mutant ignore-session-status 'if latest["status"] != "complete":|||if False:'
run_mutant pick-oldest-session  'latest = sessions[-1]|||latest = sessions[0]'
run_mutant drop-delegate-readback 'if (got or "").lower() != args.agent.lower():|||if False:'
run_mutant unclosed-block-ok    "if line.strip() == \"END FINDINGS\":|||if False:"
