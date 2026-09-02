#!/bin/bash
# kipi promote <path>  --  move ONE general capability from this instance up to the skeleton.
#
# The up-rail (prd-lessons-rail-and-up-rail, Phase 4 of the morning-brief overhaul,
# founder-directed 2026-09-01: instances author general capabilities where the work
# happens; a capability is PROMOTED, it never lives in two places). Built in six
# slices; this file grows one slice per issue and refuses to promote for real until
# the scrub and the receipt slices exist (KIPI_PROMOTE_UNSCRUBBED=1 under pytest only).
#
# Slice 1 (issue lr-promote-path-containment, Codex finding-2 on the PRD):
#   containment. Anything but a plain relative path to a regular file whose REAL
#   path sits inside <instance>/q-system/ is refused with exit 2 and nothing is
#   copied. Refused: absolute input, any '..' segment, a symlink anywhere on the
#   path (the file or a parent), a directory, a device or fifo, anything outside
#   q-system/ (including the instance's own q-<name>/ tree). The destination is
#   the SAME relative path in the skeleton; parents are created.
#
# Trees (tests point both at tmp copies; production resolves them):
#   KIPI_PROMOTE_INSTANCE   the instance root (default: the current directory's repo root)
#   KIPI_PROMOTE_SKELETON   the skeleton root (default: instance-registry.json's skeleton path,
#                           read from the skeleton clone named by KIPI_HOME, the kipi CLI's home)
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: kipi promote [--decided-by NAME] <relative path under q-system/>
       kipi promote --candidates [--instance NAME]     list divergent lessons with a receipt status each
       kipi promote --void <path> --reason TEXT        record that a lesson stays local (no copy)
USAGE
}

DECIDED_BY=""   # default is instance:<registry name>, set once the scrub resolves the name;
                # the OS username is NOT a default: on the founder's machine it carries a tripwire term
MODE="promote"; INSTANCE_ARG=""; REASON=""; POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --decided-by) [ -n "${2:-}" ] || { usage; exit 2; }; DECIDED_BY="$2"; shift 2 ;;
    --decided-by=*) DECIDED_BY="${1#--decided-by=}"; [ -n "$DECIDED_BY" ] || { usage; exit 2; }; shift ;;
    --candidates) MODE="candidates"; shift ;;
    --instance) [ -n "${2:-}" ] || { usage; exit 2; }; INSTANCE_ARG="$2"; shift 2 ;;
    --void) MODE="void"; shift ;;
    --reason) [ -n "${2:-}" ] || { usage; exit 2; }; REASON="$2"; shift 2 ;;
    --) shift; POS+=("$@"); break ;;
    -*) usage; exit 2 ;;
    *) POS+=("$1"); shift ;;   # options may follow the path (--void PATH --reason TEXT)
  esac
