#!/usr/bin/env bash
# probe_round4_findings.sh -- one phase per PR #85 round-3 review finding (ASK-291).
#
# Every phase drives the REAL scripts, and the REAL hook command string lifted out
# of .claude/settings.json, against a throwaway tree. No mocks. Each phase carries
# NEGATIVE SELF-TESTS: cases that must stay red, so a phase that goes green because
# a guard was gutted still fails here.
#
# Cleanup uses python3 shutil.rmtree, never `rm -rf`: this repo's own
# destructive-op-deny hook blocks recursive shell deletes.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TRIP="$REPO/q-system/.q-system/scripts/claude-integrity-tripwire.py"
GUARD="$REPO/q-system/.q-system/scripts/claude-path-write-guard.py"
APPLY="$REPO/q-system/.q-system/scripts/apply-claude-changes.sh"
PROPOSAL="$REPO/q-system/output/claude-changes/arm-claude-write-path-guards.json"

PASS=0
FAIL=0
WORKROOT="$(mktemp -d)"
cleanup() { python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$WORKROOT"; }
trap cleanup EXIT

ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (want rc=$2, got rc=$3)"; fi; }

# EVERY hook command that mentions the script, in configured order, exactly as
# Claude Code runs them. Lifted from the live settings.json rather than retyped:
# a harness that tests a transcribed copy of the wiring proves nothing about the
# wiring (both v1 anchor defects on this issue were transcription). Newline-
# separated, and the recovery entry and the enforcement entry are BOTH matched --
# taking only the first would test half the group.
hook_commands() { # hook_commands <settings.json> <script basename>
  python3 - "$1" "$2" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for groups in doc.get("hooks", {}).values():
    for g in groups:
        for h in g.get("hooks", []):
            if sys.argv[2] in h.get("command", ""):
                print(h["command"].replace("\n", " "))
PY
}

# Run them all and return the WORST rc, the way a hook group's failure surfaces.
run_hooks() { # run_hooks <project_dir> <commands...>
  local dir="$1"; shift
  local worst=0 rc=0
  while IFS= read -r c; do
    [ -z "$c" ] && continue
    CLAUDE_PROJECT_DIR="$dir" bash -c "$c" >/dev/null 2>&1
    rc=$?
    [ "$rc" -gt "$worst" ] && worst=$rc
  done <<< "$*"
  return "$worst"
}

# A minimal armed tree: real git repo, real remote, both guard scripts committed,
# and a recording notifier standing in for slack-notify.sh.
make_tree() { # make_tree <name> -> prints the worktree path
  local d="$WORKROOT/$1"
  mkdir -p "$d/work/.claude/rules" "$d/work/q-system/.q-system/scripts"
  cp "$TRIP" "$GUARD" "$d/work/q-system/.q-system/scripts/"
  cat > "$d/work/q-system/.q-system/scripts/slack-notify.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$1" >> "$(dirname "$0")/../../../PAGES.log"
SH
  chmod +x "$d/work/q-system/.q-system/scripts/slack-notify.sh"
  printf 'v1\n' > "$d/work/.claude/rules/keep.md"
  cp "$REPO/.claude/settings.json" "$d/work/.claude/settings.json"
  git init -q --bare "$d/origin.git"
  git -C "$d/work" init -q
  git -C "$d/work" config user.email probe@example.com
  git -C "$d/work" config user.name probe
  git -C "$d/work" add -A -f >/dev/null 2>&1
  git -C "$d/work" commit -q -m base >/dev/null 2>&1
  git -C "$d/work" branch -M main >/dev/null 2>&1
  git -C "$d/work" remote add origin "$d/origin.git"
  git -C "$d/work" push -q origin main >/dev/null 2>&1
  git -C "$d/work" remote set-head origin main >/dev/null 2>&1
  echo "$d/work"
}

pages() { # pages <worktree> -> number of pages emitted so far
  local f="$1/PAGES.log"
  [ -f "$f" ] && grep -c . "$f" || echo 0
}

# ---------------------------------------------------------------------------
echo "=== PHASE 1: deleting Layer 2 must page and self-restore ==="
echo "    finding 1 (major) .claude/settings.json:186"
# `test -f X && python3 X` is the repo convention, and it makes a MISSING script a
# no-op that neither pages nor repairs. Layer 2 watches its own file, but that
# watch runs INSIDE the deleted file: every configured invocation is gone with it,
# so the detector cannot restore itself. Round 2 closed this for Layer 1 by having
# Layer 2 watch it. Nothing watches Layer 2.
W1="$(make_tree p1)"
CMD1="$(hook_commands "$W1/.claude/settings.json" claude-integrity-tripwire.py)"
if [ -z "$CMD1" ]; then bad "phase 1: no tripwire hook found in settings.json"; fi
export KIPI_NOTIFY="$W1/q-system/.q-system/scripts/slack-notify.sh"
run_hooks "$W1" "$CMD1"   # arms the tree

BEFORE="$(pages "$W1")"
python3 -c "import os,sys; os.remove(sys.argv[1])" "$W1/q-system/.q-system/scripts/claude-integrity-tripwire.py"
run_hooks "$W1" "$CMD1"
RC1=$?
[ -f "$W1/q-system/.q-system/scripts/claude-integrity-tripwire.py" ] \
  && ok "1a deleting Layer 2 self-restores it from git" \
  || bad "1a Layer 2 stayed deleted -- every configured invocation is now a no-op"
[ "$(pages "$W1")" -gt "$BEFORE" ] \
  && ok "1b the deletion paged the founder" \
  || bad "1b Layer 2 was deleted with no page"

# The restored file has to be the real thing, not a placeholder: it must run.
run_hooks "$W1" "$CMD1"
check "1c the restored Layer 2 runs clean on an unchanged tree" 0 $?

# NEGATIVE SELF-TEST: a fix that always exits 0 would pass 1a-1c. Here git cannot
# restore the file, so the hook must fail LOUDLY rather than report success.
W1B="$(make_tree p1b)"
export KIPI_NOTIFY="$W1B/q-system/.q-system/scripts/slack-notify.sh"
run_hooks "$W1B" "$CMD1"
git -C "$W1B" rm -q --cached q-system/.q-system/scripts/claude-integrity-tripwire.py >/dev/null 2>&1
git -C "$W1B" commit -q -m "untrack the tripwire" >/dev/null 2>&1
B4="$(pages "$W1B")"
python3 -c "import os,sys; os.remove(sys.argv[1])" "$W1B/q-system/.q-system/scripts/claude-integrity-tripwire.py"
run_hooks "$W1B" "$CMD1"
RC1B=$?
[ "$RC1B" -ne 0 ] \
  && ok "1d an unrestorable Layer 2 exits non-zero (rc=$RC1B), never a silent success" \
  || bad "1d an unrestorable Layer 2 reported success (rc=0)"
[ "$(pages "$W1B")" -gt "$B4" ] \
  && ok "1e an unrestorable Layer 2 still pages" \
  || bad "1e an unrestorable Layer 2 did not page"

# NEGATIVE SELF-TEST: the wrapper must not swallow the tripwire's own verdict.
W1C="$(make_tree p1c)"
export KIPI_NOTIFY="$W1C/q-system/.q-system/scripts/slack-notify.sh"
run_hooks "$W1C" "$CMD1"
printf 'pwned\n' >> "$W1C/.claude/rules/keep.md"
run_hooks "$W1C" "$CMD1"
check "1f a real tamper is still reverted through the wrapper" 2 $?
grep -q pwned "$W1C/.claude/rules/keep.md" \
  && bad "1g the tamper survived -- the wrapper broke enforcement" \
  || ok "1g the tamper was reverted"

# ---------------------------------------------------------------------------
echo
echo "=== PHASE 2: a pushed AGENT branch is not reviewed provenance ==="
echo "    finding 2 (major) claude-integrity-tripwire.py:602"
# head_is_pushed() asks "is HEAD on ANY remote-tracking ref". Every agent in this
# fleet pushes its own branch (this very PR sits on sana/ask-291), so an agent can
# write .claude/, commit, push its own branch, and the next --enforce ABSORBS the
# tamper into the baseline and exits 0. Pushing is not review; merging is.
W2="$(make_tree p2)"
export KIPI_NOTIFY="$W2/q-system/.q-system/scripts/slack-notify.sh"
KIPI_NOTIFY="$W2/q-system/.q-system/scripts/slack-notify.sh" python3 "$TRIP" --root "$W2" --baseline --quiet

git -C "$W2" checkout -q -b agent/tamper
printf 'pwned by the agent\n' > "$W2/.claude/rules/keep.md"
git -C "$W2" commit -q -am "agent tamper" >/dev/null 2>&1
git -C "$W2" push -q origin agent/tamper >/dev/null 2>&1
KIPI_NOTIFY="$W2/q-system/.q-system/scripts/slack-notify.sh" \
  python3 "$W2/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$W2" --enforce --quiet >/dev/null 2>&1
RC2=$?
[ "$RC2" -ne 0 ] \
  && ok "2a a tamper on a pushed agent branch is NOT waved through (rc=$RC2)" \
  || bad "2a a tamper on a pushed agent branch was absorbed silently (rc=0)"
python3 - "$W2" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
b = json.load(open(os.path.join(root, "q-system", ".q-system", "claude-integrity-baseline.json")))
cur = hashlib.sha256(open(os.path.join(root, ".claude/rules/keep.md"), "rb").read()).hexdigest()
sys.exit(0 if b["entries"][".claude/rules/keep.md"]["sha256"] != cur else 1)
PY
[ $? -eq 0 ] \
  && ok "2b the baseline did not adopt the agent's tamper as sanctioned" \
  || bad "2b the tamper is now recorded as the sanctioned content"

# NEGATIVE SELF-TEST: round 3's fix must survive. Content delivered on the remote
# DEFAULT branch is reviewed and must still be absorbed, or --enforce goes back to
# fighting `git pull` and paging a SECURITY line nobody can act on.
W2B="$(make_tree p2b)"
export KIPI_NOTIFY="$W2B/q-system/.q-system/scripts/slack-notify.sh"
KIPI_NOTIFY="$W2B/q-system/.q-system/scripts/slack-notify.sh" python3 "$TRIP" --root "$W2B" --baseline --quiet
printf 'v2 reviewed\n' > "$W2B/.claude/rules/keep.md"
git -C "$W2B" commit -q -am "reviewed change on main" >/dev/null 2>&1
git -C "$W2B" push -q origin main >/dev/null 2>&1
KIPI_NOTIFY="$W2B/q-system/.q-system/scripts/slack-notify.sh" \
  python3 "$W2B/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$W2B" --enforce --quiet >/dev/null 2>&1
check "2c reviewed content on the remote default branch is still absorbed" 0 $?
grep -q 'v2 reviewed' "$W2B/.claude/rules/keep.md" \
  && ok "2d the reviewed change survived --enforce" \
  || bad "2d --enforce reverted git-delivered content again"

# NEGATIVE SELF-TEST: an unpushed local commit is still HELD, never reverted
# (round 3's invariant: --enforce never leaves the worktree inconsistent with HEAD).
W2C="$(make_tree p2c)"
export KIPI_NOTIFY="$W2C/q-system/.q-system/scripts/slack-notify.sh"
KIPI_NOTIFY="$W2C/q-system/.q-system/scripts/slack-notify.sh" python3 "$TRIP" --root "$W2C" --baseline --quiet
printf 'local only\n' > "$W2C/.claude/rules/keep.md"
git -C "$W2C" commit -q -am "unpushed" >/dev/null 2>&1
KIPI_NOTIFY="$W2C/q-system/.q-system/scripts/slack-notify.sh" \
  python3 "$W2C/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$W2C" --enforce --quiet >/dev/null 2>&1
check "2e an unpushed local commit is held, reported, not reverted" 1 $?
grep -q 'local only' "$W2C/.claude/rules/keep.md" \
  && ok "2f the held file was left agreeing with HEAD" \
  || bad "2f --enforce reverted behind git's back"

# NEGATIVE SELF-TEST: a bare shell write matching no HEAD is still reverted.
W2D="$(make_tree p2d)"
export KIPI_NOTIFY="$W2D/q-system/.q-system/scripts/slack-notify.sh"
KIPI_NOTIFY="$W2D/q-system/.q-system/scripts/slack-notify.sh" python3 "$TRIP" --root "$W2D" --baseline --quiet
printf 'uncommitted tamper\n' > "$W2D/.claude/rules/keep.md"
KIPI_NOTIFY="$W2D/q-system/.q-system/scripts/slack-notify.sh" \
  python3 "$W2D/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$W2D" --enforce --quiet >/dev/null 2>&1
check "2g an uncommitted tamper is still quarantined and reverted" 2 $?

# ---------------------------------------------------------------------------
echo
echo "=== PHASE 3: enforcement must serialize against a sanctioned apply ==="
echo "    finding 3 (major) claude-integrity-tripwire.py:539"
# The register lock only excludes other registers. --enforce takes no lock at all,
# so a PostToolUse enforcement that fires between the applier's write and its
# register sees the write as unsanctioned drift and reverts it -- while the applier
# reports OK. The sanctioned write path silently loses its change.
copy_tree() { # copy_tree <name> -> prints an armed copy of this repo's guard surface
  local d="$WORKROOT/$1"
  mkdir -p "$d/q-system/.q-system"
  cp -R "$REPO/.claude" "$d/.claude"
  python3 -c "import shutil,sys,os
for n in ('worktrees','state','plans'):
    shutil.rmtree(os.path.join(sys.argv[1], '.claude', n), ignore_errors=True)" "$d"
  cp "$REPO/settings-template.json" "$d/"
  cp -R "$REPO/q-system/.q-system/scripts" "$d/q-system/.q-system/scripts"
  cp "$REPO/q-system/.q-system/capability-manifest.json" "$d/q-system/.q-system/" 2>/dev/null
  # Disarm: the copy comes from the PR head where the proposal is already applied,
  # so an armed copy would make the apply a no-op and this phase would test nothing.
  python3 - "$d" <<'PY'
import json, os, sys
d = sys.argv[1]
GUARDS = ("claude-path-write-guard.py", "claude-integrity-tripwire.py")
for rel in (".claude/settings.json", "settings-template.json"):
    p = os.path.join(d, rel)
    s = json.load(open(p))
    for event, groups in list(s.get("hooks", {}).items()):
        kept = []
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", [])
                          if not any(x in h.get("command", "") for x in GUARDS)]
            if g["hooks"]:
                kept.append(g)
        s["hooks"][event] = kept
    json.dump(s, open(p, "w"), indent=2)
    open(p, "a").write("\n")
PY
  git -C "$d" init -q
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
  KIPI_NOTIFY=/usr/bin/true python3 "$d/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
    --root "$d" --enforce --quiet >/dev/null 2>&1   # arm
  echo "$d"
}

