#!/usr/bin/env bash
# probe_round3_findings.sh -- one phase per PR #85 round-2 review finding (ASK-291).
#
# Every phase drives the REAL scripts against a throwaway tree. No mocks. Each
# phase carries a NEGATIVE SELF-TEST: a case that must stay red, so a phase that
# passes because the guard was gutted still fails here.
#
# Cleanup uses python3 shutil.rmtree, never `rm -rf`: this repo's own
# destructive-op-deny hook blocks recursive shell deletes, and it blocked the
# reviewer's own reproducer. A harness that cannot run under the repo's gates is
# not a harness.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$REPO/q-system/.q-system/scripts/claude-path-write-guard.py"
TRIP="$REPO/q-system/.q-system/scripts/claude-integrity-tripwire.py"

PASS=0
FAIL=0
WORKROOT="$(mktemp -d)"

cleanup() { python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$WORKROOT"; }
trap cleanup EXIT

ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check() { # check <label> <expected_rc> <actual_rc>
  if [ "$2" = "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (want rc=$2, got rc=$3)"; fi
}

# Feed one command string to Layer 1 exactly as Claude Code does, and echo its rc.
layer1() { # layer1 <cwd> <command>
  python3 - "$GUARD" "$1" "$2" <<'PY' >/dev/null 2>&1
import json, subprocess, sys
guard, cwd, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
payload = json.dumps({"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": cmd}})
sys.exit(subprocess.run([sys.executable, guard], input=payload, text=True,
                        capture_output=True).returncode)
PY
  echo $?
}

# A minimal armed tree with a real git repo AND a real remote, because the whole
# question in phase 1 is whether content came from a reviewed remote or a local
# write. A repo with no remote cannot express that difference.
make_tree() { # make_tree <name> -> prints the worktree path
  local d="$WORKROOT/$1"
  mkdir -p "$d/work/.claude/rules" "$d/work/q-system/.q-system/scripts"
  cp "$TRIP" "$d/work/q-system/.q-system/scripts/"
  cp "$GUARD" "$d/work/q-system/.q-system/scripts/"
  printf 'v1\n'      > "$d/work/.claude/rules/keep.md"
  printf 'scratch\n' > "$d/work/.claude/rules/dropme.md"
  git init -q --bare "$d/origin.git"
  git -C "$d/work" init -q
  git -C "$d/work" config user.email probe@example.com
  git -C "$d/work" config user.name probe
  git -C "$d/work" add -A -f >/dev/null 2>&1
  git -C "$d/work" commit -q -m "base" >/dev/null 2>&1
  git -C "$d/work" branch -M main >/dev/null 2>&1
  git -C "$d/work" remote add origin "$d/origin.git"
  git -C "$d/work" push -q origin main >/dev/null 2>&1
  echo "$d/work"
}

echo "=== PHASE 1: --enforce must not revert git-delivered .claude/ content ==="
echo "    finding 1 (major) .claude/settings.json:186"
W="$(make_tree p1)"
python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" --root "$W" --baseline --quiet

# Author the change the way a reviewed remote change arrives: commit it, push it
# to origin, then bring it into the worktree. This is byte-identical to what a
# `git pull` leaves behind.
git -C "$W" checkout -q -b upstream
printf 'v2 reviewed\n' > "$W/.claude/rules/keep.md"
printf 'new\n'         > "$W/.claude/rules/newrule.md"
python3 -c "import os,sys; os.remove(sys.argv[1])" "$W/.claude/rules/dropme.md"
git -C "$W" add -A -f >/dev/null 2>&1
git -C "$W" commit -q -m "reviewed .claude change" >/dev/null 2>&1
git -C "$W" push -q origin upstream >/dev/null 2>&1

RC="$(python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$W" --enforce --quiet >/dev/null 2>&1; echo $?)"
check "git-delivered change survives --enforce" 0 "$RC"

AFTER="$(cat "$W/.claude/rules/keep.md" 2>/dev/null || echo MISSING)"
if [ "$AFTER" = "v2 reviewed" ]; then ok "keep.md still holds the reviewed content"
else bad "keep.md was reverted to '$AFTER'"; fi
if [ -f "$W/.claude/rules/newrule.md" ]; then ok "newrule.md was not deleted"
else bad "newrule.md was deleted by the enforcer"; fi
if [ ! -f "$W/.claude/rules/dropme.md" ]; then ok "dropme.md stayed deleted"
else bad "dropme.md was resurrected against HEAD"; fi

