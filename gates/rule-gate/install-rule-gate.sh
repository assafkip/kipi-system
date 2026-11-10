#!/bin/bash
# install-rule-gate.sh: install the ASK-4283 rule_gate.py and make gate-locked root-owned.
#
# Run once, by the founder:   sudo bash <this file>
#
# WHY A SCRIPT. Agents may not write ~/.config/kipi/gate-locked/ (RULE-2026-11-08-CODE):
# the gate's own PROTECTED list refuses it, and that is right. So the fix ships as a
# reviewed file plus this installer, and a human runs it.
#
# WHAT IT DOES, one printed line per step, exit non-zero on the first failure:
#   1. finds the gate's user and a python3 that has pytest (the reproducer needs it)
#   2. checks the source file here is the reviewed one (PATCHED_SHA256)
#   3. runs the reproducer on that source in a sandbox, before anything live is touched
#   4. checks the live gate is the file this patch was made against (BASE_SHA256), and
#      that protected-manifest.json pins that same hash; refuses on any drift
#   5. backs up the live gate and manifest under gate-locked/backups/<time>/
#   6. swaps the gate in with one rename (a hook firing mid-copy never reads half a file)
#   7. repins the gate's hash in protected-manifest.json; without this, tamper_report()
#      reports TAMPER and blocks after EVERY tool call
#   8. runs the reproducer, as the user, against the installed gate; on red it rolls 5-7 back
#   9. chown -R root:wheel + chmod -R go-w on gate-locked
#  10. proves the user can still read the gate (the reproducer again, as the user, against
#      the root-owned file) and can no longer write it; on red it gives ownership back
#
# WHAT ROOT OWNERSHIP HERE DOES NOT DO, stated (lock-gate.sh's own header): gate-locked
# sits inside ~/.config/kipi, which the user owns, so a same-user shell can still rename
# the folder away and put another one in its place, and ~/.claude/settings.json still
# decides which file the hooks run. It stops the gate's files being edited in place. The
# complete lock is D33 (lock-gate.sh: a root-owned /opt copy plus managed settings), which
# is a separate, parked install.
#
# Test overrides (test_install_rule_gate.py runs every branch with no root):
#   KIPI_GATE_LOCK, KIPI_GATE_NO_CHOWN=1, KIPI_GATE_BASE_SHA256, KIPI_GATE_REPRODUCER,
#   KIPI_GATE_PYTHON. sudo's env_reset drops them, so the founder's run uses the defaults.
set -uo pipefail

BASE_SHA256="${KIPI_GATE_BASE_SHA256:-de2f63272aaa85c4575e870114293c616207d365845d98d986fc2bb090ef72fb}"
PATCHED_SHA256="1640a543195227a5e0e4776d120be7a6ec5b74a6aa5b3d3eee3cf812a5aaa77c"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/rule_gate.py"
REPRO="${KIPI_GATE_REPRODUCER:-$HERE/test_rule_gate_worktree_baseline.py}"
NO_CHOWN="${KIPI_GATE_NO_CHOWN:-0}"

step() { printf '%-3s %s\n' "$1" "$2"; }
fail() { step "$1" "FAILED: $2"; exit "${3:-1}"; }
sha() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

# 1. the user and python
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  RUN_USER="$SUDO_USER"
  UHOME="$(dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
  as_user() { sudo -u "$RUN_USER" -H "$@"; }
else
  RUN_USER="$(id -un)"; UHOME="$HOME"
  as_user() { "$@"; }
fi
[ -n "$UHOME" ] && [ -d "$UHOME" ] || fail 1 "no home folder for the gate's user" 64
if [ "$NO_CHOWN" != "1" ] && [ "$(id -u)" != "0" ]; then fail 1 "run it with sudo: step 9 makes root the owner" 77; fi
LOCK="${KIPI_GATE_LOCK:-$UHOME/.config/kipi/gate-locked}"
GATE="$LOCK/hooks/rule_gate.py"
MANIFEST="$LOCK/protected-manifest.json"
PY=""
for p in ${KIPI_GATE_PYTHON:-} /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$p" ] && as_user "$p" -c 'import pytest' >/dev/null 2>&1; then PY="$p"; break; fi
done
[ -n "$PY" ] || fail 1 "no python3 with pytest found for $RUN_USER" 64
step 1 "ok: user $RUN_USER, lock $LOCK, python $PY"

# 2. the reviewed source
[ "$(sha "$SRC")" = "$PATCHED_SHA256" ] || fail 2 "$SRC is not the reviewed file (sha $(sha "$SRC"))" 65
step 2 "ok: source is the reviewed rule_gate.py ($PATCHED_SHA256)"

repro() {  # repro <gate or empty for sandbox copy> <label>
  local out
  if [ -n "$1" ]; then
    out="$(cd / && as_user env PYTHONDONTWRITEBYTECODE=1 RULE_GATE_UNDER_TEST="$1" "$PY" -m pytest "$REPRO" -q -p no:cacheprovider 2>&1)"
  else
    out="$(cd / && as_user env PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest "$REPRO" -q -p no:cacheprovider 2>&1)"
  fi
  local rc=$?
  REPRO_LAST="$(printf '%s\n' "$out" | tail -1)"
  return $rc
}

