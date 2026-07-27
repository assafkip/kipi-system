#!/usr/bin/env bash
# REPRO A: a COMPLETE, CORRECT kipi-dsse closeout run from anywhere that is not
# the sana/ask-<n> branch checkout produces a receipt with no linear_issue_id,
# so the PR receipt gate refuses the PR -- and the refusal text never mentions
# the branch requirement it actually enforces.
#
# Two shapes are exercised:
#   A1  closeout run from the founder's main checkout (branch `main`)
#   A2  closeout run from a detached HEAD (what `git worktree add <sha>` or a
#       CI-style checkout leaves you on)
set -uo pipefail

PR="/Users/assafkipnis/projects/kipi-system/.pr23rev/repo"
GATE="$PR/q-system/.q-system/scripts/pr-receipt-gate.py"
RUNNER="$PR/plugins/kipi-dsse/scripts/issue_runner.py"
WORK="/Users/assafkipnis/projects/kipi-system/.pr23rev/repro-a-work"

mk_repo() {   # $1 = dir, $2 = starting branch
  local d="$1" b="$2"
  mkdir -p "$d/.prd-os/issues"
  git -C "$d" init -q -b "$b"
  git -C "$d" config user.email t@k.invalid
  git -C "$d" config user.name kipi-test
  printf '.claude/state/\n' > "$d/.gitignore"
  echo work > "$d/work.txt"
  cat > "$d/.prd-os/issues/receipt-gate-e2e.md" <<'SPEC'
---
id: receipt-gate-e2e
title: end-to-end closeout for the receipt gate
status: in-progress
priority: p1
parent_prd: prd-e2e
allowed_files:
  - work.txt
required_checks:
  - "true"
---

<!-- generated-by: prd_split.py prd=prd-e2e finding=finding-1 at=2026-07-27T00:00:00Z -->

# end-to-end closeout for the receipt gate
SPEC
  git -C "$d" add -A
  git -C "$d" commit -qm "work + spec (ASK-999)"
}

closeout() {  # $1 = repo dir
  python3 "$RUNNER" --repo-root "$1" load receipt-gate-e2e   >/dev/null 2>&1
  python3 "$RUNNER" --repo-root "$1" mark verified           >/dev/null 2>&1
  python3 "$RUNNER" --repo-root "$1" mark reviewed           >/dev/null 2>&1
  python3 "$RUNNER" --repo-root "$1" mark findings_triaged   >/dev/null 2>&1
  python3 "$RUNNER" --repo-root "$1" close                   >/dev/null 2>&1
  echo "close rc=$?"
}

echo "############ A1: closeout run from the founder's main checkout ############"
A1="$WORK/a1"
mk_repo "$A1" main
closeout "$A1"
echo "--- receipt the real producer wrote ---"
cat "$A1/.prd-os/receipts.jsonl"
git -C "$A1" add -A; git -C "$A1" commit -qm "closeout receipt (ASK-999)" >/dev/null
echo "--- gate verdict for the PR branch sana/ask-999 ---"
python3 "$GATE" --branch sana/ask-999 --receipts "$A1/.prd-os/receipts.jsonl"
echo "GATE EXIT=$?"

echo
echo "############ A2: closeout run on a detached HEAD ############"
A2="$WORK/a2"
mk_repo "$A2" sana/ask-999
git -C "$A2" checkout -q --detach HEAD
echo "HEAD state: $(git -C "$A2" rev-parse --abbrev-ref HEAD)"
closeout "$A2"
echo "--- receipt the real producer wrote ---"
cat "$A2/.prd-os/receipts.jsonl"
echo "--- gate verdict for the PR branch sana/ask-999 ---"
python3 "$GATE" --branch sana/ask-999 --receipts "$A2/.prd-os/receipts.jsonl"
echo "GATE EXIT=$?"
