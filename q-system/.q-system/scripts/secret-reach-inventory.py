#!/usr/bin/env python3
"""What secrets can this process REACH, not what was it granted (ASK-1251).

Tool allowlists enumerate what an agent was granted. Nothing enumerated what is
merely reachable: the agent runs as the founder's uid, so a 0600 key file is
"protected" against every process except the one that matters. Measured
2026-09-04: a Linear write key, the Claude credentials, the CRM send gate and
three exported shell tokens were all readable by the agent's own uid.

This script refreshes that answer instead of leaving it remembered. Three
sources, each reported by NAME only:

- env    the secret-shaped variable names in this process's environment
- shell  variable assignments in the declared shell profiles, and in any
         file they `source` by a literal path (names only)
- file   declared paths, plus secret-named files anywhere under the declared
         scan dirs, up to SCAN_DEPTH levels, skipping git checkouts

What the shell source does NOT see, said here so its silence is read narrowly:
a name built at run time (`eval`, `export "$x"`), a file sourced through a
variable path other than $HOME (reported NOT-SCANNED, never followed), and
anything a login shell loads from outside the declared profiles.

A profile or scan dir that exists but cannot be read is UNREADABLE and turns
the run RED. An absent one is normal: not every machine has every profile.

A file is probed by opening it read-only and closing it. Zero bytes are read.
An env or shell value is never stored past the parse that pulls out its name.
Nothing here may print a value, and test_values_are_never_printed holds that.

Every discovered name must have a row in secret-reach-registry.json saying
whether it is knowledge-only or authority-changing (possession lets the process
send, write, delete, publish or spend). Every authority row must point at a
decision in canonical/decisions.md whose section carries an origin tag and
names the row. The origin-tag vocabulary and the section parser are imported
from decision-origin-tag-lint.py, the owner, never restated here.

Run it from the kipi-system skeleton: the decisions it checks live in the
skeleton's decisions.md, not an instance's. In a checkout with no
instance-registry.json at its root it exits 2 unless --decisions is passed.

A file row carries either an exact `path` or a `glob` of the one shape
`<literal dir>/*`, which classifies everything under that directory (Chromium
profiles, dated ack receipts). A glob over a whole scan dir is refused.
A non-regular file (a FIFO, a socket) is reported `not-regular`, never opened.

Exit 0: everything discovered is classified and every authority row is bound.
Exit 1: an UNCLASSIFIED name, an UNREADABLE source, or an authority row with no
        bound decision (a decision tagged REJECTED binds nothing).
Exit 2: the registry itself is unusable (missing, empty, a bad class, a file
        row with no path, a glob of any other shape), or an instance checkout
        with no --decisions.
"""

