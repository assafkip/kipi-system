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
REPO_ROOT="$(cd "$SCRIPTS/../../.." && pwd)"

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

mv "$FIX/.claude/rules/alpha.md" "$WORK/aside-$RANDOM.md"
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
# fable-discipline-lint-skip -- $TRIPWIRE is READ AS TEXT here (open(argv[1])) to
# build the mutant; it is never executed, so it cannot reach the notifier. The two
# invocations that DO run it (lines below) both stub KIPI_NOTIFY.
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

echo "== F. Round-2 review findings (each FAILS against the round-1 code) =="

# F1 MINOR: SANCTIONED was a substring match on the raw segment, so merely
# MENTIONING a sanctioned script disarmed Layer 1 for that statement.
FIX="$(new_fixture)"
assert_block "sanctioned name in a comment does not disarm" \
  'touch .claude/evil.txt  # kipi-update.sh'
assert_block "sanctioned name in an argument does not disarm" \
  'cp kipi-update.sh .claude/settings.json'
assert_allow "really running the sanctioned applier still works" \
  'bash q-system/.q-system/scripts/apply-claude-changes.sh prop.json'

# F1b BLOCKER (round 6, then round 7): the sanctioned early-return skipped every
# argument, so anything the SHELL runs before the exec was never judged. Round 6
# closed `$(...)`/backticks; round 7 closed the process-substitution twin, which
# runs the same way and reaches the tree the same way. Full reproducer with the
# end-to-end tamper-then-baseline demo and a negative self-test:
# q-system/output/claude-changes/repro/probe_round{6,7}_findings.sh
assert_block "command substitution behind a sanctioned argv" \
  'bash q-system/.q-system/scripts/apply-claude-changes.sh "$(touch .claude/evil.txt)"'
assert_block "process substitution behind a sanctioned argv" \
  'bash q-system/.q-system/scripts/apply-claude-changes.sh <(touch .claude/evil.txt)'
assert_block "output process substitution the redirect scan cannot read" \
  'bash q-system/.q-system/scripts/apply-claude-changes.sh p.json > >(rm .claude/rules/alpha.md)'
# Inert inside BOTH quote kinds, unlike `$(`. Measured against bash itself; see
# the extract_substitutions docstring. Judging inert text is the false-block
# class this issue hit five times -- it would refuse this very test file.
assert_allow "double-quoted process substitution is inert text" \
  'echo "<(touch .claude/evil.txt)"'

# F2 MINOR: the redirect regex required whitespace before '>'.
assert_block "redirect with no space before >" 'printf pwned>.claude/settings.json'
assert_block "append with no space before >>" 'printf pwned>>.claude/rules/alpha.md'
assert_allow "2>&1 is not a path"              'ls -la .claude 2>&1'

# F3 MINOR: EXCLUDED_DIRS was pruned at EVERY depth, hiding loadable artifacts
# under any nested dir that happened to be named state/ or plans/.
FIX="$(new_fixture)"
mkdir -p "$FIX/.claude/skills/plans" "$FIX/.claude/commands/state"
printf 'loadable skill\n' > "$FIX/.claude/skills/plans/SKILL.md"
printf 'loadable command\n' > "$FIX/.claude/commands/state/cmd.md"
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm nested >/dev/null 2>&1
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet
printf 'tampered\n' > "$FIX/.claude/skills/plans/SKILL.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "nested .claude/skills/plans/ IS watched" \
                || fail "nested .claude/skills/plans/ IS watched"
printf 'tampered\n' > "$FIX/.claude/commands/state/cmd.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "nested .claude/commands/state/ IS watched" \
                || fail "nested .claude/commands/state/ IS watched"
# Top-level volatile dirs must STILL be excluded, or the fix trades one false
# alarm for another.
FIX="$(new_fixture)"
mkdir -p "$FIX/.claude/state"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet
printf 'churn\n' > "$FIX/.claude/state/active-issue.json"
printf 'churn\n' > "$FIX/.claude/settings.local.json"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "top-level state/ + settings.local.json still excluded" \
                || fail "top-level state/ + settings.local.json still excluded"

# F4 MAJOR: the restore path wrote THROUGH a symlink, overwriting an arbitrary
# file outside .claude/ and reporting success. This is the decisive round-2 test.
FIX="$(new_fixture)"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --baseline --quiet
VICTIM="$WORK/victim-outside-claude.txt"
printf 'PRECIOUS UNRELATED FILE\n' > "$VICTIM"
mv "$FIX/.claude/rules/alpha.md" "$WORK/aside-$RANDOM.md"
ln -s "$VICTIM" "$FIX/.claude/rules/alpha.md"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --enforce >/dev/null 2>&1
if grep -q 'PRECIOUS UNRELATED FILE' "$VICTIM"; then
  pass "symlink swap does NOT clobber the file outside .claude/"
else
  fail "symlink swap does NOT clobber the file outside .claude/ (ARBITRARY WRITE)"
fi
[ ! -L "$FIX/.claude/rules/alpha.md" ] && pass "symlink itself was removed, not left in place" \
                                       || fail "symlink itself was removed, not left in place"
if grep -q 'rule alpha' "$FIX/.claude/rules/alpha.md" 2>/dev/null; then
  pass "sanctioned content restored as a real file"
else
  fail "sanctioned content restored as a real file"
