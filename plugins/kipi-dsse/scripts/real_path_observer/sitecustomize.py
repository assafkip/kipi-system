"""Real-path observer for `issue_runner.py verify` (ASK-1810). Put FIRST on PYTHONPATH by verify
for one pass of the required checks; inert unless KIPI_REAL_PATH_LOG names a file.

WHY: on ASK-1796, 66 tests ran a COPY of the gate beside stand-in producers, every one green,
while a reviewer sealed a failing page with the real gate. A test that copies a script has to
name it to copy it, so no text rule over the test file can tell a copy from the real thing
(measured 2026-09-18 on 256 specs: a copy detector even misfiled ASK-1808, the one issue built
to the standard). What CAN tell them apart is where the code ran from. This records it.

What it records, one JSON line per event into the log (append, one short write each, so
concurrent processes interleave whole lines):
  - "run":   the script a process was started on (audit event cpython.run_file)
  - "exec":  the co_filename of every code object handed to exec() -- which is how
             importlib's exec_module runs a module loaded from a path, even one never put
             in sys.modules
  - "spawn": every file argument of subprocess.Popen / os.exec* / os.posix_spawn argv,
             written BEFORE the call, because an exec replaces the process and atexit never runs
  - "mods":  at exit, every loaded module's __file__
A path is logged as the process saw it; verify resolves it and matches it against the
issue's allowed files at their tracked location. A copy in a temp dir logs the temp path.

LIMITS, stated where the refusal quotes them: Python processes only (a bash script calling a
bash script is invisible); a child started with PYTHON* variables scrubbed does not load this
file (its parent's spawn argv still counts); it proves a file was executed at its production
path, not that any assertion depended on it. It is loaded through PYTHONPATH, so a check that
treats a non-empty PYTHONPATH as its own (os.environ.setdefault) runs differently when observed:
test_computed_receipts.py did, and lost its own path (ASK-1810). Prepend, never setdefault.

It shadows the interpreter's own sitecustomize (Homebrew ships one), so it runs that one
afterwards, found on sys.path without this directory.
"""
import atexit
import json
import os
import re
import sys

_LOG = os.environ.get("KIPI_REAL_PATH_LOG")
_HERE = os.path.dirname(os.path.abspath(__file__))


def _write(kind, paths):
    if not paths:
        return
    try:
        line = json.dumps({"pid": os.getpid(), "kind": kind, "paths": sorted(set(paths))}) + "\n"
        fd = os.open(_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except Exception:
        pass        # an observer that breaks the observed run would change what it measures


_PYTHON = re.compile(r"^python(\d+(\.\d+)?)?$", re.I)
_TAKES_VALUE = {"-W", "-X", "-Q"}


def _str(a):
    try:
        a = os.fspath(a)
    except TypeError:
        return None
    return a.decode(errors="replace") if isinstance(a, bytes) else a


def _files_in(argv):
    """The script a spawn RUNS, never every .py argument: `cp tool.py tmp` then running the
    copy counted as driving tool.py (ASK-1810 review, finding-7a, the ASK-1796 copy shape).
    Counts argv[0] when it is itself a .py file; when argv[0] is a Python interpreter, the
    first non-option argument, skipping -W/-X values; nothing after -c or -m."""
    argv = [x for x in (_str(a) for a in (argv or ())) if isinstance(x, str)]
    if not argv:
        return []
    prog = argv[0]
    if prog.endswith(".py") and os.path.isfile(prog):
        return [os.path.abspath(prog)]
    name = os.path.basename(prog)
    if not (_PYTHON.match(name) or os.path.realpath(prog) == os.path.realpath(sys.executable)):
        return []
    skip = False
    for a in argv[1:]:
        if skip:
            skip = False
        elif a in ("-c", "-m", "-"):
            return []
        elif a in _TAKES_VALUE:
            skip = True
        elif a.startswith("-"):
            continue
        else:
            return [os.path.abspath(a)] if a.endswith(".py") and os.path.isfile(a) else []
    return []


def _hook(event, args):
    try:
        if event == "cpython.run_file":
            _write("run", [os.path.abspath(os.fspath(args[0]))])
        elif event == "exec":
            # every import runs its module through exec(), so this is buffered, not written
            fn = getattr(args[0], "co_filename", None)
            if fn and fn.endswith(".py"):
                _SEEN.add(fn)
        elif event == "subprocess.Popen":
            argv = args[1]
            argv = [argv] if isinstance(argv, (str, bytes, os.PathLike)) else argv
            _flush()
            _write("spawn", _files_in(argv))
        elif event in ("os.exec", "os.posix_spawn", "os.spawn"):
            _flush()        # an exec replaces this process: atexit will never run
            _write("spawn", _files_in(args[1] if len(args) > 1 else ()))
    except Exception:
        pass


_SEEN = set()


def _flush():
    seen = [os.path.abspath(f) for f in _SEEN if os.path.isfile(f)]
    _SEEN.clear()
    _write("exec", seen)


def _at_exit():
    _flush()
    files = []
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if isinstance(f, str) and f.endswith(".py"):
            files.append(os.path.abspath(f))
    _write("mods", files)


if _LOG:
    sys.addaudithook(_hook)
    atexit.register(_at_exit)


def _chain():
    import importlib.machinery
    import importlib.util
    rest = [p for p in sys.path if os.path.abspath(p or ".") != _HERE]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


try:
    _chain()
except Exception as e:
    # what CPython prints when sitecustomize raises; swallowing it made the observed run
    # differ from production with nothing said (ASK-1810 review, finding-10)
    sys.stderr.write(f"Error in sitecustomize; set PYTHONVERBOSE for traceback:\n{type(e).__name__}: {e}\n")
