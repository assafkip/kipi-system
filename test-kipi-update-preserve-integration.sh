#!/bin/bash
# End-to-end proof that kipi-update.sh preserves instance-only files.
#
# CONVERTED 2026-08-10 (ASK-608). The previous version lifted the snapshot ->
# preserve-scan -> rsync --delete -> restore sequence "verbatim from
# kipi-update.sh" into its own body. That proves the ALGORITHM and can
# structurally never observe two things that matter more:
#
#   * whether kipi-update.sh still CALLS the sequence, and
#   * which bash interprets it.
#
# Both went wrong the same day. The ASK-607 abort (`arr[*]` on an empty array is
# an unbound-variable error on /bin/bash 3.2, which is the only bash the fleet
# has) shipped with this file green, because a re-implementation runs under the
# TEST's interpreter and never reaches the code under test. `reimplementing-test-lint.py`
# now flags this shape; that lint flagged this very file, which is why it changed.
#
# So: the RED case still demonstrates the raw defect, because a reproducer that
# cannot show the bad behaviour is worthless. The GREEN case now drives the REAL
# kipi-update.sh through its real entry point and asserts the preservation
# messages the running program emits.
#
# Only --dry-run is invoked, against a throwaway skeleton and instance. Nothing
# here can reach a registered instance.
#
# Run: bash test-kipi-update-preserve-integration.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

TARGET="q-system/.q-system/scripts/instance-only.py"

echo "=== RED: a raw rsync --delete destroys a tracked instance-only file ==="
# The 2026-06-24 failure, reproduced. fractional-cxo lost its income scanners
# this way for 6 days: the snapshot only ever covered UNTRACKED files, and a
# script the instance had COMMITTED inside the synced tree had no protection.
RED="$T/red"
mkdir -p "$RED/skeleton/q-system/.q-system/scripts" "$RED/instance/q-system/.q-system/scripts"
( cd "$RED/skeleton" && echo skel > q-system/.q-system/scripts/skel.py &&
  g init -q . && g add -A && g commit -qm init ) >/dev/null 2>&1
ARCH="$RED/archive"; mkdir -p "$ARCH"
git -C "$RED/skeleton" archive --format=tar HEAD -- q-system/ | tar -x -C "$ARCH"
( cd "$RED/instance" && echo skel > q-system/.q-system/scripts/skel.py &&
  echo MINE > "$TARGET" && g init -q . && g add -A && g commit -qm init ) >/dev/null 2>&1
rsync -a --delete "$ARCH/q-system/" "$RED/instance/q-system/" 2>/dev/null
if [ -f "$RED/instance/$TARGET" ]; then
  echo "  FAIL: the file survived a raw --delete, so this reproducer proves nothing"
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: reproduced -- $TARGET was deleted with no protection"
fi

