#!/bin/bash
# ASK-3506: pr-review-agent.sh removes the review trees of merged or closed PRs
# at the start of a run and never touches an open PR's tree, the PR under review,
# a tree with a live lock holder, or a tree whose PR state cannot be read.
# Scar: 2026-10-30, 22 merged-PR trees (12 GB) filled the disk to 313 MiB free.
# ASK-3930 (2026-11-07, disk 99%): 22 more finished trees (3.4 GB) were kept for good
# because review sessions write into their own trees: hook state files
# (.active-case, the sycophancy stamp, last-handoff.md) and reproducer scratch. A
# finished tree's unique files are now ARCHIVED, verified, and the tree removed.
# Nothing is discarded; the fail-closed skips (unreadable status, live cwd, live
# lock, an archive over the size cap or one that fails to verify) still keep it.
# Drives the REAL function, sliced out of pr-review-agent.sh, in a throwaway repo
# with a fake HOME and a stub gh. Nothing here names a real path or repo.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="$HERE/../pr-review-agent.sh"
LIB="$HERE/../repo-slug-lib.sh"
T="$(mktemp -d)"
fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

# The whole reap-merged-trees block, so every helper the reaper calls comes along.
awk '/^# reap-merged-trees-begin/{f=1;next} /^# reap-merged-trees-end/{exit} f' "$AGENT" > "$T/reap.sh"
awk '/^_wt_rows\(\)/{on=1} on{print} on&&/^}$/{exit}' "$AGENT" > "$T/rows.sh"
sed -n '/^acquire_wt_lock() {/,/^}/p' "$AGENT" > "$T/lock.sh"
check "slices hold the reaper, its helpers, _wt_rows and acquire_wt_lock" \
  'grep -q "^reap_finished_review_trees()" "$T/reap.sh" && grep -q "^_archive_review_tree()" "$T/reap.sh" && grep -q "^_reap_take_lock()" "$T/reap.sh" && grep -q "^_reap_release_lock()" "$T/reap.sh" && grep -q "^_wt_rows()" "$T/rows.sh" && grep -q "^acquire_wt_lock()" "$T/lock.sh"'
check "the slice does not call the reaper itself" '! grep -qx "reap_finished_review_trees" "$T/reap.sh"'

mkdir -p "$T/bin" "$T/home/.config/kipi/review-trees" "$T/repo"
git -C "$T/repo" init -q
printf base > "$T/repo/tracked.txt"; git -C "$T/repo" add tracked.txt
git -C "$T/repo" -c user.name=t -c user.email=t@example.invalid commit -q -m init
RT="$T/home/.config/kipi/review-trees"
# Keys come from the real path builder, so the fixture cannot drift from it.
source "$LIB"
SLUG="acme/widgets"
tree() { git -C "$T/repo" worktree add -q --detach "$(review_tree_path "$T/home/.config/kipi" "$SLUG" "$1")" HEAD; }
path_of() { review_tree_path "$T/home/.config/kipi" "$SLUG" "$1"; }
tree 11   # merged
tree 12   # closed
tree 13   # open: the negative control
tree 14   # the PR under review
tree 15   # merged but a live run holds its lock
tree 16   # state unreadable (gh fails)
tree 17   # merged but DIRTY: an untracked file (ASK-3508 negative control)
tree 18   # merged but a live process stands in it (ASK-3508 negative control)
tree 19   # merged and clean and idle: positive control for the new checks
tree 20   # merged, untracked file byte-identical to the main checkout copy (ASK-3621)
tree 22   # merged, a TRACKED file modified (ASK-3630 minor 1: pins the ?? guard)
tree 23   # merged, git status unreadable (ASK-3630 minor 2: pins the sentinel)
tree 21   # merged, untracked file DIFFERS from the main checkout copy (ASK-3621 negative control)
tree 24   # merged, unique untracked file OVER the archive size cap (ASK-3930 negative control)
tree 25   # merged, an untracked NESTED repo: cannot be archived file by file (ASK-3930 negative control)
tree 26   # merged, a STAGED version that differs from both HEAD and the worktree (ASK-3930 round 1)
git -C "$T/repo" worktree add -q --detach "$RT/other_repo__pr-11" HEAD   # another repo's key
git -C "$T/repo" worktree add -q --detach "$T/bystander" HEAD           # not a review tree
printf 'unsaved' > "$(path_of 17)/untracked.txt"
printf edited > "$(path_of 22)/tracked.txt"; printf edited > "$T/repo/tracked.txt"
printf garbage > "$(git -C "$(path_of 23)" rev-parse --absolute-git-dir)/index"
mkdir -p "$T/repo/out" "$(path_of 20)/out" "$(path_of 21)/out"
printf 'same' > "$T/repo/out/dup.md"; printf 'same' > "$(path_of 20)/out/dup.md"
printf 'other' > "$(path_of 21)/out/dup.md"
head -c 4096 /dev/zero | tr '\0' x > "$(path_of 24)/big.txt"
git init -q "$(path_of 25)/nested"; printf 'inner' > "$(path_of 25)/nested/inner.txt"
printf staged > "$(path_of 26)/tracked.txt"; git -C "$(path_of 26)" add tracked.txt; printf base > "$(path_of 26)/tracked.txt"
# A textconv driver on *.txt: a recovery patch must carry the bytes, not its rendering.
git -C "$T/repo" config diff.noisy.textconv "sed s/^/CONV/"
printf '*.txt diff=noisy\n' > "$T/repo/.git/info/attributes"
# Stale locks (dead holders) on a tree that goes and on one that stays.
( exit 0 ) & DEAD=$!; wait "$DEAD"
printf '%s' "$DEAD" > "$(path_of 17).lock"; printf '%s' "$DEAD" > "$(path_of 23).lock"
(cd "$(path_of 18)" && exec sleep 300) & CWDPROC=$!
sleep 300 & LIVE=$!
printf '%s' "$LIVE" > "$(path_of 15).lock"