import argparse
import importlib.util
import json
import os
import pathlib
import re
import shlex
import stat
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
QROOT = SCRIPTS.parent.parent
DEFAULT_REGISTRY = QROOT / ".q-system" / "secret-reach-registry.json"
DEFAULT_DECISIONS = QROOT / "canonical" / "decisions.md"
CLASSES = ("authority", "knowledge")
SOURCES = ("env", "shell", "file")
# Builtins whose arguments are NAME or NAME=value. `local` is left out on
# purpose: a function-local variable never reaches the environment.
DECLARE_BUILTINS = ("export", "typeset", "declare", "readonly")
SOURCE_BUILTINS = ("source", ".")
SHELL_PUNCTUATION = set("();<>|&")
# Words that open a compound command. Stripped before the command itself is
# read: `if x; then source ~/.y; fi` is the shape the gcloud installer writes,
# and reading only the first word saw `then` and skipped it (PR #345 round 3).
SHELL_KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "{", "!")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Only for a line shlex cannot tokenize (a quote left open for a multi-line value).
FALLBACK_ASSIGN_RE = re.compile(
    r"^\s*(?:(?:export|typeset|declare|readonly)(?:\s+[-+]\w+)*\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
# Subdirectory levels walked under a scan dir. Bounded because
# ~/.config/kipi/worktrees holds whole repo checkouts full of secret-NAMED
# source files, which is also why a directory holding .git is never entered.
SCAN_DEPTH = 3
# Absent is normal (not every machine has every profile). Anything else that
# stops a read is UNREADABLE: the review of PR #345 caught the old code
# folding a permission error into "absent" and reporting GREEN.
ABSENT = (FileNotFoundError, NotADirectoryError)


class RegistryError(Exception):
    pass


def load_tag_lint():
    """Import decision-origin-tag-lint.py, the owner of the tag vocabulary."""
    path = SCRIPTS / "decision-origin-tag-lint.py"
    spec = importlib.util.spec_from_file_location("decision_origin_tag_lint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_registry(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}")
    rows = data.get("rows") or []
    # Zero rows would report every discovered name as unclassified or, with
    # discovery off, pass on nothing. Either way the run means nothing.
    if not rows:
        raise RegistryError(f"registry {path} has zero rows")
    for row in rows:
        validate_row(row, data.get("scan_dirs", []))
    return data


def validate_row(row, scan_dirs=()):
    if row.get("class") not in CLASSES:
        raise RegistryError(f"row {row.get('id')!r} has class {row.get('class')!r}, "
                            f"expected one of {CLASSES}")
    if row.get("kind") not in ("env", "file") or not row.get("id"):
        raise RegistryError(f"row {row!r} needs an id and kind env or file")
    if row["kind"] == "file" and "glob" in row:
        glob_prefix(row, scan_dirs)
        return
    path = row.get("path")
    if row["kind"] == "file" and not (isinstance(path, str) and path):
        raise RegistryError(f"file row {row['id']!r} needs a non-empty path")


def glob_prefix(row, scan_dirs):
    """The one directory a glob row classifies, or RegistryError.

    Rounds 2 and 3 of the PR #345 review: an exact-path registry can never
    classify what a Chromium profile or spillover-ratchet.py keeps minting, so
    the file scan could never hold GREEN. A glob row fixes that and is also a
    blanket that could hide a real secret, so its only legal shape is
    `<literal dir>/*`, and that dir may not be a scan dir itself. A new sibling
    directory stays UNCLASSIFIED, which is the point.
    """
    glob = row.get("glob")
    prefix = glob[:-2] if isinstance(glob, str) and glob.endswith("/*") else ""
    if not prefix or any(c in prefix for c in "*?["):
        raise RegistryError(f"file row {row['id']!r}: glob {glob!r} must be "
                            "<literal dir>/* with no other wildcard")
    if prefix.rstrip("/") in {d.rstrip("/") for d in scan_dirs}:
        raise RegistryError(f"file row {row['id']!r}: glob {glob!r} blankets the "
                            "whole scan dir, which would classify every secret in it")
    return prefix


def expand(home, raw):
    return pathlib.Path(home) / raw[2:] if raw.startswith("~/") else pathlib.Path(raw)


def display(home, path):
    try:
        return "~/" + str(pathlib.Path(path).relative_to(home))
    except ValueError:
        return str(path)


def probe_file(path):
    """Existence, mode and whether THIS process can open it. Reads no bytes."""
    try:
        info = os.stat(path)
    except ABSENT:
        return {"state": "absent"}
    except OSError:
        return {"state": "denied"}
    mode = f"{stat.S_IMODE(info.st_mode):04o}"
    # Opening a FIFO read-only blocks until a writer appears, so the run hung.
    if not stat.S_ISREG(info.st_mode):
        return {"state": "not-regular", "mode": mode}
    try:
        fd = os.open(path, os.O_RDONLY)
        os.close(fd)
        state = "reachable"
    except OSError:
        state = "denied"
    return {"state": state, "mode": mode, "own": info.st_uid == os.getuid()}


def env_names(name_re):
    return sorted(k for k in os.environ if name_re.search(k))


def shell_commands(line):
    """Split one profile line into commands (lists of words), quotes respected."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        words = list(lexer)
    except ValueError:
        match = FALLBACK_ASSIGN_RE.match(line)
        return [[match.group(1) + "="]] if match else []
    commands, current = [], []
    for word in words:
        if set(word) <= SHELL_PUNCTUATION:
            commands.append(current)
            current = []
        else:
            current.append(word)
    return [c for c in commands + [current] if c]


def assigned_names(words):
    """Names a command assigns or exports. Values are dropped here, unread."""
    if words[0] in DECLARE_BUILTINS:
        args = [w for w in words[1:] if not w.startswith(("-", "+"))]
        return [n for n in (a.split("=", 1)[0] for a in args) if NAME_RE.match(n)]
    names = []
    for word in words:  # leading NAME=value words, as in `A=1 B=2 cmd`
        name, has_equals, _ = word.partition("=")
        if not has_equals or not NAME_RE.match(name):
            break
        names.append(name)
    return names


def strip_keywords(words):
    while words and words[0] in SHELL_KEYWORDS:
        words = words[1:]
    return words


def sourced_path(arg, home):
    """The literal file `source ARG` reads, or None when ARG is computed."""
    for var in ("${HOME}", "$HOME"):
        if arg.startswith(var + "/"):
            arg = str(home) + arg[len(var):]
    if arg.startswith("~/"):
        arg = str(home) + arg[1:]
    if "$" in arg or "`" in arg:
        return None
    path = pathlib.Path(arg)
    return path if path.is_absolute() else pathlib.Path(home) / path


def read_profile(raw, path, report):
    """Profile text, or None. Absent is silent; unreadable is a problem."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except ABSENT:
        return None
    except OSError as exc:
        report["unreadable"].append(f"{raw}: {type(exc).__name__}")
        return None


def shell_export_names(home, shell_files, name_re, report):
    """Walk the profiles and the literal files they source. Returns (name, where)."""
    found, seen = [], set()
    queue = [(raw, expand(home, raw)) for raw in shell_files]
    while queue:
        raw, path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        text = read_profile(raw, path, report)
        for line in (text or "").splitlines():
            for words in map(strip_keywords, shell_commands(line)):
                if not words:
                    continue
                if words[0] in SOURCE_BUILTINS and len(words) > 1:
                    target = sourced_path(words[1], home)
                    if target is None:
                        report["not_scanned"].append(f"{words[1]} (sourced from {raw})")
                    else:
                        queue.append((display(home, target), target))
                    continue
                found += [(n, raw) for n in assigned_names(words)
                          if name_re.search(n) and (n, raw) not in found]
    return found


def scanned_files(home, scan_dirs, name_re, report):
    found = []

    def unreadable(exc):
        if not isinstance(exc, ABSENT):
            report["unreadable"].append(f"{display(home, exc.filename)}: {type(exc).__name__}")

    for raw in scan_dirs:
        base = expand(home, raw)
        for dirpath, dirnames, filenames in os.walk(base, onerror=unreadable):
            rel = pathlib.Path(dirpath).relative_to(base)
            dirnames[:] = sorted(d for d in dirnames if len(rel.parts) < SCAN_DEPTH
                                 and not os.path.lexists(os.path.join(dirpath, d, ".git")))
            found += [f"{raw.rstrip('/')}/{(rel / n).as_posix()}" for n in sorted(filenames)
                      if name_re.search(n)]
    return found


def discover(registry, home, sources):
    """Return (lines, unclassified, report) for every source requested."""
    name_re = re.compile(registry.get("secret_name_re", "(?i)(token|key|secret)"))
    by_env = {r["id"]: r for r in registry["rows"] if r["kind"] == "env"}
    by_path = {r["path"]: r for r in registry["rows"] if r["kind"] == "file" and "path" in r}
    globs = [(glob_prefix(r, ()) + "/", r) for r in registry["rows"] if "glob" in r]
    lines, unclassified = [], []
    report = {"unreadable": [], "not_scanned": []}
    if "env" in sources:
        for name in env_names(name_re):
            lines.append(describe(by_env.get(name), name, "env", "present", unclassified))
    if "shell" in sources:
        shell_files = registry.get("shell_files", [])
        for name, raw in shell_export_names(home, shell_files, name_re, report):
            lines.append(describe(by_env.get(name), name, f"assigned in {raw}", "present",
                                  unclassified))
    if "file" in sources:
        scanned = scanned_files(home, registry.get("scan_dirs", []), name_re, report)
        for raw in list(by_path) + [p for p in scanned if p not in by_path]:
            info = probe_file(expand(home, raw))
            state = info["state"] + (f" {info['mode']}" if "mode" in info else "")
            row = by_path.get(raw) or next((r for pre, r in globs if raw.startswith(pre)), None)
            where = "file" if row is None or "path" in row else f"file {raw}"
            lines.append(describe(row, raw, where, state, unclassified))
    return lines, unclassified, report


def describe(row, name, where, state, unclassified):
    if row is None:
        unclassified.append(name)
        return f"[UNCLASSIFIED] {name}  ({where}, {state})  no registry row"
    label = row["class"].upper()
    tail = f"  decision {row['decision']}" if row.get("decision") else ""
    return f"[{label}] {row['id']}  ({where}, {state})  grants: {row.get('grants', '?')}{tail}"


def binding_problem(row, sections, decisions_path, tag_lint):
    """Why this authority row is not bound to a decision, or None if it is."""
    ref = row.get("decision")
    if not ref:
        return f"{row['id']}: authority row has no decision id"
    body = sections.get(ref)
    if body is None:
        return f"{row['id']}: decision {ref} not found in {decisions_path}"
    # The section's first tag is its Origin line. Group 2 of the owner's regex
    # is the CLAUDE-RECOMMENDED outcome; a recommendation the operator rejected
    # is a record of NOT deciding, so it binds nothing.
    tag = tag_lint.VALID_TAG_RE.search(body)
    if tag is None:
        return f"{row['id']}: decision {ref} carries no origin tag"
    if tag.group(2) == "REJECTED":
        return f"{row['id']}: decision {ref} is tagged {tag.group(0)}, which binds nothing"
    if f"`{row['id']}`" not in body:
        return f"{row['id']}: decision {ref} does not name `{row['id']}`"
    return None


def unbound_authority_rows(registry, decisions_path, tag_lint):
    """Every authority row needs a decision section that is tagged and names it."""
    try:
        text = pathlib.Path(decisions_path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read decisions file {decisions_path}: {exc}"]
    sections = {heading.split(":")[0].strip(): body
                for _, heading, body in tag_lint.extract_sections(text)}
    problems = [binding_problem(row, sections, decisions_path, tag_lint)
                for row in registry["rows"] if row["class"] == "authority"]
    return [p for p in problems if p]


def instance_checkout_problem(decisions_flag):
    """Why the default decisions file is the wrong one here, or None.

    The script and registry ship to every instance through the synced q-system/
    tree, and an instance's decisions.md never carries the skeleton's
    RULE-2026-09-13 sections, so a run there reported 20 unbound rows that mean
    nothing (PR #345 round 3). Same skeleton test capability-gate.py uses:
    instance-registry.json at the repo root.
    """
    if decisions_flag is not None:
        return None
    registry = QROOT.parent / "instance-registry.json"
    if registry.is_file():
        return None
    return (f"no {registry} here, so this is an instance checkout. The decisions "
            "this binds against live in the kipi-system skeleton: run it there, "
            "or pass --decisions.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--decisions", default=None,
                    help="decisions.md to bind against (default: the skeleton's own)")
    ap.add_argument("--home", default=str(pathlib.Path.home()))
    ap.add_argument("--source", action="append", choices=SOURCES,
                    help="limit discovery to one source; repeatable (default: all)")
    args = ap.parse_args(argv)
    problem = instance_checkout_problem(args.decisions)
    if problem:
        print(f"secret-reach-inventory: {problem}", file=sys.stderr)
        return 2
    try:
        registry = load_registry(args.registry)
    except RegistryError as exc:
        print(f"secret-reach-inventory: {exc}", file=sys.stderr)
        return 2
    sources = tuple(args.source or SOURCES)
    lines, unclassified, report = discover(registry, args.home, sources)
    decisions = args.decisions or str(DEFAULT_DECISIONS)
    problems = unbound_authority_rows(registry, decisions, load_tag_lint())
    print(f"secret-reach-inventory: uid {os.getuid()}, sources {', '.join(sources)}")
    for line in lines:
        print(f"  {line}")
    for item in report["unreadable"]:
        print(f"  [UNREADABLE] {item}")
    for item in report["not_scanned"]:
        print(f"  [NOT-SCANNED] {item}  computed path, not followed")
    for problem in problems:
        print(f"  [UNBOUND] {problem}")
    verdict = "RED" if unclassified or problems or report["unreadable"] else "GREEN"
    print(f"{verdict}: {len(lines)} reachable-surface rows, "
          f"{len(unclassified)} unclassified, {len(report['unreadable'])} unreadable, "
          f"{len(problems)} unbound authority rows, "
          f"{len(report['not_scanned'])} sourced paths not scanned")
    return 1 if verdict == "RED" else 0


if __name__ == "__main__":
    sys.exit(main())

