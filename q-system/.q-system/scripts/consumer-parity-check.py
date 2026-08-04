#!/usr/bin/env python3
"""consumer-parity-check: a module that declares an exclusion predicate cannot gain
a filesystem walker that bypasses it.

WHY (ASK-315, RCA rca-one-sided-rule-application-2026-08-02): six instances of ONE
shape in ONE file in one night. A rule was added to one code path in a module that
had several, and the remaining paths kept voting with the old rule. Each fix was two
lines, which is exactly why each was made and the next appeared.

  1  which dirs are wiring surfaces      missed the rest of the repo
  2  generated trees are not wiring      missed the engine walk (12 engines dark)
  3  DATED_SNAPSHOT_RE                   missed _iter_surface_files
  4  is_excluded_tree()                  missed a 4th consumer: has_test's own rglob
  5  the invocation filter               missed .txt in SURFACE_CODE_EXT
  6  "hidden dirs rank lower"            also demoted .claude/ and .q-system/

Instance 4 is the diagnostic one. The commit that consolidated everything behind one
predicate, whose message read "one predicate for all three consumers", SHIPPED WITH A
FOURTH CONSUMER. The count came from memory, not from a grep.

WHY BY AST AND NOT BY A CONSUMER LIST: a hardcoded list of consumers is the same
unenumerated claim that caused the defect. This walks the module and enumerates every
`rglob` / `glob` / `iterdir` / `walk` / `scandir` call that exists, so a walker added
tomorrow is in the census the moment it is written. There is nothing to remember to
update.

WHAT PARITY MEANS HERE. A module may declare several exclusion predicates, and one may
call another (`is_vendored` consults SKIP_DIRS; `is_excluded_tree` consults
`_is_excluded_part`). Only the MAXIMAL predicates -- those no other predicate already
subsumes -- are required at each walker, and applying a caller counts as applying
everything it calls. So the demand is not "name every constant"; it is "this walker
filters the same way its siblings do". Instance 4 was precisely a walker that applied
is_vendored and not is_excluded_tree: filtered, but not to parity.

HONEST BOUNDARY (stated so this is not theater):
  - It proves the predicate is REFERENCED in the walker's consumer region, not that
    the reference is used correctly. `if is_vendored(p): pass` passes. STATICALLY dead
    references are the one class subtracted from that: a constant-false branch, the
    untaken side of a constant-true one, and anything after an unconditional
    return/raise/continue/break do not count as enforcement, because there the
    reference provably never runs and the walker is provably unfiltered (review
    finding, PR #82 minor). Reachability past that is undecidable, so `if DEBUG:`
    still counts and this boundary still holds.
  - A walker that itself sits in dead code is still REPORTED. The deadness rule only
    ever subtracts from `applied`, never from the census, so the error is toward
    reporting a walk that cannot run rather than toward passing one that can.
  - The consumer region is the enclosing `for` or comprehension. A walker whose result
    is stored in a variable and filtered three functions later is reported as
    `indirect` and checked at whole-function granularity, which is coarser and can go
    either way.
  - Predicate discovery is by NAME SHAPE (*EXCLUD* / *SKIP* / *VENDOR* / *IGNORE* /
    is_*_tree / is_vendored). A module whose exclusion predicate is called
    `keep_this_one` declares nothing this check can see, and is silently clean.
  - `.walk` and `.glob` are matched on the attribute name, so a non-filesystem object
    with a method of that name is a false positive. NON_FS_RECEIVERS narrows the
    known ones by receiver name (`ast.walk` is a tree traversal, `os.walk` is not); an
    unlisted one still reports. That is why everything except the seed module REPORTS
    rather than blocks.
  - `--report` skips fixtures/ and review-scratch trees (REPORT_SKIP_PARTS), judged
    RELATIVE to root. Those are red on purpose or are byte-copies of the repo, and
    counting them makes the false-positive measurement argue against itself.

MODE. Blocking is scoped to BLOCKING_MODULES (the seed). Every other module is
reported, never blocked, until the false-positive rate has been measured on real
modules -- `--report <root>` is how that measurement gets taken. `--strict` blocks on
everything, for a deliberate CI sweep.

Contract: CLI (`consumer-parity-check.py <file.py>...`, or `--report <root>`) or
PostToolUse hook (hook JSON on stdin, self-scoped to .py writes). exit 2 = block,
exit 0 = pass. Per-walker bypass: `parity-ack: <reason>` in a comment inside the
walker's own region. stdlib only.
Self-test: `python3 q-system/.q-system/scripts/test/test-consumer-parity-check.py`.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# The seed module. Everything else reports. Widening this set is a decision that
# needs a measured false-positive rate behind it (`--report`), not a hunch.
BLOCKING_MODULES = ("q-system/.q-system/scripts/capability-map-gen.py",)

ACK_MARKER = "parity-ack"

# --report only. Trees whose .py files are not modules of the repo under measurement.
# `--report` is the false-positive MEASUREMENT that gates widening BLOCKING_MODULES, so
# a tree that is red ON PURPOSE, or a byte-copy of the repo sitting in review scratch,
# makes the measurement argue against itself: it inflates both the module count and the
# finding count with things nobody will ever fix (review finding, PR #82 minor).
#   fixtures  - this check's own pre-fix snapshots. A module inside a fixtures/ dir IS
#               a fixture; being red is what it is pinned there to prove.
#   scratch   - .pr<N>rev/, worktrees/, review-trees/, .prd-os/: whole copies of the
#               repo, so every real finding in them is counted a second time.
# Deliberately NOT imported from capability-map-gen.py even though that module knows the
# same scratch shapes: a gate that imports the module it gates goes green when that
# module breaks. Duplication is the cheaper failure here.
REPORT_SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                     ".pytest_cache", "site-packages", "dist-packages", "fixtures"}
REPORT_SKIP_DIR_RE = re.compile(r"^\.pr\d+rev|^\.prd-os$|^worktrees$|^review-trees$")


def is_report_skipped(path: Path, root: Path) -> bool:
    """Sweep-only. A path named directly on the CLI is ALWAYS checked -- the reproducer
    that proves this gate works runs the pinned fixture by path.

    Judged on the path RELATIVE to root. Absolute parts are not the repo's business and
    reading them makes the answer depend on where the checkout happens to live: this
    worktree sits at `.../kipi/worktrees/ask-315`, so an absolute scan matched
    `worktrees` on EVERY file and swept the whole repo to 0 modules -- a zero that
    looked like a clean bill of health and was a broken query.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return any(part in REPORT_SKIP_PARTS or REPORT_SKIP_DIR_RE.match(part)
               for part in rel.parts)

