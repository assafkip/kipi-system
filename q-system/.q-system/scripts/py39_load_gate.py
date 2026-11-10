#!/usr/bin/env python3
"""Refuse a Python file that launchd runs and that Python 3.9 cannot load (ASK-4230).

THE SCAR. PR #668 merged `def refusal(self) -> str | None` into linear-sync.py.
validate passed, because CI ran Python 3.12 and a PEP 604 union is legal syntax
there. launchd runs every job through `bash -lc`, where python3 is
/usr/bin/python3 3.9.6, and `str | None` is EVALUATED at def time on 3.9, so the
import raised TypeError. com.kipi.capability-expiry's first run exited 1 on it,
and every launchd job that loads linear-sync.py would have crashed the same way.
PR #703 quoted the annotation; nothing stopped the class from merging again.
disk_janitor.py's docstring already said "no 3.10+ syntax", in prose only.

WHY LOADING AND NOT COMPILING. `python3.9 -m py_compile` passes on
`-> str | None`: the failure is not a SyntaxError, it is a TypeError raised when
the annotation expression is evaluated while the `def` executes. Only running the
module's top level finds it. So this gate execs each file's top level under the
target interpreter with `__name__` set to a sentinel, which runs every `def` and
class body (and therefore every annotation) without running `main()`.

HONEST BOUNDARY. This loads top level only. A 3.10+ construct that lives INSIDE a
function body (a `match` statement is a SyntaxError and is caught; an `X | Y`
isinstance call inside a function is not) is invisible here until that function
runs. It also cannot see a job whose command this collector does not resolve: the
plists are the authority, and a job added by some other route is not in the list.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys

# A path token in a plist or a shell script. Deliberately narrow: no spaces, no
# shell metacharacters, so `&&`-joined commands split into separate tokens.
PATH_TOKEN = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|sh)")

# install-plist.sh materializes these. A template path is relative to the repo
# once the placeholder is gone.
PLACEHOLDERS = ("__KIPI_REPO__/", "__ROOT__/", "__HOME__/")

# Executed with __name__ set to this, so `if __name__ == "__main__"` stays shut.
LOAD_SENTINEL = "__kipi_py39_load_probe__"

# The probe. Reads the file, compiles it, executes its top level. argv is set to
# [path] so a script that inspects sys.argv at import time sees a bare call.
#
# The sentinel module is REGISTERED IN sys.modules, and that line is load-bearing.
# Measured 2026-11-09 without it: three real scripts (browser_session.py,
# linear-route.py, prd-os config.py) failed with
# `AttributeError: 'NoneType' object has no attribute '__dict__'` from inside
# dataclasses._is_type, because @dataclass on 3.9 resolves a field's type through
# `sys.modules.get(cls.__module__)`. An unregistered module name returns None.
# That is a defect in the probe, not in the script, and a gate that is red on
# three healthy files is a gate someone switches off.
PROBE = r"""
import sys, traceback, types, os
path = sys.argv[1]
sys.argv = [path]
with open(path, "r", encoding="utf-8") as fh:
    src = fh.read()
mod = types.ModuleType(%r)
mod.__file__ = path
sys.modules[%r] = mod
sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
try:
    exec(compile(src, path, "exec"), mod.__dict__)
except SystemExit:
    pass
except BaseException:
    sys.stderr.write(traceback.format_exc())
    sys.exit(7)
""" % (LOAD_SENTINEL, LOAD_SENTINEL)

# launchd runs no pytest file. They were collected because a job's shell wrapper
# names one, and they fail on `import pytest`, which /usr/bin/python3 does not
# have. Excluded by path shape, not by an allowlist that would need maintenance.
TEST_SHAPE = re.compile(r"(^|/)(tests?)/|(^|/)test[_-]|[_-]test\.py$|conftest\.py$")


def repo_files(root):
    """Every tracked path, or every path on disk when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
        files = [ln for ln in out.splitlines() if ln]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return found


def normalize(token, root, tracked):
    """A plist/shell token to a repo-relative path, or None when it is not ours."""
    for ph in PLACEHOLDERS:
        if token.startswith(ph):
            token = token[len(ph):]
    while token.startswith("./"):
        token = token[2:]
    token = token.lstrip("/")
    if not token or ".." in token.split("/"):
        return None
    if token in tracked:
        return token
    # A plist may name a path relative to the scripts directory it sits in.
    base = os.path.basename(token)
    hits = [p for p in tracked if os.path.basename(p) == base and p.endswith(token)]
    return hits[0] if len(hits) == 1 else None


def in_package(rel, tracked):
    """True when rel is a member of a Python package.

    A package member is never loaded standalone: `from . import x` raises
    ImportError when the file is exec'd as a top level, which is a probe
    artifact and not a 3.9 defect (measured on plugins/kipi-core/voiceloop/).
    Nothing is lost by skipping it: whichever entrypoint imports the package
    executes that module's top level, under the same interpreter, and IS in
    this list.
    """
    init = os.path.join(os.path.dirname(rel), "__init__.py").replace("\\", "/")
    return init in tracked


