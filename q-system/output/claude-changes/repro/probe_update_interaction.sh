#!/usr/bin/env bash
# probe_update_interaction.sh -- does arming Layer 2 break `kipi update`? ASK-291.
#
# THE QUESTION THIS ANSWERS
# Layer 2 is an AUTO-REVERTING control and `kipi update` REWRITES both halves of
# its watch set on 23 machines: the q-system rsync (kipi-update.sh:1295) replaces
# the two EXTRA_WATCHED guard scripts, then settings.json is regenerated from
# settings-template.json and rules/, agents/, output-styles/ are copied over.
# Both are true, so the interaction has to be measured before a fleet rollout,
# not reasoned about. This is the reason the safe half was deliberately NOT
# shipped early.
#
# THE FAILURE IT REPRODUCES
# Instance updates, then the next tool call fires the PostToolUse tripwire, which
# sees the updated files as unsanctioned drift and REVERTS them. The instance
# silently rolls back to its pre-update config and nothing reports it -- the
# updater says OK and the update is gone. Across 23 machines.
#
# WHY THE FIX IS A RE-BASELINE AND NOT AN EXCLUSION
# `kipi update` is a reviewed path: its content comes from the skeleton's git
# HEAD. That is exactly the provenance the tripwire's own `attributable()` treats
# as sanctioned. So the updater re-baselines what it just wrote, the same way the
# applier re-registers what IT just wrote. Excluding .claude/settings.json from
# the watch set instead would hand back the whole hole.
#
# WHAT ROUND 14 CHANGED HERE (review finding, minor, and it was right):
# this probe could not fail for the fix that shipped. Three reasons, all in the
# file: the fixture never carried claude-path-write-guard.py, so the half of the
# watch set that lives OUTSIDE .claude/ was structurally invisible; the simulated
# update never wrote q-system/, so the fixture's shape did not match the
# producer's; and phase 4 regex-matched `--baseline|--register` inside a 9-line
# window, so emptying the register list left every phase green. All three are
# closed below: the fixture takes a FULL sync, and phases 2 and 4 EXECUTE the
# register-list block cut out of kipi-update.sh instead of describing it.
#
# NEGATIVE SELF-TEST: phase 1 requires the UNPATCHED behaviour to actually revert.
# If a simulated update did not trip the tripwire, phase 2's "no revert" would
# prove nothing.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
TRIPWIRE="$ROOT/q-system/.q-system/scripts/claude-integrity-tripwire.py"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
UPDATER="$ROOT/kipi-update.sh"
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The updater's own register-list code, cut out of the file and run here. Not a
# transcription and not a regex: editing that block changes this probe's answer.
awk '/^ *TRIPWIRE_WROTE=\(\)/{on=1} on&&/KIPI_NOTIFY=/{on=0} on' "$UPDATER" \
  > "$WORK/wrote-block.sh"

register_list() { # instance -> the paths kipi-update.sh would sanction
  (
    set -u
    path="$1"; SCRIPT_DIR="$ROOT"
    # shellcheck disable=SC1090
    . "$WORK/wrote-block.sh"
    printf '%s\n' "${TRIPWIRE_WROTE[@]}"
  ) 2>/dev/null
}

# A stand-in instance: armed tripwire, real .claude/ content, BOTH guard scripts
# (they are the tripwire's EXTRA_WATCHED, i.e. the half of the watch set that
# lives outside .claude/), own git repo.
new_instance() {
  local d="$WORK/inst-$1"
  mkdir -p "$d/q-system/.q-system/scripts"
  cp -R "$ROOT/.claude" "$d/.claude"
  rm -rf "$d/.claude/worktrees" "$d/.claude/state" "$d/.claude/plans"
  cp "$TRIPWIRE" "$GUARD" "$d/q-system/.q-system/scripts/"
  git -C "$d" init -q
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
  KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$d" --enforce --quiet >/dev/null 2>&1
  echo "$d"
}

