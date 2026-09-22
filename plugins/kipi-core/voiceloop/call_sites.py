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
       The `claude` mention is what keeps `[ssh_bin, "-p", port]` out (PR #413
       round 1 minor 2); a file that shells both ssh and the model is counted,
       which is the right side to err on. A caller that assembles `claude -p`
       inside a shell string is NOT seen. A file this Python cannot parse
       falls back to the text shape of the argv element.
  .sh  a non-comment line, not an `echo`/`printf`, running `claude -p` /
       `claude --print` with any options between the two (`claude --model X
       -p`), or a `$CLAUDE*` variable with `-p`, anywhere on the line (inside
       a `bash -c` string included, which is how a worker loop calls it). A
       heredoc body that quotes the pattern IS counted: this scanner does not
       parse heredocs, and it errs toward a row that a reason then explains.
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
_PY_TEXT = re.compile(r"""(,|\[|\()\s*["']-p["']""")
_CLAUDE_WORD = re.compile(r"\bclaude\b", re.I)
# `claude`, then any run of options (with or without a value), then -p/--print.
_SH_CALL = re.compile(
    r"""(^|[\s"'(;&|`])(claude|\$\{?CLAUDE[A-Z_]*\}?)"""
    r"""(\s+--?[\w-]+(=\S+)?(\s+[^-\s]\S*)?)*\s+(-p|--print)(\s|"|'|\\|$)""")
_SH_PRINTS = re.compile(r"^\s*(echo|printf)\b")


def _binary_like(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value.endswith("claude")
    return isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call,
                             ast.IfExp, ast.BoolOp, ast.BinOp))


def _is_dash_p(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "-p"


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
        if elts and _is_dash_p(elts[0]):
            return True
        for i in range(1, len(elts)):
            if _is_dash_p(elts[i]) and _binary_like(elts[i - 1]):
                return True
    return False


def sh_calls(text: str) -> bool:
    """Does this shell source run the model headless on a non-comment line?"""
    for line in text.splitlines():
        if line.lstrip().startswith("#") or _SH_PRINTS.match(line):
            continue
        if _SH_CALL.search(line):
            return True
    return False


def tracked(root: Path) -> list[str]:
    """Tracked .py and .sh paths, relative to `root`. Untracked files are not a call site yet."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "--", "*.py", "*.sh"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


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
