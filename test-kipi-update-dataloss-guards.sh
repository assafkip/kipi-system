#!/bin/bash
# The two ASK-606 data-loss notes I refused to close on a code read.
#
#   sp-737ce1ae (P0): with a null subtree_prefix the rsync destination is the
#     instance ROOT, so excludes anchored to the transfer root sit one level
#     ABOVE the instance's own canonical/ my-project/ memory/. The dry run
#     itemized `*deleting q-system/my-project/...` and nothing stopped it.
#     A fail-closed deletion guard was added; nobody had reproduced the variant.
#
#   sp-20c967ed (MAJOR): on a PARTIAL rsync --delete failure the updater tore
#     down ARCHIVE_TMP -- which contains SNAP, the only copy of the instance's
#     untracked files -- and continued, so the restore loop never ran. rsync
#     deletes DURING transfer, so a disk-full or a signal mid-transfer lost
#     instance-local files unrecoverably. Every pre-rsync guard correctly says
#     "rsync not started"; this is the branch where it DID start.
#
# "Verified 4 instances are intact" is not proof, and neither is reading the
# code. Both cases are forced here.
#
# WHAT EACH CASE ACTUALLY PROVES, stated because a green tick invites a wider
# reading than it earns:
#
#   sp-737ce1ae is CLOSED by this, and by a different mechanism than the note
#   or the deletion guard predicted -- a null-prefix instance is rejected up
#   front as UNDECLARED NON-PROPAGATING, so no sync starts and the excludes
#   never get the chance to point one level too high. Measured, not read.
#
#   sp-20c967ed is NOT fully closed by this. It proves the partial-failure
#   branch is REACHED, reported as "q-system sync failed", and handled without
#   crashing, and that a dry run leaves production untouched. It does NOT prove
#   the SNAP restore recovered the deleted file: --dry-run operates on a clone
#   that is torn down at the end of the run, so the restored copy cannot be
#   inspected from here. Proving that needs a non-dry fixture against a
#   throwaway instance, which is a separate piece of work. The note stays open.
#
# Only --dry-run is invoked, against throwaway fixtures.
#
# Run: bash test-kipi-update-dataloss-guards.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