# 3. reproducer on the source, sandboxed
repro "" || fail 3 "reproducer red on the source copy: $REPRO_LAST" 66
step 3 "ok: reproducer green on the source copy ($REPRO_LAST)"

# 4. the live gate and manifest are what this patch expects
[ -f "$GATE" ] || fail 4 "$GATE is missing" 67
[ -f "$MANIFEST" ] || fail 4 "$MANIFEST is missing" 67
LIVE="$(sha "$GATE")"
PINNED="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$MANIFEST" "$GATE")"
ALREADY=0
if [ "$LIVE" = "$PATCHED_SHA256" ]; then
  [ "$PINNED" = "$PATCHED_SHA256" ] || fail 4 "gate is patched but the manifest pins $PINNED; refusing to guess" 67
  ALREADY=1
  step 4 "ok: live gate is already the patched file; skipping 5-8"
else
  [ "$LIVE" = "$BASE_SHA256" ] || fail 4 "live gate drifted: sha $LIVE, expected $BASE_SHA256; nothing changed" 67
  [ "$PINNED" = "$BASE_SHA256" ] || fail 4 "manifest pins $PINNED, live gate is $LIVE; nothing changed" 67
  step 4 "ok: live gate and manifest match the patch base ($BASE_SHA256)"
fi

if [ "$ALREADY" = "0" ]; then
  # 5. backup
  BK="$LOCK/backups/$(date +%Y%m%dT%H%M%S)-ask-4283"
  mkdir -p "$BK" && cp -p "$GATE" "$BK/rule_gate.py" && cp -p "$MANIFEST" "$BK/protected-manifest.json" \
    || fail 5 "backup to $BK did not complete" 70
  [ "$(sha "$BK/rule_gate.py")" = "$LIVE" ] || fail 5 "backup copy does not match the live gate" 70
  step 5 "ok: backed up to $BK"

  rollback() {
    cp -p "$BK/rule_gate.py" "$GATE.rollback" && mv -f "$GATE.rollback" "$GATE"
    cp -p "$BK/protected-manifest.json" "$MANIFEST.rollback" && mv -f "$MANIFEST.rollback" "$MANIFEST"
    [ "$(sha "$GATE")" = "$LIVE" ] && echo "    rolled back: gate and manifest restored from $BK" \
      || echo "    ROLLBACK DID NOT VERIFY: restore $GATE from $BK by hand"
  }

  # 6. swap in
  cp "$SRC" "$GATE.new" && chmod 644 "$GATE.new" && mv -f "$GATE.new" "$GATE" \
    || { rollback; fail 6 "could not swap the gate in"; }
  [ "$(sha "$GATE")" = "$PATCHED_SHA256" ] || { rollback; fail 6 "installed gate hash is wrong"; }
  step 6 "ok: patched gate installed ($PATCHED_SHA256)"

  # 7. repin the manifest
  "$PY" - "$MANIFEST" "$GATE" "$PATCHED_SHA256" <<'EOF' || { rollback; fail 7 "manifest repin failed"; }
import json, os, sys
path, gate, digest = sys.argv[1:4]
man = json.load(open(path))
man[gate] = digest
tmp = path + ".new"
with open(tmp, "w") as fh:
    json.dump(man, fh, indent=1)
os.chmod(tmp, os.stat(path).st_mode & 0o7777)
os.replace(tmp, path)
EOF
  step 7 "ok: protected-manifest.json pins the patched hash"

  # 8. reproducer against the installed gate, as the user
  repro "$GATE" || { rollback; fail 8 "reproducer red on the installed gate: $REPRO_LAST"; }
  step 8 "ok: reproducer green on the installed gate, run as $RUN_USER ($REPRO_LAST)"
fi

# 9. root ownership
if [ "$NO_CHOWN" = "1" ]; then
  step 9 "skipped: KIPI_GATE_NO_CHOWN=1 (test run)"
else
  chown -R root:wheel "$LOCK" && chmod -R go-w "$LOCK" || fail 9 "chown/chmod on $LOCK failed" 71
  OWNER="$("$PY" -c 'import os,pwd,sys; print(pwd.getpwuid(os.stat(sys.argv[1]).st_uid).pw_name)' "$GATE")"
  [ "$OWNER" = "root" ] || fail 9 "$GATE is owned by $OWNER after chown" 71
  step 9 "ok: $LOCK is root:wheel, go-w"
fi

# 10. the user can read and run it, and cannot write it
give_back() { [ "$NO_CHOWN" = "1" ] || chown -R "$RUN_USER" "$LOCK"; echo "    ownership of $LOCK given back to $RUN_USER"; }
repro "$GATE" || { give_back; fail 10 "reproducer red as $RUN_USER after the chown: $REPRO_LAST"; }
if [ "$NO_CHOWN" != "1" ] && as_user test -w "$GATE"; then give_back; fail 10 "$RUN_USER can still write $GATE"; fi
step 10 "ok: $RUN_USER reads and runs the gate ($REPRO_LAST)$([ "$NO_CHOWN" = "1" ] || echo ", and cannot write it")"
echo "done"
