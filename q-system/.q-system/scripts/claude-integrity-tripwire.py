#!/usr/bin/env python3
"""claude-integrity-tripwire.py -- Layer 2 of the .claude/ write protection (ASK-282).

WHY THIS EXISTS (scar, 2026-08-01):
`.claude/` holds settings.json (which wires EVERY hook), rules/, agents/ and
output-styles/. An agent that writes there can disable its own safety gates and
then report success. The Write/Edit tools are refused on those paths by the auto
mode classifier -- but Bash was NOT. Measured twice that night:

    touch .claude/_probe.txt   ->  BASH WRITE SUCCEEDED

So the protection was a heuristic on TOOL CHOICE, not a rule about the PATH.
Every agent that reported "blocked" had merely used the front door. (This also
corrects sp-19387a70, which claimed both Bash and Edit were refused.)

WHY A TRIPWIRE AND NOT A BIGGER DENYLIST:
The sibling guard (claude-path-write-guard.py, Layer 1) blocks command shapes at
PreToolUse. It cannot be complete. A command-string denylist loses to touch, >,
>>, tee, cp, mv, install, rsync, sed -i, python -c open(w), `cd .claude && ...`,
a path held in a variable, $HOME/.claude, a relative path from a subdirectory,
and to forms nobody enumerated. That is the exact defect class this repo hit six
times in one file: matching a phrase where the intent is a structure.

This layer does not look at commands at all. It baselines the CONTENT of the
tree and detects any change to the RESULT. An unlisted command form is therefore
not an evasion -- the write still lands, and the hash still moves.

MODES
  --baseline            (re)record the whole watch set as sanctioned
  --check               report drift; exit 1 if drift, 0 if clean (read-only)
  --enforce             drift -> quarantine + restore + page; exit 2 if it acted
  --register PATH...    re-record only these paths (the sanctioned-apply hook)
  --root DIR            repo root to operate on (default: derived from THIS file)

--root exists so the test suite runs against a temp copy of a tree, never the
live one. The default is derived from __file__, not from cwd: a guard whose root
follows the caller's working directory answers a question about the wrong tree.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# Volatile by design: these change constantly during normal work and carry no
# hook/rule/agent wiring. Watching them would produce an alarm nobody reads,
# and an alarm nobody reads is the same as no alarm.
#   state/, plans/, worktrees/  -- gitignored scratch
#   settings.local.json         -- gitignored; local permission approvals churn
#                                  every session. NAMED GAP, not an oversight:
#                                  it carries `permissions`, so it is genuinely
#                                  security-relevant. Captured as spillover
#                                  rather than silently folded into scope.
EXCLUDED_DIRS = {"state", "plans", "worktrees", "backups", "__pycache__"}
EXCLUDED_FILES = {"settings.local.json", ".DS_Store"}

# The two guard scripts themselves. They live OUTSIDE `.claude/`, so nothing
# watched them.
#
# SCAR (review finding, PR #85 round 2): both layers are wired as
# `test -f X && python3 X` -- the repo's documented convention (skill-hook-
# pairing.md), which makes a MISSING script a silent, exit-0 no-op. So
# `rm q-system/.q-system/scripts/claude-path-write-guard.py` disarmed Layer 1
# with no alarm on either layer, and this PR's own body claims the write path
# "is now closed". A gate whose off-switch is one unwatched `rm` was never on.
#
# Watching them here means a delete lands as `removed` on the very next tool
# call: it pages, and --enforce restores the file from its stored git blob.
EXTRA_WATCHED = (
    os.path.join("q-system", ".q-system", "scripts", "claude-path-write-guard.py"),
    os.path.join("q-system", ".q-system", "scripts", "claude-integrity-tripwire.py"),
)

BASELINE_REL = os.path.join("q-system", ".q-system", "claude-integrity-baseline.json")
QUARANTINE_REL = os.path.join("q-system", "output", "claude-integrity", "quarantine")


def default_root():
    # <root>/q-system/.q-system/scripts/this-file.py -> up 3.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def watch_set(root):
    """Every file under <root>/.claude/ that is not volatile, plus the two guard
    scripts, as repo-relative paths."""
    base = os.path.join(root, ".claude")
    found = [rel for rel in EXTRA_WATCHED
             if os.path.islink(os.path.join(root, rel))
             or os.path.isfile(os.path.join(root, rel))]
    if not os.path.isdir(base):
        return sorted(found)
    for dirpath, dirnames, filenames in os.walk(base):
        # Prune the volatile names ONLY at the top of .claude/. Pruning at every
        # depth made loadable artifacts invisible: `.claude/skills/plans/` and
        # `.claude/commands/state/` are real content, not scratch, and a watcher
        # that cannot see them is a hole shaped like a convenience.
        # (Review finding, round 2.) __pycache__ stays pruned everywhere.
        at_top = os.path.abspath(dirpath) == os.path.abspath(base)
        if at_top:
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        else:
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if at_top and name in EXCLUDED_FILES:
                continue
            if name == ".DS_Store":
                continue
            full = os.path.join(dirpath, name)
            # SYMLINKS ARE WATCHED (review finding, PR #85). They used to be
            # skipped here, so `ln -s /elsewhere/evil.md .claude/agents/x.md`
            # read as CLEAN on the layer this PR armed and advertised as the
            # backstop for Layer 1's command-substitution misses. A watched
            # symlink is measured by WHERE IT POINTS, never by its target's
            # contents -- following the link is how the round-2 restore became
            # an arbitrary-write primitive.
            #
            # HONEST BOUND, still open: os.walk does not follow symlinked
            # DIRECTORIES, so a symlinked subdir under .claude/ hides whatever
            # is beneath it. Captured as spillover, not fixed here.
            if not os.path.islink(full) and not os.path.isfile(full):
                continue
            found.append(os.path.relpath(full, root))
    return sorted(found)


def git_blob_id(root, path_rel, write=True):
    """Content id for restore. `-w` puts the blob in the object store so a
    restore is possible even for a file that was never committed."""
    cmd = ["git", "-C", root, "hash-object"]
    if write:
        cmd.append("-w")
    cmd.append(path_rel)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def blob_content(root, blob):
    if not blob:
        return None
    try:
        out = subprocess.run(["git", "-C", root, "cat-file", "blob", blob],
                             capture_output=True, timeout=20)
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return None


def load_baseline(root):
    path = os.path.join(root, BASELINE_REL)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        # A corrupt baseline is itself a tamper signal. Never silently treat it
        # as "no drift" -- that is how a guard fails open.
        return {"schema_version": 1, "corrupt": True, "entries": {}}


def save_baseline(root, entries, last_alarm=""):
    path = os.path.join(root, BASELINE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {
        "schema_version": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Sanctioned content of .claude/. See claude-integrity-tripwire.py (ASK-282).",
        # Fingerprint of the last drift state we PAGED for. Identical drift must
        # not re-page every session: a repeating alert for an unchanged fact is
        # the thing the founder asked us to stop building (finding, round 3).
        "last_alarm": last_alarm,
        "entries": entries,
    }
    # Unique temp in the SAME directory, so os.replace stays atomic.
    #
    # SCAR (review finding, round 3): this used a fixed `path + ".tmp"` while the
    # comment claimed "single-writer". Two concurrent first-run --check calls
    # raced on that one name and crashed one of them (15/15 trials) -- and
    # session-start then mistranslated the traceback into a SECURITY banner,
    # Slack-paging the literal text "Traceback (most recent call last):".
    # A comment asserting an invariant the code does not hold is the same defect
    # shape as a header warning about phrase-matching above a phrase match.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".baseline-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)  # atomic swap, never a half-written baseline
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


LOCK_WAIT_DEFAULT = 10.0
LOCK_HELD_ENV = "KIPI_TRIPWIRE_LOCK_HELD"


def lock_wait_seconds():
    """How long a VERIFIER waits for an in-flight sanctioned apply. Operational
    knob, not a test hook: it has to stay under the hook timeout declared in
    settings.json, and that timeout is per-instance."""
    raw = os.environ.get("KIPI_TRIPWIRE_LOCK_WAIT", "")
    if not raw:
        return LOCK_WAIT_DEFAULT
    try:
        return max(0.0, float(raw))
    except ValueError:
        return LOCK_WAIT_DEFAULT


def _flock_wait(fh, timeout):
    """Poll for the exclusive lock until `timeout` elapses. True if acquired."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


