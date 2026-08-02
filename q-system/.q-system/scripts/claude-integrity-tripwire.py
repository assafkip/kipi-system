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
import hashlib
import json
import os
import shutil
import subprocess
import sys
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
    """Every file under <root>/.claude/ that is not volatile, as repo-relative paths."""
    base = os.path.join(root, ".claude")
    found = []
    if not os.path.isdir(base):
        return found
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if name in EXCLUDED_FILES:
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
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


def save_baseline(root, entries):
    path = os.path.join(root, BASELINE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {
        "schema_version": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Sanctioned content of .claude/. See claude-integrity-tripwire.py (ASK-282).",
        "entries": entries,
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)  # single-writer: atomic swap, never a half-written baseline
    return path


def measure(root, paths):
    entries = {}
    for rel in paths:
        full = os.path.join(root, rel)
        entries[rel] = {"sha256": sha256_file(full), "blob": git_blob_id(root, rel)}
    return entries


def diff(root, baseline):
    """Return (modified, added, removed) against the recorded sanctioned state."""
    recorded = (baseline or {}).get("entries", {})
    current = watch_set(root)
    modified, added = [], []
    for rel in current:
        full = os.path.join(root, rel)
        now = sha256_file(full)
        if rel not in recorded:
            added.append(rel)
        elif recorded[rel].get("sha256") != now:
            modified.append(rel)
    removed = [r for r in recorded if r not in set(current)]
    return sorted(modified), sorted(added), sorted(removed)


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
        if os.path.isfile(full):
            shutil.copy2(full, os.path.join(qdir, rel.replace(os.sep, "__")))
    return qdir


def restore(root, baseline, modified, added, removed):
    recorded = baseline.get("entries", {})
    restored, failed = [], []
    for rel in modified + removed:
        content = blob_content(root, recorded.get(rel, {}).get("blob", ""))
        if content is None:
            failed.append(rel)  # fail loud; never guess at content
            continue
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(content)
        restored.append(rel)
    for rel in added:
        full = os.path.join(root, rel)
        if os.path.isfile(full):
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
        entries = measure(root, watch_set(root))
        path = save_baseline(root, entries)
        if not args.quiet:
            print("baselined %d file(s) -> %s" % (len(entries), os.path.relpath(path, root)))
        return 0

    if args.register is not None:
        base = load_baseline(root) or {"entries": {}}
        entries = dict(base.get("entries", {}))
        current = set(watch_set(root))
        for rel in args.register:
            rel = os.path.relpath(os.path.abspath(os.path.join(root, rel)), root)
            if rel in current:
                entries.update(measure(root, [rel]))
            else:
                entries.pop(rel, None)
        save_baseline(root, entries)
        if not args.quiet:
            print("registered %d sanctioned path(s)" % len(args.register))
        return 0

    baseline = load_baseline(root)
    if baseline is None:
        # No baseline yet is not "clean" -- it is "unknown". Say so.
        if not args.quiet:
            print("NO BASELINE: run --baseline first (tripwire is not armed)")
        return 0
    if baseline.get("corrupt"):
        notify(root, "SECURITY: .claude integrity baseline is unreadable/corrupt. Tripwire cannot verify.")
        print("BASELINE CORRUPT -- cannot verify .claude/", file=sys.stderr)
        return 2

    modified, added, removed = diff(root, baseline)
    if not (modified or added or removed):
        if not args.quiet:
            print("clean: %d file(s) match baseline" % len(baseline.get("entries", {})))
        return 0

    summary = "SECURITY: unsanctioned .claude/ change -- %d modified, %d added, %d removed: %s" % (
        len(modified), len(added), len(removed),
        ", ".join((modified + added + removed)[:6]))

    if args.check:
        print(summary, file=sys.stderr)
        for rel in modified:
            print("  modified: %s" % rel, file=sys.stderr)
        for rel in added:
            print("  added:    %s" % rel, file=sys.stderr)
        for rel in removed:
            print("  removed:  %s" % rel, file=sys.stderr)
        return 1

    if args.enforce:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        qdir = quarantine(root, modified + added, stamp)
        restored, failed = restore(root, baseline, modified, added, removed)
        msg = summary + (" | reverted %d, quarantined at %s" % (len(restored), os.path.relpath(qdir, root)))
        if failed:
            msg += " | COULD NOT RESTORE: " + ", ".join(failed)
        notify(root, msg)
        print(msg, file=sys.stderr)
        return 2

    print(summary, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
