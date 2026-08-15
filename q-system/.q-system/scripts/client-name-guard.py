#!/usr/bin/env python3
"""Block a client name from reaching a PUBLIC repo, in staged content or the message.

Scar (2026-08-13): a pre-push scan of 15 commits found a captured production
alert sitting in a test fixture that carried a CLIENT NAME and the founder's
absolute home path, plus two commit subjects naming clients. This repo is public
with 102 stars and 23 forks. gitleaks passed all of it, because a client name is
not a secret in the credential sense. Nothing else looked.

The offending strings are described by CLASS above and deliberately NOT quoted
here. Quoting them would republish the exact data this file exists to keep out
of a public repo -- and this file is on the guard's own exclusion list, so
nothing would have stopped it. That is not hypothetical: for one commit this
docstring did quote them verbatim, which put a client name and a real home path
back into the public tree and tripped validate-separation.py's skeleton sweep
(caught 2026-08-14, ASK-746). A privacy exclusion names the data class, never
the data.

Two of those were already public and could not be recalled: rewriting history
does not remove objects that 23 forks already hold, and GitHub keeps dangling
commits reachable by SHA. So the only fix that pays is preventing the next one.

## The list never ships

Putting client names in a public repo to block client names is self-defeating.
The token list lives OUTSIDE the repo at ~/.config/kipi/client-tokens, one token
per line, '#' comments allowed. It is read at hook time and never committed.

Absent list => WARN and pass, never block. A fresh clone by someone who is not
the founder has no clients to protect, and a gate that fails closed on a missing
local file blocks every contributor for nothing (scar: a-hook-that-fails-closed-
on-a-missing-script-blocks-the-fix-too).

## Bypass

Intentional (a public case study with recorded permission): put the bypass
token on its OWN LINE in the commit message, optionally with a reason:

    client-name-guard-skip: case study, permission recorded 2026-08-01

Merely naming the token in prose does not bypass anything -- the guard reads a
trailer, not a mention. Both stages read the bypass from the commit message; the
staged stage never reads it from the diff, or editing this file would disarm it.

Usage:
    client-name-guard.py --staged            # staged diff content (pre-commit)
    client-name-guard.py --message <file>    # commit message (commit-msg)
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

TOKENS_FILE = Path.home() / ".config" / "kipi" / "client-tokens"
SKIP = "client-name-guard-skip"

# A BYPASS IS AN ACT, NOT A WORD (ASK-747).
#
# This used to be `if SKIP in text`. That cannot tell an author INVOKING the
# bypass from prose that merely NAMES it, and the guard's own introducing commit
# proved it: that message documented the token, both hook stages printed
# `bypassed`, and the guard never scanned the commit that introduced it.
#
# So the token must now be a TRAILER -- alone on its line, or `token: reason`.
# That form cannot occur by accident in a sentence, and it is the shape git
# itself uses for authorial metadata.
#
# Comment lines are skipped. Git strips them from the final message, so a token
# inside the commented template would authorise a bypass that never appears in
# the recorded message -- a bypass with no audit trail is the thing this gate is.
_BYPASS_LINE = re.compile(
    rf"^\s*{re.escape(SKIP)}\s*(?::\s*\S.*)?\s*$", re.IGNORECASE)


def bypass_reason(text):
    """The trailer that authorises a bypass, or None. Prose mentioning the token
    is NOT a bypass -- that distinction is the whole point of this function."""
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        if _BYPASS_LINE.match(line):
            return line.strip()
    return None


def commit_message_text():
    """The message being written, for the --staged stage.

    THE BYPASS LIVES IN THE COMMIT MESSAGE, NEVER IN THE CONTENT (ASK-747).
    --staged used to test its own DIFF for the token, so any commit that touched
    a file CONTAINING the token disarmed the staged scan -- and the file that
    contains it is this one. The guard was structurally unable to see its own
    changes. Content is not consent: a diff can say anything, only the author's
    message can authorise.
    """
    path = os.environ.get("LEFTHOOK_COMMIT_MSG_FILE")
    if not path:
        try:
            git_dir = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True, text=True, check=True).stdout.strip()
        except Exception:  # noqa: BLE001 - no git dir means no message, not a crash
            return ""
        path = os.path.join(git_dir, "COMMIT_EDITMSG")
    try:
        return Path(path).read_text()
    except Exception:  # noqa: BLE001 - absent message means no bypass, fail closed
        return ""


def load_tokens():
    if not TOKENS_FILE.exists():
        return None
    out = []
    for line in TOKENS_FILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if len(line) > 3:
            out.append(line.lower())
    return out


def hits(text, tokens):
    low = text.lower()
    found = []
    for t in tokens:
        # word-ish boundary so a token never fires inside a longer ordinary word.
        # The founder's own vocabulary getting blocked is how a gate gets turned
        # off (scar: word-lists-catch-the-founder, 12 of 58 real posts on the
        # first naive version of a list like this).
        if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low):
            found.append(t)
    return sorted(set(found))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--message", type=Path)
    args = ap.parse_args()

    tokens = load_tokens()
    if tokens is None:
        print(f"client-name-guard: no token list at {TOKENS_FILE}, skipping "
              f"(create it, one client token per line, to arm this gate)")
        return 0
    if not tokens:
        return 0

    if args.message:
        text = args.message.read_text() if args.message.exists() else ""
        where = "commit message"
    else:
        text = subprocess.run(
            ["git", "diff", "--cached", "-U0"],
            capture_output=True, text=True).stdout
        # only ADDED lines; a diff that REMOVES a client name is the fix, not the defect
        text = "\n".join(l for l in text.splitlines()
                         if l.startswith("+") and not l.startswith("+++"))
        where = "staged content"

    # Read the bypass from the MESSAGE in both stages. See commit_message_text().
    reason = bypass_reason(text if args.message else commit_message_text())
    if reason:
        print(f"client-name-guard: bypassed via trailer {reason!r}")
        return 0

    found = hits(text, tokens)
    if not found:
        return 0

    print(f"BLOCK: client name in {where}: {', '.join(found)}")
    print("This repo is PUBLIC. Client names never go public without recorded")
    print("permission. The pattern is the post, the client is not.")
    print("  fix   : rename to a generic label (example_instance, a client engagement)")
    print(f"  intend: add '{SKIP}' to the commit message")
    return 1


if __name__ == "__main__":
    sys.exit(main())