LOST=0
for trial in 1 2 3; do
  D3="$(copy_tree "p3t$trial")"
  STOP="$WORKROOT/stop-$trial"
  (
    while [ ! -f "$STOP" ]; do
      KIPI_NOTIFY=/usr/bin/true python3 \
        "$D3/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
        --root "$D3" --enforce --quiet >/dev/null 2>&1
    done
  ) &
  LOOP=$!
  bash "$APPLY" "$PROPOSAL" --root "$D3" >/dev/null 2>&1
  RCA=$?
  touch "$STOP"; wait "$LOOP" 2>/dev/null
  if [ "$RCA" -ne 0 ]; then
    bad "3a trial $trial: the applier itself failed (rc=$RCA)"
  elif grep -q 'claude-path-write-guard' "$D3/.claude/settings.json"; then
    :
  else
    LOST=$((LOST+1))
  fi
done
[ "$LOST" -eq 0 ] \
  && ok "3a 3/3 sanctioned applies survived concurrent enforcement" \
  || bad "3a $LOST/3 sanctioned applies were reverted mid-flight by a concurrent --enforce"

# NEGATIVE SELF-TEST: with nothing in flight, enforcement still reverts a tamper.
# A "fix" that simply stops enforcing would pass 3a and fail here.
D3B="$(copy_tree p3b)"
printf 'pwned\n' >> "$D3B/.claude/settings.json"
KIPI_NOTIFY=/usr/bin/true python3 "$D3B/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$D3B" --enforce --quiet >/dev/null 2>&1
check "3b enforcement still reverts a tamper when no apply is in flight" 2 $?

