#!/bin/bash
# Tests for kipi-dispatch-pinned.sh.
#
# Everything runs against throwaway repos in mktemp -d. Nothing here touches
# ~/projects/kipi-system, ~/.config/kipi, or any launchd job: the wrapper's three
# real paths are injected via KIPI_REPO_MAIN / KIPI_DISPATCH_CHECKOUT /
# KIPI_DISPATCH_LOG, and kipi-dispatch.sh is replaced by a stub that only prints
# which checkout it was handed.
#
# The load-bearing test is TEST 2. It is paired with a negative self-test that
# runs a FORCING variant of the wrapper and proves the assertion goes red, because
# an assertion that has only ever been green cannot tell "the wrapper refuses to
# force" from "the test cannot see forcing".
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$HERE/kipi-dispatch-pinned.sh"
fails=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n     %s\n' "$1" "${2:-}"; fails=$((fails + 1)); }

# Build an upstream repo plus a "main checkout" of it, with a dispatch stub.
build_fixture() {
  local root; root="$(mktemp -d)"
  git init -q -b main "$root/upstream"
  cat >"$root/upstream/kipi-dispatch.sh" <<'STUB'
#!/bin/bash
echo "DISPATCH_RAN KIPI_REPO=$KIPI_REPO"
STUB
  echo "v1" >"$root/upstream/marker.txt"
  git -C "$root/upstream" add -A
  git -C "$root/upstream" -c user.email=t@t -c user.name=t commit -qm init
  git clone -q "$root/upstream" "$root/main"
  echo "$root"
}

run_wrapper() {  # $1=root ; echoes stdout, log goes to $1/log
  KIPI_REPO_MAIN="$1/main" \
  KIPI_DISPATCH_CHECKOUT="$1/pinned" \
  KIPI_DISPATCH_LOG="$1/log" \
    bash "$2" 2>&1
}

# ---------------------------------------------------------------------------
# TEST 1: it creates the pinned checkout and hands THAT to dispatch.
# ---------------------------------------------------------------------------
R="$(build_fixture)"
out="$(run_wrapper "$R" "$WRAPPER")"
[ -e "$R/pinned/.git" ] || bad "T1 creates the pinned checkout" "no .git at $R/pinned"
case "$out" in
  *"DISPATCH_RAN KIPI_REPO=$R/pinned"*) ok "T1 dispatch receives the pinned checkout" ;;
  *) bad "T1 dispatch receives the pinned checkout" "got: $out" ;;
esac
# It must NOT hand over the shared checkout -- that is the whole defect.
case "$out" in
  *"KIPI_REPO=$R/main"*) bad "T1 must not fall back to the shared checkout" "got: $out" ;;
  *) ok "T1 does not hand dispatch the shared checkout" ;;
esac

# ---------------------------------------------------------------------------
# TEST 2: a DIRTY pinned checkout is not forced green. The guard keeps its teeth.
# ---------------------------------------------------------------------------
# Advance upstream so the pinned tree is genuinely behind, then dirty it. A
# wrapper that forced the tree would discard the edit and let dispatch run on a
# checkout nobody verified. The correct behaviour is to leave it dirty, log the
# refusal, and let kipi-dispatch.sh's own stale_check() decide.
dirty_case() {  # $1=wrapper-under-test ; echoes "PRESERVED" or "DISCARDED"
  local R; R="$(build_fixture)"
  run_wrapper "$R" "$WRAPPER" >/dev/null 2>&1          # create pinned at v1
  echo "v2" >"$R/upstream/marker.txt"
  git -C "$R/upstream" -c user.email=t@t -c user.name=t commit -qam v2
  echo "LOCAL-EDIT" >"$R/pinned/marker.txt"            # dirty the pinned tree
  run_wrapper "$R" "$1" >/dev/null 2>&1
  if [ "$(cat "$R/pinned/marker.txt")" = "LOCAL-EDIT" ]; then echo "PRESERVED"; else echo "DISCARDED"; fi
}

verdict="$(dirty_case "$WRAPPER")"
[ "$verdict" = "PRESERVED" ] \
  && ok "T2 a dirty pinned checkout is NOT forced (guard keeps its teeth)" \
  || bad "T2 a dirty pinned checkout is NOT forced" "wrapper discarded the local edit"

# NEGATIVE SELF-TEST for T2: the same assertion against a forcing variant must
# come back DISCARDED. If this prints PRESERVED too, T2 proves nothing.
FORCER="$(mktemp -d)/forcing-wrapper.sh"
sed 's/checkout --detach --quiet origin\/main/checkout --detach --force --quiet origin\/main/' \
    "$WRAPPER" >"$FORCER"
grep -q -- "--force" "$FORCER" || bad "T2-neg mutant did not apply" "sed produced no --force"
neg="$(dirty_case "$FORCER")"
[ "$neg" = "DISCARDED" ] \
  && ok "T2-neg the assertion CAN fail (forcing variant discarded the edit)" \
  || bad "T2-neg the assertion can fail" "forcing variant also came back $neg -- T2 is decorative"

# ---------------------------------------------------------------------------
# TEST 3: no forcing verb anywhere in the wrapper.
# ---------------------------------------------------------------------------
# Grep-the-tree guard. The wrapper is allowed to name these only in prose, so
# comments are stripped before matching.
code="$(sed 's/[[:space:]]*#.*$//' "$WRAPPER")"
for verb in 'reset --hard' 'checkout -f' 'checkout --force' 'clean -fd' 'push --force'; do
  case "$code" in
    *"$verb"*) bad "T3 wrapper must not use '$verb'" "found in executable lines" ;;
    *) : ;;
  esac
done
ok "T3 wrapper contains no forcing verb outside comments"

# ---------------------------------------------------------------------------
# TEST 4: if the pinned checkout cannot be made, it refuses instead of falling back.
# ---------------------------------------------------------------------------
R2="$(build_fixture)"
: >"$R2/pinned"          # a FILE where the checkout should go -> worktree add fails
out2="$(run_wrapper "$R2" "$WRAPPER")"
case "$out2" in
  *DISPATCH_RAN*) bad "T4 refuses when the pinned checkout cannot be created" "dispatch still ran: $out2" ;;
  *) ok "T4 refuses when the pinned checkout cannot be created" ;;
esac
grep -q "NOT falling back" "$R2/log" 2>/dev/null \
  && ok "T4 logs the refusal loudly" \
  || bad "T4 logs the refusal loudly" "no refusal line in the log"

[ "$fails" -eq 0 ] && { echo "PASS: dispatch-pinned"; exit 0; }
echo "FAIL: $fails check(s)"; exit 1
