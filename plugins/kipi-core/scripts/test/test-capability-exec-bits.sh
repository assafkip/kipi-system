#!/usr/bin/env bash
# test-capability-exec-bits.sh - the capability-token approval path must be
# EXECUTABLE as shipped, not after a local chmod.
#
# Scar (ASK-257, discovered live 2026-07-29): kipi-approve and
# capability-token.sh were committed 100644, so the marketplace clone at
# ~/.claude/plugins/marketplaces/kipi/... shipped them -rw-r--r--. The founder's
# documented approval command for a blocked destructive op returned "permission
# denied". The gate's approval path had been unusable since 2026-06-19, which
# pressures every blocked op toward ALLOW_DESTRUCTIVE instead of a minted token.
#
# Why the GIT MODE and not the working-tree mode: the marketplace copy is a git
# clone, so the mode a clone receives is the mode in the index. A `chmod +x` in
# any local checkout is invisible to the clone and would make a filesystem-only
# check pass while the shipped copy stays broken.
#
# Why a `git archive` export and not this checkout: verify against a copy
# (fable-discipline). The export reproduces a fresh clone's permissions exactly,
# so "runs with no bash prefix" is proven on clone-equivalent bytes rather than
# on a working tree somebody may have chmod'd by hand.
#
# No side effects: `kipi-approve` with an empty hash is refused by cmd_mint's
# hex validation BEFORE it creates or touches $HOME/.claude/approvals, so this
# test never mints a token and never writes under .claude/.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"

fail=0
ok()  { printf 'ok   - %s\n' "$1"; }
bad() { printf 'FAIL - %s\n' "$1"; fail=1; }

# Every script on the founder's approval path. kipi-approve is what the deny
# message tells him to run; capability-token.sh is what it execs; the installer
# is how both reach ~/.claude/bin.
EXEC_PATHS=(
  "plugins/kipi-core/scripts/kipi-approve"
  "plugins/kipi-core/scripts/capability-token.sh"
  "plugins/kipi-core/scripts/install-capability-token.sh"
)

# --- 1. git index mode is 100755 (this is what a clone gets) ------------------
for rel in "${EXEC_PATHS[@]}"; do
  mode="$(git -C "$REPO" ls-files -s -- "$rel" | awk '{print $1}')"
  if [ -z "$mode" ]; then
    bad "$rel is not tracked by git (cannot ship at all)"
  elif [ "$mode" = "100755" ]; then
    ok "$rel git mode $mode"
  else
    bad "$rel git mode $mode (want 100755; a clone will ship it non-executable)"
  fi
done

# --- 2. runs from a clone-equivalent export, no bash prefix, no chmod ---------
TMP="$(mktemp -d)" || { echo "FAIL - mktemp"; exit 1; }
trap 'rm -rf "$TMP"' EXIT
if git -C "$REPO" archive HEAD plugins/kipi-core/scripts | tar -x -C "$TMP"; then
  ok "exported HEAD to a clone-equivalent tree"
else
  bad "git archive export failed"
fi

APPROVE="$TMP/plugins/kipi-core/scripts/kipi-approve"
if [ -x "$APPROVE" ]; then
  ok "exported kipi-approve carries the exec bit"
else
  bad "exported kipi-approve is not executable (this is the ASK-257 defect)"
fi

# Direct invocation. Exit 126 is the shell's "cannot execute"; that is the
# failure this test exists to catch. An empty hash must be refused by mint's
# own validation, which proves control reached capability-token.sh.
out="$("$APPROVE" 2>&1)"
rc=$?
if [ "$rc" -eq 126 ]; then
  bad "kipi-approve exited 126 (permission denied) - not executable as shipped"
elif [ "$rc" -eq 2 ] && printf '%s' "$out" | grep -q '64 lowercase hex'; then
  ok "kipi-approve ran with no bash prefix and reached capability-token.sh mint"
else
  bad "kipi-approve rc=$rc out=[$out] (want rc=2 and mint's hex validation)"
fi

# --- 3. the lib it execs must be executable in the export too ----------------
# kipi-approve falls back to ~/.claude/bin when the sibling lib is not -x, so a
# non-executable lib in the clone would be masked on any machine that has the
# installed copy. Assert the export's own lib directly.
LIB="$TMP/plugins/kipi-core/scripts/capability-token.sh"
if [ -x "$LIB" ]; then
  ok "exported capability-token.sh carries the exec bit"
else
  bad "exported capability-token.sh is not executable (clone falls back to ~/.claude/bin)"
fi

if [ "$fail" -eq 0 ]; then
  echo "PASS - capability approval path is executable as shipped"
else
  echo "FAIL - capability approval path is not executable as shipped"
fi
exit "$fail"
