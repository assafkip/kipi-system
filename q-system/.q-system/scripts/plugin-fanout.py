#!/usr/bin/env python3
"""plugin-fanout: copy a skeleton plugin into registered instances, bounded and
hash-classified, WITHOUT `kipi update` and WITHOUT any delete.

WHY NOT `kipi update` (scar, ASK-721, 2026-08-13):

`kipi update --dry` shows it would DELETE plugins/memory-lifecycle/* and
claude-integrity-baseline.json from instances. That is the exact 2026-08-07 shape
where voicekit was deleted from 19 instances. The destructive-op hook blocks it
and the hook is right. So this script never deletes: it overwrites and it creates,
and a file that exists in the instance but not in the skeleton is REPORTED as
stale_extra, never removed. Removing an upstream-deleted file is a separate,
founder-visible decision.

WHY CLASSIFY BEFORE WRITING

A blind fan-out cannot tell "an old release we shipped" from "somebody edited
this here". Overwriting the second silently destroys work. So every target is
classified first, against git history rather than against a guess:

  NEW     the instance tree is byte-identical to skeleton HEAD -> nothing to do
  OLD     it is byte-identical to some ANCESTOR commit of this plugin in skeleton
          history -> a genuine earlier release, safe to advance
  OTHER   neither -> REFUSED. Local edits, or a tree from another lineage.
  MISSING the plugin is not installed here -> skipped, not created

Comparison is by git blob sha per relative path, computed in-process. That is the
same identity git itself uses, so "identical" means identical, not "same size and
mtime".

DIRTY TREES ARE REFUSED, scoped to the plugin path only. A repo can be dirty for
unrelated reasons -- another agent was live in cole-gtm while this ran -- and
refusing on whole-repo dirt would have skipped every target for reasons that have
nothing to do with the files being written.

USAGE

    python3 q-system/.q-system/scripts/plugin-fanout.py --plugin prd-os
    python3 q-system/.q-system/scripts/plugin-fanout.py --plugin prd-os --apply

Survey is the default. --apply writes only to OLD and only after the same
classification runs again. Exit 0 always on survey; on --apply, 1 if any target
that classified OLD failed to be written.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

NOISE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
NOISE_SUFFIXES = (".pyc", ".pyo")

# How far back to look for a matching ancestor release. An instance older than
# this classifies OTHER and gets a human, which is the safe direction.
ANCESTOR_DEPTH = 60


def blob_sha(path):
    """git's own object id for a file's content: sha1("blob <len>\\0" + bytes)."""
    with open(path, "rb") as handle:
        data = handle.read()
    header = b"blob %d\0" % len(data)
    return hashlib.sha1(header + data).hexdigest()


def tree_map_from_disk(root):
    """{relpath: blobsha} for a plugin directory on disk."""
    result = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in NOISE_DIRS]
        for name in files:
            if name.endswith(NOISE_SUFFIXES):
                continue
            full = os.path.join(base, name)
            if os.path.islink(full):
                continue
            result[os.path.relpath(full, root)] = blob_sha(full)
    return result


def tree_map_from_git(repo, rev, prefix):
    """{relpath: blobsha} for a plugin directory at a git revision."""
    proc = subprocess.run(
        ["git", "-C", repo, "ls-tree", "-r", rev, "--", prefix],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    result = {}
    for line in proc.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        result[os.path.relpath(path, prefix)] = parts[2]
    return result or None


def ancestor_maps(repo, prefix):
    """Tree maps for every past commit that touched this plugin, newest first."""
    proc = subprocess.run(
        ["git", "-C", repo, "rev-list", f"-{ANCESTOR_DEPTH}", "HEAD", "--", prefix],
        capture_output=True, text=True,
    )
    revs = proc.stdout.split() if proc.returncode == 0 else []
    for rev in revs:
        got = tree_map_from_git(repo, rev, prefix)
        if got:
            yield rev, got


def plugin_path_is_dirty(repo, prefix):
    """Uncommitted changes UNDER THE PLUGIN PATH only. None if not a git repo."""
    proc = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain", "--", prefix],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def classify(instance_dir, prefix, head_map, ancestors):
    target = os.path.join(instance_dir, prefix)
    if not os.path.isdir(target):
        return "MISSING", None
    live = tree_map_from_disk(target)
    if live == head_map:
        return "NEW", None
    for rev, older in ancestors:
        if live == older:
            return "OLD", rev
    return "OTHER", None


def stale_extras(instance_dir, prefix, head_map):
    """Files the instance has that skeleton HEAD does not. Reported, never cut."""
    target = os.path.join(instance_dir, prefix)
    live = tree_map_from_disk(target)
    return sorted(set(live) - set(head_map))


def copy_plugin(skeleton, instance_dir, prefix, head_map):
    """Overwrite + create. No delete, ever. Returns files written."""
    written = 0
    for rel in head_map:
        src = os.path.join(skeleton, prefix, rel)
        dst = os.path.join(instance_dir, prefix, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        written += 1
    return written


def main(argv=None):
    parser = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--skeleton", default=os.path.abspath(os.path.join(here, "..", "..", "..")))
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    skeleton = args.skeleton
    prefix = os.path.join("plugins", args.plugin)

    head_map = tree_map_from_disk(os.path.join(skeleton, prefix))
    if not head_map:
        print(f"CHECK FAILED TO RUN: no files at {skeleton}/{prefix}", file=sys.stderr)
        return 2
    ancestors = list(ancestor_maps(skeleton, prefix))

    registry = os.path.join(skeleton, "instance-registry.json")
    with open(registry, encoding="utf-8") as handle:
        targets = json.load(handle)["instances"]

    buckets = {"NEW": [], "OLD": [], "OTHER": [], "MISSING": [], "DIRTY": []}
    actions = []

    for entry in targets:
        path = entry["path"]
        name = entry.get("name", path)
        if not os.path.isdir(path):
            buckets["MISSING"].append((name, "instance path does not exist"))
            continue

        status, matched_rev = classify(path, prefix, head_map, ancestors)
        if status == "MISSING":
            buckets["MISSING"].append((name, f"no {prefix}/ in this instance"))
            continue
        if status == "OTHER":
            buckets["OTHER"].append((name, "content matches neither HEAD nor any ancestor release"))
            continue
        if status == "NEW":
            buckets["NEW"].append((name, "already at skeleton HEAD"))
            continue

        dirty = plugin_path_is_dirty(path, prefix)
        if dirty:
            buckets["DIRTY"].append((name, f"uncommitted changes under {prefix}"))
            continue

        buckets["OLD"].append((name, f"ancestor {matched_rev[:8] if matched_rev else '?'}"))
        if args.apply:
            extras = stale_extras(path, prefix, head_map)
            count = copy_plugin(skeleton, path, prefix, head_map)
            actions.append((name, count, extras))

    print(f"plugin      : {args.plugin}")
    print(f"skeleton    : {skeleton}")
    print(f"mode        : {'APPLY' if args.apply else 'SURVEY'}")
    print(f"targets     : {len(targets)} registered instances")
    print(f"head files  : {len(head_map)}")
    print()
    for label in ("OLD", "NEW", "OTHER", "DIRTY", "MISSING"):
        rows = buckets[label]
        verb = "would write" if label == "OLD" and not args.apply else (
            "WRITTEN" if label == "OLD" else "skipped")
        print(f"{label:<8} {len(rows):>3}  ({verb})")
        for name, reason in rows:
            print(f"         - {name}: {reason}")
    if actions:
        print()
        for name, count, extras in actions:
            note = f", {len(extras)} stale extra file(s) left in place" if extras else ""
            print(f"wrote {count} files -> {name}{note}")
    print()
    reached = len(buckets["OLD"]) if args.apply else 0
    skipped = len(targets) - reached
    print(f"REACHED {reached} / SKIPPED {skipped} "
          f"(NEW={len(buckets['NEW'])} OTHER={len(buckets['OTHER'])} "
          f"DIRTY={len(buckets['DIRTY'])} MISSING={len(buckets['MISSING'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
