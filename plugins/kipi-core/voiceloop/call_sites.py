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
  .sh  a logical line (backslash continuations joined) split at pipes and
       list operators outside quotes; a segment counts when the token in
       command position (past `NAME=value` and known wrappers such as env,
       nohup, timeout, sudo with its -u value, xargs with its -I value) is
       `claude`, a path ending in `/claude`, or a `$CLAUDE*` variable, and a
       later token in the segment is exactly -p or --print. A shell's -c
       string is scanned the same way, which is how a worker loop calls it
       through a wrapper function of its own. An `echo`/`printf` line skips
       only its first segment, so `echo "$p" | claude --print` counts and
       `echo 'a; claude -p x'` does not; `sudo -u claude run.sh -p` is a
       service account, not a call. Linear time. A heredoc body that quotes
       the pattern IS counted: this scanner does not parse heredocs, and it
       errs toward a row a reason explains.
Test directories are skipped: a test that spends a real call is a token
problem, not a metering one, and their fixtures quote the pattern in prose.
Review scratch trees (`.review-*`) hold copies of the scripts and are not
runtime.
"""
from __future__ import annotations

import ast
import re
import shlex
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
_BINARY_TOKEN = re.compile(r"""^["'`(]*((\S*/)?claude|\$\{?CLAUDE[A-Z_]*\}?)["'`)]*$""")
_FLAG_TOKEN = re.compile(r"""^["'`]*(-p|--print)["'`\\]*$""")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# Tokens that stand in front of a command without being one, and the flags of
# theirs that take a separate value (`sudo -u claude run.sh` is a service account,
# not an invocation: PR #413 round 5). A subset of fleet-health-daily.py's table;
# the skeleton test holds the two scanners against each other on every shared
# shell site so the subset cannot drift silently.
_WRAPPERS = {"env", "nohup", "nice", "time", "timeout", "caffeinate", "sudo", "exec",
             "stdbuf", "flock", "command", "xargs", "if", "then", "else", "elif",
             "while", "until", "do", "!", "{", "("}
_WRAPPER_VALUE_FLAGS = {
    "sudo": {"-u", "--user", "-g", "--group", "-C", "-D", "-p", "-r", "-t", "-R"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S"},
    "nice": {"-n"}, "timeout": {"-s", "-k"}, "caffeinate": {"-t", "-w"},
    "stdbuf": {"-i", "-o", "-e"}, "time": {"-f", "-o"}, "exec": {"-a"},
    "flock": {"-w", "--timeout", "-E"}, "xargs": {"-I", "-n", "-P", "-s", "-L", "-d", "-a"},
}
_WRAPPER_OPERANDS = {"flock": 1, "timeout": 1}   # a lock file, a duration
_SH_PRINTS = re.compile(r"^\s*(echo|printf)\b")
_MAX_DEPTH = 4


def _binary_like(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value.endswith("claude")
    # ast.Starred (ASK-2072): `[binary, *NO_MCP_ARGS, "-p", prompt]` puts a starred
    # constant between the binary and `-p`. Without it the engine's own wrapper stopped
    # counting as a call site, and any later script in that shape would spend unmetered.
    return isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call,
                             ast.IfExp, ast.BoolOp, ast.BinOp, ast.Starred))


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


def _segments(command: str) -> list[str]:
    """Split a command line at pipes and list operators, OUTSIDE quotes.

    `echo 'a; claude -p x'` is one segment, an echo (PR #413 round 5); the
    old split cut it at the `;` and counted the tail.
    """
    out, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1]); i += 1
        elif ch in ("'", '"'):
            quote = ch; buf.append(ch)
        elif command.startswith(("||", "&&", "|&"), i):
            out.append("".join(buf)); buf = []; i += 1
        elif ch in ("|", ";", "&"):
            # a bare `&` ends a command too: `cmd & claude -p x` (PR #418 round 1).
            # Redirections such as `2>&1` never reach here with a leading space,
            # and `&1` alone is an empty segment either way.
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [seg for seg in out if seg.strip()]


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _command_index(tokens: list[str]) -> int:
    """Index of the token in command position, past assignments and wrappers."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _ASSIGNMENT.match(tok):
            i += 1; continue
        base = tok.rsplit("/", 1)[-1]
        if tok.startswith("$") and not _BINARY_TOKEN.match(tok):
            # `$TO claude -p` (open-loops-heartbeat.sh) and `$NO_SUPABASE -u X
            # "$CLAUDE_BIN" -p` (a producer job): a wrapper held in a variable,
            # unknowable here; step past it and its flags like `env`.
            i += 1
            flags = _WRAPPER_VALUE_FLAGS["env"]
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in flags else 1
            continue
        if base not in _WRAPPERS:
            return i
        i += 1
        flags = _WRAPPER_VALUE_FLAGS.get(base, set())
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 2 if tokens[i] in flags else 1
        i += _WRAPPER_OPERANDS.get(base, 0)
    return -1


def _segment_calls(segment: str, depth: int = 0) -> bool:
    if depth > _MAX_DEPTH:
        return False
    tokens = _tokens(segment)
    ci = _command_index(tokens)
    if ci < 0:
        return False
    cmd = tokens[ci]
    if _BINARY_TOKEN.match(cmd) and any(_FLAG_TOKEN.match(t) for t in tokens[ci + 1:]):
        return True
    # No early False: a `case` arm such as `claude) run_bounded ... bash -c "..."`
    # puts a claude-shaped PATTERN in command position, and the call is in the
    # -c string behind it (pr-review-agent.sh:876).
    # A quoted command STRING as an argument (`case` arms that continue a
    # `bash -c` from the line above, pr-review-agent.sh:876) is scanned as a
    # line of its own. This is also where a logged mention such as
    # `log "claude -p x failed"` gets counted: the same erring-toward-a-row
    # the heredoc rule states, and no worse than the regex it replaced.
    for tok in tokens:
        if " " in tok and _CLAUDE_WORD.search(tok) and _line_calls(tok, depth + 1):
            return True
    # A shell with a -c string anywhere in the segment runs that string: this is
    # how a worker loop calls the model (`run_bounded "$T" bash -c "cd ... &&
    # claude -p \"$1\""`), through a wrapper function of its own.
    for j, tok in enumerate(tokens):
        if tok.rsplit("/", 1)[-1] in _SHELLS and j + 2 < len(tokens) + 1:
            k = j + 1
            while k < len(tokens) and tokens[k].startswith("-"):
                if "c" in tokens[k].lstrip("-") and k + 1 < len(tokens):
                    return _line_calls(tokens[k + 1], depth + 1)
                k += 1
    return False


def _substitutions(line: str) -> list[str]:
    """The inner text of every `$( ... )` and backtick substitution, balanced.

    `out="$(env -u X "$CLAUDE_BIN" -p "$@" 2>&1)"` is an assignment whose
    value RUNS the model; the assignment is skipped in command position, so
    the substitution has to be scanned as a command of its own.
    """
    out, i = [], 0
    while i < len(line):
        if line.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(line) and depth:
                if line.startswith("$(", j):
                    depth += 1; j += 2; continue
                if line[j] == "(":
                    depth += 1
                elif line[j] == ")":
                    depth -= 1
                j += 1
            out.append(line[i + 2:j - 1]); i = j
        elif line[i] == "`":
            j = line.find("`", i + 1)
            if j < 0:
                break
            out.append(line[i + 1:j]); i = j + 1
        else:
            i += 1
    return out


def _line_calls(line: str, depth: int = 0) -> bool:
    if depth > _MAX_DEPTH:
        return False
    segments = _segments(line)
    if _SH_PRINTS.match(line):
        segments = segments[1:]
    if any(_segment_calls(seg, depth) for seg in segments):
        return True
    return any(_line_calls(sub, depth + 1) for sub in _substitutions(line))


def _logical_lines(text: str):
    """Physical lines joined at a trailing backslash (PR #413 round 5)."""
    buf = []
    for line in text.splitlines():
        # A COMMENT ending in a backslash continues nothing: joining it would
        # swallow the next line into a comment (PR #418 round 1).
        if not buf and line.lstrip().startswith("#"):
            yield line; continue
        if line.rstrip().endswith("\\"):
            buf.append(line.rstrip()[:-1]); continue
        buf.append(line)
        yield " ".join(buf); buf = []
    if buf:
        yield " ".join(buf)


def sh_calls(text: str) -> bool:
    """Does this shell source run the model headless on a non-comment line?

    Read as commands: a logical line (backslash continuations joined) is split
    at pipes and list operators outside quotes; in each segment the token in
    COMMAND POSITION (past `NAME=value` and the wrappers above) must be the
    binary, followed by a -p/--print token; a shell's -c string is scanned the
    same way. An `echo`/`printf` line is a mention, not a call, unless a later
    segment runs the model (`echo "$p" | claude --print`, round 4).
    """
    for line in _logical_lines(text):
        if line.lstrip().startswith("#"):
            continue
        if _line_calls(line):
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