cat > "$T/bin/gh" <<'EOF'
#!/bin/bash
n="$3"
case "$n" in
  11|15|17|18|19|20|21|22|23|24|25|26|99) echo MERGED ;; 12) echo CLOSED ;; 13|14) echo OPEN ;; *) exit 1 ;;
esac
EOF
chmod +x "$T/bin/gh"
for tool in bash env git cat awk cut grep rm kill printf tr sed dirname lsof cmp gzip mkdir mktemp date cp wc head sleep rmdir find touch python3; do ln -sf "$(command -v "$tool")" "$T/bin/$tool"; done
# tar is a WRAPPER, never a symlink (writing through a symlink would edit the real
# binary). While the archive of PR 17 is being written, a starting review tries to
# take that tree's lock. It calls the REAL acquire_wt_lock as its own process: round
# 2 kept a hand-copied protocol here, and a copy cannot catch a defect in the original.
REALTAR="$(command -v tar)"
cat > "$T/bin/tar" <<EOF
#!$(command -v bash)
case " \$* " in
  *" -czf "*"__pr-17-"*)
    # PR 17's lock was seeded with a DEAD holder, so a reaper that does not hold
    # it loses the tree here.
    "$T/bin/bash" -c '_wt_lock_path=""; source "\$1"; acquire_wt_lock "\$2"; echo "\$?"' _ "$T/lock.sh" "$(path_of 17)" > "$T/race.rc" 2>/dev/null
    case "\$(cat "$T/race.rc")" in 2) echo refused > "$T/race.out" ;; 0) echo took > "$T/race.out" ;; *) echo error > "$T/race.out" ;; esac ;;
esac
exec "$REALTAR" "\$@"
EOF
chmod +x "$T/bin/tar"

cat > "$T/drive.sh" <<EOF
set -uo pipefail   # what pr-review-agent.sh runs under (line 94)
REVIEW_REPO="$T/repo"; REVIEW_SLUG="$SLUG"; PR=14; KIPI_GH_REPO_ARGS=""; KIPI_REVIEW_ARCHIVE_MAX_KB=2
_wt_lock_path="the-review-own-lock"
source "$LIB"
source "$T/rows.sh"
source "$T/lock.sh"
source "$T/reap.sh"
reap_finished_review_trees
echo "review lock pointer after: \$_wt_lock_path"
EOF
mkdir -p "$T/tmp"
HOME="$T/home" TMPDIR="$T/tmp" PATH="$T/bin" "$T/bin/bash" "$T/drive.sh" > "$T/out" 2>"$T/err"
drive_rc=$?; echo "drive rc=$drive_rc"; cat "$T/out"
check "the reaper exits 0 under set -u and pipefail, with nothing on stderr" '[ "$drive_rc" = 0 ] && [ ! -s "$T/err" ]'

check "merged PR tree is removed (red before the fix: nothing removed it)" '[ ! -e "$(path_of 11)" ]'
check "closed PR tree is removed" '[ ! -e "$(path_of 12)" ]'
check "removed trees are unregistered from the repo" \
  '! git -C "$T/repo" worktree list | grep -q "__pr-11\$"'
