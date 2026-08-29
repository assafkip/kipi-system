#!/usr/bin/env bash
# Adversarial test for verify.sh: does it actually BLOCK, or only pass tests?
#
# Every case builds a FRESH throwaway repo, breaks something real, runs the real
# script, and asserts the EXIT CODE. No mocks, no stubs, no fixtures.
#
# The harness lives OUTSIDE the repos it builds. The first version lived inside
# one and its own `git clean -fd` deleted it mid-run, which produced two
# phantom failures that had nothing to do with verify.sh. A test harness that
# perturbs its own subject is measuring itself.
VERIFY_SRC="${1:?usage: adversarial.sh /path/to/verify.sh}"
pass=0; fail=0

newrepo() {
  local d; d="$(mktemp -d)"
  git -C "$d" init -q .
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  mkdir -p "$d/q-system/.q-system"
  cp "$VERIFY_SRC" "$d/q-system/.q-system/verify.sh"
  printf "print('ok')\n" > "$d/good.py"
  printf '{"a": 1}\n'    > "$d/good.json"
  printf 'echo hi\n'     > "$d/good.sh"
  git -C "$d" add -A; git -C "$d" commit -qm init
  printf '%s' "$d"
}

check() {
  if [ "$2" = "$3" ]; then printf '  PASS  %-38s exit=%s\n' "$1" "$3"; pass=$((pass+1))
  else printf '  FAIL  %-38s exit=%s want=%s\n' "$1" "$3" "$2"; fail=$((fail+1)); fi
}

run() { ( cd "$1" && bash q-system/.q-system/verify.sh "$2" >/dev/null 2>&1 ); }

# --- baseline: a clean repo must PASS, or every later result is meaningless ---
R=$(newrepo); run "$R" --full; check "clean repo, --full" 0 $?; rm -rf "$R"

# --- it blocks on real breakage, at the staged gate ---
for case in "py:def (:bad.py" "json:{bad:bad.json" "sh:if [ 1 ; then:bad.sh"; do
  kind="${case%%:*}"; rest="${case#*:}"; body="${rest%:*}"; file="${rest##*:}"
  R=$(newrepo); printf '%s\n' "$body" > "$R/$file"; git -C "$R" add "$file"
  run "$R" --staged; check "broken $kind, --staged BLOCKS" 1 $?; rm -rf "$R"
done

# --- THE STAGED SNAPSHOT IS THE SUBJECT, not the working tree ---
# This is the entire reason --staged materialises the index into a temp dir.
R=$(newrepo)
printf 'def (\n' > "$R/good.py"           # TRACKED file, broken, NOT staged
printf 'x\n' > "$R/ok.txt"; git -C "$R" add ok.txt
run "$R" --staged; check "unstaged breakage ignored, --staged" 0 $?
run "$R" --full;   check "same breakage caught by --full" 1 $?
rm -rf "$R"

# --full deliberately does NOT see an untracked file. It runs at pre-push and in
# CI, and an untracked file reaches neither. Asserted so that if someone later
# widens --full to walk the filesystem, this goes red and they have to argue for
# it rather than drift into it.
R=$(newrepo)
printf 'def (\n' > "$R/never-tracked.py"
run "$R" --full;   check "untracked file NOT checked by --full" 0 $?
rm -rf "$R"

# --- a commit cannot smuggle breakage past --staged by leaving it unstaged ---
# The inverse of the case above: the file IS staged broken while the working
# tree copy is fine. A hook that checked the working tree would pass this.
R=$(newrepo)
printf 'def (\n' > "$R/sneak.py"; git -C "$R" add sneak.py
printf "print('fine')\n" > "$R/sneak.py"   # working tree now clean, index is not
run "$R" --staged; check "staged-broken/tree-clean BLOCKS" 1 $?
rm -rf "$R"

# --- THE ONE THAT MATTERS: nothing to check must FAIL, never pass ---
# A green exit meaning "I found no linter" is indistinguishable from "your code
# is fine" at any call site that reads only the exit code.
E="$(mktemp -d)"; git -C "$E" init -q .
git -C "$E" config user.email t@t; git -C "$E" config user.name t
mkdir -p "$E/q-system/.q-system"; cp "$VERIFY_SRC" "$E/q-system/.q-system/verify.sh"
printf 'hello\n' > "$E/readme.txt"; git -C "$E" add -A
git -C "$E" commit -qm init
run "$E" --full; check "empty repo FAILS (cannot-run)" 1 $?; rm -rf "$E"

# --- a manifest naming a vanished suite must FAIL, never silently skip ---
R=$(newrepo)
printf 'no-such-dir\n' > "$R/.verify-suites"
printf 'x\n' > "$R/t.txt"; git -C "$R" add .verify-suites t.txt
run "$R" --staged; check "missing suite dir FAILS" 1 $?; rm -rf "$R"

# --- nothing staged is a no-op. A hook that blocks an empty commit gets removed ---
R=$(newrepo); run "$R" --staged; check "nothing staged, --staged no-op" 0 $?; rm -rf "$R"

# --- bad argument is refused, not silently treated as --full ---
R=$(newrepo)
( cd "$R" && bash q-system/.q-system/verify.sh --oops >/dev/null 2>&1 )
check "unknown mode refused" 2 $?; rm -rf "$R"

# --- THE HOOK ENVIRONMENT. git exports GIT_DIR and GIT_INDEX_FILE to its hooks,
# and --staged builds a worktree, which inherits them and dies on the parent's
# relative index path. Measured 2026-08-27: --staged passed by hand and refused
# on every lefthook pre-commit call, which is the worst split there is, because
# the by-hand run is the one you use to convince yourself the gate works.
# Every other case here runs with a clean environment and CANNOT see it.
R=$(newrepo)
printf 'x = 1\n' > "$R/ok.py"; git -C "$R" add ok.py
( cd "$R" && GIT_DIR=.git GIT_INDEX_FILE=.git/index \
    bash q-system/.q-system/verify.sh --staged >/dev/null 2>&1 )
