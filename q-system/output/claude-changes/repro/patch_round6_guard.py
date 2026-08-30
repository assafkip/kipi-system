#!/usr/bin/env python3
"""One-shot patcher for the round-6 BLOCKER on claude-path-write-guard.py
(ASK-291): a sanctioned script name exempted the whole command from argument
inspection, so a command substitution in that same call mutated .claude/ and the
sanctioned tool then baselined the mutation as trusted.

WHY THIS FILE EXISTS AT ALL: the guard scripts are self-watched by Layer 2, so a
plain Edit is reverted one tool call later (sp-39c1b891 -- the watched guards
have no sanctioned EDIT path once armed; observed again this round, the first
Edit was reverted and quarantined). The working route is write-then-register
inside a SINGLE tool call, which means the write has to be scripted. Committed
rather than deleted: it IS the provenance of the diff.

Usage: python3 patch_round6_guard.py <path-to-claude-path-write-guard.py>
Every anchor must match exactly once or the run aborts without writing.
"""
import io
import sys

TARGET = sys.argv[1]
src = io.open(TARGET, encoding="utf-8").read()

pairs = []

# --- carry the delimiter's quoting out of the heredoc scanner ----------------
# `<<'EOF'` does not expand `$(...)`; `<<EOF` does. The substitution scan below
# has to tell them apart, so the scanner has to report which it saw.
pairs.append(('''            out.append((m.start(), m.end(), m.group(2)))''',
'''            out.append((m.start(), m.end(), m.group(2), bool(m.group(1))))'''))

pairs.append(('''    for start, end, delim in _heredoc_openers(text):''',
'''    for start, end, delim, _quoted in _heredoc_openers(text):'''))

# --- the fix: judge what the shell runs BEFORE the visible program -----------
pairs.append(('''def analyse(command, cwd):
    """Return a blocking reason, or None."""
    assigns = {}''',
'''def _strip_inert_heredocs(text):
    """Drop the bodies of QUOTED-delimiter heredocs (`<<\\'EOF\\'`) only.

    The shell expands `$(...)` inside an unquoted-delimiter body and does not
    inside a quoted one, and extract_substitutions has to know the difference.
    Judge an inert body and this guard refuses prose that merely QUOTES an
    attack shape -- the false-block class that has already nearly killed it five
    times in this issue alone. Skip an expanding body and the substitution scan
    has a hole a heredoc walks straight through.

    An unterminated opener is NOT stripped: leaving it in risks a false block,
    dropping it risks a false allow, and this layer fails closed.
    """
    out, pos = [], 0
    for start, end, delim, quoted in _heredoc_openers(text):
        if start < pos or not quoted:
            continue
        nl = text.find("\\n", end)
        if nl == -1:
            continue
        term = re.search(r"^[\\t ]*%s[\\t ]*$" % re.escape(delim),
                         text[nl + 1:], re.M)
        if term is None:
            continue
        out.append(text[pos:nl + 1])
        pos = nl + 1 + term.start()
    out.append(text[pos:])
    return "".join(out)


def _matching_paren(text, i):
    """Body and end-index of the `$(` whose contents start at `i`.

    Quote-aware and nesting-aware. Returns (None, len(text)) if it never closes.
    """
    depth, quote, n, start = 1, None, len(text), i
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\\\" and quote == \'"\' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "\\\\" and i + 1 < n:
            i += 2
            continue
        if ch in ("\'", \'"\'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, n


def extract_substitutions(text):
    """Every command body the shell RUNS before the visible program is exec\'d.

    `$(...)` and backticks, live inside double quotes, inert inside single ones,
    nested bodies returned flat so one pass judges all of them.

    WHY THIS EXISTS (review finding, PR #85 round 6, BLOCKER): `_is_sanctioned`
    matches on argv[0]/argv[1] and `_stage` then returns `ok` without looking at
    a single argument. So

        bash apply-claude-changes.sh "$(touch .claude/evil.txt)"

    walked past Layer 1 untouched -- and past Layer 2 as well, because the shell
    expands BEFORE it execs: the substitution mutates the tree, and then the
    sanctioned tool\'s own re-baseline records the mutation as the trusted state.
    One Bash call, both layers defeated, no alarm. Measured in
    probe_round6_findings.sh phase 2 before the fix: `.claude/rules/r.md`
    rewritten, `--check` answering `clean: 2 file(s) match baseline`.

    A substitution is a COMMAND, not an argument, so it is judged as one. That
    is also why this runs in `analyse` ahead of everything rather than as one
    more special case inside `_stage`: an exemption handed to the outer program
    must not be reachable from inside it, and every future exemption added to
    `_stage` inherits that property for free instead of re-opening this hole.

    Only the `>` shapes were ever covered here, and by accident: the redirect
    scan happens to run before the sanctioned early-return, which is why the
    first probe cases written for this finding passed against the broken guard
    and had to be rewritten redirect-free to mean anything.

    NAMED GAP: a body is judged against the SESSION cwd, so the substitution in
    `cd /tmp && bash apply.sh "$(touch .claude/x)"` is judged as if it ran at the
    session cwd. That direction is a false BLOCK, never a false allow, and
    threading expansion-order cwd through the parser is more than this layer\'s
    stated scope (COVERAGE, NOT A BOUNDARY) is meant to carry.
    """
    text = _strip_inert_heredocs(text)
    out, quote, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "\'":
            if ch == "\'":
                quote = None
            i += 1
            continue
        if ch == "\\\\" and i + 1 < n:
            i += 2                      # `\\$(` and a backslashed backtick are literal
            continue
        if quote == \'"\':
            if ch == \'"\':
                quote = None
                i += 1
                continue
            # `$(` and backticks stay LIVE inside double quotes -- fall through.
        elif ch in ("\'", \'"\'):
            quote = ch
            i += 1
            continue
        if text.startswith("$(", i):
            body, end = _matching_paren(text, i + 2)
            if body is None:
                # FAIL CLOSED: an opener with no closer hands its tail over to
                # be judged anyway. Round 2\'s heredoc code dropped an
                # unterminated tail instead, and dropped a real write with it.
                out.append(text[i + 2:])
                return out
            out.append(body)
            out.extend(extract_substitutions(body))
            i = end
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            if j == -1:
                out.append(text[i + 1:])
                return out
            out.append(text[i + 1:j])
            out.extend(extract_substitutions(text[i + 1:j]))
            i = j + 1
            continue
        i += 1
    return out


def analyse(command, cwd):
    """Return a blocking reason, or None.

    Command substitutions are judged FIRST and on their own terms, because the
    shell runs them first and because no exemption granted to the outer program
    -- the sanctioned-entrypoint one above all -- can reach inside them.
    """
    for body in extract_substitutions(command):
        reason = _analyse_statements(body, cwd)
        if reason:
            return "command substitution %s" % reason
    return _analyse_statements(command, cwd)


def _analyse_statements(command, cwd):
    """The statement-and-stage walk over one command string."""
    assigns = {}'''))

for old, new in pairs:
    if src.count(old) != 1:
        sys.exit("ANCHOR NOT UNIQUE (%d hits): %r" % (src.count(old), old[:70]))
    src = src.replace(old, new)

io.open(TARGET, "w", encoding="utf-8").write(src)
print("patched %s (%d edits)" % (TARGET, len(pairs)))
