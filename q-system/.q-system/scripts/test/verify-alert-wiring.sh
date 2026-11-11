#!/bin/bash
# ASK-636 wiring receipt. Checks the alert path end to end across every LIVE
# repo, and says PASS/FAIL per check rather than asserting anything in prose.
#
# "Live" means a real working repo, not a review scratch dir, worktree, or
# .prNNrev tree. Those are excluded on purpose and counted separately: they are
# inert (nothing scheduled points at one, verified below) but they carry the old
# webhook script, so they must never be confused for a live copy.
set -uo pipefail

# The fleet checkout root. A literal /Users/<founder> cannot live under
# q-system/ in this PUBLIC repo -- validate-separation.py's full skeleton sweep
# fails on one, and that failure sat invisible for days behind an earlier red
# gate (ASK-746). Default keeps the behaviour identical on the founder's machine;
# override for a differently-laid-out checkout.
FLEET_ROOT="${KIPI_FLEET_ROOT:-$HOME/projects}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n       %s\n' "$1" "${2:-}"; }

is_scratch() {
  case "$1" in
    */.git/*|*/worktrees/*|*kipi-wt-*|*_codex-worktrees*|*.pr[0-9]*rev*|\
    */.review-scratch/*|*/.fable-wt/*|*/template-repo/*|*/.review-tmp*) return 0 ;;
  esac
  return 1
}

echo "== ASK-636 alert-path wiring receipt =="
echo

# --- 1. every LIVE notify script is the Linear one ---------------------------
echo "-- 1. live notify scripts route to Linear, not the webhook"
live=0; stale=0; wrong=""
while IFS= read -r f; do
  if is_scratch "$f"; then stale=$((stale+1)); continue; fi
  live=$((live+1))
  head -3 "$f" | grep -q "Linear ticket" || wrong="$wrong$f\n"
done < <(find "$FLEET_ROOT" -name "slack-notify.sh" -not -path "*/.git/*" 2>/dev/null)
if [ -z "$wrong" ]; then
  ok "all $live live copies route to Linear ($stale scratch/worktree copies excluded)"
else
  bad "$live live copies checked, some still carry the webhook body" "$(printf "$wrong")"
fi

# --- 2. no live auto-commit still alerts -------------------------------------
echo "-- 2. auto-commit alerts nobody"
bad_ac=""
while IFS= read -r f; do
  is_scratch "$f" && continue
  grep -q "_notify_slack\|slack-notify" "$f" && bad_ac="$bad_ac$f\n"
done < <(find "$FLEET_ROOT" -name "auto-commit.py" -not -path "*/.git/*" 2>/dev/null)
[ -z "$bad_ac" ] && ok "no live auto-commit.py references the alert path" \
                 || bad "an auto-commit still alerts" "$(printf "$bad_ac")"

# --- 3. the cole carve-out is throttled --------------------------------------
echo "-- 3. cole carve-out speaks once per day"
CP=$FLEET_ROOT/cole-gtm/gtm/scripts/podcast/daily_social_publer.py
grep -q "carve-out-said" "$CP" 2>/dev/null \
  && ok "carve-out throttle present" \
  || bad "carve-out throttle missing" "$CP"

# --- 4. nothing scheduled runs from a scratch copy ---------------------------
echo "-- 4. no scheduled job points at a stale copy"
ptr=""
for p in "$HOME"/Library/LaunchAgents/*.plist; do
  a=$(/usr/libexec/PlistBuddy -c "Print :ProgramArguments" "$p" 2>/dev/null | tr '\n' ' ')
  case "$a" in
    *kipi-wt-*|*_codex-worktrees*|*rev/*|*review-scratch*|*worktrees*)
      ptr="$ptr$(basename "$p")\n" ;;
  esac
done
[ -z "$ptr" ] && ok "no launchd job runs from a scratch/worktree copy" \
              || bad "a scheduled job runs from a stale copy" "$(printf "$ptr")"

# --- 5. the pytest guard holds through the real chain ------------------------
echo "-- 5. a test cannot file a ticket (full 2-hop chain, per live repo)"
for repo in $FLEET_ROOT/consulting \
            $FLEET_ROOT/cole-gtm \
            $FLEET_ROOT/kipi-system; do
  n="$repo/q-system/.q-system/scripts/slack-notify.sh"
  [ -f "$n" ] || { bad "no notify script in $(basename "$repo")" "$n"; continue; }
  out=$(PYTEST_CURRENT_TEST="probe (call)" bash "$n" "wiring receipt probe" 2>&1)
  rc=$?
  if [ "$rc" = "4" ] && printf '%s' "$out" | grep -q REFUSED; then
    ok "$(basename "$repo"): refuses under pytest (exit 4)"
  else
    bad "$(basename "$repo"): A TEST COULD FILE A TICKET" "exit $rc: $out"
  fi
done

# HONEST LIMIT ON CHECK 6, measured not assumed: the detector below found 1 of
# the 2 posters confirmed by hand on 2026-08-10. It matches the python shape
# (name = ...slack-webhook -> urlopen(name)) reliably and the shell shape
# (VAR="$(< ...)" -> curl "$VAR") only sometimes. run_weekly.sh is a real poster
# it did NOT flag. Under-reporting is the dangerous direction for a safety
# check, so treat a clean check 6 as "no NEW python poster appeared", never as
# "nothing posts". The KNOWN list is the hand-verified record; the detector is
# a tripwire on top of it, not a replacement for it.
# --- 6. direct Slack posters: retired (RULE-2026-11-11-A, ASK-4479) ----------
# This section hunted scripts that read the old Slack webhook file and POSTed to
# it. Slack is gone from this repo (chief's own Slack code is the follow-up, ASK-4488), and q-system/.q-system/tests/test_no_slack_bots.py
# walks every tracked file for any Slack sender or reader, which is stronger than a
# same-name heuristic over one config path. Nothing is checked here on purpose.

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
