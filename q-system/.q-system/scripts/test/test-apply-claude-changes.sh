#!/usr/bin/env bash
# Tests for apply-claude-changes: the safe path for landing .claude/ edits.
#
# Every case builds a THROWAWAY fixture root under mktemp and points the engine
# at it with --root. No case touches the repo's real .claude/ -- that is both the
# fable-discipline test-isolation rule and the whole point of the tool.
#
# The four mutation cases at the end are the reason to trust the rest: they copy
# the engine, break one specific guard in the copy, and prove the matching test
# goes RED. A guard never seen to fail is not a guard.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# Ref hatch: point the suite at a pre-fix engine to watch a case fail.
#   git show <ref>:q-system/.q-system/scripts/apply_claude_changes.py > /tmp/old.py
#   APPLY_ENGINE=/tmp/old.py bash <this script>
# A regression case that has never been watched fail is not known to catch
# anything. The three round-1 MAJORs (settings.local.json, concurrent apply,
# partial write) were each confirmed red against 8c22e29 this way.
ENGINE="${APPLY_ENGINE:-$SCRIPT_DIR/../apply_claude_changes.py}"
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
  # A rule carrying both enforcement-bearing token classes the content census
  # counts: an (ENFORCED marker and a named executable. The last paragraph is
  # the false claim a `replace` has to be able to correct.
  cat > "$r/.claude/rules/enforced-rule.md" <<'MD'
# Sample Rule (ENFORCED)

The deterministic half is `existing-lint.py`, wired PostToolUse on Edit|Write.

This rule is enforced end to end and covers every path in the repo.
MD
  echo "print('lint')" > "$r/q-system/.q-system/scripts/existing-lint.py"
  # A rule carrying NEITHER token class the content census counts, plus the
  # frontmatter that decides whether it loads at all. 5 of this repo's 34 real
  # rules look exactly like this (security.md, content-output.md, ...), so it is
  # the shape a token-only census is blind to.
  cat > "$r/.claude/rules/advisory-rule.md" <<'MD'
---
description: Advisory guidance for generated output
paths:
  - "q-system/output/**"
---

# Advisory Rule

Never publish a number whose source is not in this repo.

Every claim traces to a file a reader can open.

Ambiguity is preserved with an explicit marker, never smoothed over.
MD
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
  # Invoked via python3, not the shebang: a ref-hatch engine pulled with
  # `git show` is not executable, and exit 126 would look like a real failure.
  OUT=$(python3 "$1" "$2" --root "$3" 2>&1)
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
for OP in delete remove overwrite; do
  cat > "$T/op.json" <<JSON
{
  "schema_version": 1, "slug": "op-$OP", "reason": "try to remove a hook",
  "edits": [ { "file": ".claude/settings.json", "op": "$OP",
               "insert": "x", "reason": "r" } ]
}
JSON
  run_engine "$ENGINE" "$T/op.json" "$T"
  check "op '$OP' refused as unknown" 2 "is not a permitted op" "$RC" "$OUT"
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
OUT=$(python3 "$ENGINE" "$T/flag.json" --root "$T" --force 2>&1); RC=$?
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

