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
check "slices hold the reaper, its helpers and _wt_rows" \
  'grep -q "^reap_finished_review_trees()" "$T/reap.sh" && grep -q "^_archive_review_tree()" "$T/reap.sh" && grep -q "^_reap_take_lock()" "$T/reap.sh" && grep -q "^_reap_release_lock()" "$T/reap.sh" && grep -q "^_wt_rows()" "$T/rows.sh"'
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
for tool in bash env git cat awk cut grep rm kill printf tr sed dirname lsof cmp gzip mkdir mktemp date cp wc head; do ln -sf "$(command -v "$tool")" "$T/bin/$tool"; done
# tar is a WRAPPER, never a symlink (writing through a symlink would edit the real
# binary). While the archive of PR 17 is being written, a competitor tries to take
# that tree's lock with the same noclobber protocol a starting review uses.
REALTAR="$(command -v tar)"
cat > "$T/bin/tar" <<EOF
#!$(command -v bash)
case " \$* " in
  *" -czf "*"__pr-17-"*)
    # acquire_wt_lock's whole protocol, stale reclaim included: PR 17's lock was
    # seeded with a DEAD holder, so a reaper that does not hold it loses it here.
    L="$(path_of 17).lock"
    if ( set -o noclobber; printf competitor > "\$L" ) 2>/dev/null; then echo took > "$T/race.out"
    else
      h="\$(cat "\$L" 2>/dev/null)"
      if [ -n "\$h" ] && kill -0 "\$h" 2>/dev/null; then echo refused > "$T/race.out"
      else rm -f "\$L"; ( set -o noclobber; printf competitor > "\$L" ) 2>/dev/null && echo took > "$T/race.out"; fi
    fi ;;
esac
exec "$REALTAR" "\$@"
EOF
chmod +x "$T/bin/tar"

cat > "$T/drive.sh" <<EOF
set -uo pipefail   # what pr-review-agent.sh runs under (line 94)
REVIEW_REPO="$T/repo"; REVIEW_SLUG="$SLUG"; PR=14; KIPI_GH_REPO_ARGS=""; KIPI_REVIEW_ARCHIVE_MAX_KB=2
source "$LIB"
source "$T/rows.sh"
source "$T/reap.sh"
reap_finished_review_trees
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
source "$T/reap.sh"
_archive_review_tree "$T/cut" 30 "$T/cut-short.list" 0 2 >/dev/null; echo "short=\$?"
_archive_review_tree "$T/cut" 31 "$T/cut-whole.list" 0 2 >/dev/null; echo "whole=\$?"
EOF
HOME="$T/home2" TMPDIR="$T/tmp2" PATH="$T/bin" "$T/bin/bash" "$T/drive2.sh" > "$T/out2" 2>&1
AR2="$T/home2/.config/kipi/review-tree-archive"
check "ASK-3930 round 1: a truncated list is refused (rc 1)" 'grep -qx "short=1" "$T/out2"'
check "ASK-3930 round 1: POSITIVE CONTROL, the same list whole is archived (rc 0)" 'grep -qx "whole=0" "$T/out2"'
check "ASK-3930 round 1: exactly one archive exists, the whole one" '[ "$(ls "$AR2" 2>/dev/null | wc -l | tr -d " ")" = 1 ]'

kill "$LIVE" "$CWDPROC" 2>/dev/null
exit "$fail"
