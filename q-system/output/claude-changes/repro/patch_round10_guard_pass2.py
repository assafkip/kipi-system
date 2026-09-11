#!/usr/bin/env python3
"""Round-10 pass 2 on claude-path-write-guard.py (ASK-291).

FOUND WHILE FIXING PASS 1, not reported by the reviewer, and wider than their
finding: `_stage()` skips every token starting with `-` because "a flag is not a
path". `--output=.claude/settings.json` is a flag AND a path. Measured live,
all rc=0 on the pass-1 guard:

    sort --output=.claude/settings.json /dev/null
    sort -o.claude/settings.json /dev/null
    tar  --file=.claude/settings.json -c /dev/null
    cp   --target-directory=.claude /etc/hosts

This is not about readers at all -- it is every writer in the system, and it
would have re-opened the exact hole pass 1 closed the moment anyone wrote the
long-flag form.

THE FIX, and why it needs no flag grammar. A value attaches to a flag in exactly
two ways in the POSIX/GNU convention: after an `=`, or directly after a
single-letter flag. So a flag token yields two mechanical candidates -- the part
after the first `=`, and the dash-stripped token minus its first character --
and each is judged by the SAME resolve()/hits_claude() rules as any other token.
No table of which flags take a path, which is the enumeration that would rot.

WHY NOT "block any flag token containing .claude": it would refuse
`--output=/tmp/unrelated-tree/.claude/settings.json`, and the round-5 pin says an
unrelated tree's .claude/ is not this guard's business. Extracting the candidate
and resolving it keeps that scoping intact -- the probe pins it as an allow.

COST, named: a `--flag=<free text>` whose text starts a clean `.claude/` path
component (`--desc=.claude/rules/x.md is wrong`) is a false block. Text that
merely MENTIONS the path mid-sentence is not, because `.claude` is then not a
path component (`--desc=see .claude/rules/x.md` resolves through `see .claude`,
which is not `.claude`). Both are pinned in the probe so the boundary is a
measurement, not a belief.
"""
import io
import sys

TARGET = "q-system/.q-system/scripts/claude-path-write-guard.py"
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

pairs.append(('''def _is_sanctioned(tokens):''', '''def _flag_values(token):
    """The path candidates hiding inside a flag token (review finding, round 10).

    A flag is not a path, which is why `_stage()` skips `-`-leading tokens. But a
    value ATTACHES to a flag two ways and only two ways, so this needs no table
    of which flags take a path:

        --output=.claude/x   the part after the first `=`
        -o.claude/x          the dash-stripped token minus its flag letter

    Both candidates go through the same resolve()/hits_claude() as any other
    token, so an unrelated tree's `.claude/` stays out of scope
    (`--output=/tmp/other/.claude/x` is still allowed; the round-5 pin holds).
    Ordinary flags yield harmless garbage: `-rn` gives `rn` and `n`, neither of
    which resolves anywhere near `.claude`.
    """
    body = token.lstrip("-")
    if "=" in token:
        return [token.split("=", 1)[1]]
    return [body, body[1:]] if body else []


def _is_sanctioned(tokens):'''))

pairs.append(('''    paths = [resolve(a, effective_cwd, assigns) for a in args
             if not a.startswith("-") and "\\n" not in a]''',
              '''    # A flag token is not skipped outright any more (review finding, round 10):
    # its ATTACHED value is a path when it is one. See _flag_values().
    candidates = []
    for a in args:
        if "\\n" in a:
            continue
        candidates.extend(_flag_values(a) if a.startswith("-") else [a])
    paths = [resolve(a, effective_cwd, assigns) for a in candidates]'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
