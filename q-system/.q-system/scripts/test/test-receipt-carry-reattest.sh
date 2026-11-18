#!/usr/bin/env bash
# Narrow re-attest: carry an approval across a merge of main whose only hand edit
# is a plugin.json "version" bump (ASK-4969, ruling 2026-11-18 22:20 UTC).
#
# THE SCAR. PR #839 was approved on 060b3038. main then bumped the same plugin
# version, the merge conflicted on that one line, and the hand-resolved head
# 55e215b0 (1.13.72, main had 1.13.71) carried no approval. The round cap (3)
# refused a 4th review and receipt-carry-approval.sh only carried receipt-only
# deltas, so a bookkeeping line stranded an approved PR.
#
# Isolation: `gh` is a recording stub via RECEIPT_CARRY_GH, repos are throwaway
# `git init` trees under mktemp. No network, no status posted, no live path.
set -uo pipefail
export KIPI_NOTIFY=/usr/bin/true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FX="$HERE/fixtures/receipt-carry"
SCRIPT="${RECEIPT_CARRY_SCRIPT:-$HERE/../receipt-carry-approval.sh}"
export REVIEWER_TOKEN_LIB="${REVIEWER_TOKEN_LIB:-$HERE/../reviewer-token-lib.sh}"
unset KIPI_REVIEWER_TOKEN_ENV GH_TOKEN 2>/dev/null || true
PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check_eq() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (want '$2', got '$3')"; fi; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/receipt-reattest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
STUB="$TMP/gh"; CALLS="$TMP/calls"
cat > "$STUB" <<STUBEOF
#!/usr/bin/env bash
echo "\$*" >> "$CALLS"
case "\$*" in
  *"-X POST"*) exit 0 ;;
  *"/commits/\$STUB_REVIEWED/statuses"*) cat "\$STUB_REVIEWED_PAYLOAD" ;;
  *"/commits/"*"/statuses"*) cat "\$STUB_HEAD_PAYLOAD" ;;
esac
STUBEOF
chmod +x "$STUB"

PJ=plugins/kp/.claude-plugin/plugin.json
pj() {  # pj <version> <description>
  printf '{\n  "name": "kp",\n  "version": "%s",\n  "description": "%s"\n}\n' "$1" "$2"
}

# mkcase <dir> <head-version> <head-description> <extra-edit: none|pr-file|revert|delete>
# main: 1.13.69 -> 1.13.71 (+ b.txt). PR: a.txt edited, version 1.13.70 (REVIEWED).
# HEAD = merge of main into the PR, version line hand-resolved to <head-version>.
mkcase() {
  local d="$1" hv="$2" hd="$3" extra="$4"
  g() { git -C "$d" "$@"; }
  git init -q -b main "$d"
  g config user.email t@t; g config user.name t; g config commit.gpgsign false
  mkdir -p "$d/plugins/kp/.claude-plugin"
  pj 1.13.69 base > "$d/$PJ"; echo one > "$d/a.txt"; echo c0 > "$d/c.txt"; echo d > "$d/d.txt"
  g add -A; g commit -q -m base
  g checkout -q -b pr
  pj 1.13.70 base > "$d/$PJ"; echo pr-change > "$d/a.txt"; [ "$extra" = "delete" ] && git -C "$d" rm -q d.txt
  g add -A; g commit -q -m "pr work"; REVIEWED="$(g rev-parse HEAD)"
  g checkout -q main
  pj 1.13.71 "$([ "$extra" = main-desc ] && echo mdesc || echo base)" > "$d/$PJ"; echo b > "$d/b.txt"; echo c-main-fix > "$d/c.txt"
  g add -A; g commit -q -m "main bump"
  g checkout -q pr
  g merge -q --no-edit main >/dev/null 2>&1 || true
  pj "$hv" "$hd" > "$d/$PJ"
  [ "$extra" = "pr-file" ] && echo sneaky >> "$d/a.txt"
  [ "$extra" = "revert" ] && g checkout -q "$REVIEWED" -- c.txt
  g add -A; g commit -q -m "merge main"; HEAD_SHA="$(g rev-parse HEAD)"
}
run() {  # run <dir> -> number of POSTs; exit code in RC
  : > "$CALLS"
  STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" STUB_HEAD_PAYLOAD="$FX/head-absent.json" \
    RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" --reattest-version "$1" "$REVIEWED" "$HEAD_SHA" "o/r" main >/dev/null 2>&1
  RC=$?
  grep -c -- "-X POST" "$CALLS" || true
}