done
set -- ${POS[@]+"${POS[@]}"}
if [ "$MODE" = "candidates" ]; then
  [ $# -eq 0 ] || { usage; exit 2; }
  REL=""
else
  if [ $# -ne 1 ] || [ -z "${1:-}" ]; then usage; exit 2; fi   # ONE capability per call; extra args fail, never half-succeed
  [ "$MODE" != "void" ] || [ -n "$REASON" ] || { usage; exit 2; }   # a void without a reason is a shrug, not a decision
  REL="$1"
fi
case "$REL" in
  *$'\n'*) echo "kipi promote: refused: a newline in the path ($REL)" >&2; exit 2 ;;
  *//*) echo "kipi promote: refused: empty segment in the path ($REL)" >&2; exit 2 ;;
esac

INSTANCE="${KIPI_PROMOTE_INSTANCE:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
if [ -z "${KIPI_PROMOTE_SKELETON:-}" ]; then
  KIPI_HOME_DIR="${KIPI_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  KIPI_PROMOTE_SKELETON="$(python3 -c 'import json,sys,os; print(os.path.realpath(json.load(open(sys.argv[1]))["skeleton"]["path"]))' "$KIPI_HOME_DIR/instance-registry.json" 2>/dev/null || true)"
fi
SKELETON="${KIPI_PROMOTE_SKELETON:-}"
if [ -z "$SKELETON" ] || [ ! -d "$SKELETON/q-system" ]; then
  echo "kipi promote: cannot resolve the skeleton root (set KIPI_PROMOTE_SKELETON or a registry with a skeleton path)" >&2
  exit 2
fi

refuse() { echo "kipi promote: refused: $1" >&2; exit 2; }

PROMOTE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIPI_HOME_DIR="${KIPI_HOME:-$PROMOTE_HOME}"   # the same registry skeleton resolution used
REGISTRY="${KIPI_PROMOTE_REGISTRY:-$KIPI_HOME_DIR/instance-registry.json}"
SCRUB_PY="$PROMOTE_HOME/q-system/.q-system/scripts/lessons_scrub.py"
TRIPWIRE_FILE="$PROMOTE_HOME/q-system/.q-system/scripts/tripwire-terms.txt"
RECEIPTS="$SKELETON/q-system/.q-system/promotions.receipts"

# --instance NAME: the instance is the registry's, not the cwd's (issue 12,
# candidates are listed for a hub instance from wherever the operator sits)
if [ -n "$INSTANCE_ARG" ]; then
  [ -f "$REGISTRY" ] || refuse "no instance registry at $REGISTRY; cannot resolve --instance $INSTANCE_ARG"
  INSTANCE="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); m=[e for e in d.get("instances",[]) if e.get("name")==sys.argv[2]]; print(m[0]["path"] if m else "")' "$REGISTRY" "$INSTANCE_ARG" 2>/dev/null || true)"
  [ -n "$INSTANCE" ] && [ -d "$INSTANCE" ] || refuse "no registered instance named $INSTANCE_ARG (or its path is missing)"
fi

# receipt_row <pending|done|voided>: the ONLY writer of promotions.receipts.
# The caller holds the lock (fd 9) across every phase. from_instance is the
# registry NAME, never a path: a path carries /Users/ and the owner's name, and
# this file fans out to every instance where the push tripwire greps it. The
# row itself is scrubbed against the tripwire for the same reason.
receipt_row() {
  python3 - "$RECEIPTS" "$REL" "$BLOB" "$INSTANCE_NAME" "$DECIDED_BY" "$SCRUB" "$TRIPWIRE_FILE" "$BASE" "$1" "$REASON" <<'PYRECEIPT'
import datetime, json, os, sys
path, rel, blob, inst, who, scrub, tripwire, base, status, reason = sys.argv[1:11]
row = {"path": rel, "blob": blob, "base": base, "from_instance": inst, "decided_by": who, "scrub": scrub, "status": status,
       "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")}
if status == "voided":
    row["reason"] = reason
terms = [l.strip() for l in open(tripwire, encoding="utf-8") if l.strip() and not l.startswith("#")]
line = json.dumps(row)
if any(t.lower() in line.lower() for t in terms):
    sys.exit(1)
with open(path, "a", encoding="utf-8") as fh:  # the caller holds the lock (fd 9) across both phases
    fh.write(line + "\n")
    fh.flush()
    os.fsync(fh.fileno())
PYRECEIPT
}
take_lock() {
  # ONE lock for the whole operation: taken on fd 9 (an flock lives on the open
  # file description, so a child process locking the inherited fd leaves it held
  # by this shell until exit). macOS ships no flock(1); python does the locking.
  mkdir -p "$(dirname "$RECEIPTS")"
  exec 9>>"$RECEIPTS.lock"
  python3 -c 'import fcntl, sys; fcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX)' 9 || refuse "could not take the promotion lock $RECEIPTS.lock"
}
instance_name() { python3 -c 'import importlib.util,sys; s=importlib.util.spec_from_file_location("m",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.instance_name_for(sys.argv[2], sys.argv[3]) or "")' "$SCRUB_PY" "$REGISTRY" "$1" 2>/dev/null || true; }