fi
# find, not a glob: the quarantined name starts with a dot
# (.claude__rules__alpha.md.SYMLINK) and shell globs skip leading-dot files.
if [ -n "$(find "$FIX/q-system/output/claude-integrity" -name '*.SYMLINK' 2>/dev/null)" ]; then
  pass "symlink target recorded as evidence"
else
  fail "symlink target recorded as evidence"
fi

# F5 MAJOR: no baseline must ARM silently, never alarm. A committed/propagated
# baseline would have paged every instance daily.
FIX="$(new_fixture)"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "first run arms silently (no fleet-wide daily page)" \
                || fail "first run arms silently (no fleet-wide daily page)"
[ -f "$FIX/q-system/.q-system/claude-integrity-baseline.json" ] \
  && pass "first run actually wrote a baseline" || fail "first run actually wrote a baseline"
KIPI_NOTIFY=/usr/bin/true python3 "$TRIPWIRE" --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "second run is clean, not a repeat alarm" \
                || fail "second run is clean, not a repeat alarm"
# The baseline must never be committed: a propagated baseline is the defect.
if git -C "$REPO_ROOT" ls-files --error-unmatch \
     q-system/.q-system/claude-integrity-baseline.json >/dev/null 2>&1; then
  fail "baseline is NOT tracked by git (it would propagate via kipi update)"
else
  pass "baseline is NOT tracked by git (it would propagate via kipi update)"
fi

# F6 MAJOR: the only armed trigger sat behind a machine-wide daily sentinel.
# Compare line numbers, not an awk range: the range version ended at the word
# "already_ran_today" inside the explanatory comment and never reached the call.
SS="$SCRIPTS/../../hooks/session-start.py"
L_INT="$(grep -n 'integrity_warning = check_claude_integrity' "$SS" | head -1 | cut -d: -f1)"
L_SENT="$(grep -n 'if already_ran_today()' "$SS" | head -1 | cut -d: -f1)"
if [ -n "$L_INT" ] && [ -n "$L_SENT" ] && [ "$L_INT" -lt "$L_SENT" ]; then
  pass "session-start runs the tripwire BEFORE the daily sentinel (L$L_INT < L$L_SENT)"
else
  fail "session-start runs the tripwire BEFORE the daily sentinel (L$L_INT vs L$L_SENT)"
fi

echo "== G. Round-3 findings: the re-baseline path =="
# A notifier that RECORDS, so "did it page?" is an assertion and not a vibe.
PAGES="$WORK/pages.log"
cat > "$WORK/fake-notify.sh" <<'PY'
#!/bin/bash
printf '%s\n' "$1" >> "$PAGES_FILE"
PY
chmod +x "$WORK/fake-notify.sh"
tw() { PAGES_FILE="$PAGES" KIPI_NOTIFY="$WORK/fake-notify.sh" python3 "$TRIPWIRE" "$@"; }
pagecount() { [ -f "$PAGES" ] && wc -l < "$PAGES" | tr -d ' ' || echo 0; }

# G1: a legitimate change that landed through git (pull / checkout / merge, and
# `kipi update`, which commits into each instance) must RE-BASELINE ITSELF.
#
# The fixture grows a REMOTE in round 5. Rounds 3-4 committed locally with no
# remote at all and called that "git-landed", which passed only because --check
# absorbed on any branch. That leniency was the round-5 finding: --enforce HELD
# an agent's committed tamper and the next --check sanctioned it permanently.
# Both modes now ask the same question -- is HEAD contained in a remote's
# DEFAULT branch -- so the fixture has to model the artifact it claims to model.
# The assertion is unchanged: a pull must not page, ever, or the alarm is noise.
FIX="$(new_fixture)"; : > "$PAGES"
gitq() { git -C "$FIX" -c user.email=t@t -c user.name=t "$@" >/dev/null 2>&1; }
ORIGIN="$FIX-origin.git"; git init --bare -q -b main "$ORIGIN"
gitq remote add origin "$ORIGIN"
gitq push -u origin HEAD:main
gitq remote set-head origin main
tw --root "$FIX" --baseline --quiet
printf 'legitimately updated rule\n' > "$FIX/.claude/rules/alpha.md"
gitq add -A
gitq commit -qm "pull"
gitq push origin HEAD:main
tw --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "git-landed change re-baselines itself (no alarm)" \
                || fail "git-landed change re-baselines itself (no alarm)"
[ "$(pagecount)" = "0" ] && pass "git-landed change pages ZERO times" \
                         || fail "git-landed change pages ZERO times (got $(pagecount))"
tw --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "0" ] && pass "and stays clean on the next session (not permanent drift)" \
                || fail "and stays clean on the next session (not permanent drift)"

# G1b (round 5): the same change committed on a branch NO remote default
# contains is NOT sanctioned provenance. --check reports it instead of absorbing
# it, so it cannot quietly undo a hold --enforce already decided on.
FIX="$(new_fixture)"; : > "$PAGES"
gitq() { git -C "$FIX" -c user.email=t@t -c user.name=t "$@" >/dev/null 2>&1; }
ORIGIN="$FIX-origin.git"; git init --bare -q -b main "$ORIGIN"
gitq remote add origin "$ORIGIN"
gitq push -u origin HEAD:main
gitq remote set-head origin main
tw --root "$FIX" --baseline --quiet
gitq checkout -b agent/tamper
printf 'committed tamper\n' > "$FIX/.claude/rules/alpha.md"
gitq commit -qam tamper
gitq push origin agent/tamper
tw --root "$FIX" --check --quiet >/dev/null 2>&1
[ "$?" = "1" ] && pass "committed tamper off the default branch is NOT absorbed" \
                || fail "committed tamper off the default branch is NOT absorbed"