# What kipi update actually does to an instance, in the producer's order:
# q-system/ first (the rsync replaces both guard scripts), then .claude/
# (settings.json from the template, then rules/). Not a call into kipi-update.sh,
# which would need a registered instance and a full archive; the WRITES are the
# part that matters, and their SHAPE now matches the producer's.
simulate_update() {
  printf '\n# propagated by kipi update\n' >> "$1/q-system/.q-system/scripts/claude-path-write-guard.py"
  printf '\n# propagated by kipi update\n' >> "$1/q-system/.q-system/scripts/claude-integrity-tripwire.py"
  python3 - "$1" "$ROOT" <<'PY'
import json, os, sys
inst, root = sys.argv[1], sys.argv[2]
s = json.load(open(os.path.join(inst, ".claude", "settings.json")))
s.setdefault("hooks", {}).setdefault("SessionStart", [])
s["_kipi_update_marker"] = "propagated-from-skeleton"
with open(os.path.join(inst, ".claude", "settings.json"), "w") as fh:
    json.dump(s, fh, indent=2)
rules = os.path.join(inst, ".claude", "rules")
if os.path.isdir(rules):
    p = os.path.join(rules, "coding-standards.md")
    open(p, "a").write("\n<!-- propagated by kipi update -->\n")
PY
  # The updater commits the synced tree before it sanctions (guarded_commit at
  # kipi-update.sh:1316). Without this the tripwire's git-attribution branch
  # would never be exercised, and phase 1 would trip for the wrong reason.
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" -c user.email=t@t -c user.name=t commit -qm sync >/dev/null 2>&1
}

enforce() { KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$1" --enforce --quiet >/dev/null 2>&1; echo $?; }
updated() { grep -q '_kipi_update_marker' "$1/.claude/settings.json" && echo yes || echo no; }
guard_updated() { grep -q 'propagated by kipi update' "$1/q-system/.q-system/scripts/claude-path-write-guard.py" && echo yes || echo no; }

echo "== Phase 1. Negative self-test: WITHOUT a re-baseline the update is not clean =="
A="$(new_instance a)"
simulate_update "$A"
[ "$(updated "$A")" = "yes" ] && pass "the simulated update landed" || fail "update did not land"
RC="$(enforce "$A")"
[ "$RC" -ne 0 ] && pass "tripwire acted on the update (rc=$RC)" \
                || fail "tripwire did not act (rc=$RC) -- phase 2 would prove nothing"

echo "== Phase 2. WITH the register the update survives, both halves of the watch set =="
B="$(new_instance b)"
simulate_update "$B"
# The fix, exactly as kipi-update.sh performs it: the list its own code builds,
# passed to --register, immediately after writing and before any tool call.
# shellcheck disable=SC2046
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$B" --quiet \
  --register $(register_list "$B" | tr '\n' ' ') >/dev/null 2>&1
RC="$(enforce "$B")"
[ "$RC" -eq 0 ] && pass "no drift after the register (exit 0)" \
                || fail "still reported drift (rc=$RC)"
RC="$(enforce "$B")"
[ "$RC" -eq 0 ] && pass "and it stays clean -- not a permanent SECURITY banner" \
                || fail "SECURITY drift is permanent (rc=$RC) -- 23 machines"
[ "$(updated "$B")" = "yes" ] \
  && pass "the update survives: settings.json still carries the propagated change" \
  || fail "update was reverted despite the register"
[ "$(guard_updated "$B")" = "yes" ] \
  && pass "the update survives in q-system/ too: the guard script kept its change" \
  || fail "the synced guard script was reverted (EXTRA_WATCHED was not sanctioned)"

echo "== Phase 3. The register does not blind the tripwire =="
# Sanctioning what the UPDATER wrote must not sanction everything forever.
printf 'pwned\n' >> "$B/.claude/settings.json"
RC="$(enforce "$B")"
[ "$RC" -eq 2 ] && pass "a post-update tamper is still caught (exit 2)" \
                || fail "tripwire went blind after the register (rc=$RC)"
grep -q 'pwned' "$B/.claude/settings.json" \
  && fail "tamper was NOT reverted" \
  || pass "tamper reverted; the tripwire is still armed"

echo "== Phase 4. The list kipi-update.sh BUILDS covers everything it wrote =="
# Structural and executable, not a regex over a window: the block is run, and its
# output is compared against the watch set the tripwire itself declares. Emptying
# TRIPWIRE_WROTE, or adding a watched file outside .claude/ without adding it to
# the list, turns this red.
C="$(new_instance c)"
register_list "$C" > "$WORK/list-c"
if [ -s "$WORK/list-c" ]; then
  pass "the register-list block is present and produces a list"
else
  fail "the register-list block produced nothing (the fleet outage above is live)"
fi
MISSING=""
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  grep -qxF "$rel" "$WORK/list-c" || MISSING="$MISSING $rel"
done < <(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print("\n".join(mod.EXTRA_WATCHED))
' "$TRIPWIRE")
[ -z "$MISSING" ] \
  && pass "every EXTRA_WATCHED path the tripwire declares is in the register list" \
  || fail "register list omits EXTRA_WATCHED:$MISSING"
grep -qxF ".claude/settings.json" "$WORK/list-c" \
  && pass ".claude/settings.json is in the register list" \
  || fail "settings.json is not sanctioned; the update will be reverted"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
