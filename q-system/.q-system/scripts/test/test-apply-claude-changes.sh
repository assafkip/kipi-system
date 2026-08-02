#!/usr/bin/env bash
# Tests for apply-claude-changes: the safe path for landing .claude/ edits.
#
# Every case builds a THROWAWAY fixture root under mktemp and points the engine
# at it with --root. No case touches the repo's real .claude/ -- that is both the
# fable-discipline test-isolation rule and the whole point of the tool.
#
# The two mutation cases at the end are the reason to trust the rest: they copy
# the engine, break one specific guard in the copy, and prove the matching test
# goes RED. A guard never seen to fail is not a guard.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ENGINE="$SCRIPT_DIR/../apply_claude_changes.py"
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# check <name> <expected-exit> <expected-substring> <actual-exit> <actual-output>
check() {
  local name="$1" want_rc="$2" want_sub="$3" got_rc="$4" got_out="$5"
  if [ "$got_rc" != "$want_rc" ]; then
    bad "$name (exit $got_rc, wanted $want_rc) :: $got_out"; return
  fi
  case "$got_out" in
    *"$want_sub"*) ok "$name" ;;
    *) bad "$name (missing '$want_sub') :: $got_out" ;;
  esac
}

# Exactly one line of founder-facing output, in every outcome.
check_one_line() {
  local name="$1" out="$2"
  local n
  n=$(printf '%s\n' "$out" | grep -c '' || true)
  if [ "$n" = "1" ]; then ok "$name emits exactly 1 line"; else bad "$name emitted $n lines"; fi
}

mk_fixture() {  # mk_fixture <root>
  local r="$1"
  mkdir -p "$r/.claude/rules" "$r/.claude/agents" "$r/.claude/output-styles"
  mkdir -p "$r/q-system/.q-system/scripts" "$r/q-system/output"
  echo "# existing" > "$r/.claude/rules/coding-standards.md"
  echo "# agent" > "$r/.claude/agents/preflight.md"
  echo "print('lint')" > "$r/q-system/.q-system/scripts/existing-lint.py"
  cat > "$r/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "allow": [
      "Bash(ls:*)"
    ],
    "deny": [
      "Read(.env)"
    ],
    "defaultMode": "acceptEdits"
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/existing-lint.py\""
          }
        ]
      }
    ]
  }
}
JSON
  cat > "$r/settings-template.json" <<'JSON'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/existing-lint.py\""
          },
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/new-lint.py\""
          }
        ]
      }
    ]
  }
}
JSON
  cat > "$r/q-system/.q-system/capability-manifest.json" <<'JSON'
{ "schema_version": 1, "expected_tests": [ { "path": "a/b.py", "runner": "python3" } ] }
JSON
}

run_engine() {  # run_engine <engine> <proposal> <root>  -> sets RC and OUT
  set +e
  OUT=$("$1" "$2" --root "$3" 2>&1)
  RC=$?
  set -e
}

echo "=== apply-claude-changes ==="

# ---------------------------------------------------------------- 1. apply e2e
T=$(mktemp -d); mk_fixture "$T"
echo "print('new')" > "$T/q-system/.q-system/scripts/new-lint.py"
cat > "$T/p.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "add-new-lint",
  "reason": "wire the new lint",
  "requires": { "files_present": ["q-system/.q-system/scripts/new-lint.py"], "template_pairs": ["scripts/new-lint.py"] },
  "edits": [
    {
      "file": ".claude/settings.json",
      "op": "insert_after",
      "anchor": "            \"command\": \"python3 \\\"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/existing-lint.py\\\"\"\n          }",
      "insert": ",\n          {\n            \"type\": \"command\",\n            \"command\": \"python3 \\\"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/new-lint.py\\\"\"\n          }",
      "reason": "add the new lint hook entry"
    },
    {
      "file": ".claude/rules/coding-standards.md",
      "op": "append",
      "insert": "\n## Armed\nThe new lint is armed.\n",
      "reason": "document the arming"
    }
  ]
}
JSON
BEFORE_HOOKS=$(grep -c 'CLAUDE_PROJECT_DIR' "$T/.claude/settings.json")
run_engine "$ENGINE" "$T/p.json" "$T"
check "apply e2e succeeds" 0 "OK applied add-new-lint" "$RC" "$OUT"
check_one_line "apply e2e" "$OUT"
AFTER_HOOKS=$(grep -c 'CLAUDE_PROJECT_DIR' "$T/.claude/settings.json")
if [ "$BEFORE_HOOKS" = "1" ] && [ "$AFTER_HOOKS" = "2" ]; then
  ok "apply e2e before/after: hook commands 1 -> 2"