@contextlib.contextmanager
def baseline_lock(root, timeout=None):
    """Serialize the baseline against writers AND readers. Yields True while the
    lock is held, False when `timeout` elapsed with another process holding it.

    The lock is a SEPARATE file, never the baseline itself: save_baseline
    os.replace()s a new inode into place, so a lock held on the old inode would
    protect nothing after the first write.

    SCAR (review finding, PR #85 round 3): round 3 wrapped --register in this and
    called the race closed. It excluded other registers and nothing else --
    --enforce took no lock at all. But the applier's write and its register are
    two separate steps, so a PostToolUse enforcement landing between them saw the
    write as unsanctioned drift and reverted it while the applier printed OK: the
    sanctioned path losing its own change, silently. Measured 3/3 losses before
    this, 0/3 after (probe_round4_findings phase 3). Register-against-register
    was never the race. Register-against-ENFORCE was.

    Two callers, two contracts:
      writers (--baseline, --register)  timeout=None -> block until acquired.
      verifiers (--check, --enforce)    timeout=N    -> bounded wait, then report
                                        WITHOUT acting. Acting unserialized is
                                        what ate the applier's write; waiting
                                        forever would hand any process a silent
                                        off-switch for enforcement.

    LOCK_HELD_ENV is the parent-holds-it handoff: the applier takes this lock
    around its whole write+register sequence, and `--register` runs as its CHILD,
    which would otherwise block forever on a lock its own parent owns. It is NOT
    a security control. Setting it skips serialization, never detection, and the
    worst it buys an attacker is enforcement running DURING a legitimate apply,
    which is noisy rather than quiet.
    """
    if os.environ.get(LOCK_HELD_ENV) == "1":
        yield True
        return
    path = os.path.join(root, BASELINE_REL) + ".lock"
    fh = None
    held = True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "a+")
        if timeout is None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        elif not _flock_wait(fh, timeout):
            held = False
            fh.close()
            fh = None
    except OSError:
        # The lock file cannot be created AT ALL (read-only tree, no perms).
        # That is not contention, so proceed unlocked rather than refuse: a
        # sanctioned apply that cannot register is reverted one tool call later,
        # and a verifier that refuses to look is worse than one that looks alone.
        if fh is not None:
            fh.close()
        fh = None
        held = True
    try:
        yield held
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()


