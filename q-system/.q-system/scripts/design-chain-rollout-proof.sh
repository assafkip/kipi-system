#!/usr/bin/env bash
# design-chain-rollout-proof.sh -- dc-25 (ASK-1796): prove the design chain REACHED an instance.
#
# WHY. Every other issue proves the gate works here. This one proves an instance HAS it: the fleet
# sync ships q-system/ and the settings template, and the command ships through the marketplace
# clone, so three different paths have to have run. A grep in the skeleton proves none of them.
#
# Usage:
#   design-chain-rollout-proof.sh <instance-root>   # the real proof, after the founder's fleet sync
#   design-chain-rollout-proof.sh --selftest        # builds a temp instance and runs the same checks
#
# Exit 0 every check passed, 1 a check failed, 2 the arguments were wrong. Read-only: it writes
# nothing outside its own temp dir, and never touches the instance it is handed.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPTS=(design-chain-gate.py design-engine-door.py design-engines.json design-standard-check.py
         design-gap-check.py design-impeccable-check.py design-reader-gate.py)
COMMAND_REL="plugins/kipi-core/commands/design-chain.md"
fails=0

say() { printf '%-58s %s\n' "$1" "$2"; }
check() { if [ "$1" = 0 ]; then say "$2" "ok"; else say "$2" "FAILED: $3"; fails=$((fails + 1)); fi; }

proof() {
  local inst="$1"
  [ -d "$inst" ] || { echo "not a directory: $inst" >&2; exit 2; }

  # 1. the scripts arrived (the fleet sync's rsync of q-system/)
  local missing=""
  for s in "${SCRIPTS[@]}"; do
    [ -f "$inst/q-system/.q-system/scripts/$s" ] || missing="$missing $s"
  done
  check "$([ -z "$missing" ] && echo 0 || echo 1)" "design scripts in the instance" "missing:$missing"

  # 2. the hooks are wired in the instance's own settings (the template merge). Parsed, not grepped:
  # a settings.json with the hooks stripped and five decorative mentions of the script names read as
  # wired (dc-25 review), which is the one thing this check exists to refuse.
  local wired
  wired=$(python3 - "$inst/.claude/settings.json" <<'PY' 2>/dev/null || echo 0
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    print(0); raise SystemExit
n = 0
for ev, arr in (d.get("hooks") or {}).items():
    for m in arr if isinstance(arr, list) else []:
        for h in m.get("hooks", []) if isinstance(m, dict) else []:
            c = h.get("command", "") if isinstance(h, dict) else ""
            if "design-chain-gate.py" in c or "design-engine-door.py" in c:
                n += 1
print(n)
PY
)
  check "$([ "${wired:-0}" -ge 5 ] && echo 0 || echo 1)" "gate and door hooks wired in the instance" \
        "found ${wired:-0} hook command(s) inside hooks arrays, want 5"

  # 3. the wired gate REFUSES an unsealed page when run as the harness runs it. A round is built in
  #    a temp dir, never in the instance: the proof must not write into a live instance.
  local tmp page rc out
  tmp=$(mktemp -d)
  mkdir -p "$tmp/site/design/r1"
  printf '{"project": "proof", "owners": []}\n' > "$tmp/design-chain.json"
  page="$tmp/site/design/r1/Home-laptop.html"
  printf '<html><body><p>x</p></body></html>\n' > "$page"
  out=$(printf '{"hook_event_name":"PreToolUse","tool_name":"SendUserFile","session_id":"proof","tool_input":{"files":["%s"]}}\n' "$page" \
    | CLAUDE_PROJECT_DIR="$tmp" DESIGN_CHAIN_STATE="$tmp/state" \
      python3 "$inst/q-system/.q-system/scripts/design-chain-gate.py" 2>&1)
  rc=$?
  rm -rf "$tmp"
  # the exit code alone is not the proof: python3 exits 2 when the script is MISSING, and that read
  # as a refusal against an empty instance (caught by running this against a bare temp dir)
  case "$out" in *"design chain"*) ;; *) rc="-1 (no refusal in its output)" ;; esac
  check "$([ "$rc" = 2 ] && echo 0 || echo 1)" "the instance's gate refuses an unsealed page" \
        "exit $rc, want 2 with the gate's own words"

  # 4. the command a session really loads: the marketplace clone, matched BY CONTENT against the
  # instance's own copy. Any clone holding a file at that path satisfied a bare existence check, so
  # a stale fork or another checkout passed for every instance (dc-25 review). The marketplaces dir
  # is machine-global and per user, which is why the instance's copy is what it is compared to.
  # Resolved here, not at load: the selftest points it at its own clone.
  local marketplaces="${KIPI_MARKETPLACES:-$HOME/.claude/plugins/marketplaces}"
  local want="$inst/$COMMAND_REL" clone cmd_found=1 why="no $COMMAND_REL under $marketplaces"
  if [ ! -f "$want" ]; then
    why="the instance has no $COMMAND_REL to compare the clone against"
  elif [ -d "$marketplaces" ]; then
    while IFS= read -r clone; do
      if cmp -s "$clone" "$want"; then cmd_found=0; break; fi
      why="a clone holds $COMMAND_REL but its bytes differ from the instance's ($clone)"
    done < <(find "$marketplaces" -path "*/$COMMAND_REL" 2>/dev/null)
  fi
  check "$cmd_found" "the command in the marketplace clone, same bytes" "$why"

  [ "$fails" = 0 ] && echo "ROLLOUT PROOF: every check passed for $inst" \
                   || echo "ROLLOUT PROOF: $fails check(s) failed for $inst"
  return $([ "$fails" = 0 ] && echo 0 || echo 1)
}

selftest() {
  # A temp instance built from THIS repo: the same checks, so a change that breaks the proof is
  # caught here rather than after a fleet sync.
  local tmp repo
  repo=$(cd "$HERE/../../.." && pwd)
  tmp=$(mktemp -d)
  mkdir -p "$tmp/inst/q-system/.q-system/scripts" "$tmp/inst/.claude" "$tmp/mp/kipi/plugins/kipi-core/commands"
  for s in "${SCRIPTS[@]}"; do cp "$repo/q-system/.q-system/scripts/$s" "$tmp/inst/q-system/.q-system/scripts/"; done
  cp "$repo/q-system/.q-system/scripts/read-first-gate.py" "$tmp/inst/q-system/.q-system/scripts/" 2>/dev/null
  cp "$repo/.claude/settings.json" "$tmp/inst/.claude/settings.json"
  mkdir -p "$tmp/inst/plugins/kipi-core/commands"
  cp "$repo/$COMMAND_REL" "$tmp/inst/$COMMAND_REL"
  cp "$repo/$COMMAND_REL" "$tmp/mp/kipi/plugins/kipi-core/commands/design-chain.md"
  KIPI_MARKETPLACES="$tmp/mp" proof "$tmp/inst"
  local rc=$?
  rm -rf "$tmp"
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "" ) echo "usage: $(basename "$0") <instance-root> | --selftest" >&2; exit 2 ;;
  * ) proof "$1" ;;
esac
