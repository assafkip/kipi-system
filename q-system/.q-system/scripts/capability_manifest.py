#!/usr/bin/env python3
"""Assemble the capability manifest from a per-declaration FRAGMENT DIRECTORY.

WHY THIS SHAPE (scar, measured 2026-08-29 over the 57-PR backlog).
`q-system/.q-system/capability-manifest.json` was one hand-maintained file
holding one unsorted 182-entry `expected_tests` array. Every branch that added
a test appended to the end of that array, so every branch collided with every
other branch on the same lines: the manifest was the conflict in 37 of 41
conflicting PRs and the ONLY conflict in 16 of them. Resolving it by hand costs
a full re-read of main's manifest per PR (main had also restructured entries
and grown a `scope_exempt` block, so "take theirs and re-add mine" is the only
correct resolution) and that does not scale to 37.

WHY NOT A MERGE DRIVER. Measured, not assumed: GitHub does NOT run merge
drivers when it computes mergeability. Five PRs (#212, #209, #208, #154, #80)
that `git merge` resolves CLEAN via the built-in `union` driver on
`.prd-os/receipts.jsonl` are still reported CONFLICTING in the GitHub UI. A
driver would leave all 37 looking exactly as blocked, which is the thing that
had to change.

WHY NOT UNTRACK IT. `present-but-undeclared` is the whole point of the gate.
Deleting the declaration deletes the gate.

So: one file per declaration. Two branches adding two declarations write two
different filenames in the same directory, which git merges as two adds and
GitHub reports as mergeable. The assembled view is built in memory here and
handed to every consumer, so nothing downstream learns the layout.

SINGLE WRITER. If the legacy monolith and the fragment directory both exist,
this refuses instead of picking one. A rebase that resurrects
capability-manifest.json would otherwise silently drop that branch's
declarations, which is the same class of loss the migration exists to end.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FRAGMENT_DIR = "q-system/.q-system/capability"
LEGACY_MANIFEST = "q-system/.q-system/capability-manifest.json"
META_FILE = "manifest.json"

# Section name == the top-level manifest key == the subdirectory name. One
# mapping, no translation table to drift: a reader who knows the assembled
# manifest already knows the directory layout.
LIST_SECTIONS = (
    "expected_tests",
    "required_data",
    "skeleton_only",
    "declared_inert",
    "uncovered_known",
    "scope_exempt",
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def entry_key(section, entry):
    """The natural identity of one declaration, used to name its fragment.

    Path-keyed for the sections that declare a file; `prefix` for scope_exempt;
    the note text itself for uncovered_known, which is free prose with no other
    identity. A section whose entry has no key at all still gets a fragment --
    the key falls back to the entry's canonical JSON -- so a malformed entry is
    still round-trippable rather than silently dropped at migration time.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for field in ("path", "prefix"):
            if isinstance(entry.get(field), str) and entry[field]:
                return entry[field]
    return json.dumps(entry, sort_keys=True)


def fragment_name(section, entry):
    """Deterministic filename for one declaration. A pure function of the entry
    alone: adding a declaration must never rename an existing fragment, because
    a rename is a conflict and conflicts are the thing being removed.

    Branch A (readable) applies only when the key has no literal `__` and no
    `--`, so `/`->`__` stays reversible and branch-B names stay distinguishable.
    Branch B carries a sha1 of the full key, so it is injective by construction.
    `load()` re-derives this name for every entry it reads and errors on a
    mismatch, so a naming bug is loud rather than a silent overwrite.
    """
    key = entry_key(section, entry)
    safe = key.replace("/", "__")
    if ("__" not in key and "--" not in key and len(safe) <= 120
            and _SAFE_NAME.match(safe)):
        return safe + ".json"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    stem = _UNSAFE_CHARS.sub("_", safe)[:96].strip("_") or "entry"
    return "%s--%s.json" % (stem, digest)


def fragment_dir(root):
    return Path(root) / FRAGMENT_DIR


def legacy_path(root):
    return Path(root) / LEGACY_MANIFEST


def _err(errors, msg):
    if errors is not None:
        errors.append(msg)