def save_and_reload(root, entries, baseline):
    """Persist entries while preserving the alarm-dedupe marker."""
    last = baseline.get("last_alarm", "")
    save_baseline(root, entries, last)
    return {"schema_version": 1, "last_alarm": last, "entries": entries}


def measure(root, paths):
    """Record each path's sanctioned identity: link TARGET for a symlink,
    content hash + git blob for a regular file. Never the target's contents."""
    entries = {}
    for rel in paths:
        full = os.path.join(root, rel)
        if os.path.islink(full):
            entries[rel] = {"symlink": os.readlink(full), "sha256": "", "blob": ""}
        else:
            entries[rel] = {"sha256": sha256_file(full), "blob": git_blob_id(root, rel)}
    return entries


def diff(root, baseline):
    """Return (modified, added, removed) against the recorded sanctioned state."""
    recorded = (baseline or {}).get("entries", {})
    current = watch_set(root)
    modified, added = [], []
    for rel in current:
        full = os.path.join(root, rel)
        if rel not in recorded:
            added.append(rel)
            continue
        rec = recorded[rel]
        if os.path.islink(full):
            # Retargeted, or a regular file swapped for a link. Either way the
            # sanctioned identity moved.
            if rec.get("symlink", "") != os.readlink(full):
                modified.append(rel)
        elif rec.get("symlink"):
            modified.append(rel)  # sanctioned as a link, now a regular file
        elif rec.get("sha256") != sha256_file(full):
            modified.append(rel)
    removed = [r for r in recorded if r not in set(current)]
    return sorted(modified), sorted(added), sorted(removed)


