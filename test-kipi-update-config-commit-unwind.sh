#!/usr/bin/env bash
# The ASK-797 unwind on the CONFIG-SYNC commit half must leave a clean index.
#
# WHY THIS IS NOT test-kipi-update-safety.sh CASE 13. That case already plants a
# pre-commit hook that exits 1 and already asserts a clean index, so the unwind
# looked covered. It is not. Measured 2026-08-14 by instrumenting kipi-update.sh
# with markers and replaying that exact fixture: the run dies at "could not
# commit q-system sync" and NEITHER the config-sync call site NOR the ASK-797
# unwind is ever reached. Case 13 passes on a different unwind entirely -- the
# q-system sync failure path -- and the commit-half unwind it appears to cover
# has never once executed.
#
# A hook that refuses EVERY commit stops at the first one. To reach the second,
# the hook here refuses SELECTIVELY: it passes the q-system sync commit and
# rejects only a commit that stages .claude/ or plugins/. That is not a
# contrived shape -- it is exactly what a lefthook `blocked-paths` rule is, and
# two instances in this fleet run one.
#
# The assertion is on the INDEX, because that is what strands an instance: the
# dirty-tree guard reads `git diff --cached`, so staged leftovers make every
# later run refuse over debris that is not founder work.
#
# Self-test at the bottom: the same fixture is replayed against a copy of the
# updater with the unwind deleted, and the index assertion must FAIL there. A
# test for a path that has never executed is worth nothing until it is shown to
# go red.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$ROOT/kipi-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

build_fixture() {
  # $1 = dir to build in, $2 = path to the updater to install as the skeleton's
  local work="$1" updater="$2"
  local sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/.claude/rules" "$sk/plugins/demo" "$inst/q-system"
  cp "$updater" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/kipi-update-deletion-guard.py" "$sk/kipi-update-deletion-guard.py"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
  printf 'skeleton content v2\n' > "$sk/q-system/tracked.md"
  # Config + a plugin, so the config-sync commit has something to stage. Without
  # these the call site is guarded on `git diff --cached --quiet` and is skipped.
  printf '# a rule\n' > "$sk/.claude/rules/demo-rule.md"
  printf '{"name":"demo","version":"0.0.1"}\n' > "$sk/plugins/demo/plugin.json"
  printf '{"hooks":{}}\n' > "$sk/.claude/settings.json"
  ( cd "$sk" && G init -q && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"stuck","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  printf 'skeleton content v1 (old)\n' > "$inst/q-system/tracked.md"
  # The config-sync block is gated on `[ -d "$path/.claude" ]` -- the INSTANCE's
  # own .claude/, not the skeleton's. Without it the whole stage is skipped and
  # the run reports success, which is what the precondition assertion below
  # caught the first time this fixture was written.
  mkdir -p "$inst/.claude/rules"
  printf '{}\n' > "$inst/.claude/settings.json"
  printf '# stale rule\n' > "$inst/.claude/rules/demo-rule.md"
  ( cd "$inst" && G init -q && G add -A && G commit -qm inst )
  mkdir -p "$inst/.git/hooks"
  cat > "$inst/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Passes the q-system sync commit, refuses anything staging .claude/ or
# plugins/. The shape of a lefthook blocked-paths rule.
staged="$(git diff --cached --name-only)"
if printf '%s\n' "$staged" | grep -qE '^(\.claude/|plugins/)'; then
  echo "instance pre-commit refuses config/plugins paths" >&2
  exit 1
fi
exit 0
HOOK
  chmod +x "$inst/.git/hooks/pre-commit"
}

# --------------------------------------------------------------------------
# 1. the real updater: the run fails, and the index is left clean
# --------------------------------------------------------------------------
W1="$(mktemp -d)"
build_fixture "$W1" "$SCRIPT"
OUT1="$(bash "$W1/skel/kipi-update.sh" --only stuck 2>&1)"

# Reaching the config-sync commit at all is a precondition, not a nicety: if the
# run died earlier this test would assert a clean index for the same wrong
# reason case 13 does. Asserted on the run's OWN output, because the first
# version of this check used "a commit whose message contains sync" as a proxy
# and reported not-reached while the stage was in fact running.
echo "$OUT1" | grep -q "Syncing .claude/ config" || \
  fail "the run never reached the config-sync stage; this fixture proves nothing.
Output: $OUT1"
echo "$OUT1" | grep -q "instance pre-commit refuses config/plugins paths" || \
  fail "the hook never refused, so the unwind under test never ran.
Output: $OUT1"

if ! G -C "$W1/inst" diff --cached --quiet; then
  fail "the config-commit failure left the index STAGED, so every later run
refuses at the dirty-tree guard: $(G -C "$W1/inst" diff --cached --name-only | tr '\n' ' ')"
fi
echo "PASS: a refused config-sync commit leaves the index clean"

# and the instance is still updatable once the hook is gone
rm -f "$W1/inst/.git/hooks/pre-commit"
OUT2="$(bash "$W1/skel/kipi-update.sh" --only stuck 2>&1)"
echo "$OUT2" | grep -q "dirty working tree" && \
  fail "run 2 refused at the dirty-tree guard -- the instance is stuck: $OUT2"
echo "PASS: the instance still converges on a later run"

# --------------------------------------------------------------------------
# 2. WHICH mechanism actually holds the line? Two candidates, mutate both.
# --------------------------------------------------------------------------
# Two things could be keeping that index clean: the ASK-797 unwind at the
# config-sync call site, and restore_instance (reached via abandon_instance when
# CONFIG_FAILED is set). Asserting "the index is clean" cannot tell them apart,
# and a guard credited with work it does not do is how the real one gets
# deleted later by someone tidying up.
#
# MEASURED 2026-08-14, and the answer is not the obvious one: deleting the
# ASK-797 unwind changes NOTHING -- restore_instance cleans the index either
# way. The unwind is belt-and-braces at this call site, not the guard. That is
# recorded here rather than asserted, because it is a fact about today's control
# flow: if abandon_instance ever stops restoring, the unwind becomes load-
# bearing and control B below is what will notice.
mutate() {  # $1 = out path, $2 = old, $3 = new, $4 = label
  python3 - "$SCRIPT" "$1" "$2" "$3" "$4" <<'PY'
import sys
src, dst, old, new, label = sys.argv[1:6]
text = open(src).read()
if text.count(old) != 1:
    sys.exit(f"MUTANT '{label}' NOT APPLICABLE: {text.count(old)} matches")
open(dst, "w").write(text.replace(old, new))
print(f"  mutant applied: {label}")
PY
}

W2="$(mktemp -d)"
M_UNWIND="$W2/no-unwind.sh"
mutate "$M_UNWIND" \
  '{ unstage_scope "$path" .claude/ plugins/; false; }
          fi; }' \
  '{ false; }
          fi; }' \
  "ASK-797 unwind deleted" || fail "could not build the no-unwind mutant"
