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

# (b) WIRED, which is not the same as "the filename appears in the file". The
# first version of this grepped `-F "scripts/<name>"` over the whole settings
# JSON, so a disabled entry, a leftover "_comment", or any prose mentioning the
# path counted as live wiring -- all three hooks could be no-ops with this test
# green (Codex on PR #48). So: parse the JSON and require the path inside an
# actual hooks[].command string, and take the settings file as an argument so the
# negative self-test below can run the SAME function against a mutated copy.
settings_wires_script() {
  local settings_file="$1" script="$2"
  python3 - "$settings_file" "$script" <<'PY'
import json, sys
settings_file, script = sys.argv[1], sys.argv[2]
needle = "scripts/" + script
try:
    data = json.load(open(settings_file))
except Exception as exc:
    print("unparseable settings JSON: %s" % exc, file=sys.stderr)
    sys.exit(2)
for matchers in (data.get("hooks") or {}).values():
    for matcher in matchers:
        for hook in matcher.get("hooks") or []:
            command = hook.get("command") or ""
            # A command that only mentions the path in a shell comment is not
            # wiring either; cut each line at its first '#'.
            live = "\n".join(line.split("#", 1)[0] for line in command.splitlines())
            if needle in live:
                sys.exit(0)
sys.exit(1)
PY
}

for script in "${SCRIPTS[@]}"; do
  script_path="$ROOT/q-system/.q-system/scripts/$script"
  # (c) the named executable is real and runnable
  [ -f "$script_path" ] || fail "$script is named by the rule but missing at $script_path"
  [ -x "$script_path" ] || fail "$script_path is not executable"
  # wired in the skeleton's own settings AND in the template every instance gets
  settings_wires_script "$ROOT/.claude/settings.json" "$script" \
    || fail ".claude/settings.json has no live hook command running $script"
  settings_wires_script "$ROOT/settings-template.json" "$script" \
    || fail "settings-template.json has no live hook command running $script (fleet would get a dead switch)"
done

# Negative self-test for (b): disable the voice-lint.py hook command in a COPY
# while LEAVING the literal path elsewhere in the file. The old grep passed this
# mutant; settings_wires_script has to reject it, or it is the same non-check
# wearing more code.
python3 - "$ROOT/.claude/settings.json" "$TMPDIR_TEST/mutant.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for matchers in (data.get("hooks") or {}).values():
    for matcher in matchers:
        for hook in matcher.get("hooks") or []:
            if "scripts/voice-lint.py" in (hook.get("command") or ""):
                hook["command"] = "true"
                # the path survives in the file, just not in any live command
                matcher["_disabled_note"] = "was q-system/.q-system/scripts/voice-lint.py"
json.dump(data, open(sys.argv[2], "w"), indent=2)
PY
grep -qF "scripts/voice-lint.py" "$TMPDIR_TEST/mutant.json" \
  || fail "negative self-test is not testing what it claims: the mutant lost the literal path"
if settings_wires_script "$TMPDIR_TEST/mutant.json" voice-lint.py; then
  fail "negative self-test: settings_wires_script passed a settings file whose voice-lint.py hook is disabled"
fi

echo "PASS: voice-enforcement.md names ${#SCRIPTS[@]} executables; each exists, is executable, and is wired in .claude/settings.json + settings-template.json"