def git_head_blob(root, rel):
    """The blob id git HEAD records for `rel`, or "" if untracked at HEAD."""
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "HEAD:%s" % rel],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def attributable(root, rel):
    """True when the file's CURRENT content is exactly what git HEAD records.

    THE RE-BASELINE PATH (review finding, round 3 -- the one that decided the
    design). Round 2 had no way for a legitimate change to update the baseline.
    So a `git pull` that touched any rule left the tree permanently drifted and
    paged an identical SECURITY line every session, forever. That is the
    founder's own complaint -- an alert that fires for a fact nobody can act on
    -- manufactured by the fix for it. Blind or crying wolf are both ignored,
    and ignored is the same as absent.

    All 41 watched files are git-tracked, so git is the provenance oracle: if
    the working content equals the HEAD blob, the change arrived through
    pull / checkout / merge -- a reviewed path -- not through a shell write.

    HONEST BOUND: "attributable" means VISIBLE IN VERSION CONTROL, not "safe".
    An attacker who commits their tamper makes it attributable. That is a real
    bar (it is now in history, diffable and blamed) but it is not a wall, which
    is why this is never applied in --enforce mode; see main().
    """
    full = os.path.join(root, rel)
    if not os.path.isfile(full) or os.path.islink(full):
        return False
    head = git_head_blob(root, rel)
    return bool(head) and head == git_blob_id(root, rel, write=False)


