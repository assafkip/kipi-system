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

# DISARM the copy before applying to it (review finding, PR #85). The copy is
# taken from the PR head, where the proposal is ALREADY applied, so phase 1 was
# exercising the no-op path and its "applied (exit 0)" proved nothing about the
# apply it claimed to test. Stripping both hooks puts the copy back in the state
# a real instance is in before arming. Merge-proof: it edits the copy's own JSON
# rather than reaching for a pre-merge git ref that stops existing after merge.
disarm() {
  python3 - "$1" <<'PY'
import json, os, sys
d = sys.argv[1]
GUARDS = ("claude-path-write-guard.py", "claude-integrity-tripwire.py")
for rel in (".claude/settings.json", "settings-template.json"):
    p = os.path.join(d, rel)
    s = json.load(open(p))
    for event, groups in list(s.get("hooks", {}).items()):
        kept = []
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", [])
                          if not any(x in h.get("command", "") for x in GUARDS)]
            if g["hooks"]:
                kept.append(g)
        s["hooks"][event] = kept
    json.dump(s, open(p, "w"), indent=2)
    open(p, "a").write("\n")
PY
}
disarm "$D"

echo "== Phase 1. Apply on the copy =="
OUT="$(bash "$APPLY" "$PROPOSAL" --root "$D" 2>&1)"; RC=$?
echo "     $OUT"
[ "$RC" -eq 0 ] && pass "applied (exit 0)" || fail "applier refused (exit $RC)"
case "$OUT" in
  *already-applied*) fail "phase 1 was a NO-OP -- the copy arrived already armed, so this harness tested nothing" ;;
  *) pass "phase 1 performed a real apply (not already-applied)" ;;
esac

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

echo "== Phase 5. The sanctioned route still works AFTER arming =="
# THE ONE THAT FIRED LIVE (2026-08-03 15:22Z). The applier wrote .claude/
# settings.json, exited OK, and the very next tool call ran the freshly-armed
# PostToolUse tripwire, which saw the arming itself as unsanctioned drift and
# REVERTED it:
#   SECURITY: unsanctioned .claude/ change -- 1 modified ... | reverted 1
# The applier is THE sanctioned write path, so its writes have to be recorded as
# sanctioned. The tripwire already exposes exactly this (`--register PATH...`,
# its docstring calls it "the sanctioned-apply hook"); the applier never called
# it. A guard that reverts the legitimate path is a different outage, and this is
# the phase that holds it shut.
D2="$WORK/root2"
mkdir -p "$D2/q-system/.q-system"
cp -R "$ROOT/.claude" "$D2/.claude"
rm -rf "$D2/.claude/worktrees" "$D2/.claude/state" "$D2/.claude/plans"
cp "$ROOT/settings-template.json" "$D2/"
cp -R "$ROOT/q-system/.q-system/scripts" "$D2/q-system/.q-system/scripts"
cp "$ROOT/q-system/.q-system/capability-manifest.json" "$D2/q-system/.q-system/" 2>/dev/null
disarm "$D2"   # same reason as phase 1: an armed copy makes this phase a no-op
git -C "$D2" init -q
git -C "$D2" add -A >/dev/null 2>&1
git -C "$D2" -c user.email=t@t -c user.name=t commit -qm base >/dev/null 2>&1
TW="$D2/q-system/.q-system/scripts/claude-integrity-tripwire.py"
KIPI_NOTIFY=/usr/bin/true python3 "$TW" --root "$D2" --enforce --quiet >/dev/null 2>&1  # arm

bash "$APPLY" "$PROPOSAL" --root "$D2" >/dev/null 2>&1
RC5=$?
[ "$RC5" -eq 0 ] && pass "applier succeeds against an armed tree (exit 0)" \
                 || fail "applier exit $RC5 against an armed tree"

KIPI_NOTIFY=/usr/bin/true python3 "$TW" --root "$D2" --enforce --quiet >/dev/null 2>&1
RC5B=$?
[ "$RC5B" -eq 0 ] && pass "the tripwire treats the applier's write as sanctioned (exit 0)" \
                  || fail "tripwire reported the sanctioned apply as drift (exit $RC5B)"
grep -q 'claude-path-write-guard' "$D2/.claude/settings.json" \
  && pass "the arming SURVIVED the enforcer (not auto-reverted)" \
  || fail "the applier's own change was reverted by the tripwire"

# And the other end: registering the applier's write must not blind the tripwire.
printf 'pwned\n' >> "$D2/.claude/settings.json"
KIPI_NOTIFY=/usr/bin/true python3 "$TW" --root "$D2" --enforce --quiet >/dev/null 2>&1
[ $? -eq 2 ] && pass "a tamper after a sanctioned apply is still caught" \
             || fail "tripwire went blind after the apply registered its write"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
