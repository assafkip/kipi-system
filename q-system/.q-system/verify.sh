#!/usr/bin/env bash
# THE floor. One script, run identically at every gate, so the agent, the commit
# and the merge cannot quietly drift apart.
#
# why this exists: this repo had SEVEN different pre-commit commands, a
# hand-written native pre-push (lefthook kept silently skipping its own), and no
# CI at all. Every one of those checks was real; nothing guaranteed the same set
# ran at each door. "It passed" did not say which door it passed.
#
#   verify.sh --staged    what a commit would contain, checked against a COPY
#   verify.sh --full      the working tree, everything
#   verify.sh --changed [--base REF] [--rev SHA]
#                         a COPY of one commit (default HEAD), pytest scoped to
#                         what changed since its merge-base with origin's default
#                         branch. The pre-push door (2026-09-30).
#
# --staged never touches your working tree. It turns the git INDEX into a real
# commit object and checks that out as a throwaway worktree, then runs there.
# The obvious alternative, `git stash --keep-index`, puts uncommitted work
# inside a stash that a crash mid-hook can strand. Verifying against a copy
# costs a couple of seconds and cannot eat anybody's work.
#
# THE ONE RULE THAT IS NOT NEGOTIABLE: if this script discovers no checks to
# run, it FAILS. A gate that cannot run must not pass. The alternative is a
# green exit that means "I looked for a linter and did not find one", which is
# indistinguishable from "your code is fine" at every call site that reads only
# the exit code.
set -euo pipefail

MODE="${1:---full}"
CHANGED_BASE=""
CHANGED_REV="HEAD"
if [ "$MODE" = "--changed" ]; then
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --base) CHANGED_BASE="${2:?--base needs a ref}"; shift 2 ;;
      --rev)  CHANGED_REV="${2:?--rev needs a commit}"; shift 2 ;;
      *) echo "usage: verify.sh --changed [--base REF] [--rev SHA]" >&2; exit 2 ;;
    esac
  done
fi
REPO="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Where pytest's ordering cache lives. Git's COMMON dir, never the working tree:
# see the long note at the `-o cache_dir` call below. --path-format=absolute so a
# `cd` inside the pytest subshell cannot re-root a relative `.git`; the fallback
# keeps this working on a git too old for that flag.
VERIFY_CACHE_ROOT="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
[ -n "$VERIFY_CACHE_ROOT" ] || VERIFY_CACHE_ROOT="$REPO/.git"
VERIFY_CACHE_ROOT="$VERIFY_CACHE_ROOT/kipi-verify-cache"
RAN=()
FAILED=()
TMP=""

# `return 0` is LOAD-BEARING, not tidiness. An EXIT trap's last command sets the
# script's exit status. The first version was a bare `[ -n "$TMP" ] && [ -d ...
# ] && rm -rf "$TMP"`, and in --full mode TMP is empty, so the chain returned 1
# and EVERY SUCCESSFUL --full RUN EXITED 1. It printed "verify.sh ok" and then
# failed. Wired at pre-push and CI, that is a floor that blocks every push
# forever, which is the same amount of protection as a floor that blocks
# nothing: both get switched off within a day.
#
# Caught 2026-08-27 by the adversarial suite asserting the exit code of a CLEAN
# repo. No test of the failure cases could have found it: they all expect 1.
cleanup() {
  if [ -n "$TMP" ] && [ -d "$TMP" ]; then rm -rf "$TMP"; fi
  # The staged worktree lived under $TMP, so removing $TMP orphans its
  # registration in .git/worktrees. prune is the sanctioned cleanup, is a no-op
  # when nothing is stale, and never touches a worktree whose directory still
  # exists. Without it every --staged run leaks an entry and `git worktree list`
  # fills with dead paths until an add starts failing.
  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY \
      -u GIT_COMMON_DIR git worktree prune >/dev/null 2>&1 || true
  return 0
}
trap cleanup EXIT

# A COLLISION IS NOT A FAILED CHECK, and the two must never share an exit status
# (ASK-1900). Building the staged snapshot touches metadata every worktree of the
# repo shares -- the index and .git/worktrees -- so a concurrent session, the
# dispatcher, or a sibling lefthook command in the same `parallel: true` stage can
# lose this script a lock. Nothing about the staged code is wrong when that
# happens, and a caller that reads "your change will not pass later" from it goes
# off editing code that was fine.
#
# 75 is EX_TEMPFAIL: retry is the correct response, not a source edit. It is still
# non-zero, so the commit is still refused -- a gate that cannot run must not pass,
# which is this script's one non-negotiable rule and it is not weakened here.
EXIT_COLLISION=75
snapshot_collision() {
  echo "verify.sh: COLLISION, not a failed check. Could not $1." >&2
  echo "  Another git process holds shared repository state. NOTHING WAS CHECKED:" >&2
  echo "  no verdict on your staged content was reached, in either direction." >&2
  echo "  Retry the commit. If it repeats with nothing else running, then it is real." >&2
  if [ -n "${2:-}" ]; then printf '%s\n' "$2" | sed 's/^/  git: /' >&2; fi
  exit "$EXIT_COLLISION"
}

# Does this git error name a lock or a name clash on shared state? Used to
# classify, never to decide whether to refuse -- a refusal happens either way.
is_collision_error() {
  printf '%s' "$1" | grep -qiE \
    'index\.lock|\.lock.: File exists|already (exists|registered|checked out)|Another git process|unable to create.*lock'
}

case "$MODE" in
  --staged|--full|--changed) ;;
  *) echo "usage: verify.sh [--staged|--full|--changed [--base REF] [--rev SHA]]" >&2; exit 2 ;;
esac

