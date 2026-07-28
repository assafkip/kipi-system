#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SHA=28ae52602b528f5e89dfd2c14739c407b5754c5e
mkdir -p .pr25rev/head/q-system/.q-system/scripts/test
for f in \
  q-system/.q-system/scripts/linear-worker.sh \
  q-system/.q-system/scripts/pr-verdict-lib.sh \
  q-system/.q-system/scripts/test/test-severity-floor.sh ; do
  git show "$SHA:$f" > ".pr25rev/head/$f"
done
git diff main..."$SHA" -- q-system/.q-system/scripts > .pr25rev/pr25.diff
ls -l .pr25rev/head/q-system/.q-system/scripts .pr25rev/head/q-system/.q-system/scripts/test
wc -l .pr25rev/pr25.diff
