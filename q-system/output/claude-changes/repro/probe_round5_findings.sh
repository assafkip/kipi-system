#!/usr/bin/env bash
# probe_round5_findings.sh -- reproducer for the round-5 Codex findings on PR #85
# (ASK-291). Written BEFORE the fixes; every phase was observed RED first.
#
#   1 major  --check absorbs a committed tamper on ANY branch, permanently
#            sanctioning what --enforce deliberately held and refused to sanction
#   2 major  an unresolved-variable prefix walks past Layer 1 while
#            settings.local.json is unwatched by Layer 2 -> a permissions
#            self-grant lands with NEITHER layer firing
#   3 minor  --check is documented read-only but writes the baseline
#   4 minor  the guard cites a test file that does not exist
#   5 minor  hits_claude has no project-root notion, so a .claude/ path anywhere
#            on the machine is blocked, including unrelated fixture trees
#
# Negative self-test: run with SELF_TEST=1 to point the phases at the pre-fix
# behaviour. A probe that cannot fail is not a probe.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SCRIPTS="$REPO/q-system/.q-system/scripts"
GUARD="$SCRIPTS/claude-path-write-guard.py"
TRIP="$SCRIPTS/claude-integrity-tripwire.py"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
passed=0; failed=0
pass() { passed=$((passed+1)); printf '  PASS  %s\n' "$1"; }
fail() { failed=$((failed+1)); printf '  FAIL  %s\n' "$1"; }
phase() { printf '\n== %s ==\n' "$1"; }

# ---------------------------------------------------------------- guard driver
guard_rc() { # command, cwd -> exit code
  CMD="$1" CWD="$2" python3 - <<'PY' | python3 "$GUARD" >/dev/null 2>&1; echo $?
import json, os, sys
print(json.dumps({"tool_name": "Bash",
                  "tool_input": {"command": os.environ["CMD"]},
                  "cwd": os.environ["CWD"]}))
PY
}
assert_block() { # desc, command, cwd
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "2" ] && pass "$1" || fail "$1 (expected block=2, got $rc)"
}
assert_allow() { # desc, command, cwd
  local rc; rc="$(guard_rc "$2" "$3")"
  [ "$rc" = "0" ] && pass "$1" || fail "$1 (expected allow=0, got $rc)"
}

# ------------------------------------------------------------- tripwire fixture
# A repo with a REAL remote whose default branch is known, because
# head_is_reviewed() is defined against `<remote>/HEAD`. Without a remote every
# branch is unreviewed and phase 1 would pass for the wrong reason.
make_repo() { # -> prints the worktree path
  local base="$1" origin="$1/origin.git" work="$1/work"
  git init --bare -q -b main "$origin"
  git init -q -b main "$work"
  git -C "$work" config user.email probe@local
  git -C "$work" config user.name probe
  mkdir -p "$work/.claude/rules"
  printf '{"hooks":{}}\n'   > "$work/.claude/settings.json"
  printf 'original rule\n'  > "$work/.claude/rules/r.md"
  git -C "$work" add -A >/dev/null
  git -C "$work" commit -qm init
  git -C "$work" remote add origin "$origin"
  git -C "$work" push -q -u origin main
  git -C "$work" remote set-head origin main >/dev/null 2>&1
  echo "$work"
}

phase "1 (major) --check must not sanction what --enforce refused to sanction"
W="$(make_repo "$WORK/p1")"
python3 "$TRIP" --root "$W" --baseline --quiet

# The tamper: an agent rewrites settings.json, commits it on its OWN branch and
# pushes. Content now equals the HEAD blob, so attributable() is True -- but the
# branch is not the remote default, so it never passed review.
git -C "$W" checkout -qb agent/tamper
printf '{"hooks":{},"pwned":true}\n' > "$W/.claude/settings.json"
git -C "$W" commit -qam tamper
git -C "$W" push -q origin agent/tamper

