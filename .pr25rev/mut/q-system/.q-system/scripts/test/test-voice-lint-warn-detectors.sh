#!/usr/bin/env bash
# H8b+H9: emphasis-opener + rhetorical-QA WARN detectors. Pairs with issue voice-lint-warn-detectors.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
VL="$ROOT/q-system/.q-system/scripts/voice-lint.py"
fail() { echo "FAIL: $1" >&2; exit 1; }
T="$(mktemp -d)"

# cli_mode lints any path and exits 2 only on BLOCK violations; WARN rules exit 0.

# 1. emphasis opener should FLAG and stay WARN (exit 0)
printf 'Importantly, the gate holds.\n' > "$T/e1.md"
OUT="$(python3 "$VL" "$T/e1.md" 2>&1)" && rc=0 || rc=$?
echo "$OUT" | grep -q "emphasis-opener" || fail "sentence-initial 'Importantly,' not flagged: $OUT"
[ "$rc" -eq 0 ] || fail "emphasis-opener exited $rc (must be 0 = WARN, not BLOCK): $OUT"

# 2. emphasis opener should NOT flag mid-sentence
printf 'This runs significantly faster, notably under load.\n' > "$T/e2.md"
OUT="$(python3 "$VL" "$T/e2.md" 2>&1)" || true
echo "$OUT" | grep -q "emphasis-opener" && fail "mid-sentence 'significantly/notably' wrongly flagged: $OUT" || true

# 3. rhetorical Q-then-answer should FLAG and stay WARN (exit 0)
printf 'The result? A cleaner pipeline.\n' > "$T/q1.md"
OUT="$(python3 "$VL" "$T/q1.md" 2>&1)" && rc=0 || rc=$?
echo "$OUT" | grep -q "rhetorical-qa" || fail "'The result? A cleaner pipeline.' not flagged: $OUT"
[ "$rc" -eq 0 ] || fail "rhetorical-qa exited $rc (must be 0 = WARN, not BLOCK): $OUT"

# 4. a real reader-directed question + substantive answer should NOT flag
printf 'What do you think about gated workflows? I have run them on three projects now and the receipts changed how my team trusts the output.\n' > "$T/q2.md"
OUT="$(python3 "$VL" "$T/q2.md" 2>&1)" || true
echo "$OUT" | grep -q "rhetorical-qa" && fail "reader-directed question wrongly flagged: $OUT" || true

# 5. WARN_RULES membership is unchanged except the two new names (no existing rule re-tiered)
python3 - "$VL" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("vl", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
new = {"emphasis-opener", "rhetorical-qa"}
orig = {"rule-of-three", "rule-of-three-density", "comma-triplet", "cross-paragraph-fragments",
        "sentence-uniformity", "hedge-density", "no-single-sentence-paragraph",
        "bold-restatement", "missing-contraction"}
assert new <= m.WARN_RULES, "new rules missing from WARN_RULES"
assert orig <= m.WARN_RULES, "an existing WARN rule was dropped/renamed"
assert m.WARN_RULES == orig | new, f"WARN_RULES membership drifted: {sorted(m.WARN_RULES)}"
print("WARN_RULES membership OK (orig 9 + 2 new, nothing re-tiered)")
PY

echo "PASS: emphasis-opener + rhetorical-qa flag the AI tells as WARN (exit 0), do not flag mid-sentence use or real reader-directed questions, and WARN_RULES membership is unchanged except the two new names"
