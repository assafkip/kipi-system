#!/usr/bin/env bash
# ASK-136: .claude/rules/quick-plan.md carried an (ENFORCED) heading and named no
# executable anywhere in its 24 lines, so capability-map-gen.py graded the label
# prompt-only. Unlike its ASK-138 sibling this rule DOES have a deterministic half
# that a hook can hold -- the SHAPE of a written plan file -- so the fix is not only
# honest labelling: plan-lint.py has to be named by the rule AND actually wired.
#
# That second half is the whole point. ASK-140's sibling rules could take their
# wiring for granted because their scripts were already switched on in both settings
# files. plan-lint.py was not: it shipped as an engine with no switch (PR #236), and
# Codex flagged exactly that twice ("the linter is never wired into any hook"). A
# reproducer that only grepped the rule text would have gone green on that dead
# engine, which is the defect this file exists to make impossible.
#
# Three checks, each with a negative self-test against a mutated copy:
#   (a) the rule NAMES plan-lint.py and that file exists;
#   (b) every "(ENFORCED" heading in the rule names an executable inside its own
#       section, and that executable EXISTS in this repo (a plausible-but-fake
#       filename must not satisfy it, or the check degrades into "name any string
#       ending in .py");
#   (c) plan-lint.py is wired as a PostToolUse hook in BOTH .claude/settings.json
#       and settings-template.json. Parsed as JSON and walked to the hook command,
#       never grepped: a bare grep is satisfied by the name appearing in a comment,
#       in a different event, or in a key that is not a command, and each of those
#       is a dead switch that reads as a live one. Both files, because kipi update
#       rebuilds every instance's settings.json from the template alone -- one
#       without the other runs dead on one side (settings-template-sync-check.py).
#
# Not asserting the exec bit on plan-lint.py: it is invoked as `python3 <path>`, so
# chmod +x is not what makes it runnable. Asserting -x would be a check that passes
# or fails for a reason nobody depends on.
#
# Pairs with .claude/rules/quick-plan.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RULE="$ROOT/.claude/rules/quick-plan.md"
LINT_REL="q-system/.q-system/scripts/plan-lint.py"
LINT_NAME="plan-lint.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$RULE" ] || fail "rule file missing at $RULE"

# --- (a) the rule names its enforcing executable -----------------------------
# Factored so the negative self-test below runs the SAME function against a mutated
# copy and proves it can go red. A check that cannot fail is decoration.
rule_names_lint() {
  grep -qF "$LINT_NAME" "$1"
}

rule_names_lint "$RULE" \
  || fail "quick-plan.md claims ENFORCED but never names $LINT_NAME"

# --- (b) no ENFORCED heading without a REAL executable in its section --------
# Walks the file, tracks the current heading, and for every heading carrying
# "(ENFORCED" collects the *.py / *.sh basenames appearing in that section's body.
# A section passes only if at least one of those names resolves to a file that
# actually exists in this repo.
enforced_sections_without_executable() {
  local rule_file="$1" line heading="" enforced=0 satisfied=0 name
  emit() {
    [ "$enforced" -eq 1 ] && [ "$satisfied" -eq 0 ] && [ -n "$heading" ] \
      && printf '%s\n' "$heading"
    return 0
  }
  while IFS= read -r line; do
    case "$line" in
      '#'*' '*)
        emit
        heading="$line"
        case "$line" in *'(ENFORCED'*) enforced=1 ;; *) enforced=0 ;; esac
        satisfied=0
        continue
        ;;
    esac
    [ "$enforced" -eq 1 ] || continue
    for name in $(printf '%s\n' "$line" | grep -oE '[A-Za-z0-9_-]+\.(py|sh)' || true); do
      if [ -n "$(find "$ROOT" -name "$name" -not -path '*/.git/*' -print -quit)" ]; then
        satisfied=1
      fi
    done
  done < "$rule_file"
  emit
}

orphans="$(enforced_sections_without_executable "$RULE")"
[ -z "$orphans" ] || fail "ENFORCED heading(s) in quick-plan.md name no executable:
$orphans
Either name a real one in that section, or state the marker's scope honestly there."