# Check SNAP out as a throwaway worktree at $TMP/wt and point TARGET at it.
# Shared by --staged (a commit built from the index) and --changed (an existing
# commit), so both doors grade a COPY by the same machinery, collisions included.
materialise_snapshot() {
  local SNAP="$1" _what="$2"
  WT_OK=""
  for _try in 1 2 3; do
    if WT_ERR="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE \
                     -u GIT_OBJECT_DIRECTORY -u GIT_COMMON_DIR \
                     git -C "$REPO" worktree add --detach "$TMP/wt" "$SNAP" 2>&1)"; then
      WT_OK=1
      break
    fi
    is_collision_error "$WT_ERR" || break
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY \
        -u GIT_COMMON_DIR git -C "$REPO" worktree prune >/dev/null 2>&1 || true
    sleep 0.2
  done
  if [ -z "$WT_OK" ]; then
    if is_collision_error "$WT_ERR"; then
      snapshot_collision "create the $_what worktree after 3 tries" "$WT_ERR"
    fi
    # Print what git said. The first version threw stderr away and the refusal
    # was untraceable: a gate that cannot say why it refused gets bypassed.
    echo "verify.sh: could not create the $_what worktree. Refusing." >&2
    echo "$WT_ERR" | sed 's/^/  /' >&2
    exit 1
  fi
  TARGET="$TMP/wt"
}