tw --root "$FIX" --enforce --quiet >/dev/null 2>&1
[ "$?" = "1" ] && pass "--enforce still holds it after --check ran" \
                || fail "--enforce still holds it after --check ran"

# G2: unattributed drift still alarms -- but ONCE, not every session forever.
FIX="$(new_fixture)"; : > "$PAGES"
tw --root "$FIX" --baseline --quiet
printf 'pwned\n' > "$FIX/.claude/rules/alpha.md"
tw --root "$FIX" --check >/dev/null 2>&1
[ "$?" = "1" ] && pass "uncommitted tamper still detected" || fail "uncommitted tamper still detected"
[ "$(pagecount)" = "1" ] && pass "tamper pages once" || fail "tamper pages once (got $(pagecount))"
tw --root "$FIX" --check >/dev/null 2>&1
tw --root "$FIX" --check >/dev/null 2>&1
[ "$(pagecount)" = "1" ] && pass "identical drift does NOT re-page (3 sessions, 1 page)" \
                         || fail "identical drift does NOT re-page (got $(pagecount))"
printf 'pwned differently\n' > "$FIX/.claude/rules/alpha.md"
tw --root "$FIX" --check >/dev/null 2>&1
[ "$(pagecount)" = "2" ] && pass "NEW drift does page again" || fail "NEW drift does page again (got $(pagecount))"

# G3: --enforce against an UNPUSHED commit -- the agent-writes-then-commits
# shape. Round 3 reverted it and this test pinned that. The round-2 review of
# PR #85 falsified the reasoning, not the goal: round 3 decided "in --enforce
# the actor is provably the agent" against a surface that did not exist yet,
# and THIS PR wires --enforce PostToolUse on Bash, where the actor of a
# `git pull` is git delivering reviewed remote content. Measured: the pull
# silently un-applied itself and left the worktree disagreeing with HEAD three
# ways, on every machine that adopts it.
#
# The contract is now three-tier and this pins the MIDDLE tier: content equal
# to HEAD on an UNPUSHED commit is HELD -- paged and reported (rc=1), never
# reverted, so --enforce never leaves the tree inconsistent with HEAD. It is
# not sanctioned either: nothing is absorbed and the alarm still fires, so the
# attack is visible rather than waved through. The reviewed tier (HEAD
# contained in a remote-tracking ref -> absorbed, rc=0) needs a real remote to
# express, so probe_round3_findings.sh phase 1 owns it.
FIX="$(new_fixture)"; : > "$PAGES"
tw --root "$FIX" --baseline --quiet
printf 'agent tampered then committed\n' > "$FIX/.claude/rules/alpha.md"
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" -c user.email=t@t -c user.name=t commit -qm "agent commit" >/dev/null 2>&1
tw --root "$FIX" --enforce >/dev/null 2>&1
[ "$?" = "1" ] && pass "--enforce on an unpushed commit reports instead of reverting" \
                || fail "--enforce on an unpushed commit reports instead of reverting"
[ "$(pagecount)" = "1" ] && pass "an unpushed-commit change still pages (not sanctioned)" \
                         || fail "an unpushed-commit change still pages (got $(pagecount))"
grep -q 'agent tampered then committed' "$FIX/.claude/rules/alpha.md" \
  && pass "--enforce leaves the worktree consistent with HEAD" \
  || fail "--enforce leaves the worktree consistent with HEAD"

# G3b: NEGATIVE SELF-TEST. An UNCOMMITTED shell write matches no HEAD state, so
# the full quarantine-and-revert must still fire. Without this, G3 would pass
# just as well on a tripwire that had stopped enforcing altogether.
printf 'uncommitted tamper\n' > "$FIX/.claude/rules/alpha.md"
tw --root "$FIX" --enforce >/dev/null 2>&1
[ "$?" = "2" ] && pass "NEGATIVE: an uncommitted write is still reverted" \
                || fail "NEGATIVE: an uncommitted write is still reverted"
grep -q 'rule alpha' "$FIX/.claude/rules/alpha.md" \
  && pass "NEGATIVE: reverted to the sanctioned baseline content" \
  || fail "NEGATIVE: reverted to the sanctioned baseline content"

# G4: concurrent first-run --check must not crash on a shared temp path.
FIX="$(new_fixture)"
for i in 1 2 3 4 5 6 7 8; do tw --root "$FIX" --check --quiet >/dev/null 2>>"$WORK/conc.err" & done
wait
if grep -q 'Traceback' "$WORK/conc.err" 2>/dev/null; then
  fail "8 concurrent first-run checks, no crash"
else
  pass "8 concurrent first-run checks, no crash"
fi

