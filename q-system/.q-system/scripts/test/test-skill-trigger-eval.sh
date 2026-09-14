#!/usr/bin/env bash
# H1: skill-trigger eval harness, OFFLINE (mocks claude -p). Pairs with issue skill-trigger-eval.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
H="$ROOT/q-system/.q-system/scripts/skill-trigger-eval.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# mock claude: prints the FIRED marker when the prompt contains 'yes', else not
MOCK="$(mktemp -d)/mockclaude"
printf '%s\n' '#!/usr/bin/env bash' 'case "$2" in *yes*) echo "skill FIRED here";; *) echo "nothing happened";; esac' > "$MOCK"
chmod +x "$MOCK"
FX="$(mktemp -d)"

# 1. all cases match should_trigger -> rate 1.00
cat > "$FX/testskill.json" <<'J'
{"skill":"testskill","fired_marker":"FIRED","cases":[
 {"prompt":"yes do it","should_trigger":true},
 {"prompt":"no thanks","should_trigger":false},
 {"prompt":"yes please","should_trigger":true}
]}
J
OUT="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" testskill 2>&1)" || fail "harness errored: $OUT"
echo "$OUT" | grep -q "trigger_rate=1.00" || fail "expected trigger_rate=1.00, got: $OUT"
echo "$OUT" | grep -qi "ADVISORY" || fail "missing advisory note"

# 2. a should_trigger=false case that fires -> rate drops to 0.50
cat > "$FX/testskill.json" <<'J'
{"skill":"testskill","fired_marker":"FIRED","cases":[
 {"prompt":"yes a","should_trigger":true},
 {"prompt":"yes b","should_trigger":false}
]}
J
OUT2="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" testskill 2>&1)" || fail "harness errored (case2)"
echo "$OUT2" | grep -q "trigger_rate=0.50" || fail "expected 0.50 (one false-positive), got: $OUT2"

# 3. malformed fixture -> non-zero exit
printf '{"skill":"bad"}\n' > "$FX/bad.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" bad >/dev/null 2>&1 && fail "malformed fixture did not error" || true

# 4. the 4 real fixtures parse + run with a no-op mock (no live claude call)
NOOP="$(mktemp -d)/noop"; printf '%s\n' '#!/usr/bin/env bash' 'echo ""' > "$NOOP"; chmod +x "$NOOP"
for sk in founder-voice audhd-executive-function rca fable-discipline; do
  SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" "$sk" >/dev/null 2>&1 || fail "real fixture $sk failed to parse/run"
done

# 5. broken/missing claude command -> clear error (exit 3), NOT a misleading low rate
printf '{"skill":"t","fired_marker":"FIRED","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/t.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="/nonexistent/claude-xyz" python3 "$H" t >/dev/null 2>&1 && fail "broken claude binary did not error" || true

# --- paths-scoped rules (ASK-1242) ---
# A paths-scoped rule loads only when a matching file is touched. A bare
# `claude -p` touches none, so an unseeded fixture measures the un-ruled model.
# Scar: the instrument-discipline fixture was built, then deleted for exactly
# this (Codex round 1, PR #298); fable-escalation.json ran bare until ASK-1242.
FAKE="$(mktemp -d)/repo"; mkdir -p "$FAKE/.claude/rules" "$FAKE/src"
printf '%s\n' '---' 'description: scoped' 'paths:' '  - "src/**"' '  - "**/*.sql"' '---' 'body' > "$FAKE/.claude/rules/scoped.md"
printf '%s\n' '---' 'paths: "db/**"' '---' 'measured by q-system/.q-system/skill-evals/linked.json' > "$FAKE/.claude/rules/other.md"
printf '%s\n' '---' 'paths:' '  - "**/*"' '---' 'always on' > "$FAKE/.claude/rules/everywhere.md"
echo "x = 1" > "$FAKE/src/existing.py"
git -C "$FAKE" init -q && git -C "$FAKE" add -A && git -C "$FAKE" -c user.email=t@t -c user.name=t commit -qm init
CALLS="$(mktemp)"
# fires only when the seed exists in the session's cwd AND the prompt names it AND says yes
SEEDMOCK="$(mktemp -d)/seedmock"
printf '%s\n' '#!/usr/bin/env bash' "echo call >> '$CALLS'" \
  'if [ -f "$PWD/src/seed_eval.py" ]; then case "$2" in *src/seed_eval.py*yes*|*yes*src/seed_eval.py*) echo "FIRED";; esac; fi' > "$SEEDMOCK"