SCOPED=""
STAGED=""
if [ "$MODE" = "--staged" ]; then
  # TWO DIFFERENT QUESTIONS, and conflating them opened a hole.
  #
  # STAGED is "which files should I scope checks to", so it excludes deletions:
  # you cannot syntax-check a file that will not exist. ANY_STAGED is "is this
  # commit empty", and deletions absolutely count.
  #
  # the finding (codex, PR #259 round 4): one variable answered both. A commit
  # that ONLY deletes files produced an empty ACMR list, hit the early exit, and
  # sailed through at exit 0 with no checks run at all. Deleting the last caller
  # of a module, or deleting a test file, is exactly the change a floor should
  # look at -- the remaining tree still has to parse and its suites still have to
  # pass without it.
  # --no-renames, because ANY_STAGED also feeds the test selector (ASK-1795).
  # Rename detection is on by default and prints ONLY the new path, so a
  # `git mv helper.py helper2.py` hid the old module name, and the tests that
  # still import `helper` were not selected. Reviewer finding on PR #371, with a
  # reproducer: with renames on, the selection was the declared fallback alone;
  # with `-c diff.renames=false`, both names appear and test_helper.py is picked.
  ANY_STAGED="$(git -C "$REPO" diff -z --cached --no-renames --name-only | tr '\0' '\n')"
  STAGED="$(git -C "$REPO" diff -z --cached --name-only --diff-filter=ACMR | tr '\0' '\n')"
  if [ -z "$ANY_STAGED" ]; then
    echo "verify.sh --staged: nothing staged, nothing to verify."
    exit 0
  fi
  SCOPED=1
  # The staged snapshot, materialised AS A REAL REPOSITORY. Not the working
  # tree, and not a stash.
  #
  # why a worktree and not `git checkout-index --prefix=` (the first version):
  # checkout-index writes FILES and nothing else, so the snapshot had no .git.
  # Every test that asks the repository a question then got a wrong answer
  # instead of an error. Measured 2026-08-27 on this repo: 25 failed under
  # --staged against 7 under --full, and the 18-test difference was entirely
  # this. `provenance.resolve` on HEAD returned "empty commit ref"; the
  # gitignore checks, the behind-upstream check and the live-tree enumerations
  # all followed. A pre-commit gate that fails 18 times for a reason unrelated
  # to your change is a gate that gets deleted in a day, which is the same
  # protection as no gate at all.
  #
  # write-tree + commit-tree turns the INDEX into a real commit object without
  # touching any ref, any branch, or the working tree. The worktree checked out
  # at that commit is a genuine git repository holding exactly what the commit
  # would contain, so a repo-aware test is answered about the STAGED state
  # rather than about a directory that is not a repo.
  TMP="$(mktemp -d)"
  # THE INDEX IS READ FROM A COPY TOO (ASK-1900), and that is a collision fix,
  # not tidiness. `git write-tree` does not merely read the index: it writes the
  # updated cache-tree extension back, so it takes `index.lock` -- and it takes it
  # with LOCK_DIE_ON_ERROR, which means it does not degrade, it dies. Every other
  # index-touching call here returns 0 while the lock is held; measured on a repo
  # with a held lock: diff --cached 0, diff --cached ACMR 0, ls-files 0,
  # rev-parse HEAD 0, write-tree 128.
  #
  # So one sibling holding the lock for a few milliseconds killed this script at
  # the second command, under `set -e`, before it echoed a single line. lefthook
  # then printed its own fail_text, which said the change "will not pass later".
  # That is false: nothing was ever checked. Observed four times in one evening
  # across two worktrees of this repo, each refusal back in 0.10-0.17s against a
  # ~2.8s real run, each identical retry green. lefthook's pre-commit stage is
  # `parallel: true` and several siblings shell out to git, so the contender is
  # usually this same commit's own hook stage.
  #
  # A copy cannot be contended. Measured: write-tree against a copied index
  # returns the IDENTICAL tree sha while the real index.lock is held.
  # Which index -- git EXPORTS GIT_INDEX_FILE to its hooks, and for a pathspec
  # commit (`git commit -- foo`) that is a temporary index, not .git/index. Read
  # the exported one or the commit being graded is the wrong one.
  _index_src="${GIT_INDEX_FILE:-}"
  if [ -z "$_index_src" ]; then
    _index_src="$(git -C "$REPO" rev-parse --path-format=absolute --git-path index 2>/dev/null || true)"
    [ -n "$_index_src" ] || _index_src="$REPO/.git/index"
  fi
  # git runs hooks from the top of the worktree, so a relative export resolves
  # against $REPO. --path-format=absolute covers the fallback; older git has no
  # such flag and returns a relative path, which this also catches.
  case "$_index_src" in /*) ;; *) _index_src="$REPO/$_index_src" ;; esac
  if [ ! -f "$_index_src" ]; then
    echo "verify.sh: cannot read the index at $_index_src. Refusing." >&2
    exit 1
  fi
  # git replaces the index by rename, so a cp sees one complete version of it,
  # never a torn one.
  if ! CP_ERR="$(cp "$_index_src" "$TMP/index" 2>&1)"; then
    echo "verify.sh: could not copy the index for the staged snapshot. Refusing." >&2
    printf '%s\n' "$CP_ERR" | sed 's/^/  /' >&2
    exit 1
  fi
  # Kept as a branch rather than deleted: the copy removes the contention on the
  # REAL index, and a failure here is then about the snapshot machinery rather
  # than about the staged code. Either way it is not a failed check, and saying so
  # is the whole point of ASK-1900.
  TREE=""
  for _try in 1 2 3; do
    if TREE="$(GIT_INDEX_FILE="$TMP/index" git -C "$REPO" write-tree 2>"$TMP/write-tree.err")"; then
      break
    fi
    TREE=""
    _err="$(cat "$TMP/write-tree.err")"
    # A NON-collision failure must not be retried. Retrying a deterministic error
    # three times only makes the refusal slower and buries the real message.
    is_collision_error "$_err" || break
    sleep 0.2
  done
  if [ -z "$TREE" ]; then
    if is_collision_error "${_err:-}"; then
      snapshot_collision "write the staged tree after 3 tries" "${_err:-}"
    fi
    echo "verify.sh: could not build the staged tree. Refusing." >&2
    printf '%s\n' "${_err:-}" | sed 's/^/  /' >&2
    exit 1
  fi
  # An empty repo has no HEAD to parent from; the adversarial suite covers it.
  if git -C "$REPO" rev-parse --verify -q HEAD >/dev/null 2>&1; then
    SNAP="$(git -C "$REPO" commit-tree "$TREE" -p HEAD -m 'verify.sh staged snapshot')"
  else
    SNAP="$(git -C "$REPO" commit-tree "$TREE" -m 'verify.sh staged snapshot')"
  fi
  # FAIL, never fall through. A failed `worktree add` leaves $TMP/wt absent, and
  # a TARGET that does not exist would send every check at the MAIN CHECKOUT,
  # reporting green for a tree nobody staged.
  #
  # `env -u` is not defensive tidiness, it is the whole reason this works inside
  # a hook. git EXPORTS GIT_DIR and GIT_INDEX_FILE to its hooks, and a child
  # `git worktree add` inherits them and tries to use the PARENT's index path
  # inside the new worktree: "fatal: .git/index: index file open failed: Not a
  # directory". Measured 2026-08-27 -- verify.sh --staged ran fine by hand and
  # refused every time lefthook called it, which is the worst possible split
  # because the by-hand run is the one you use to convince yourself it works.
  # write-tree above deliberately KEEPS the inherited environment: it has to
  # read the index the commit is actually being built from.
  #
  # `.git/worktrees` is shared by every worktree of the repo, so this is the
  # second collision surface (ASK-1900) and it gets the same treatment as
  # write-tree: retry a lock or a name clash, refuse anything else immediately,
  # and never report either as a failed check.
  materialise_snapshot "$SNAP" "staged"
  # AND NOW DROP THEM FOR THE REST OF THE RUN. Sanitizing only the `worktree
  # add` above fixed the crash and left the deeper half: every check below runs
  # with the hook's environment too, so a TEST that shells out to git inherits
  # GIT_DIR=.git and GIT_INDEX_FILE=.git/index and asks the PARENT repo, from
  # inside the snapshot, using a relative path that means something else there.
  # Measured 2026-08-27: a bare `verify.sh --staged` printed "verify.sh ok" and
  # the pre-commit call on byte-identical staged content failed on
  # test_corpus_is_tracked, test_acquisition_manifest,
  # test_sp_392043b5_backup_is_ignored and test_provenance_repo_field -- every
  # one of them a test that asks git what is tracked or ignored.
  #
  # This is the script's own thesis applied to itself. verify.sh exists so the
  # same checks run identically at every door; a run whose answers depend on
  # which door invoked it is the exact drift it was written to stop.
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
elif [ "$MODE" = "--changed" ]; then
  # THE PUSH DOOR, SCOPED (founder-directed 2026-09-30). Pre-push used to run
  # --full: ~6300 tests in consulting, 6-13 min, pushes hitting a 30-min timeout,
  # and CI then ran the SAME full suite again before any merge, because main
  # requires the `validate` check. Every change paid the whole suite twice. The
  # full suite now runs ONCE, in CI, which is the gate merges already wait on.
  # This door runs the tests that own what the branch changed.
  #
  # WHAT IS GRADED: a copy of one COMMIT (default HEAD), not the working tree.
  # A push sends commits; uncommitted edits never reach the remote, so grading
  # them (as --full at pre-push did) could block a push on work it does not carry.
  #
  # WHAT CHANGED: the diff from the merge-base with origin's DEFAULT branch, never
  # from the branch's own upstream. A new branch has no upstream, and cole-gtm's
  # gate answered that with "no remote base to diff; running the suite", which is
  # the full-suite tax on every first push. The default branch always exists.
  _rev="$(git -C "$REPO" rev-parse --verify -q "${CHANGED_REV}^{commit}" || true)"
  if [ -z "$_rev" ]; then
    echo "verify.sh --changed: cannot resolve '$CHANGED_REV' to a commit. Refusing." >&2
    exit 1
  fi
  _base_ref="$CHANGED_BASE"
  if [ -z "$_base_ref" ]; then
    _base_ref="$(git -C "$REPO" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    if [ -z "$_base_ref" ]; then
      for _cand in origin/main origin/master; do
        if git -C "$REPO" rev-parse --verify -q "$_cand^{commit}" >/dev/null; then
          _base_ref="$_cand"; break
        fi
      done
    fi
  fi
  _mb=""
  if [ -n "$_base_ref" ]; then
    _mb="$(git -C "$REPO" merge-base "$_base_ref" "$_rev" 2>/dev/null || true)"
  fi
  if [ -n "$_mb" ]; then
    # --no-renames for the same reason as --staged (PR #371): a rename must
    # surface the OLD module name, or the tests importing it go unselected.
    # -z on all four diffs. By default git prints a non-ASCII path quoted and
    # octal-escaped, `"suite/test_caf\303\251.py"`, which no `^suite/` gate
    # matches, so the suite was skipped at exit 0 (PR #489 review, reproduced).
    # core.quotePath=false fixed only the accent: a `"` or `\` in a name is
    # quoted regardless (round 2 of the same review). NUL output is never quoted.
    ANY_STAGED="$(git -C "$REPO" diff -z --no-renames --name-only "$_mb" "$_rev" | tr '\0' '\n')"
    STAGED="$(git -C "$REPO" diff -z --name-only --diff-filter=ACMR "$_mb" "$_rev" | tr '\0' '\n')"
    if [ -z "$ANY_STAGED" ]; then
      echo "verify.sh --changed: $CHANGED_REV changes nothing against $_base_ref, nothing to verify."
      exit 0
    fi
    SCOPED=1
    _nchg=$(printf '%s\n' "$ANY_STAGED" | sed -n '$=')
    echo "verify.sh --changed: $_nchg path(s) changed since merge-base with $_base_ref (${_mb:0:12})"
  else
    # NO BASE, NO GUESS. A repo with no origin default branch, or history that
    # shares nothing with it, gets the FULL suite on the snapshot. A selector
    # that cannot say what changed may cost time, never coverage.
    echo "verify.sh --changed: no merge-base with origin's default branch -> full suite"
  fi
  TMP="$(mktemp -d)"
  materialise_snapshot "$_rev" "changed"
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
else
  TARGET="$REPO"
  # --full has no snapshot to build, so there is nothing to read the index for
  # and the same leak applies from the first check onward.
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
fi

# The scoped pytest runner, ONE body for the selected and the full-suite case.
# args: target suite cache plugin_dir select_list(or "") serial_list(or "") xdist...
# Exit 5 ("collected nothing") from a SELECTION reruns the full suite rather than
# passing on zero tests. With a .verify-serial, phase one runs everything else
# (in parallel when xdist args are given) and phase two runs the serial files in
# one process; a 5 from one phase is fine, a 5 from both is "collected nothing".
_VERIFY_RUN='
  cd "$1/$2" || exit 1
  cache="$3"; plug="$4"; list="$5"; serial="$6"; shift 6
  export PYTHONPATH="$plug${PYTHONPATH:+:$PYTHONPATH}"
  one() {
    local base=(python3 -m pytest -q --no-header --ff -x -o cache_dir="$cache" -p _kipi_verify_select)
    if [ -z "$serial" ]; then "${base[@]}" "$@"; return $?; fi
    export KIPI_VERIFY_SERIAL="$serial"
    KIPI_VERIFY_PHASE=parallel "${base[@]}" "$@"; local r1=$?
    if [ "$r1" -ne 0 ] && [ "$r1" -ne 5 ]; then return "$r1"; fi
    echo "serial pass (.verify-serial)"
    KIPI_VERIFY_PHASE=serial "${base[@]}"; local r2=$?
    if [ "$r2" -ne 0 ] && [ "$r2" -ne 5 ]; then return "$r2"; fi
    if [ "$r1" -eq 5 ] && [ "$r2" -eq 5 ]; then return 5; fi
    return 0
  }
  if [ -n "$list" ]; then export KIPI_VERIFY_SELECT="$list"; fi
  one "$@"; rc=$?
  if [ "$rc" -eq 5 ] && [ -n "$list" ]; then
    echo "selection collected no tests -> full suite"
    unset KIPI_VERIFY_SELECT
    one "$@"; rc=$?
  fi
  exit $rc'

say() { printf '  %-28s %s\n' "$1" "$2"; }

run_check() {
  local name="$1"; shift
  RAN+=("$name")
  if "$@" >/tmp/verify-$$-out 2>&1; then
    say "$name" "ok"
  else
    FAILED+=("$name")
    say "$name" "FAILED"
    # EVERY failure line, THEN the tail for context.
    #
    # the scar (2026-08-27): this was `| tail -30` alone. A run with 50 failures
    # printed the last 30 lines of pytest output, which held 12 of the 50 FAILED
    # lines, and the other 38 were invisible EVERYWHERE -- the job log, the raw
    # API log, `gh run view --log` all only ever contain what this line emitted.
    # I spent three rounds fixing the instances visible in a 12-of-50 sample,
    # which is precisely the fix-the-instance-not-the-class failure the reviewer
    # caught on this same PR three times.
    #
    # A gate that hides most of what it found is a gate you cannot act on. The
    # summary lines are the diagnosis, so they are never truncated silently: if
    # the cap is hit, the count of what was dropped is PRINTED, so the output can
    # never imply it was complete when it was not.
    _sum="$(grep -E '^(FAILED|ERROR) ' /tmp/verify-$$-out || true)"
    if [ -n "$_sum" ]; then
      _n=$(printf '%s\n' "$_sum" | wc -l | tr -d ' ')
      printf '%s\n' "$_sum" | head -200 | sed 's/^/      /'
      # `if`, NOT `[ ... ] && echo`. Under `set -e` a bare test that evaluates
      # FALSE returns 1 and kills the script mid-check -- which is exactly what
      # the first version of this block did, silently, before `say` could even
      # print the failure. Caught by running it against a repo with 40 failing
      # tests and watching verify.sh stop after "shell syntax ok".
      if [ "$_n" -gt 200 ]; then
        echo "      ... and $((_n - 200)) more failure lines (capped)"
      fi
      echo "      ---- tail of the run ----"
    fi
    sed 's/^/      /' /tmp/verify-$$-out | tail -30
  fi
  rm -f /tmp/verify-$$-out
}

echo "verify.sh ${MODE} in ${TARGET}"

# --- python: syntax, every tracked .py -----------------------------------
# This is not a linter and is not pretending to be one. It is the floor under
# the floor: a file that does not compile cannot be reasoned about by anything
# downstream, and this repo has no ruff installed to catch it.
# Enumerated from $TARGET, not $REPO: under --changed --rev the snapshot is a
# DIFFERENT commit from the checkout's index, and a .py present only in the
# pushed commit was never compiled (PR #489 review, reproduced: exit 0 on a
# commit with a SyntaxError). In --full TARGET is REPO, so nothing changes there.
PYFILES="$(git -C "$TARGET" ls-files -z '*.py' | tr '\0' '\n' | head -4000)"
if [ -n "$PYFILES" ]; then
  # compile(), NOT py_compile, and NOT ast.parse either. Two fixes, one line.
  #
  # WHY NOT py_compile (2026-08-29). It WRITES a .pyc, so any write failure
  # surfaces through a check labelled "python syntax", and the label is a lie
  # about the cause. Measured during a full-disk stop: this printed
  # `python syntax FAILED` and "a tree that does not parse cannot be tested"
  # while every file parsed fine and the real errors were hundreds of
  # `[Errno 28] No space left on device` from compileall. It sent the reader to
  # debug their own code, which is the most expensive place a wrong error
  # message can send someone. Reproducer without a full disk: put a valid .py in
  # a directory, chmod 500 it, run the old line, and read
  # `[Errno 13] Permission denied` reported as a syntax failure.
  #
  # WHY NOT ast.parse, which was the first fix and was too weak (Codex major,
  # PR #277). ast.parse only PARSES. The compiler runs a second layer of checks
  # that the parser does not, and every one of them is a real SyntaxError that
  # py_compile used to catch and ast.parse waves through. Measured, all six:
  #
  #     case                      ast.parse   compile()
  #     return outside function   pass        CAUGHT
  #     break outside loop        pass        CAUGHT
  #     continue outside loop     pass        CAUGHT
  #     yield outside function    pass        CAUGHT
  #     duplicate parameter       pass        CAUGHT
  #     await outside async       pass        CAUGHT
  #
  # compile() keeps the property the change was FOR -- it writes nothing -- while
  # restoring everything py_compile caught. Removing the write was the right
  # idea; removing the compiler with it was the accident.
  #
  # tokenize.open, not open(encoding="utf-8"): it honours the PEP 263 coding
  # cookie and strips a UTF-8 BOM, exactly as the interpreter does when it loads
  # the file. Plain utf-8 leaves the BOM in the string and compile() then
  # reports a SyntaxError on a file Python itself runs happily. No such file is
  # in the repo today, which is precisely why it would have been found late.
  #
  # ONE interpreter for every file, not one per file (ASK-1795). The per-file
  # loop spawned ~1500 python3 processes in consulting: 35s measured on
  # 2026-09-18, paid on every commit before a single test ran. Same compile(),
  # same tokenize.open, same verdict per file. dont_inherit=True so the checker's
  # own __future__ flags can never leak into the file being compiled, which is
  # exactly what the old fresh-process-per-file gave for free.
  run_check "python syntax" bash -c '
    cd "$1" || exit 1
    printf "%s\n" "$2" | python3 -c "
import sys, tokenize
fail = 0
for f in sys.stdin.read().splitlines():
    try:
        fh = tokenize.open(f)
    except FileNotFoundError:
        continue
    try:
        with fh:
            compile(fh.read(), f, \"exec\", dont_inherit=True)
    except Exception as e:
        print(f\"{f}: {type(e).__name__}: {e}\")
        fail = 1
sys.exit(fail)
"
  ' _ "$TARGET" "$PYFILES"
fi

# --- shell: syntax, every tracked .sh ------------------------------------
SHFILES="$(git -C "$TARGET" ls-files -z '*.sh' | tr '\0' '\n' | head -2000)"
if [ -n "$SHFILES" ]; then
  run_check "shell syntax" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      bash -n "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
  ' _ "$TARGET" "$SHFILES"
fi

# --- json: every tracked .json parses ------------------------------------
# Config in this fleet IS behaviour: room lists, model tiers, source weights.
# A malformed one fails at 07:30 in a launchd job nobody is watching.
# EXCLUDED BY PATHSPEC, NOT BY `grep -v`, and that is a silent-death fix
# (ASK-1900). grep exits 1 when nothing survives the filter, and under
# `set -euo pipefail` a command substitution whose pipeline returns 1 kills this
# script THERE: exit 1, in about a tenth of a second, with no message of its own
# and no summary line -- the exact shape of refusal this issue is about, reached
# by a second route. It fires on any repo whose tracked .json files are all under
# dist/ or node_modules/, and on any repo with no tracked .json at all. Found by
# the ASK-1900 reproducer, whose first fixture had no .json and which therefore
# measured this instead of the race it was written for.
# git ls-files exits 0 on an empty result, so the hazard is gone rather than
# suppressed with `|| true` -- which would also have hidden a real grep error.
# Verified identical on this repo: both forms select the same 563 files.
JSONFILES="$(git -C "$TARGET" ls-files -z '*.json' \
  ':!:dist/**' ':!:**/dist/**' ':!:node_modules/**' ':!:**/node_modules/**' | tr '\0' '\n' | head -3000)"
if [ -n "$JSONFILES" ]; then
  # One interpreter for all of them, same reason as python syntax (ASK-1795).
  run_check "json parse" bash -c '
    cd "$1" || exit 1
    printf "%s\n" "$2" | python3 -c "
import json, os, sys
fail = 0
for f in sys.stdin.read().splitlines():
    if not os.path.isfile(f):
        continue
    try:
        with open(f) as fh:
            json.load(fh)
    except Exception as e:
        print(f\"{f}: {type(e).__name__}: {e}\")
        fail = 1
sys.exit(fail)
"
  ' _ "$TARGET" "$JSONFILES"
fi

# --- ruff, only if the machine has it ------------------------------------
# Optional TOOL, never an optional CHECK: if ruff is installed it must pass.
# The discovery is about what exists, not about what is allowed to fail.
if command -v ruff >/dev/null 2>&1; then
  run_check "ruff" bash -c 'cd "$1" && ruff check .' _ "$TARGET"
fi

# --- tests ---------------------------------------------------------------
# --staged runs the tests from the COPY, which is the point: it proves the
# snapshot being committed passes on its own, not that the working tree does.
# NO PIPE INTO `grep -q` HERE, and that is a scar, not a style preference.
# The first version of this line ended `| grep -q .`. Under `set -o pipefail`,
# grep -q exits the instant it matches, git gets SIGPIPE (141), and the PIPELINE
# reports failure precisely BECAUSE there were tests. Measured on the first live
# run: 400 test files present, pytest silently skipped, exit 0, "verify.sh ok".
# A discovery step that inverts on success is worse than no discovery step.
# FAIL FAST BEFORE THE EXPENSIVE PART. Measured 2026-08-27: a commit with one
# unparseable .py staged blocked correctly and took over two minutes, because
# the syntax check failed and the script then ran the full suite anyway. Nobody
# waits two minutes to be told about a typo; they run --no-verify, and then the
# floor is decorative. Tests cannot tell you anything useful about a tree that
# does not parse, so there is nothing lost by stopping here.
if [ ${#FAILED[@]} -gt 0 ]; then
  echo
  echo "verify.sh FAILED (${#FAILED[@]}/${#RAN[@]}): ${FAILED[*]}" >&2
  echo "Stopped before the test suites: a tree that does not parse cannot be tested." >&2
  exit 1
fi

TESTFILES="$(git -C "$TARGET" ls-files -z 'test_*.py' '*/test_*.py' | tr '\0' '\n')"