def load(root, errors=None):
    """Assemble the manifest. Returns a dict, or None when it cannot be read.

    Never raises on content: every problem is appended to `errors`, because two
    of the three callers (the ratchet census, the CI-shaped runner) treat an
    unreadable manifest as "no data" and must not crash on one bad fragment.
    """
    root = Path(root)
    fdir = fragment_dir(root)
    legacy = legacy_path(root)

    if fdir.is_dir() and legacy.is_file():
        _err(errors,
             "TWO manifest sources present: %s and the legacy %s. One writer "
             "only -- delete the legacy file and move its entries into "
             "fragments (see capability_manifest.py --explode-from)."
             % (FRAGMENT_DIR, LEGACY_MANIFEST))
        return None
    if not fdir.is_dir():
        if legacy.is_file():
            _err(errors,
                 "legacy monolithic manifest present but %s is missing; this "
                 "checkout predates the fragment migration" % FRAGMENT_DIR)
        else:
            # Wording pinned: "manifest missing:" is the phrase the gate's
            # own suite and its callers assert on. The layout moved; the
            # refusal contract did not.
            _err(errors, "manifest missing: %s (fragment directory)" % FRAGMENT_DIR)
        return None

    meta_path = fdir / META_FILE
    if not meta_path.is_file():
        _err(errors, "manifest meta missing: %s/%s" % (FRAGMENT_DIR, META_FILE))
        return None
    try:
        data = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        _err(errors, "manifest meta malformed JSON (%s/%s): %s"
             % (FRAGMENT_DIR, META_FILE, exc))
        return None
    if not isinstance(data, dict):
        _err(errors, "manifest meta must be a JSON object: %s/%s"
             % (FRAGMENT_DIR, META_FILE))
        return None
    if set(data) - {"schema_version"}:
        _err(errors, "manifest meta may only carry schema_version, found: %s"
             % sorted(set(data) - {"schema_version"}))

    known = set(LIST_SECTIONS)
    for child in sorted(fdir.iterdir()):
        if child.is_dir() and child.name not in known:
            _err(errors, "unknown fragment section directory: %s/%s"
                 % (FRAGMENT_DIR, child.name))
        elif child.is_file() and child.name != META_FILE:
            _err(errors, "stray file in fragment root (declarations live in a "
                 "section subdirectory): %s/%s" % (FRAGMENT_DIR, child.name))

    for section in LIST_SECTIONS:
        sdir = fdir / section
        items = []
        if sdir.is_dir():
            for frag in sorted(sdir.iterdir()):
                if frag.name.startswith("."):
                    continue
                if not frag.is_file() or frag.suffix != ".json":
                    _err(errors, "non-JSON fragment: %s/%s/%s"
                         % (FRAGMENT_DIR, section, frag.name))
                    continue
                try:
                    entry = json.loads(frag.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    _err(errors, "fragment malformed JSON (%s/%s/%s): %s"
                         % (FRAGMENT_DIR, section, frag.name, exc))
                    continue
                expected = fragment_name(section, entry)
                if expected != frag.name:
                    # A mismatch means two entries could map to one file and
                    # one would silently overwrite the other. Loud, always.
                    _err(errors,
                         "fragment filename does not match its declaration: "
                         "%s/%s/%s should be %s"
                         % (FRAGMENT_DIR, section, frag.name, expected))
                items.append(entry)
        data[section] = items
    return data


def explode(root, manifest, errors=None):
    """Write one fragment per declaration. Used by the migration and by tests.

    Rewrites the section directories from scratch so an explode is idempotent
    and never leaves a stale fragment behind (a stale fragment is a declaration
    nobody wrote, which is the inverse of the bug this file exists for).
    """
    fdir = fragment_dir(root)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / META_FILE).write_text(json.dumps(
        {"schema_version": manifest.get("schema_version")}, indent=1) + "\n")
    written = 0
    for section in LIST_SECTIONS:
        sdir = fdir / section
        if sdir.is_dir():
            for old in sdir.iterdir():
                if old.is_file():
                    old.unlink()
        entries = manifest.get(section) or []
        if not entries and not sdir.is_dir():
            continue
        sdir.mkdir(parents=True, exist_ok=True)
        seen = {}
        for entry in entries:
            name = fragment_name(section, entry)
            if name in seen:
                _err(errors, "two %s declarations map to one fragment %s: %r and %r"
                     % (section, name, seen[name], entry))
                continue
            seen[name] = entry
            (sdir / name).write_text(json.dumps(entry, indent=1,
                                                sort_keys=True) + "\n")
            written += 1
    return written


