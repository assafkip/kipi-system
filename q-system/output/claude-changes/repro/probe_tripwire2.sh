#!/usr/bin/env bash
# probe_tripwire2.sh -- reproducer for Layer 2 wiring (claude-integrity-tripwire.py). ASK-291.
#
# WHAT IT PROVES
# That the tripwire is wired to a matcher that CAN SEE a Bash tool call, and
# that when it runs on that path it actually reverts a Bash write into .claude/.
#
# THE DEFECT IT WAS WRITTEN FOR (sp-b100a0e9)
# The arming proposal inserted Layer 2 after `settings-template-sync-check.py`,
# whose enclosing PostToolUse group has matcher "Edit|Write". Bash is not in it.
# The tripwire would have sat in settings.json looking armed and never fired on
# the Bash write it exists to catch -- while a grep-based "is it wired?" check
# PASSED. That is the representation-vs-thing error one layer up, and it is how
# the original false-green happened. So this probe never greps for the script
# name. It parses settings.json, finds the group that CARRIES the tripwire, and
# asserts that group's matcher lists Bash. Then it runs the thing.
#
# HOW IT RUNS
# Against a TEMP COPY of .claude/, never the live tree (`--root`). It performs a
# real Bash write into the copy and requires --enforce to revert it.
#
# NEGATIVE SELF-TEST
# Phase 0 runs the same enforce pass on an UNDRIFTED copy and requires exit 0.
# If that reported drift, every later "reverted" result would be meaningless.
#
# Exit: 0 all phases pass, 1 any phase fails.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
TRIPWIRE="$ROOT/q-system/.q-system/scripts/claude-integrity-tripwire.py"
SETTINGS="$ROOT/.claude/settings.json"
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

new_copy() {
  # A standalone tree the tripwire can own: real .claude/ content, its own git
  # repo so hash-object/cat-file work, and the script path it derives --root from.
  local dst="$WORK/copy-$1"
  mkdir -p "$dst/q-system/.q-system/scripts"
  cp -R "$ROOT/.claude" "$dst/.claude"
  rm -rf "$dst/.claude/worktrees" "$dst/.claude/state" "$dst/.claude/plans"
  cp "$TRIPWIRE" "$dst/q-system/.q-system/scripts/"
  git -C "$dst" init -q 2>/dev/null
  git -C "$dst" add -A >/dev/null 2>&1
  git -C "$dst" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
  echo "$dst"
}

enforce() { KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$1" --enforce --quiet 2>&1; }

echo "== Phase 0. Negative self-test: a clean tree must NOT report drift =="
C0="$(new_copy 0)"
enforce "$C0" >/dev/null            # first run arms the baseline
OUT="$(enforce "$C0")"; RC=$?
if [ "$RC" -eq 0 ]; then
  pass "clean tree exits 0 (so a later 'reverted' means something)"
else
  fail "clean tree reported drift (rc=$RC): $OUT"
fi

echo "== Phase 1. The wiring: does the group carrying Layer 2 even see Bash? =="
# Structural, not textual. Finds the hook entry whose command invokes the
# tripwire and reports ITS OWN group's matcher. A grep for the filename would
# pass on the broken proposal; this cannot.
MATCHER="$(python3 - "$SETTINGS" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
hits = [g.get("matcher") or ""
        for groups in s.get("hooks", {}).values()
        for g in groups
        for h in g.get("hooks", [])
        if "claude-integrity-tripwire.py" in h.get("command", "")]
print(hits[0] if hits else "ABSENT")
PY
)"
case "$MATCHER" in
  ABSENT) fail "Layer 2 is not wired into .claude/settings.json at all" ;;
  *Bash*) pass "Layer 2's own group matcher lists Bash (matcher=$MATCHER)" ;;
  *)      fail "Layer 2 wired to a matcher that cannot see Bash (matcher=$MATCHER)" ;;
esac

# Same question for the template: kipi update rebuilds instance settings from it
# only, so a Bash-blind matcher there ships a dead switch to the whole fleet.
TMATCHER="$(python3 - "$ROOT/settings-template.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
hits = [g.get("matcher") or ""
        for groups in s.get("hooks", {}).values()
        for g in groups
        for h in g.get("hooks", [])
        if "claude-integrity-tripwire.py" in h.get("command", "")]
print(hits[0] if hits else "ABSENT")
PY
)"
case "$TMATCHER" in
  ABSENT) fail "Layer 2 missing from settings-template.json (ships dead to the fleet)" ;;
  *Bash*) pass "template's Layer 2 group also lists Bash (matcher=$TMATCHER)" ;;
  *)      fail "template wired Layer 2 to a Bash-blind matcher (matcher=$TMATCHER)" ;;
esac

echo "== Phase 2. The thing: a Bash write into .claude/ is reverted =="
C1="$(new_copy 1)"
enforce "$C1" >/dev/null            # arm
# The exact measured hole from the 2026-08-01 scar, run for real.
printf 'pwned\n' >> "$C1/.claude/settings.json"
touch "$C1/.claude/_probe.txt"
OUT="$(enforce "$C1")"; RC=$?
[ "$RC" -eq 2 ] && pass "drift detected and acted on (exit 2)" \
                || fail "Bash write went unnoticed (rc=$RC): $OUT"
grep -q 'pwned' "$C1/.claude/settings.json" \
  && fail "modified settings.json was NOT reverted" \
  || pass "modified settings.json reverted to sanctioned content"
[ -e "$C1/.claude/_probe.txt" ] \
  && fail "added file _probe.txt was NOT removed" \
  || pass "added file _probe.txt removed"
ls "$C1/q-system/output/claude-integrity/quarantine" >/dev/null 2>&1 \
  && pass "drifted content quarantined before revert (a false positive costs nothing)" \
  || fail "no quarantine written"

echo "== Phase 3. The sanctioned route still works after arming =="
# A guard that also blocks the legitimate path is a different outage. The
# tripwire must accept --register, the hook the applier uses to re-baseline.
C2="$(new_copy 2)"
enforce "$C2" >/dev/null
printf '\n' >> "$C2/.claude/settings.json"
python3 "$TRIPWIRE" --root "$C2" --register .claude/settings.json --quiet >/dev/null 2>&1
OUT="$(enforce "$C2")"; RC=$?
[ "$RC" -eq 0 ] && pass "a --register'd change is sanctioned, not reverted" \
                || fail "sanctioned re-baseline still reported drift (rc=$RC): $OUT"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
