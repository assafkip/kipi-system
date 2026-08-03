#!/bin/bash
# Pairs with: ff-merge-if-safe.sh (ASK-294 stale-checkout handler).
#
# EVERY CASE RUNS AGAINST A THROWAWAY REPO BUILT IN mktemp -d. Nothing here ever
# points at the founder's checkout: the script under test performs a real
# `git merge` on whatever it is handed, so a suite that aimed it at the live tree
# would BE the data-loss bug it exists to prevent.
#
# The two cases that carry the design are 4 and 7, and they pull in opposite
# directions:
#   4  an IGNORED file in the merge set must STOP the merge (the ASK-284 r1 scar:
#      a fast-forward overwrites it silently, exit 0, no reflog).
#   7  an ignored file OUTSIDE the merge set must NOT stop it. This checkout
#      carries 3982 ignored files, so a guard keyed on "is the tree clean" would
#      refuse every time and the handler would be decoration -- quiet, green, and
#      never once doing its job.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$(cd "$HERE/.." && pwd)/ff-merge-if-safe.sh"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
G() { git -C "$1" -c user.email=t@t -c user.name=t -c commit.gpgsign=false "${@:2}"; }

# origin = a bare repo; clone = the "checkout" the loop runs. Real remotes, so
# rev-parse origin/main resolves exactly as it does in production.
new_pair() {
  local n="$1" up="$WORK/$1.git" wt="$WORK/$1" ignore="${2:-}"
  git init -q --bare "$up"
  # A bare repo's HEAD defaults to refs/heads/master, so `git clone` of it checks
  # out nothing and every author-side commit+push fails with "src refspec main
  # does not match any". symbolic-ref rather than --initial-branch: works on the
  # older git macOS ships too.
  git -C "$up" symbolic-ref HEAD refs/heads/main
  git init -q "$wt"; G "$wt" remote add origin "$up"
  printf 'base\n' > "$wt/base.txt"
  # The ignore rule must live in the BASE commit for case 4. An ignore rule that
  # exists only upstream is not in effect locally, so that case would silently
  # degrade into the plain-untracked case 3 and prove nothing new.
  [ -z "$ignore" ] || printf '%s\n' "$ignore" > "$wt/.gitignore"
  G "$wt" add -A; G "$wt" commit -qm base
  G "$wt" branch -M main; G "$wt" push -q origin main
  # A second clone is where "origin moves ahead" is authored.
  rm -rf "$WORK/$n-author"; git clone -q "$up" "$WORK/$n-author"
  G "$WORK/$n-author" config user.email t@t; G "$WORK/$n-author" config user.name t
}
advance_origin() {  # advance_origin <name> <file> <content>
  local n="$1" wt="$WORK/$1-author"
  printf '%s\n' "$3" > "$wt/$2"
  # add -f, not add -A: case 4's incoming file is covered by the base commit's
  # .gitignore, so `add -A` skipped it, the author's commit was EMPTY, origin
  # never moved, and the case passed as "already current" while testing nothing.
  # A tracked file that also matches .gitignore is exactly the shape that scar is
  # about, so the fixture has to be able to create it.
  G "$wt" add -f "$2"; G "$wt" commit -qm "add $2"; G "$wt" push -q origin main
  G "$WORK/$1" fetch -q origin main
  # The fixture must have actually moved origin, or every assertion after it is
  # measuring an unchanged repo.
  [ "$(git -C "$WORK/$1" rev-parse HEAD)" != "$(git -C "$WORK/$1" rev-parse origin/main)" ] \
    || bad "harness: advance_origin($1,$2) did NOT move origin/main" "the case below tests nothing"
}
run() { bash "$SUT" "$WORK/$1" main origin > "$WORK/$1.out" 2>&1; echo $? > "$WORK/$1.rc"; }
rc()  { cat "$WORK/$1.rc"; }
out() { cat "$WORK/$1.out"; }

echo "== ASK-294 unattended fast-forward handler =="

# 1. already current -> quiet
new_pair c1; run c1
[ "$(rc c1)" = 0 ] && out c1 | grep -q '^current' && ok "already current: exit 0, no page" \
  || bad "already current" "rc=$(rc c1) out=$(out c1)"

# 2. behind + clean -> merges itself, and HEAD REALLY MOVES
new_pair c2; advance_origin c2 new.txt hello; BEFORE="$(git -C "$WORK/c2" rev-parse HEAD)"; run c2
AFTER="$(git -C "$WORK/c2" rev-parse HEAD)"
[ "$(rc c2)" = 0 ] && out c2 | grep -q '^merged' && ok "behind + clean: exit 0, reports merged" \
  || bad "behind + clean merges" "rc=$(rc c2) out=$(out c2)"