# NEGATIVE SELF-TEST: a local shell write that is in NO remote must still be
# quarantined and reverted. If this goes green the phase above proves nothing.
printf 'pwned\n' > "$W/.claude/rules/keep.md"
RC="$(python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$W" --enforce --quiet >/dev/null 2>&1; echo $?)"
check "NEGATIVE: unattributable local write still reverted" 2 "$RC"
AFTER="$(cat "$W/.claude/rules/keep.md" 2>/dev/null || echo MISSING)"
if [ "$AFTER" = "v2 reviewed" ]; then ok "NEGATIVE: reverted to the sanctioned content"
else bad "NEGATIVE: left '$AFTER' in place"; fi

echo
echo "=== PHASE 2: strip_heredocs must not drop the rest of the command ==="
echo "    finding 2 (major) claude-path-write-guard.py:265"
CW="$WORKROOT/p2"; mkdir -p "$CW"

# A quoted `<<` is a string, not a heredoc opener. Reading it as one discards
# every statement after line 1 -- including the write.
RC="$(layer1 "$CW" 'echo "diff a<<b"
touch .claude/evil.txt')"
check "quoted << does not blind the guard to a later write" 2 "$RC"

RC="$(layer1 "$CW" 'echo "see <<TOKEN"
python3 -c "open(\".claude/settings.local.json\",\"w\").write(\"{}\")"')"
check "quoted << does not hide a settings.local.json self-grant" 2 "$RC"

# An UNFOUND delimiter must not strip to EOF either.
RC="$(layer1 "$CW" 'git commit -m "switch to <<EOF heredocs"
rm .claude/rules/stale.md')"
check "unterminated heredoc opener does not swallow the next statement" 2 "$RC"

# NEGATIVE SELF-TEST: a REAL heredoc body mentioning .claude/ must still be
# allowed. Deleting strip_heredocs entirely would pass the three above and fail
# this one -- that is the point of it being here.
RC="$(layer1 "$CW" "git commit -F - <<'MSG'
this change edits .claude/rules/foo.md and mentions .claude/settings.json
MSG")"
check "NEGATIVE: real heredoc body mentioning .claude/ still allowed" 0 "$RC"

# NEGATIVE SELF-TEST: a real heredoc that REDIRECTS into .claude/ stays blocked.
RC="$(layer1 "$CW" "cat > .claude/settings.json <<'EOF'
{}
EOF")"
check "NEGATIVE: heredoc redirecting into .claude/ still blocked" 2 "$RC"

echo
echo "=== PHASE 3: deleting a guard script must not disarm silently ==="
echo "    finding 3 (minor) .claude/settings.json:169"
W="$(make_tree p3)"
python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" --root "$W" --baseline --quiet
RC="$(python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$W" --check --quiet >/dev/null 2>&1; echo $?)"
check "NEGATIVE: untouched tree reports clean" 0 "$RC"

python3 -c "import os,sys; os.remove(sys.argv[1])" \
  "$W/q-system/.q-system/scripts/claude-path-write-guard.py"
RC="$(python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$W" --check --quiet >/dev/null 2>&1; echo $?)"
check "deleting the Layer 1 guard is DETECTED" 1 "$RC"

# And the enforcer puts it back, so the disarm does not survive one tool call.
RC="$(python3 "$W/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$W" --enforce --quiet >/dev/null 2>&1; echo $?)"
check "deleting the Layer 1 guard is REVERTED" 2 "$RC"
if [ -f "$W/q-system/.q-system/scripts/claude-path-write-guard.py" ]; then
  ok "the deleted guard script was restored"
else bad "the guard script is still gone after --enforce"; fi

echo
echo "=== PHASE 4: an unresolvable cwd must not fabricate a .claude/ path ==="
echo "    finding 4 (minor) claude-path-write-guard.py:397"
RC="$(layer1 "$CW" 'D=$(mktemp -d); mkdir -p "$D/.claude/rules"')"
check "command-substitution dir is not resolved against the session cwd" 0 "$RC"

RC="$(layer1 "$CW" 'cd "$WORK" && mkdir -p .claude/agents')"
check "cd into an unset var does not anchor .claude/ to the session cwd" 0 "$RC"

# NEGATIVE SELF-TESTS: everything the guard could actually resolve stays blocked.
RC="$(layer1 "$CW" 'cd .claude && touch evil.txt')"
check "NEGATIVE: cd into a literal .claude still blocked" 2 "$RC"

RC="$(layer1 "$CW" 'D=.claude; touch $D/evil.txt')"
check "NEGATIVE: a resolvable var holding .claude still blocked" 2 "$RC"

RC="$(layer1 "$CW" 'touch $HOME/.claude/evil.txt')"
check "NEGATIVE: \$HOME expands, so \$HOME/.claude stays blocked" 2 "$RC"

echo
echo "================================================"
printf 'RESULT: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
