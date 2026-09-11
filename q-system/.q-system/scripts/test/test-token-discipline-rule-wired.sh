#!/usr/bin/env bash
# ASK-139: .claude/rules/token-discipline.md carried three ENFORCED-shaped claims and
# named no executable anywhere in the file. Its Layer-1 blocks ARE real (token-guard.py,
# wired on three events in both settings files), but two subsections -- the
# Cleanup/Migration two-grep-pass and Pre-Action Echo -- claimed ENFORCED with nothing
# behind them. `grep -n -i "pre-action\|two grep\|pass 2" token-guard.py` returned
# nothing while every token-guard test stayed green: green and blind.
#
# This test pins both halves so the file cannot drift back:
#   (a) the rule NAMES its enforcing executable, and that file exists and is wired in
#       BOTH .claude/settings.json and settings-template.json (a script the fleet
#       template never wires ships every instance a dead switch);
#   (b) every "(ENFORCED)" heading in the rule names an executable inside its own
#       section, and that executable EXISTS in this repo. A section that cannot name
#       a real one has to state its scope honestly instead.
#
# (b) demands existence, not just a filename, because "name any plausible script" is
# a check a hallucinated path would pass. The engine that lands .claude/ edits
# (apply_claude_changes.py) refuses to let an agent delete an (ENFORCED marker at all
# -- "demoting a rule to advisory is enforcement-weakening whether or not the prose is
# honest" -- so the sanctioned repair is to correct the SCOPE under the marker, which
# is what this check measures.
#
# Pairs with .claude/rules/token-discipline.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RULE="$ROOT/.claude/rules/token-discipline.md"
GUARD_REL="q-system/.q-system/token-guard.py"
GUARD_NAME="token-guard.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$RULE" ] || fail "rule file missing at $RULE"

# --- (a) the rule names its enforcing executable -----------------------------
# Factored so the negative self-test below runs the SAME check against a copy and
# proves it can go red. A check that cannot fail is decoration.
rule_names_guard() {
  grep -qF "$GUARD_NAME" "$1"
}

rule_names_guard "$RULE" \
  || fail "token-discipline.md claims ENFORCED but never names $GUARD_NAME"

# --- (b) no ENFORCED heading without a REAL executable in its section --------
# Walks the file, tracks the current heading, and for every heading carrying
# "(ENFORCED" collects the *.py / *.sh basenames appearing in that section's body.
# A section passes only if at least one of those names resolves to a file that
# actually exists in this repo. This is the check the two prompt-only subsections
# failed: they named nothing at all.
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
    # Any basename ending .py/.sh on this line; satisfied once one of them is real.
    for name in $(printf '%s\n' "$line" | grep -oE '[A-Za-z0-9_-]+\.(py|sh)' || true); do
      if [ -n "$(find "$ROOT" -name "$name" -not -path '*/.git/*' -print -quit)" ]; then
        satisfied=1
      fi
    done
  done < "$rule_file"
  emit
}

orphans="$(enforced_sections_without_executable "$RULE")"
[ -z "$orphans" ] || fail "ENFORCED heading(s) in token-discipline.md name no executable:
$orphans
Either wire one and name it, or relabel the section ADVISORY."

# --- negative self-tests: both checks must go red on a mutated copy ----------
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

sed "s/$GUARD_NAME//g" "$RULE" > "$TMPDIR_TEST/stripped.md"
if rule_names_guard "$TMPDIR_TEST/stripped.md"; then
  fail "negative self-test: rule_names_guard passed on a copy with the name stripped"
fi

cp "$RULE" "$TMPDIR_TEST/orphaned.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nNo executable is named in this section.\n' \
  >> "$TMPDIR_TEST/orphaned.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/orphaned.md")" ]; then
  fail "negative self-test: the ENFORCED-heading check passed on a copy carrying a scriptless ENFORCED section"
fi

# ...and a plausible-but-nonexistent filename must NOT satisfy it, or the check
# degrades into "name any string ending in .py".
cp "$RULE" "$TMPDIR_TEST/hallucinated.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nEnforced by `no-such-guard-ask139.py`.\n' \
  >> "$TMPDIR_TEST/hallucinated.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/hallucinated.md")" ]; then
  fail "negative self-test: a nonexistent script name satisfied the ENFORCED-heading check"
fi

# --- the named executable is real and wired ----------------------------------
# Not asserting the exec bit: both settings entries invoke it as `python3 <path>`,
# so chmod +x is not what makes this wiring live. Asserting -x here would be a
# check that passes or fails for a reason nobody depends on.
[ -f "$ROOT/$GUARD_REL" ] || fail "$GUARD_NAME is named by the rule but missing at $GUARD_REL"

grep -qF "$GUARD_REL" "$ROOT/.claude/settings.json" \
  || fail ".claude/settings.json does not wire $GUARD_NAME"
grep -qF "$GUARD_REL" "$ROOT/settings-template.json" \
  || fail "settings-template.json does not wire $GUARD_NAME (fleet would get a dead switch)"

echo "PASS: token-discipline.md names $GUARD_NAME (exists, wired in .claude/settings.json + settings-template.json) and every ENFORCED heading names an executable"
