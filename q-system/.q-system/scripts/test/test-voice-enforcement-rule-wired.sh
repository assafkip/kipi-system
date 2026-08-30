#!/usr/bin/env bash
# ASK-140: .claude/rules/voice-enforcement.md says ENFORCED, so it has to name the
# executables that do the enforcing -- and each of those has to exist, be executable,
# and be wired in BOTH .claude/settings.json and settings-template.json. A rule that
# names no executable is prompt-only; a rule naming a script the fleet template never
# wires ships every instance a dead switch. Pairs with .claude/rules/voice-enforcement.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RULE="$ROOT/.claude/rules/voice-enforcement.md"
SCRIPTS=(voice-lint.py voice-substance-lint.py voice-stop-gate.py)
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$RULE" ] || fail "rule file missing at $RULE"

# (a) the rule names every enforcing executable. Factored into a function taking the
# file path so the negative self-test below can run the SAME check against a copy and
# prove it actually fails -- a check that cannot go red is not a check.
rule_names_scripts() {
  local rule_file="$1" script
  for script in "${SCRIPTS[@]}"; do
    grep -qF "$script" "$rule_file" || return 1
  done
  return 0
}

rule_names_scripts "$RULE" \
  || fail "voice-enforcement.md claims ENFORCED but does not name all of: ${SCRIPTS[*]}"

# Negative self-test: strip the names out of a COPY, the same check must go red.
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT
sed 's/voice-lint\.py//g; s/voice-substance-lint\.py//g; s/voice-stop-gate\.py//g' \
  "$RULE" > "$TMPDIR_TEST/stripped.md"
if rule_names_scripts "$TMPDIR_TEST/stripped.md"; then
  fail "negative self-test: rule_names_scripts passed on a copy with the names stripped"
fi

for script in "${SCRIPTS[@]}"; do
  script_path="$ROOT/q-system/.q-system/scripts/$script"
  # (c) the named executable is real and runnable
  [ -f "$script_path" ] || fail "$script is named by the rule but missing at $script_path"
  [ -x "$script_path" ] || fail "$script_path is not executable"
  # (b) wired in the skeleton's own settings AND in the template every instance gets
  grep -qF "scripts/$script" "$ROOT/.claude/settings.json" \
    || fail ".claude/settings.json does not wire $script"
  grep -qF "scripts/$script" "$ROOT/settings-template.json" \
    || fail "settings-template.json does not wire $script (fleet would get a dead switch)"
done

echo "PASS: voice-enforcement.md names ${#SCRIPTS[@]} executables; each exists, is executable, and is wired in .claude/settings.json + settings-template.json"
