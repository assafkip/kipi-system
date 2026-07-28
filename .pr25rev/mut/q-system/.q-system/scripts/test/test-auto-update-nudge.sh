#!/usr/bin/env bash
# H5: auto-update.sh must be de-fanged (no subtree pull), nudge-only, and wired. Pairs with issue auto-update-nudge.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
H="$ROOT/q-system/hooks/auto-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

grep -vE '^\s*#' "$H" | grep -q "subtree pull" && fail "auto-update.sh still has a git subtree pull command (must be de-fanged)"
grep -q "auto-update.sh" "$ROOT/settings-template.json" || fail "not registered in settings-template.json"
grep -q "auto-update.sh" "$ROOT/.claude/settings.json" || fail "not registered in .claude/settings.json"

# never-blocks on a non-git dir
D="$(mktemp -d)"
CLAUDE_PROJECT_DIR="$D" bash "$H" >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "auto-update.sh did not exit 0 on a non-git dir"

# faithful nudge: an instance lacking the remote's HEAD -> nudge, exit 0, NO pull
BARE="$(mktemp -d)/r.git"; git init -q --bare "$BARE"; git -C "$BARE" symbolic-ref HEAD refs/heads/main
SEED="$(mktemp -d)"; ( cd "$SEED" && G init -q && mkdir -p q-system && printf 'a\n' > q-system/a.md && G add -A && G commit -qm base && G push -q "$BARE" HEAD:main )
INST="$(mktemp -d)"; ( cd "$INST" && G clone -q -b main "$BARE" . )
( cd "$SEED" && printf 'b\n' > q-system/b.md && G add -A && G commit -qm extra && G push -q "$BARE" HEAD:main )
OUT="$(CLAUDE_PROJECT_DIR="$INST" KIPI_SKELETON_REMOTE="$BARE" bash "$H" 2>&1)" && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "nudge path exited non-zero: $OUT"
echo "$OUT" | grep -qi "kipi update" || fail "skew did not produce a kipi-update nudge: $OUT"
[ ! -f "$INST/q-system/b.md" ] || fail "auto-update PULLED (b.md appeared) -- must only nudge"

# DIRTY tree must NOT suppress the nudge. Regression guard for the removed pull-era
# skip (it ran `git diff --quiet` and silently swallowed the nudge on any dirty tree).
# Fixture: a fresh instance that is BEHIND the remote (so it reaches the nudge path),
# then modify a TRACKED file so `git diff --quiet` reports dirty (an untracked file
# would not trip the old check, so it would not prove the regression is fixed).
INST2="$(mktemp -d)"; ( cd "$INST2" && G clone -q -b main "$BARE" . )
( cd "$SEED" && printf 'c\n' > q-system/c.md && G add -A && G commit -qm extra2 && G push -q "$BARE" HEAD:main )
printf 'wip\n' >> "$INST2/q-system/a.md"   # modify a TRACKED file -> dirty working tree
OUT2="$(CLAUDE_PROJECT_DIR="$INST2" KIPI_SKELETON_REMOTE="$BARE" bash "$H" 2>&1)" && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "dirty-tree nudge path exited non-zero: $OUT2"
echo "$OUT2" | grep -qi "kipi update" || fail "dirty tree suppressed the nudge (pull-era skip regressed): $OUT2"
[ ! -f "$INST2/q-system/c.md" ] || fail "auto-update PULLED on a dirty tree (c.md appeared) -- must only nudge"

echo "PASS: de-fanged (no subtree pull), exits 0 on non-git, nudges on skew AND on a dirty tree without pulling, registered in both settings files"
