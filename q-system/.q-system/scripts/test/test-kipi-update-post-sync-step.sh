#!/usr/bin/env bash
# An instance's declared post-sync step runs before the config commit (ASK-4726).
#
# Scar: an instance whose pre-commit check refuses the config commit until a
# derived artifact is refreshed was rolled back by every sync that delivered a
# new engine file ("config sync did not reach a complete committed state"),
# four times, each unblocked by hand. The artifact can only be refreshed once
# the engine is on disk, so the step must run after the rsync and before the
# commit. Here the "check" is a pre-commit hook that refuses a commit staging
# .claude/ or plugins/ unless a marker file exists; the declared step makes it.
#
# Every fixture is a scratch skeleton and scratch instances under mktemp -d. No
# real instance and no real data path is touched.
#
# Cases: 1 no declaration (rolls back, as before)  2 step makes the marker
# (completes; the SAME fixture on origin/main's updater is red)  3 step makes
# the marker then exits non-zero (rolled back, step named, a second instance
# unaffected)  4 same with a missing command  5 dry run (printed, not run)
# 6 a declaration holding two commands is refused.  Then one mutant per
# decision point; each must turn this file red.
#
# The failing steps create the marker BEFORE they fail, on purpose: with the
# marker absent the instance's own hook would roll the sync back anyway, and a
# mutant that ignored the step's exit code would survive.
#
# KIPI_UPDATE_UNDER_TEST points the cases at a mutated copy of the updater.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT="${KIPI_UPDATE_UNDER_TEST:-$ROOT/kipi-update.sh}"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
TOP="$(mktemp -d)"
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TOP"' EXIT
# mktemp, not a counter: callers use $(newdir), a subshell, and a counter bumped
# there is lost, which handed every case the SAME directory.
newdir() { mktemp -d "$TOP/w.XXXXXX"; }

# $1 = instance dir, $2 = declaration text ("" = none), $3 = yes|no: marker hook
mk_inst() {
  local inst="$1" decl="$2" hook="$3"
  mkdir -p "$inst/q-system" "$inst/.claude/rules"
  printf 'skeleton content v1 (old)\n' > "$inst/q-system/tracked.md"
  printf '{}\n' > "$inst/.claude/settings.json"
  printf 'committed root notes\n' > "$inst/NOTES-AT-ROOT.md"
  printf '# stale rule\n' > "$inst/.claude/rules/demo-rule.md"
  # Hostile names for the invariant case: a space and non-ASCII (git C-quotes
  # both in porcelain output) and a file the step renames.
  printf 'committed accented\n' > "$inst/root notes é.md"
  printf 'committed rename me\n' > "$inst/to-rename.md"
  [ -n "$decl" ] && printf '%s\n' "$decl" > "$inst/.kipi-post-sync"
  ( cd "$inst" && G init -q && G add -A && G commit -qm inst )
  # An uncommitted human file: must survive every case untouched.
  printf 'unsaved human notes\n' > "$inst/human-notes.txt"
  if [ "$hook" = yes ]; then
    mkdir -p "$inst/.git/hooks"
    cat > "$inst/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# The shape of a mirror gate: refuse a config commit until the derived artifact
# (the marker) exists in the tree.
if git diff --cached --name-only | grep -qE '^(\.claude/|plugins/)' \
    && [ ! -f "$(git rev-parse --show-toplevel)/.mirror-ok" ]; then
  echo "pre-commit: mirror is STALE (marker missing)" >&2
  exit 1
fi
exit 0
HOOK
    chmod +x "$inst/.git/hooks/pre-commit"
  fi
}

