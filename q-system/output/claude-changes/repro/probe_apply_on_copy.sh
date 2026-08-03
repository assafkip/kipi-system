#!/usr/bin/env bash
# probe_apply_on_copy.sh -- verify the arming proposal against a COPY. ASK-291.
#
# "Verify against a copy" (fable-discipline): the applier is the only sanctioned
# write path into .claude/, so the first run of a rewritten proposal happens on a
# throwaway tree, never on the live one. If the anchors are wrong or the pair is
# missing, the refusal costs nothing here.
#
# NEGATIVE SELF-TEST: phase 2 re-runs the same proposal on the same tree and
# requires "already-applied". A harness that reports OK on the second apply too
# would not be able to tell an apply from a no-op.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
PROPOSAL="$ROOT/q-system/output/claude-changes/arm-claude-write-path-guards.json"
APPLY="$ROOT/q-system/.q-system/scripts/apply-claude-changes.sh"
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
D="$WORK/root"
mkdir -p "$D/q-system/.q-system"
cp -R "$ROOT/.claude" "$D/.claude"
rm -rf "$D/.claude/worktrees" "$D/.claude/state" "$D/.claude/plans"
cp "$ROOT/settings-template.json" "$D/"
cp -R "$ROOT/q-system/.q-system/scripts" "$D/q-system/.q-system/scripts"
cp "$ROOT/q-system/.q-system/capability-manifest.json" "$D/q-system/.q-system/" 2>/dev/null
git -C "$D" init -q

echo "== Phase 1. Apply on the copy =="
OUT="$(bash "$APPLY" "$PROPOSAL" --root "$D" 2>&1)"; RC=$?
echo "     $OUT"
[ "$RC" -eq 0 ] && pass "applied (exit 0)" || fail "applier refused (exit $RC)"

echo "== Phase 2. Negative self-test: a second apply must be a no-op =="
OUT2="$(bash "$APPLY" "$PROPOSAL" --root "$D" 2>&1)"; RC2=$?
case "$OUT2" in
  *already-applied*) pass "second run reports already-applied (this harness can tell them apart)" ;;
  *) fail "second run did not report already-applied: $OUT2" ;;
esac
[ "$RC2" -eq 0 ] || fail "second run exited $RC2"

echo "== Phase 3. Both files are valid JSON and carry both layers =="
python3 - "$D" <<'PY'
import json, os, sys
d = sys.argv[1]
ok = True
for rel in (".claude/settings.json", "settings-template.json"):
    s = json.load(open(os.path.join(d, rel)))
    for script, event, need_bash in (
            ("claude-path-write-guard.py", "PreToolUse", True),
            ("claude-integrity-tripwire.py", "PostToolUse", True)):
        hits = [g.get("matcher") or "" for g in s["hooks"].get(event, [])
                for h in g.get("hooks", []) if script in h.get("command", "")]
        if not hits:
            print("  FAIL %s: %s absent from %s" % (rel, script, event)); ok = False
        elif need_bash and "Bash" not in hits[0]:
            print("  FAIL %s: %s wired to Bash-blind matcher %r" % (rel, script, hits[0])); ok = False
        else:
            print("  ok   %s: %s in %s, matcher=%s" % (rel, script, event, hits[0]))
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && pass "both surfaces parse and carry both layers on Bash-visible matchers" \
             || fail "wiring assertion failed"

echo "== Phase 4. settings-template-sync-check is green on the applied tree =="
OUT4="$(cd "$D" && CLAUDE_PROJECT_DIR="$D" python3 "$D/q-system/.q-system/scripts/settings-template-sync-check.py" --check 2>&1)"; RC4=$?
[ "$RC4" -eq 0 ] && pass "no stranded hook: the pair landed on both surfaces" \
                 || fail "sync-check exit $RC4: $OUT4"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