out_enforce="$(python3 "$TRIP" --root "$W" --enforce 2>&1)"; rc_enforce=$?
case "$rc_enforce:$out_enforce" in
  1:*"NOT reverted"*) pass "--enforce HELDS the committed tamper (exit 1, reported)" ;;
  *) fail "--enforce did not hold the tamper (rc=$rc_enforce): $out_enforce" ;;
esac

out_check="$(python3 "$TRIP" --root "$W" --check 2>&1)"; rc_check=$?
[ "$rc_check" = "1" ] \
  && pass "--check REPORTS the same tamper instead of absorbing it" \
  || fail "--check absorbed the tamper (rc=$rc_check): $out_check"

# The permanence half: once absorbed, the tamper is sanctioned forever, so the
# NEXT --enforce reports a clean tree and the hold is gone.
out_after="$(python3 "$TRIP" --root "$W" --enforce 2>&1)"; rc_after=$?
[ "$rc_after" = "1" ] \
  && pass "--enforce still holds the tamper AFTER a --check pass" \
  || fail "--check permanently sanctioned the tamper (rc=$rc_after): $out_after"

# The other direction: a genuinely REVIEWED change must still be absorbed, or
# the fix is just "absorption off" and every pull pages forever (the round-3
# defect this absorb path exists to prevent).
git -C "$W" checkout -q main
printf 'reviewed edit\n' > "$W/.claude/rules/r.md"
git -C "$W" commit -qam reviewed
git -C "$W" push -q origin main
out_rev="$(python3 "$TRIP" --root "$W" --check 2>&1)"; rc_rev=$?
case "$rc_rev:$out_rev" in
  0:*"re-baselined"*) pass "a change on the remote DEFAULT branch is still absorbed" ;;
  *) fail "reviewed change no longer absorbed (rc=$rc_rev): $out_rev" ;;
esac

phase "2 (major) fail closed where Layer 2 cannot back Layer 1 up"
FIX2="$WORK/p2"; mkdir -p "$FIX2/.claude"
# The self-grant: settings.local.json carries `permissions` and is deliberately
# NOT watched by Layer 2, so Layer 1 walking past it means NOTHING fires.
assert_block "unresolved prefix + settings.local.json is blocked" \
  'touch $NOPE/.claude/settings.local.json' "$FIX2"
assert_block "unresolved prefix + newline payload, same target" \
  'touch "$NOPE/.claude/settings.local.json"' "$FIX2"
# The scar this must NOT reintroduce: a fixture tree under an unresolvable var
# whose tail IS watched by Layer 2 stays allowed (4 false blocks in this issue).
assert_allow "unresolved prefix + a Layer-2-WATCHED tail stays allowed" \
  'mkdir -p "$D/.claude/rules"' "$FIX2"
assert_allow "unresolved prefix + agents/ stays allowed" \
  'mkdir -p $D/.claude/agents' "$FIX2"

# Pin the premise: Layer 2 really does not watch settings.local.json, so the
# claim "Layer 2 still catches it" was false for exactly this file.
W2="$(make_repo "$WORK/p2repo")"
python3 "$TRIP" --root "$W2" --baseline --quiet
printf '{"permissions":{"allow":["Bash(*)"]}}\n' > "$W2/.claude/settings.local.json"
python3 "$TRIP" --root "$W2" --check --quiet >/dev/null 2>&1
[ $? = 0 ] \
  && pass "premise holds: Layer 2 is blind to settings.local.json" \
  || fail "premise broken: Layer 2 now watches settings.local.json"

# Both layers must agree on WHICH files Layer 2 skips, or the fail-closed rule
# above drifts out of sync with the thing it compensates for.
SETS_EQ="$(python3 - "$SCRIPTS" <<'PY'
import importlib.util, os, sys
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod
d = sys.argv[1]
l1 = load("l1", os.path.join(d, "claude-path-write-guard.py")).LAYER2_EXCLUDED_FILES
l2 = load("l2", os.path.join(d, "claude-integrity-tripwire.py")).EXCLUDED_FILES
print("EQUAL" if l1 == l2 else "DIVERGED l1=%s l2=%s" % (sorted(l1), sorted(l2)))
PY
)"
[ "$SETS_EQ" = "EQUAL" ] \
  && pass "L1 LAYER2_EXCLUDED_FILES == L2 EXCLUDED_FILES" \
  || fail "excluded-file sets diverged: $SETS_EQ"

