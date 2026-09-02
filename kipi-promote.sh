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

usage() { echo "usage: kipi promote [--decided-by NAME] <relative path under q-system/>" >&2; }

DECIDED_BY=""   # default is instance:<registry name>, set once the scrub resolves the name;
                # the OS username is NOT a default: on the founder's machine it carries a tripwire term
while [ $# -gt 0 ]; do
  case "$1" in
    --decided-by) [ -n "${2:-}" ] || { usage; exit 2; }; DECIDED_BY="$2"; shift 2 ;;
    --decided-by=*) DECIDED_BY="${1#--decided-by=}"; [ -n "$DECIDED_BY" ] || { usage; exit 2; }; shift ;;
    --) shift; break ;;
    -*) usage; exit 2 ;;
    *) break ;;
  esac
done
if [ $# -ne 1 ] || [ -z "${1:-}" ]; then usage; exit 2; fi   # ONE capability per call; extra args fail, never half-succeed
REL="$1"
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

# --- receipt (issue lr-promote-receipt-hash-binding, Codex finding-1 on the PRD) ---
# The receipt binds the CONTENT, not the path: `blob` is git hash-object of what
# was copied, the same value the lessons guard reads from ls-tree, so a receipt
# written for one version never blesses a later edit at the same path. Lives in
# the skeleton at q-system/.q-system/promotions.jsonl (the guard reads it from
# FETCH_HEAD, issue 11). Two-phase writing under a lock is issue 10.
RECEIPTS="$SKELETON/q-system/.q-system/promotions.jsonl"
# Hashed with the INSTANCE's attributes (-C, --path) so the blob is the one its
# ls-tree reports, whatever the caller's cwd repo filters; `|| true` so a
# missing git reaches refuse instead of exiting under set -e (Claude review).
BLOB="$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$DEST" 2>/dev/null || true)"
[ -n "$BLOB" ] || refuse "could not hash the promoted file $DEST"
[ "$BLOB" = "$(git -C "$INSTANCE_REAL" hash-object --path "$REL" "$INSTANCE_REAL/$REL" 2>/dev/null || true)" ] || refuse "copy does not match the source after promotion ($REL)"
mkdir -p "$(dirname "$RECEIPTS")"
# from_instance is the registry NAME, never the absolute path: a path carries
# /Users/ and the owner's name, and this file fans out to every instance where
# the push tripwire would then refuse every push (Claude review, blocker).
python3 - "$RECEIPTS" "$REL" "$BLOB" "$INSTANCE_NAME" "$DECIDED_BY" "$SCRUB" "$PROMOTE_HOME/q-system/.q-system/scripts/tripwire-terms.txt" "$BASE" <<'PYRECEIPT' || refuse "receipt refused for $REL: a field carries a tripwire term (this file fans out to every instance), or it could not be written"
import datetime, json, sys
path, rel, blob, inst, who, scrub, tripwire, base = sys.argv[1:9]
row = {"path": rel, "blob": blob, "base": base, "from_instance": inst, "decided_by": who, "scrub": scrub, "status": "done",
       "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")}
# the row itself is scrubbed: it lands in every instance's q-system/ where the push tripwire greps
terms = [l.strip() for l in open(tripwire, encoding="utf-8") if l.strip() and not l.startswith("#")]
line = json.dumps(row)
if any(t.lower() in line.lower() for t in terms):
    sys.exit(1)
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row) + "\n")
PYRECEIPT
echo "promoted $REL -> $DEST (blob $BLOB, receipt appended to $RECEIPTS)"