def _git_line(root, argv):
    """One trimmed line of git stdout, or "" on any failure."""
    try:
        out = subprocess.run(["git", "-C", root] + argv,
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def remote_default_refs(root):
    """The remote-tracking refs that stand for REVIEWED content: each remote's
    DEFAULT branch. Prefers the recorded `<remote>/HEAD`, falls back to main then
    master, and returns nothing when a remote publishes neither -- an unknown
    default is not a reviewed one."""
    refs = []
    for remote in _git_line(root, ["remote"]).split():
        head = _git_line(root, ["symbolic-ref", "--quiet",
                                "refs/remotes/%s/HEAD" % remote])
        if head:
            refs.append(head)
            continue
        for name in ("main", "master"):
            ref = "refs/remotes/%s/%s" % (remote, name)
            if _git_line(root, ["rev-parse", "--verify", "--quiet", ref]):
                refs.append(ref)
                break
    return refs


def head_is_reviewed(root):
    """True when HEAD is contained in some remote's DEFAULT branch.

    This is the discriminator round 3 lacked. `attributable()` alone cannot tell
    `git pull` from an agent that wrote a file and committed it -- both leave
    content equal to the HEAD blob -- which is why round 3 refused it in
    --enforce entirely. But that refusal was decided against a surface that did
    not exist yet: this PR wires --enforce PostToolUse on Bash, where the actor
    of a `git pull` is git delivering REVIEWED REMOTE content.

    SCAR (review finding, round 3): the first version of this asked "is HEAD on
    ANY remote-tracking ref", and called that reviewed. Every agent in this fleet
    pushes its own branch -- this PR sits on `sana/ask-291` -- so an agent could
    write .claude/, commit, `git push origin its-own-branch`, and the next
    --enforce ABSORBED the tamper into the baseline and exited 0. Pushing is
    self-service; the reviewed artifact is the DEFAULT branch, which is reached
    through a PR. Narrowing to it only ever downgrades a case from "absorbed
    silently" to "held and paged", never the reverse, so the round-3 invariant
    (--enforce never leaves the worktree inconsistent with HEAD) is untouched.

    One git call per remote per run, not per file.
    """
    refs = remote_default_refs(root)
    if not refs:
        return False  # cannot prove reviewed provenance -> do not sanction
    return bool(_git_line(root, ["for-each-ref", "--contains", "HEAD",
                                 "--format=%(refname)"] + refs))


def matches_head(root, rel):
    """True when the worktree agrees with HEAD about `rel` -- including agreeing
    that it is GONE. The invariant --enforce must never break is leaving the tree
    inconsistent with HEAD; this is the test for it."""
    if not os.path.exists(os.path.join(root, rel)):
        return not git_head_blob(root, rel)
    return attributable(root, rel)


def drift_fingerprint(root, rels):
    """Stable id for one drift state, so an unchanged situation pages once."""
    h = hashlib.sha256()
    for rel in sorted(rels):
        full = os.path.join(root, rel)
        h.update(rel.encode())
        h.update(b":")
        try:
            if os.path.islink(full):
                # Two different link targets are two different drift states, so
                # the second one must not be deduped away as "already paged".
                h.update(b"symlink:" + os.readlink(full).encode())
            elif os.path.isfile(full):
                h.update(sha256_file(full).encode())
            else:
                h.update(b"absent")
        except OSError:
            h.update(b"unreadable")
    return h.hexdigest()


def notify(root, message):
    """Single sink for founder pings (founder-notifications rule). osascript is
    banned: it is silently dropped from a sandboxed/background process."""
    notifier = os.environ.get("KIPI_NOTIFY") or os.path.join(
        root, "q-system", ".q-system", "scripts", "slack-notify.sh")
    try:
        subprocess.run([notifier, message], capture_output=True, timeout=20)
    except Exception:
        pass  # a dead notifier must never stop the revert


def quarantine(root, rels, stamp):
    """Copy drifted content aside BEFORE restoring it. Never silently delete:
    a reverted change stays readable so a false positive costs nothing."""
    qdir = os.path.join(root, QUARANTINE_REL, stamp)
    os.makedirs(qdir, exist_ok=True)
    for rel in rels:
        full = os.path.join(root, rel)
        dest = os.path.join(qdir, rel.replace(os.sep, "__"))
        if os.path.islink(full):
            # Record where it pointed WITHOUT following it. A watched file
            # replaced by a symlink is the tamper shape that turned the restore
            # path into an arbitrary write (review finding, round 2), so the
            # evidence is the target, not the target's contents.
            with open(dest + ".SYMLINK", "w") as fh:
                fh.write(os.readlink(full) + "\n")
        elif os.path.isfile(full):
            shutil.copy2(full, dest)
    return qdir


def _inside_claude(root, full):
    """True only if `full` sits inside <root>/.claude, WITHOUT resolving the
    leaf through a symlink. Compares the resolved PARENT so a symlinked leaf
    cannot smuggle the target outside the tree."""
    base = os.path.realpath(os.path.join(root, ".claude"))
    parent = os.path.realpath(os.path.dirname(full))
    return parent == base or parent.startswith(base + os.sep)


def _restorable(root, rel, full):
    """Where restore() is allowed to write: inside <root>/.claude, or one of the
    two EXTRA_WATCHED guard scripts at its exact literal path.

    The guard scripts live outside `.claude/`, so `_inside_claude` refuses them
    -- measured live the moment they were added to the watch set:

        COULD NOT RESTORE: q-system/.q-system/scripts/claude-path-write-guard.py
        (parent resolves outside .claude/)

    Watching a file this function cannot repair gives a page and no repair, which
    is half the fix. The allowance stays as narrow as the round-2 rule it extends:
    a fixed two-entry tuple, matched by relative path, with the parent resolved
    so a symlinked leaf still cannot smuggle the write somewhere else.
    """
    if rel in EXTRA_WATCHED:
        want = os.path.realpath(os.path.join(root, os.path.dirname(rel)))
        return os.path.realpath(os.path.dirname(full)) == want
    return _inside_claude(root, full)


def restore(root, baseline, modified, added, removed):
    """Put the sanctioned content back.

    SCAR (review finding, round 2 -- the worst defect in round 1): this function
    used to `open(full, "wb")` directly. If an attacker replaced a watched file
    with a SYMLINK pointing outside .claude/, watch_set skipped it (it skips
    symlinks), so it registered as `removed`, and the restore wrote THROUGH the
    link -- silently overwriting an arbitrary file anywhere on disk, leaving the
    link in place, and reporting "reverted 1". The repair path was itself an
    arbitrary-write primitive, which is strictly worse than the hole it closes.

    Two invariants now, both tested:
      1. Never write through a symlink. Unlink it first (removing the LINK, not
         its target), after quarantining it.
      2. Never write to a path whose parent resolves outside <root>/.claude.
         Refuse and report instead. A restore that cannot be done safely is a
         page, not a best effort.
    """
    recorded = baseline.get("entries", {})
    restored, failed = [], []

    for rel in modified + removed:
        full = os.path.join(root, rel)
        if not _restorable(root, rel, full):
            failed.append("%s (parent resolves outside .claude/)" % rel)
            continue
        rec = recorded.get(rel, {})
        if rec.get("symlink"):
            # This path is sanctioned AS a link. Put the link back pointing where
            # the baseline says, rather than writing bytes into it: recreating a
            # link never writes through one, so the round-2 arbitrary-write shape
            # cannot come back through the repair path.
            if os.path.islink(full) or os.path.exists(full):
                os.remove(full)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            os.symlink(rec["symlink"], full)
            restored.append(rel)
            continue
        content = blob_content(root, rec.get("blob", ""))
        if content is None:
            failed.append("%s (no stored blob)" % rel)  # fail loud, never guess
            continue
        if os.path.islink(full):
            # Unlinks the symlink itself. The file it pointed at is untouched.
            os.remove(full)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(content)
        restored.append(rel)

    for rel in added:
        full = os.path.join(root, rel)
        if not _restorable(root, rel, full):
            failed.append("%s (parent resolves outside .claude/)" % rel)
            continue
        if os.path.islink(full) or os.path.isfile(full):
            os.remove(full)  # content is already in quarantine
            restored.append(rel)
    return restored, failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=default_root())
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--enforce", action="store_true")
    ap.add_argument("--register", nargs="*")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    if args.baseline:
        with baseline_lock(root):
            entries = measure(root, watch_set(root))
            path = save_baseline(root, entries)
        if not args.quiet:
            print("baselined %d file(s) -> %s" % (len(entries), os.path.relpath(path, root)))
        return 0

    if args.register is not None:
        # Read-modify-write under an exclusive lock (review finding, PR #85).
        # save_baseline's os.replace is atomic per WRITE, which the round-3
        # comment mistook for single-writer. Two sanctioned appliers registering
        # different paths concurrently both read the same `entries`, both printed
        # success, and the last writer silently dropped the other's path -- so
        # the next --enforce reverted a legitimate, already-reported change.
        # Measured 5/5 losses before this lock, 0/5 after (probe_review_findings
        # phase 4).
        with baseline_lock(root):
            base = load_baseline(root)
            if base is None:
                # NO BASELINE ON THIS TREE (review finding, PR #85). Registering
                # into an empty dict produced a baseline holding only the paths
                # this run wrote, so the very next --enforce saw every OTHER
                # watched file as `added` and DELETED it -- the sanctioned write
                # path wiping .claude/ is a worse outage than the hole it closes.
                # An unarmed tree has no prior sanctioned state to protect, so
                # arm it exactly the way a first --check would (full watch set),
                # then register on top.
                base = {"entries": measure(root, watch_set(root))}
            entries = dict(base.get("entries", {}))
            current = set(watch_set(root))
            for rel in args.register:
                rel = os.path.relpath(os.path.abspath(os.path.join(root, rel)), root)
                if rel in current:
                    entries.update(measure(root, [rel]))
                else:
                    entries.pop(rel, None)
            save_baseline(root, entries, base.get("last_alarm", ""))
        if not args.quiet:
            print("registered %d sanctioned path(s)" % len(args.register))
        return 0

    # Verification runs under the SAME lock as registration (review finding,
    # round 3): otherwise an enforcement landing between the applier's write and
    # its register reverts a sanctioned change the applier then reports as OK.
    # Bounded, because a lock nobody releases must not become a silent
    # off-switch -- a timeout reports and exits non-zero instead of acting.
    with baseline_lock(root, timeout=lock_wait_seconds()) as held:
        if not held:
            print("TRIPWIRE-DEFERRED: the .claude/ baseline lock is held "
                  "(sanctioned apply in flight?); did not verify or act this pass",
                  file=sys.stderr)
            return 1
        return verify(root, args)


