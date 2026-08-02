#!/usr/bin/env python3
"""claude-path-write-guard.py -- Layer 1 of the .claude/ write protection (ASK-282).

PreToolUse hook on Bash. Blocks shell commands that would write inside a
`.claude/` tree.

SCOPE HONESTY, STATED UP FRONT:
This layer is COVERAGE, NOT A BOUNDARY. It reasons about a command string, and a
command string can always be obfuscated further than any parser follows. It is
here to stop the ordinary forms cheaply and early. The actual control is Layer 2
(claude-integrity-tripwire.py), which ignores commands entirely and checks
whether the CONTENT of the tree moved. If you are reading this while adding
"just one more pattern", stop: the answer to an evaded pattern is that Layer 2
already caught it, not that this list should grow.

WHY IT IS BUILT THIS WAY (scar, 2026-08-01, ASK-282):
Bash could write into `.claude/` while Write/Edit were refused there --
`touch .claude/_probe.txt` succeeded. The obvious fix, a denylist of dangerous
commands, is the exact defect class this repo hit six times in one file: matching
a phrase where the intent is a structure. A writer-denylist loses to touch, >,
>>, tee, cp, mv, install, rsync, sed -i, python -c open(w), `cd .claude && ...`,
a path in a variable, $HOME/.claude, a relative path from a subdirectory.

So the polarity is INVERTED. We do not enumerate writers. We enumerate READERS
and fail closed on everything else:

    a command that touches a .claude/ path is BLOCKED
    unless its program is on a small, stable read-only allowlist

Getting the reader list wrong yields a false BLOCK (loud, harmless, fixable).
Enumerating writers and getting it wrong yields a false ALLOW (silent, and the
gate was never real). A gate fails closed; a filter fails open.

Exit contract: 2 = block (stderr is fed back to Claude), 0 = allow.
"""

import json
import os
import re
import shlex
import sys

# Programs that cannot write to a path they are given. Small and stable by
# design. Anything not here is assumed write-capable.
READ_ONLY = {
    "cat", "ls", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag",
    "wc", "stat", "file", "diff", "cmp", "awk", "sed", "cut", "sort", "uniq",
    "md5", "md5sum", "shasum", "sha256sum", "basename", "dirname", "realpath",
    "readlink", "test", "echo", "printf", "pwd", "which", "type", "du", "df",
    "jq", "yq", "column", "less", "more", "nl", "od", "xxd", "tree", "find",
}

# `sed -i` and `awk`-into-a-file are the two readers that can write. `find` can
# too (-delete / -exec). Handled explicitly below rather than dropped from the
# allowlist, because their read forms are common in normal work.
READER_WRITE_FLAGS = {
    "sed": re.compile(r"(^|\s)-[a-zA-Z]*i"),
    "find": re.compile(r"(^|\s)(-delete|-exec|-execdir|-ok)"),
}

# git subcommands that only read. Any other git subcommand touching .claude/ is
# treated as write-capable (checkout, restore, apply, clean, mv, rm...).
# `config` and `worktree` were here in rounds 1-2 and both WRITE:
#   git config -f .claude/settings.json user.x y   -> rewrites the file
#   git worktree add .claude/wt                    -> creates a tree inside it
# A subcommand is not read-only independent of its arguments (finding, round 3).
# Dropped rather than special-cased: their read forms on a .claude/ path are
# rare, and a false block is the safe direction here.
GIT_READ_ONLY = {
    "status", "log", "diff", "show", "ls-files", "ls-tree", "cat-file",
    "blame", "grep", "rev-parse", "describe", "shortlog", "hash-object",
    "branch", "remote", "count-objects", "check-ignore",
}

# Piping into an interpreter re-enters the shell with content this parser never
# inspected. Treat as write-capable regardless of the visible program.
SHELL_SINKS = {"bash", "sh", "zsh", "dash", "ksh", "eval", "source", "xargs",
               "python", "python3", "perl", "ruby", "node", "tee", "install"}

# The sanctioned write path. It carries its own additive-only vocabulary,
# enforcement ratchet and auto-revert (PR #63); Layer 1 defers to those guards
# rather than duplicating them. Naming a script cannot smuggle a payload -- the
# command still has to actually BE that script for this to matter.
SANCTIONED = ("apply-claude-changes.sh", "apply_claude_changes.py",
              "claude-integrity-tripwire.py", "kipi-update.sh")

# Statement boundaries only. A single `|` is deliberately NOT a boundary: a
# pipeline is one unit of intent, and splitting it severs the path from the
# writer. `echo .claude/x | xargs touch` has the path in stage 1 and the writer
# in stage 2, and neither stage alone looks dangerous. Caught by its own test.
STATEMENT_SPLIT = re.compile(r"&&|\|\||;|\n")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def unquote(token):
    """Strip shell quoting before any path comparison.

    SCAR (review finding, round 3): the redirect target is captured by regex,
    not by shlex, so `echo pwned > ".claude/settings.json"` kept its quote
    characters. The first path component became `".claude` instead of `.claude`,
    the component test missed, and the write landed. That is comparing a
    REPRESENTATION instead of the thing -- the same root cause as matching a
    phrase where the intent is a structure.
    """
    t = token.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1].strip()
    return t.replace('"', "").replace("'", "")


def expand(token, cwd, assigns):
    """~, $HOME, ${HOME} and locally-assigned vars. A path held in a variable is
    still a path; a guard that only reads literals misses `D=.claude; touch $D/x`."""
    t = token
    for name, val in assigns.items():
        t = t.replace("${%s}" % name, val).replace("$" + name, val)
    home = os.path.expanduser("~")
    t = t.replace("${HOME}", home).replace("$HOME", home)
    if t.startswith("~"):
        t = os.path.expanduser(t)
    if not os.path.isabs(t):
        t = os.path.join(cwd, t)
    return os.path.normpath(t)