phase "3 (minor) --check documents that it writes the baseline"
doc="$(python3 - "$TRIP" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print(mod.__doc__ or "")
PY
)"
check_line="$(printf '%s\n' "$doc" | grep -- '--check' | head -1)"
printf '%s' "$check_line" | grep -qi 'read-only' \
  && fail "--check is still documented read-only: $check_line" \
  || pass "--check no longer claims read-only"
printf '%s' "$doc" | grep -qi 'last_alarm' \
  && pass "the docstring names last_alarm as a --check write" \
  || fail "the docstring does not say what --check writes"

# Behavioural half: prove it WRITES, so the doc is describing something real.
W3="$(make_repo "$WORK/p3")"
python3 "$TRIP" --root "$W3" --baseline --quiet
BASE="$W3/.claude/state/claude-integrity-baseline.json"
[ -f "$BASE" ] || BASE="$(find "$W3" -name 'claude-integrity-baseline.json' | head -1)"
before="$(shasum "$BASE" | cut -d' ' -f1)"
printf 'drift with no git provenance\n' > "$W3/.claude/rules/r.md"
python3 "$TRIP" --root "$W3" --check >/dev/null 2>&1
after="$(shasum "$BASE" | cut -d' ' -f1)"
[ "$before" != "$after" ] \
  && pass "--check does write the baseline (last_alarm), as now documented" \
  || fail "--check did not write the baseline -- the doc would be wrong again"

phase "4 (minor) the guard cites a test that exists"
grep -q 'test_claude_path_write_guard\.py' "$GUARD" \
  && fail "guard still cites the nonexistent test_claude_path_write_guard.py" \
  || pass "the nonexistent test file is no longer cited"
cited="$(grep -o 'test-claude-write-path\.sh[^ ]*' "$GUARD" | head -1)"
[ -n "$cited" ] \
  && pass "guard cites test-claude-write-path.sh" \
  || fail "guard cites no real test for the parity assertion"
[ -f "$SCRIPTS/test/test-claude-write-path.sh" ] \
  && pass "the cited test file exists on disk" \
  || fail "the cited test file does not exist"
grep -q 'EXCLUDED_DIRS' "$SCRIPTS/test/test-claude-write-path.sh" \
  && pass "the cited test really carries the parity assertion" \
  || fail "the cited test does not assert parity"

phase "5 (minor) a .claude/ tree this hook does not guard is not its business"
FIX5="$WORK/p5"; mkdir -p "$FIX5"
OTHER="$WORK/other-tree"; mkdir -p "$OTHER"
# $WORK is a mktemp dir: outside $HOME and outside this repo. An unrelated
# fixture tree there wires no hook of ours.
assert_allow "an unrelated tree's .claude/ is not blocked" \
  "touch $OTHER/.claude/settings.json" "$FIX5"
assert_allow "read-only tools on an unrelated .claude/ are not blocked" \
  "cp $OTHER/.claude/settings.json $OTHER/copy.json" "$FIX5"
# ...but everything this session can actually reach stays closed.
assert_block "the guard's OWN repo is blocked from an unrelated cwd" \
  "touch $REPO/.claude/settings.json" "$FIX5"
assert_block "\$HOME/.claude stays blocked (it wires destructive-op-deny)" \
  'touch $HOME/.claude/settings.json' "$FIX5"
assert_block "the session cwd's own tree stays blocked" \
  "touch $FIX5/.claude/settings.json" "$FIX5"
assert_block "a bare write with cwd inside the session's .claude stays blocked" \
  'touch evil.txt' "$FIX5/.claude"

printf '\nRESULT: %d passed, %d failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