def verify(root, args):
    """Diff the tree against its sanctioned baseline, then report (--check) or
    act (--enforce). Always called with the baseline lock held."""
    baseline = load_baseline(root)
    if baseline is None:
        # FIRST RUN IN THIS INSTANCE -> arm silently, do not alarm.
        #
        # SCAR (review finding, round 2, the one that would have hurt most):
        # round 1 COMMITTED the baseline. `kipi update` propagates it fleet-wide,
        # but every instance regenerates .claude/settings.json from
        # settings-template.json -- so the shared baseline could never match, and
        # --check would have paged Slack DAILY ON EVERY INSTANCE. A security fix
        # whose main observable effect is an unactionable daily alarm on every
        # repo the founder owns is a worse defect than the hole it closes.
        #
        # The baseline is therefore INSTANCE-LOCAL and gitignored. That is also
        # the correct semantics: this tripwire answers "did THIS tree change
        # since we last sanctioned it", not "does it match the skeleton".
        entries = measure(root, watch_set(root))
        save_baseline(root, entries)
        # Page once, on the arming transition only. This is deliberate: an
        # attacker who DELETES the baseline to force a clean re-arm produces
        # this same ping in a repo that was already armed, which is the signal.
        notify(root, "armed .claude/ integrity tripwire: %d file(s) baselined" % len(entries))
        if not args.quiet:
            print("armed: baselined %d file(s) (first run)" % len(entries))
        return 0
    if baseline.get("corrupt"):
        notify(root, "SECURITY: .claude integrity baseline is unreadable/corrupt. Tripwire cannot verify.")
        print("BASELINE CORRUPT -- cannot verify .claude/", file=sys.stderr)
        return 2

    modified, added, removed = diff(root, baseline)

    # THE RE-BASELINE PATH. In report mode, absorb every drifted file whose
    # content equals its git HEAD blob: that change came through pull/checkout/
    # merge, which is reviewed, so it is sanctioned and the baseline moves with
    # it. Never in --enforce mode: there the actor is provably the agent, and an
    # agent that writes then commits is precisely the attack this would wave
    # through. (Review finding, round 3.)
    absorbed = []
    sanction_git = (not args.enforce) or head_is_reviewed(root)
    if sanction_git:
        for rel in list(modified) + list(added):
            if attributable(root, rel):
                absorbed.append(rel)
        if absorbed:
            entries = dict(baseline.get("entries", {}))
            entries.update(measure(root, absorbed))
            baseline = save_and_reload(root, entries, baseline)
            modified = [r for r in modified if r not in set(absorbed)]
            added = [r for r in added if r not in set(absorbed)]
        # A file deleted in HEAD is a sanctioned removal, not a tamper.
        still_removed = [r for r in removed if git_head_blob(root, r)]
        if len(still_removed) != len(removed):
            entries = dict(baseline.get("entries", {}))
            for rel in [r for r in removed if r not in set(still_removed)]:
                entries.pop(rel, None)
                absorbed.append(rel)
            baseline = save_and_reload(root, entries, baseline)
            removed = still_removed

    if not (modified or added or removed):
        if not args.quiet:
            msg = "clean: %d file(s) match baseline" % len(baseline.get("entries", {}))
            if absorbed:
                msg += " (re-baselined %d git-attributable change(s))" % len(absorbed)
            print(msg)
        return 0

    summary = "SECURITY: unsanctioned .claude/ change -- %d modified, %d added, %d removed: %s" % (
        len(modified), len(added), len(removed),
        ", ".join((modified + added + removed)[:6]))

    if args.check:
        # Page only when the drift STATE changes. Persisting drift still shows
        # in the session banner and the exit code; it just stops re-paging an
        # identical line forever (finding, round 3). Single writer for alarms:
        # the tripwire decides, session-start only displays.
        fp = drift_fingerprint(root, modified + added + removed)
        if fp != baseline.get("last_alarm", ""):
            notify(root, summary)
            save_baseline(root, baseline.get("entries", {}), fp)
        print(summary, file=sys.stderr)
        print("re-baseline if this was sanctioned: python3 %s --baseline"
              % os.path.relpath(os.path.abspath(__file__), root), file=sys.stderr)
        for rel in modified:
            print("  modified: %s" % rel, file=sys.stderr)
        for rel in added:
            print("  added:    %s" % rel, file=sys.stderr)
        for rel in removed:
            print("  removed:  %s" % rel, file=sys.stderr)
        return 1

    if args.enforce:
        # THE INVARIANT: --enforce never leaves the worktree inconsistent with
        # HEAD. A drifted path whose state already EQUALS HEAD is HELD -- paged
        # and reported, never reverted. Reverting those is what un-applied a
        # `git checkout` three different ways in the reviewer's repro.
        #
        # Reaching here means head_is_pushed() was False (a pushed HEAD was
        # absorbed above), so a held path sits on an UNPUSHED local commit: not
        # sanctioned provenance, but undoing it behind git's back trades a
        # recoverable alarm for a silently broken tree. Report, do not revert.
        held = [r for r in modified + added + removed if matches_head(root, r)]
        heldset = set(held)
        act_mod = [r for r in modified if r not in heldset]
        act_add = [r for r in added if r not in heldset]
        act_rem = [r for r in removed if r not in heldset]

        if not (act_mod or act_add or act_rem):
            msg = summary + " | matches HEAD on an unpushed commit -- reported, NOT reverted"
            fp = drift_fingerprint(root, held)
            if fp != baseline.get("last_alarm", ""):
                notify(root, msg)
                save_baseline(root, baseline.get("entries", {}), fp)
            print(msg, file=sys.stderr)
            return 1

        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        # `removed` is quarantined too: the symlink-swap tamper shows up as a
        # removal, and its target is the evidence (review finding, round 2).
        qdir = quarantine(root, act_mod + act_add + act_rem, stamp)
        restored, failed = restore(root, baseline, act_mod, act_add, act_rem)
        msg = summary + (" | reverted %d, quarantined at %s" % (len(restored), os.path.relpath(qdir, root)))
        if held:
            msg += " | held %d matching HEAD" % len(held)
        if failed:
            msg += " | COULD NOT RESTORE: " + ", ".join(failed)
        notify(root, msg)
        print(msg, file=sys.stderr)
        return 2

    print(summary, file=sys.stderr)
    return 1


if __name__ == "__main__":
    # A crash must exit 3 and say TRIPWIRE-ERROR, never leak a traceback into
    # the drift channel. Round 2 let an exception exit 1 -- the same code as
    # "drift found" -- so session-start paged the founder a Python traceback
    # under a SECURITY headline (finding, round 3). A false security alarm is
    # worse than a missed one: it teaches him to dismiss the banner that counts.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        sys.stderr.write("TRIPWIRE-ERROR: %s: %s\n" % (type(exc).__name__, exc))
        sys.exit(3)