check "--staged works under hook env" 0 $?; rm -rf "$R"

# --- THE STAGED MANIFEST DECIDES, NOT THE WORKING TREE'S. Both reads used
# $REPO, which is identical in --full and wrong in --staged: the snapshot's
# checks were chosen by whatever .verify-suites happened to be lying in the
# working tree. Here the STAGED manifest names a directory that does not exist
# (which verify.sh must refuse) while the WORKING TREE manifest is valid. The
# old code read the working tree, found a fine manifest, and passed.
R=$(newrepo)
mkdir -p "$R/realsuite"
printf 'def test_ok():\n    assert True\n' > "$R/realsuite/test_ok.py"
printf 'realsuite\n' > "$R/.verify-suites"
git -C "$R" add .verify-suites realsuite/test_ok.py
git -C "$R" commit -qm "good manifest"
# stage a BAD manifest, then put the good one back in the working tree only
printf 'no-such-dir\n' > "$R/.verify-suites"
git -C "$R" add .verify-suites
printf 'realsuite\n' > "$R/.verify-suites"
run "$R" --staged; check "staged manifest decides, not the worktree" 1 $?

# --- A DELETION-ONLY COMMIT MUST STILL BE CHECKED. The scoping list excludes
# deletions on purpose (you cannot syntax-check a file that will not exist), and
# one variable used to answer both "what do I scope to" and "is this commit
# empty". So a commit that ONLY deletes files produced an empty list, hit the
# nothing-staged early exit, and passed at exit 0 having run nothing at all.
# Deleting the last caller of a module, or deleting a test, is exactly the
# change a floor should look at: the remaining tree still has to parse.
R=$(newrepo)
printf 'x = 1\n' > "$R/keep.py"
printf 'def gone():\n    pass\n' > "$R/doomed.py"
git -C "$R" add keep.py doomed.py
git -C "$R" commit -qm "add"
printf 'this is not python(\n' > "$R/keep.py"
git -C "$R" add keep.py
git -C "$R" commit -qm "break it"
git -C "$R" rm -q doomed.py
# keep.py is broken in the committed tree, and the staged set is a deletion
# ONLY. The old code skipped everything here and exited 0.
run "$R" --staged; check "deletion-only commit is still checked" 1 $?

# --- THE DEEPER HALF of the same leak. Sanitizing only `worktree add` stops the
# crash and leaves every CHECK running with the hook's git environment, so a
# test that shells out to git asks the PARENT repo from inside the snapshot.
# This case owns a suite whose test does exactly that; case 13 cannot see it,
# because a repo with no git-aware test passes either way.
R=$(newrepo)
mkdir -p "$R/suite"
printf 'suite\n' > "$R/.verify-suites"
cat > "$R/suite/test_tracked.py" <<'PYEOF'
import subprocess
def test_git_sees_the_tracked_file():
    # ls-files prints paths relative to CWD, and pytest runs from the suite dir,
    # so this is "test_tracked.py" and not "suite/test_tracked.py". Under the
    # env leak GIT_DIR=.git resolves against THIS dir, finds nothing, and git
    # exits with empty stdout, which is what makes the assertion discriminate.
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    assert "test_tracked.py" in r.stdout, (r.returncode, r.stdout, r.stderr)
PYEOF
git -C "$R" add .verify-suites suite/test_tracked.py
( cd "$R" && GIT_DIR=.git GIT_INDEX_FILE=.git/index \
    bash q-system/.q-system/verify.sh --staged >/dev/null 2>&1 )
check "git-aware test correct under hook env" 0 $?; rm -rf "$R"

# --- A FAILING TEST INSIDE A STAGED MANIFEST SUITE MUST BLOCK. ---
#
# THE HOLE THIS FILLS (2026-08-29). Fifteen cases existed and not one of them
# ran a suite that FAILS. Every manifest case asserted a STRUCTURAL refusal --
# missing directory, wrong manifest, deletion-only -- so the line that actually
# invokes pytest was never graded on a red suite. Measured by mutation: replace
# the --staged pytest invocation with `true` and all 16 cases still passed. A
# floor whose whole job is running your tests had no test proving it runs them.
#
# It matters more now that --staged and --full invoke pytest DIFFERENTLY
# (--ff -x -o cache_dir on the staged path only). That split doubled the number
# of call sites a mutation can hide in, and the two cases below grade both.
R=$(newrepo)
mkdir -p "$R/suite"
printf 'suite\n' > "$R/.verify-suites"
printf 'def test_red():\n    assert False\n' > "$R/suite/test_red.py"
git -C "$R" add .verify-suites suite/test_red.py
run "$R" --staged; check "failing test in staged suite BLOCKS" 1 $?
# The same red suite through the OTHER invocation. --full keeps neither --ff nor
# -x, so it is a genuinely separate code path and a mutation of one does not
# show up in the other.
git -C "$R" commit -qm "commit the red suite"
run "$R" --full; check "failing test in suite BLOCKS --full" 1 $?; rm -rf "$R"

# --- AND THE GREEN CASE, so the two above cannot pass by always-refusing. ---
# Without this a verify.sh that returned 1 unconditionally would score 18/18.
R=$(newrepo)
mkdir -p "$R/suite"
printf 'suite\n' > "$R/.verify-suites"
printf 'def test_green():\n    assert True\n' > "$R/suite/test_green.py"
git -C "$R" add .verify-suites suite/test_green.py
run "$R" --staged; check "passing test in staged suite PASSES" 0 $?; rm -rf "$R"

echo
echo "adversarial: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