# $1 = work dir, $2 = updater to install as the skeleton's, $3 = declaration
build_fixture() {
  local work="$1" updater="$2" decl="$3"
  local sk="$work/skel"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/.claude/rules" "$sk/plugins/demo"
  cp "$updater" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/kipi-update-deletion-guard.py" "$sk/kipi-update-deletion-guard.py"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  # Fail-closed gates and helpers the updater requires of any skeleton; a
  # fixture without them aborts before the sync (measured: the older
  # config-commit-unwind fixture lacks the divergence gate and is red on main).
  cp "$ROOT/kipi-settings-merge.py" "$sk/kipi-settings-merge.py"
  cp "$ROOT/q-system/.q-system/scripts/fleet-replica-divergence.py" \
     "$sk/q-system/.q-system/scripts/fleet-replica-divergence.py"
  printf 'raise SystemExit(0)\n' > "$sk/q-system/.q-system/scripts/capability-gate.py"
  printf '{"permissions":{"allow":["Read"]},"hooks":{}}\n' > "$sk/settings-template.json"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
  printf 'skeleton content v2\n' > "$sk/q-system/tracked.md"
  printf '# a rule\n' > "$sk/.claude/rules/demo-rule.md"
  printf '{"name":"demo","version":"0.0.1"}\n' > "$sk/plugins/demo/plugin.json"
  printf '{"hooks":{}}\n' > "$sk/.claude/settings.json"
  ( cd "$sk" && G init -q && G add -A -f && G commit -qm skel )
  mk_inst "$work/needy" "$decl" "${NEEDY_HOOK:-yes}"
  mk_inst "$work/other" "" no
  printf '{"instances":[{"name":"needy","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"other","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$work/needy" "$work/other" > "$sk/instance-registry.json"
}

run() { bash "$1/skel/kipi-update.sh" "${@:2}" 2>&1; }
# Unfiltered on purpose. It used to drop `?? .mirror-ok`, the one untracked file
# every case's step creates, so a step's untracked leftovers were invisible to
# every status comparison (PR #780 round 3).
status_of() { G -C "$1" status --porcelain=v1 -z | tr '\0' '\n' | sort; }
# The whole observable state of an instance, read with git's own NUL output and
# never parsed by hand: HEAD, the index (mode, blob, path), every tracked or
# untracked file by content hash and mode, and the stash list. A standalone
# script, so the hostile step can take the same fingerprint at the moment it
# starts: that is the "before" the invariant is about.
FP="$TOP/fp.sh"
cat > "$FP" <<'FPEOF'
d="$1"
g() { git -c user.email=t@t.t -c user.name=test -C "$d" "$@"; }
g rev-parse HEAD
g ls-files -s -z | tr '\0' '\n'
echo "--- stash"; g stash list
echo "--- files"
g ls-files -z -c -o | python3 -c '
import hashlib, os, sys
root = sys.argv[1]
for rel in sorted(sys.stdin.buffer.read().split(b"\0")):
    if not rel:
        continue
    p = os.path.join(root.encode(), rel)
    try:
        st = os.lstat(p)
        body = os.readlink(p).encode() if os.path.islink(p) else open(p, "rb").read()
        print(oct(st.st_mode), hashlib.sha256(body).hexdigest(), repr(rel))
    except OSError:
        print("MISSING", repr(rel))
' "$d"
FPEOF
# .claude/ and plugins/ are left out of the comparison: the updater's existing
# rollback resets them to HEAD after any refusal, which would hide whether the
# step rollback did its part. Writes there are asserted by name instead.
fingerprint() { bash "$FP" "$1" | grep -vE "(\.claude|plugins)/"; }
rolled_back() { echo "$1" | grep -q "config sync did not reach a complete committed state"; }
# Captured first: under pipefail, grep -q closing the pipe early makes git log
# exit 141 and the check reads false on a commit that exists.
synced_commit() { local l; l="$(G -C "$1" log --format=%s)"; case "$l" in *"sync .claude config"*) return 0;; esac; return 1; }
assert_human() {
  [ "$(cat "$1/human-notes.txt")" = "unsaved human notes" ] || fail "human file changed in $1"
  [ "$(status_of "$1" | grep human-notes)" = "?? human-notes.txt" ] || fail "human file no longer untracked in $1"
  G -C "$1" diff --cached --quiet || fail "index left staged in $1"
}