# THE SUITE MANIFEST, `.verify-suites` at the repo root, one `dir` per line.
# Each is a directory pytest is invoked FROM, because that is how these suites
# actually run: q-consult/pipeline/tests imports `pipeline`, which resolves only
# with q-consult as the working directory. A single root-level pytest is the
# obvious design and it is wrong here. Measured: from the repo root, 3526 tests
# collect and 896 error out, most of them belonging to the nested instances
# under projects/ that are separate repos with their own paths. From their own
# directories the two real suites collect 5379 and 486 with zero errors.
#
# A repo with no manifest falls back to one root pytest, which is right for a
# normal repo and is what every instance without the file gets.
# THE MANIFEST COMES FROM THE TREE BEING GRADED, not from the working tree.
#
# the finding (codex, PR #259 round 5): both reads used $REPO. In --full that is
# the same path, so it looked right. In --staged it meant the snapshot's checks
# were chosen by whatever manifest happened to be lying in the working tree.
# Stage a commit that ADDS a suite and the gate would not run it; stage one that
# REMOVES a broken suite and the gate would still run it and refuse. The whole
# premise of --staged is "grade what the commit contains", and the file deciding
# WHAT GETS GRADED was exempt from it.
# THE INSTALLED GUARD MUST MATCH THE REVIEWED ONE (ASK-1144).
#
# `~/.claude/settings.json` runs destructive-op-deny.sh from the HOME tree; this
# repo holds the vendored copy that gets reviewed. Nothing compared them, so a
# corrected hook could merge while unattended agents kept executing the stale
# one. Codex measured it on PR #279: checked_in_equals_installed=no.
#
# SCOPED TO A MACHINE THAT ACTUALLY RUNS HOOKS, and that is not a bypass. A
# GitHub runner has no ~/.claude/hooks at all, so an unscoped check would be red
# on every PR for a reason nobody can fix in a commit -- the exact shape the
# .verify-suites comment below was written about, and the fastest way to get a
# gate switched off. On a runner it prints a SKIP line rather than passing
# silently: a check that could not run has to say so.
# THE DENYLIST MUST NAME SERVERS THAT EXIST (ASK-1144). Operation-keyed denial
# makes a MISSING namespace harmless; it does not make a DEAD one visible, and a
# dead entry reading as coverage is what let the Linear hole survive review.
# Machine-independent by construction (declared namespaces, not discovered), so
# it means the same thing on a runner as on a laptop.
# GUARDED ON THE FILES EXISTING, because verify.sh runs against trees that are
# not this repo. The floor's own adversarial suite drives it at synthetic
# fixtures with no q-system/ at all, and an unconditional check there fails for
# "the file is missing" rather than for anything about the target -- 5 of 7
# adversarial cases went red exactly that way. A check that cannot apply must
# say so, not fail.
_mcp_ns_check="$TARGET/q-system/.q-system/scripts/mcp-denylist-namespace-check.py"
_mcp_ns_hook="$TARGET/q-system/.q-system/hooks/destructive-op-deny.sh"
if [ -f "$_mcp_ns_check" ] && [ -f "$_mcp_ns_hook" ]; then
  run_check "mcp-denylist-namespaces" \
    python3 "$_mcp_ns_check" --hook "$_mcp_ns_hook"
