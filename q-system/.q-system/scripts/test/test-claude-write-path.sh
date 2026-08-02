#!/bin/bash
# test-claude-write-path.sh -- ASK-282, the .claude/ write path.
#
# Every case runs against a mktemp fixture tree. No case touches the live
# .claude/ (fable-discipline test isolation; the live tree is the thing under
# protection, so testing against it would be the exact mistake).
#
# The suite is in four parts:
#   A  Layer 1 blocks the ordinary write shapes
#   B  Layer 1 does not break the legitimate paths
#   C  Layer 2 baselines / detects / reverts
#   D  THE DECISIVE TEST: a write Layer 1 MISSES, that Layer 2 catches anyway,
#      plus the mutation proving Layer 2 is what caught it.
#
# Part D is the whole point. Without it this is a denylist wearing a tripwire's
# name, and we would believe we were protected when we were not.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
GUARD="$SCRIPTS/claude-path-write-guard.py"
TRIPWIRE="$SCRIPTS/claude-integrity-tripwire.py"

PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'chmod -R u+w "$WORK" 2>/dev/null; /bin/rm -r "$WORK" 2>/dev/null' EXIT

mkjson() {
  CMD="$1" CWD="$2" python3 - <<'PY'
import json, os
print(json.dumps({"tool_name": "Bash",
                  "tool_input": {"command": os.environ["CMD"]},
                  "cwd": os.environ["CWD"]}))
PY
}

# Build a disposable tree shaped like a real instance: settings.json + rules +
# agents, committed, so the tripwire can resolve git blobs for restore.
new_fixture() {
  local fix; fix="$(mktemp -d "$WORK/fixXXXXXX")"
  mkdir -p "$fix/.claude/rules" "$fix/.claude/agents" "$fix/.claude/output-styles"
  printf '{"hooks":{"PreToolUse":[]}}\n' > "$fix/.claude/settings.json"
  printf 'rule alpha\n' > "$fix/.claude/rules/alpha.md"
  printf 'agent beta\n' > "$fix/.claude/agents/beta.md"
  printf 'style gamma\n' > "$fix/.claude/output-styles/gamma.md"
  git init -q "$fix" 2>/dev/null
  git -C "$fix" add -A >/dev/null 2>&1
  git -C "$fix" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1
  printf '%s' "$fix"
}

guard_rc() { # command, cwd -> prints exit code
  local out; out="$(mkjson "$1" "$2")"
  printf '%s' "$out" | python3 "$GUARD" >/dev/null 2>&1
  printf '%s' "$?"
}

assert_block() { # desc, command [, cwd]
  local rc; rc="$(guard_rc "$2" "${3:-$FIX}")"
  [ "$rc" = "2" ] && pass "L1 blocks: $1" || fail "L1 blocks: $1 (exit $rc, expected 2)"
}

assert_allow() { # desc, command [, cwd]
  local rc; rc="$(guard_rc "$2" "${3:-$FIX}")"
  [ "$rc" = "0" ] && pass "L1 allows: $1" || fail "L1 allows: $1 (exit $rc, expected 0)"
}

FIX="$(new_fixture)"

echo "== A. Layer 1 blocks the write shapes =="
# The reproduce case from the brief -- this exact command succeeded via Bash.
assert_block "touch .claude/_probe.txt"          'touch .claude/_probe.txt'
assert_block "redirect > into settings.json"     'echo pwned > .claude/settings.json'
assert_block "append >> into a rule"             'echo pwned >> .claude/rules/alpha.md'
assert_block "cp into .claude"                   'cp /etc/hosts .claude/x'
assert_block "mv into .claude"                   'mv /tmp/x .claude/settings.json'
assert_block "sed -i in place"                   "sed -i '' s/a/b/ .claude/settings.json"  # portability-lint-skip: BSD form is the fixture INPUT, never executed
assert_block "cd .claude then write"             'cd .claude && touch evil.txt'
assert_block "path held in a variable"           'D=.claude; touch $D/evil.txt'
assert_block "\$HOME-absolute path"              'touch $HOME/.claude/evil.txt'
assert_block "python3 -c open(w)"                'python3 -c "open(\".claude/settings.json\",\"w\")"'
assert_block "tee into a rule"                   'echo pwned | tee .claude/rules/alpha.md'
# --- shapes NOT named in the brief; found while building this guard ---
assert_block "xargs (not in brief)"              'echo .claude/evil.txt | xargs touch'
assert_block "git checkout (not in brief)"       'git checkout HEAD -- .claude/settings.json'
assert_block "ln -sf symlink swap (not in brief)" 'ln -sf /dev/null .claude/settings.json'
assert_block "rsync into .claude (not in brief)" 'rsync -a /tmp/src/ .claude/rules/'
# cwd already inside .claude: the command contains no .claude token at all.
assert_block "no .claude token, cwd is inside"   'touch evil.txt' "$FIX/.claude"