# G5: a crash must be reported as a crash, never as a security event.
CRASHER="$WORK/crasher.py"
printf 'import sys\nsys.stderr.write("Traceback (most recent call last):\\n")\nsys.exit(1)\n' > "$CRASHER"
FIX="$(new_fixture)"
mkdir -p "$FIX/q-system/.q-system/scripts" "$FIX/q-system/hooks"
cp "$CRASHER" "$FIX/q-system/.q-system/scripts/claude-integrity-tripwire.py"
cp "$SCRIPTS/../../hooks/session-start.py" "$FIX/q-system/hooks/"
BANNER="$(PAGES_FILE="$PAGES" KIPI_NOTIFY="$WORK/fake-notify.sh" python3 - \
  "$FIX/q-system/hooks/session-start.py" "$FIX" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ss", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print(mod.check_claude_integrity(sys.argv[2]))
PY
)"
case "$BANNER" in
  *"NOT a security finding"*) pass "a crashing tripwire reports a malfunction, not SECURITY" ;;
  *) fail "a crashing tripwire reports a malfunction, not SECURITY (got: ${BANNER:0:60})" ;;
esac
case "$BANNER" in
  *SECURITY*) fail "crash banner must not contain the word SECURITY" ;;
  *) pass "crash banner must not contain the word SECURITY" ;;
esac

echo "== H. Round-3 Layer 1 minors =="
FIX="$(new_fixture)"
assert_block "quoted redirect target"      'echo pwned > ".claude/settings.json"'
assert_block "single-quoted redirect"      "echo pwned > '.claude/settings.json'"
assert_block "git config -f writes"        'git config -f .claude/settings.json user.x y'
assert_block "git worktree add writes"     'git worktree add .claude/wt'
assert_allow "git status still allowed"    'git status .claude/'

echo "== I. ASK-291: one watch set across both layers =="
# The two layers must agree on WHICH paths are protected. Layer 1 blocking a
# path Layer 2 refuses to watch is the wedge that killed git commit from an
# agent worktree (sp-2b9372f6); Layer 1 allowing a path Layer 2 DOES watch would
# be a hole. Both directions are the same defect: two definitions of one set.
# This is the single-writer enforcement -- the constant is duplicated for hook
# speed, so the equality is pinned by a test rather than by a comment.
SETS_EQ="$(python3 - "$SCRIPTS" <<'PY'
import importlib.util, sys, os
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod
d = sys.argv[1]
l1 = load("l1", os.path.join(d, "claude-path-write-guard.py")).EXCLUDED_DIRS
l2 = load("l2", os.path.join(d, "claude-integrity-tripwire.py")).EXCLUDED_DIRS
print("EQUAL" if l1 == l2 else "DIVERGED l1=%s l2=%s" % (sorted(l1), sorted(l2)))
PY
)"
case "$SETS_EQ" in
  EQUAL) pass "L1 EXCLUDED_DIRS == L2 EXCLUDED_DIRS" ;;
  *)     fail "L1/L2 watch sets diverged: $SETS_EQ" ;;
esac

# The exclusion is for scratch UNDER a volatile dir, not for the dir itself.
assert_allow "scratch under .claude/worktrees/ is allowed" \
  'touch .claude/worktrees/opus-fallback/scratch.txt'
assert_allow "scratch under .claude/state/ is allowed" \
  'echo x > .claude/state/run.json'
assert_block ".claude/worktrees itself is still protected" \
  'rm -rf .claude/worktrees'
assert_block "watched subtree still protected under a scratch NAME" \
  'touch .claude/rules/worktrees.md'

# --- round 8: a re-baseline in the same command voids the handoff to Layer 2 ---
# Layer 1 hands an UNANCHORABLE `.claude/` write to Layer 2 because the file
# lands and the hash moves. `--register` / `--baseline` in the SAME tool call
# records the tamper as trusted before any PostToolUse hook runs, so the backstop
# reports clean. Both layers defeated, no alarm (review finding, PR #85 round 8).
TRIP=q-system/.q-system/scripts/claude-integrity-tripwire.py
APPLY=q-system/.q-system/scripts/apply-claude-changes.sh

assert_block "unanchorable write + --register in one command" \
  "touch \$UNSET/.claude/rules/pwn.md; python3 $TRIP --register .claude/rules/pwn.md"
assert_block "same pair, re-baseline first (order-independent)" \
  "python3 $TRIP --register .claude/rules/pwn.md; touch \$UNSET/.claude/rules/pwn.md"
assert_block "unanchorable redirect + blanket --baseline" \
  "printf pwned > \$UNSET/.claude/rules/pwn.md; python3 $TRIP --baseline"
assert_block "unanchorable write inside <( ), re-baseline outside" \
  "python3 $TRIP --register .claude/rules/pwn.md <(touch \$UNSET/.claude/rules/pwn.md)"
assert_block "unanchorable write && the applier, which re-baselines" \
  "touch \$UNSET/.claude/agents/pwn.md && bash $APPLY proposal.json"

# The void reaches ONLY tokens that took the handoff. Everything below kept
# working, and each line is one of the false blocks that has nearly killed this
# guard: the handoff itself when nothing erases the backstop, the temp-dir
# fixture, and any path this parser CAN anchor.
assert_allow "unanchorable write alone still hands off to Layer 2" \
  'touch $UNSET/.claude/rules/pwn.md'
assert_allow "re-baseline alone" \
  "python3 $TRIP --register .claude/rules/x.md"
