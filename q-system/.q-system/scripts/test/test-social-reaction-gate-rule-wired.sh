#!/usr/bin/env bash
# ASK-138: .claude/rules/social-reaction-gate.md carried an (ENFORCED) heading and named
# no executable anywhere in its 18 lines, so the label was prompt-only. Unlike its
# siblings there is no hook to point at and there never can be: a reaction is chat
# output with no file artifact for a PostToolUse hook to inspect, and whether the gate
# FIRES is a model decision, which per skill-hook-pairing.md is the judgment half.
#
# So the executable behind the label is not a blocker, it is a MEASUREMENT
# (skill-trigger-eval.py + a fixture) plus this test pinning the labelling. That makes
# the honest-scope claim the thing under test, which is the same contract
# test-token-discipline-rule-wired.sh holds for its rule.
#
# Three checks, each with a negative self-test against a mutated copy:
#   (a) the rule NAMES its measuring executable and that file exists;
#   (b) every "(ENFORCED" heading in the rule names an executable inside its own
#       section, and that executable EXISTS in this repo (a plausible-but-fake
#       filename must not satisfy it, or the check degrades into "name any string
#       ending in .py");
#   (c) the fixture the rule points at exists and LOADS under skill-trigger-eval.py's
#       own loader -- not a hand-rolled JSON check here, because a second reader of the
#       same file is a second spelling of the contract and they drift apart.
#
# Not asserting the exec bit on skill-trigger-eval.py: it is invoked as
# `python3 <path>`, so chmod +x is not what makes it runnable. Asserting -x would be a
# check that passes or fails for a reason nobody depends on.
#
# Pairs with .claude/rules/social-reaction-gate.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RULE="$ROOT/.claude/rules/social-reaction-gate.md"
EVAL_REL="q-system/.q-system/scripts/skill-trigger-eval.py"
EVAL_NAME="skill-trigger-eval.py"
FIXTURE_REL="q-system/.q-system/skill-evals/social-reaction-gate.json"
fail() { echo "FAIL: $1" >&2; exit 1; }

[ -f "$RULE" ] || fail "rule file missing at $RULE"

# --- (a) the rule names its measuring executable -----------------------------
# Factored so the negative self-test below runs the SAME function against a mutated
# copy and proves it can go red. A check that cannot fail is decoration.
rule_names_eval() {
  grep -qF "$EVAL_NAME" "$1"
}

rule_names_eval "$RULE" \
  || fail "social-reaction-gate.md claims ENFORCED but never names $EVAL_NAME"

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
[ -z "$orphans" ] || fail "ENFORCED heading(s) in social-reaction-gate.md name no executable:
$orphans
Either name a real one in that section, or state the marker's scope honestly there."

# --- negative self-tests: (a) and (b) must go red on a mutated copy ----------
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

sed "s/$EVAL_NAME//g" "$RULE" > "$TMPDIR_TEST/stripped.md"
if rule_names_eval "$TMPDIR_TEST/stripped.md"; then
  fail "negative self-test: rule_names_eval passed on a copy with the name stripped"
fi

cp "$RULE" "$TMPDIR_TEST/orphaned.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nNo executable is named in this section.\n' \
  >> "$TMPDIR_TEST/orphaned.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/orphaned.md")" ]; then
  fail "negative self-test: the ENFORCED-heading check passed on a copy carrying a scriptless ENFORCED section"
fi

cp "$RULE" "$TMPDIR_TEST/hallucinated.md"
printf '\n## Synthetic Claim (ENFORCED)\n\nEnforced by `no-such-guard-ask138.py`.\n' \
  >> "$TMPDIR_TEST/hallucinated.md"
if [ -z "$(enforced_sections_without_executable "$TMPDIR_TEST/hallucinated.md")" ]; then
  fail "negative self-test: a nonexistent script name satisfied the ENFORCED-heading check"
fi

# --- (c) the fixture exists and loads under the harness's OWN loader ---------
[ -f "$ROOT/$EVAL_REL" ] || fail "$EVAL_NAME is named by the rule but missing at $EVAL_REL"
[ -f "$ROOT/$FIXTURE_REL" ] || fail "fixture missing at $FIXTURE_REL (the rule's measurement has nothing to run)"

load_fixture_via_harness() {
  # $1 = SKILL_EVAL_DIR. Imports skill-trigger-eval.py and calls its load_fixture, so
  # the shape contract is read from the one place that defines it.
  SKILL_EVAL_DIR="$1" python3 - "$ROOT/$EVAL_REL" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ste", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
fx = mod.load_fixture("social-reaction-gate")
if not any(c["should_trigger"] for c in fx["cases"]):
    raise SystemExit("fixture has no should_trigger=true case")
if not any(not c["should_trigger"] for c in fx["cases"]):
    raise SystemExit("fixture has no should_trigger=false case; a set of all-positives cannot measure a false positive")
PY
}

load_fixture_via_harness "$ROOT/q-system/.q-system/skill-evals" \
  || fail "$FIXTURE_REL does not load under skill-trigger-eval.py's own loader"

# negative self-test for (c): a fixture missing 'cases' must be refused.
mkdir -p "$TMPDIR_TEST/evals"
printf '{"skill":"social-reaction-gate","cases":[]}\n' > "$TMPDIR_TEST/evals/social-reaction-gate.json"
if load_fixture_via_harness "$TMPDIR_TEST/evals" 2>/dev/null; then
  fail "negative self-test: an empty-cases fixture loaded"
fi

# ...and an all-positive fixture must be refused too, or (c) only checks JSON syntax.
printf '{"skill":"social-reaction-gate","cases":[{"prompt":"p","should_trigger":true}]}\n' \
  > "$TMPDIR_TEST/evals/social-reaction-gate.json"
if load_fixture_via_harness "$TMPDIR_TEST/evals" 2>/dev/null; then
  fail "negative self-test: an all-positive fixture satisfied the both-polarities check"
fi

echo "PASS: social-reaction-gate.md names $EVAL_NAME (exists), every ENFORCED heading names a real executable, and $FIXTURE_REL loads with both polarities"
