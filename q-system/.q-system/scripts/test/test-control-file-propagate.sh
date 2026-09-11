#!/usr/bin/env bash
# Negative-first self-test for control-file-propagate.py (ASK-755).
#
# THE TEST THAT MATTERS IS THE REFUSAL, NOT THE WRITE. A propagator that copies is
# trivial to make green; the property being bought here is that it does NOT copy
# over a local edit or over uncommitted work. So OTHER and DIRTY are asserted
# FIRST, and each is asserted by the file's CONTENT being unchanged on disk -- not
# by the word "REFUSED" appearing in the output. A run that printed the refusal
# and wrote anyway would pass a text-only assertion (scar: "or across signals
# hides the alarm").
#
# Runs entirely against throwaway git repos under mktemp -d. Nothing here touches
# a live checkout, which is the fable-discipline lint's rule and also the reason
# this file can be run unattended.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROP="$SCRIPT_DIR/../control-file-propagate.py"
REL="q-system/.q-system/scripts/linear-worker.sh"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL %s: %s\n' "$1" "$2"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkrepo() {
  local root="$1"
  mkdir -p "$root/$(dirname "$REL")"
  git -C "$root" init -q 2>/dev/null || git init -q "$root"
  git -C "$root" config user.email t@t.local
  git -C "$root" config user.name  tester
}

commit_worker() {
  local root="$1" body="$2" msg="$3"
  printf '%s\n' "$body" > "$root/$REL"
  git -C "$root" add -A
  # Distinct message AND distinct content per commit: identical file + message +
  # second produces the identical commit sha across "different" fixture repos,
  # which silently collapses two cases into one (git-fixture scar).
  git -C "$root" commit -q -m "$msg"
}

# --- skeleton with two generations of the control file ---------------------
SKEL="$TMP/skel"; mkrepo "$SKEL"
commit_worker "$SKEL" "worker v1 -- the ancestor" "gen1"
V1_HASH="$(shasum -a 256 "$SKEL/$REL" | awk '{print $1}')"
commit_worker "$SKEL" "worker v2 -- skeleton HEAD" "gen2"
HEAD_HASH="$(shasum -a 256 "$SKEL/$REL" | awk '{print $1}')"
[ "$V1_HASH" != "$HEAD_HASH" ] || { echo "fixture broken: both generations hash the same"; exit 2; }

# --- targets ---------------------------------------------------------------
T_OLD="$TMP/t_old";     mkrepo "$T_OLD";     commit_worker "$T_OLD"   "worker v1 -- the ancestor" "old-target"
T_NEW="$TMP/t_new";     mkrepo "$T_NEW";     commit_worker "$T_NEW"   "worker v2 -- skeleton HEAD" "new-target"
T_OTHER="$TMP/t_other"; mkrepo "$T_OTHER";   commit_worker "$T_OTHER" "worker -- HAND EDITED locally" "other-target"
T_DIRTY="$TMP/t_dirty"; mkrepo "$T_DIRTY";   commit_worker "$T_DIRTY" "worker v1 -- the ancestor" "dirty-target"
printf 'worker v1 -- the ancestor\nsomeone is mid-edit\n' > "$T_DIRTY/$REL"

run_apply() { python3 "$PROP" --skeleton "$SKEL" --file "$REL" --target "$1" --apply 2>&1; }
hash_of()   { shasum -a 256 "$1/$REL" | awk '{print $1}'; }

# === 1. OTHER is refused, and the bytes are untouched ======================
BEFORE="$(hash_of "$T_OTHER")"
OUT="$(run_apply "$T_OTHER")"; RC=$?
AFTER="$(hash_of "$T_OTHER")"
if [ "$BEFORE" = "$AFTER" ]; then ok "OTHER: file bytes unchanged"; else bad "OTHER" "the file was overwritten"; fi
[ "$RC" -ne 0 ] && ok "OTHER: exit non-zero" || bad "OTHER" "exit was 0, a refusal must fail the run"
case "$OUT" in *REFUSED*OTHER*) ok "OTHER: named in output" ;; *) bad "OTHER" "output did not name OTHER: $OUT" ;; esac

# === 2. DIRTY is refused, and the mid-edit survives ========================
BEFORE="$(hash_of "$T_DIRTY")"
OUT="$(run_apply "$T_DIRTY")"; RC=$?
AFTER="$(hash_of "$T_DIRTY")"
if [ "$BEFORE" = "$AFTER" ]; then ok "DIRTY: uncommitted edit survived"; else bad "DIRTY" "the mid-edit was overwritten"; fi
[ "$RC" -ne 0 ] && ok "DIRTY: exit non-zero" || bad "DIRTY" "exit was 0"
case "$OUT" in *REFUSED*DIRTY*) ok "DIRTY: named in output" ;; *) bad "DIRTY" "output did not name DIRTY: $OUT" ;; esac

# === 3. NEW is a no-op ======================================================
BEFORE="$(hash_of "$T_NEW")"
OUT="$(run_apply "$T_NEW")"; RC=$?
AFTER="$(hash_of "$T_NEW")"
[ "$BEFORE" = "$AFTER" ] && ok "NEW: unchanged" || bad "NEW" "an already-current file was rewritten"
[ "$RC" -eq 0 ] && ok "NEW: exit 0" || bad "NEW" "exit was $RC"

# === 4. survey does NOT write (the default must be safe) ===================
BEFORE="$(hash_of "$T_OLD")"
python3 "$PROP" --skeleton "$SKEL" --file "$REL" --target "$T_OLD" >/dev/null 2>&1
AFTER="$(hash_of "$T_OLD")"
[ "$BEFORE" = "$AFTER" ] && ok "survey: wrote nothing without --apply" || bad "survey" "the default mode wrote to disk"

# === 5. ONLY NOW the positive case: OLD is written to HEAD =================
OUT="$(run_apply "$T_OLD")"; RC=$?
AFTER="$(hash_of "$T_OLD")"
[ "$AFTER" = "$HEAD_HASH" ] && ok "OLD: written to skeleton HEAD" || bad "OLD" "hash is $AFTER, wanted $HEAD_HASH"
[ "$RC" -eq 0 ] && ok "OLD: exit 0" || bad "OLD" "exit was $RC -- $OUT"

# === 6. a dirty SKELETON refuses (never propagate uncommitted source) ======
printf 'worker v2 -- skeleton HEAD\nuncommitted skeleton edit\n' > "$SKEL/$REL"
T_OLD2="$TMP/t_old2"; mkrepo "$T_OLD2"; commit_worker "$T_OLD2" "worker v1 -- the ancestor" "old-target-2"
BEFORE="$(hash_of "$T_OLD2")"
OUT="$(run_apply "$T_OLD2")"; RC=$?
AFTER="$(hash_of "$T_OLD2")"
[ "$BEFORE" = "$AFTER" ] && ok "dirty skeleton: target untouched" || bad "dirty-skeleton" "propagated uncommitted source"
[ "$RC" -ne 0 ] && ok "dirty skeleton: exit non-zero" || bad "dirty-skeleton" "exit was 0"

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
