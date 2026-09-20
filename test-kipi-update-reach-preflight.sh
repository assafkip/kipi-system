#!/bin/bash
# The long path must not start without the one-second answer.
#
# THE SCAR (2026-09-20). A full run costs 20-25 minutes and reports only the
# FIRST refusal per instance. Five runs across 2026-09-19 and 2026-09-20 were
# spent learning one blocker per run -- dirty tree, then skeleton behind
# origin/main, then dangling symlinks -- while fleet-reach-audit.py, which
# reports every instance's refusal reason read-only in about a second, sat
# unopened in this directory. It was written 2026-08-14 (ASK-797/ASK-803)
# after the same pattern burned that rollout.
#
# A memory file, a rule and a comment all existed and none of them fired. So
# the fix is the invocation, and this file is what keeps the invocation there.
#
# THE AUDIT IS STUBBED, DELIBERATELY. The preflight's contract is "given the
# audit's verdict, do the right thing"; the audit's own correctness has its own
# tests. Stubbing at $SKEL/fleet-reach-audit.py also proves the preflight reads
# THAT path -- a stub that was never called cannot produce the marker each case
# asserts on.
#
# ONLY --dry-run is ever invoked, against a throwaway skeleton and instance.
#
# Run: bash test-kipi-update-reach-preflight.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

has() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
ok()   { echo "  ok: $1"; }
bad()  { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

# $1 root, $2 = the stub audit's stdout, $3 = the stub's exit code,
# $4 = "absent" to omit the audit entirely.
build_fleet() {
  local root="$1" verdict="$2" rc="$3" mode="${4:-present}"
  local skel="$root/skeleton" inst="$root/instance"
  mkdir -p "$skel"
  cp -R "$REAL/q-system" "$skel/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$skel/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$skel/" 2>/dev/null
  cp -R "$REAL/plugins" "$skel/plugins" 2>/dev/null
  chmod +x "$skel/kipi-update.sh"
  g init -q "$skel" && g -C "$skel" add -A && g -C "$skel" commit -qm init

  mkdir -p "$inst/q-system"
  echo instance > "$inst/q-system/marker"
  g init -q "$inst" && g -C "$inst" add -A && g -C "$inst" commit -qm init

  cat > "$skel/instance-registry.json" <<JSON
{"skeleton": {"path": "$skel"},
 "instances": [{"name": "fixture", "path": "$inst",
                "subtree_prefix": "q-system", "instance_q_dir": null,
                "type": "subtree", "has_git": true}]}
JSON

  if [ "$mode" = "absent" ]; then
    rm -f "$skel/fleet-reach-audit.py"
  else
    cat > "$skel/fleet-reach-audit.py" <<PY
#!/usr/bin/env python3
import sys
print("STUB-AUDIT-RAN")
print("$verdict")
sys.exit($rc)
PY
    chmod +x "$skel/fleet-reach-audit.py"
  fi
  printf '%s' "$skel"
}

run_update() {  # $1 skeleton, rest = extra args
  local skel="$1"; shift
  ( cd "$skel" && ./kipi-update.sh --dry-run "$@" 2>&1 )
}

echo "== A. clean fleet: preflight prints and the run proceeds =="
SK="$(build_fleet "$T/a" "REACH: 1 of 1 would sync now" 0)"
OUT="$(run_update "$SK")"
has "$OUT" "STUB-AUDIT-RAN" \
  && ok "the audit at \$SCRIPT_DIR was actually invoked" \
  || bad "the audit was never called"
has "$OUT" "REACH: 1 of 1" \
  && ok "the verdict is printed on a CLEAN fleet too (liveness, not silence)" \
  || bad "a clean fleet printed no verdict; zero and never look identical"
has "$OUT" "would refuse this update" \
  && bad "a clean fleet was refused" \
  || ok "a clean fleet is not refused"

echo "== B. blockers exist: refuse BEFORE any instance is touched =="
SK="$(build_fleet "$T/b" "REACH: 0 of 1 would sync now" 0)"
OUT="$(run_update "$SK")"; RC=$?
has "$OUT" "ABORT: 1 of 1 instance(s) would refuse" \
  && ok "refused, naming the count" \
  || bad "did NOT refuse on a blocked fleet -- this is the whole test"
has "$OUT" "--- fixture" \
  && bad "an instance was entered despite a known blocker" \
  || ok "no instance was entered"
has "$OUT" "fleet-unblock.py --apply" \
  && ok "the refusal names the remedy" \
  || bad "the refusal does not name fleet-unblock.py"

echo "== C. audit missing: abort, never a silent pass =="
SK="$(build_fleet "$T/c" "" 0 absent)"
OUT="$(run_update "$SK")"
has "$OUT" "ABORT: reach preflight missing" \
  && ok "a missing preflight aborts" \
  || bad "a missing preflight passed silently"

echo "== D. audit runs but reports no verdict: abort =="
SK="$(build_fleet "$T/d" "something went wrong" 1)"
OUT="$(run_update "$SK")"
has "$OUT" "ABORT: the reach preflight did not report a verdict" \
  && ok "a mute preflight aborts" \
  || bad "a mute preflight passed -- a gate that cannot run must not pass"

echo "== E. the hatch works and announces itself =="
SK="$(build_fleet "$T/e" "REACH: 0 of 1 would sync now" 0)"
OUT="$(run_update "$SK" --skip-reach-preflight)"
has "$OUT" "reach preflight: SKIPPED" \
  && ok "the hatch announces itself" \
  || bad "the hatch is silent"
has "$OUT" "ABORT: 1 of 1 instance(s) would refuse" \
  && bad "the hatch did not bypass the refusal" \
  || ok "the hatch bypasses the refusal"

echo "== F. MUTATION: delete the call, case B must go RED =="
SK="$(build_fleet "$T/f" "REACH: 0 of 1 would sync now" 0)"
BEFORE="$(wc -c < "$SK/kipi-update.sh")"
# Remove the single invocation, leaving the function defined but unreachable.
python3 - "$SK/kipi-update.sh" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
needle = "\nreach_preflight\n\nwhile IFS='|' read -r name path prefix itype declared; do"
assert needle in s, "mutation target not found; the mutant was NOT applied"
p.write_text(s.replace(needle, "\n\nwhile IFS='|' read -r name path prefix itype declared; do"))
PY
AFTER="$(wc -c < "$SK/kipi-update.sh")"
if [ "$BEFORE" -eq "$AFTER" ]; then
  bad "mutant not applied (byte count unchanged) -- case F proves nothing"
else
  ok "mutant applied ($BEFORE -> $AFTER bytes)"
  OUT="$(run_update "$SK")"
  has "$OUT" "ABORT: 1 of 1 instance(s) would refuse" \
    && bad "the mutant SURVIVED: the refusal fires without the call site" \
    || ok "the mutant is killed: no call site, no refusal"
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: the long path cannot start without the one-second answer."
  exit 0
fi
echo "FAIL: $FAILURES check(s)"
exit 1
