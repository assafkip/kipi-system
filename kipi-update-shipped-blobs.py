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


def main(argv: list[str]) -> int:
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
