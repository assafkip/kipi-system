#!/bin/bash
# The long path must not start without the one-second answer -- and the
# preflight must not wedge the fleet it exists to unblock.
#
# THE SCAR (2026-09-20). A full run costs 20-25 minutes and reports only the
# FIRST refusal per instance. Five runs across 2026-09-19 and 2026-09-20 were
# spent learning one blocker per run -- dirty tree, then skeleton behind
# origin/main, then dangling symlinks -- while fleet-reach-audit.py, which
# reports every instance's refusal reason read-only in about a second, sat
# unopened in this directory. It was written 2026-08-14 (ASK-797/ASK-803)
# after the same pattern burned that rollout.
#
# THE SECOND SCAR, from this PR's own review. The first version of the gate
# counted BLOCKED-FOUNDER in its refusal total and ran before --only was
# consulted, so ONE instance holding founder work refused EVERY invocation on
# the live fleet, including runs scoped to a different clean instance. The only
# escape was --skip-reach-preflight, i.e. the gate off. Cases B2 and B3 below
# are that finding; they go red against the original version.
#
# THE AUDIT IS STUBBED, DELIBERATELY. The preflight's contract is "given the
# audit's verdict, do the right thing"; the audit's own correctness has its own
# tests. Stubbing at $SKEL/fleet-reach-audit.py also proves the preflight reads
# THAT path -- a stub that was never called cannot produce what each case
# asserts on. The stub emits the SAME --json shape the real producer emits:
# a list of {name, path, prefix, blocked_by, verdict}.
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

# $1 root, $2 = verdict for instance "clean", $3 = verdict for "second"
#   ("" means the fleet has only one instance), $4 = "absent" | "garbage"
build_fleet() {
  local root="$1" v1="$2" v2="${3:-}" mode="${4:-present}"
  local skel="$root/skeleton"
  mkdir -p "$skel"
  cp -R "$REAL/q-system" "$skel/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$skel/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$skel/" 2>/dev/null
  cp -R "$REAL/plugins" "$skel/plugins" 2>/dev/null
  chmod +x "$skel/kipi-update.sh"
  g init -q "$skel" && g -C "$skel" add -A && g -C "$skel" commit -qm init

  local reg='{"skeleton": {"path": "'"$skel"'"}, "instances": ['
  for n in clean second; do
    if [ "$n" = "second" ] && [ -z "$v2" ]; then continue; fi
    mkdir -p "$root/$n/q-system"; echo "$n" > "$root/$n/q-system/marker"
    g init -q "$root/$n" && g -C "$root/$n" add -A && g -C "$root/$n" commit -qm init
    reg="$reg"'{"name":"'"$n"'","path":"'"$root/$n"'","subtree_prefix":"q-system",'
    reg="$reg"'"instance_q_dir":null,"type":"subtree","has_git":true},'
  done
  printf '%s]}' "${reg%,}" > "$skel/instance-registry.json"

  case "$mode" in
    absent) rm -f "$skel/fleet-reach-audit.py" ;;
    garbage)
      printf '#!/usr/bin/env python3\nimport sys\nsys.exit(3)\n' > "$skel/fleet-reach-audit.py"
      chmod +x "$skel/fleet-reach-audit.py" ;;
    *)
      {
        echo '#!/usr/bin/env python3'
        echo 'import json, sys'
        echo 'rows = [{"name": "clean", "path": "/x", "prefix": "q-system",'
        echo '         "blocked_by": [{"status": "M", "path": "q-system/marker",'
        echo '                         "staged": False, "kind": "founder"}],'
        echo '         "verdict": "'"$v1"'"}]'
        if [ -n "$v2" ]; then
          echo 'rows.append({"name": "second", "path": "/y", "prefix": "q-system",'
          echo '             "blocked_by": [{"status": "A", "path": "plugins/x",'
          echo '                             "staged": True, "kind": "fleet"}],'
          echo '             "verdict": "'"$v2"'"})'
        fi
        echo 'print(json.dumps(rows))'
      } > "$skel/fleet-reach-audit.py"
      chmod +x "$skel/fleet-reach-audit.py" ;;
  esac
  printf '%s' "$skel"
}

run_update() { local skel="$1"; shift; ( cd "$skel" && ./kipi-update.sh --dry-run "$@" 2>&1 ); }

