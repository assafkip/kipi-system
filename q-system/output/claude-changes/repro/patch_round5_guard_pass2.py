#!/usr/bin/env python3
"""Second one-shot pass over claude-path-write-guard.py (ASK-291 round 5).

Pass 1 fixed the dead test citation but kept the dead filename inside the scar
sentence ("rounds 1-4 cited X, which never existed"). probe_round5_findings.sh
phase 4 still failed, and correctly: a grep cannot tell a citation from a
correction, and neither can a reviewer skimming the file. The scar is worth
keeping; the dead filename is not.

Same write-then-register constraint as pass 1 -- see patch_round5_guard.py.
Usage: python3 patch_round5_guard_pass2.py <path-to-claude-path-write-guard.py>
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

old = '''# what the protected set IS is worse than either bound alone. Rounds 1-4 cited
# `test_claude_path_write_guard.py`, a file that has never existed in this repo
# (review finding, round 5): a citation nobody can open is not a citation, it
# reads as coverage that is not there.'''

new = '''# what the protected set IS is worse than either bound alone. Rounds 1-4 named a
# test file that has never existed in this repo (review finding, round 5): a
# citation nobody can open is not a citation, it reads as coverage that is not
# there. The dead name is deliberately not repeated here -- a grep cannot tell a
# citation from a correction, so leaving it in leaves the finding standing.'''

if src.count(old) != 1:
    sys.exit("ANCHOR NOT UNIQUE (%d hits)" % src.count(old))

io.open(TARGET, "w", encoding="utf-8").write(src.replace(old, new))
print("patched %s (1 edit)" % TARGET)