def add_delta(root, base, head, errors=None):
    """Write a fragment for every declaration `head` has that `base` does not.

    The rebase tool for the 37 open branches that predate the split. Their
    manifest edit is almost always one appended entry; replaying it by hand
    means re-reading main's whole manifest per PR, which is what did not scale.
    Feed it the merge-base manifest and the branch-head manifest and it writes
    exactly that branch's additions as fragments, touching nothing else.

    Additive ONLY. A branch that REMOVED a declaration is reported, never acted
    on: deleting someone else's declaration during a rebase is the silent loss
    this whole change exists to prevent, so it is surfaced for a human.
    """
    written, removed = [], []
    for section in LIST_SECTIONS:
        seen = {json.dumps(e, sort_keys=True) for e in (base.get(section) or [])}
        have = {json.dumps(e, sort_keys=True) for e in (head.get(section) or [])}
        for raw in sorted(have - seen):
            entry = json.loads(raw)
            sdir = fragment_dir(root) / section
            sdir.mkdir(parents=True, exist_ok=True)
            name = fragment_name(section, entry)
            (sdir / name).write_text(json.dumps(entry, indent=1,
                                                sort_keys=True) + "\n")
            written.append("%s/%s" % (section, name))
        for raw in sorted(seen - have):
            removed.append("%s: %s" % (section, raw))
    if removed:
        _err(errors, "this branch also REMOVED %d declaration(s); replay those "
                     "by hand rather than silently: %s"
                     % (len(removed), " | ".join(removed)))
    return written


def equivalent(a, b):
    """Order-insensitive equality of two assembled manifests.

    Order is not part of the contract: every consumer either set-ifies the
    entries (the declared-vs-actual diff, the ratchet census) or iterates them
    to run each one. Comparing sorted canonical JSON is what "lossless" means
    here, and it is what the migration proof asserts.
    """
    def norm(m):
        out = {"schema_version": m.get("schema_version")}
        for section in LIST_SECTIONS:
            out[section] = sorted(json.dumps(e, sort_keys=True)
                                  for e in (m.get(section) or []))
        return out
    return norm(a) == norm(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="print the assembled manifest as JSON on stdout")
    ap.add_argument("--explode-from", metavar="FILE",
                    help="write fragments from a monolithic manifest JSON file")
    ap.add_argument("--check-against", metavar="FILE",
                    help="assemble and prove equivalence with a monolithic file")
    ap.add_argument("--add-from", nargs=2, metavar=("BASE_JSON", "HEAD_JSON"),
                    help="replay a pre-split branch: write a fragment for every "
                         "declaration HEAD_JSON adds over BASE_JSON")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if args.explode_from:
        manifest = json.loads(Path(args.explode_from).read_text())
        errors = []
        n = explode(root, manifest, errors)
        for e in errors:
            print("ERROR: " + e, file=sys.stderr)
        print("wrote %d fragment(s) under %s" % (n, FRAGMENT_DIR))
        return 1 if errors else 0

    if args.add_from:
        base = json.loads(Path(args.add_from[0]).read_text())
        head = json.loads(Path(args.add_from[1]).read_text())
        errors = []
        written = add_delta(root, base, head, errors)
        for w in written:
            print("added fragment: %s/%s" % (FRAGMENT_DIR, w))
        for e in errors:
            print("ERROR: " + e, file=sys.stderr)
        print("%d declaration(s) replayed" % len(written))
        return 1 if errors else 0

    errors = []
    assembled = load(root, errors)
    for e in errors:
        print("ERROR: " + e, file=sys.stderr)
    if assembled is None:
        return 1
    if args.check_against:
        other = json.loads(Path(args.check_against).read_text())
        ok = equivalent(assembled, other)
        print("equivalent: %s" % ok)
        return 0 if ok and not errors else 1
    if args.do_print or not args.check_against:
        json.dump(assembled, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