check "NEGATIVE CONTROL: an open PR tree stays" '[ -d "$(path_of 13)" ]'
check "the PR under review keeps its tree" '[ -d "$(path_of 14)" ]'
check "a merged PR with a live lock holder keeps its tree" '[ -d "$(path_of 15)" ]'
check "an unreadable PR state keeps the tree" '[ -d "$(path_of 16)" ]'
check "another repo's key is never touched" '[ -d "$RT/other_repo__pr-11" ]'
check "a non-review worktree is never touched" '[ -d "$T/bystander" ]'
AR="$T/home/.config/kipi/review-tree-archive"
arch_of() { ls "$AR"/"$(basename "$(path_of "$1")")"-*.tar.gz 2>/dev/null | head -1; }
# No archive must read as a FAIL, never as tar waiting on stdin for an archive.
member() { local a; a="$(arch_of "$1")"; [ -n "$a" ] || return 1; tar -xzOf "$a" "$(basename "$(path_of "$1")")/$2" </dev/null 2>/dev/null; }
check "ASK-3930 a merged tree with a unique untracked file is removed (red before: the dirty skip kept it for good)" '[ ! -e "$(path_of 17)" ]'
check "ASK-3930 its unique file is in the archive, byte for byte" '[ "$(member 17 untracked/untracked.txt)" = unsaved ]'
check "ASK-3930 a merged tree whose untracked file differs from main is removed" '[ ! -e "$(path_of 21)" ]'
check "ASK-3930 the differing copy is archived, not the main checkout copy" '[ "$(member 21 untracked/out/dup.md)" = other ]'
check "ASK-3930 a merged tree with a modified TRACKED file is removed" '[ ! -e "$(path_of 22)" ]'
check "ASK-3930 the tracked edit is archived as a patch" 'member 22 unstaged.patch | grep -q "^+edited"'
check "ASK-3930 round 1: the patch is raw bytes, not the textconv rendering" '! member 22 unstaged.patch | grep -q CONV'
check "ASK-3930 round 1: a staged version unlike HEAD and the worktree is removed" '[ ! -e "$(path_of 26)" ]'
check "ASK-3930 round 1: that staged version is in staged.patch" 'member 26 staged.patch | grep -q "^+staged"'
check "ASK-3930 round 1: a competitor could NOT take the lock while the tree was archived" '[ "$(cat "$T/race.out" 2>/dev/null)" = refused ]'
check "ASK-3930 round 1: a removed tree's stale lock is gone" '[ ! -e "$(path_of 17).lock" ]'
check "ASK-3930 round 1: a kept tree's lock is given back, not left holding this run's PID" '[ ! -e "$(path_of 23).lock" ]'
check "ASK-3930 round 1: a live holder's lock is untouched" '[ "$(cat "$(path_of 15).lock")" = "$LIVE" ]'
check "ASK-3930 round 2: the review's own lock pointer is put back after the reaper" 'grep -qx "review lock pointer after: the-review-own-lock" "$T/out"'
check "ASK-3930 round 2: no claim mutex is left behind by the reaper" '[ -z "$(ls -d "$RT"/*.claim 2>/dev/null)" ]'
check "ASK-3930 the archive carries a manifest naming the PR" 'member 22 MANIFEST.txt | grep -q "^pr: 22$"'
check "ASK-3930 a duplicate-only tree gets no archive (nothing unique to keep)" '[ -z "$(arch_of 20)" ]'
check "ASK-3930 a clean tree gets no archive" '[ -z "$(arch_of 19)" ]'
check "ASK-3930 NEGATIVE CONTROL: unique files over the size cap keep the tree" '[ -f "$(path_of 24)/big.txt" ]'
check "ASK-3930 the size-cap skip is named" 'grep -q "skip: PR 24 tree holds .* unique, over the" "$T/out"'
check "ASK-3930 no archive is left for the tree it kept" '[ -z "$(arch_of 24)" ]'
check "ASK-3930 NEGATIVE CONTROL: a tree whose unique files cannot be archived stays" '[ -f "$(path_of 25)/nested/inner.txt" ]'
check "ASK-3930 the archive-failure skip is named" 'grep -q "skip: PR 25 tree kept, its unique files could not be archived" "$T/out"'
check "ASK-3930 a failed archive leaves no archive file" '[ -z "$(arch_of 25)" ]'
check "ASK-3508 a merged tree that is a live process cwd stays" '[ -d "$(path_of 18)" ]'
check "ASK-3508 the live-cwd skip is named" 'grep -q "skip: PR 18 tree is the cwd" "$T/out"'
check "ASK-3508 a clean idle merged tree is still removed" '[ ! -e "$(path_of 19)" ]'
check "ASK-3621 a merged tree whose only untracked file duplicates the main checkout is removed" '[ ! -e "$(path_of 20)" ]'
check "ASK-3630 NEGATIVE CONTROL: an unreadable status keeps the tree" '[ -d "$(path_of 23)" ]'
check "ASK-3630 the unreadable status is NAMED as a skip" 'grep -q "skip: PR 23 tree status is unreadable" "$T/out"'
check "ASK-3630 the cleanup line counts force-removed trees" 'grep -q "(5 of them force-removed" "$T/out"'
check "ASK-3930 the cleanup line counts archived trees" 'grep -q "4 archived to " "$T/out"'
check "one cleanup line is printed" '[ "$(grep -c "review-tree cleanup:" "$T/out")" = 1 ]'
check "the line counts 8 removed" 'grep -q "removed 8 finished" "$T/out"'
check "no staging directory is left in TMPDIR" '[ -z "$(ls -d "$T/tmp"/review-archive.* 2>/dev/null)" ]'

