#!/usr/bin/env bash
# probe_update_interaction.sh -- does arming Layer 2 break `kipi update`? ASK-291.
#
# THE QUESTION THIS ANSWERS
# Layer 2 is an AUTO-REVERTING control and `kipi update` REWRITES .claude/ from
# the skeleton on 23 machines (kipi-update.sh:1367 regenerates settings.json from
# settings-template.json; the loop below it copies rules/, agents/,
# output-styles/). Both are true, so the interaction has to be measured before a
# fleet rollout, not reasoned about. This is the reason the safe half was
# deliberately NOT shipped early.
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
# NEGATIVE SELF-TEST: phase 1 requires the UNPATCHED behaviour to actually revert.
# If a simulated update did not trip the tripwire, phase 2's "no revert" would
# prove nothing.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
TRIPWIRE="$ROOT/q-system/.q-system/scripts/claude-integrity-tripwire.py"
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# A stand-in instance: armed tripwire, real .claude/ content, own git repo.
new_instance() {
  local d="$WORK/inst-$1"
  mkdir -p "$d/q-system/.q-system/scripts"
  cp -R "$ROOT/.claude" "$d/.claude"
  rm -rf "$d/.claude/worktrees" "$d/.claude/state" "$d/.claude/plans"
  cp "$TRIPWIRE" "$d/q-system/.q-system/scripts/"
  git -C "$d" init -q
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
  KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$d" --enforce --quiet >/dev/null 2>&1
  echo "$d"
}

# What kipi update actually does to .claude/: rewrite settings.json from the
# template, then copy rules/ over. Not a call into kipi-update.sh, which would
# need a registered instance and a full rsync; the WRITE is the part that matters.
simulate_update() {
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
}

enforce() { KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$1" --enforce --quiet >/dev/null 2>&1; echo $?; }
updated() { grep -q '_kipi_update_marker' "$1/.claude/settings.json" && echo yes || echo no; }

echo "== Phase 1. Negative self-test: WITHOUT a re-baseline the update is reverted =="
A="$(new_instance a)"
simulate_update "$A"
[ "$(updated "$A")" = "yes" ] && pass "the simulated update landed" || fail "update did not land"
RC="$(enforce "$A")"
[ "$RC" -eq 2 ] && pass "tripwire acted on the update (exit 2)" \
                || fail "tripwire did not act (rc=$RC) -- phase 2 would prove nothing"
[ "$(updated "$A")" = "no" ] \
  && pass "CONFIRMED OUTAGE: kipi update silently rolled back by the tripwire" \
  || fail "expected the update to be reverted, it survived"

echo "== Phase 2. WITH the re-baseline the update survives =="
B="$(new_instance b)"
simulate_update "$B"
# The fix, as kipi-update.sh performs it: re-baseline the instance's .claude/
# immediately after writing it, before any tool call can fire the enforcer.
python3 "$TRIPWIRE" --root "$B" --baseline --quiet >/dev/null 2>&1
RC="$(enforce "$B")"
[ "$RC" -eq 0 ] && pass "no drift after the re-baseline (exit 0)" \
                || fail "still reported drift (rc=$RC)"
[ "$(updated "$B")" = "yes" ] \
  && pass "the update survives: settings.json still carries the propagated change" \
  || fail "update was reverted despite the re-baseline"

echo "== Phase 3. The re-baseline does not blind the tripwire =="
# A re-baseline must sanction what the UPDATER wrote, not everything forever.
printf 'pwned\n' >> "$B/.claude/settings.json"
RC="$(enforce "$B")"
[ "$RC" -eq 2 ] && pass "a post-update tamper is still caught (exit 2)" \
                || fail "tripwire went blind after the re-baseline (rc=$RC)"
grep -q 'pwned' "$B/.claude/settings.json" \
  && fail "tamper was NOT reverted" \
  || pass "tamper reverted; the tripwire is still armed"

echo "== Phase 4. kipi-update.sh actually carries the re-baseline =="
# Structural, not a grep for the word: parse out the invocation and require it
# to name the tripwire with a baseline-class flag.
if python3 - "$ROOT/kipi-update.sh" <<'PY'
import re, sys
lines = open(sys.argv[1]).read().splitlines()
# CODE lines only. A comment naming the script is documentation, not wiring --
# and reading one as wiring is the same representation-vs-thing error the whole
# issue is about (this probe made it on its first run).
hits = [(i, l) for i, l in enumerate(lines)
        if "claude-integrity-tripwire.py" in l and not l.lstrip().startswith("#")]
if not hits:
    sys.exit("no tripwire invocation in kipi-update.sh (only comments, if any)")
for i, line in hits:
    window = "\n".join(lines[max(0, i - 4): i + 5])
    if re.search(r"--baseline|--register", window):
        print("     invocation at line %d: %s" % (i + 1, line.strip()))
        break
else:
    sys.exit("tripwire invoked without --baseline/--register: %s" % hits[0][1].strip())
PY
then pass "kipi-update.sh re-baselines the instance tripwire after rewriting .claude/"
else fail "kipi-update.sh does not re-baseline (the fleet outage above is live)"
fi

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