# $1 root, $2 prefix JSON value (e.g. '"q-system"' or 'null')
build_fleet() {
  local root="$1"
  local prefix_json="$2"
  local skel="$root/skeleton"
  local inst="$root/instance"
  mkdir -p "$skel"
  cp -R "$REAL/q-system" "$skel/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$skel/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$skel/" 2>/dev/null
  cp -R "$REAL/plugins" "$skel/plugins" 2>/dev/null
  chmod +x "$skel/kipi-update.sh"
  echo "skeleton-owned" > "$skel/q-system/.q-system/scripts/skel-tool.py"

  cat > "$skel/instance-registry.json" <<JSON
{
  "skeleton": "$skel",
  "instances": [
    { "name": "fake", "path": "$inst", "subtree_prefix": $prefix_json,
      "instance_q_dir": "q-fake", "type": "subtree", "has_git": true }
  ],
  "standalone": [],
  "eliminated": []
}
JSON
  ( cd "$skel" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm skel ) >/dev/null 2>&1

  # Founder data kept under q-system/, which is where it lives on a real
  # instance and one level BELOW where root-anchored excludes point.
  mkdir -p "$inst/q-system/.q-system/scripts" "$inst/q-system/my-project" \
           "$inst/q-system/canonical" "$inst/q-system/memory"
  echo "skeleton-owned" > "$inst/q-system/.q-system/scripts/skel-tool.py"
  echo "FOUNDER CLIENTS"  > "$inst/q-system/my-project/clients.json"
  echo "FOUNDER DECISION" > "$inst/q-system/canonical/decisions.md"
  echo "FOUNDER MEMORY"   > "$inst/q-system/memory/handoff.md"
  ( cd "$inst" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1
  echo "UNTRACKED NOTES" > "$inst/q-system/.q-system/scripts/scratch.txt"
}

echo "=== sp-737ce1ae: a null subtree_prefix must not delete founder data ==="
build_fleet "$T/a" 'null'
LOG="$T/a/run.log"
/bin/bash "$T/a/skeleton/kipi-update.sh" --dry-run --only fake > "$LOG" 2>&1
INST="$T/a/instance"

# Two independent questions: did the guard SPEAK, and did the data SURVIVE.
# Asserting only survival would pass on a run that skipped the instance
# entirely, which is why the reached-the-instance check is separate.
if ! grep -qE -- "--- fake|fake \(" "$LOG"; then
  echo "  WARN: the run did not clearly reach the instance; reporting what it said"
  tail -3 "$LOG" | sed 's/^/      /'
fi
# MEASURED, not assumed: the null-prefix variant is closed EARLIER than the
# deletion guard. The updater rejects the instance outright as UNDECLARED
# NON-PROPAGATING and never starts a sync, so the excludes never get a chance
# to point at the wrong level. I asserted the deletion-guard text first and it
# did not fire -- because the run never reaches it. Both refusals are accepted
# here, but the one that actually protects today is the declaration check.
if grep -q "UNDECLARED NON-PROPAGATING" "$LOG"; then
  echo "  OK: refused up front as UNDECLARED NON-PROPAGATING; no sync started"
elif grep -q "would delete instance-owned data; refusing" "$LOG"; then
  echo "  OK: the deletion guard refused, naming instance-owned data"
else
  echo "  FAIL: nothing refused a null-prefix sync"
  FAILURES=$((FAILURES + 1))
fi
for f in q-system/my-project/clients.json q-system/canonical/decisions.md \
         q-system/memory/handoff.md; do
  if [ -f "$INST/$f" ]; then
    echo "  OK: $f survived"
  else
    echo "  FAIL: $f WAS DELETED -- this is the P0"
    FAILURES=$((FAILURES + 1))
  fi
done

echo ""
echo "=== sp-20c967ed: a PARTIAL rsync failure must not lose untracked files ==="
# Force the branch every pre-rsync guard cannot reach: an rsync that really
# starts, really deletes, and THEN fails. A stub earlier in PATH does it
# deterministically -- disk-full and Ctrl-C are not reproducible on demand.
build_fleet "$T/b" '"q-system"'
BIN="$T/b/bin"; mkdir -p "$BIN"
cat > "$BIN/rsync" <<'STUB'
#!/bin/bash
# Pass through every rsync EXCEPT the real destructive one (-a --delete without
# -n). For that one: delete something, then fail -- a partial transfer.
REALSYNC="$(PATH=/usr/bin:/bin:/usr/local/bin command -v rsync)"
# EXACT flags only. `-*n*` also matched --exclude=/canonical/ and
# --exclude=node_modules/, so every call passed through and the stub never
# fired -- a fixture that silently measured nothing.
for a in "$@"; do case "$a" in -ain|-n|--dry-run) exec "$REALSYNC" "$@" ;; esac; done
# Fail ONLY the q-system sync, identified by its SOURCE being the extracted
# skeleton archive (.../q-system/). The first version failed on any --delete,
# which killed the dry-run MODEL BUILD instead: the run aborted with "could not
# create disposable dry-run model" and never reached the branch under test. It
# still printed PASS, because the assertion accepted any ERROR line. A green
# from that measured nothing.
src=""; dest="${@: -1}"
for a in "$@"; do case "$a" in -*) ;; *) src="$a" ;; esac; done
case "$src" in
  */q-system/)
    victim="$dest/.q-system/scripts/scratch.txt"
    [ -f "$victim" ] && rm -f "$victim"
    echo "rsync: simulated partial failure after deleting" >&2
    exit 12
    ;;
esac
exec "$REALSYNC" "$@"
STUB
chmod +x "$BIN/rsync"

LOG2="$T/b/run.log"
PATH="$BIN:$PATH" /bin/bash "$T/b/skeleton/kipi-update.sh" --dry-run --only fake > "$LOG2" 2>&1
INST2="$T/b/instance"

# Require the q-system sync failure SPECIFICALLY. Accepting any ERROR is exactly
# how the first version reported PASS while aborting in the model build.
if grep -q "q-system sync failed" "$LOG2"; then
  echo "  OK: the partial q-system sync failure was reached and reported"
else
  echo "  FAIL: never reached the q-system sync; this case measured nothing"
  grep -m2 -E "ERROR" "$LOG2" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
fi
# The real question. --dry-run works on a CLONE, so the production instance must
# be untouched no matter what; that is the property worth pinning, because it is
# what protects a real fleet when a transfer dies half way.
if [ -f "$INST2/q-system/.q-system/scripts/scratch.txt" ]; then
  echo "  OK: the untracked file is intact in the production instance"
else
  echo "  FAIL: an untracked instance file was lost to a partial failure"
  FAILURES=$((FAILURES + 1))
fi
for f in q-system/my-project/clients.json q-system/canonical/decisions.md; do
  if [ -f "$INST2/$f" ]; then echo "  OK: $f survived the partial failure"
  else echo "  FAIL: $f lost to a partial failure"; FAILURES=$((FAILURES + 1)); fi
done

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
