#!/usr/bin/env python3
"""PostToolUse ratchet for portability-lint.sh.

Pairs with: q-system/.q-system/scripts/portability-lint.sh (skill-hook-pairing.md
-- the rule is deterministic, so it gets a hook, not a paragraph).

WHY A RATCHET AND NOT A GATE. The lint finds 24 pre-existing BSD/GNU findings
repo-wide (sp-db43af2f). Turning those into a red gate on day one would block work
nobody is doing today, and the predictable outcome is that someone disables the
gate -- at which point the class comes back with the tool nominally in place. So
this lints ONLY the file that was just written, which means:

  - a file you touch must leave clean, so the count only ever goes down
  - a file you do not touch is not your problem today
  - the pre-existing set is captured in the ledger, not silently tolerated

WHY IT EXISTS AT ALL. Three defects in one session were "green locally, wrong
where it runs" (ASK-221): a BASH_SOURCE-derived root, a test reaching the real
codex CLI, and `mktemp -t` that works on BSD and is rejected by GNU. The third
turned `validate` red on a PR after passing 14/14 on the author's machine. This
repo straddles two kernels -- macOS/BSD locally, Linux/GNU in CI -- so both
directions are real bugs and neither shows up on the machine you are typing on.

EXIT CODES (the contract in skill-hook-pairing.md): 2 = block with stderr fed
back to Claude, 0 = pass. Anything unexpected exits 0: a broken hook must never
be the reason work stops.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, "portability-lint.sh")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    # Self-scope hard and fast-exit on anything else (token-discipline: never run
    # logic on every Edit).
    if not path.endswith((".sh", ".bash")):
        return 0
    if not os.path.isfile(path) or not os.path.isfile(LINT):
        return 0
    # The lint self-excludes by basename; do the same here so editing the lint
    # cannot block on its own vocabulary.
    if os.path.basename(path) == "portability-lint.sh":
        return 0

    # Lint the single file by pointing the scanner at a directory containing only
    # it. The scanner takes a root, so a per-file run means a temp dir with one
    # symlink -- cheaper and clearer than teaching it a second input mode, which
    # would be a second reader of "what do I scan".
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        # COPY, do not symlink. `grep -r` skips symlinks encountered during
        # recursion (only `-R` follows them), so the first cut scanned an empty
        # directory and passed every file including a deliberately bad one. The
        # hook looked wired and enforced nothing -- caught by testing the BLOCK
        # direction first, which is the only reason it did not ship inert.
        import shutil

        link = os.path.join(td, os.path.basename(path))
        try:
            shutil.copyfile(path, link)
        except OSError:
            return 0
        try:
            out = subprocess.run(
                ["bash", LINT, td], capture_output=True, text=True, timeout=30
            )
        except Exception:
            return 0

    if out.returncode == 0:
        return 0

    body = out.stdout.strip()
    if not body:
        return 0
    sys.stderr.write(
        "portability-lint: this file uses a construct that only works on one of "
        "the two kernels this repo runs on (macOS/BSD locally, Linux/GNU in CI).\n\n"
        + body
        + "\n\nThis is a ratchet: only the file you just edited is checked, so the "
        "count only goes down. If the line is a deliberate platform-specific "
        "branch, mark it with `# portability-lint-skip`.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
