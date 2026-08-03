#!/bin/bash
# Pairs with: notify-callsite-audit.py (PR #72 review, minor).
#
# WHY A PLANTED-PRODUCER FIXTURE. The audit was wired into `kipi check` as Gate
# 1.2b and described as enforcement while catching 2 of the 4 ways this repo
# actually invokes the notifier. Nothing measured that, because the only evidence
# was "it reports OK on the real repo" -- and a detector that finds nothing looks
# identical to a repo with nothing to find. Planting known-bad producers is the
# only way to tell those two apart.
#
# THREE FAULTS, EACH MASKING THE NEXT:
#   1. INVOKE hardcoded `bash\s+`, so a direct exec (`"$NOTIFY" "msg"`, valid
#      because the file is +x) and an `sh`-prefixed call were invisible.
#   2. The --kind window matched COMMENTS, so a bare call under
#      `# --kind receipt is what a good call looks like` was excused by the very
#      sentence describing what it failed to do.
#   3. The window looked forward 4 lines with no stop, so a LATER, DIFFERENT
#      call's --kind cleared an earlier bare one.
#
# The negative half matters as much: an unanchored fix for #1 produced 12 false
# positives in this repo (assignments, `-x` tests, chmod, echo prose). A gate that
# cries wolf gets switched off, so both directions are pinned here.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$(cd "$HERE/.." && pwd)/notify-callsite-audit.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { printf '  \033[0;32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[0;31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

mkdir -p "$WORK/q-system/.q-system/scripts"
cd "$WORK" && git init -q .
cat > q-system/.q-system/scripts/planted.sh <<'FIXTURE'
#!/bin/bash
NOTIFY="${KIPI_NOTIFY:-/x/slack-notify.sh}"
bash "$NOTIFY" "bare one: the shape the audit was written for"
"$NOTIFY" "bare two: direct exec, the file is +x"
sh "$NOTIFY" "bare three: sh instead of bash"
#    --kind receipt is what a GOOD call looks like
bash "$NOTIFY" "bare four: window poisoned by the comment above"
bash "$NOTIFY" --kind receipt "good one: declares a kind"
"$NOTIFY" --kind decision --class spend "good two: direct exec, declares a kind"
if [ -x "$NOTIFY" ]; then echo "guard, not a call"; fi
chmod +x "$NOTIFY"
echo "the notifier lives at $NOTIFY" >&2
FIXTURE
git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm fixture >/dev/null 2>&1

OUT="$(python3 "$AUDIT" --repo "$WORK" 2>&1)"

echo "== every bare producer is caught =="
for n in one two three four; do
  printf '%s' "$OUT" | grep -q "bare $n" \
    && ok "catches 'bare $n'" \
    || bad "MISSED 'bare $n' -- the gate reports OK on a file that is not OK" "$OUT"
done

echo
echo "== nothing correct is flagged =="
for pat in "good one" "good two" "guard, not a call" "chmod" "the notifier lives at"; do
  printf '%s' "$OUT" | grep -q "$pat" \
    && bad "FALSE POSITIVE on '$pat' -- a noisy gate gets switched off" "$OUT" \
    || ok "does not flag '$pat'"
done

echo
echo "== a clean tree really is reported clean =="
mkdir -p "$WORK/clean/q-system/.q-system/scripts" && cd "$WORK/clean" && git init -q .
cat > q-system/.q-system/scripts/good.sh <<'CLEAN'
#!/bin/bash
NOTIFY=/x/slack-notify.sh
bash "$NOTIFY" --kind receipt "handled by the machine"
CLEAN
git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm clean >/dev/null 2>&1
python3 "$AUDIT" --repo "$WORK/clean" >/dev/null 2>&1 \
  && ok "exit 0 on a tree where every call declares a kind" \
  || bad "a compliant tree was reported as violating"

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
