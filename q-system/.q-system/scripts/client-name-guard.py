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

Intentional (a public case study with recorded permission): put the bypass token
on its OWN LINE in the commit message, optionally with a reason:

    client-name-guard-skip: case study, permission recorded 2026-08-01

Naming the token in prose bypasses nothing. The guard reads a TRAILER, not a
mention, and the line must start at column 0 so an indented quote of this very
docstring is not an invocation.

## One stage, and why (ASK-747)

There is ONE scan and it runs at commit-msg. That is the only stage where both
facts hold at once:

  * the REAL message for THIS commit arrives as the argument -- no persistence,
    no cross-commit leak, and it is present for `git commit -m` exactly as for an
    editor commit;
  * `git diff --cached` still returns the staged content, because the commit
    object does not exist yet.

The previous shape ran a second scan at pre-commit. That stage cannot see the
message, so it could not honour a legitimate bypass, and the first fix attempt
(PR #194) tried to reach the message through $GIT_DIR/COMMIT_EDITMSG. Both
consequences were measured, not argued:

  * COMMIT_EDITMSG PERSISTS from the previous commit, so a legitimate bypass in
    commit N authorised the scan of commit N+1 -- a client name passed;
  * COMMIT_EDITMSG is ABSENT at pre-commit for `git commit -m`, so the documented
    bypass did not exist there at all, which routes an author to --no-verify and
    disarms every other hook in the repo.

Earlier feedback is not worth a gate that contradicts its own escape hatch.

Usage:
    client-name-guard.py --message <file>    # commit-msg: the one authoritative scan
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
# This was `if SKIP in text`, which cannot tell an author INVOKING the bypass
# from prose that merely NAMES it. The guard's own introducing commit proved it:
# that message documented the token, both stages printed `bypassed`, and the
# guard never scanned the commit that introduced it.
#
# ANCHORED AT COLUMN 0, deliberately. Allowing leading whitespace would let an
# indented quote of the usage docstring above count as an invocation -- the same
# mention-vs-use confusion one level down. Anchoring also means a git comment
# line cannot match, without needing a claim about when git strips them (it does
# NOT strip them for `git commit -m`, so a rule that relied on that would be
# wrong).
_BYPASS_LINE = re.compile(rf"^{re.escape(SKIP)}(?::[ \t]*\S.*?)?[ \t]*$")


def bypass_reason(message):
    """The trailer authorising a bypass, or None.

    Reads the MESSAGE ONLY. Content is never consent: a diff can contain any
    text at all, including this file, which is exactly how the pre-commit stage
    used to disarm itself (it tested the skip token against its own staged
    diff, so any commit touching a file containing the token was unscanned).
    """
    for line in (message or "").splitlines():
        if _BYPASS_LINE.match(line):
            return line.strip()
    return None


def staged_added_lines():
    """Added lines of the staged diff, still readable at commit-msg time.

    The commit object does not exist yet, so --cached IS this commit's content.
    Only ADDED lines: a diff that REMOVES a client name is the fix, not the
    defect. Fails CLOSED -- we only reach here with an armed token list, and a
    guard that cannot see what is being committed must not report all clear.
    """
    r = subprocess.run(["git", "diff", "--cached", "-U0"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git diff --cached failed")
    return "\n".join(l for l in r.stdout.splitlines()
                      if l.startswith("+") and not l.startswith("+++"))


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
    # --staged is GONE. It was a second scan at a stage that cannot see the
    # message, so it could neither honour a bypass nor be trusted to refuse one;
    # it tested the skip token against its own staged diff. One stage, one
    # verdict -- see the module docstring for the measurements behind that.
    ap.add_argument("--message", type=Path, required=True,
                    help="the commit message file (lefthook commit-msg passes {1})")
    args = ap.parse_args()

    tokens = load_tokens()
    if tokens is None:
        print(f"client-name-guard: no token list at {TOKENS_FILE}, skipping "
              f"(create it, one client token per line, to arm this gate)")
        return 0
    if not tokens:
        return 0

    message = args.message.read_text() if args.message.exists() else ""

    # The bypass is decided by the message and nothing else, before any scan.
    reason = bypass_reason(message)
    if reason:
        print(f"client-name-guard: bypassed via trailer {reason!r}")
        return 0

    # BOTH SURFACES IN ONE PASS. The message and the staged content are separate
    # leak paths, and each used to be checked by a stage the other could disarm.
    try:
        content = staged_added_lines()
    except RuntimeError as exc:
        print(f"BLOCK: cannot read the staged diff ({exc}).")
        print("Refusing rather than reporting all clear. The token list is armed,")
        print("so passing here would be an unverified claim that nothing leaked.")
        return 1

    found = [(where, hits(text, tokens))
             for where, text in (("commit message", message),
                                 ("staged content", content))]
    found = [(w, h) for w, h in found if h]
    if not found:
        return 0

    for where, names in found:
        print(f"BLOCK: client name in {where}: {', '.join(names)}")
    print("This repo is PUBLIC. Client names never go public without recorded")
    print("permission. The pattern is the post, the client is not.")
    print("  fix   : rename to a generic label (example_instance, a client engagement)")
    print(f"  intend: put '{SKIP}: <reason>' on its OWN LINE in the commit message")
    return 1


if __name__ == "__main__":
    sys.exit(main())
