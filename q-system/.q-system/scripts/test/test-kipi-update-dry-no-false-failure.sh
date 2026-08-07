#!/usr/bin/env bash
# Reproducer for sp-f6733ee3: `kipi update --dry` reported FAILED for a healthy
# instance that merely had TRACKED content under a directory named `build`.
#
# Pairs with: the git-tracked check in model_rsync_excludes() (kipi-update.sh).
#
# THE MECHANISM. The model build rsyncs the instance into a throwaway clone
# excluding any directory whose basename is a build-cache name, then copies
# `.git` VERBATIM. A tracked file under such a directory is therefore absent
# from the model worktree while still present in the model index, so git reports
# a deletion, the tracked-changes predicate reads the tree as dirty, and the
# instance is abandoned. Measured 2026-08-06 on interview-coach:
# `D design-room/build/gate-report.md`, while live the file is tracked, present,
# and the tree has zero tracked changes.
#
# WHY CASE 2 EXISTS. Case 1 alone passes if the fix simply stops refusing
# anything -- deleting the dirty-tree predicate outright would make it green.
# Case 2 holds the other side: an instance with a REAL tracked modification must
# still be refused. A fix that satisfies one and not the other is not a fix.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
SCRIPT="${KIPI_UPDATE_UNDER_TEST:-$ROOT/kipi-update.sh}"
[ -f "$SCRIPT" ] || { echo "missing $SCRIPT"; exit 1; }

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

build_fixture() {  # build_fixture <workdir> <dirty:yes|no>
  local W="$1" dirty="$2" SK="$1/skel" INST="$1/inst"
  mkdir -p "$SK/q-system/.q-system/scripts" "$SK/q-system/.q-system/state"
  cp "$SCRIPT" "$SK/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$ROOT/kipi-update-deletion-guard.py" \
     "$ROOT/validate-separation.py" "$SK/"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$SK/q-system/.q-system/scripts/"
  cat > "$SK/q-system/.q-system/state/propagation-leak-baseline.json" <<'J'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
J
  printf 'skeleton v2\n' > "$SK/q-system/tracked.md"
  ( cd "$SK" && G init -q && G add -A && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$INST" > "$SK/instance-registry.json"

  # THE DEFECT SHAPE: authored, TRACKED content under a `build/`-named dir.
  mkdir -p "$INST/q-system" "$INST/design-room/build"
  printf 'skeleton v1\n' > "$INST/q-system/tracked.md"
  printf '# design-room gate report (authored, not a build cache)\n' \
    > "$INST/design-room/build/gate-report.md"
  ( cd "$INST" && G init -q && G add -A && G commit -qm inst )
  # Case 2 only: a REAL tracked modification, which must still be refused.
  if [ "$dirty" = "yes" ]; then
    printf 'founder edit in progress\n' >> "$INST/q-system/tracked.md"
  fi
}

# Reports FAILED (or refused) for testinst?
refused() {  # refused <log>
  grep -q 'dirty working tree; refusing' "$1" && echo yes || echo no
}

echo "== 1. THE DEFECT: tracked content under build/ must NOT fail a clean instance =="
W1="$(mktemp -d)"; build_fixture "$W1" no
bash "$W1/skel/kipi-update.sh" --dry-run >"$W1/out.log" 2>&1
if [ "$(refused "$W1/out.log")" = "no" ]; then
  ok "a clean instance with tracked design-room/build/ content is NOT refused"
else
  bad "THE DEFECT: healthy instance refused; model saw a phantom deletion"
  grep -A4 'blocked by dirty' "$W1/out.log" | head -5 | sed 's/^/      /'
fi

echo
echo "== 2. THE OTHER SIDE: a genuinely dirty instance must STILL be refused =="
# Without this, deleting the dirty-tree predicate would satisfy case 1.
W2="$(mktemp -d)"; build_fixture "$W2" yes
bash "$W2/skel/kipi-update.sh" --dry-run >"$W2/out.log" 2>&1
if [ "$(refused "$W2/out.log")" = "yes" ]; then
  ok "a real tracked modification is still refused (the guard still guards)"
else
  bad "REGRESSION: a genuinely dirty instance was allowed through"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
echo "  logs: $W1/out.log  $W2/out.log"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: --dry refuses real dirt and only real dirt"
