#!/usr/bin/env bash
# H3: kipi rollback -- safe revert of the last skeleton sync. Pairs with issue kipi-rollback-verb.
set -euo pipefail

# NEVER pipe into `grep -q` in this file. `set -o pipefail` is on (above), and
# `grep -q` exits the instant it matches -- so the producer on the left can still
# be writing, take SIGPIPE, exit 141, and pipefail turns that into a FAILED
# pipeline even though the assertion actually PASSED. Use a herestring, or
# capture to a variable first.
#
# Scar (sp-3fe1ab9d, 2026-07-28): this suite flaked at 3/30 under capability-gate
# and always passed when run by hand, so it read as "green, occasionally weird".
# It surfaced as `FAIL: pre-sync auto-commit lost`, which points at rollback
# losing a commit -- a data-loss bug that was never happening. A nondeterministic
# gate is worse than a red one: it teaches everyone to re-run until green, and
# the day it means something nobody looks. After converting all 9 pipelines to
# herestrings: 0/60.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RB="$ROOT/kipi-rollback.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
# The rollback script under test runs BARE git revert, which needs committer
# identity. Founder machines always have one; CI runners have none, so the
# revert failed there and the script's error path mislabeled it a conflict
# (first CI execution of this suite, 2026-07-23). Hermetic identity for the
# whole test process, not just the G() wrapper.
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=t@t.t
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=t@t.t
WORK="$(mktemp -d)"

# Fixture instance: baseline -> a pre-sync auto-commit -> a sync commit that modifies
# ONLY a synced tracked file. Preserved files are written at baseline and never touched
# by the sync (mirrors kipi-update.sh's rsync --exclude of my-project/ + canonical/).
mk_instance() {
  local dir="$1"; mkdir -p "$dir"
  ( cd "$dir" && G init -q
    mkdir -p q-system/my-project q-system/canonical
    printf 'orig\n'     > q-system/CLAUDE.md
    printf 'state-v1\n' > q-system/my-project/current-state.md
    printf 'dec-v1\n'   > q-system/canonical/decisions.md
    G add -A && G commit -qm baseline
    printf 'userwork\n' > q-system/userfile.md
    G add -A && G commit -qm "chore: auto-commit before kipi update"
    printf 'synced-v2\n' > q-system/CLAUDE.md
    G add -A && G commit -qm "chore: sync q-system from skeleton 2026-06-20"
  )
}
mk_registry() {  # $1=regfile ; rest = name::path
  local reg="$1"; shift
  python3 -c "
import json,sys
items=[{'name':p.split('::',1)[0],'path':p.split('::',1)[1]} for p in sys.argv[1:]]
json.dump({'instances':items}, open('$reg','w'))
" "$@"
}

# 1. happy path: reverts the sync, preserves everything else, keeps the pre-sync commit
A="$WORK/inst-a"; mk_instance "$A"
REG="$WORK/reg1.json"; mk_registry "$REG" "inst-a::$A"
PRE_STATE="$(cat "$A/q-system/my-project/current-state.md")"
PRE_DEC="$(cat "$A/q-system/canonical/decisions.md")"
OUT="$(KIPI_REGISTRY="$REG" bash "$RB" 2>&1)" || fail "happy-path rollback exited non-zero: $OUT"
grep -qi "ROLLED BACK" <<<"$OUT" || fail "happy path did not report ROLLED BACK: $OUT"
[ "$(cat "$A/q-system/CLAUDE.md")" = "orig" ] || fail "synced file not reverted to pre-sync content"
[ "$(cat "$A/q-system/my-project/current-state.md")" = "$PRE_STATE" ] || fail "preserved my-project file changed"
[ "$(cat "$A/q-system/canonical/decisions.md")" = "$PRE_DEC" ] || fail "preserved canonical file changed"
log_a="$(G -C "$A" log --format=%s)"
grep -qx "chore: auto-commit before kipi update" <<<"$log_a" || fail "pre-sync auto-commit lost"
head_a="$(G -C "$A" log -1 --format=%s)"
grep -qi "^Revert" <<<"$head_a" || fail "HEAD is not a Revert commit"

# 2. dirty tree refuses, instance untouched
B="$WORK/inst-b"; mk_instance "$B"
printf 'dirty\n' >> "$B/q-system/CLAUDE.md"
REGB="$WORK/reg2.json"; mk_registry "$REGB" "inst-b::$B"
HEAD_B="$(G -C "$B" rev-parse HEAD)"
OUTB="$(KIPI_REGISTRY="$REGB" bash "$RB" 2>&1)" || true
grep -qi "SKIP (dirty" <<<"$OUTB" || fail "dirty tree was not refused: $OUTB"
[ "$(G -C "$B" rev-parse HEAD)" = "$HEAD_B" ] || fail "dirty instance HEAD moved (must be untouched)"

# 3. revert conflict aborts cleanly (no half-applied revert), reports FAIL, exits 1
C="$WORK/inst-c"; mk_instance "$C"
( cd "$C" && printf 'manual-v3\n' > q-system/CLAUDE.md && G add -A && G commit -qm "manual edit on top of sync" )
REGC="$WORK/reg3.json"; mk_registry "$REGC" "inst-c::$C"
HEAD_C="$(G -C "$C" rev-parse HEAD)"
OUTC="$(KIPI_REGISTRY="$REGC" bash "$RB" 2>&1)" && rc=0 || rc=$?
grep -qi "FAIL (revert" <<<"$OUTC" || fail "conflict not reported as FAIL: $OUTC"
[ "${rc:-0}" -ne 0 ] || fail "script exited 0 despite a failed instance (should be 1)"
[ ! -f "$C/.git/REVERT_HEAD" ] || fail "REVERT_HEAD left behind (half-applied revert)"
{ G -C "$C" diff --quiet && G -C "$C" diff --cached --quiet; } || fail "conflict left a dirty tree (not aborted cleanly)"
[ "$(G -C "$C" rev-parse HEAD)" = "$HEAD_C" ] || fail "conflicted instance HEAD moved (abort must leave it untouched)"