else bad "apply e2e hook count $BEFORE_HOOKS -> $AFTER_HOOKS (wanted 1 -> 2)"; fi
if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$T/.claude/settings.json" 2>/dev/null; then
  ok "apply e2e leaves valid JSON"
else bad "apply e2e produced invalid JSON"; fi
if grep -q "The new lint is armed." "$T/.claude/rules/coding-standards.md"; then
  ok "apply e2e appended to the rules file"
else bad "apply e2e did not append to the rules file"; fi
if ls "$T/q-system/output/claude-changes/.backups/" | grep -q "add-new-lint"; then
  ok "apply e2e wrote a backup"
else bad "apply e2e wrote no backup"; fi

# ------------------------------------------------------- 2. idempotent re-run
BEFORE_RERUN=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/p.json" "$T"
check "re-run is a no-op" 0 "OK already-applied" "$RC" "$OUT"
check_one_line "re-run" "$OUT"
AFTER_RERUN=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
if [ "$BEFORE_RERUN" = "$AFTER_RERUN" ]; then
  ok "re-run changed nothing"
else bad "re-run mutated the file"; fi
rm -r "$T"

# ------------------------------------------------------- 3. anchor mismatches
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/absent.json" <<'JSON'
{
  "schema_version": 1, "slug": "absent-anchor", "reason": "anchor will not match",
  "edits": [ { "file": ".claude/rules/coding-standards.md", "op": "insert_after",
               "anchor": "THIS TEXT DOES NOT EXIST", "insert": "x", "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/absent.json" "$T"
check "absent anchor refused" 2 "anchor not found" "$RC" "$OUT"
check "absent anchor is named" 2 "THIS TEXT DOES NOT EXIST" "$RC" "$OUT"
check_one_line "absent anchor" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')" ]; then
  ok "absent anchor wrote nothing"
else bad "absent anchor mutated the file"; fi

printf 'dup\ndup\n' > "$T/.claude/rules/dup.md"
cat > "$T/dup.json" <<'JSON'
{
  "schema_version": 1, "slug": "dup-anchor", "reason": "anchor matches twice",
  "edits": [ { "file": ".claude/rules/dup.md", "op": "insert_after",
               "anchor": "dup", "insert": "X", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/dup.json" "$T"
check "ambiguous anchor refused" 2 "must be exactly 1" "$RC" "$OUT"
if [ "$(cat "$T/.claude/rules/dup.md")" = "$(printf 'dup\ndup')" ]; then
  ok "ambiguous anchor wrote nothing"
else bad "ambiguous anchor mutated the file"; fi
rm -r "$T"

# ------------------------------------------------------ 4. outside .claude/
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/outside.json" <<'JSON'
{
  "schema_version": 1, "slug": "outside", "reason": "targets outside .claude",
  "edits": [ { "file": "q-system/CLAUDE.md", "op": "append", "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/outside.json" "$T"
check "outside .claude/ refused" 2 "outside .claude/" "$RC" "$OUT"
cat > "$T/escape.json" <<'JSON'
{
  "schema_version": 1, "slug": "escape", "reason": "traversal",
  "edits": [ { "file": ".claude/../q-system/CLAUDE.md", "op": "append", "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/escape.json" "$T"
check "traversal out of .claude/ refused" 2 "outside .claude/" "$RC" "$OUT"
rm -r "$T"

# ------------------------- 5. removal / disable is not expressible (no bypass)
T=$(mktemp -d); mk_fixture "$T"
for OP in replace delete remove overwrite; do
  cat > "$T/op.json" <<JSON
{
  "schema_version": 1, "slug": "op-$OP", "reason": "try to remove a hook",
  "edits": [ { "file": ".claude/settings.json", "op": "$OP",
               "insert": "x", "reason": "r" } ]
}
JSON
  run_engine "$ENGINE" "$T/op.json" "$T"
  check "op '$OP' refused as non-additive" 2 "is not additive" "$RC" "$OUT"
done

# The flag the old design would have used. It must not be a bypass; it must not
# even be a recognised key.
cat > "$T/flag.json" <<'JSON'
{
  "schema_version": 1, "slug": "flagged", "reason": "declare intent to disable",
  "disables_enforcement": true,
  "edits": [ { "file": ".claude/settings.json", "op": "append", "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/flag.json" "$T"
check "disables_enforcement key refused" 2 "unknown proposal key" "$RC" "$OUT"

set +e
OUT=$("$ENGINE" "$T/flag.json" --root "$T" --force 2>&1); RC=$?
set -e
check "--force is not a flag" 2 "unknown option --force" "$RC" "$OUT"
rm -r "$T"

# --------------------------------- 6. enforcement reduction caught by ratchet
# Textually additive: it only INSERTS " || true" after an existing hook command.
# Nothing is deleted, yet the hook is disabled. The ratchet is the only layer
# that can see this, because the old exact command string vanishes.
mk_disable_proposal() {  # mk_disable_proposal <root>
  # The insert lands INSIDE the JSON string, so the result is still valid JSON
  # and still one hook entry. Every other guard is satisfied; the ratchet is the
  # only layer that can object. That is what makes the mutation below meaningful:
  # an earlier version of this fixture inserted after the closing quote, so the
  # mutant was caught by the JSON-validity check and the ratchet was never tested.
  cat > "$1/disable.json" <<'JSON'
{
  "schema_version": 1, "slug": "sneaky-disable", "reason": "additive but disabling",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/settings.json", "op": "insert_after",
               "anchor": "existing-lint.py\\\"",
               "insert": " || true", "reason": "silently neuter the lint" } ]
}
JSON
}
T=$(mktemp -d); mk_fixture "$T"; mk_disable_proposal "$T"
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/disable.json" "$T"
check "enforcement reduction refused" 2 "enforcement ratchet" "$RC" "$OUT"
check_one_line "enforcement reduction" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "enforcement reduction wrote nothing"
else bad "enforcement reduction mutated settings.json"; fi
rm -r "$T"

# ------------------------------- 7. permissions.allow widening is refused
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/allow.json" <<'JSON'
{
  "schema_version": 1, "slug": "widen-allow", "reason": "widen permissions",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/settings.json", "op": "insert_after",
               "anchor": "      \"Bash(ls:*)\"",
               "insert": ",\n      \"Bash(:*)\"", "reason": "widen" } ]
}
JSON
run_engine "$ENGINE" "$T/allow.json" "$T"
check "permissions.allow widening refused" 2 "may not be changed" "$RC" "$OUT"
rm -r "$T"

# ------------------------------------- 8. both-or-neither template pairing
T=$(mktemp -d); mk_fixture "$T"
echo "print('x')" > "$T/q-system/.q-system/scripts/unpaired.py"
cat > "$T/unpaired.json" <<'JSON'
{
  "schema_version": 1, "slug": "unpaired", "reason": "runtime without template",
  "requires": { "template_pairs": ["scripts/unpaired.py"] },
  "edits": [ { "file": ".claude/rules/coding-standards.md", "op": "append",
               "insert": "x\n", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/unpaired.json" "$T"
check "unpaired template refused" 2 "does not carry" "$RC" "$OUT"
rm -r "$T"

# ------------------------------- 8b. settings/template both-or-neither
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/tpl-only.json" <<'JSON'
{
  "schema_version": 1, "slug": "tpl-only", "reason": "template without runtime",
  "edits": [ { "file": "settings-template.json", "op": "append", "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/tpl-only.json" "$T"
check "template without settings.json refused" 2 "edited without .claude/settings.json" "$RC" "$OUT"
cat > "$T/rt-only.json" <<'JSON'
{
  "schema_version": 1, "slug": "rt-only", "reason": "runtime without template",
  "edits": [ { "file": ".claude/settings.json", "op": "append", "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/rt-only.json" "$T"
check "settings.json without template pair refused" 2 "without the settings-template.json pair" "$RC" "$OUT"
rm -r "$T"

# --------------------------------------------- 9. gate break -> auto-revert
# Deliberately ships a proposal that applies cleanly and passes the ratchet, but
# wires a hook to a script that does not exist. hook-scripts-exist goes
# pass -> FAIL, so the write must be undone without anyone looking at it.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/break.json" <<'JSON'
{
  "schema_version": 1, "slug": "breaks-a-gate", "reason": "wires a missing script",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [
    {
      "file": ".claude/settings.json",
      "op": "insert_after",
      "anchor": "            \"command\": \"python3 \\\"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/existing-lint.py\\\"\"\n          }",
      "insert": ",\n          {\n            \"type\": \"command\",\n            \"command\": \"python3 \\\"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/does-not-exist.py\\\"\"\n          }",
      "reason": "hook a script that is not there"
    }
  ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/break.json" "$T"
check "gate break auto-reverts" 3 "REVERTED breaks-a-gate" "$RC" "$OUT"
check "revert names the gate" 3 "hook-scripts-exist" "$RC" "$OUT"
check_one_line "gate break" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "auto-revert restored the original file byte-for-byte"
else bad "auto-revert left the file modified"; fi
rm -r "$T"

# ============================ MUTATION =====================================
# Copy the engine, break ONE guard, prove the matching case goes red. Without
# this, a green suite only proves the tests run, not that the guards do anything.
mutate() {  # mutate <dest> <python-old> <python-new>
  python3 - "$ENGINE" "$1" "$2" "$3" <<'PY'
import sys
src, dest, old, new = sys.argv[1:5]
text = open(src).read()
assert text.count(old) == 1, "mutation anchor hit %d times" % text.count(old)
open(dest, "w").write(text.replace(old, new))
PY
}

echo "--- mutation: break the duplicate-anchor check ---"
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_anchor.py"
mutate "$MUT" "    if hits > 1:" "    if hits > 99:"
printf 'dup\ndup\n' > "$T/.claude/rules/dup.md"
cat > "$T/dup.json" <<'JSON'
{
  "schema_version": 1, "slug": "dup-anchor", "reason": "anchor matches twice",
  "edits": [ { "file": ".claude/rules/dup.md", "op": "insert_after",
               "anchor": "dup", "insert": "X", "reason": "r" } ]
}
JSON
set +e
MOUT=$(python3 "$MUT" "$T/dup.json" --root "$T" 2>&1); MRC=$?
set -e
if [ "$MRC" = "2" ]; then
  bad "MUTATION anchor: mutant still refused - the ambiguous-anchor test is not load-bearing"
else
  ok "MUTATION anchor: guard removed -> ambiguous anchor applied (rc=$MRC), test goes RED as required"
fi
rm -r "$T"

echo "--- mutation: disable the enforcement ratchet ---"
T=$(mktemp -d); mk_fixture "$T"; mk_disable_proposal "$T"
MUT="$T/mutant_ratchet.py"
mutate "$MUT" "        gone = before[key] - after.get(key, set())" "        gone = set()"
set +e
MOUT=$(python3 "$MUT" "$T/disable.json" --root "$T" 2>&1); MRC=$?
set -e
if [ "$MRC" = "2" ]; then
  bad "MUTATION ratchet: mutant still refused - the ratchet test is not load-bearing"
else
  ok "MUTATION ratchet: ratchet disabled -> silent hook-disable applied (rc=$MRC), test goes RED as required"
fi
if grep -q '|| true' "$T/.claude/settings.json"; then
  ok "MUTATION ratchet: confirmed the mutant really wrote the disabling text"
else bad "MUTATION ratchet: mutant did not write; mutation may be inert"; fi
rm -r "$T"

echo
echo "passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ]