echo "== B. Layer 1 does not break legitimate work =="
assert_allow "cat a settings file"               'cat .claude/settings.json'
assert_allow "grep the rules dir"                'grep -rn hook .claude/rules/'
assert_allow "ls the agents dir"                 'ls -la .claude/agents'
assert_allow "git status on .claude"             'git status .claude/'
assert_allow "git log on .claude"                'git log --oneline -- .claude/rules'
assert_allow "sanctioned applier"                'bash q-system/.q-system/scripts/apply-claude-changes.sh prop.json'
assert_allow "kipi update (writes instances)"    'bash kipi-update.sh --dry'
assert_allow "unrelated write outside .claude"   'touch /tmp/harmless.txt'
assert_allow "similarly-named dir is not .claude" 'touch my.claude-notes/x'

echo "== C. Layer 2 baseline / detect / revert =="
FIX="$(new_fixture)"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet
[ -f "$FIX/q-system/.q-system/claude-integrity-baseline.json" ] \
  && pass "baseline written" || fail "baseline written"

KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "clean tree checks green" || fail "clean tree checks green"

printf 'tampered\n' > "$FIX/.claude/rules/alpha.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "modified file detected" || fail "modified file detected"

# Negative self-test: the check must FAIL on the violation before a green result
# from it means anything.
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --enforce >/dev/null 2>&1
rc=$?
[ "$rc" = "2" ] && pass "enforce exits 2 when it acts" || fail "enforce exits 2 when it acts (got $rc)"
if grep -q 'rule alpha' "$FIX/.claude/rules/alpha.md" 2>/dev/null; then
  pass "modified file restored to sanctioned content"
else
  fail "modified file restored to sanctioned content"
fi
if ls "$FIX/q-system/output/claude-integrity/quarantine/"*/ >/dev/null 2>&1; then
  pass "drifted content quarantined, not destroyed"
else
  fail "drifted content quarantined, not destroyed"
fi

# An ADDED file is the interesting case: a new agent definition with a wide tool
# allowlist is an attack that deletes nothing.
printf 'evil agent\n' > "$FIX/.claude/agents/evil.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "added file detected" || fail "added file detected"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --enforce >/dev/null 2>&1
[ ! -f "$FIX/.claude/agents/evil.md" ] && pass "added file reverted" || fail "added file reverted"

/bin/rm -f "$FIX/.claude/rules/alpha.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "removed file detected" || fail "removed file detected"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --enforce >/dev/null 2>&1
[ -f "$FIX/.claude/rules/alpha.md" ] && pass "removed file restored" || fail "removed file restored"

# The sanctioned path re-registers what it wrote, so a legitimate apply is not
# an alarm. This is the coupling to apply-claude-changes.sh (PR #63).
printf 'legitimately changed\n' > "$FIX/.claude/rules/alpha.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --register .claude/rules/alpha.md --quiet
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "registered (sanctioned) change does not trip the wire" \
                || fail "registered (sanctioned) change does not trip the wire"

echo "== D. DECISIVE: a write Layer 1 misses, Layer 2 catches =="
# Command substitution. The path .claude never appears as a literal anywhere in
# the command; it exists only after the shell runs a subprocess. Static analysis
# of a command string cannot resolve that without executing it, and executing it
# is precisely what we are trying to prevent. This is not a patchable gap in
# Layer 1 -- it is the ceiling of what any Layer 1 can do.
FIX="$(new_fixture)"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet
EVASION='P=$(printf %s Y2xhdWRl | base64 --decode); printf pwned > ".$P/settings.json"'