# Method names that hand back filesystem entries. Attribute calls only: a bare
# `walk(...)` is usually a module-local helper that wraps a real walker, and that
# inner walker is already in the census -- counting the wrapper too would report the
# same walk twice and demand the filter at both layers.
WALKER_ATTRS = {"rglob", "glob", "iglob", "iterdir", "walk", "scandir", "listdir"}

# Receivers whose `.walk` / `.glob` hands back something that is not a filesystem
# entry, so a path-exclusion predicate at that call site would be meaningless. Matched
# on the BARE NAME of the receiver, never on the method, so `os.walk` stays a walker.
# This narrows the false-positive class the module docstring already declares; it is
# not a bypass list, and a real filesystem module never belongs in it.
# `ast` earned its place by making this check report five findings against its OWN
# source the moment REPORT_SKIP_PARTS gave the module a declared predicate. A checker
# that cries wolf on itself is the one an operator switches off first.
NON_FS_RECEIVERS = {"ast", "re", "json", "networkx", "nx"}

# An exclusion predicate names itself. FUNCTIONS whose name carries an exclusion verb,
# and module-level CONSTANTS whose name does and whose value is a container or a
# compiled pattern (a bare string constant named SKIP_MARKER is a bypass token, not a
# tree filter, and demanding it at every walker would be noise).
_PREDICATE_FUNC_RE = re.compile(
    r"^_?is_\w*(?:exclud|skip|vendor|ignor)\w*$|^_?is_\w+_tree$", re.I)
_PREDICATE_CONST_RE = re.compile(r"EXCLUD|SKIP|VENDOR|IGNOR", re.I)
_CONTAINER_NODES = (ast.Set, ast.List, ast.Tuple, ast.Dict, ast.SetComp,
                    ast.ListComp, ast.DictComp)


class Finding(NamedTuple):
    path: str
    lineno: int
    expr: str
    scope: str        # enclosing function name
    kind: str         # for | comprehension | indirect
    applied: tuple    # predicates this walker does apply
    missing: tuple    # predicates its siblings apply and it does not

    @property
    def severity(self) -> str:
        return "bypass" if not self.applied else "parity"

    def render(self) -> str:
        applied = ", ".join(self.applied) or "NOTHING"
        return (f"  {self.path}:{self.lineno}  [{self.severity}] "
                f"{self.scope}: {self.expr}\n"
                f"      applies: {applied}\n"
                f"      missing: {', '.join(self.missing)}"
                + ("\n      (indirect: result is not consumed by the enclosing loop, "
                   "so this was checked at whole-function granularity)"
                   if self.kind == "indirect" else ""))


