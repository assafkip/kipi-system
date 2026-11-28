#!/usr/bin/env python3
"""Shipped-blob map for kipi-update.sh: every blob the skeleton ever committed, per path.

Why this exists (ASK-5851): fleet_authored_blob answered "was this exact content ever
shipped for this path" with `git rev-list <ref> -- <path>` plus one `git rev-parse
<commit>:<path>` per commit, per file, per instance. lessons-daily's fleet sync ran
7.5h+ on 2026-11-27 spawning one rev-list a second over 282 lesson files. One
`git log -m --raw` pass over the whole history takes about 0.3s and carries the same
facts: the blob each commit left at each path.

Output: one `<path>\\t<blob>` line per (path, blob) the history ever wrote, sorted and
unique. A path's deletion writes no blob, matching the old loop where rev-parse of a
deleted path came back empty and never equalled the instance's hash.

`-m` is deliberate: the old rev-list walked merge commits too, so a conflict-resolved
merge whose blob exists on no side is still a shipped blob. `--no-renames` keeps a
moved path's blob under its new name, as `rev-parse <commit>:<path>` saw it.
"""
import os
import subprocess
import sys

ZERO = set("0")


def build_map(repo: str, ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "log", "-m", "--raw", "--no-renames", "--no-abbrev",
         "--format=", "-z", ref],
        check=True, capture_output=True,
    ).stdout.decode("utf-8", "surrogateescape")
    parts = out.split("\0")
    seen: set[str] = set()
    i = 0
    # -z raw records are `:<modes> <old> <new> <status>` NUL `<path>` NUL.
    while i < len(parts) - 1:
        meta = parts[i].lstrip("\n")
        if not meta.startswith(":"):
            i += 1
            continue
        fields = meta[1:].split()
        path = parts[i + 1]
        i += 2
        new, status = fields[3], fields[4]
        if status[0] == "D" or set(new) <= ZERO:
            continue
        seen.add(f"{path}\t{new}")
    return sorted(seen)


def tracked_paths(root: str) -> set[str]:
    """Every path the instance index tracks, from ONE `git ls-files -z`.

    ASK-5855: instance_ahead_scan ran `git ls-files --error-unmatch -- <path>` once
    per rsync candidate. rsync -ain lists every file whose mtime differs, which in a
    fresh dry-run model is every file, so that was ~3,000 git calls per instance.
    Exact set membership, not pathspec: a candidate is always a regular file, so
    the only case this reads differently is a filename holding glob characters,
    where the old pathspec could match a DIFFERENT tracked file.
    """
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                         check=True, capture_output=True).stdout
    return {p for p in out.decode("utf-8", "surrogateescape").split("\0") if p}


def _hash_one(repo: str, path: str) -> str:
    res = subprocess.run(["git", "-C", repo, "hash-object", "--", path],
                         capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def hash_paths(repo: str, paths: list[str]) -> list[str]:
    """Blob id per path ("" where git cannot hash it), from ONE hash-object call.

    Same answer as `git -C <repo> hash-object -- <path>` per file, which is what
    fleet_authored_blob ran. --stdin-paths aborts the whole batch on one unreadable
    file, so a failed or short batch falls back to the per-file call: slower, never
    a different answer. A path holding a newline cannot ride a line protocol and
    always takes the per-file call.
    """
    if not paths:
        return []
    # Only readable regular files ride the batch (PR #911 review): one dangling
    # symlink or vanished file would abort it and send EVERY path to the per-file
    # call. The rest take the per-file call, which answers "" for them as before.
    batchable = [p for p in paths if "\n" not in p and os.path.isfile(p)
                 and os.access(p, os.R_OK)]
    by_path: dict[str, str] = {}
    if batchable:
        res = subprocess.run(["git", "-C", repo, "hash-object", "--stdin-paths"],
                             input="".join(p + "\n" for p in batchable).encode(
                                 "utf-8", "surrogateescape"),
                             capture_output=True)
        blobs = res.stdout.decode().split()
        if res.returncode == 0 and len(blobs) == len(batchable):
            by_path = dict(zip(batchable, blobs))
        else:
            print(f"WARN: hash-object --stdin-paths failed (rc {res.returncode}); "
                  f"hashing {len(batchable)} file(s) one by one", file=sys.stderr)
    return [by_path[p] if p in by_path else _hash_one(repo, p) for p in paths]


def load_map(map_file: str) -> set[str]:
    """The `<path>\\t<blob>` lines build_map wrote. "" means the map is unavailable,
    which reads as "nothing shipped", exactly as fleet_authored_blob returned 1."""
    if not map_file:
        return set()
    with open(map_file, encoding="utf-8", errors="surrogateescape") as handle:
        return {line.rstrip("\n") for line in handle}


def filter_ahead(repo: str, root: str, map_file: str, records: list[list[str]]) -> list[list[str]]:
    """Keep the records the old per-file loop would have reported, in input order.

    A record is [kind, shown, blob_rel, file, skel_file]; skel_file is "" for a
    deletion and is only passed through. Dropped when `shown` is untracked in
    root (the `ls-files --error-unmatch ... || continue`), or when the bytes at
    `file` equal a blob the skeleton shipped at `blob_rel` (fleet_authored_blob).
    """
    tracked = tracked_paths(root)
    kept = [r for r in records if r[1] in tracked]
    shipped = load_map(map_file)
    blobs = hash_paths(repo, [r[3] for r in kept])
    return [r for r, blob in zip(kept, blobs)
            if not (blob and f"{r[2]}\t{blob}" in shipped)]


def filter_main(argv: list[str]) -> int:
    """`filter <repo> <root> <map-or-empty>`: TSV records on stdin, survivors on stdout."""
    if len(argv) != 5:
        print("usage: kipi-update-shipped-blobs.py filter <repo> <root> <map-or-empty>",
              file=sys.stderr)
        return 2
    raw = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    records = [line.split("\t") for line in raw.split("\n") if line]
    try:
        kept = filter_ahead(argv[2], argv[3], argv[4], records)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"filter failed: {exc}", file=sys.stderr)
        return 1
    out = "".join("\t".join(r) + "\n" for r in kept)
    sys.stdout.buffer.write(out.encode("utf-8", "surrogateescape"))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "filter":
        return filter_main(argv)
    if len(argv) != 3:
        print("usage: kipi-update-shipped-blobs.py <repo> <ref>", file=sys.stderr)
        return 2
    try:
        lines = build_map(argv[1], argv[2])
    except subprocess.CalledProcessError as exc:
        print(f"git log failed: {exc.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 1
    sys.stdout.write("".join(line + "\n" for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