# ---------------- 1. no declaration: today's behaviour ----------------
W="$(newdir)"; build_fixture "$W" "$SCRIPT" ""
B="$(status_of "$W/needy")"
OUT="$(run "$W" --only needy)"
echo "$OUT" | grep -q "Syncing .claude/ config" || fail "case 1 never reached config sync: $OUT"
echo "$OUT" | grep -q "mirror is STALE" || fail "case 1 hook never refused: $OUT"
rolled_back "$OUT" || fail "case 1 should roll back: $OUT"
echo "$OUT" | grep -q "post-sync" && fail "case 1 mentions a post-sync step without a declaration: $OUT"
[ "$(status_of "$W/needy")" = "$B" ] || fail "case 1 status changed"
assert_human "$W/needy"
echo "PASS 1: no declaration, rolled back as before"

# ---------------- 2. step makes the marker ----------------
W="$(newdir)"; build_fixture "$W" "$SCRIPT" "touch .mirror-ok"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" && fail "case 2 did not complete: $OUT"
synced_commit "$W/needy" || fail "case 2 made no config commit: $OUT"
[ -f "$W/needy/.mirror-ok" ] || fail "case 2: the step's untracked product must stay on success"
echo "$OUT" | grep -q "Running post-sync step: touch .mirror-ok" || fail "case 2 did not name the step: $OUT"
assert_human "$W/needy"
echo "PASS 2: declared step makes the commit-time check pass"

# Reproducer: the SAME fixture on origin/main's updater ignores the declaration.
if [ -z "${KIPI_UPDATE_UNDER_TEST:-}" ]; then
  BASE="$(newdir)/kipi-update.base.sh"
  G -C "$ROOT" show origin/main:kipi-update.sh > "$BASE" 2>/dev/null || BASE=""
  if [ -n "$BASE" ] && ! grep -q 'kipi-post-sync' "$BASE"; then
    W="$(newdir)"; build_fixture "$W" "$BASE" "touch .mirror-ok"
    OUT="$(run "$W" --only needy)"
    rolled_back "$OUT" || fail "case 2 on the old updater should be red: $OUT"
    echo "PASS 2b: reproducer is red on origin/main's updater"
  else
    echo "NOTE 2b: origin/main already carries the feature (or is unreadable); reproducer skipped"
  fi
fi

# ---------------- 3 and 4. failing / missing step ----------------
for spec in "failing|touch .mirror-ok && sh -c 'echo step-says-no; exit 3'" "missing|touch .mirror-ok && kipi-no-such-command-xyz"; do
  label="${spec%%|*}"; decl="${spec#*|}"
  W="$(newdir)"; build_fixture "$W" "$SCRIPT" "$decl"
  B="$(status_of "$W/needy")"
  OUT="$(run "$W")"
  rolled_back "$OUT" || fail "case 3/4 ($label) should roll back: $OUT"
  echo "$OUT" | grep -qF "ERROR: post-sync step failed: $decl" || fail "case 3/4 ($label) did not name the step: $OUT"
  echo "$OUT" | grep -qF "[post-sync step failed: $decl]" || fail "case 3/4 ($label) summary lacks the step: $OUT"
  [ "$label" = failing ] && { echo "$OUT" | grep -q "step-says-no" || fail "step's own output missing: $OUT"; }
  synced_commit "$W/needy" && fail "case 3/4 ($label) committed despite a failed step: $OUT"
  [ "$(status_of "$W/needy")" = "$B" ] || fail "case 3/4 ($label) needy status changed"
  assert_human "$W/needy"
  synced_commit "$W/other" || fail "case 3/4 ($label) other instance was affected: $OUT"
  echo "PASS 3/4 ($label): rolled back, step named, other instance synced"
done

# ---------------- 5. dry run ----------------
W="$(newdir)"; RAN="$W/step-ran"
build_fixture "$W" "$SCRIPT" "touch $RAN"
OUT="$(run "$W" --dry-run --only needy)"
echo "$OUT" | grep -qF "post-sync step (dry run, NOT run): touch $RAN" || fail "case 5 did not print the command: $OUT"
[ ! -e "$RAN" ] || fail "case 5 ran the command"
echo "PASS 5: dry run prints the step and does not run it"

# ---------------- 6. two commands ----------------
W="$(newdir)"; RAN="$W/step-ran"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok
touch $RAN"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 6 should refuse: $OUT"
[ ! -e "$RAN" ] || fail "case 6 ran a command from a malformed declaration"
echo "PASS 6: a declaration with two commands is refused"