# --- predicate discovery ------------------------------------------------------


def _declared_predicates(tree: ast.Module) -> set:
    """Names in this module that shape-declare themselves as exclusion predicates."""
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _PREDICATE_FUNC_RE.match(node.name):
                found.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            value = node.value
            if not names or value is None:
                continue
            is_container = isinstance(value, _CONTAINER_NODES)
            is_pattern = (isinstance(value, ast.Call)
                          and isinstance(value.func, ast.Attribute)
                          and value.func.attr in ("compile",))
            if not (is_container or is_pattern):
                continue
            for name in names:
                if _PREDICATE_CONST_RE.search(name):
                    found.add(name)
    return found


def _names_in(node: ast.AST) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _coverage(tree: ast.Module, predicates: set) -> dict:
    """predicate -> every predicate it reaches, transitively.

    `is_vendored` consults SKIP_DIRS, so a walker that calls is_vendored has already
    applied SKIP_DIRS. Without this the check would demand every constant be named at
    every walker, which is noise and would train people to silence it.
    """
    direct = {p: set() for p in predicates}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in predicates:
            direct[node.name] = (_names_in(node) & predicates) - {node.name}

    closed: dict = {}
    for start in predicates:
        seen, stack = set(), list(direct.get(start, ()))
        while stack:
            cur = stack.pop()
            if cur in seen or cur == start:
                continue
            seen.add(cur)
            stack.extend(direct.get(cur, ()))
        closed[start] = seen
    return closed


def _required(predicates: set, coverage: dict) -> set:
    """The MAXIMAL predicates: those no other predicate already subsumes.

    This is what makes the demand "filter like your siblings do" rather than "recite
    every constant". A leaf constant reached only through is_vendored is satisfied by
    calling is_vendored.
    """
    return {p for p in predicates
            if not any(p in coverage.get(q, ()) for q in predicates if q != p)}


# --- walker census ------------------------------------------------------------


def _is_walker_call(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WALKER_ATTRS):
        return False
    receiver = node.func.value
    return not (isinstance(receiver, ast.Name) and receiver.id in NON_FS_RECEIVERS)


def _parents(tree: ast.Module) -> dict:
    out = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _contains(root: ast.AST, target: ast.AST) -> bool:
    return any(n is target for n in ast.walk(root))


class _Region(NamedTuple):
    node: ast.AST
    kind: str
    scope: str


def _region_for(call: ast.Call, parents: dict, tree: ast.Module) -> _Region:
    """The construct that CONSUMES this walker's results.

    A `for` loop's body, or the comprehension the walker feeds. Function granularity
    is the fallback and is reported as such: `collect_domains` holds two walkers with
    different filtering, and a function-level answer would let the filtered one vouch
    for the unfiltered one -- which is the defect this file exists to find.
    """
    scope = "<module>"
    node, child = parents.get(id(call)), call
    while node is not None:
        if isinstance(node, (ast.For, ast.AsyncFor)) and _contains(node.iter, call):
            return _Region(node, "for", _enclosing_function(call, parents))
        if isinstance(node, ast.comprehension) and _contains(node.iter, call):
            comp = parents.get(id(node))
            if comp is not None:
                return _Region(comp, "comprehension", _enclosing_function(call, parents))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return _Region(node, "indirect", node.name)
        child, node = node, parents.get(id(node))
    return _Region(tree, "indirect", scope)


