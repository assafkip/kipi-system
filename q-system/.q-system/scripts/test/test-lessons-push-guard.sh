#!/usr/bin/env bash
# Test suite for the lessons + registry guards in kipi-push-upstream.sh.
# Pairs with issue lessons-push-guard.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT="$ROOT/kipi-push-upstream.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

WORK="$(mktemp -d)"
git init -q --bare "$WORK/skel.git"
G clone -q "$WORK/skel.git" "$WORK/seed"
mkdir -p "$WORK/seed/q-system/lessons"
printf -- '---\nid: a\nkind: pattern\ntitle: A clean lesson\ndate: 2026-06-01\n---\nbody\n' > "$WORK/seed/q-system/lessons/a.md"
( cd "$WORK/seed" && G add -A && G commit -qm seed && G push -q origin HEAD:main )
G clone -q -b main "$WORK/skel.git" "$WORK/inst"
cp "$SCRIPT" "$WORK/inst/kipi-push-upstream.sh"
clean_reg() { printf '{"instances":[{"name":"foo","type":"subtree"},{"name":"car-research","type":"direct-clone"}]}\n' > "$WORK/inst/instance-registry.json"; }
clean_reg
run() { ( cd "$WORK/inst" && KIPI_SKELETON_REMOTE="$WORK/skel.git" bash kipi-push-upstream.sh ) 2>&1; }

# 1. clean lessons + clean registry -> guards pass (reach the push stage)
OUT="$(run)" || true
echo "$OUT" | grep -q "Pushing to skeleton" || fail "clean case blocked by guards: $OUT"

# 2. non-allowlisted direct-clone in registry -> refuse
printf '{"instances":[{"name":"evil","type":"direct-clone"}]}\n' > "$WORK/inst/instance-registry.json"
OUT="$(run)" && RC=0 || RC=$?
[ "${RC:-0}" -ne 0 ] || fail "non-allowlisted direct-clone not refused"
echo "$OUT" | grep -qi "direct-clone" || fail "registry guard wrong error: $OUT"
clean_reg

# 3. uncommitted lesson edit -> refuse before push
echo "tamper" >> "$WORK/inst/q-system/lessons/a.md"
OUT="$(run)" && RC=0 || RC=$?
[ "${RC:-0}" -ne 0 ] || fail "uncommitted lesson edit not refused"
echo "$OUT" | grep -qi "skeleton-authored" || fail "uncommitted wrong error: $OUT"
echo "$OUT" | grep -q "Pushing to skeleton" && fail "uncommitted reached push despite violation"
( cd "$WORK/inst" && G checkout -q -- q-system/lessons/a.md )

# 4. committed lesson edit -> refuse
( cd "$WORK/inst" && echo "diverge" >> q-system/lessons/a.md && G commit -qam "edit lesson" )
OUT="$(run)" && RC=0 || RC=$?
[ "${RC:-0}" -ne 0 ] || fail "committed lesson edit not refused"
echo "$OUT" | grep -qiE "skeleton-authored|differs" || fail "committed wrong error: $OUT"

# 5. fail-CLOSED: fresh instance, committed lesson edit, fetch FAILS (bad remote) -> refuse
G clone -q -b main "$WORK/skel.git" "$WORK/inst2"
cp "$SCRIPT" "$WORK/inst2/kipi-push-upstream.sh"
printf '{"instances":[{"name":"foo","type":"subtree"}]}\n' > "$WORK/inst2/instance-registry.json"
( cd "$WORK/inst2" && echo "LEAKED CLIENT SECRET" >> q-system/lessons/a.md && G commit -qam tamper )
OUT="$( ( cd "$WORK/inst2" && KIPI_SKELETON_REMOTE="/nonexistent/path-xyz-$$.git" bash kipi-push-upstream.sh ) 2>&1 )" && RC=0 || RC=$?
[ "${RC:-0}" -ne 0 ] || fail "FAIL-OPEN: committed lesson edit pushed when skeleton fetch failed"
echo "$OUT" | grep -q "Pushing to skeleton" && fail "FAIL-OPEN: reached push with tampered lesson and failed fetch"
echo "$OUT" | grep -qiE "cannot verify|fail-closed|skeleton-authored" || fail "fail-closed: wrong message: $OUT"

# 6. FLAT skeleton layout (lessons/ at repo root) vs a nested instance -> guard must not crash
git init -q --bare "$WORK/flatskel.git"
G clone -q "$WORK/flatskel.git" "$WORK/flatseed"
mkdir -p "$WORK/flatseed/lessons"
printf -- '---\nid: a\nkind: pattern\ntitle: A clean lesson\ndate: 2026-06-01\n---\nbody\n' > "$WORK/flatseed/lessons/a.md"
( cd "$WORK/flatseed" && G add -A && G commit -qm seed && G push -q origin HEAD:main )
G clone -q -b main "$WORK/skel.git" "$WORK/inst3"
cp "$SCRIPT" "$WORK/inst3/kipi-push-upstream.sh"
printf '{"instances":[{"name":"foo","type":"subtree"}]}\n' > "$WORK/inst3/instance-registry.json"
OUT="$( ( cd "$WORK/inst3" && KIPI_SKELETON_REMOTE="$WORK/flatskel.git" bash kipi-push-upstream.sh ) 2>&1 )" || true
echo "$OUT" | grep -qiE "Traceback|IndexError" && fail "flat-skeleton layout crashed the guard: $OUT"
echo "$OUT" | grep -q "Pushing to skeleton" || fail "flat-skeleton clean case did not clear the guards: $OUT"

echo "PASS: refuses uncommitted+committed lesson edits and non-allowlisted direct-clones; clean push clears the guards; fails CLOSED when unverifiable; handles flat + nested skeleton layouts"