echo "re-attest (version-line merge resolution only)"
mkcase "$TMP/ok" 1.13.72 base none
check_eq "version line only, greater than main: carried"            "1"  "$(run "$TMP/ok")"
run "$TMP/ok" >/dev/null
check_eq "carried exits 0"                                          "0"  "$RC"
mkcase "$TMP/eq" 1.13.71 base none
check_eq "version equal to main: refused"                           "0"  "$(run "$TMP/eq")"
run "$TMP/eq" >/dev/null
check_eq "refusal exits 10"                                         "10" "$RC"
mkcase "$TMP/lo" 1.13.70 base none
check_eq "version lower than main: refused"                         "0"  "$(run "$TMP/lo")"
mkcase "$TMP/other" 1.13.72 base pr-file
check_eq "any other PR file differing: refused"                     "0"  "$(run "$TMP/other")"
mkcase "$TMP/field" 1.13.72 changed none
check_eq "version plus another plugin.json field: refused"          "0"  "$(run "$TMP/field")"
mkcase "$TMP/revert" 1.13.72 base revert
check_eq "version bump that silently reverts a main change: refused" "0" "$(run "$TMP/revert")"
mkcase "$TMP/del" 1.13.72 base delete
check_eq "a PR that deletes a file can still use the mode"          "1"  "$(run "$TMP/del")"
mkcase "$TMP/mdr" 1.13.72 base main-desc
check_eq "head reverts main's own non-version plugin.json edit: refused" "0" "$(run "$TMP/mdr")"
mkcase "$TMP/mdk" 1.13.72 mdesc main-desc
check_eq "head keeps main's plugin.json edit and bumps: carried"        "1" "$(run "$TMP/mdk")"
mkcase "$TMP/nm" 1.13.72 base none
: > "$CALLS"
STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" STUB_HEAD_PAYLOAD="$FX/head-absent.json" \
  RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" "$TMP/nm" "$REVIEWED" "$HEAD_SHA" "o/r" >/dev/null 2>&1
check_eq "the default mode still refuses the same head"             "0"  "$(grep -c -- '-X POST' "$CALLS" || true)"

if [ -z "${RECEIPT_CARRY_SCRIPT:-}" ]; then
  echo "mutation (each mutant must fail this file)"
  mutate() {
    local m="$TMP/mutant.sh"; sed "$2" "$SCRIPT" > "$m"
    if cmp -s "$m" "$SCRIPT"; then fail "mutant '$1' changed nothing"; return; fi
    if RECEIPT_CARRY_SCRIPT="$m" bash "${BASH_SOURCE[0]}" >/dev/null 2>&1; then fail "mutant '$1' SURVIVED"; else pass "mutant '$1' killed"; fi
  }
  mutate "strictly-greater guard removed" 's/^  version_gt "\$hv" "\$mv"$/  true/'
  mutate "merge-result reference swapped for reviewed sha" 's/merge-tree --write-tree --no-messages "\$mainref" "\$reviewed"/rev-parse "$reviewed^{tree}"/'
  mutate "main's fields no longer required"  's/\[ "\$hrest" = "\$mrest" \] || return 1/true/'
  mutate "other-fields guard removed"          's/\[ "\$hrest" = "\$rrest" \]/true/'
fi
echo; echo "passed $PASS, failed $FAIL"
[ "$FAIL" = "0" ]