[ "$BEFORE" != "$AFTER" ] && [ "$AFTER" = "$(git -C "$WORK/c2" rev-parse origin/main)" ] \
  && ok "the working tree ACTUALLY advanced to origin/main" \
  || bad "tree advanced" "before=$BEFORE after=$AFTER"
[ -f "$WORK/c2/new.txt" ] && ok "the incoming file is present on disk afterwards" \
  || bad "incoming file present" "new.txt missing"

# 3. incoming path already exists UNTRACKED -> refuse
new_pair c3; advance_origin c3 new.txt fromorigin
printf 'local work\n' > "$WORK/c3/new.txt"; run c3
[ "$(rc c3)" = 1 ] && out c3 | grep -q 'collision' && ok "untracked collision: refuses" \
  || bad "untracked collision refuses" "rc=$(rc c3) out=$(out c3)"
grep -q 'local work' "$WORK/c3/new.txt" && ok "the untracked file is UNTOUCHED after the refusal" \
  || bad "untracked file preserved" "content=$(cat "$WORK/c3/new.txt")"

# 4. THE r1 SCAR: incoming path exists and is GITIGNORED -> must still refuse.
#    Bare `git merge --ff-only` overwrites this case silently with exit 0.
new_pair c4 'secret.env'; advance_origin c4 secret.env "FROM_ORIGIN"
printf 'MY_REAL_LOCAL_SECRET\n' > "$WORK/c4/secret.env"
# Prove the fixture is what it claims BEFORE asserting on it. If secret.env were
# merely untracked rather than ignored this case would duplicate case 3 and the
# r1 scar would go untested while the suite stayed green.
git -C "$WORK/c4" status --porcelain | grep -q 'secret\.env' \
  && bad "harness: secret.env is NOT actually ignored" "status shows it as untracked"
run c4
[ "$(rc c4)" = 1 ] && out c4 | grep -q 'collision' && ok "IGNORED collision: refuses (the r1 scar)" \
  || bad "ignored collision refuses" "rc=$(rc c4) out=$(out c4)"
grep -q 'MY_REAL_LOCAL_SECRET' "$WORK/c4/secret.env" 2>/dev/null \
  && ok "the ignored file is UNTOUCHED (bare --ff-only would have eaten it)" \
  || bad "ignored file preserved" "content=$(cat "$WORK/c4/secret.env" 2>/dev/null)"

# 5. incoming path is TRACKED but locally modified -> refuse
new_pair c5; advance_origin c5 base.txt changed-upstream
printf 'changed-locally\n' > "$WORK/c5/base.txt"; run c5
[ "$(rc c5)" = 1 ] && out c5 | grep -q 'collision' && ok "locally-modified tracked path: refuses" \
  || bad "locally-modified refuses" "rc=$(rc c5) out=$(out c5)"

# 6. diverged -> refuse, and say diverged (this is the founder-decision branch)
new_pair c6; advance_origin c6 up.txt upstream
printf 'mine\n' > "$WORK/c6/mine.txt"; G "$WORK/c6" add -A; G "$WORK/c6" commit -qm local; run c6
[ "$(rc c6)" = 1 ] && out c6 | grep -q '^diverged' && ok "diverged: refuses and names it diverged" \
  || bad "diverged refuses" "rc=$(rc c6) out=$(out c6)"

# 7. THE OVER-REFUSAL GUARD: ignored junk OUTSIDE the merge set must not block.
#    Without this case a "tree is clean" check would pass every other test here
#    and still never merge once in production.
new_pair c7; advance_origin c7 new.txt hello
mkdir -p "$WORK/c7/.prXXrev"; printf 'scratch\n' > "$WORK/c7/.prXXrev/junk"
printf 'untracked-elsewhere\n' > "$WORK/c7/unrelated.txt"; run c7
[ "$(rc c7)" = 0 ] && out c7 | grep -q '^merged' \
  && ok "untracked files OUTSIDE the merge set do NOT block the merge" \
  || bad "does not over-refuse" "rc=$(rc c7) out=$(out c7)"
[ -f "$WORK/c7/unrelated.txt" ] && ok "those untracked files survive the merge" \
  || bad "unrelated untracked survives" "gone"

# 8. not a repo -> fail OPEN (2), never refuse on ignorance
mkdir -p "$WORK/c8"; run c8
[ "$(rc c8)" = 2 ] && ok "not a git repo: exit 2 (no answer, fail open)" \
  || bad "no-answer exit 2" "rc=$(rc c8) out=$(out c8)"

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