# ---------------- 7 and 8. writes outside the committed scope ----------------
# PR #780 review: a step writing a tracked file outside .claude/ and plugins/
# was neither committed nor rolled back. A success wedged the next run at the
# dirty-tree guard; a failure left the clobbered file behind.
W="$(newdir)"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok && printf 'derived\n' > q-system/tracked.md"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 7 should refuse a step that dirties q-system/: $OUT"
echo "$OUT" | grep -qF "went outside its bounds" || fail "case 7 did not say why: $OUT"
[ "$(cat "$W/needy/q-system/tracked.md")" != "derived" ] || fail "case 7 left the step's write behind"
synced_commit "$W/needy" && fail "case 7 committed: $OUT"
assert_human "$W/needy"
echo "PASS 7: a successful step that dirties tracked files outside scope is refused and restored"

W="$(newdir)"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok && printf 'CLOBBERED\n' > NOTES-AT-ROOT.md && git add NOTES-AT-ROOT.md && exit 3"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 8 should roll back: $OUT"
[ "$(cat "$W/needy/NOTES-AT-ROOT.md")" = "committed root notes" ] || fail "case 8: a failed step's write survived the rollback"
assert_human "$W/needy"
echo "PASS 8: a failed step's out-of-scope write is restored"

# ---------------- 9. the invariant, over hostile writes ----------------
# After a refused or failed step, the instance's tracked content, index,
# untracked set and stash list equal the state before the run. Rounds 2 and 3 of
# PR #780 were two defects in a hand-rolled undo pass; this case asserts the
# property once, over every hostile write at the same time, for both a step that
# exits 0 (refused) and one that exits non-zero (failed).
for exitcode in 0 3; do
  W="$(newdir)"
  cat > "$W/hostile.sh" <<HOSTILE
bash $FP "\$PWD" > $W/fp.before
touch .mirror-ok
printf 'X\n' > "root notes é.md"
git mv to-rename.md "renamed é.md"
printf 'n\n' > new-staged.md && git add new-staged.md
printf 'u\n' > "new untracked é.txt"
mkdir -p deep/dir && printf 'u\n' > deep/dir/f
printf 'I\n' > .claude/rules/demo-rule.md
printf 'U\n' > .claude/rules/from-the-step.md
printf 'H\n' >> human-notes.txt
exit $exitcode
HOSTILE
  build_fixture "$W" "$SCRIPT" "sh $W/hostile.sh"
  OUT="$(run "$W" --only needy)"
  FP_BEFORE="$(grep -vE "(\.claude|plugins)/" "$W/fp.before")"
  rolled_back "$OUT" || fail "case 9 (exit $exitcode) should roll back: $OUT"
  synced_commit "$W/needy" && fail "case 9 (exit $exitcode) committed: $OUT"
  FP_AFTER="$(fingerprint "$W/needy")"
  [ -s "$W/fp.before" ] || fail "case 9 (exit $exitcode): the step never ran"
  if [ "$exitcode" = 0 ]; then
    echo "$OUT" | grep -qF ".claude/rules/from-the-step.md" || fail "case 9: a new file under .claude/ was not named: $OUT"
    echo "$OUT" | grep -qF ".claude/rules/demo-rule.md" || fail "case 9: a changed file under .claude/ was not named: $OUT"
  fi
  [ "$(cat "$W/needy/.claude/rules/demo-rule.md")" = "# stale rule" ] || fail "case 9 (exit $exitcode): .claude/ write survived"
  [ ! -e "$W/needy/.claude/rules/from-the-step.md" ] || fail "case 9 (exit $exitcode): .claude/ file created by the step survived"
  [ "$FP_BEFORE" = "$FP_AFTER" ] || fail "case 9 (exit $exitcode): state differs after the refusal:
$(diff <(echo "$FP_BEFORE") <(echo "$FP_AFTER"))"
done
echo "PASS 9: refused and failed steps leave tracked content, index, untracked set and stash list unchanged"