# --- candidates: every lesson in the instance that is absent from or divergent with the skeleton ---
if [ "$MODE" = "candidates" ]; then
  INSTANCE_REAL="$(cd "$INSTANCE" && pwd -P)"
  NAME="$(instance_name "$INSTANCE_REAL")"
  # the instance must be the registry's (Codex, issue 12): receipts are matched
  # by from_instance, and the void action names the instance's own lessons dir
  [ -n "$NAME" ] || refuse "no registry entry for $INSTANCE_REAL; candidates are listed for registered instances only"
  QDIR="$(python3 -c 'import json,sys,os; d=json.load(open(sys.argv[1])); m=[e for e in d.get("instances",[]) if os.path.realpath(e.get("path",""))==sys.argv[2]]; print((m[0].get("instance_q_dir") or "") if m else "")' "$REGISTRY" "$INSTANCE_REAL" 2>/dev/null || true)"
  [ -n "$QDIR" ] || refuse "the registry entry for $NAME has no instance_q_dir; cannot name where a voided lesson goes"
  python3 - "$INSTANCE_REAL" "$SKELETON" "$RECEIPTS" "$QDIR" "$NAME" <<'PYCAND'
import glob, json, os, subprocess, sys
inst, skel, receipts, qdir, name = sys.argv[1:6]
def blob(root, rel):
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        return ""
    return subprocess.run(["git", "-C", inst, "hash-object", "--path", rel, p], capture_output=True, text=True).stdout.strip()
rows = []
if os.path.exists(receipts):
    for line in open(receipts, encoding="utf-8"):
        try:
            r = json.loads(line)
            if isinstance(r, dict):
                rows.append(r)
        except ValueError:
            pass
out = []
for p in sorted(glob.glob(os.path.join(inst, "q-system", "lessons", "*.md"))):
    rel = os.path.relpath(p, inst)
    if os.path.basename(rel) == "README.md":
        continue
    b = blob(inst, rel)
    if b and b == blob(skel, rel):
        continue  # identical: not a candidate
    # only THIS instance's receipts count (from_instance), and only for the
    # blob the file has now; the status is one of exactly none, pending, done,
    # voided (the contract), with an earlier receipt mentioned in the note
    mine = [r for r in rows if r.get("path") == rel and r.get("from_instance") == name]
    exact = [r for r in mine if r.get("blob") == b]
    status = str(exact[-1].get("status")) if exact else "none"
    if status not in ("pending", "done", "voided"):
        status = "none"
    note = ""
    if not exact and mine:
        note = " (an earlier version had a " + str(mine[-1].get("status")) + " receipt; this content has none)"
    if status == "done":
        nxt = "commit the skeleton, then the updater fans the receipt out"
    elif status == "pending":
        nxt = "re-run: kipi promote " + rel + " (a pending row stands)"
    elif status == "voided":
        nxt = "move it to " + qdir + "/lessons/ (voided; the guard still refuses it under q-system/)"
    else:
        nxt = "kipi promote " + rel + "   or   kipi promote --void " + rel + " --reason \"...\"" + note
    out.append((status, rel, nxt))
for status, rel, nxt in out:
    print(f"{status:14} {rel}   next: {nxt}")
print(f"{len(out)} candidate(s) in {inst}")
PYCAND
  exit $?
fi