rc="$(guard_rc "$EVASION" "$FIX")"
if [ "$rc" = "0" ]; then
  pass "L1 MISSES the command-substitution write (proved, exit 0)"
else
  fail "L1 MISSES the command-substitution write (exit $rc -- test is no longer decisive)"
fi

( cd "$FIX" && eval "$EVASION" ) >/dev/null 2>&1
if grep -q pwned "$FIX/.claude/settings.json" 2>/dev/null; then
  pass "the evasive write really landed in .claude/settings.json"
else
  fail "the evasive write really landed (fixture did not reproduce)"
fi

KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "L2 CATCHES what L1 missed" || fail "L2 CATCHES what L1 missed"

KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --enforce >/dev/null 2>&1
if grep -q '"hooks"' "$FIX/.claude/settings.json" 2>/dev/null \
   && ! grep -q pwned "$FIX/.claude/settings.json" 2>/dev/null; then
  pass "L2 reverted the evasive write"
else
  fail "L2 reverted the evasive write"
fi

echo "== D2. MUTATION: disable the tripwire, the evasion must go red =="
# A green test that cannot fail proves nothing. Blind the detector and confirm
# the decisive case stops passing -- otherwise something ELSE was catching it.
MUTANT="$WORK/tripwire-mutant.py"
python3 - "$TRIPWIRE" "$MUTANT" <<'PY'
import sys
src = open(sys.argv[1]).read()
# Blind diff(): report no drift, ever.
marker = '    recorded = (baseline or {}).get("entries", {})'
assert marker in src, "mutation anchor missing -- update this mutant"
src = src.replace(marker, '    return [], [], []\n' + marker, 1)
open(sys.argv[2], "w").write(src)
PY

FIX="$(new_fixture)"
KIPI_NOTIFY=/usr/bin/true python3 "$MUTANT" --root "$FIX" --baseline --quiet
( cd "$FIX" && eval "$EVASION" ) >/dev/null 2>&1
KIPI_NOTIFY=/usr/bin/true python3 "$MUTANT" --root "$FIX" --check >/dev/null 2>&1
rc=$?
if [ "$rc" = "0" ]; then
  pass "mutant is blind (evasion undetected) -- the tripwire is load-bearing"
else
  fail "mutant still detected drift (exit $rc) -- something else is doing the work"
fi

echo "== E. Bootstrap wiring: session-start.py actually surfaces drift =="
# Layer 2 is armed WITHOUT a settings.json entry by being called from
# session-start.py (already wired, and outside .claude/). Proving the tripwire
# works is not proving session-start CALLS it, so drive the real function.
FIX="$(new_fixture)"
mkdir -p "$FIX/q-system/.q-system/scripts" "$FIX/q-system/hooks"
cp "$TRIPWIRE" "$FIX/q-system/.q-system/scripts/"
cp "$SCRIPTS/../../hooks/session-start.py" "$FIX/q-system/hooks/"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet

SS_PROBE="$WORK/ss_probe.py"
cat > "$SS_PROBE" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ss", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("BANNER" if mod.check_claude_integrity(sys.argv[2]).strip() else "SILENT")
PY

out="$(KIPI_NOTIFY=/usr/bin/true python3 "$SS_PROBE" "$FIX/q-system/hooks/session-start.py" "$FIX" 2>/dev/null)"
[ "$out" = "SILENT" ] && pass "clean tree -> session-start says nothing" \
                      || fail "clean tree -> session-start says nothing (got $out)"

printf 'pwned\n' > "$FIX/.claude/rules/alpha.md"
out="$(KIPI_NOTIFY=/usr/bin/true python3 "$SS_PROBE" "$FIX/q-system/hooks/session-start.py" "$FIX" 2>/dev/null)"
[ "$out" = "BANNER" ] && pass "drifted tree -> session-start surfaces the banner" \
                      || fail "drifted tree -> session-start surfaces the banner (got $out)"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