# ---------------- 10. a failed step must stop the commit by itself ----------------
# With the marker rolled back (case 3/4) the instance's own hook refuses the
# commit anyway, which hid a mutant that commits after a failed step. An
# instance with no hook makes the updater's own skip the only thing in the way.
W="$(newdir)"; NEEDY_HOOK=no build_fixture "$W" "$SCRIPT" "sh -c 'exit 3'"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 10 should roll back: $OUT"
synced_commit "$W/needy" && fail "case 10 committed after a failed step: $OUT"
echo "PASS 10: no config commit after a failed step, with no hook to stop it"

# ---------------- 11. an index-only change ----------------
# Staging a file already in the tree changes no tree object, so only the index
# comparison sees it. The human file must come back unstaged.
W="$(newdir)"; build_fixture "$W" "$SCRIPT" "touch .mirror-ok && git add human-notes.txt"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 11 should refuse an index change: $OUT"
echo "$OUT" | grep -qF "the index changed" || fail "case 11 did not say why: $OUT"
assert_human "$W/needy"
echo "PASS 11: a step that only stages is refused and the index restored"

[ -n "${KIPI_UPDATE_UNDER_TEST:-}" ] && exit 0

# ---------------- mutants: one per decision point ----------------
# A mutant whose anchor does not match exactly once is a FAILED EXPERIMENT, not
# a kill. Each mutant is a copy of the updater run through the cases above.
mutant() {  # $1 label, $2 old, $3 new
  local out; out="$(newdir)/mutant.sh"
  python3 - "$SCRIPT" "$out" "$2" "$3" <<'PY' || fail "mutant '$1' not applicable (anchor must match exactly once)"
import sys
src, dst, old, new = sys.argv[1:5]
t = open(src).read()
if t.count(old) != 1:
    sys.exit(1)
open(dst, "w").write(t.replace(old, new))
PY
  if KIPI_UPDATE_UNDER_TEST="$out" bash "${BASH_SOURCE[0]}" >/dev/null 2>&1; then
    fail "MUTANT SURVIVED: $1"
  fi
  echo "KILLED: $1"
}
mutant "declaration ignored" \
  '[ -f "$path/$POST_SYNC_DECL" ]; then' '[ -f "$path/$POST_SYNC_DECL.off" ]; then'
mutant "step exit code ignored" \
  'bash -c "$POST_SYNC_STEP" 2>&1)"; then' 'bash -c "$POST_SYNC_STEP" 2>&1; true)"; then'
mutant "dry run executes the step" \
  'elif [ "$DRY_RUN" = "--dry-run" ]; then
        echo "    post-sync step (dry run' 'elif false; then
        echo "    post-sync step (dry run'
mutant "commit still runs after a failed step" \
  '[ -z "$POST_SYNC_FAILED_STEP" ] &&
        git -C "$path" rev-parse --git-dir' 'true &&
        git -C "$path" rev-parse --git-dir'
mutant "out-of-bounds writes not detected" \
  'if [ -n "$ps_bad" ]; then' 'if false; then'
mutant "rollback skipped after a refusal" \
  'if [ -n "$POST_SYNC_FAILED_STEP" ]; then
            ps_rollback' 'if false; then
            ps_rollback'
mutant "added files are not removed" \
  '| ( cd "$repo" && xargs -0 rm -f -- )' '| ( cd "$repo" && cat >/dev/null )'
mutant "changed files are not restored" \
  'checkout-index -f -z --stdin || return 1' 'checkout-index -f -z --stdin </dev/null || return 1'
mutant "real index not restored" \
  'cp -- "$dir/index.before" "$real"; else' 'true; else'
mutant "an index change is not a violation" \
  'cmp -s "$dir/ls.before" "$dir/ls.after" || echo "(the index changed)"' 'true'
mutant "a write under .claude/ is allowed" \
  '.claude/*) printf' '.claude-x/*) printf'
mutant "a changed file outside plugins/ is allowed" \
  'case "$p" in plugins/*) ;; *) printf' 'case "$p" in *) ;; *) printf'
mutant "one-command check loosened" \
  '-ne 1 ]; then' '-ne 2 ]; then'
mutant "summary stops naming the step" \
  '${POST_SYNC_FAILED_STEP:+ [post-sync step failed: $POST_SYNC_FAILED_STEP]}' ''
echo "ALL PASS"