# 4. no sync commit -> SKIP
D="$WORK/inst-d"; mkdir -p "$D"
( cd "$D" && G init -q && mkdir -p q-system && printf 'x\n' > q-system/a.md && G add -A && G commit -qm baseline )
REGD="$WORK/reg4.json"; mk_registry "$REGD" "inst-d::$D"
OUTD="$(KIPI_REGISTRY="$REGD" bash "$RB" 2>&1)" || fail "no-sync-commit run exited non-zero: $OUTD"
grep -qi "SKIP (no skeleton-sync" <<<"$OUTD" || fail "instance with no sync commit not skipped: $OUTD"

# 5. a content commit sits ON TOP of the sync -> rollback targets the SYNC (message-prefix),
#    not HEAD. This is the finding-1 correctness case: a `git revert HEAD` impl would fail it.
E="$WORK/inst-e"; mk_instance "$E"
( cd "$E" && printf 'note\n' > q-system/notes.md && G add -A && G commit -qm "add notes (content commit on top of sync)" )
REGE="$WORK/reg5.json"; mk_registry "$REGE" "inst-e::$E"
OUTE="$(KIPI_REGISTRY="$REGE" bash "$RB" 2>&1)" || fail "content-on-top rollback exited non-zero: $OUTE"
grep -qi "ROLLED BACK" <<<"$OUTE" || fail "content-on-top did not roll back: $OUTE"
[ "$(cat "$E/q-system/CLAUDE.md")" = "orig" ] || fail "sync NOT reverted with a content commit on top (reverted HEAD instead of the sync)"
[ "$(cat "$E/q-system/notes.md")" = "note" ] || fail "content commit on top was wrongly reverted (must stay untouched)"

# 6. direct-clone instance (no local sync commit) -> clearer, type-aware SKIP message (review minor)
F2="$WORK/inst-f"; mkdir -p "$F2"
( cd "$F2" && G init -q && mkdir -p q-system && printf 'x\n' > q-system/a.md && G add -A && G commit -qm base )
REGF="$WORK/reg6.json"
python3 -c "import json;json.dump({'instances':[{'name':'inst-f','path':'$F2','type':'direct-clone'}]},open('$REGF','w'))"
OUTF="$(KIPI_REGISTRY="$REGF" bash "$RB" 2>&1)" || fail "direct-clone run exited non-zero: $OUTF"
grep -qi "direct-clone" <<<"$OUTF" || fail "direct-clone instance did not get the type-aware SKIP message: $OUTF"

# 7. empty/all-merged registry -> explicit 'no eligible instances', not a silent 0/0/0 success
REGE2="$WORK/reg7.json"
python3 -c "import json;json.dump({'instances':[{'name':'gone','path':'$WORK/none','status':'merged'}]},open('$REGE2','w'))"
OUTE2="$(KIPI_REGISTRY="$REGE2" bash "$RB" 2>&1)" || fail "empty-registry run exited non-zero: $OUTE2"
grep -qi "No eligible instances" <<<"$OUTE2" || fail "empty registry did not signal 'no eligible instances': $OUTE2"

echo "PASS: rollback reverts sync by message-prefix (even with a content commit on top), preserves instance dirs + pre-sync commit, refuses dirty trees, aborts cleanly on conflict, skips no-sync + direct-clone instances with clear messages, signals an empty registry"

# --- a real update writes TWO commits; rollback must undo both ---------------
# kipi-update.sh writes "chore: sync q-system from skeleton" AND "chore: sync
# .claude config + plugins from skeleton". SYNC_PREFIX matched only the first,
# so a rollback reverted the q-system half and silently left the config and
# plugin half applied. Every fixture in this suite created only the first
# commit, so the blind spot was untestable by construction.
WORK2="$(mktemp -d)"; INST2="$WORK2/inst"
mkdir -p "$INST2/q-system" "$INST2/.claude/rules"
( cd "$INST2" && G init -q
  printf 'v1\n' > q-system/tracked.md
  printf 'rule v1\n' > .claude/rules/demo.md
  G add -A && G commit -qm "instance baseline"
  printf 'v2\n' > q-system/tracked.md
  G add -A && G commit -qm "chore: sync q-system from skeleton 2026-07-25"
  printf 'rule v2\n' > .claude/rules/demo.md
  G add -A && G commit -qm "chore: sync .claude config + plugins from skeleton 2026-07-25" )
printf '{"instances":[{"name":"two","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$INST2" > "$WORK2/registry.json"

KIPI_REGISTRY="$WORK2/registry.json" bash "$RB" >/dev/null 2>&1 || true
q="$(cat "$INST2/q-system/tracked.md")"
r="$(cat "$INST2/.claude/rules/demo.md")"
[ "$q" = "v1" ] || fail "q-system half not rolled back (got '$q')"
[ "$r" = "rule v1" ] || fail "config+plugins half NOT rolled back (got '$r') -- SYNC_PREFIX missed the second commit"
echo "PASS: rollback undoes both commits a single update writes"