chmod +x "$SEEDMOCK"
run_fake() { SKILL_EVAL_DIR="$FX" SKILL_EVAL_REPO_ROOT="$FAKE" SKILL_EVAL_CLAUDE_CMD="$SEEDMOCK" python3 "$H" "$@"; }

# 6. REPRODUCER: paths-scoped rule, no seed_path, no matching path in the prompt -> refused, globs named, zero claude calls
printf '{"skill":"scoped","fired_marker":"FIRED","cases":[{"prompt":"yes","should_trigger":true},{"prompt":"no","should_trigger":false}]}\n' > "$FX/scoped.json"
: > "$CALLS"
if OUT6="$(run_fake scoped 2>&1)"; then fail "unseeded paths-scoped fixture was run, not refused: $OUT6"; fi
echo "$OUT6" | grep -q 'src/\*\*' || fail "refusal does not name the rule's paths globs: $OUT6"
echo "$OUT6" | grep -q 'scoped.md' || fail "refusal does not name the rule file: $OUT6"
[ ! -s "$CALLS" ] || fail "refused fixture still spent $(wc -l < "$CALLS") claude call(s)"

# 7. the rule found by the fixture path it names (skill-evals/linked.json), not only by file stem
printf '{"skill":"linked","fired_marker":"FIRED","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/linked.json"
if OUT7="$(run_fake linked 2>&1)"; then fail "fixture named by a paths-scoped rule body was run bare: $OUT7"; fi
echo "$OUT7" | grep -q 'db/\*\*' || fail "inline paths: scalar not parsed: $OUT7"

# 8. a seed_path that matches none of the globs -> refused
printf '{"skill":"scoped","fired_marker":"FIRED","seed_path":"docs/readme.md","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/scoped.json"
if OUT8="$(run_fake scoped 2>&1)"; then fail "non-matching seed_path was accepted: $OUT8"; fi

# 9. POSITIVE: a matching seed_path is created in a temp copy, named in the prompt, and the marker check runs.
#    Unseeded, the mock never fires and this would read 0.50, so 1.00 proves the seed reached the session.
printf '{"skill":"scoped","fired_marker":"FIRED","seed_path":"src/seed_eval.py","cases":[{"prompt":"yes","should_trigger":true},{"prompt":"no","should_trigger":false}]}\n' > "$FX/scoped.json"
OUT9="$(run_fake scoped 2>&1)" || fail "seeded fixture errored: $OUT9"
echo "$OUT9" | grep -q "trigger_rate=1.00" || fail "seed did not reach the session (expected 1.00): $OUT9"
[ ! -e "$FAKE/src/seed_eval.py" ] || fail "seed was written into the live repo, not a copy"
[ -z "$(git -C "$FAKE" status --porcelain)" ] || fail "live repo dirtied by the eval: $(git -C "$FAKE" status --porcelain)"

# 10. a prompt that itself names a matching path is not refused
printf '{"skill":"scoped","fired_marker":"FIRED","cases":[{"prompt":"yes look at src/existing.py","should_trigger":false}]}\n' > "$FX/scoped.json"
OUT10="$(run_fake scoped 2>&1)" || fail "prompt naming a matching path was refused: $OUT10"

# 11. a "**/*" rule is always-on, so its fixture runs bare
printf '{"skill":"everywhere","fired_marker":"FIRED","cases":[{"prompt":"no","should_trigger":false}]}\n' > "$FX/everywhere.json"
OUT11="$(run_fake everywhere 2>&1)" || fail "always-on rule fixture was refused: $OUT11"

# 12. the real paths-scoped fixtures are measurable against the real repo (no-op mock, no live call)
for sk in fable-escalation social-reaction-gate; do
  SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" "$sk" >/dev/null 2>&1 || fail "real fixture $sk refused or failed: $(SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" "$sk" 2>&1 | tail -3)"
done

echo "PASS: trigger_rate computed, false-positive penalized, malformed rejected, all 4 real fixtures parse; broken-claude errors clearly (offline); paths-scoped rules refused bare, seeded into a temp copy"
