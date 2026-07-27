#!/usr/bin/env bash
# REPRO B1: a hand-forged but WELL-FORMED receipt line, committed by the PR
#          itself, clears the gate with --head-sha. The gate reads the ledger
#          out of the PR's own head, so the artifact it trusts is authored by
#          the same actor it is supposed to be checking.
#
# REPRO B2: merging origin/main into the PR branch after a correct closeout
#          (the GitHub "Update branch" button) turns the gate red again.
set -uo pipefail

PR="/Users/assafkipnis/projects/kipi-system/.pr23rev/repo"
GATE="$PR/q-system/.q-system/scripts/pr-receipt-gate.py"
LEDGER_CHECK="$PR/q-system/.q-system/scripts/receipts-ledger-check.py"
RUNNER="$PR/plugins/kipi-dsse/scripts/issue_runner.py"
W="/Users/assafkipnis/projects/kipi-system/.pr23rev/repro-b-work"

echo "############ B1: forged well-formed receipt, no closeout ever ran ############"
B1="$W/b1"
mkdir -p "$B1/.prd-os"
git -C "$B1" init -q -b main
git -C "$B1" config user.email t@k.invalid
git -C "$B1" config user.name kipi-test
echo base > "$B1/base.txt"; git -C "$B1" add -A; git -C "$B1" commit -qm base
git -C "$B1" checkout -q -b sana/ask-999
echo "shipped work nobody verified" > "$B1/work.txt"
git -C "$B1" add -A; git -C "$B1" commit -qm "work (ASK-999)"
WORK_SHA="$(git -C "$B1" rev-parse HEAD)"

# The forgery: one line, valid JSON, only keys receipts-ledger-check.py allows.
printf '{"issue_id": "totally-made-up", "prd_id": "prd-x", "linear_issue_id": "ASK-999", "commit_sha": "%s", "closed_at": "2026-07-27T00:00:00Z", "verified_at": "2026-07-27T00:00:00Z", "reviewed_at": "2026-07-27T00:00:00Z", "findings_triaged_at": "2026-07-27T00:00:00Z"}\n' \
  "$WORK_SHA" > "$B1/.prd-os/receipts.jsonl"
git -C "$B1" add -Af; git -C "$B1" commit -qm "closeout receipt (ASK-999)" >/dev/null
HEAD_SHA="$(git -C "$B1" rev-parse HEAD)"

echo "--- did any closeout run? ---"
ls "$B1/.claude/state" 2>/dev/null || echo "no .claude/state -> issue_runner.py never ran here"
echo "--- the repo's own ledger checker on the forged line ---"
(cd "$B1" && python3 "$LEDGER_CHECK"); echo "LEDGER-CHECK EXIT=$?"
echo "--- the gate, WITH --head-sha (the strongest mode CI uses) ---"
(cd "$B1" && python3 "$GATE" --branch sana/ask-999 --head-sha "$HEAD_SHA")
echo "GATE EXIT=$?"

echo
echo "############ B2: correct closeout, then 'Update branch' from main ############"
B2="$W/b2"
mkdir -p "$B2/.prd-os/issues"
git -C "$B2" init -q -b main
git -C "$B2" config user.email t@k.invalid
git -C "$B2" config user.name kipi-test
printf '.claude/state/\n' > "$B2/.gitignore"
echo base > "$B2/base.txt"
cat > "$B2/.prd-os/issues/receipt-gate-e2e.md" <<'SPEC'
---
id: receipt-gate-e2e
title: e2e
status: in-progress
priority: p1
parent_prd: prd-e2e
allowed_files:
  - work.txt
required_checks:
  - "true"
---

<!-- generated-by: prd_split.py prd=prd-e2e finding=finding-1 at=2026-07-27T00:00:00Z -->

# e2e
SPEC
git -C "$B2" add -A; git -C "$B2" commit -qm base
git -C "$B2" checkout -q -b sana/ask-999
echo work > "$B2/work.txt"; git -C "$B2" add -A; git -C "$B2" commit -qm "work (ASK-999)"

for c in "load receipt-gate-e2e" "mark verified" "mark reviewed" "mark findings_triaged" "close"; do
  python3 "$RUNNER" --repo-root "$B2" $c >/dev/null 2>&1
done
git -C "$B2" add -A; git -C "$B2" commit -qm "closeout receipt (ASK-999)" >/dev/null
GOOD_HEAD="$(git -C "$B2" rev-parse HEAD)"
echo "--- gate right after a correct closeout ---"
(cd "$B2" && python3 "$GATE" --branch sana/ask-999 --head-sha "$GOOD_HEAD" 2>&1 | tail -2)
echo "GATE EXIT=$?"

# main moves (another PR landed), operator clicks "Update branch"
git -C "$B2" checkout -q main
echo "something unrelated landed on main" > "$B2/other.txt"
git -C "$B2" add -A; git -C "$B2" commit -qm "unrelated main commit"
git -C "$B2" checkout -q sana/ask-999
git -C "$B2" merge -q --no-edit main
MERGED_HEAD="$(git -C "$B2" rev-parse HEAD)"
echo "--- gate after merging main in (no new work by the agent) ---"
(cd "$B2" && python3 "$GATE" --branch sana/ask-999 --head-sha "$MERGED_HEAD")
echo "GATE EXIT=$?"
