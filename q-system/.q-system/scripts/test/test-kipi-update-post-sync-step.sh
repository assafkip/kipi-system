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
# Shape B (founder, 2026-11-13): the updater does NOT police what the step
# writes. PRs #780 and #784 did, and each round found a new gap in that code.
# What holds instead is that the config commit stages only .claude/ and
# plugins/ (case 7 proves it with git show --name-only).
#
# Every fixture is a scratch skeleton and scratch instances under mktemp -d. No
# real instance and no real data path is touched. KIPI_UPDATE_UNDER_TEST points
# the cases at a mutated copy of the updater.
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
rolled_back() { echo "$1" | grep -q "config sync did not reach a complete committed state"; }
# Captured first: under pipefail, grep -q closing the pipe early makes git log
# exit 141 and the check reads false on a commit that exists.
synced_commit() { local l; l="$(G -C "$1" log --format=%s)"; case "$l" in *"sync .claude config"*) return 0;; esac; return 1; }
# The seeded uncommitted human file: untouched and still untracked after every case.
assert_human() {
  [ "$(cat "$1/human-notes.txt")" = "unsaved human notes" ] || fail "human file changed in $1"
  [ "$(status_of "$1" | grep human-notes)" = "?? human-notes.txt" ] || fail "human file no longer untracked in $1"
  G -C "$1" diff --cached --quiet || fail "index left staged in $1"
}

# ---------------- 1. no declaration: today's behaviour ----------------
W="$(newdir)"; build_fixture "$W" "$SCRIPT" ""
B="$(status_of "$W/needy")"
OUT="$(run "$W" --only needy)"
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
[ -f "$W/needy/.mirror-ok" ] || fail "case 2: the step's product must stay"
echo "$OUT" | grep -q "Running post-sync step: touch .mirror-ok" || fail "case 2 did not name the step: $OUT"
assert_human "$W/needy"
echo "PASS 2: declared step makes the commit-time check pass"

# Reproducer: the SAME fixture on origin/main's updater ignores the declaration.
BASE=""
if [ -z "${KIPI_UPDATE_UNDER_TEST:-}" ]; then
  BASE="$(newdir)/kipi-update.base.sh"
  G -C "$ROOT" show origin/main:kipi-update.sh > "$BASE" 2>/dev/null || BASE=""
  if [ -n "$BASE" ] && ! grep -q 'kipi-post-sync' "$BASE"; then
    W="$(newdir)"; build_fixture "$W" "$BASE" "touch .mirror-ok"
    OUT="$(run "$W" --only needy)"
    rolled_back "$OUT" || fail "case 2 on the old updater should be red: $OUT"
    echo "PASS 2b: reproducer is red on origin/main's updater"
  else
    BASE=""
    echo "NOTE 2b: origin/main already carries the feature (or is unreadable); reproducer skipped"
  fi
fi

# ---------------- 3 and 4. failing / missing step ----------------
# The steps create the marker BEFORE they fail: with the marker absent the
# instance's own hook would roll the sync back anyway and a mutant that ignored
# the step's exit code would survive.
for spec in "failing|touch .mirror-ok && sh -c 'echo step-says-no; exit 3'" "missing|touch .mirror-ok && kipi-no-such-command-xyz"; do
  label="${spec%%|*}"; decl="${spec#*|}"
  W="$(newdir)"; build_fixture "$W" "$SCRIPT" "$decl"
  OUT="$(run "$W")"
  rolled_back "$OUT" || fail "case 3/4 ($label) should roll back: $OUT"
  echo "$OUT" | grep -qF "ERROR: post-sync step failed: $decl" || fail "case 3/4 ($label) did not name the step: $OUT"
  echo "$OUT" | grep -qF "[post-sync step failed: $decl]" || fail "case 3/4 ($label) summary lacks the step: $OUT"
  [ "$label" = failing ] && { echo "$OUT" | grep -q "step-says-no" || fail "step's own output missing: $OUT"; }
  synced_commit "$W/needy" && fail "case 3/4 ($label) committed despite a failed step: $OUT"
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
assert_human "$W/needy"
echo "PASS 5: dry run prints the step and does not run it"

# ---------------- 6. two commands ----------------
W="$(newdir)"; RAN="$W/step-ran"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok
touch $RAN"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" || fail "case 6 should refuse: $OUT"
[ ! -e "$RAN" ] || fail "case 6 ran a command from a malformed declaration"
assert_human "$W/needy"
echo "PASS 6: a declaration with two commands is refused"

