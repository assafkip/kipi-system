#!/usr/bin/env bash
# Ground-truth capture (ASK-215, PR #27 review round 2): the exact text and exit
# code git emits for the TRANSIENT failures the reviewer flagged, so the
# non-gate classifier keys off real output rather than remembered output.
# Run: bash q-system/output/capture-git-transient-failures.sh
set -uo pipefail

S="$(mktemp -d)"
cleanup() { python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$S"; }
trap cleanup EXIT
rmf() { python3 -c "import os,sys
for p in sys.argv[1:]:
    if os.path.exists(p):
        os.remove(p)" "$@"; }

cd "$S"
git init -q .
git config user.email t@t.t
git config user.name t
git config commit.gpgsign false
echo hi > a.txt
git add a.txt

run_case() {
  echo "===== $1 ====="
  set +e
  OUT="$(eval "$2" 2>&1)"
  CODE=$?
  set -e
  echo "exit_code=$CODE"
  printf '%s\n' "$OUT"
  echo
}

touch .git/index.lock
run_case "1. index.lock held (auto-committer / parallel session race)" \
  "git commit -m 'x (ASK-215)'"
rmf .git/index.lock

run_case "2. gpg signing failure" \
  "git -c commit.gpgsign=true -c gpg.program=/bin/false commit -m 'x (ASK-215)'"

mkdir -p .git/hooks
printf '#!/bin/sh\necho "BLOCK: bump plugin.json"\nexit 1\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
run_case "3. pre-commit hook REFUSAL (the real gate case)" \
  "git commit -m 'x (ASK-215)'"
rmf .git/hooks/pre-commit

git commit -q -m 'first (ASK-215)' >/dev/null 2>&1
run_case "4. nothing to commit" "git commit -m 'x (ASK-215)'"

B="$(git symbolic-ref --short HEAD)"
touch ".git/refs/heads/$B.lock"
echo more >> a.txt
git add a.txt
run_case "5. cannot lock ref" "git commit -m 'x (ASK-215)'"
rmf ".git/refs/heads/$B.lock"

# Does git propagate a hook's OWN exit status, or normalise it to 1? Decides
# whether "exit code 1" can be required as a positive gate signal.
echo "===== 6. hook exit-code propagation ====="
set +e
for c in 1 2 3 42 128; do
  printf '#!/bin/sh\necho "gate says no"\nexit %s\n' "$c" > .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit
  git commit -m "x (ASK-215)" >/dev/null 2>&1
  echo "hook exit $c -> git exit $?"
done
rmf .git/hooks/pre-commit