# ---------------------------- 10. settings.local.json is refused outright
# Round-1 review MAJOR: the allowlist accepted .claude/settings.local.json, so a
# proposal could widen permissions.allow there while permission_surface_check and
# the hook census both inspected .claude/settings.json and reported clean.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/.claude/settings.local.json" <<'JSON'
{ "permissions": { "allow": [ "Bash(ls:*)" ] } }
JSON
cat > "$T/local.json" <<'JSON'
{
  "schema_version": 1, "slug": "widen-via-local", "reason": "widen permissions via the local override",
  "edits": [ { "file": ".claude/settings.local.json", "op": "insert_after",
               "anchor": "\"Bash(ls:*)\"", "insert": ", \"Bash(:*)\"",
               "reason": "widen through the file nobody checks" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/settings.local.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/local.json" "$T"
check "settings.local.json refused" 2 "may not be edited through this path" "$RC" "$OUT"
check_one_line "settings.local.json" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.local.json" | awk '{print $1}')" ]; then
  ok "settings.local.json untouched"
else bad "settings.local.json was modified"; fi
rm -r "$T"

# ------------------------------- 11. concurrent applies do not both succeed
# Round-1 review MAJOR: two applies each read the same base and the second write
# silently discarded the first proposal, both reporting success.
T=$(mktemp -d); mk_fixture "$T"
echo "print('new')" > "$T/q-system/.q-system/scripts/new-lint.py"
mkdir -p "$T/q-system/output/claude-changes"
python3 - "$T" <<'PY' &
import fcntl, os, sys, time
d = os.path.join(sys.argv[1], "q-system", "output", "claude-changes")
os.makedirs(d, exist_ok=True)
f = open(os.path.join(d, ".apply.lock"), "w")
fcntl.flock(f.fileno(), fcntl.LOCK_EX)
time.sleep(8)
PY
LOCKER=$!
python3 -c "import time; time.sleep(1.5)"
cat > "$T/concurrent.json" <<'JSON'
{
  "schema_version": 1, "slug": "concurrent", "reason": "second writer",
  "edits": [ { "file": ".claude/rules/coding-standards.md", "op": "append",
               "insert": "second writer\n", "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/concurrent.json" "$T"
check "concurrent apply refused" 2 "another apply is already running" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')" ]; then
  ok "concurrent apply wrote nothing"
else bad "concurrent apply mutated the file"; fi
kill "$LOCKER" 2>/dev/null || true
wait "$LOCKER" 2>/dev/null || true
# lock is released on process exit, so the same proposal applies cleanly after
run_engine "$ENGINE" "$T/concurrent.json" "$T"
check "apply succeeds once the lock is free" 0 "OK applied concurrent" "$RC" "$OUT"
rm -r "$T"

# --------------------- 12. write failure mid-apply leaves NO partial config
# Round-1 review MAJOR: a write failure after the first target escaped uncaught
# and left a partially applied configuration. Files are written in sorted order,
# so .claude/rules/... lands before .claude/settings.json. Making the directory
# that holds settings.json read-only fails the SECOND write specifically.
T=$(mktemp -d); mk_fixture "$T"
echo "print('new')" > "$T/q-system/.q-system/scripts/new-lint.py"
cat > "$T/partial.json" <<'JSON'
{
  "schema_version": 1, "slug": "partial-write",
  "reason": "second write fails; first must be rolled back",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [
    { "file": ".claude/rules/coding-standards.md", "op": "append",
      "insert": "\nFIRST TARGET WRITTEN\n", "reason": "lands first" },
    { "file": ".claude/settings.json", "op": "insert_after",
      "anchor": "      \"Read(.env)\"", "insert": ",\n      \"Read(secret)\"",
      "reason": "lands second, into a read-only directory" }
  ]
}
JSON
RULES_SUM=$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')
SET_SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
chmod 555 "$T/.claude"
run_engine "$ENGINE" "$T/partial.json" "$T"
chmod 755 "$T/.claude"
check "write failure reverts" 3 "no partial apply" "$RC" "$OUT"
check_one_line "write failure" "$OUT"
if [ "$RULES_SUM" = "$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')" ]; then
  ok "first target rolled back byte-for-byte"
else bad "PARTIAL APPLY: first target kept its write"; fi
if [ "$SET_SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "second target unchanged"
else bad "second target was modified"; fi
if ls "$T/.claude"/*.claude-changes.tmp >/dev/null 2>&1; then
  bad "left a .claude-changes.tmp behind"
else ok "no temp files left behind"; fi
rm -r "$T"

# ------------- 13. a second SPELLING of settings.json cannot dodge the checks
# Round-2 review MAJOR: permission_surface_check was gated on a RAW staged key
# while touches_settings used normpath, so ".claude/./settings.json" wrote the
# real file with the permission surface check never firing. Same class as
# settings.local.json in round 1: a second spelling only one guard recognises.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/dotslash.json" <<'JSON'
{
  "schema_version": 1, "slug": "dotslash-widen",
  "reason": "widen permissions.allow via a ./ spelling",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/./settings.json", "op": "insert_after",
               "anchor": "      \"Bash(ls:*)\"",
               "insert": ",\n      \"Bash(:*)\"",
               "reason": "widen through a spelling only one reader normalizes" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/dotslash.json" "$T"
check "./ spelling cannot dodge the permission check" 2 "may not be changed" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "./ spelling wrote nothing"
else bad "./ spelling MUTATED settings.json"; fi

# Redundant-slash and trailing-segment spellings collapse to the same key.
cat > "$T/slashes.json" <<'JSON'
{
  "schema_version": 1, "slug": "slashes-widen", "reason": "widen via redundant slashes",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude//rules/../settings.json", "op": "insert_after",
               "anchor": "      \"Bash(ls:*)\"",
               "insert": ",\n      \"Bash(:*)\"", "reason": "widen" } ]
}
JSON
run_engine "$ENGINE" "$T/slashes.json" "$T"
check "redundant-slash spelling cannot dodge it either" 2 "may not be changed" "$RC" "$OUT"

# Case variant. On a case-insensitive filesystem (macOS default) this is the SAME
# file and inode identity must catch it; on a case-sensitive one it simply does
# not exist. Both outcomes are a refusal, which is the point.
cat > "$T/case.json" <<'JSON'
{
  "schema_version": 1, "slug": "case-widen", "reason": "widen via a case variant",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/SETTINGS.json", "op": "insert_after",
               "anchor": "      \"Bash(ls:*)\"",
               "insert": ",\n      \"Bash(:*)\"", "reason": "widen" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/case.json" "$T"
check "case-variant spelling refused" 2 "REFUSED" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "case-variant wrote nothing"
else bad "case-variant MUTATED settings.json"; fi

# settings.local.json under a case variant must still be refused by basename.
cat > "$T/.claude/settings.local.json" <<'JSON'
{ "permissions": { "allow": [ "Bash(ls:*)" ] } }
JSON
cat > "$T/localcase.json" <<'JSON'
{
  "schema_version": 1, "slug": "local-case", "reason": "local override, case variant",
  "edits": [ { "file": ".claude/Settings.Local.json", "op": "append",
               "insert": "x", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/localcase.json" "$T"
check "settings.local.json case variant refused" 2 "may not be edited through this path" "$RC" "$OUT"
rm -r "$T"

# ------------- 14. an arg-parse refusal never logs into a tree it was not aimed at
# Round-2 review MINOR: _ROOT was assigned after the argument loop, so refusals
# raised DURING parsing fell back to the real repo and appended apply.log there.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/ok.json" <<'JSON'
{
  "schema_version": 1, "slug": "argparse", "reason": "never reached",
  "edits": [ { "file": ".claude/rules/coding-standards.md", "op": "append",
               "insert": "x", "reason": "r" } ]
}
JSON
set +e
OUT=$(python3 "$ENGINE" "$T/ok.json" --root "$T" --force 2>&1); RC=$?
set -e
check "arg-parse refusal still refuses" 2 "unknown option --force" "$RC" "$OUT"
case "$OUT" in
  *"$T"*) ok "arg-parse refusal logged into the target tree, not the live repo" ;;
  *) bad "arg-parse refusal logged outside the target tree :: $OUT" ;;
esac
rm -r "$T"

# ---------------------------------------- 15. replace, pinned to rule text
# ASK-289. Additive-only meant a wrong sentence in a rule could only be BURIED,
# never corrected -- design-auto-invoke.md still carries a narrowing paragraph
# wedged ABOVE its own H1 because insert_before was the only expressible op.
# `replace` fixes that, and is safe only because the census now reads rule
# CONTENT (see the two ratchet cases below), not just the directory listing.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/fixclaim.json" <<'JSON'
{
  "schema_version": 1, "slug": "fix-false-claim",
  "reason": "correct an overbroad enforcement sentence",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "This rule is enforced end to end and covers every path in the repo.",
               "insert": "This rule is enforced on Edit|Write only; other paths are advisory.",
               "reason": "the old sentence claimed coverage the hook does not have" } ]
}
JSON
run_engine "$ENGINE" "$T/fixclaim.json" "$T"
check "replace on rule text succeeds" 0 "OK applied fix-false-claim" "$RC" "$OUT"
check_one_line "replace on rule text" "$OUT"
if grep -q "other paths are advisory" "$T/.claude/rules/enforced-rule.md"; then
  ok "replace wrote the corrected sentence"
else bad "replace did not write the corrected sentence"; fi
if grep -q "covers every path in the repo" "$T/.claude/rules/enforced-rule.md"; then
  bad "replace left the false claim in place (it was buried, not corrected)"
else ok "replace REMOVED the false claim, which no additive op could do"; fi
if grep -q "(ENFORCED)" "$T/.claude/rules/enforced-rule.md"; then
  ok "replace left the (ENFORCED) marker and the exec ref untouched"
else bad "replace collaterally dropped the (ENFORCED) marker"; fi

# Idempotent: the anchor is gone but the insert is present exactly once.
BEFORE_RERUN=$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/fixclaim.json" "$T"
check "replace re-run is a no-op" 0 "OK already-applied" "$RC" "$OUT"
if [ "$BEFORE_RERUN" = "$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')" ]; then
  ok "replace re-run changed nothing"
else bad "replace re-run mutated the file"; fi
rm -r "$T"

# 15b. the ratchet reads rule CONTENT: stripping (ENFORCED) is refused.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/demote.json" <<'JSON'
{
  "schema_version": 1, "slug": "demote-rule",
  "reason": "quietly downgrade a rule to advisory",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "# Sample Rule (ENFORCED)",
               "insert": "# Sample Rule", "reason": "drop the marker" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/demote.json" "$T"
check "stripping (ENFORCED) refused by the ratchet" 2 "enforcement ratchet" "$RC" "$OUT"
check_one_line "stripping (ENFORCED)" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')" ]; then
  ok "stripping (ENFORCED) wrote nothing"
else bad "stripping (ENFORCED) mutated the rule"; fi

# 15c. dropping the executable a rule routes readers to is the same class.
cat > "$T/unwire.json" <<'JSON'
{
  "schema_version": 1, "slug": "unwire-rule",
  "reason": "remove the pointer to the enforcer",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "The deterministic half is `existing-lint.py`, wired PostToolUse on Edit|Write.",
               "insert": "The deterministic half is a hook.", "reason": "drop the ref" } ]
}
JSON
run_engine "$ENGINE" "$T/unwire.json" "$T"
check "dropping an exec reference refused by the ratchet" 2 "enforcement ratchet" "$RC" "$OUT"
rm -r "$T"

# 15d. replace cannot reach the config surface. .claude/settings.json is named
# outright; the pair requirement is satisfied so the SCOPE check is what refuses.
mk_replace_settings() {  # mk_replace_settings <root>
  # Deliberately picks a swap NO other layer objects to: the census keys on the
  # command string (unchanged), the JSON stays valid, permissions do not move.
  # Only the rule-text scope check stands between this and a broken hook.
  cat > "$1/rep-settings.json" <<'JSON'
{
  "schema_version": 1, "slug": "replace-settings",
  "reason": "reach the config surface through the one non-additive op",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/settings.json", "op": "replace",
               "anchor": "\"type\": \"command\"", "insert": "\"type\": \"cmd\"",
               "reason": "silently break the hook type" } ]
}
JSON
}
T=$(mktemp -d); mk_fixture "$T"; mk_replace_settings "$T"
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/rep-settings.json" "$T"
check "replace on settings.json refused" 2 "replace may not target" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "replace on settings.json wrote nothing"
else bad "replace MUTATED settings.json"; fi

cat > "$T/rep-agent.json" <<'JSON'
{
  "schema_version": 1, "slug": "replace-agent", "reason": "reach an agent file",
  "edits": [ { "file": ".claude/agents/preflight.md", "op": "replace",
               "anchor": "# agent", "insert": "# other", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/rep-agent.json" "$T"
check "replace outside .claude/rules/ refused" 2 "only permitted on" "$RC" "$OUT"
rm -r "$T"

# 15e. a symlink parked in .claude/rules/ is a second name for a file the string
# scope check would wave through. Same class as settings.local.json (round 1)
# and the ./ spelling (round 2), arriving through the new op.
T=$(mktemp -d); mk_fixture "$T"
ln -s "../settings.json" "$T/.claude/rules/sneak.md"
cat > "$T/sneak.json" <<'JSON'
{
  "schema_version": 1, "slug": "sneak-settings",
  "reason": "reach settings.json through a symlink inside rules/",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/rules/sneak.md", "op": "replace",
               "anchor": "\"type\": \"command\"", "insert": "\"type\": \"cmd\"",
               "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')
run_engine "$ENGINE" "$T/sneak.json" "$T"
check "symlink-to-settings refused" 2 "replace may not target" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/settings.json" | awk '{print $1}')" ]; then
  ok "symlink-to-settings wrote nothing"
else bad "symlink-to-settings MUTATED settings.json"; fi

# A symlink out of rules/ that is NOT the settings pair: the realpath check is
# the only layer left, so this case is what makes that check load-bearing.
ln -s "../agents/preflight.md" "$T/.claude/rules/sneak2.md"
cat > "$T/sneak2.json" <<'JSON'
{
  "schema_version": 1, "slug": "sneak-agent",
  "reason": "reach an agent file through a symlink inside rules/",
  "edits": [ { "file": ".claude/rules/sneak2.md", "op": "replace",
               "anchor": "# agent", "insert": "# other", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/sneak2.json" "$T"
check "symlink out of rules/ refused" 2 "resolves outside" "$RC" "$OUT"
rm -r "$T"

# 15f. replace is not a delete: an empty insert is refused, so "remove this
# paragraph" stays inexpressible (the Not-doing line of ASK-289).
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/erase.json" <<'JSON'
{
  "schema_version": 1, "slug": "erase-para", "reason": "delete by replacing with nothing",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "This rule is enforced end to end and covers every path in the repo.",
               "insert": "", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/erase.json" "$T"
check "empty insert refused (no delete op)" 2 "must be a non-empty string" "$RC" "$OUT"

# Whitespace-only is the same delete wearing a hat.
cat > "$T/erase2.json" <<'JSON'
{
  "schema_version": 1, "slug": "erase-para-ws", "reason": "delete via whitespace",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "This rule is enforced end to end and covers every path in the repo.",
               "insert": "   ", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/erase2.json" "$T"
check "whitespace-only insert refused" 2 "must be a non-empty string" "$RC" "$OUT"

# 15g. anchor contained in the insert never converges: every run would find the
# anchor again and grow the file. Refused, with the additive op named instead.
cat > "$T/grow.json" <<'JSON'
{
  "schema_version": 1, "slug": "grow-forever", "reason": "anchor survives its own replacement",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "# Sample Rule (ENFORCED)",
               "insert": "# Sample Rule (ENFORCED) and then some", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/grow.json" "$T"
check "non-converging replace refused" 2 "never converges" "$RC" "$OUT"

# 15h. anchor arithmetic is the same as for the insert ops.
printf 'dup\ndup\n' > "$T/.claude/rules/dup.md"
cat > "$T/repdup.json" <<'JSON'
{
  "schema_version": 1, "slug": "rep-dup", "reason": "anchor matches twice",
  "edits": [ { "file": ".claude/rules/dup.md", "op": "replace",
               "anchor": "dup", "insert": "X", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/repdup.json" "$T"
check "ambiguous replace anchor refused" 2 "must be exactly 1" "$RC" "$OUT"
cat > "$T/repabs.json" <<'JSON'
{
  "schema_version": 1, "slug": "rep-absent", "reason": "anchor is not there",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "NO SUCH TEXT ANYWHERE", "insert": "X", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/repabs.json" "$T"
check "absent replace anchor refused" 2 "anchor not found" "$RC" "$OUT"
rm -r "$T"

# 15i. gutting a rule that carries NO enforcement tokens (PR #70 round 3, major).
# A token-only census reports rule_marks unchanged while the whole body goes,
# because a rule with no (ENFORCED marker and no named script has nothing to
# count. The body-line floor is the layer that has to refuse this.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/gut.json" <<'JSON'
{
  "schema_version": 1, "slug": "gut-advisory",
  "reason": "swap an entire rule body for one sentence",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "Never publish a number whose source is not in this repo.\n\nEvery claim traces to a file a reader can open.\n\nAmbiguity is preserved with an explicit marker, never smoothed over.",
               "insert": "Use your judgement.", "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/advisory-rule.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/gut.json" "$T"
check "gutting a zero-token rule refused" 2 "enforcement ratchet" "$RC" "$OUT"
check_one_line "gutting a zero-token rule" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/advisory-rule.md" | awk '{print $1}')" ]; then
  ok "gutting a zero-token rule wrote nothing"
else bad "gutting a zero-token rule REMOVED the body"; fi

# Rewording at the same body length stays allowed -- that is the correction this
# op exists for, and a floor that refused it would refuse the whole feature.
cat > "$T/reword.json" <<'JSON'
{
  "schema_version": 1, "slug": "reword-advisory",
  "reason": "correct one sentence without shortening the rule",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "Never publish a number whose source is not in this repo.",
               "insert": "Never publish a number whose source is not a file in this repo.",
               "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/reword.json" "$T"
check "same-length reword still succeeds" 0 "OK applied reword-advisory" "$RC" "$OUT"
rm -r "$T"

# 15j. narrowing frontmatter so the rule never loads (PR #70 round 3, major).
# Same body, same tokens, same line count -- every content check sees no change,
# and the rule is dead because its paths: no longer match anything.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/unload.json" <<'JSON'
{
  "schema_version": 1, "slug": "unload-rule",
  "reason": "narrow the scoping key so the rule stops loading",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "  - \"q-system/output/**\"",
               "insert": "  - \"q-system/output/__never__/**\"", "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/advisory-rule.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/unload.json" "$T"
check "narrowing frontmatter refused" 2 "frontmatter" "$RC" "$OUT"
check_one_line "narrowing frontmatter" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/advisory-rule.md" | awk '{print $1}')" ]; then
  ok "narrowing frontmatter wrote nothing"
else bad "narrowing frontmatter MUTATED the scoping key"; fi

# The body of a rule that HAS frontmatter is still reachable; the refusal above
# is about the frontmatter block, not about the file carrying one.
cat > "$T/body-ok.json" <<'JSON'
{
  "schema_version": 1, "slug": "fix-body",
  "reason": "correct body text in a rule that has frontmatter",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "Every claim traces to a file a reader can open.",
               "insert": "Every claim traces to a file any reader can open.", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/body-ok.json" "$T"
check "body of a frontmattered rule still editable" 0 "OK applied fix-body" "$RC" "$OUT"
rm -r "$T"

# 15k. renaming a rule's enforcer to a dead name (PR #70 round 3, minor).
# `existing-lint.py.retired` still CONTAINS `existing-lint.py`, so an exec-ref
# pattern with no trailing boundary reports the mark intact while the reader's
# route to the enforcer is dead.
T=$(mktemp -d); mk_fixture "$T"
cat > "$T/retire.json" <<'JSON'
{
  "schema_version": 1, "slug": "retire-enforcer",
  "reason": "point the rule at a name that does not run",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "The deterministic half is `existing-lint.py`, wired PostToolUse on Edit|Write.",
               "insert": "The deterministic half was `existing-lint.py.retired`, now unwired.",
               "reason": "r" } ]
}
JSON
SUM=$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')
run_engine "$ENGINE" "$T/retire.json" "$T"
check "renaming the enforcer to a dead name refused" 2 "enforcement ratchet" "$RC" "$OUT"
if [ "$SUM" = "$(shasum -a 256 "$T/.claude/rules/enforced-rule.md" | awk '{print $1}')" ]; then
  ok "renaming the enforcer wrote nothing"
else bad "renaming the enforcer left a dead pointer in the rule"; fi

# A ref at the end of a sentence is still a ref: the boundary must reject a
# LONGER filename, not a following period. Otherwise every "see foo.py." line in
# the real rules silently stops being a census member.
printf -- '---\ndescription: d\n---\n\n# Sentence End (ENFORCED)\n\nThe gate is q-system/.q-system/scripts/existing-lint.py.\n\nIt runs on write.\n' \
  > "$T/.claude/rules/sentence-end.md"
cat > "$T/sentence.json" <<'JSON'
{
  "schema_version": 1, "slug": "drop-sentence-end-ref",
  "reason": "drop a ref that sat at the end of a sentence",
  "edits": [ { "file": ".claude/rules/sentence-end.md", "op": "replace",
               "anchor": "The gate is q-system/.q-system/scripts/existing-lint.py.",
               "insert": "The gate is somewhere in the repo, look for it.", "reason": "r" } ]
}
JSON
run_engine "$ENGINE" "$T/sentence.json" "$T"
check "a ref ending a sentence is still a census member" 2 "enforcement ratchet" "$RC" "$OUT"
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

echo "--- mutation: remove the write-failure rollback ---"
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_partial.py"
mutate "$MUT" "        restore(root, backup_dir, sorted(staged))" "        pass"
cat > "$T/partial.json" <<'JSON'
{
  "schema_version": 1, "slug": "partial-write",
  "reason": "second write fails; first must be rolled back",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [
    { "file": ".claude/rules/coding-standards.md", "op": "append",
      "insert": "\nFIRST TARGET WRITTEN\n", "reason": "lands first" },
    { "file": ".claude/settings.json", "op": "insert_after",
      "anchor": "      \"Read(.env)\"", "insert": ",\n      \"Read(secret)\"",
      "reason": "lands second, into a read-only directory" }
  ]
}
JSON
RULES_SUM=$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')
chmod 555 "$T/.claude"
set +e
python3 "$MUT" "$T/partial.json" --root "$T" >/dev/null 2>&1
set -e
chmod 755 "$T/.claude"
if [ "$RULES_SUM" = "$(shasum -a 256 "$T/.claude/rules/coding-standards.md" | awk '{print $1}')" ]; then
  bad "MUTATION partial: rollback removed but first target still clean - test not load-bearing"
else
  ok "MUTATION partial: rollback removed -> first target kept its write (partial apply), test goes RED as required"
fi
rm -r "$T"

echo
echo "--- mutation: restore the two-reader path defect ---"
# The ./ bypass is now closed TWICE over, and that was measured, not assumed:
# removing the boundary normalization alone does NOT reopen it (inode identity
# still resolves the key), and reverting identity to a string compare alone does
# not either (the boundary already canonicalized the spelling). The original
# round-2 defect needed BOTH readers to disagree, so the mutation restores both.
mutate2() {  # mutate2 <dest> <old1> <new1> <old2> <new2>
  python3 - "$ENGINE" "$@" <<'PY'
import sys, ast
src, dest = sys.argv[1], sys.argv[2]
pairs = list(zip(sys.argv[3::2], sys.argv[4::2]))
text = open(src).read()
for old, new in pairs:
    assert text.count(old) == 1, "mutation anchor hit %d times: %s" % (text.count(old), old[:60])
    text = text.replace(old, new)
assert text.strip(), "mutant is empty"
ast.parse(text)          # a mutant that does not parse reports a FALSE kill
assert text != open(src).read(), "mutant is identical to the original"
open(dest, "w").write(text)
PY
}
echo "--- mutation: blind the body-line floor ---"
# Stop emitting line marks and a rule with no enforcement tokens is defenceless
# again: the whole body goes and the ratchet reports nothing missing.
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_lines.py"
mutate "$MUT" "            line_marks.add(\"%s|line|%d\" % (name, index))" "            pass"
cat > "$T/gut.json" <<'JSON'
{
  "schema_version": 1, "slug": "gut-advisory", "reason": "swap a whole rule body",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "Never publish a number whose source is not in this repo.\n\nEvery claim traces to a file a reader can open.\n\nAmbiguity is preserved with an explicit marker, never smoothed over.",
               "insert": "Use your judgement.", "reason": "r" } ]
}
JSON
set +e
MOUT=$(python3 "$MUT" "$T/gut.json" --root "$T" 2>&1); MRC=$?
set -e
if grep -q "Never publish a number" "$T/.claude/rules/advisory-rule.md"; then
  bad "MUTATION lines: mutant did not gut the rule - the body-floor test is not load-bearing"
else
  ok "MUTATION lines: floor blinded -> a zero-token rule's whole body vanished (rc=$MRC), test goes RED as required"
fi
rm -r "$T"

echo "--- mutation: drop the frontmatter pin ---"
# Without it, the scoping key narrows, the rule stops loading, and every content
# check reports clean because the body never moved.
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_fm.py"
mutate "$MUT" "        if _frontmatter(new) != _frontmatter(content):" "        if False:"
cat > "$T/unload.json" <<'JSON'
{
  "schema_version": 1, "slug": "unload-rule", "reason": "narrow the scoping key",
  "edits": [ { "file": ".claude/rules/advisory-rule.md", "op": "replace",
               "anchor": "  - \"q-system/output/**\"",
               "insert": "  - \"q-system/output/__never__/**\"", "reason": "r" } ]
}
JSON
set +e
MOUT=$(python3 "$MUT" "$T/unload.json" --root "$T" 2>&1); MRC=$?
set -e
if grep -q "__never__" "$T/.claude/rules/advisory-rule.md"; then
  ok "MUTATION frontmatter: pin dropped -> the rule was switched off via paths: (rc=$MRC), test goes RED as required"
else
  bad "MUTATION frontmatter: mutant did not narrow paths: - the frontmatter test is not load-bearing"
fi
rm -r "$T"

echo "--- mutation: restore the unbounded exec-ref pattern ---"
# The prefix match is the whole defect: `existing-lint.py.retired` contains
# `existing-lint.py`, so the census sees a mark that no longer points anywhere.
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_ref.py"
mutate "$MUT" '(?:py|sh)(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9_])' '(?:py|sh)'
cat > "$T/retire.json" <<'JSON'
{
  "schema_version": 1, "slug": "retire-enforcer", "reason": "point at a dead name",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "The deterministic half is `existing-lint.py`, wired PostToolUse on Edit|Write.",
               "insert": "The deterministic half was `existing-lint.py.retired`, now unwired.",
               "reason": "r" } ]
}
JSON
set +e
MOUT=$(python3 "$MUT" "$T/retire.json" --root "$T" 2>&1); MRC=$?
set -e
if grep -q "existing-lint.py.retired" "$T/.claude/rules/enforced-rule.md"; then
  ok "MUTATION execref: boundary removed -> the rule now points at a name that does not run (rc=$MRC), test goes RED as required"
else
  bad "MUTATION execref: mutant did not write the dead pointer - the boundary test is not load-bearing"
fi
rm -r "$T"

T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_norm.py"
mutate2 "$MUT" \
  '        edit["file"] = canonical_rel(edit["file"])' '        pass' \
  '        return os.path.exists(p) and os.path.exists(target) and os.path.samefile(p, target)' \
  '        return rel == os.path.relpath(target, root)'
cat > "$T/dotslash.json" <<'JSON'
{
  "schema_version": 1, "slug": "dotslash-widen",
  "reason": "widen permissions.allow via a ./ spelling",
  "requires": { "template_pairs": ["existing-lint.py"] },
  "edits": [ { "file": ".claude/./settings.json", "op": "insert_after",
               "anchor": "      \"Bash(ls:*)\"",
               "insert": ",\n      \"Bash(:*)\"", "reason": "widen" } ]
}
JSON
set +e
python3 "$MUT" "$T/dotslash.json" --root "$T" >/dev/null 2>&1; MRC=$?
set -e
if grep -q 'Bash(:\*)' "$T/.claude/settings.json"; then
  ok "MUTATION normalize: both readers restored -> ./ spelling widened permissions.allow (rc=$MRC), test goes RED as required"
else
  bad "MUTATION normalize: mutant did not widen permissions - the ./ test is not load-bearing"
fi
rm -r "$T"

echo
echo "--- mutation: blind the rule-content census ---"
# Before ASK-289 the rule census was a directory listing, so it could not see
# anything a replace did INSIDE a file. Putting that blindness back must let the
# quiet demotion through, or case 15b is decoration.
T=$(mktemp -d); mk_fixture "$T"
MUT="$T/mutant_marks.py"
mutate "$MUT" '        if "(ENFORCED" in text:' '        if False:'
cat > "$T/demote.json" <<'JSON'
{
  "schema_version": 1, "slug": "demote-rule", "reason": "quietly downgrade a rule",
  "edits": [ { "file": ".claude/rules/enforced-rule.md", "op": "replace",
               "anchor": "# Sample Rule (ENFORCED)",
               "insert": "# Sample Rule", "reason": "drop the marker" } ]
}
JSON
set +e
python3 "$MUT" "$T/demote.json" --root "$T" >/dev/null 2>&1; MRC=$?
set -e
if grep -q "(ENFORCED)" "$T/.claude/rules/enforced-rule.md"; then
  bad "MUTATION marks: census blinded but the demotion was still refused - case 15b is not load-bearing"
else
  ok "MUTATION marks: census blinded -> (ENFORCED) silently stripped (rc=$MRC), test goes RED as required"
fi
rm -r "$T"

echo
echo "--- mutation: remove the rule-text scope pin on replace ---"
T=$(mktemp -d); mk_fixture "$T"; mk_replace_settings "$T"
MUT="$T/mutant_scope.py"
mutate "$MUT" '            rule_text_only(root, rel, settings_key, template_key)' '            pass'
set +e
python3 "$MUT" "$T/rep-settings.json" --root "$T" >/dev/null 2>&1; MRC=$?
set -e
if grep -q '"type": "cmd"' "$T/.claude/settings.json"; then
  ok "MUTATION scope: pin removed -> replace reached settings.json and broke a hook (rc=$MRC), test goes RED as required"
else
  bad "MUTATION scope: pin removed but settings.json is untouched - case 15d is not load-bearing"
fi
rm -r "$T"

echo
echo "passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ]