def _enclosing_function(node: ast.AST, parents: dict) -> str:
    cur = parents.get(id(node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        cur = parents.get(id(cur))
    return "<module>"


def _names_in_region(region: ast.AST, other_regions: set, predicates: set,
                     dead: set) -> set:
    """Predicate names referenced in this region, NOT descending into a sibling
    walker's region and NOT into statically dead code.

    collect_domains is the case: its outer `for p in sorted(root.glob("q-*"))` body
    contains an inner comprehension that DOES filter. Counting the inner filter for the
    outer walker is how a one-sided exclusion hides -- the filtered consumer vouches
    for the unfiltered one.

    `dead` is the same shape one rung further down: a predicate named in code that can
    never execute filters nothing, so counting it turns the BLOCKING path green over an
    unfiltered walk (review finding, PR #82 minor).
    """
    found, stack = set(), [region]
    while stack:
        node = stack.pop()
        if node is not region and (id(node) in other_regions or id(node) in dead):
            continue
        if isinstance(node, ast.Name) and node.id in predicates:
            found.add(node.id)
        stack.extend(ast.iter_child_nodes(node))
    return found


# Statements after one of these in the same block cannot run.
_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _static_truth(test: ast.AST):
    """True / False when the test is a compile-time constant, else None.

    Constants only, deliberately. `if DEBUG:` may be dead in every real run and this
    says nothing about it: over-claiming deadness would DISCOUNT a real filter and
    report a walker that does filter, and a checker that cries wolf is the one an
    operator switches off (same reasoning as NON_FS_RECEIVERS).
    """
    if isinstance(test, ast.Constant):
        try:
            return bool(test.value)
        except Exception:  # pragma: no cover - bool() on a constant does not raise
            return None
    return None


def _dead_nodes(tree: ast.Module) -> set:
    """ids of every node inside code that cannot execute.

    Three decidable shapes only: the body of a constant-false `if`/`while`, the
    `else` of a constant-true one, and whatever follows an unconditional
    return/raise/continue/break in the same statement list. Reachability in general is
    undecidable; this covers the shape the review named and nothing more.
    """
    dead = set()

    def kill(node: ast.AST) -> None:
        for inner in ast.walk(node):
            dead.add(id(inner))

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)):
            truth = _static_truth(node.test)
            if truth is True:
                for stmt in node.orelse:
                    kill(stmt)
            elif truth is False:
                for stmt in node.body:
                    kill(stmt)
        for field in _BLOCK_FIELDS:
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            terminated = False
            for stmt in block:
                if terminated:
                    kill(stmt)
                elif isinstance(stmt, _TERMINATORS):
                    terminated = True
    return dead


def _expr_text(call: ast.Call, source_lines: list) -> str:
    try:
        text = ast.unparse(call)
    except Exception:  # pragma: no cover - unparse is stdlib >=3.9
        text = source_lines[call.lineno - 1].strip() if call.lineno <= len(source_lines) else "?"
    return text if len(text) <= 90 else text[:87] + "..."


def _is_nested_in(inner: ast.AST, outer: ast.AST) -> bool:
    i_start, i_end = _span(inner)
    o_start, o_end = _span(outer)
    return o_start <= i_start and i_end <= o_end


def _span(node: ast.AST) -> tuple:
    start = getattr(node, "lineno", 1)
    return start, getattr(node, "end_lineno", start)


def _acked(region: ast.AST, source_lines: list, nested: list) -> bool:
    """Is there a `parity-ack` comment on a line this region OWNS?

    A nested walker's lines are not the parent's. The ack is scanned by line span, and
    a nested region's span sits inside its parent's, so an ack on the inner walker used
    to silence the outer one as well -- the acknowledged consumer vouching for the
    unfiltered one, which is the one-sided-exclusion shape this whole check exists to
    catch, one rung down (review finding, PR #82 minor). Same reason `_names_in_region`
    refuses to descend into a sibling region.

    The region's own OPENING line is always its own, even when a nested walker starts
    on it (`for f in [x for x in root.glob('*')]:  # parity-ack: ...`); otherwise the
    guard would silently void acks written where they read best.
    """
    start, end = _span(region)
    owned_by_nested = set()
    for other in nested:
        o_start, o_end = _span(other)
        owned_by_nested.update(range(o_start, o_end + 1))
    owned_by_nested.discard(start)
    return any(ACK_MARKER in line
               for lineno, line in enumerate(source_lines[max(start - 1, 0):end], start)
               if lineno not in owned_by_nested)


# --- the check ----------------------------------------------------------------