echo "== A. clean fleet: the verdict prints and the run proceeds =="
SK="$(build_fleet "$T/a" WOULD-SYNC)"
OUT="$(run_update "$SK")"
has "$OUT" "reach preflight: 1 of 1 would sync now" \
  && ok "the verdict prints on a CLEAN fleet too (liveness, not silence)" \
  || bad "no verdict on a clean fleet"
has "$OUT" "ABORT:" && bad "a clean fleet was refused" || ok "a clean fleet is not refused"

echo "== B. BLOCKED-FLEET: refuse before any instance is touched =="
SK="$(build_fleet "$T/b" BLOCKED-FLEET)"
OUT="$(run_update "$SK")"
has "$OUT" "clean: BLOCKED by updater exhaust" \
  && ok "names the blocked instance" || bad "did NOT refuse on updater exhaust"
has "$OUT" "--- clean" && bad "entered an instance despite a known blocker" \
  || ok "no instance was entered"
has "$OUT" "fleet-unblock.py --apply" && ok "names the remedy" || bad "no remedy named"

echo "== B2. BLOCKED-FOUNDER alone must NOT refuse (review finding 1) =="
SK="$(build_fleet "$T/b2" BLOCKED-FOUNDER)"
OUT="$(run_update "$SK")"
has "$OUT" "ABORT:" \
  && bad "a correct founder refusal wedged the whole run -- that is the gate off by design" \
  || ok "founder work does not abort the run"
has "$OUT" "correctly refused until committed" \
  && ok "founder work prints as information" || bad "founder work not surfaced at all"

echo "== B3. --only a clean instance while another is BLOCKED-FLEET (finding 1) =="
SK="$(build_fleet "$T/b3" WOULD-SYNC BLOCKED-FLEET)"
OUT="$(run_update "$SK" --only clean)"
has "$OUT" "scoped to --only clean" \
  && ok "the verdict is scoped to what this run would touch" || bad "verdict not scoped to --only"
has "$OUT" "ABORT:" \
  && bad "a run scoped to a clean instance was refused over an unrelated one" \
  || ok "an unrelated blocked instance does not refuse a scoped run"

echo "== C. audit absent: DISARM with an announcement, never a silent pass =="
SK="$(build_fleet "$T/c" WOULD-SYNC "" absent)"
OUT="$(run_update "$SK")"
has "$OUT" "reach preflight: disarmed (no fleet-reach-audit.py" \
  && ok "absent audit disarms out loud (every fixture skeleton is this shape)" \
  || bad "absent audit did not disarm cleanly"

echo "== D. audit present but produces no verdict: ABORT =="
SK="$(build_fleet "$T/d" WOULD-SYNC "" garbage)"
OUT="$(run_update "$SK")"
has "$OUT" "ABORT: the reach preflight produced no verdict" \
  && ok "a broken audit aborts -- a gate that cannot run must not pass" \
  || bad "a broken audit passed"

echo "== E. the hatch, and the remedy carries the operator's args (finding 2) =="
SK="$(build_fleet "$T/e" BLOCKED-FLEET)"
OUT="$(run_update "$SK" --skip-reach-preflight)"
has "$OUT" "reach preflight: SKIPPED" && ok "the hatch announces itself" || bad "the hatch is silent"
has "$OUT" "ABORT:" && bad "the hatch did not bypass" || ok "the hatch bypasses the refusal"
OUT="$(run_update "$SK" --only clean)"
has "$OUT" "./kipi-update.sh --dry-run --only clean --skip-reach-preflight" \
  && ok "the remedy reproduces the operator's own invocation" \
  || bad "the remedy dropped the operator's arguments; pasting it widens the run"

echo "== F. MUTATION: delete the call, case B must go RED =="
SK="$(build_fleet "$T/f" BLOCKED-FLEET)"
BEFORE="$(wc -c < "$SK/kipi-update.sh")"
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
  has "$OUT" "BLOCKED by updater exhaust" \
    && bad "the mutant SURVIVED: the refusal fires without the call site" \
    || ok "the mutant is killed: no call site, no refusal"
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS: the long path cannot start without the one-second answer, and that"
  echo "      answer cannot wedge a run it has no business wedging."
  exit 0
fi
echo "FAIL: $FAILURES check(s)"
exit 1