# ---------------- 7. the claim Shape B rests on ----------------
# The step writes a tracked-file edit and a new file OUTSIDE the synced paths,
# plus one new file under plugins/ (inside them). The config commit must hold
# only .claude/ and plugins/ paths. The updater does not undo the outside
# writes either: they stay on disk, as the step left them.
W="$(newdir)"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok && printf 'edited by step\n' > NOTES-AT-ROOT.md && printf 'new\n' > outside-new.txt && printf 'p\n' > plugins/from-step.txt"
OUT="$(run "$W" --only needy)"
rolled_back "$OUT" && fail "case 7 did not complete: $OUT"
SHA="$(G -C "$W/needy" log --format='%H %s' | grep 'sync .claude config' | cut -d' ' -f1)"
[ -n "$SHA" ] || fail "case 7 made no config commit: $OUT"
FILES="$(G -C "$W/needy" show --name-only --format= "$SHA")"
echo "$FILES" | grep -qE '^(\.claude/|plugins/)' || fail "case 7: config commit holds no synced path: $FILES"
echo "$FILES" | grep -vE '^(\.claude/|plugins/)' | grep -q . && fail "case 7: config commit holds a path outside the synced ones: $FILES"
echo "$FILES" | grep -qE 'NOTES-AT-ROOT.md|outside-new.txt' && fail "case 7: the step's outside write is in the commit: $FILES"
[ "$(cat "$W/needy/NOTES-AT-ROOT.md")" = "edited by step" ] || fail "case 7: the updater undid the step's write"
[ -f "$W/needy/outside-new.txt" ] || fail "case 7: the updater removed the step's new file"
assert_human "$W/needy"
echo "  case 7 config commit paths: $(echo $FILES)"
echo "PASS 7: the config commit holds only synced paths; the step's outside writes stay uncommitted and untouched"

# ---------------- 8. no declaration is identical to origin/main ----------------
if [ -n "$BASE" ]; then
  # Commit ids differ by construction (the two skeletons hold different updaters).
  norm() { sed -E -e "s#$1#WORK#g" -e 's/^\[master [0-9a-f]+\]/[master SHA]/'; }
  for hook in yes no; do
    WA="$(newdir)"; NEEDY_HOOK=$hook build_fixture "$WA" "$BASE" ""
    WB="$(newdir)"; NEEDY_HOOK=$hook build_fixture "$WB" "$SCRIPT" ""
    OA="$(run "$WA" | norm "$WA")"; OB="$(run "$WB" | norm "$WB")"
    [ "$OA" = "$OB" ] || fail "case 8 ($hook): output differs from origin/main:
$(diff <(echo "$OA") <(echo "$OB"))"
    [ "$(status_of "$WA/needy")" = "$(status_of "$WB/needy")" ] || fail "case 8 ($hook): needy status differs"
    [ "$(G -C "$WA/needy" rev-parse 'HEAD^{tree}')" = "$(G -C "$WB/needy" rev-parse 'HEAD^{tree}')" ] || fail "case 8 ($hook): needy tree differs"
  done
  echo "PASS 8: with no declaration the run is identical to origin/main's updater"
fi

# ---------------- 9. a step that reads stdin must not eat the instance loop ----------------
# PR #785 round 1: the instance loop reads the registry from stdin, so a step
# that read stdin (ssh, git push over ssh, cat) consumed the remaining rows. The
# other instances were never processed and the run still exited 0.
W="$(newdir)"
build_fixture "$W" "$SCRIPT" "touch .mirror-ok && cat >/dev/null"
mk_inst "$W/third" "" no
printf '{"instances":[{"name":"needy","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"other","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"third","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$W/needy" "$W/other" "$W/third" > "$W/skel/instance-registry.json"
OUT="$(run "$W")"
for inst in needy other third; do
  synced_commit "$W/$inst" || fail "case 9: $inst was not synced after a step read stdin: $OUT"
done
echo "$OUT" | grep -qE "Updated: +3" || fail "case 9: summary does not count three instances: $OUT"
echo "PASS 9: a step that reads stdin leaves every later instance synced"

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
  'bash -c "$POST_SYNC_STEP" </dev/null 2>&1)"; then' 'bash -c "$POST_SYNC_STEP" </dev/null 2>&1; true)"; then'
mutant "dry run executes the step" \
  'elif [ "$DRY_RUN" = "--dry-run" ]; then
        echo "    post-sync step (dry run' 'elif false; then
        echo "    post-sync step (dry run'
mutant "commit still runs after a failed step" \
  '[ -z "$POST_SYNC_FAILED_STEP" ] &&
        git -C "$path" rev-parse --git-dir' 'true &&
        git -C "$path" rev-parse --git-dir'
mutant "one-command check loosened" \
  '-ne 1 ]; then' '-ne 2 ]; then'
mutant "summary stops naming the step" \
  '${POST_SYNC_FAILED_STEP:+ [post-sync step failed: $POST_SYNC_FAILED_STEP]}' ''
mutant "step keeps the loop's stdin" \
  'bash -c "$POST_SYNC_STEP" </dev/null 2>&1)"; then' 'bash -c "$POST_SYNC_STEP" 2>&1)"; then'
mutant "config staging widened to the whole tree" \
  'git -C "$target" add -u -- "$scope/" || return 1' 'git -C "$target" add -u || return 1'
echo "ALL PASS"
