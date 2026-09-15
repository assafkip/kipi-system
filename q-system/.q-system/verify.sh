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
REPO="$(git rev-parse --show-toplevel)"
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

case "$MODE" in
  --staged|--full) ;;
  *) echo "usage: verify.sh [--staged|--full]" >&2; exit 2 ;;
esac

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
  ANY_STAGED="$(git -C "$REPO" diff --cached --name-only)"
  STAGED="$(git -C "$REPO" diff --cached --name-only --diff-filter=ACMR)"
  if [ -z "$ANY_STAGED" ]; then
    echo "verify.sh --staged: nothing staged, nothing to verify."
    exit 0
  fi
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
  TREE="$(git -C "$REPO" write-tree)"
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
  if ! WT_ERR="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE \
                     -u GIT_OBJECT_DIRECTORY -u GIT_COMMON_DIR \
                     git -C "$REPO" worktree add --detach "$TMP/wt" "$SNAP" 2>&1)"; then
    # Print what git said. The first version threw stderr away and the refusal
    # was untraceable: a gate that cannot say why it refused gets bypassed.
    echo "verify.sh: could not create the staged worktree. Refusing." >&2
    echo "$WT_ERR" | sed 's/^/  /' >&2
    exit 1
  fi
  TARGET="$TMP/wt"
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
else
  TARGET="$REPO"
  # --full has no snapshot to build, so there is nothing to read the index for
  # and the same leak applies from the first check onward.
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
fi

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
PYFILES="$(git -C "$REPO" ls-files '*.py' | head -4000)"
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
  run_check "python syntax" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      python3 -c "import sys,tokenize
with tokenize.open(sys.argv[1]) as fh:
    src = fh.read()
compile(src, sys.argv[1], \"exec\")" "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
  ' _ "$TARGET" "$PYFILES"
fi

# --- shell: syntax, every tracked .sh ------------------------------------
SHFILES="$(git -C "$REPO" ls-files '*.sh' | head -2000)"
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
JSONFILES="$(git -C "$REPO" ls-files '*.json' | grep -v -E '(^|/)(dist|node_modules)/' | head -3000)"
if [ -n "$JSONFILES" ]; then
  run_check "json parse" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
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

TESTFILES="$(git -C "$REPO" ls-files 'test_*.py' '*/test_*.py')"

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

if [ -d "$HOME/.claude/hooks" ] && [ -f "$TARGET/q-system/.q-system/scripts/install-claude-hooks.py" ]; then
  run_check "installed-hooks-match-repo" \
    python3 "$TARGET/q-system/.q-system/scripts/install-claude-hooks.py" --check
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
        if [ "$MODE" = "--staged" ]; then
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
      # and a 5-minute pre-commit is a hook people delete. Pre-push and CI run
      # --full, so nothing escapes; it just escapes later than the fastest
      # possible door.
      if [ "$MODE" = "--staged" ]; then
        if ! printf '%s\n' "$STAGED" | grep -q "^$suite/"; then
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
      if [ "$MODE" = "--staged" ]; then
        run_check "pytest:$suite" bash -c \
          'cd "$1/$2" && python3 -m pytest -q --no-header --ff -x -o cache_dir="$3"' \
          _ "$TARGET" "$suite" "$VERIFY_CACHE_ROOT/$(printf '%s' "$suite" | tr / _)"
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
elif [ -f "$REPO/pytest.ini" ] || [ -f "$REPO/pyproject.toml" ] || \
     [ -d "$REPO/tests" ] || [ -n "$TESTFILES" ]; then
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