assert_allow "temp-dir fixture tree beside nothing" \
  'D=$(mktemp -d); mkdir -p "$D/.claude/rules"'
assert_allow "resolvable /tmp fixture beside a re-baseline" \
  "mkdir -p /tmp/x/.claude/rules; python3 $TRIP --register .claude/rules/x.md"

# --- round 9: with no backstop left, only a plain literal is readable ---------
# Round 8 voided the handoff, but acted only where a literal `.claude` tail was
# still VISIBLE. `${!V}` hides the whole component in the variable, and
# UNRESOLVED enumerated expansion SHAPES rather than the alphabet, so the token
# was anchored to a fabricated path carrying no `.claude` at all: rc=0, both
# layers defeated (review finding, PR #85 round 9).
#
# Two changes hold these. UNRESOLVED now tests the ALPHABET -- every shell
# expansion is introduced by `$` or a backtick and by nothing else -- and inside
# a re-baselining command a token that is not a plain literal is refused without
# any expansion reasoning at all. Nine spellings, one rule; the list is here so
# the next person sees it is a CLASS and does not close them one at a time.
assert_block "indirect expansion + same-command --baseline" \
  "P=.claude; V=P; touch \${!V}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "default-value expansion" \
  "touch \${UNSET:-.claude}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "substring-replacement expansion" \
  "P=xclaude; touch \${P/x/.}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "array-subscript expansion" \
  "A=(.claude); touch \${A[0]}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "ANSI-C quoting" \
  "touch \$'.clau''de'/rules/pwn.md; python3 $TRIP --baseline"
assert_block "glob that expands to .claude" \
  "touch .clau*/rules/pwn.md; python3 $TRIP --baseline"
assert_block "brace expansion" \
  "touch .{claude}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "character class" \
  "touch .clau[d]e/rules/pwn.md; python3 $TRIP --baseline"
assert_block "unreadable redirect target beside a re-baseline" \
  "printf pwned > \${!V}/rules/pwn.md; python3 $TRIP --baseline"
assert_block "indirect expansion inside a process substitution" \
  "python3 $TRIP --baseline <(P=.claude; V=P; touch \${!V}/rules/pwn.md)"

# The no-backstop rule is bounded, and each of these is one of the bounds. A
# reader is still a reader, and an expansion with no re-baseline beside it is
# still a real handoff to Layer 2 -- the file lands, the hash moves.
assert_allow "reading a glob beside a re-baseline (READ_ONLY holds)" \
  "grep -rn hook .claude/rules/*.md; python3 $TRIP --baseline"
assert_allow "indirect expansion alone still hands off to Layer 2" \
  'P=.claude; V=P; touch ${!V}/rules/pwn.md'

# --- round 10: READ_ONLY held eight programs that can write ------------------
# The finding named `awk`. The defect was the CLAIM: "programs that cannot write
# to a path they are given", asserted over a set holding awk, sed, sort, uniq,
# tree, xxd, yq and find -- with an inner READER_WRITE_FLAGS table that knew
# `sed -i` but not `sed 'w FILE'`, and `find -delete` but not `find -fprint`.
assert_block "awk writes through system()" \
  "awk 'BEGIN{system(\"touch .claude/settings.json\")}'"
assert_block "awk writes through a pipe to a command" \
  "awk 'BEGIN{print \"x\" | \"tee .claude/settings.json\"}'"
assert_block "awk carries the path in -v, program text does the write" \
  "awk -v f=.claude/settings.json 'BEGIN{print \"x\" > f}'"
assert_block "sed writes with w, no -i in sight" \
  "sed -n 'w .claude/settings.json' /etc/hosts"
assert_block "sed writes with s///w" \
  "sed 's/a/b/w .claude/settings.json' /etc/hosts"
assert_block "find writes with -fprint" \
  "find /tmp -name x -fprint .claude/settings.json"
assert_block "sort writes with -o" \
  "sort -o .claude/settings.json /dev/null"
assert_block "uniq's second positional is its output file" \
  "uniq /dev/null .claude/settings.json"
assert_block "xxd's second positional is its output file" \
  "xxd /dev/null .claude/settings.json"
assert_block "tree writes with -o" \
  "tree -o .claude/settings.json ."
assert_block "yq writes with -i" \
  "yq -i '.a=1' .claude/settings.json"
assert_block "a reader-write beside a same-command re-baseline" \
  "sort -o .claude/settings.json /dev/null; python3 $TRIP --baseline"

# The NAMED COST of dropping them, pinned so it stays a measurement. Plain
# awk/sed READS still block; that is the fail-closed direction this file's
# header chooses, and the pipe escape hatch below is the sanctioned route.
assert_block "plain awk read of a .claude path" \
  "awk '{print \$1}' .claude/settings.json"
assert_block "plain sed read of a .claude path" \
  "sed -n 1p .claude/settings.json"
# ASK-984 (sp-54b02aa0): plain find became a READER. Enumerating writes
# nothing, and blocking it refused legitimate recon under .claude/.
# FIND_WRITE_PRIMARIES keeps every write primary blocked fail-closed; the
# -fprint assert above stays RED.
assert_allow "plain find over .claude (reader form, ASK-984)" \
  "find .claude -name '*.md'"
assert_allow "escape hatch: pipe a .claude file into awk" \
  "cat .claude/settings.json | awk '{print \$1}'"
