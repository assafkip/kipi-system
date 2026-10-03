#!/usr/bin/env python3
"""Throwaway: apply one mutation and PROVE it landed. Exit 1 if the target is
absent or the write did not change the file, so a bad mutation target reports
itself instead of reading as a surviving mutant."""
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read()
if src.count(old) != 1:
    print(f"target appears {src.count(old)} times, need exactly 1: {old!r}", file=sys.stderr)
    sys.exit(1)
out = src.replace(old, new, 1)
if out == src:
    print("replacement was a no-op", file=sys.stderr)
    sys.exit(1)
open(path, "w").write(out)
assert new in open(path).read(), "mutant not on disk after write"
