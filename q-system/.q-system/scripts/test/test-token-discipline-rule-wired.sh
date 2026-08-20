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
#       section. A section that cannot name one is ADVISORY and must say so.
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

# --- (b) no ENFORCED heading without an executable in its section ------------
# Splits the file on markdown headings, keeps the sections whose heading says
# ENFORCED, and demands a *.py / *.sh filename somewhere in that section's body.
# This is the check the two prompt-only subsections failed.
enforced_sections_without_executable() {
  awk '
    /^#{1,6} / {
      if (heading != "" && enforced && !named) print heading
      heading = $0
      enforced = (index(toupper($0), "(ENFORCED)") > 0)
      named = 0
      next
    }
    { if ($0 ~ /[A-Za-z0-9_-]+\.(py|sh)/) named = 1 }
    END { if (heading != "" && enforced && !named) print heading }
  ' "$1"
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