assert_allow "escape hatch: pipe a .claude file into sed" \
  "cat .claude/settings.json | sed -n 1p"

# --- round 10: a path GLUED TO A FLAG ---------------------------------------
# Not awk-specific and not in the finding: every writer in the system could
# attach its target to a flag and walk past the `-`-leading token skip.
assert_block "long flag with an attached .claude value" \
  "sort --output=.claude/settings.json /dev/null"
assert_block "short flag with an attached .claude value" \
  "sort -o.claude/settings.json /dev/null"
assert_block "cp --target-directory= into .claude" \
  "cp --target-directory=.claude /etc/hosts"
assert_allow "a flag value that is not a path" \
  "python3 script.py --desc=see-the-guard-notes"
assert_allow "a flag value naming an UNRELATED tree's .claude (round-5 pin)" \
  "sort --output=/tmp/unrelated-tree/.claude/settings.json /dev/null"

# --- round 10: READ_ONLY membership is pinned, not free to grow --------------
# The set is only sound while every member has NO file-writing channel on ANY
# command line. That property is checkable once and then stays checked -- but
# only if adding a name is a reviewed act. Same intent the file already states
# for GIT_READ_ONLY ("so nobody completes the set later by pattern-matching on
# the word read-only"); this makes it a test rather than a comment.
_ro_expected="ag basename cat cmp column cut df diff dirname du echo egrep fgrep file grep head jq ls md5 md5sum nl od printf pwd readlink realpath rg sha256sum shasum stat tail test type wc which"
_ro_actual="$(python3 - "$GUARD" <<'PY'
import importlib.util, sys
p = sys.argv[1]
spec = importlib.util.spec_from_file_location("guard", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(" ".join(sorted(mod.READ_ONLY)))
PY
)"
if [ "$_ro_actual" = "$_ro_expected" ]; then
  PASS=$((PASS+1)); echo "  ok   READ_ONLY membership is exactly the pinned set"
else
  FAIL=$((FAIL+1))
  echo "  FAIL READ_ONLY membership changed"
  echo "       want: $(printf '%s' "$_ro_expected" | tr -d '\n' | tr -s ' ')"
  echo "       got:  $_ro_actual"
  echo "       Adding a name here asserts it has NO file-writing channel on ANY"
  echo "       command line. Establish that, then update this pin in the same change."
fi

# F11 BLOCKER (round 11): Layer 1 protects Layer 2's baseline file, so the two
# layers must agree on WHERE that file is. They name it independently -- the
# tripwire owns BASELINE_REL, the guard needs its own copy because importing the
# tripwire into a PreToolUse hook would put Layer 2's whole module on the
# critical path of every Bash call. Two copies that silently disagree would turn
# the entire round-11 check off with no visible failure: _voids_layer2 would
# scan for a filename that never appears. Same reasoning as the EXCLUDED_DIRS
# pin above -- two layers disagreeing about what they guard is worse than either
# bound alone.
_paths="$(python3 - "$(dirname "$GUARD")" <<'PY'
import importlib.util, os, sys
d = sys.argv[1]
def load(n, p):
    spec = importlib.util.spec_from_file_location(n, p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
l1 = load("l1", os.path.join(d, "claude-path-write-guard.py"))
l2 = load("l2", os.path.join(d, "claude-integrity-tripwire.py"))
print("EQUAL" if l1.LAYER2_BASELINE_REL == l2.BASELINE_REL else
      "DIFFER l1=%s l2=%s" % (l1.LAYER2_BASELINE_REL, l2.BASELINE_REL))
print("NAMEOK" if l1.LAYER2_BASELINE_NAME == os.path.basename(l2.BASELINE_REL)
      else "NAMEBAD %s" % l1.LAYER2_BASELINE_NAME)
PY
)"
case "$_paths" in
  "EQUAL"*"NAMEOK"*)
    pass "L1 LAYER2_BASELINE_REL == L2 BASELINE_REL (and the basename matches)" ;;
  *)
    fail "L1 and L2 disagree about the baseline path -- round 11's check is inert"
    echo "       $_paths"
    echo "       _voids_layer2() scans stage text for LAYER2_BASELINE_NAME. If that"
    echo "       name is not the tripwire's actual baseline filename, the scan never"
    echo "       matches and the round-11 blocker is open again, silently." ;;
esac

# F11 BLOCKER (round 11), the Layer 2 half: the armed marker must NOT be in the
# watch set. If it ever is, --enforce sees it as `added` against the baseline
# that preceded it, deletes it, the next run recreates it, and the flap pages
# forever -- a self-inflicted version of the round-2 daily-alarm outage.
_marker_watched="$(python3 - "$(dirname "$GUARD")" <<'PY'
import importlib.util, os, sys, tempfile
d = sys.argv[1]
spec = importlib.util.spec_from_file_location("l2", os.path.join(d, "claude-integrity-tripwire.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, ".claude", "rules"))
open(os.path.join(root, ".claude", "rules", "r.md"), "w").write("x")
m.mark_armed(root)
print("WATCHED" if m.ARMED_MARKER_REL in m.watch_set(root) else "UNWATCHED")
print("PRESENT" if m.was_armed(root) else "ABSENT")
PY
)"
case "$_marker_watched" in
  "UNWATCHED"*"PRESENT"*)
    pass "armed marker is written, and is deliberately NOT watched (no flap)" ;;
  *)
    fail "armed marker watch-set/creation invariant broken: $_marker_watched" ;;