fi

# AT PRE-COMMIT (--staged) DRIFT IS A WARN, NOT A FAILURE (ASK-1248).
#
# The install happens AFTER merge (kipi update, behind its provenance preflight).
# So a branch that changes the hook can never commit while this check fails the
# commit: the machine only gets the new copy once the branch lands, and the
# branch only lands once it can commit. Measured 2026-09-23: the merge of main
# into sana/ask-1144 was refused here, installed copy 480 lines vs 898. Merged,
# it would also have refused every OTHER kipi-system commit on the machine until
# someone installed by hand. --changed (pre-push) gets the same WARN for the
# same reason: a branch that edits a hook could commit and then never push.
# --full on a machine with installed hooks (a deliberate run) still FAILS on
# drift, and `kipi update --dry` still prints it, so drift stays visible.
_hooks_installer="$TARGET/q-system/.q-system/scripts/install-claude-hooks.py"
if { [ "$MODE" = "--staged" ] || [ "$MODE" = "--changed" ]; } && [ -d "$HOME/.claude/hooks" ] && [ -f "$_hooks_installer" ]; then
  if _drift="$(python3 "$_hooks_installer" --check 2>&1)"; then
    say "installed-hooks-match-repo" "ok"
  else
    say "installed-hooks-match-repo" "WARN (drift; not fatal at commit/push, --full fails)"
    printf '%s\n' "$_drift" | sed 's/^/    /'
  fi
