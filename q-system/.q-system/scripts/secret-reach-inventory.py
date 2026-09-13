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
- shell  `export NAME=` lines in the declared shell profiles (names only)
- file   declared paths, plus secret-named files in the declared scan dirs

A file is probed by opening it read-only and closing it. Zero bytes are read.
An env or shell value is never stored past the regex that pulls out its name.
Nothing here may print a value, and test_values_are_never_printed holds that.

Every discovered name must have a row in secret-reach-registry.json saying
whether it is knowledge-only or authority-changing (possession lets the process
send, write, delete, publish or spend). Every authority row must point at a
decision in canonical/decisions.md whose section carries an origin tag and
names the row. The origin-tag vocabulary and the section parser are imported
from decision-origin-tag-lint.py, the owner, never restated here.

Run it from the kipi-system skeleton: the decisions it checks live in the
skeleton's decisions.md, not an instance's.

Exit 0: everything discovered is classified and every authority row is bound.
Exit 1: an UNCLASSIFIED name, or an authority row with no bound decision.
Exit 2: the registry itself is unusable (missing, empty, or a bad class).
"""

import argparse
import importlib.util
import json
import os
import pathlib
import re
import stat
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
QROOT = SCRIPTS.parent.parent
DEFAULT_REGISTRY = QROOT / ".q-system" / "secret-reach-registry.json"
DEFAULT_DECISIONS = QROOT / "canonical" / "decisions.md"
CLASSES = ("authority", "knowledge")
SOURCES = ("env", "shell", "file")
EXPORT_RE = re.compile(r"^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=")


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
        if row.get("class") not in CLASSES:
            raise RegistryError(f"row {row.get('id')!r} has class {row.get('class')!r}, "
                                f"expected one of {CLASSES}")
        if row.get("kind") not in ("env", "file") or not row.get("id"):
            raise RegistryError(f"row {row!r} needs an id and kind env or file")
    return data


def expand(home, raw):
    return pathlib.Path(home) / raw[2:] if raw.startswith("~/") else pathlib.Path(raw)


def probe_file(path):
    """Existence, mode and whether THIS process can open it. Reads no bytes."""
    try:
        info = os.stat(path)
    except OSError:
        return {"state": "absent"}
    mode = f"{stat.S_IMODE(info.st_mode):04o}"
    try:
        fd = os.open(path, os.O_RDONLY)
        os.close(fd)
        state = "reachable"
    except OSError:
        state = "denied"
    return {"state": state, "mode": mode, "own": info.st_uid == os.getuid()}


def env_names(name_re):
    return sorted(k for k in os.environ if name_re.search(k))


def shell_export_names(home, shell_files, name_re):
    found = []
    for raw in shell_files:
        try:
            lines = expand(home, raw).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = EXPORT_RE.match(line)
            if match and name_re.search(match.group(1)):
                found.append((match.group(1), raw))
    return found


def scanned_files(home, scan_dirs, name_re):
    found = []
    for raw in scan_dirs:
        base = expand(home, raw)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        found += [f"{raw.rstrip('/')}/{n}" for n in names
                  if name_re.search(n) and (base / n).is_file()]
    return found


def discover(registry, home, sources):
    """Return (lines, unclassified) for every source requested."""
    name_re = re.compile(registry.get("secret_name_re", "(?i)(token|key|secret)"))
    by_env = {r["id"]: r for r in registry["rows"] if r["kind"] == "env"}
    by_path = {r["path"]: r for r in registry["rows"] if r["kind"] == "file"}
    lines, unclassified = [], []
    if "env" in sources:
        for name in env_names(name_re):
            lines.append(describe(by_env.get(name), name, "env", "present", unclassified))
    if "shell" in sources:
        for name, raw in shell_export_names(home, registry.get("shell_files", []), name_re):
            lines.append(describe(by_env.get(name), name, f"export in {raw}", "present",
                                  unclassified))
    if "file" in sources:
        paths = list(by_path) + [p for p in scanned_files(home, registry.get("scan_dirs", []),
                                                         name_re) if p not in by_path]
        for raw in paths:
            info = probe_file(expand(home, raw))
            state = info["state"] + (f" {info['mode']}" if "mode" in info else "")
            lines.append(describe(by_path.get(raw), raw, "file", state, unclassified))
    return lines, unclassified


def describe(row, name, where, state, unclassified):
    if row is None:
        unclassified.append(name)
        return f"[UNCLASSIFIED] {name}  ({where}, {state})  no registry row"
    label = row["class"].upper()
    tail = f"  decision {row['decision']}" if row.get("decision") else ""
    return f"[{label}] {row['id']}  ({where}, {state})  grants: {row.get('grants', '?')}{tail}"


def unbound_authority_rows(registry, decisions_path, tag_lint):
    """Every authority row needs a decision section that is tagged and names it."""
    try:
        text = pathlib.Path(decisions_path).read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read decisions file {decisions_path}: {exc}"]
    sections = {heading.split(":")[0].strip(): body
                for _, heading, body in tag_lint.extract_sections(text)}
    problems = []
    for row in registry["rows"]:
        if row["class"] != "authority":
            continue
        ref = row.get("decision")
        body = sections.get(ref) if ref else None
        if not ref:
            problems.append(f"{row['id']}: authority row has no decision id")
        elif body is None:
            problems.append(f"{row['id']}: decision {ref} not found in {decisions_path}")
        elif not tag_lint.VALID_TAG_RE.search(body):
            problems.append(f"{row['id']}: decision {ref} carries no origin tag")
        elif f"`{row['id']}`" not in body:
            problems.append(f"{row['id']}: decision {ref} does not name `{row['id']}`")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    ap.add_argument("--home", default=str(pathlib.Path.home()))
    ap.add_argument("--source", action="append", choices=SOURCES,
                    help="limit discovery to one source; repeatable (default: all)")
    args = ap.parse_args(argv)
    try:
        registry = load_registry(args.registry)
    except RegistryError as exc:
        print(f"secret-reach-inventory: {exc}", file=sys.stderr)
        return 2
    sources = tuple(args.source or SOURCES)
    lines, unclassified = discover(registry, args.home, sources)
    problems = unbound_authority_rows(registry, args.decisions, load_tag_lint())
    print(f"secret-reach-inventory: uid {os.getuid()}, sources {', '.join(sources)}")
    for line in lines:
        print(f"  {line}")
    for problem in problems:
        print(f"  [UNBOUND] {problem}")
    verdict = "RED" if unclassified or problems else "GREEN"
    print(f"{verdict}: {len(lines)} reachable-surface rows, "
          f"{len(unclassified)} unclassified, {len(problems)} unbound authority rows")
    return 1 if verdict == "RED" else 0


if __name__ == "__main__":
    sys.exit(main())