build_fixture "$W2" "$M_UNWIND"
bash "$W2/skel/kipi-update.sh" --only stuck >/dev/null 2>&1
if G -C "$W2/inst" diff --cached --quiet; then
  echo "NOTE: control A -- with the ASK-797 unwind DELETED the index is STILL"
  echo "      clean, so restore_instance is what holds this line, not the unwind."
else
  echo "NOTE: control A -- the ASK-797 unwind IS load-bearing here now"
  echo "      (staged without it: $(G -C "$W2/inst" diff --cached --name-only | tr '\n' ' '))"
fi

# Control B is the one that gives the assertion above its teeth: remove the
# restore and the index MUST be left dirty. If this stops failing, the test has
# stopped testing anything.
W3="$(mktemp -d)"
M_RESTORE="$W3/no-restore.sh"
mutate "$M_RESTORE" \
  '  [ -n "$message" ] && echo "$message"
  restore_instance' \
  '  [ -n "$message" ] && echo "$message"' \
  "restore_instance removed from abandon_instance" || \
  fail "could not build the no-restore mutant"
build_fixture "$W3" "$M_RESTORE"
bash "$W3/skel/kipi-update.sh" --only stuck >/dev/null 2>&1
if G -C "$W3/inst" diff --cached --quiet && G -C "$W3/inst" diff --quiet; then
  fail "SELF-TEST FAILED: the instance came out clean with the restore REMOVED.
Nothing in this file is testing a guard; the assertions pass for free."
fi
echo "PASS: self-test -- removing the restore leaves the instance dirty ($(G -C "$W3/inst" status --porcelain | head -3 | tr '\n' ' '))"

echo "ALL PASS"