# ASK-3930 round 1: a list cut short (a full TMPDIR mid-append drops the last NUL)
# is refused against the caller's own count, never archived as if complete. The
# helper is driven directly with the same list twice: once whole, once truncated.
mkdir -p "$T/cut" "$T/home2" "$T/tmp2"
printf one > "$T/cut/a.txt"; printf two > "$T/cut/b.txt"
printf 'a.txt\0b.txt\0' > "$T/cut-whole.list"; printf 'a.txt\0b.txt' > "$T/cut-short.list"
cat > "$T/drive2.sh" <<EOF
set -uo pipefail
REVIEW_REPO="$T/repo"
source "$T/lock.sh"
source "$T/reap.sh"
_archive_review_tree "$T/cut" 30 "$T/cut-short.list" 0 2 >/dev/null; echo "short=\$?"
_archive_review_tree "$T/cut" 31 "$T/cut-whole.list" 0 2 >/dev/null; echo "whole=\$?"
EOF
HOME="$T/home2" TMPDIR="$T/tmp2" PATH="$T/bin" "$T/bin/bash" "$T/drive2.sh" > "$T/out2" 2>&1
AR2="$T/home2/.config/kipi/review-tree-archive"
check "ASK-3930 round 1: a truncated list is refused (rc 1)" 'grep -qx "short=1" "$T/out2"'
check "ASK-3930 round 1: POSITIVE CONTROL, the same list whole is archived (rc 0)" 'grep -qx "whole=0" "$T/out2"'
check "ASK-3930 round 1: exactly one archive exists, the whole one" '[ "$(ls "$AR2" 2>/dev/null | wc -l | tr -d " ")" = 1 ]'