elif [ -d "$HOME/.claude/hooks" ] && [ -f "$_hooks_installer" ]; then
  run_check "installed-hooks-match-repo" \
    python3 "$_hooks_installer" --check
else
  say "installed-hooks-match-repo" "SKIP (no ~/.claude/hooks on this machine)"
fi

MANIFEST="$TARGET/.verify-suites"
if [ -f "$MANIFEST" ]; then
  if command -v pytest >/dev/null 2>&1 || python3 -c "import pytest" 2>/dev/null; then
    while IFS= read -r suite; do
      case "$suite" in ''|'#'*) continue ;; esac
      # A MANIFEST ENTRY MAY BE A FILE, not only a directory.
      #
      # why (codex, PR #259 round 4): 10 tracked test files sit where no
      # runnable directory contains them -- two at the repo root, one beside a
      # broken sibling suite, two under scripts/. Running pytest FROM those
      # locations either collects nothing or drags in the vendored trees that
      # produce 109 collection errors. Without file support the only options
      # were to leave them silently ungated, which is the finding, or to declare
      # them excluded, which pretends a limitation is a decision. 48 tests were
      # passing and gated by nothing.
      #
      # A file entry runs from the REPO ROOT against that path, so pytest
      # resolves it exactly as a human would typing the path.
      if [ -f "$TARGET/$suite" ]; then
        if [ -n "$SCOPED" ]; then
          if ! printf '%s\n' "$STAGED" | grep -q "^$suite$"; then
            say "pytest:$suite" "skipped (not staged)"
            continue
          fi
        fi
        run_check "pytest:$suite" bash -c 'cd "$1" && python3 -m pytest "$2" -q --no-header' \
                  _ "$TARGET" "$suite"
        continue
      fi
      if [ ! -d "$TARGET/$suite" ]; then
        # A manifest naming a directory that is gone is a BROKEN FLOOR. Silently
        # skipping it is how a suite stops running and nobody notices.
        RAN+=("pytest:$suite")
        FAILED+=("pytest:$suite (directory missing)")
        say "pytest:$suite" "FAILED (missing)"
        continue
      fi
      # --staged runs only the suites that OWN a staged file. Not a weaker
      # check, a narrower input: the same pytest, on the same snapshot, scoped
      # to what this commit can have broken. The full suite is 5 minutes here,
      # and a 5-minute pre-commit is a hook people delete. --changed (pre-push)
      # scopes the same way over the branch's diff; CI runs --full and is the
      # required merge check, so nothing reaches main unrun.
      # ANY_STAGED, not STAGED: a branch or commit that only DELETES a module
      # under the suite still has to run the tests that import it. STAGED drops
      # deletions (it scopes syntax checks), so keying on it skipped the suite
      # and a deleted-out-from-under import passed. Caught by
      # test_verify_changed.sh "deleting a module runs the tests naming it".
      if [ -n "$SCOPED" ]; then
        if ! printf '%s\n' "$ANY_STAGED" | grep -q "^$suite/"; then
          say "pytest:$suite" "skipped (no staged files)"
          continue
        fi
      fi
      # THE RETRY COSTS AS MUCH AS THE FIRST RUN, and that is the whole problem
      # (2026-08-29). A caller with a shorter timeout than the suite kills the hook
      # mid-run, nothing is committed, the caller retries, and pays the full run
      # again to reach the same failure. Measured three times in one session on a
      # ~160s suite.
      #
      # Two changes, neither of which weakens the gate:
      #
      #   --ff   run the tests that failed LAST time first. The retry hits its
      #          failure in seconds instead of after the whole suite.
      #   -x     stop at the first failure. A commit blocked by one failing test is
      #          blocked either way; there is nothing gained by spending another two
      #          minutes proving the rest still pass. A GREEN run is unaffected: it
      #          has no first failure, so it still runs every test. Measured on a
      #          real hook: a failing pre-commit went 142s -> 2.84s, and a green
      #          tree still ran all 5800 tests.
      #
      # `-o cache_dir` is what makes --ff work at all here. The --staged snapshot
      # worktree is thrown away after every run, so pytest's cache died with it and
      # --ff had nothing to read. The cache lives under git's COMMON DIR instead,
      # keyed per suite. It is a CACHE OF ORDERING, never of verdicts: no run is
      # skipped, so a corrupt or stale cache can only make the run slower, never
      # green-by-cache.
      #
      # NOT `$REPO/.verify-cache` (Codex major, PR #269). That path is inside the
      # working tree and matched no .gitignore entry, so every staged run left the
      # checkout dirty -- and this fleet's unattended jobs commit with `git add -A`,
      # so pytest cache files would ride into real commits and a human would be
      # cleaning them at 3am. The common dir is the right home for two reasons at
      # once: git never reports it in `status`, and it is SHARED across worktrees,
      # so the primary checkout and every scratch worktree warm one cache instead
      # of N. A .gitignore entry would have fixed only the first half.
      #
      # --full deliberately keeps NEITHER flag. Pre-push and CI want the complete
      # picture, not the fastest no. The file-entry branch above also keeps neither:
      # a single test file is already the fast case, so --ff would buy nothing and
      # -x would hide sibling failures in the same file.
      #
      # --staged ALSO NARROWS THE SUITE TO THE TESTS THAT OWN THE CHANGE (ASK-1795).
      # A suite used to run IN FULL on any staged path under it: every commit
      # touching q-consult/ in the consulting instance ran ~6300 tests, 620s and
      # 788s measured 2026-09-18, and the founder asked twice that day for the
      # pre-commit door to stop doing that. verify_select.py picks the owning test
      # files and prints WHY per staged path; a path no test names takes the
      # suite's declared fallback (<suite>/.verify-fallback, else the full suite),
      # never nothing. --full is untouched, and CI (the required check) runs all of it.
      #
      # The selector comes from the TREE BEING GRADED, same rule as the manifest.
      # If it is missing or errors, the suite runs in full: a broken selector may
      # cost time, it may never cost coverage.
      if [ -n "$SCOPED" ]; then
        _cache="$VERIFY_CACHE_ROOT/$(printf '%s' "$suite" | tr / _)"
        _sel_src="$TARGET/q-system/.q-system/verify_select.py"
        [ -f "$_sel_src" ] || _sel_src="$SCRIPT_DIR/verify_select.py"
        _sel_mode="full"; _sel_out=""
        # The commit door asks for the NARROW rule (imports, not bare words);
        # the push door keeps the broad one. See verify_select.py's docstring.
        _sel_door=""
        [ "$MODE" = "--staged" ] && _sel_door="staged"
        if [ -f "$_sel_src" ] && \
           _sel_out="$(printf '%s\n' "$ANY_STAGED" | \
                       python3 "$_sel_src" --target "$TARGET" --suite "$suite" \
                         ${_sel_door:+--door "$_sel_door"})"; then
          # Parameter expansion, not `| head -1`: under pipefail a selection past
          # the pipe buffer SIGPIPEs printf and set -e aborts with no verdict
          # (PR #489 review round 2).
          _sel_mode="${_sel_out%%$'\n'*}"
        else
          echo "      selector unavailable or failed -> full suite"
        fi
        # PARALLEL AT THE COMMIT DOOR (2026-10-05). The staged run used one core of
        # ten: a one-file change to a hot module selected ~100 test files and the
        # commit took 6 to 23 minutes. pytest-xdist spreads the selection across
        # workers. --dist loadfile keeps every test of one FILE on one worker, so
        # module-scoped fixtures and in-file ordering behave exactly as serially.
        # A suite's `.verify-serial` (test paths relative to the suite, one per
        # line) names files that share state ACROSS files; they run afterwards
        # in a second, single-process pass, so nothing else runs beside them.
        # No xdist installed means serial, said out loud, never a failure: speed
        # is not coverage. --changed and --full are untouched.
        _xd=()
        if [ "$MODE" = "--staged" ] && [ -z "${KIPI_VERIFY_NO_XDIST:-}" ]; then
          if python3 -c "import xdist" 2>/dev/null; then
            _ncpu="$(python3 -c 'import os; print(os.cpu_count() or 1)')"
            _xd=(-n "$_ncpu" --dist loadfile)
          else
            echo "      pytest-xdist not installed -> serial (pip install -r q-system/.q-system/requirements-verify.txt)"
          fi
        fi
        _serial="$TARGET/$suite/.verify-serial"
        [ -f "$_serial" ] || _serial=""
        if [ "$_sel_mode" = "select" ]; then
          _plug="$TMP/verify-select-plugin"
          mkdir -p "$_plug"
          cp "$_sel_src" "$_plug/_kipi_verify_select.py"
          _list="$TMP/verify-select-$(printf '%s' "$suite" | tr / _).txt"
          # sed -n, never `| head`: under pipefail head's early exit SIGPIPEs the
          # writer and kills the script (the 141 scar in the discovery note above).
          printf '%s\n' "$_sel_out" | sed -n '2,$p' | sed '/^$/d' > "$_list.rel"
          sed "s|^|$TARGET/$suite/|" "$_list.rel" > "$_list"
          _n=$(sed -n '$=' "$_list"); _n="${_n:-0}"
          sed -n '1,40p' "$_list.rel" | sed 's/^/        /'
          if [ "$_n" -gt 40 ]; then echo "        ... and $((_n - 40)) more"; fi
          # Exit 5 is "collected nothing": every selected file was collect_ignored
          # or held no test. That is an empty selection, so it takes the full
          # suite rather than passing on zero tests run.
          run_check "pytest:$suite ($_n selected)" bash -c "$_VERIFY_RUN" _ \
            "$TARGET" "$suite" "$_cache" "$_plug" "$_list" "$_serial" "${_xd[@]+"${_xd[@]}"}"
        else
          _plug="$TMP/verify-select-plugin"
          mkdir -p "$_plug"
          [ -f "$_sel_src" ] && cp "$_sel_src" "$_plug/_kipi_verify_select.py"
          if [ -f "$_plug/_kipi_verify_select.py" ]; then
            run_check "pytest:$suite" bash -c "$_VERIFY_RUN" _ \
              "$TARGET" "$suite" "$_cache" "$_plug" "" "$_serial" "${_xd[@]+"${_xd[@]}"}"
          else
            # No selector anywhere: no plugin to load, so no phases. Same full,
            # ordered, fail-fast run as before; parallel still applies.
            run_check "pytest:$suite" bash -c \
              'cache="$3"; cd "$1/$2" && shift 3 && python3 -m pytest -q --no-header --ff -x -o cache_dir="$cache" "$@"' \
              _ "$TARGET" "$suite" "$_cache" "${_xd[@]+"${_xd[@]}"}"
          fi
        fi
      else
        run_check "pytest:$suite" bash -c 'cd "$1/$2" && python3 -m pytest -q --no-header' \
                  _ "$TARGET" "$suite"
      fi
    done < "$MANIFEST"
  else
    RAN+=("pytest")
    FAILED+=("pytest: .verify-suites present but pytest is not installed")
    say "pytest" "FAILED (not installed)"
  fi
elif [ -f "$TARGET/pytest.ini" ] || [ -f "$TARGET/pyproject.toml" ] || \
     [ -d "$TARGET/tests" ] || [ -n "$TESTFILES" ]; then
  if command -v pytest >/dev/null 2>&1 || python3 -c "import pytest" 2>/dev/null; then
    run_check "pytest" bash -c 'cd "$1" && python3 -m pytest -q --no-header' _ "$TARGET"
  else
    # Tests exist and the runner does not. That is a broken floor, not a pass.
    RAN+=("pytest")
    FAILED+=("pytest: tests present but pytest is not installed")
    say "pytest" "FAILED (not installed)"
  fi
fi

echo
if [ ${#RAN[@]} -eq 0 ]; then
  echo "verify.sh: NO CHECKS DISCOVERED. Failing." >&2
  echo "A gate that cannot run must not pass. Wire a check or delete this hook." >&2
  exit 1
fi

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "verify.sh FAILED (${#FAILED[@]}/${#RAN[@]}): ${FAILED[*]}" >&2
  exit 1
fi

echo "verify.sh ok (${#RAN[@]} checks: ${RAN[*]})"