# NEGATIVE SELF-TEST: the wait for the lock is BOUNDED and LOUD. A held lock must
# not become a silent, permanent off-switch for enforcement.
D3C="$(copy_tree p3c)"
printf 'pwned\n' >> "$D3C/.claude/settings.json"
python3 - "$D3C" <<'PY' &
import os, sys, time, importlib.util
root = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "tw", os.path.join(root, "q-system", ".q-system", "scripts", "claude-integrity-tripwire.py"))
tw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tw)
with tw.baseline_lock(root):
    time.sleep(6)
PY
HOLDER=$!
sleep 1
KIPI_TRIPWIRE_LOCK_WAIT=1 KIPI_NOTIFY=/usr/bin/true \
  python3 "$D3C/q-system/.q-system/scripts/claude-integrity-tripwire.py" \
  --root "$D3C" --enforce --quiet >/dev/null 2>&1
RC3C=$?
wait "$HOLDER" 2>/dev/null
[ "$RC3C" -ne 0 ] \
  && ok "3c a held lock reports (rc=$RC3C) instead of silently passing" \
  || bad "3c a held lock turned enforcement into a silent exit 0"
grep -q pwned "$D3C/.claude/settings.json" \
  && ok "3d a held lock defers the revert rather than acting unserialized" \
  || bad "3d enforcement acted while a sanctioned apply held the lock"

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