echo ""
echo "=== GREEN: the REAL kipi-update.sh preserves it ==="
SKEL="$T/green/skeleton"
INST="$T/green/instance"
mkdir -p "$T/green"
# Full skeleton copy: the updater runs fail-closed preflight gates that each
# require their own script, so a stub tree aborts before reaching the code under
# test -- which would be a green run that measured nothing.
cp -R "$REAL/q-system" "$SKEL/q-system" 2>/dev/null || { mkdir -p "$SKEL"; cp -R "$REAL/q-system" "$SKEL/q-system"; }
cp "$REAL"/*.py "$REAL"/*.sh "$SKEL/" 2>/dev/null
cp "$REAL"/*.json "$REAL"/*.yml "$SKEL/" 2>/dev/null
cp -R "$REAL/plugins" "$SKEL/plugins" 2>/dev/null
chmod +x "$SKEL/kipi-update.sh"
echo "skeleton-owned" > "$SKEL/q-system/.q-system/scripts/skel-tool.py"

cat > "$SKEL/instance-registry.json" <<JSON
{
  "skeleton": "$SKEL",
  "instances": [
    { "name": "fake", "path": "$INST", "subtree_prefix": "q-system",
      "instance_q_dir": "q-fake", "type": "subtree", "has_git": true }
  ],
  "standalone": [],
  "eliminated": []
}
JSON
( cd "$SKEL" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm skel ) >/dev/null 2>&1

mkdir -p "$INST/q-system/.q-system/scripts"
echo "skeleton-owned" > "$INST/q-system/.q-system/scripts/skel-tool.py"
echo "MINE" > "$INST/$TARGET"                       # TRACKED, instance-only
( cd "$INST" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1
echo "NOTES" > "$INST/q-system/.q-system/scripts/untracked-note.txt"   # UNTRACKED

LOG="$T/green/run.log"
/bin/bash "$SKEL/kipi-update.sh" --dry-run --only fake > "$LOG" 2>&1

if ! grep -q -- "--- fake (subtree) ---" "$LOG"; then
  echo "  FAIL: the run never reached the instance, so nothing was measured"
  tail -4 "$LOG" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
else
  # Positive signals emitted by the RUNNING program, not the absence of a
  # deletion line -- an absence would pass against a run that died early.
  if grep -q "tracked instance-only file(s) would be deleted" "$LOG" &&
     grep -q "instance-only.py" "$LOG"; then
    echo "  OK: the updater announced it was preserving the tracked file"
  else
    echo "  FAIL: no preservation warning for $TARGET"
    FAILURES=$((FAILURES + 1))
  fi
  if grep -q "restored untracked: $TARGET" "$LOG"; then
    echo "  OK: the tracked instance-only file was restored after --delete"
  else
    echo "  FAIL: $TARGET was not restored"
    grep -i "restored" "$LOG" | head -3 | sed 's/^/      /'
    FAILURES=$((FAILURES + 1))
  fi
  if grep -q "restored untracked: q-system/.q-system/scripts/untracked-note.txt" "$LOG"; then
    echo "  OK: the untracked file was restored too"
  else
    echo "  FAIL: the untracked file was not restored"
    FAILURES=$((FAILURES + 1))
  fi
fi

BASELINE_REL="q-system/.q-system/claude-integrity-baseline.json"
ARMED_REL="q-system/.q-system/.claude-integrity-armed"
TRIPWIRE="$REAL/q-system/.q-system/scripts/claude-integrity-tripwire.py"

# A recorder, never the real sink. notify() resolves
# $root/q-system/.q-system/scripts/slack-notify.sh unless KIPI_NOTIFY overrides
# it, and this box HAS ~/.config/kipi/slack-webhook -- so an unstubbed run pages
# the founder with a SECURITY alarm from a test. Relying on "the temp tree has no
# slack-notify.sh" would be an accidental shield, not isolation: it goes away the
# day the fixture copies more of the skeleton. Stub the seam explicitly, then
# ASSERT on the recorder, because the page IS the harm and exit 2 alone would
# pass on a tree that refused for some unrelated reason.
NOTIFY_LOG="$T/notify.log"
cat > "$T/fake-notify.sh" <<'STUB'
#!/bin/bash
printf '%s\n' "$1" >> "$NOTIFY_LOG"
STUB
chmod +x "$T/fake-notify.sh"

echo ""
echo "=== RED: a baseline the skeleton ONCE TRACKED is deleted, and the tripwire refuses ==="
# THE SHAPE THIS FILE COULD NOT SEE (measured 2026-08-14, 6 instances). Both cases above use a
# NEVER-TRACKED instance-only file, which preserve-scan rule 3 protects. The
# baseline is the opposite shape: the skeleton DID track
# q-system/.q-system/claude-integrity-baseline.json (e25734cb / 629d01b2,
# ASK-282) and then deleted it, so rule 3 reads a deliberate skeleton deletion
# and correctly lets it propagate. Every guard in this file was green while
# 6 instances lost their baseline.
#
# Reproducer, so it reimplements the sequence on purpose (see the header): the
# point is to show the raw defect. What it does NOT reimplement is the two
# programs whose verdicts decide the outcome -- the REAL preserve-scan and the
# REAL tripwire both run here. This case stays red-capable forever: it is the
# harm, not the fix. The fix is proved by the two cases below.
R2="$T/red2"
mkdir -p "$R2/skeleton/q-system/.q-system/scripts" "$R2/instance/q-system/.q-system/scripts"
( cd "$R2/skeleton" && g init -q . &&
  echo skel > q-system/.q-system/scripts/skel.py &&
  echo '{"files":{}}' > "$BASELINE_REL" &&
  g add -A && g commit -qm "ASK-282: skeleton once tracked the baseline" &&
  rm "$BASELINE_REL" && g add -A && g commit -qm "ASK-282 round 2: instance-local, untrack it"
) >/dev/null 2>&1

# The instance committed its own baseline -- which is exactly what
# kipi-update.sh's system-state commit does to it.
( cd "$R2/instance" && g init -q . &&
  echo skel > q-system/.q-system/scripts/skel.py &&
  echo '{"files":{"x":"sha"}}' > "$BASELINE_REL" &&
  : > "$ARMED_REL" &&
  g add -A -f && g commit -qm "instance state" ) >/dev/null 2>&1

if ! git -C "$R2/instance" ls-files --error-unmatch -- "$BASELINE_REL" >/dev/null 2>&1; then
  echo "  FAIL: fixture never tracked the baseline, so this case measures nothing"
  FAILURES=$((FAILURES + 1))
else
  A2="$T/red2-archive"; mkdir -p "$A2"
  git -C "$R2/skeleton" archive --format=tar HEAD -- q-system/ | tar -x -C "$A2"

  # The REAL scanner decides. Not a stand-in for it.
  PRESERVED="$(python3 "$REAL/kipi-update-preserve-scan.py" \
                 --skeleton-archive "$A2" --instance "$R2/instance" \
                 --prefix q-system --skeleton-git "$R2/skeleton" 2>/dev/null)"
  # The two files sit in the SAME directory and go through the SAME scan, and
  # the scan must answer them differently. That pairing is the control: if the
  # armed marker were not preserved here, a deleted baseline would prove nothing
  # about rule 3 -- it would just mean --delete removed everything.
  if ! printf '%s\n' "$PRESERVED" | grep -qx -- "$ARMED_REL"; then
    echo "  FAIL: preserve-scan did not protect the armed marker either; no discrimination to show"
    FAILURES=$((FAILURES + 1))
  elif printf '%s\n' "$PRESERVED" | grep -qx -- "$BASELINE_REL"; then
    echo "  FAIL: preserve-scan protected the baseline, so the reproducer is wrong"
    FAILURES=$((FAILURES + 1))
  else
    echo "  OK: preserve-scan preserved the armed marker and NOT the baseline (rule 3)"
    # Snapshot + restore the preserved set, because that is what the updater does
    # around its rsync. Skipping it would delete the armed marker too and the
    # tripwire would then refuse for the wrong reason.
    SNAP2="$T/red2-snap"; mkdir -p "$SNAP2"
    while IFS= read -r rel; do
      [ -n "$rel" ] || continue
      mkdir -p "$SNAP2/$(dirname "$rel")" && cp -a "$R2/instance/$rel" "$SNAP2/$rel"
    done <<< "$PRESERVED"
    rsync -a --delete "$A2/q-system/" "$R2/instance/q-system/" 2>/dev/null
    while IFS= read -r rel; do
      [ -n "$rel" ] || continue
      mkdir -p "$R2/instance/$(dirname "$rel")" && cp -a "$SNAP2/$rel" "$R2/instance/$rel"
    done <<< "$PRESERVED"
    if [ -f "$R2/instance/$BASELINE_REL" ]; then
      echo "  FAIL: the baseline survived --delete; no harm to demonstrate"
      FAILURES=$((FAILURES + 1))
    elif [ ! -f "$R2/instance/$ARMED_REL" ]; then
      echo "  FAIL: the armed marker also went; the refusal would not be this defect"
      FAILURES=$((FAILURES + 1))
    else
      # THE ASSERTION THAT MATTERS. The missing file is the symptom; the tripwire
      # refusing every tool call on an armed tree is the harm the founder feels.
      : > "$NOTIFY_LOG"
      KIPI_NOTIFY="$T/fake-notify.sh" NOTIFY_LOG="$NOTIFY_LOG" \
        python3 "$TRIPWIRE" --check --root "$R2/instance" >/dev/null 2>&1
      rc=$?
      if [ "$rc" = "2" ] && grep -q "baseline is MISSING" "$NOTIFY_LOG" 2>/dev/null; then
        echo "  OK: reproduced -- tripwire exit 2 and a SECURITY page on an armed tree"
      else
        echo "  FAIL: expected exit 2 + a SECURITY page, got rc=$rc, page=$(cat "$NOTIFY_LOG" 2>/dev/null | head -1)"
        FAILURES=$((FAILURES + 1))
      fi
    fi
  fi
fi

# --- The fix, driven through the REAL kipi-update.sh -------------------------
# The case above is the harm and stays red-capable forever. These two are the
# fix, and they assert on lines the RUNNING program prints, never on a file the
# test placed itself.
#
# The fixture skeleton must TRACK-THEN-DELETE the baseline, the way the real one
# does (e25734cb / 629d01b2). A fresh `git init` skeleton has never tracked it,
# preserve-scan rule 3 would protect it, and both cases would pass against
# unpatched code -- a fixture built wrong is a gate that cannot fire.
build_skel() {
  local S="$1"
  mkdir -p "$S"
  cp -R "$REAL/q-system" "$S/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$S/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$S/" 2>/dev/null
  cp -R "$REAL/plugins" "$S/plugins" 2>/dev/null
  chmod +x "$S/kipi-update.sh"
  rm -f "$S/$BASELINE_REL" "$S/$ARMED_REL"
  ( cd "$S" && g init -q . &&
    echo '{"files":{}}' > "$BASELINE_REL" && g add -A -f >/dev/null 2>&1 &&
    g commit -qm "skeleton once tracked the baseline (ASK-282)" &&
    rm "$BASELINE_REL" && g add -A >/dev/null 2>&1 &&
    g commit -qm "skeleton untracked it: instance-local" ) >/dev/null 2>&1
}

reg() {  # $1=skeleton $2=instance path
  cat > "$1/instance-registry.json" <<JSON
{
  "skeleton": "$1",
  "instances": [
    { "name": "fake", "path": "$2", "subtree_prefix": "q-system",
      "instance_q_dir": "q-fake", "type": "subtree", "has_git": true }
  ],
  "standalone": [],
  "eliminated": []
}
JSON
}

run_case() {  # $1=label $2=track-the-baseline? $3=logfile
  local S="$T/$1/skeleton" I="$T/$1/instance"
  build_skel "$S"
  reg "$S" "$I"
  mkdir -p "$I/q-system/.q-system/scripts"
  echo "seed" > "$I/q-system/.q-system/scripts/seed.py"
  ( cd "$I" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1
  echo '{"files":{"x":"sha"}}' > "$I/$BASELINE_REL"
  : > "$I/$ARMED_REL"
  if [ "$2" = "tracked" ]; then
    ( cd "$I" && g add -A -f >/dev/null 2>&1 && g commit -qm "instance committed its baseline" ) >/dev/null 2>&1
  fi
  /bin/bash "$S/kipi-update.sh" --dry-run --only fake > "$3" 2>&1
}

echo ""
echo "=== FIX 1: the updater must never COMMIT the baseline (chokepoint) ==="
# Two feeders reach sys_owned_dirty: the SYSTEM_OWNED_PATHS hand list and
# auto-commit.py --system-state, which classifies the whole tree. Committing the
# baseline is what makes it tracked, which is what hands it to rule 3.
L1="$T/fix1.log"
run_case fix1 untracked "$L1"
if ! grep -q -- "--- fake (subtree) ---" "$L1"; then
  echo "  FAIL: the run never reached the instance, so nothing was measured"
  tail -4 "$L1" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
else
  # A BARE indented path is the committed list and nothing else: the block prints
  # its members with `printf '    %s\n'`. Matching the path anywhere in the log
  # instead is what the first draft of this assertion did, and it swallowed the
  # later "restored untracked: <path>" line -- reporting the defect while the
  # chokepoint was in fact holding.
  if grep -qE '^[[:space:]]*q-system/\.q-system/claude-integrity-baseline\.json[[:space:]]*$' "$L1"; then
    echo "  FAIL: the updater committed the baseline (this is the defect)"
    sed -n '/Committing .* system-written file/,+4p' "$L1" | sed 's/^/      | /'
    FAILURES=$((FAILURES + 1))
  else
    echo "  OK: the baseline was not in the system-state commit"
  fi
  # Positive: the chokepoint FIRED. Absence alone would also pass on a run that
  # never classified the baseline at all.
  if grep -q "Leaving instance-local file uncommitted: $BASELINE_REL" "$L1"; then
    echo "  OK: the chokepoint named it and declined to commit it"
  else
    echo "  FAIL: the chokepoint never fired on the baseline"
    FAILURES=$((FAILURES + 1))
  fi
  # Positive signal: untracked means the ordinary snapshot catches it.
  if grep -q "restored untracked: $BASELINE_REL" "$L1"; then
    echo "  OK: it stayed untracked and was restored across the sync"
  else
    echo "  FAIL: the baseline was not restored as untracked after the sync"
    grep -i "baseline" "$L1" | head -3 | sed 's/^/      /'
    FAILURES=$((FAILURES + 1))
  fi
fi

echo ""
echo "=== FIX 2: an ALREADY-TRACKED baseline is untracked, not deleted (migration) ==="
# The 6 instances already broken on 2026-08-14 have it committed. The chokepoint
# alone does nothing for them: the file is already tracked, so rule 3 still hands
# it to --delete on the very next run.
L2="$T/fix2.log"
run_case fix2 tracked "$L2"
if ! grep -q -- "--- fake (subtree) ---" "$L2"; then
  echo "  FAIL: the run never reached the instance, so nothing was measured"
  tail -4 "$L2" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
else
  if grep -q "untracking instance-local file: $BASELINE_REL" "$L2"; then
    echo "  OK: the updater announced the untrack"
  else
    echo "  FAIL: no untrack announcement for an already-tracked baseline"
    FAILURES=$((FAILURES + 1))
  fi
  # The behavioural proof, printed by pre-existing updater code: a file only
  # reaches "restored untracked" when it is genuinely untracked by then.
  if grep -q "restored untracked: $BASELINE_REL" "$L2"; then
    echo "  OK: it survived the sync as an untracked file"
  else
    echo "  FAIL: the baseline did not survive the sync"
    grep -i "baseline" "$L2" | head -3 | sed 's/^/      /'
    FAILURES=$((FAILURES + 1))
  fi
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