def check_source(source: str, path: str) -> list:
    """Every walker in `source` that does not filter to the module's own parity."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    predicates = _declared_predicates(tree)
    if not predicates:
        return []  # nothing declared, nothing to be at parity with
    coverage = _coverage(tree, predicates)
    required = _required(predicates, coverage)
    if not required:
        return []

    parents = _parents(tree)
    dead = _dead_nodes(tree)
    source_lines = source.splitlines()
    calls = [n for n in ast.walk(tree) if _is_walker_call(n)]
    regions = {id(call): _region_for(call, parents, tree) for call in calls}
    region_ids = {id(r.node) for r in regions.values()}
    region_nodes = {id(r.node): r.node for r in regions.values()}

    findings = []
    for call in calls:
        region = regions[id(call)]
        nested = [n for i, n in region_nodes.items()
                  if i != id(region.node) and _is_nested_in(n, region.node)]
        if _acked(region.node, source_lines, nested):
            continue
        applied = _names_in_region(region.node, region_ids - {id(region.node)},
                                   predicates, dead)
        expanded = set(applied)
        for name in applied:
            expanded |= coverage.get(name, set())
        missing = required - expanded
        if not missing:
            continue
        findings.append(Finding(
            path=path,
            lineno=call.lineno,
            expr=_expr_text(call, source_lines),
            scope=region.scope,
            kind=region.kind,
            applied=tuple(sorted(applied)),
            missing=tuple(sorted(missing)),
        ))
    return sorted(findings, key=lambda f: f.lineno)


def check_file(path: Path, display: str = "") -> list:
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return check_source(source, display or str(path))


def is_blocking(path_str: str) -> bool:
    normalized = path_str.replace(os.sep, "/")
    return any(normalized.endswith(m) for m in BLOCKING_MODULES)


def _stderr_report(findings: list, blocking: bool) -> str:
    head = ("CONSUMER PARITY (blocked): " if blocking
            else "consumer-parity-check (report): ")
    body = "\n".join(f.render() for f in findings)
    tail = (
        "\n\n  A walker whose results skip the module's own exclusion predicate votes "
        "with the OLD rule. That is the defect shape from ASK-315: six instances of it "
        "in one file in one night, each fix two lines, each fix followed by another.\n"
        "  Fix: filter this walker through the same predicate its siblings use. If the "
        f"walker genuinely must not filter, put `{ACK_MARKER}: <reason>` in a comment "
        "inside its loop or comprehension.\n"
        "  Scar: the commit that consolidated capability-map-gen.py behind one "
        "predicate, whose message read \"one predicate for all three consumers\", "
        "shipped with a fourth consumer. The count came from memory, not from a grep. "
        "This check counts by AST so there is no memory to be wrong.\n")
    return head + f"{len(findings)} walker(s) below parity.\n\n" + body + tail


# --- modes --------------------------------------------------------------------


def run_cli(paths: list, strict: bool) -> int:
    findings, blocked = [], False
    for raw in paths:
        path = Path(raw)
        got = check_file(path, raw)
        if got and (strict or is_blocking(raw)):
            blocked = True
        findings.extend(got)
    if not findings:
        print(f"consumer-parity-check: {len(paths)} module(s) checked, all walkers at parity.")
        return 0
    stream = sys.stderr if blocked else sys.stdout
    stream.write(_stderr_report(findings, blocked) + "\n")
    return 2 if blocked else 0


def run_report(root: Path) -> int:
    """Fleet sweep. This is the false-positive measurement the DoR gates widening on:
    it prints every module with a declared predicate and how many walkers miss parity,
    and it NEVER blocks."""
    modules, total, dirty = 0, 0, 0
    for path in sorted(root.rglob("*.py")):
        if is_report_skipped(path, root):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if not _declared_predicates(tree):
            continue
        modules += 1
        findings = check_source(source, str(path.relative_to(root)))
        if findings:
            dirty += 1
            total += len(findings)
            print(f"{path.relative_to(root)}: {len(findings)} walker(s) below parity")
            for finding in findings:
                print(finding.render())
    print(f"\nconsumer-parity-check --report: {modules} module(s) declare a predicate; "
          f"{dirty} have at least one walker below parity; {total} finding(s) total.")
    return 0


def run_hook(payload: dict) -> int:
    file_path = ((payload.get("tool_input") or {}).get("file_path") or "").strip()
    if not file_path.endswith(".py"):
        return 0
    path = Path(file_path)
    if not path.is_file():
        return 0
    findings = check_file(path, file_path)
    if not findings:
        return 0
    if is_blocking(file_path):
        sys.stderr.write(_stderr_report(findings, True) + "\n")
        return 2
    print(_stderr_report(findings, False))
    return 0


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        description="Assert every filesystem walker in a module applies the module's "
                    "own exclusion predicate.")
    parser.add_argument("paths", nargs="*", help="python modules to check")
    parser.add_argument("--report", metavar="ROOT",
                        help="sweep a tree and report; never blocks")
    parser.add_argument("--strict", action="store_true",
                        help="block on any module, not only BLOCKING_MODULES")
    args = parser.parse_args(argv)

    if args.report:
        return run_report(Path(args.report).resolve())
    if args.paths:
        return run_cli(args.paths, args.strict)

    try:
        payload = json.load(sys.stdin)
    except Exception:
        parser.print_help()
        return 0
    return run_hook(payload if isinstance(payload, dict) else {})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
