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
HELPER_LINT = os.path.join(HERE, "undefined-helper-lint.sh")


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
    if os.path.basename(path) in ("portability-lint.sh", "undefined-helper-lint.sh"):
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
        # TWO LINTS, ONE HOOK. Both answer "is this file silently wrong somewhere
        # other than the machine you are typing on" -- one across kernels, one
        # across a helper that does not exist. A second PostToolUse entry would
        # mean a second place to forget to wire, and an unwired lint is an inert
        # engine (sp-72b60bff), which is the thing this repo keeps finding.
        body_parts = []
        for script in (LINT, HELPER_LINT):
            if not os.path.isfile(script):
                continue
            try:
                out = subprocess.run(
                    ["bash", script, td], capture_output=True, text=True, timeout=30
                )
            except Exception:
                continue
            if out.returncode != 0 and out.stdout.strip():
                body_parts.append(out.stdout.strip())

    if not body_parts:
        return 0
    body = "\n\n".join(body_parts)
    # The header must not name a class the finding may not belong to. It said
    # "only works on one of the two kernels" for EVERY finding, so an undefined
    # helper was reported as a portability bug -- a message that misdescribes its
    # own finding sends the reader to fix the wrong thing.
    sys.stderr.write(
        "shell lint: this file is silently wrong somewhere other than the machine "
        "you are typing on.\n\n"
        + body
        + "\n\nThis is a ratchet: only the file you just edited is checked, so the "
        "count only goes down. A deliberate platform-specific line can be marked "
        "`# portability-lint-skip`.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