def hits_claude(path):
    """True if the resolved path is inside (or is) a `.claude` directory.
    Component-wise, so `my.claude-notes` and `claude/` do not false-positive."""
    parts = os.path.normpath(path).split(os.sep)
    return ".claude" in parts


def analyse(command, cwd):
    """Return a blocking reason, or None."""
    assigns = {}
    effective_cwd = cwd

    for raw_stmt in STATEMENT_SPLIT.split(command):
        stmt = raw_stmt.strip()
        if not stmt:
            continue

        stages = [s.strip() for s in stmt.split("|") if s.strip()]

        # Pipeline judged whole: any stage that re-enters an interpreter turns
        # a .claude/ path anywhere in the statement into a write.
        # Same program-position rule as _is_sanctioned: a mention of a
        # sanctioned script must never disarm a pipeline (review finding, r2).
        if ".claude" in stmt and not any(_is_sanctioned(s.split()) for s in stages):
            for stage in stages:
                head = stage.split()
                if head and os.path.basename(head[0]) in SHELL_SINKS:
                    return "pipeline feeds a .claude/ path into %r" % os.path.basename(head[0])

        for seg in stages:
            reason = _stage(seg, assigns, [effective_cwd])
            if isinstance(reason, str):
                return reason
            effective_cwd = reason[0]

    return None


def _is_sanctioned(tokens):
    """True only if the command actually EXECUTES a sanctioned entrypoint.

    Round 1 tested `any(s in seg for s in SANCTIONED)` -- a substring match on
    the raw segment. That meant any command merely CONTAINING the text
    "kipi-update.sh", including inside a quoted string or a trailing comment,
    disabled Layer 1 for that statement:

        touch .claude/evil.txt  # kipi-update.sh

    Which is the phrase-versus-structure defect this guard's own header warns
    about, committed inside the guard. Caught in review, round 2. The check now
    looks at the PROGRAM POSITION only: argv[0], plus argv[1] when argv[0] is an
    interpreter, since `bash apply-claude-changes.sh ...` is the normal form.
    """
    if not tokens:
        return False
    cands = [os.path.basename(tokens[0])]
    if cands[0] in ("bash", "sh", "zsh", "python", "python3") and len(tokens) > 1:
        for t in tokens[1:]:
            if not t.startswith("-"):
                cands.append(os.path.basename(t))
                break
    return any(c in SANCTIONED for c in cands)


def _stage(seg, assigns, cwd_box):
    """One pipeline stage. Returns a blocking reason (str), or [new_cwd] to
    carry a `cd` forward to the stages and statements after it."""
    effective_cwd = cwd_box[0]
    ok = [effective_cwd]
    try:
        tokens = shlex.split(seg, comments=True)
    except ValueError:
        tokens = seg.split()
    if not tokens:
        return ok

    # Redirection into a .claude path is a write no matter the program.
    # No leading-whitespace requirement: `printf pwned>.claude/settings.json`
    # is valid shell and walked straight past the first version of this regex
    # (review finding, round 2). Excluding & and < from the target keeps `2>&1`
    # and here-strings from matching as paths.
    for redir in re.finditer(r">>?\s*([^\s;&|<>]+)", seg):
        if hits_claude(expand(unquote(redir.group(1)), effective_cwd, assigns)):
            return "redirects output into .claude/: %s" % redir.group(1)

    # Leading VAR=value assignments, so a path in a variable still resolves.
    while tokens:
        m = ASSIGN.match(tokens[0])
        if not m:
            break
        assigns[m.group(1)] = m.group(2)
        tokens.pop(0)
    if not tokens:
        return ok

    prog = os.path.basename(tokens[0])
    args = tokens[1:]

    # `cd .claude && touch x` -- the write target is relative to the NEW cwd.
    if prog == "cd" and args:
        return [expand(args[0], effective_cwd, assigns)]

    if _is_sanctioned(tokens):
        return ok

    paths = [expand(a, effective_cwd, assigns) for a in args
             if not a.startswith("-")]
    touches = [p for p in paths if hits_claude(p)]

    # A bare write inside an already-.claude cwd has no .claude token at all.
    if not touches and hits_claude(effective_cwd) and prog not in READ_ONLY:
        return "runs %r with cwd inside .claude/" % prog

    # An interpreter carries its target INSIDE a code string, where
    # component-wise path resolution cannot see it:
    #   python3 -c "open('.claude/settings.json','w')"
    # Found while writing the tests for this guard, not from the brief.
    if prog in SHELL_SINKS and ".claude" in seg:
        return "%r carries a .claude/ path inside its code/argument string" % prog

    if not touches:
        return ok

    if prog in SHELL_SINKS:
        return "%r re-enters the shell with a .claude/ path: %s" % (prog, touches[0])

    if prog == "git":
        sub = args[0] if args and not args[0].startswith("-") else ""
        if sub in GIT_READ_ONLY:
            return ok
        return "git %s targets .claude/: %s" % (sub or "?", touches[0])

    if prog in READ_ONLY:
        pat = READER_WRITE_FLAGS.get(prog)
        if pat and pat.search(seg):
            return "%r used in its writing form on .claude/: %s" % (prog, touches[0])
        return ok

    return "%r would write inside .claude/: %s" % (prog, touches[0])


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never break the session on a malformed hook payload
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    reason = analyse(command, cwd)
    if reason:
        sys.stderr.write(
            "BLOCKED by claude-path-write-guard (ASK-282): %s\n"
            ".claude/ wires every hook, rule and agent; an agent that writes there can "
            "disable its own gates. Use the sanctioned path: a proposal applied by "
            "apply-claude-changes.sh (additive-only, ratcheted, auto-reverting).\n" % reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
