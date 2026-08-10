#!/usr/bin/env python3
"""Third one-shot pass over claude-path-write-guard.py (ASK-291 round 5).

Self-caught before the round-5 work was reported: _unanchored_unwatched() also
re-examined tokens carrying a NEWLINE. Those are text payloads -- a commit
message, a --body, a progress comment -- and the rule immediately above it
skips them for exactly that reason. So a message merely NAMING
settings.local.json was about to be blocked as a write. That is the fifth false
block of this class in one issue, and the first one this file would have caused
itself; it would have refused the comment reporting the fix.

The unresolved-PREFIX shape (the actual round-5 finding) is untouched.

Usage: python3 patch_round5_guard_pass3.py <path-to-claude-path-write-guard.py>
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

old = '''    Narrow on purpose. `mkdir -p "$D/.claude/rules"` in a temp fixture stays
    ALLOWED -- rules/ is watched, so the handoff is real, and that is the false
    block that has already nearly killed this guard four times.
    """
    out = []
    for arg in args:
        if arg.startswith("-"):
            continue
        if "\\n" not in arg and resolve(arg, cwd, assigns) is not None:
            continue  # anchorable: judged as a real path elsewhere
        tail = literal_claude_tail(arg, assigns)'''

new = '''    Narrow on purpose, twice over:

    * `mkdir -p "$D/.claude/rules"` in a temp fixture stays ALLOWED -- rules/ is
      watched, so the handoff to Layer 2 is real, and that is the false block
      that has already nearly killed this guard four times.
    * a token carrying a NEWLINE is skipped, same as the rule above. Those are
      text payloads (a commit message, a --body, a progress comment), and the
      first version of this function judged them as paths -- so a message that
      merely NAMED settings.local.json would have been refused as a write. It
      would have blocked the comment reporting this very fix. What that costs is
      the exotic `touch $\'.claude/settings.local.json\\ny\'` shape, which stays
      inside the newline gap this file already names.
    """
    out = []
    for arg in args:
        if arg.startswith("-") or "\\n" in arg:
            continue
        if resolve(arg, cwd, assigns) is not None:
            continue  # anchorable: judged as a real path elsewhere
        tail = literal_claude_tail(arg, assigns)'''

if src.count(old) != 1:
    sys.exit("ANCHOR NOT UNIQUE (%d hits)" % src.count(old))

io.open(TARGET, "w", encoding="utf-8").write(src.replace(old, new))
print("patched %s (1 edit)" % TARGET)
