"""Find every file that shells the headless model itself instead of using the wrapper.

why (ASK-2008, Step 2 of the ticket-flood plan). `prompt_render.run_model` is the
metered chokepoint: one ledger row per call. A script that runs `claude -p` on
its own is invisible to that ledger, and on 2026-09-12, when the fleet hit the
weekly limit, nothing could say which bot had spent it. This module is the
detector an inventory test holds a tree against; the inventory itself (which
sites are tolerated, and why) belongs to the deployment, never to the engine.

WHAT IT SEES, and what it does not, stated so its silence reads right:
  .py  a file that names `claude` somewhere AND holds an argv list or tuple
       literal with the string "-p" either first (`DEFAULT_ARGS = ["-p", ...]`,
       the binary prepended elsewhere) or right after an expression standing
       for the binary: a string ending in `claude`, a variable, an attribute,
       a call, or a conditional such as `CLAUDE_BIN if ... else "claude"`.
       `--print`, the long spelling, counts the same as `-p`.
       The `claude` mention is what keeps `[ssh_bin, "-p", port]` out (PR #413
       round 1 minor 2); a file that shells both ssh and the model is counted,
       which is the right side to err on. A caller that assembles `claude -p`
       inside a shell string is NOT seen. A file this Python cannot parse
       falls back to the text shape of the argv element.
  .sh  a non-comment line with a command segment (split at pipes and list
       operators) whose binary token is `claude`, a path ending in `/claude`,
       or a `$CLAUDE*` variable, followed later in that segment by a token
       that is exactly -p or --print, options in between allowed
       (`claude --model X -p`). Read as tokens, linear time. A `bash -c`
       string is seen through its quotes, which is how a worker loop calls
       it. An `echo`/`printf` line skips only its first segment, so
       `echo "$p" | claude --print` counts and `echo "claude -p x"` does
       not. A heredoc body that quotes the pattern IS counted: this scanner
       does not parse heredocs, and it errs toward a row a reason explains.
Test directories are skipped: a test that spends a real call is a token
problem, not a metering one, and their fixtures quote the pattern in prose.
Review scratch trees (`.review-*`) hold copies of the scripts and are not
runtime.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

_TEST_DIR = re.compile(r"(^|/)(tests?|test)/|(^|/)test[_-]")
_SCRATCH = re.compile(r"^\.review-")
_PY_TEXT = re.compile(r"""(,|\[|\()\s*["'](-p|--print)["']""")
_CLAUDE_WORD = re.compile(r"\bclaude\b", re.I)
# Shell is read as TOKENS, not as one regex over the line (PR #413 round 4: the
# nested-optional pattern backtracked exponentially, 16.8 s on a 24-flag line,
# inside a pre-push gate with no timeout). A command segment ends at a pipe or
# a list operator; inside a segment the binary token is `claude`, a path ending
# in `/claude`, or a `$CLAUDE*` variable, and the call flag is any later token
# that is exactly -p or --print. Quotes around the tokens are stripped, which is
# how a `bash -c "... claude -p \"$1\""` string is seen.
_SEGMENT_SPLIT = re.compile(r"\|\|?|&&|;|\|&")
_BINARY_TOKEN = re.compile(r"""^["'`(]*((\S*/)?claude|\$\{?CLAUDE[A-Z_]*\}?)["'`)]*$""")
_FLAG_TOKEN = re.compile(r"""^["'`]*(-p|--print)["'`\\]*$""")
_SH_PRINTS = re.compile(r"^\s*(echo|printf)\b")


def _binary_like(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value.endswith("claude")
    return isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call,
                             ast.IfExp, ast.BoolOp, ast.BinOp))


def _is_dash_p(node) -> bool:
    return isinstance(node, ast.Constant) and node.value in ("-p", "--print")


def py_calls(text: str) -> bool:
    """Does this Python source build an argv that runs the model headless?"""
    if not _CLAUDE_WORD.search(text):
        return False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return bool(_PY_TEXT.search(text))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        elts = node.elts
        # -p first, the binary prepended elsewhere: counts when something after
        # it is not itself a flag (a prompt, a value). A flags-only tuple such as
        # this module's own ("-p", "--print") is a vocabulary, not an argv.
        if elts and _is_dash_p(elts[0]) and any(
                not (isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.startswith("-"))
                for e in elts[1:]):
            return True
        for i in range(1, len(elts)):
            if _is_dash_p(elts[i]) and _binary_like(elts[i - 1]):
                return True
    return False


def _segment_calls(segment: str) -> bool:
    tokens = segment.split()
    for i, tok in enumerate(tokens):
        if _BINARY_TOKEN.match(tok):
            return any(_FLAG_TOKEN.match(t) for t in tokens[i + 1:])
    return False


def sh_calls(text: str) -> bool:
    """Does this shell source run the model headless on a non-comment line?

    An `echo`/`printf` line is a mention, not a call, UNLESS something after
    a pipe runs the model: `echo "$prompt" | claude --model sonnet --print` is
    a real caller (PR #413 round 4, major), and the first segment is the only
    one the print guard may skip.
    """
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        segments = _SEGMENT_SPLIT.split(line)
        if _SH_PRINTS.match(line):
            segments = segments[1:]
        if any(_segment_calls(seg) for seg in segments):
            return True
    return False


def tracked(root: Path) -> list[str]:
    """Tracked .py and .sh paths, relative to `root`. Untracked files are not a call site yet."""
    r = subprocess.run(["git", "-C", str(root), "ls-files", "--", "*.py", "*.sh"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # A registered instance with a broken .git must say so, not raise a bare
        # CalledProcessError with its stderr thrown away (PR #413 round 2).
        raise RuntimeError("git ls-files failed in %s: %s" % (root, (r.stderr or "").strip()[:200]))
    return [p for p in r.stdout.splitlines() if p]


def call_sites(root: Path) -> set[str]:
    """Every tracked .py/.sh outside test and scratch directories that shells the model."""
    found = set()
    for rel in tracked(root):
        if _TEST_DIR.search(rel) or _SCRATCH.search(rel):
            continue
        try:
            text = (root / rel).read_text(errors="replace")
        except OSError:
            continue
        hit = py_calls(text) if rel.endswith(".py") else sh_calls(text)
        if hit:
            found.add(rel)
    return found


def check(root: Path, allowed: dict, wrappers=()) -> tuple[set, set]:
    """(sites with no row, rows whose file is here but no longer calls). Both must be empty.

    A row for a file this tree does not carry is neither: an older copy of a
    shared tree simply has not received it. A row for a file that IS here and
    no longer shells the model is stale and has to leave the list, which is
    how the list only shrinks.
    """
    sites = call_sites(root) - set(wrappers)
    rows = set(allowed)
    stale = {r for r in rows - sites if (root / r).exists()}
    return sites - rows, stale
