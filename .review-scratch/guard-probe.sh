#!/usr/bin/env bash
# Does the prompt-only-enforcement guard flag the HEAD copy of the audit script,
# i.e. is what it just blocked pre-existing text my edit did not touch?
cd "$(dirname "${BASH_SOURCE[0]}")/.."
probe() {
  printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$1" \
    | python3 q-system/.q-system/scripts/prompt-only-enforcement-guard.py 2>&1
  echo "rc=$?"
}
echo "--- HEAD copy ---"
probe "$PWD/.review-scratch/head-audit-285-r7.py"
echo "--- working copy ---"
probe "$PWD/q-system/.q-system/scripts/instruction-budget-audit.py"
