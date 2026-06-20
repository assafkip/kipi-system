#!/usr/bin/env bash
# Negative-test suite for lessons-validator.py. Pairs with issue lessons-validator.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
V="$ROOT/q-system/.q-system/scripts/lessons-validator.py"
D="$(mktemp -d)"; mkdir -p "$D/q-system/lessons"
LP="$D/q-system/lessons"
fail() { echo "FAIL: $1" >&2; exit 1; }
run() { printf '{"tool_input":{"file_path":"%s"}}' "$1" | python3 "$V"; echo $?; }
mk() { printf -- '---\nid: x\nkind: %s\ntitle: %s\ndate: 2026-06-19\n---\nbody\n' "$2" "$3" > "$1"; }

# valid -> 0
mk "$LP/ok.md" pattern "A clean how-only pattern"
[ "$(run "$LP/ok.md")" = "0" ] || fail "valid lesson did not exit 0"
# kind=scar -> 2
mk "$LP/scar.md" scar "t"
[ "$(run "$LP/scar.md")" = "2" ] || fail "kind=scar did not exit 2"
# extra key -> 2
printf -- '---\nid: x\nkind: pattern\ntitle: t\ndate: 2026-06-19\nsource_instances: a,b\n---\nb\n' > "$LP/extra.md"
[ "$(run "$LP/extra.md")" = "2" ] || fail "extra key did not exit 2"
# uppercase token -> 2
mk "$LP/token.md" pattern "The KTLYST escalation antipattern"
[ "$(run "$LP/token.md")" = "2" ] || fail "uppercase client token did not exit 2"
# LOWERCASE token -> 2 (case-insensitive denylist)
mk "$LP/lower.md" pattern "the ciso playbook for assaf"
[ "$(run "$LP/lower.md")" = "2" ] || fail "lowercase client token did not exit 2"
# missing field (no date) -> 2
printf -- '---\nid: x\nkind: pattern\ntitle: t\n---\nb\n' > "$LP/missing.md"
[ "$(run "$LP/missing.md")" = "2" ] || fail "missing field did not exit 2"
# forbidden lesson with NON-.md extension under lessons/ -> 2 (scope not limited to .md)
mk "$LP/leak.markdown" scar "t"
[ "$(run "$LP/leak.markdown")" = "2" ] || fail "non-.md forbidden lesson bypassed the validator"
# out of scope file -> 0
echo "whatever" > "$D/other.md"
[ "$(run "$D/other.md")" = "0" ] || fail "out-of-scope file did not exit 0"
# README in lessons/ -> 0
echo "# readme" > "$LP/README.md"
[ "$(run "$LP/README.md")" = "0" ] || fail "README was not exempted"

rm "$LP"/* "$D"/other.md; rmdir "$LP" "$D/q-system" "$D" 2>/dev/null || true
echo "PASS: blocks scar/extra/token(any case)/missing/non-md-leak, allows valid + out-of-scope + README"