# --- the claim mutex (ASK-3930 rounds 2 and 3) -------------------------------
# acquire_wt_lock serializes every claim on ONE kernel flock per review-trees
# directory (.tree-lock.mutex). These helpers hold it from outside, the way a
# contender inside its critical section would.
# It lets go only when told (or killed). Round 5 medium: a 20 second self-expiry let
# a paused contender walk into a mutex this test claimed to be holding. The 300
# second bound is a hang guard for a broken test, not a schedule: a check that
# depends on the holder still holding asserts `kill -0` on it instead.
hold_mutex() {  # <dir> <ready-file> <release-file>; exec, so $! is the holder itself
  exec python3 -I -c 'import fcntl, os, sys, time
fd = os.open(os.path.join(sys.argv[1], ".tree-lock.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
open(sys.argv[2], "w").close()
for _ in range(6000):
    if os.path.exists(sys.argv[3]):
        break
    time.sleep(0.05)' "$@"
}
mutex_free() {  # <dir>: 0 when nobody holds the mutex
  python3 -I -c 'import fcntl, os, sys
fd = os.open(os.path.join(sys.argv[1], ".tree-lock.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)' "$1" 2>/dev/null
}
wait_for() { local i=0; while [ ! -e "$1" ] && [ "$i" -lt "${2:-50}" ]; do i=$((i+1)); sleep 0.1; done; [ -e "$1" ]; }

# Round 2: contender A has read a dead holder and waits on the mutex, which this
# test holds as contender B. B reclaims the lock for a LIVE holder and lets go. A
# must re-read inside the mutex, see the live holder and back off.
mkdir -p "$T/race3"; L3="$T/race3/tree"
printf '%s' "$DEAD" > "$L3.lock"
hold_mutex "$T/race3" "$T/race3/held" "$T/race3/let-go" & H3=$!
wait_for "$T/race3/held"
cat > "$T/drive3.sh" <<EOF
set -uo pipefail
_wt_lock_path=""
source "$T/lock.sh"
acquire_wt_lock "$L3"; echo "rc=\$?" > "$T/race3/rc"
EOF
PATH="$T/bin" "$T/bin/bash" "$T/drive3.sh" & A=$!
sleep 0.5
if kill -0 "$A" 2>/dev/null; then echo blocked > "$T/race3/state"; else echo ran-through > "$T/race3/state"; fi
printf '%s' "$LIVE" > "$L3.lock"; : > "$T/race3/let-go"
wait "$H3"; wait "$A"
check "ASK-3930 round 2: contender A really waited on the claim mutex" '[ "$(cat "$T/race3/state")" = blocked ]'
check "ASK-3930 round 2: A backs off as busy (rc 2) once B holds the lock" 'grep -qx "rc=2" "$T/race3/rc"'
check "ASK-3930 round 2: B's live lock survives A's stale read" '[ "$(cat "$L3.lock")" = "$LIVE" ]'
check "ASK-3930 round 2: A gives the mutex back" 'mutex_free "$T/race3"'

# Round 3: a mutex whose holder was KILLED is free at once, because the kernel
# drops an flock when its holder dies. 344b340f instead cleared a mutex by AGE,
# which is the race below. A fresh mkdir mutex left by a pre-fix run is litter and
# must not wedge the tree (344b340f waited it out, then gave up with rc 1).
mkdir -p "$T/race4"; L4="$T/race4/tree"
printf '%s' "$DEAD" > "$L4.lock"; mkdir "$L4.lock.claim"
hold_mutex "$T/race4" "$T/race4/held" "$T/race4/never" & H4=$!
wait_for "$T/race4/held"; kill -9 "$H4" 2>/dev/null; wait "$H4" 2>/dev/null
cat > "$T/drive4.sh" <<EOF
set -uo pipefail
_wt_lock_path=""
source "$T/lock.sh"
acquire_wt_lock "$L4"; echo "rc=\$?"
EOF
PATH="$T/bin" "$T/bin/bash" "$T/drive4.sh" > "$T/race4/out" 2>&1
check "ASK-3930 round 3: a killed mutex holder frees the mutex, and the dead lock is reclaimed (rc 0)" 'grep -qx "rc=0" "$T/race4/out"'

# Round 3, Codex's interleave, forced. Start: a dead holder and an EXPIRED pre-fix
# .claim mutex. Two real contenders, A and B. PATH shims pin 344b340f's schedule:
# both pass the expiry check before either removes the mutex (find), A removes and
# recreates it and reads the dead holder, then B removes A's fresh mutex, recreates
# it and also reads the dead holder (cat), and B replaces the lock only after A has
# returned (rm). This test holds the kernel mutex while both start, so a protocol
# that uses it queues both at its door. Every wait is bounded: a protocol that never
# reaches a shim simply runs through. Both contenders stay alive to the end, so a
# winner can never be reclaimed as stale.
mkdir -p "$T/race5/bar" "$T/shim5"; L5="$T/race5/tree"; BAR="$T/race5/bar"
printf '%s' "$DEAD" > "$L5.lock"; mkdir "$L5.lock.claim"; touch -t 202601010000 "$L5.lock.claim"
SH="$(command -v bash)"; RFIND="$(command -v find)"; RCAT="$(command -v cat)"; RRM="$(command -v rm)"; RSLEEP="$(command -v sleep)"
cat > "$T/shim5/find" <<EOF
#!$SH
out="\$("$RFIND" "\$@")"; rc=\$?
if [ -n "\${ROLE:-}" ] && [ -n "\$out" ]; then
  : > "$BAR/found.\$ROLE"; i=0
  while { [ ! -e "$BAR/found.A" ] || [ ! -e "$BAR/found.B" ]; } && [ "\$i" -lt 100 ]; do i=\$((i+1)); "$RSLEEP" 0.1; done
  if [ "\$ROLE" = B ]; then i=0; while [ ! -e "$BAR/A.cat2" ] && [ "\$i" -lt 100 ]; do i=\$((i+1)); "$RSLEEP" 0.1; done; fi
fi
[ -z "\$out" ] || printf '%s\n' "\$out"
exit "\$rc"
EOF
cat > "$T/shim5/cat" <<EOF
#!$SH
if [ -n "\${ROLE:-}" ] && [ "\$#" = 1 ] && [ "\$1" = "$L5.lock" ]; then
  n=\$(( \$("$RCAT" "$BAR/cat.\$ROLE" 2>/dev/null || echo 0) + 1 )); printf '%s' "\$n" > "$BAR/cat.\$ROLE"
  out="\$("$RCAT" "\$1")"; rc=\$?
  if [ "\$n" = 2 ]; then
    : > "$BAR/\$ROLE.cat2"
    if [ "\$ROLE" = A ]; then i=0; while [ ! -e "$BAR/B.cat2" ] && [ "\$i" -lt 100 ]; do i=\$((i+1)); "$RSLEEP" 0.1; done; fi
  fi
  printf '%s' "\$out"; exit "\$rc"
fi
exec "$RCAT" "\$@"
EOF
cat > "$T/shim5/rm" <<EOF
#!$SH
if [ "\${ROLE:-}" = B ]; then i=0; while [ ! -e "$BAR/done.A" ] && [ "\$i" -lt 100 ]; do i=\$((i+1)); "$RSLEEP" 0.1; done; fi
exec "$RRM" "\$@"
EOF
chmod +x "$T/shim5/find" "$T/shim5/cat" "$T/shim5/rm"
cat > "$T/drive5.sh" <<EOF
set -uo pipefail
_wt_lock_path=""
source "$T/lock.sh"
acquire_wt_lock "$L5"; rc=\$?
echo "\$\$ \$rc" > "$T/race5/out.\$ROLE"; : > "$BAR/done.\$ROLE"
i=0; while [ ! -e "$BAR/release" ] && [ "\$i" -lt 300 ]; do i=\$((i+1)); sleep 0.1; done
EOF
hold_mutex "$T/race5" "$BAR/held" "$BAR/let-go" & H5=$!
wait_for "$BAR/held"
ROLE=A PATH="$T/shim5:$T/bin" "$T/bin/bash" "$T/drive5.sh" & CA=$!
ROLE=B PATH="$T/shim5:$T/bin" "$T/bin/bash" "$T/drive5.sh" & CB=$!
sleep 1.5; : > "$BAR/let-go"; wait "$H5"
wait_for "$T/race5/out.A" 150; wait_for "$T/race5/out.B" 150
owners="$(cat "$T/race5/out.A" "$T/race5/out.B" 2>/dev/null | awk '$2 == 0' | wc -l | tr -d ' ')"
busy="$(cat "$T/race5/out.A" "$T/race5/out.B" 2>/dev/null | awk '$2 == 2' | wc -l | tr -d ' ')"
winner="$(cat "$T/race5/out.A" "$T/race5/out.B" 2>/dev/null | awk '$2 == 0 {print $1}' | head -1)"
echo "round 3 contenders (pid rc): A $(cat "$T/race5/out.A" 2>/dev/null), B $(cat "$T/race5/out.B" 2>/dev/null); the lock holds $(cat "$L5.lock" 2>/dev/null)"
check "ASK-3930 round 3: after both pass the expiry check, exactly ONE contender owns the tree (red on 344b340f: both did)" '[ "$owners" = 1 ]'
check "ASK-3930 round 3: the other backs off as busy (rc 2), so it never clears the owner's ref" '[ "$busy" = 1 ]'
check "ASK-3930 round 3: the lock names the one owner" '[ -n "$winner" ] && [ "$(cat "$L5.lock")" = "$winner" ]'
: > "$BAR/release"; wait "$CA" "$CB" 2>/dev/null

# Round 4: a contender that times out on the mutex never returns rc 1, which sends
# review_worktree to _wt_bail and deletes refs/remotes/pr/<N>. Codex's schedule: A
# owns the tree (LIVE), B (this test) holds the directory-wide mutex, C claims A's
# tree. Round 6 makes the timeout UNKNOWN (rc 3): the mutex covers the directory, so
# B being inside it says nothing about who owns A's tree.
# The proof the timeout path ran is by effect, not elapsed time (round 5 medium).
# Had C got inside the mutex it would have read A's live PID and returned busy (2),
# so rc 3 here means it never did, and B is asserted still alive, so still holding,
# at the moment C returned.
mkdir -p "$T/race6"; L6="$T/race6/tree"
printf '%s' "$LIVE" > "$L6.lock"
hold_mutex "$T/race6" "$T/race6/held" "$T/race6/let-go" & H6=$!
wait_for "$T/race6/held"
cat > "$T/drive6.sh" <<EOF
set -uo pipefail
_wt_lock_path=""
source "$T/lock.sh"
acquire_wt_lock "$L6"; echo "rc=\$?"
EOF
PATH="$T/bin" "$T/bin/bash" "$T/drive6.sh" > "$T/race6/out" 2>&1
if kill -0 "$H6" 2>/dev/null; then echo held > "$T/race6/holder"; else echo gone > "$T/race6/holder"; fi
: > "$T/race6/let-go"; wait "$H6"
check "ASK-3930 round 4: a mutex timeout is unknown (rc 3), never 1, so the owner's ref is never cleared" 'grep -qx "rc=3" "$T/race6/out"'
check "ASK-3930 round 4: the mutex holder still held when the contender returned" '[ "$(cat "$T/race6/holder")" = held ]'
check "ASK-3930 round 4: the live owner's lock is untouched" '[ "$(cat "$L6.lock")" = "$LIVE" ]'

# --- Round 6: rc 1 only on proof (ASK-3930, Codex rounds 4 and 5) -------------
# review_worktree clears refs/remotes/pr/<N> only when acquire_wt_lock says nobody
# owns the tree. Each case breaks ONE step of a claim and drives the REAL
# review_worktree, then reads the effect: the rc acquire_wt_lock gave it, whether
# the ref survived, whether the lock still names its holder, and whether the mutex
# was given back to this same shell (it holds the mutex on fd 8 now). A fault shim
# stands in for python3: the real interpreter runs the same script with one OS call
# broken, and logs that the fault fired, so a case proves its path was taken.
RW="$T/rw"; mkdir -p "$RW/repo" "$RW/shim" "$RW/nopy" "$RW/gitshim" "$RW/home"
REALPY="$(command -v python3)"; REALGIT="$(command -v git)"; RBASH="$(command -v bash)"
git -C "$RW/repo" init -q
printf one > "$RW/repo/f.txt"; git -C "$RW/repo" add f.txt
git -C "$RW/repo" -c user.name=t -c user.email=t@example.invalid commit -q -m one
RW1="$(git -C "$RW/repo" rev-parse HEAD)"
printf two > "$RW/repo/f.txt"
git -C "$RW/repo" -c user.name=t -c user.email=t@example.invalid commit -q -am two
RW2="$(git -C "$RW/repo" rev-parse HEAD)"
{ sed -n '/^_wt_bail() {/,/^}/p' "$AGENT"
  sed -n '/^acquire_wt_lock() {/,/^}/p' "$AGENT" | sed '1s/^acquire_wt_lock()/_acquire_under_test()/'
  sed -n '/^release_wt_lock() {/,/^}/p' "$AGENT"
  sed -n '/^review_worktree() {/,/^  printf/p' "$AGENT"; echo '}'; } > "$RW/fns.sh"
check "ASK-3930 round 6: the slice holds review_worktree, _wt_bail and the lock under test" \
  'grep -q "^_wt_bail()" "$RW/fns.sh" && grep -q "^_acquire_under_test()" "$RW/fns.sh" && grep -q "^review_worktree()" "$RW/fns.sh" && grep -q "clear-stale-ref" "$RW/fns.sh"'
for f in "$T/bin"/*; do [ "${f##*/}" = python3 ] || ln -s "$f" "$RW/nopy/${f##*/}"; done
cat > "$RW/shim/python3" <<EOF
#!$RBASH
# python3 with ONE OS call broken (\$FAULT). Each patch logs to \$FAULT_LOG when it fires.
if [ "\${FAULT:-}" = noop ]; then echo noop >> "\$FAULT_LOG"; exit 0; fi
shift 2   # drop -I and -: the script arrives on stdin, its argv follows
exec "$REALPY" -I -c '
import builtins, errno, fcntl, os, signal, sys
fault, log, lock = os.environ.get("FAULT", ""), os.environ["FAULT_LOG"], sys.argv[1]
r_flock, r_kill, r_open, r_link, r_unlink = fcntl.flock, os.kill, builtins.open, os.link, os.unlink
def fired():
    with r_open(log, "a") as fh:
        fh.write(fault + "\n")
def flock(*a):
    if fault == "flock":
        fired(); raise OSError(errno.ENOLCK, "no locks available")
    r_flock(*a)
    if fault == "sigkill":
        fired(); r_kill(os.getpid(), signal.SIGKILL)
def kill(pid, sig):
    if fault == "kill" and pid != os.getpid():
        fired(); raise OSError(errno.EIO, "liveness unknown")
    return r_kill(pid, sig)
def opener(path, *a, **k):
    if fault == "read" and path == lock:
        fired(); raise PermissionError(errno.EACCES, "denied", path)
    return r_open(path, *a, **k)
def link(src, dst, *a, **k):
    if fault == "link":
        fired(); raise PermissionError(errno.EACCES, "denied", dst)
    return r_link(src, dst, *a, **k)
def unlink(path, *a, **k):
    if fault == "tmpunlink" and str(path).endswith(".tmp"):
        fired(); raise PermissionError(errno.EACCES, "denied", path)
    return r_unlink(path, *a, **k)
fcntl.flock, os.kill, builtins.open, os.link, os.unlink = flock, kill, opener, link, unlink
src = sys.stdin.read()
sys.argv = ["-"] + sys.argv[1:]
exec(compile(src, "<acquire_wt_lock>", "exec"), {"__name__": "__main__"})
' "\$@"
EOF
# git shim: at every ref delete, record whether the claim mutex is held right then.
cat > "$RW/gitshim/git" <<EOF
#!$RBASH
case " \$* " in
  *" update-ref -d "*)
    if "$REALPY" -I -c 'import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)' "\$CLEAR_MUTEX" 2>/dev/null; then echo free; else echo held; fi >> "\$CLEAR_LOG" ;;
esac
exec "$REALGIT" "\$@"
EOF
# mkdir that fails while the tree exists and is owned: Codex round 6's EACCES on a
# parent. Round 6 first read a failed mkdir as "no directory, so no owner".
mkdir -p "$RW/mkdirfail"
cat > "$RW/mkdirfail/mkdir" <<EOF
#!$RBASH
echo mkdir >> "\$FAULT_LOG"; echo "mkdir: Permission denied" >&2; exit 1
EOF
chmod +x "$RW/shim/python3" "$RW/gitshim/git" "$RW/mkdirfail/mkdir"
cat > "$RW/drive.sh" <<EOF
set -uo pipefail
HOME="$RW/home"; REVIEW_REPO="$RW/repo"; REVIEW_SLUG=acme/widgets; PR=77
_wt_lock_path=""
source "$RW/fns.sh"
review_tree_path() { echo "\$CASE/trees/acme_widgets__pr-77"; }
acquire_wt_lock() { _acquire_under_test "\$@"; local rc=\$?; echo "\$rc" > "\$CASE/rc"; return "\$rc"; }
echo "\$\$" > "\$CASE/me"
review_worktree "$RW2" > "\$CASE/path" 2> "\$CASE/warn"
if "$REALPY" -I -c 'import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)' "\$CASE/trees/.tree-lock.mutex" 2>/dev/null; then echo free; else echo held; fi > "\$CASE/mutex-after"
EOF
rw_case() {  # <name> <holder pid> <fault> [nopy|mutexdir]
  local c="$RW/case-$1" p="$RW/gitshim:$RW/shim:$T/bin"
  mkdir -p "$c/trees"; printf '%s' "$2" > "$c/trees/acme_widgets__pr-77.lock"; : > "$c/fault.log"; : > "$c/clear.log"
  [ "${4:-}" = nopy ] && p="$RW/gitshim:$RW/nopy"
  [ "${4:-}" = mkdirfail ] && p="$RW/gitshim:$RW/mkdirfail:$RW/shim:$T/bin"
  [ "${4:-}" = mutexdir ] && mkdir "$c/trees/.tree-lock.mutex"
  git -C "$RW/repo" update-ref refs/remotes/pr/77 "$RW1"
  CASE="$c" FAULT="$3" FAULT_LOG="$c/fault.log" CLEAR_LOG="$c/clear.log" CLEAR_MUTEX="$c/trees/.tree-lock.mutex" \
    PATH="$p" "$T/bin/bash" "$RW/drive.sh" > "$c/out" 2>&1
  echo "round 6 $1: rc=$(cat "$c/rc" 2>/dev/null) ref=$(git -C "$RW/repo" rev-parse --verify --quiet refs/remotes/pr/77 | cut -c1-8) lock=$(cat "$c/trees/acme_widgets__pr-77.lock" 2>/dev/null) fault=$(tr '\n' ' ' < "$c/fault.log") clears=$(tr '\n' ' ' < "$c/clear.log") mutex-after=$(cat "$c/mutex-after" 2>/dev/null)"
  git -C "$RW/repo" rev-parse --verify --quiet refs/remotes/pr/77 > "$c/ref-after"
}
rw() { cat "$RW/case-$1/$2" 2>/dev/null; }
# Ownership unknown, with a LIVE owner of the tree: the ref and the lock must survive.
for spec in "nopy::nopy" "mutexdir::mutexdir" "mkdirfail::mkdirfail" "flock:flock:" "sigkill:sigkill:" "read:read:" "kill:kill:" "noop:noop:"; do
  name="${spec%%:*}"; rest="${spec#*:}"; fault="${rest%%:*}"; mode="${rest#*:}"
  rw_case "$name" "$LIVE" "$fault" "$mode"
  check "ASK-3930 round 6: $name: ownership unknown is rc 3, never 1" '[ "$(rw "$name" rc)" = 3 ]'
  check "ASK-3930 round 6: $name: the live owner's ref survives" '[ "$(rw "$name" ref-after)" = "$RW1" ]'
  check "ASK-3930 round 6: $name: the live owner's lock is untouched" '[ "$(rw "$name" trees/acme_widgets__pr-77.lock)" = "$LIVE" ]'
  [ -n "$fault" ] && check "ASK-3930 round 6: $name: the fault fired, so this path was taken" 'grep -qx "$fault" "$RW/case-$name/fault.log"'
  [ "$mode" = mutexdir ] || check "ASK-3930 round 6: $name: the mutex is given back" '[ "$(rw "$name" mutex-after)" = free ]'
done
check "ASK-3930 round 6: nopy: python3 really was absent from that PATH" '[ ! -e "$RW/nopy/python3" ] && [ -e "$RW/nopy/git" ]'
check "ASK-3930 round 6: mutexdir: the mutex path really is a directory" '[ -d "$RW/case-mutexdir/trees/.tree-lock.mutex" ]'
check "ASK-3930 round 6: mkdirfail: the failing mkdir ran, with the owned tree's directory present" 'grep -qx mkdir "$RW/case-mkdirfail/fault.log" && [ -d "$RW/case-mkdirfail/trees" ]'
check "ASK-3930 round 6: mkdirfail: no ref delete was even attempted" '[ ! -s "$RW/case-mkdirfail/clear.log" ]'
# Proven unowned (a DEAD holder, read inside the mutex), and the claim cannot be
# written: rc 1, the ref is cleared, and it is cleared while the mutex is held.
rw_case claimfail "$DEAD" link
check "ASK-3930 round 6: claimfail: a dead holder plus a failed claim is rc 1" '[ "$(rw claimfail rc)" = 1 ]'
check "ASK-3930 round 6: claimfail: the stale ref is cleared" '[ -z "$(rw claimfail ref-after)" ]'
check "ASK-3930 round 6: claimfail: the clear ran while the claim mutex was held" 'grep -qx held "$RW/case-claimfail/clear.log" && ! grep -qx free "$RW/case-claimfail/clear.log"'
check "ASK-3930 round 6: claimfail: the fault fired, so this path was taken" 'grep -qx link "$RW/case-claimfail/fault.log"'
check "ASK-3930 round 6: claimfail: the mutex is given back" '[ "$(rw claimfail mutex-after)" = free ]'
# The claim was linked but the tmp name could not be tidied: the lock is this run's.
rw_case tmpunlink "$DEAD" tmpunlink
check "ASK-3930 round 6: tmpunlink: a claim that linked is held (rc 0) though its tmp file stayed" '[ "$(rw tmpunlink rc)" = 0 ]'
check "ASK-3930 round 6: tmpunlink: the lock names this run" '[ "$(rw tmpunlink trees/acme_widgets__pr-77.lock)" = "$(rw tmpunlink me)" ]'
check "ASK-3930 round 6: tmpunlink: the fault fired, so this path was taken" 'grep -qx tmpunlink "$RW/case-tmpunlink/fault.log"'
check "ASK-3930 round 6: tmpunlink: the mutex is given back" '[ "$(rw tmpunlink mutex-after)" = free ]'
# POSITIVE CONTROL: the same shim with no fault claims a dead holder's tree.
rw_case control "$DEAD" none
check "ASK-3930 round 6: control: no fault claims the tree (rc 0)" '[ "$(rw control rc)" = 0 ]'
check "ASK-3930 round 6: control: the ref moves to the reviewed sha" '[ "$(rw control ref-after)" = "$RW2" ]'
check "ASK-3930 round 6: control: the lock names this run" '[ "$(rw control trees/acme_widgets__pr-77.lock)" = "$(rw control me)" ]'
check "ASK-3930 round 6: control: no fault fired and no ref was deleted" '[ ! -s "$RW/case-control/fault.log" ] && [ ! -s "$RW/case-control/clear.log" ]'
check "ASK-3930 round 6: control: the mutex is given back" '[ "$(rw control mutex-after)" = free ]'

kill "$LIVE" "$CWDPROC" 2>/dev/null
exit "$fail"