esac

# F13 BLOCKER (round 13): the executable is not always argv[0]. An environment
# assignment in front of a re-baselining command hid the program from
# `_program_names`, so `_voids_layer2` never saw the tripwire and an unanchorable
# `.claude/` write was handed to a backstop the same call erased.
#
# The pin holds BOTH sides, because they fail in opposite directions and a later
# edit that merges them re-opens one of the two:
#   * the WITHDRAWAL side (_voids_layer2) must see a rebaseliner behind ANY
#     prefix -- assignments, env, and the wrapper programs that carry their own
#     operand grammar. It matches the NAME, not the position, so this holds
#     without a table of which flags take a value.
#   * the EXEMPTION side (_is_sanctioned) must find the real executable behind an
#     assignment prefix, and must NOT be fooled by a sanctioned name sitting in an
#     assignment VALUE -- `os.path.basename("FOO=.../apply-claude-changes.sh")` is
#     `apply-claude-changes.sh`, which sanctioned the statement outright until
#     round 13. That is round 2's blocker arriving through the assignment door.
_r13="$(python3 - "$GUARD" <<'PY'
import importlib.util, shlex, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
trip = "q-system/.q-system/scripts/claude-integrity-tripwire.py"
appl = "q-system/.q-system/scripts/apply-claude-changes.sh"
write = "touch $UNSET/.claude/rules/pwn.md; "
prefixes = ["KIPI_NOTIFY=/usr/bin/true ", "A=1 B=2 ", "env KIPI_NOTIFY=x ",
            "env -i ", "env -u KIPI_NOTIFY ", "env --unset=X ", "env -i -- ",
            "nice ", "timeout 20 ", "command ", "nohup ", "stdbuf -oL "]  # portability-lint-skip: parser input, never executed
missed = [p for p in prefixes
          if not g._voids_layer2("%s%spython3 %s --baseline" % (write, p, trip), "/repo")]
print("VOIDSOK" if not missed else "VOIDSMISS %s" % missed)
print("EXECOK" if "claude-integrity-tripwire.py" in
      g._program_names(shlex.split("KIPI_NOTIFY=x python3 %s --baseline" % trip))
      else "EXECMISS")
print("VALUEOK" if not g._is_sanctioned(shlex.split("FOO=%s touch .claude/x" % appl))
      else "VALUEBAD")
PY
)"
case "$_r13" in
  "VOIDSOK"*"EXECOK"*"VALUEOK"*)
    pass "round-13 class: a prefix cannot hide the executable, and a sanctioned name in an assignment VALUE does not sanction" ;;
  *)
    fail "round-13 class is open again"
    echo "       $_r13"
    echo "       VOIDSMISS: that prefix hides a rebaseliner from _voids_layer2, so an"
    echo "       unanchorable .claude/ write is handed to a backstop the same call erases."
    echo "       VALUEBAD: an assignment VALUE ending in a sanctioned filename exempts the"
    echo "       whole statement from Layer 1 -- round 2's blocker through a new door." ;;
esac

# F14 MAJOR (round 14): round 13's grammar-free match read a MENTION as an
# INVOCATION. `_stage`'s no-backstop rule then refused any unreadable argument, so
# a rebaseliner name in a comment or a quoted commit message plus any glob was a
# hard block -- on a PreToolUse hook shipping to 23 machines, and on the exact
# commit shape this issue's own commits use.
#
# Three sides, pinned together because narrowing one is what re-opens another:
#   * PROSE must not void. A comment (which the shell never runs) and a phrase
#     carrying the name as one word among several.
#   * INVOCATION must still void, behind every prefix round 13 closed and from
#     inside an inline code string, where no path-shaped token exists.
#   * A GLOB must not reach past a leading dot. No shell expands `q-system/*` to
#     `q-system/.q-system`; fnmatch does, which made a plain recursive copy of
#     that glob a block whose stderr claimed it re-baselines Layer 2.
_r14="$(python3 - "$GUARD" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
trip = "q-system/.q-system/scripts/claude-integrity-tripwire.py"
prose = ["python3 build.py --out dist/*.js  # see kipi-update.sh",
         "python3 build.py --out d/*.js --note 'see kipi-update.sh'",
         "git commit -m 'fix apply_claude_changes.py' -- q-system/plugins",
         "cp -r q-system/* /tmp/backup/",
         "tar -cf /tmp/b.tar q-system/*"]
bad = [c for c in prose if g._voids_layer2(c, "/repo")]
print("PROSEOK" if not bad else "PROSEBLOCK %s" % bad)
invoke = ["python3 %s --baseline" % trip,
          "KIPI_NOTIFY=x python3 %s --baseline" % trip,
          "nice python3 %s --baseline" % trip,
          "bash apply-claude-changes.sh p.json",
          "python3 -c \"import runpy; runpy.run_path('%s')\"" % trip,
          "nice bash -c 'python3 %s --baseline'" % trip,
          "rm q-system/.q-system/claude-integrity-baseline.json",
          "rm -rf q-system",
          "rm -rf q-system/.q-*"]
