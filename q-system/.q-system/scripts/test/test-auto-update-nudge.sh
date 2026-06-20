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

echo "PASS: de-fanged (no subtree pull), exits 0 on non-git, nudges on skew without pulling, registered in both settings files"