# --- (c) the engine is actually SWITCHED ON, in both settings files ----------
# Walks hooks -> <event> -> [group] -> hooks -> [.command] and asks whether any
# PostToolUse command string invokes plan-lint.py. Reports the event it found the
# hook under so a miswired event fails loudly instead of silently.
lint_wired_in() {
  # $1 = settings file, $2 = script basename to look for
  python3 - "$1" "$2" <<'PY'
import json, sys
path, name = sys.argv[1], sys.argv[2]
try:
    with open(path) as fh:
        settings = json.load(fh)
except (OSError, ValueError) as exc:
    raise SystemExit("unreadable: %s" % exc)
for event, groups in (settings.get("hooks") or {}).items():
    if not isinstance(groups, list):
        continue
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if isinstance(hook, dict) and name in str(hook.get("command", "")):
                if event != "PostToolUse":
                    raise SystemExit("wired under %s, expected PostToolUse" % event)
                raise SystemExit(0)
raise SystemExit("no hook command invokes %s" % name)
PY
}

for settings_rel in ".claude/settings.json" "settings-template.json"; do
  [ -f "$ROOT/$settings_rel" ] || fail "$settings_rel missing"
  lint_wired_in "$ROOT/$settings_rel" "$LINT_NAME" \
    || fail "$LINT_NAME is named by quick-plan.md but NOT wired in $settings_rel -- the rule advertises a switch that is off, which is the prompt-only shape the label is supposed to have left behind"
done

[ -f "$ROOT/$LINT_REL" ] || fail "$LINT_NAME is named by the rule but missing at $LINT_REL"

# --- negative self-tests: every check above must go red on a mutated input ----
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

sed "s/$LINT_NAME//g" "$RULE" > "$TMPDIR_TEST/stripped.md"
if rule_names_lint "$TMPDIR_TEST/stripped.md"; then
  fail "negative self-test: rule_names_lint passed on a copy with the name stripped"
fi

cp "$RULE" "$TMPDIR_TEST/orphaned.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nNo executable is named in this section.\n' \
  >> "$TMPDIR_TEST/orphaned.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/orphaned.md")" ]; then
  fail "negative self-test: the ENFORCED-heading check passed on a copy carrying a scriptless ENFORCED section"
fi

cp "$RULE" "$TMPDIR_TEST/hallucinated.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nEnforced by `no-such-guard-ask136.py`.\n' \
  >> "$TMPDIR_TEST/hallucinated.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/hallucinated.md")" ]; then
  fail "negative self-test: a nonexistent script name satisfied the ENFORCED-heading check"
fi

# (c) must refuse a settings file with no such hook...
printf '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":"python3 other.py"}]}]}}\n' \
  > "$TMPDIR_TEST/no-hook.json"
if lint_wired_in "$TMPDIR_TEST/no-hook.json" "$LINT_NAME" 2>/dev/null; then
  fail "negative self-test: the wiring check passed on settings carrying no $LINT_NAME hook"
fi

# ...and must refuse the name appearing under the WRONG event, which is a dead
# switch that a grep-based check would have called wired.
printf '{"hooks":{"SessionStart":[{"matcher":"","hooks":[{"type":"command","command":"python3 plan-lint.py"}]}]}}\n' \
  > "$TMPDIR_TEST/wrong-event.json"
if lint_wired_in "$TMPDIR_TEST/wrong-event.json" "$LINT_NAME" 2>/dev/null; then
  fail "negative self-test: a $LINT_NAME hook under SessionStart satisfied the PostToolUse wiring check"
fi

# ...and must refuse the name sitting in a non-command key, the other dead switch
# a grep cannot tell from a live one.
printf '{"hooks":{"PostToolUse":[{"matcher":"plan-lint.py","hooks":[{"type":"command","command":"python3 other.py"}]}]}}\n' \
  > "$TMPDIR_TEST/matcher-only.json"
if lint_wired_in "$TMPDIR_TEST/matcher-only.json" "$LINT_NAME" 2>/dev/null; then
  fail "negative self-test: $LINT_NAME appearing only in a matcher satisfied the wiring check"
fi

echo "PASS: quick-plan.md names $LINT_NAME (exists), every ENFORCED heading names a real executable, and the hook is wired PostToolUse in .claude/settings.json AND settings-template.json"