# --- containment, checked on the INPUT before anything touches the disk ---
case "$REL" in
  /*) refuse "absolute paths are not promotable; give a path relative to the instance root ($REL)" ;;
esac
case "/$REL/" in
  */../*|*/./*) refuse "'.' and '..' segments are not allowed ($REL)" ;;
esac
case "$REL" in
  q-system/*) : ;;
  *) refuse "only files under q-system/ are promotable; instance-owned trees stay where they are ($REL)" ;;
esac

SRC="$INSTANCE/$REL"
# every component from the instance root down must be a real directory or file, never a link
_walk="$INSTANCE"
IFS='/' read -r -a _parts <<< "$REL"
for _part in "${_parts[@]}"; do
  _walk="$_walk/$_part"
  if [ -L "$_walk" ]; then refuse "symlink on the path: ${_walk#"$INSTANCE"/}"; fi
done
[ -e "$SRC" ] || refuse "no such file: $REL"
[ -d "$SRC" ] && refuse "directories are not promotable; promote one file at a time ($REL)"
[ -f "$SRC" ] || refuse "not a regular file (device, fifo or socket): $REL"
REAL="$(cd "$(dirname "$SRC")" && pwd -P)/$(basename "$SRC")"
INSTANCE_REAL="$(cd "$INSTANCE" && pwd -P)"
case "$REAL" in
  "$INSTANCE_REAL/q-system"/*) : ;;
  *) refuse "real path escapes q-system/: $REAL" ;;
esac
# The destination is the ON-DISK relative path, not the caller's spelling: on
# case-insensitive APFS `q-system/Lessons/General.md` opens the real file, and
# `$SKELETON/$REL` would create a second, differently-cased copy on a
# case-sensitive checkout (Claude standard review, issue 7).
REL="$(python3 -c 'import os,sys; r,i=sys.argv[1:3]; print(os.path.relpath(os.path.join(os.path.dirname(r), os.path.basename(r)), i))' "$(python3 -c 'import os,sys; d,b=sys.argv[1:3]; n=next((e for e in os.listdir(d) if e.lower()==b.lower() and os.path.lexists(os.path.join(d,e))), b); print(os.path.join(d,n))' "$(dirname "$REAL")" "$(basename "$SRC")")" "$INSTANCE_REAL")"
[ -f "$INSTANCE_REAL/$REL" ] || refuse "on-disk path could not be resolved for $1"
DEST="$SKELETON/$REL"

# --- void: a decision that this lesson stays local. No copy, no content scrub
# (client data is often WHY it stays local); the row itself is still scrubbed.
if [ "$MODE" = "void" ]; then
  INSTANCE_NAME="$(instance_name "$INSTANCE_REAL")"
  [ -n "$INSTANCE_NAME" ] || refuse "no registry entry for $INSTANCE_REAL; cannot record who voided"
  [ -n "$DECIDED_BY" ] || DECIDED_BY="instance:$INSTANCE_NAME"
  BLOB="$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$INSTANCE_REAL/$REL" 2>/dev/null || true)"
  [ -n "$BLOB" ] || refuse "could not hash $REL"
  SCRUB="void"; BASE=""
  take_lock
  receipt_row "voided" || refuse "void refused for $REL: a field carries a tripwire term (this file fans out to every instance), or it could not be written"
  echo "voided $REL (blob $BLOB): stays in this instance; move it out of q-system/lessons/ so the push guard passes"
  exit 0
fi

# --- scrub (issue lr-promote-scrub-source, Codex finding-3 on the PRD) ---
# Production term sources, no test-only list:
#   1. instance codenames from instance-registry.json (lessons_scrub.codenames_from_registry)
#   2. every client name and slug in THIS instance's my-project/clients.json, located through
#      the registry entry whose path is this instance (instance_q_dir/my-project/clients.json)
#   3. the tripwire terms in q-system/.q-system/scripts/tripwire-terms.txt, the same file
#      kipi-push-upstream.sh reads for its pre-push grep
# The scrub module and the tripwire file are read from THIS script's own checkout (the kipi
# home), the code that is actually running. A missing clients file REFUSES (fail-closed): an
# instance that cannot name its clients cannot prove a file carries none of them.
# KIPI_PROMOTE_REGISTRY is a test seam for the registry path only; production reads the
# registry beside this script.
PROMOTE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIPI_HOME_DIR="${KIPI_HOME:-$PROMOTE_HOME}"   # the same registry skeleton resolution used
REGISTRY="${KIPI_PROMOTE_REGISTRY:-$KIPI_HOME_DIR/instance-registry.json}"
[ -f "$REGISTRY" ] || refuse "no instance registry at $REGISTRY; cannot build the scrub roster"
SCRUB_OUT="$(python3 - "$INSTANCE_REAL/$REL" "$REGISTRY" "$INSTANCE_REAL" "$PROMOTE_HOME/q-system/.q-system/scripts/lessons_scrub.py" "$PROMOTE_HOME/q-system/.q-system/scripts/tripwire-terms.txt" <<'PYSCRUB'
import importlib.util, os, sys
src, registry, instance, scrub_py, tripwire = sys.argv[1:6]
spec = importlib.util.spec_from_file_location("lessons_scrub", scrub_py)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
clients = mod.clients_file_for_instance(registry, instance)
if clients is None:
    print("REFUSE no registry entry with an instance_q_dir for " + instance + "; cannot locate my-project/clients.json"); sys.exit(0)
if not os.path.exists(clients):
    print("REFUSE clients file missing: " + clients); sys.exit(0)
name = mod.instance_name_for(registry, instance) or ""
terms = list(mod.codenames_from_registry(registry)) + mod.client_terms(clients)
trip = mod.tripwire_terms(tripwire)
with open(src, encoding="utf-8", errors="replace") as fh:
    text = fh.read()
hits = mod.find_client_data(text, extra_terms=terms)
# tripwire terms match as case-insensitive SUBSTRINGS, exactly like the push
# script's `grep -ril`; find_client_data's word boundaries cannot see "/Users/"
low = text.lower()
hits += [("tripwire", t) for t in trip if t.lower() in low]
terms += trip
# Scripts are promotable and carry shebangs and repo URLs by nature, so the
# lessons scrub's generic "any unix path" and "any URL" categories do not apply
# here; the tripwire's /Users/ term still refuses a home path, and static
# tokens, emails, codenames and client terms all still refuse.
hits = [h for h in hits if h[0] not in ("path", "url")]
if hits:
    print("REFUSE client data: " + "; ".join(f"{k}={v}" for k, v in hits[:5]))
else:
    print("CLEAN " + name + " " + str(len(terms)) + " terms")
PYSCRUB
)" || refuse "scrub apparatus failed for $REL"
case "$SCRUB_OUT" in
  CLEAN*) INSTANCE_NAME="$(printf '%s' "$SCRUB_OUT" | awk '{print $2}')"; SCRUB="clean ($(printf '%s' "$SCRUB_OUT" | cut -d' ' -f3-))" ;;
  *) refuse "${SCRUB_OUT#REFUSE }" ;;
esac
[ -n "$INSTANCE_NAME" ] || refuse "the registry entry for $INSTANCE_REAL has no name"
[ -n "$DECIDED_BY" ] || DECIDED_BY="instance:$INSTANCE_NAME"

# --- the receipt slice lands in the next issue; until then this never promotes for real ---
# The seam needs THREE things: pytest's marker, the explicit opt-in, and an
# instance root under a temp directory. PYTEST_CURRENT_TEST alone is anyone's
# to set (Codex adversarial, issue lr-promote-path-containment); a real
# instance never lives under /tmp or /private/var/folders, so this cannot be
# turned into a working unscrubbed promoter for a real tree.
# (Tests under a TMPDIR outside these four prefixes get rc 3 from every copy
# test; run pytest with the default basetemp.)
_tmp_rooted=0
case "$INSTANCE_REAL" in
  /tmp/*|/private/tmp/*|/private/var/folders/*|/var/folders/*) _tmp_rooted=1 ;;
esac
if [ -z "${PYTEST_CURRENT_TEST:-}" ] || [ "${KIPI_PROMOTE_UNSCRUBBED:-}" != "1" ] || [ "$_tmp_rooted" != "1" ]; then
  echo "kipi promote: containment passed for $REL, but the scrub and receipt slices are not built yet; nothing copied" >&2
  exit 3
fi

# BASE: the skeleton's blob at this path BEFORE the copy ("" when new). The
# receipt records it and the lessons guard honours the receipt only while the
# skeleton still holds that base; once the skeleton moves past the promotion
# (an edit, a lint pass) a stale instance can no longer push the receipted
# version back over it (Claude adversarial review, issue 9).
BASE=""
if [ -e "$DEST" ]; then
  BASE="$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$DEST" 2>/dev/null || true)"
  [ -n "$BASE" ] || refuse "could not hash the skeleton's current $REL"
fi

# --- receipt, phase 1 (issues lr-promote-receipt-hash-binding and lr-promote-two-phase-receipt) ---
# The receipt binds the CONTENT, not the path: `blob` is git hash-object of the
# SOURCE, hashed with the instance's attributes (-C, --path) so it is the value
# its ls-tree reports; `|| true` so a missing git reaches refuse instead of an
# exit under set -e. It is written in TWO phases around the copy (Codex
# finding-11 on the PRD): a `pending` row before the copy, a `done` row after
# the copied file re-hashes equal. A crash between them leaves a pending row
# that blesses nothing (the guard honours done only) and never a silent copy.
# Both appends take one flock on a sibling .lock of the receipt file, so
# concurrent promotions interleave whole rows. from_instance is the registry
# NAME, never a path: a path carries /Users/ and the owner's name, and this
# file fans out to every instance where the push tripwire greps it.
BLOB="$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$INSTANCE_REAL/$REL" 2>/dev/null || true)"
[ -n "$BLOB" ] || refuse "could not hash the source $REL"
# ONE lock for the whole promotion (take_lock, fd 9), released only when the
# script ends: it covers the pending row, the copy, the re-hash and the done
# row as one critical section, so two promotions of the same destination
# cannot interleave (Codex, both passes on issue 10).
take_lock
receipt_row "pending" || refuse "receipt refused for $REL: a field carries a tripwire term (this file fans out to every instance), or it could not be written; nothing copied"

# Test seam (pytest + tmp-rooted only, like KIPI_PROMOTE_UNSCRUBBED): a pause
# between the pending row and the copy, so a test can probe that the lock is
# still held through the copy. Production never sets it.
if [ -n "${KIPI_PROMOTE_TEST_SLOW_COPY:-}" ] && [ "$_tmp_rooted" = "1" ] && [ -n "${PYTEST_CURRENT_TEST:-}" ]; then
  sleep "$KIPI_PROMOTE_TEST_SLOW_COPY"
fi

# The copy IS the containment. The bash checks above give early, readable
# refusals; this walk is what holds: every component on both sides is opened
# with O_NOFOLLOW relative to the previous directory fd, so a symlink swapped
# in after the checks (source or destination) fails the open instead of being
# followed (Codex adversarial: TOCTOU and unchecked destination chain).
python3 - "$INSTANCE" "$SKELETON" "$REL" <<'PYCOPY' || refuse "contained copy failed for $REL (a component changed under us or is a symlink)"
import os, stat, sys
instance, skeleton, rel = sys.argv[1:4]
parts = rel.split("/")
def walk_dirs(root, names, create=False):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in names:
            if create:
                try:
                    os.mkdir(name, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except OSError:
        os.close(fd)
        raise
sdir = walk_dirs(instance, parts[:-1])
try:
    # O_NONBLOCK: a fifo swapped in after the bash -f check must FAIL the
    # S_ISREG test below, not block this open forever (Claude standard review).
    sfd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=sdir)
finally:
    os.close(sdir)
try:
    st = os.fstat(sfd)
    if not stat.S_ISREG(st.st_mode):
        sys.exit(1)
    os.set_blocking(sfd, True)
    ddir = walk_dirs(skeleton, parts[:-1], create=True)
    try:
        dfd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=ddir, mode=0o644)
    finally:
        os.close(ddir)
    # keep the mode bits: a promoted hook or test script arrives executable,
    # as cp preserved it (Claude standard review: 755 -> 644 fanned out broken)
    os.fchmod(dfd, stat.S_IMODE(st.st_mode))
    with os.fdopen(sfd, "rb") as src, os.fdopen(dfd, "wb") as dst:
        sfd = None
        while True:
            chunk = src.read(1 << 16)
            if not chunk:
                break
            dst.write(chunk)
finally:
    if sfd is not None:
        os.close(sfd)
PYCOPY

# --- phase 2: the copied file re-hashes equal to the source, then the done row ---
COPIED="$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$DEST" 2>/dev/null || true)"
[ "$COPIED" = "$BLOB" ] || refuse "copy does not match the source after promotion ($REL); the pending row stands, no done row"
receipt_row "done" || refuse "could not write the done receipt for $REL; the pending row stands"
echo "promoted $REL -> $DEST (blob $BLOB, receipt appended to $RECEIPTS)"