missed = [c for c in invoke if not g._voids_layer2(c, "/repo")]
print("INVOKEOK" if not missed else "INVOKEMISS %s" % missed)
PY
)"
case "$_r14" in
  "PROSEOK"*"INVOKEOK"*)
    pass "round-14 class: prose naming a rebaseliner is not an invocation, and a glob does not cross a leading dot" ;;
  *)
    fail "round-14 class is open again"
    echo "       $_r14"
    echo "       PROSEBLOCK: a mention the shell never executes voids Layer 2, so any"
    echo "       glob argument beside it is a hard block. That refuses the commit that"
    echo "       describes this guard -- the false-block class that nearly killed it five times."
    echo "       INVOKEMISS: a real re-baseliner is invisible, so an unanchorable .claude/"
    echo "       write is handed to a backstop the same call erases (rounds 8, 11, 13)." ;;
esac

# F15 MAJOR (round 15): "path-shaped" was still SPELLING. A bare filename is one
# token whose basename IS the name wherever it sits, so an option's VALUE read as
# an invocation -- while the QUOTED form of the same message did not, which made
# the verdict depend on whether the operator happened to type quotes.
#
# Both sides in ONE case on purpose: this narrows a fail-CLOSED test, so every
# shape it drops has to be one the shell cannot execute. Narrowing further turns
# INVOKE red; widening back turns DATA red.
#   * DATA must not void: a filename in an option value, a plain operand of a
#     program that executes nothing, an interpreter's NON-first operand.
#   * INVOCATION must still void: bare, behind an assignment, behind env(1),
#     behind nice/timeout/command/nohup/stdbuf, direct with no interpreter,
#     direct behind a wrapper, from an assignment VALUE, and handed over a pipe
#     to a sink that reads its program from stdin.
_r15="$(python3 - "$GUARD" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
trip = "q-system/.q-system/scripts/claude-integrity-tripwire.py"
data = ["git commit -m claude-integrity-tripwire.py -- q-system/*",
        "python3 build.py --label claude-integrity-tripwire.py --out dist/*.js",
        "python3 build.py --manifest=apply_claude_changes.py --out dist/*.js",
        "grep -n kipi-update.sh docs/*.md",
        "git log --oneline -- kipi-update.sh q-system/*",
        "git log --oneline -- kipi-update.sh | grep fix"]
bad = [c for c in data if g._voids_layer2(c, "/repo")]
print("DATAOK" if not bad else "DATABLOCK %s" % bad)
invoke = ["python3 %s --baseline" % trip,
          "KIPI_NOTIFY=/usr/bin/true python3 %s --baseline" % trip,
          "env -i KIPI_NOTIFY=x python3 %s --baseline" % trip,
          "nice python3 %s --baseline" % trip,
          "timeout 20 python3 %s --baseline" % trip,
          "command python3 %s --baseline" % trip,
          "nohup python3 %s --baseline" % trip,
          "stdbuf -oL python3 %s --baseline" % trip,
          "./%s --register .claude/settings.json" % trip,
          "nice ./%s --register .claude/settings.json" % trip,
          "TOOL=%s make build" % trip,
          "echo %s | xargs python3" % trip,
          "bash apply-claude-changes.sh p.json"]
missed = [c for c in invoke if not g._voids_layer2(c, "/repo")]
print("INVOKEOK" if not missed else "INVOKEMISS %s" % missed)
PY
)"
case "$_r15" in
  "DATAOK"*"INVOKEOK"*)
    pass "round-15 class: a filename in a data position is not an invocation, and every invocation shape still voids" ;;
  *)
    fail "round-15 class is open again"
    echo "       $_r15"
    echo "       DATABLOCK: a filename the shell passes as DATA voids Layer 2, so any"
    echo "       glob beside it is a hard block -- the reviewer's own commit shape."
    echo "       INVOKEMISS: a real re-baseliner runs unseen, so an unanchorable"
    echo "       .claude/ write is handed to a backstop the same call erases." ;;
esac

# F14 MAJOR, second half: the watch set is not only `.claude/`. `kipi update`
# rsyncs q-system/ -- both EXTRA_WATCHED guard scripts -- and then sanctioned only
# the `.claude/` files it wrote, so every instance reported SECURITY drift on
# every tool call after a routine update, forever. Producer-derived: the list-
# building block is CUT OUT of kipi-update.sh and executed, so editing that block
# is what changes this answer.
_upd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
_wrote="$(awk '/^ *TRIPWIRE_WROTE=\(\)/{on=1} on&&/KIPI_NOTIFY=/{on=0} on' \
            "$_upd_root/kipi-update.sh")"
_missing="$(
  path="$_upd_root"; SCRIPT_DIR="$_upd_root"
  eval "$_wrote" 2>/dev/null
  python3 - "$_upd_root/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
           "${TRIPWIRE_WROTE[@]:-}" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
have = set(sys.argv[2:])
print(" ".join(r for r in mod.EXTRA_WATCHED if r not in have))
PY
)"
if [ -z "$_missing" ]; then
  pass "kipi update sanctions every EXTRA_WATCHED path its own rsync rewrote"
else
  fail "kipi update leaves watched files unsanctioned:$_missing"
  echo "       Every tool call on every updated instance reports SECURITY drift,"
  echo "       permanently, until a human runs --baseline on each machine."
fi

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