def string_constants(tree):
    """Short single-line string literals. Docstrings and prose blocks are out:
    a comment that happens to name a .py file is not an exec."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) <= 200 and "\n" not in node.value:
                yield node.value


def py_references(path, root, tracked):
    """What this Python file imports or execs, as repo-relative paths."""
    out = set()
    abspath = os.path.join(root, path)
    try:
        with open(abspath, "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return out
    try:
        tree = ast.parse(src, path)
    except SyntaxError:
        # A file 3.14 cannot parse is a different defect; the load probe reports it.
        return out

    here = os.path.dirname(path)
    search = [here, "q-system/.q-system", "q-system/.q-system/scripts"]

    def add_module(name):
        head = name.split(".")[0]
        for d in search:
            cand = os.path.join(d, head + ".py").replace("\\", "/")
            if cand in tracked:
                out.add(cand)
                return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                add_module(node.module)

    for text in string_constants(tree):
        for m in PATH_TOKEN.finditer(text):
            rel = normalize(m.group(0), root, tracked)
            if rel and rel.endswith(".py"):
                out.add(rel)
    return out


def shell_references(path, root, tracked, text=None):
    """What this shell script (or one `case` arm of the kipi CLI) names."""
    out = set()
    if text is None:
        try:
            with open(os.path.join(root, path), "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return out
    for m in PATH_TOKEN.finditer(text):
        rel = normalize(m.group(0), root, tracked)
        if rel:
            out.add(rel)
    return out


def kipi_subcommand_body(root, subcommand):
    """The `<subcommand>)` case arm of the kipi CLI, as text.

    Scoped on purpose. Seeding the whole CLI collected 187 files, most of them
    reachable only from verbs no launchd job runs, and a gate that is red on a
    file no job loads is a gate someone switches off. A plist names one verb;
    this returns only what that verb runs.
    """
    try:
        with open(os.path.join(root, "kipi"), "r", encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return ""
    start = re.search(r"^\s*%s\)\s*$" % re.escape(subcommand), src, re.M)
    if not start:
        return ""
    rest = src[start.end():]
    end = rest.find("\n    ;;")
    return rest if end < 0 else rest[:end]


KIPI_VERB = re.compile(r"(?:\./)?kipi\s+([a-z][a-z-]*)")


def plist_seeds(root, tracked):
    """Every .py and .sh a tracked com.kipi.*.plist names, plus the kipi verbs
    those plists invoke, each expanded to its own case arm only."""
    plists = sorted(
        p for p in tracked
        if os.path.basename(p).startswith("com.kipi.") and p.endswith(".plist")
    )
    seeds = set()
    verbs = set()
    for plist in plists:
        try:
            with open(os.path.join(root, plist), "r", encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for m in PATH_TOKEN.finditer(src):
            rel = normalize(m.group(0), root, tracked)
            if rel:
                seeds.add(rel)
        # `cd __KIPI_REPO__ && ./kipi dor --limit 8` runs the CLI, which runs Python.
        for m in KIPI_VERB.finditer(src):
            verbs.add(m.group(1))

    for verb in sorted(verbs):
        body = kipi_subcommand_body(root, verb)
        if body:
            seeds |= shell_references("kipi", root, tracked, text=body)
    return plists, seeds


def collect(root):
    """The transitive set of Python files a launchd job loads.

    Returns (files, plists, seeds). `files` is sorted and repo-relative.
    """
    tracked = set(repo_files(root))
    plists, seeds = plist_seeds(root, tracked)

    seen = set()
    work = sorted(seeds)
    pyfiles = set()
    while work:
        item = work.pop()
        if item in seen:
            continue
        seen.add(item)
        if item.endswith(".py"):
            if not TEST_SHAPE.search(item) and not in_package(item, tracked):
                pyfiles.add(item)
            nxt = py_references(item, root, tracked)
        else:
            nxt = shell_references(item, root, tracked)
        for ref in nxt:
            if ref not in seen:
                work.append(ref)
    return sorted(pyfiles), plists, sorted(seeds)


def load_one(python, root, rel, timeout):
    """Run rel's top level under `python`. Returns (ok, detail)."""
    try:
        proc = subprocess.run(
            [python, "-c", PROBE, rel],
            cwd=root, capture_output=True, text=True, timeout=timeout,
        )
    except OSError as exc:
        return False, "could not run %s: %s" % (python, exc)
    except subprocess.TimeoutExpired:
        return False, "timed out after %ss loading its top level" % timeout
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "exit %d" % proc.returncode).strip()


def blame_line(detail, rel):
    """The file:line the traceback blames, so the failure names a line."""
    hits = re.findall(r'File "([^"]*%s)", line (\d+)' % re.escape(rel), detail)
    if hits:
        return "%s:%s" % (rel, hits[-1][1])
    return rel


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--python", default="python3.9",
                    help="the interpreter launchd would use (3.9)")
    ap.add_argument("--list", action="store_true",
                    help="print the collected file list and exit 0")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.repo_root)
    files, plists, seeds = collect(root)

    if args.list:
        for f in files:
            print(f)
        return 0

    # NEGATIVE SELF-TEST, and the reason this gate cannot read green while blind.
    # An empty list means the collector resolved nothing: a renamed placeholder, a
    # plist moved out of the tree, a git call that returned no files. A gate that
    # checks zero files passes every PR, which is the exact failure mode PR #668
    # already shipped once.
    if not files:
        sys.stderr.write(
            "py39-load-gate: collected 0 files from %d plist(s) and %d seed(s).\n"
            "An empty list cannot pass: the collector is broken, not the tree.\n"
            % (len(plists), len(seeds))
        )
        return 2

    failures = []
    for rel in files:
        ok, detail = load_one(args.python, root, rel, args.timeout)
        if not ok:
            failures.append({"file": rel, "where": blame_line(detail, rel),
                             "detail": detail})

    if args.json:
        print(json.dumps({
            "python": args.python, "plists": len(plists),
            "checked": files, "failures": failures,
        }, indent=1))
    else:
        print("py39-load-gate: %d file(s) from %d plist(s), interpreter %s"
              % (len(files), len(plists), args.python))
        for f in failures:
            print("FAIL %s" % f["where"])
            for line in f["detail"].splitlines()[-6:]:
                print("     %s" % line)
        if not failures:
            print("OK: every file loads under %s" % args.python)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
