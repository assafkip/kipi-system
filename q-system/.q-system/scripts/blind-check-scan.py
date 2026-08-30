#!/usr/bin/env python3
"""Static detectors for checks that RUN, PASS, and cannot see what they exist to catch.

Pairs with q-system/lessons/ (the class), and with mutation-sweep.py, which is
the EXPENSIVE detector for the same class. Mutation testing answers "can any
version of the subject turn this test red" by executing it; that costs minutes
per test and cannot run at commit time. These three answer cheaper questions
statically, so a NEW instance is caught when it is written rather than at the
next periodic sweep.

    scope    (mechanism E) a check whose declared scope excludes members of the
             population it claims to cover.
    swallow  (mechanism C) a verdict-bearing call whose exit code is discarded.
    predcopy (mechanism G) a test carrying its own copy of the rule it checks.

Three design constraints, taken from q-system/hooks/lessons-index.py, which
solved a version of this problem in this repo already:

1. NO RELEVANCE RANKING. Findings are reported flat, in path order. A wrong
   rank looks identical to a right one and fails silently, which is the same
   class of failure these detectors exist to catch. A detector that mis-ranks
   is worse than one that reports flat.

2. A CEILING, NOT A CAP. --ratchet compares each detector's count against
   blind-check-baseline.json and FAILS when a count grows. It never truncates
   and never silently tolerates. A cap drops content quietly; a ceiling makes
   growth a decision someone makes on purpose. Unbounded growth and a silent
   cap are the same defect pointed in opposite directions.

3. MEASURED COST, NOT ESTIMATED. --cost prints wall-clock and files walked. A
   standing gate nobody can afford gets switched off, and a gate that is off
   protects nothing.

Every detector here keys on something SPECIFIC rather than on a raw pattern.
Measured on this repo: the raw pattern counts are 413 (|| true) and 781
(2>/dev/null). Reporting those would be reporting noise. The swallow detector
filters to calls whose callee is a repo artifact that actually exits nonzero,
which is the difference between a finding and a grep.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 1

# Copies of nothing: these are this scanner's own walk rules. Scratch trees are
# full repo copies (4448 of this repo's 8261 raw test-pattern matches live under
# .claude/worktrees/), and walking them measures the same file many times.
EXCLUDE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "site-packages", "__pycache__",
    ".claude", ".fable-wt", "template-repo", ".rescue", ".review-scratch",
    ".mypy_cache", ".pytest_cache", "vendor", "dist", "build", ".prd-os",
})
EXCLUDE_PREFIXES = (".pr", ".wt-", ".review-tmp", "rescued")

TEST_GLOBS = ("test_*.py", "test-*.py", "test-*.sh", "test_*.sh",
              "*_test.py", "*_test.sh")


def excluded(name):
    return name in EXCLUDE_DIRS or name.startswith(EXCLUDE_PREFIXES)


def walk(root, suffixes=None, globs=None):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not excluded(d)]
        for fn in filenames:
            if suffixes and not fn.endswith(suffixes):
                continue
            if globs and not any(fnmatch.fnmatch(fn, g) for g in globs):
                continue
            yield Path(dirpath) / fn


def rel(root, p):
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return str(p)


# ------------------------------------------------------------- mechanism E

def detect_scope(root, registry_path):
    """Diff each declared scope against the population it claims to cover.

    The registry is data, not inference. An auto-discovered "scope constant"
    detector would guess which of this repo's twenty-odd *_PREFIXES tuples are
    scope claims and which are ordinary constants, and a wrong guess here is
    silent -- the same failure mode as the thing being detected. So a scope is
    registered explicitly, with the two commands that enumerate its population
    and its coverage, and the detector only subtracts.

    Each entry:
      id           name for the finding
      population   shell command printing one member per line (what exists)
      covered      shell command printing one member per line (what is watched)
      allow        members deliberately outside the scope, each with a reason.
                   An allowlist entry is a decision someone made on purpose;
                   an unlisted gap is a hole nobody knows about.
    """
    findings = []
    try:
        reg = json.loads(Path(registry_path).read_text())
    except FileNotFoundError:
        return [{"detector": "scope", "path": str(registry_path),
                 "detail": "scope registry missing; no scope is being checked"}]
    except json.JSONDecodeError as e:
        return [{"detector": "scope", "path": str(registry_path),
                 "detail": f"scope registry is unparseable: {e}"}]

    for entry in reg.get("scopes", []):
        sid = entry.get("id", "<unnamed>")
        allow = {a["member"]: a.get("reason", "") for a in entry.get("allow", [])}

        def run(cmd):
            r = subprocess.run(["bash", "-c", cmd], cwd=root, text=True,
                               capture_output=True, timeout=120)
            return r
        try:
            rp = run(entry["population"])
            rc = run(entry["covered"])
        except (subprocess.TimeoutExpired, KeyError) as e:
            findings.append({"detector": "scope", "path": sid,
                             "detail": f"scope commands did not run: {e}"})
            continue
        # A scope whose OWN enumeration is broken reports an empty population
        # and therefore a clean diff: the detector would go green for exactly
        # the reason it exists to catch. Non-zero rc is fatal to the entry.
        if rp.returncode != 0 or rc.returncode != 0:
            findings.append({
                "detector": "scope", "path": sid,
                "detail": "enumeration FAILED (population rc=%d, covered rc=%d); "
                          "refusing to report a clean diff over a broken "
                          "enumeration: %s" % (rp.returncode, rc.returncode,
                                               (rp.stderr + rc.stderr).strip()[:200])})
            continue
        population = {l.strip() for l in rp.stdout.splitlines() if l.strip()}
        covered = {l.strip() for l in rc.stdout.splitlines() if l.strip()}
        if not population:
            findings.append({"detector": "scope", "path": sid,
                             "detail": "population enumerated EMPTY; a scope "
                                       "diff over an empty population is "
                                       "vacuously clean"})
            continue
        for member in sorted(population - covered):
            if member in allow:
                continue
            findings.append({
                "detector": "scope", "path": sid, "member": member,
                "detail": "in the population, outside the declared scope"})
    return findings


# ------------------------------------------------------------- mechanism C

_SWALLOW_SH = re.compile(
    r"(?P<call>[^\s;|&]*\.(?:py|sh))(?P<args>[^|;#]*)"
    r"(?P<swallow>\|\|\s*true\b|2>\s*/dev/null|\|\|\s*:)")


def _exits_nonzero(path: Path):
    """Does this artifact actually carry a verdict?

    The filter that turns 1194 raw hits into a finding list. A discarded exit
    code only matters when the callee HAS one to discard.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return bool(re.search(r"sys\.exit\(\s*[1-9]|exit\s+[1-9]|"
                          r"raise\s+SystemExit\(\s*[1-9]", text))


def detect_swallow(root):
    findings = []
    for f in walk(root, suffixes=(".sh", ".yml", ".yaml")):
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or "blind-check-skip" in line:
                continue
            m = _SWALLOW_SH.search(line)
            if not m:
                continue
            callee = m.group("call").strip()
            cand = (root / callee.lstrip("./")) if not callee.startswith("/") else Path(callee)
            if not cand.is_file():
                # try a bare basename anywhere in the tree
                hits = [p for p in walk(root, suffixes=(".py", ".sh"))
                        if p.name == Path(callee).name]
                if len(hits) != 1:
                    continue
                cand = hits[0]
            if not _exits_nonzero(cand):
                continue
            findings.append({
                "detector": "swallow", "path": rel(root, f), "line": n,
                "member": rel(root, cand),
                "detail": "verdict-bearing callee, exit code discarded by "
                          + m.group("swallow").strip()})

    for f in walk(root, suffixes=(".py",)):
        try:
            src = f.read_text(errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        if "blind-check-skip" in src:
            continue
        # Walk Try nodes directly. Finding a handler's parent by re-parsing the
        # whole file once per handler was quadratic; the parent is right here.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not _runs_subprocess(node.body):
                continue
            for h in node.handlers:
                if len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                    findings.append({
                        "detector": "swallow", "path": rel(root, f),
                        "line": h.lineno, "member": "except: pass",
                        "detail": "handler discards the verdict of a subprocess "
                                  "call; a guard whose result is discarded is "
                                  "not a guard"})
    return findings


def _runs_subprocess(body):
    """True when this try: body actually runs a subprocess.

    The filter is the whole point. `except: pass` around ordinary code is
    usually a deliberate best-effort, and a detector that reports those gets
    switched off, which protects nothing.
    """
    for st in body:
        for sub in ast.walk(st):
            if isinstance(sub, ast.Attribute) and sub.attr in (
                    "run", "check_call", "check_output", "call", "Popen"):
                return True
    return False


# ------------------------------------------------------------- mechanism G

def _def_names(path: Path):
    try:
        src = path.read_text(errors="replace")
    except OSError:
        return set(), ""
    if path.suffix == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return set(), src
        return {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}, src
    return set(re.findall(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{",
                          src, re.M)), src


# Names every test file defines and no subject shares. Reporting these is
# reporting the test framework back at the reader.
_HARNESS_NAMES = frozenset({
    "main", "setup", "teardown", "run", "fail", "ok", "pass_", "assert_eq",
    "setUp", "tearDown", "fixture", "log", "die", "usage", "cleanup", "note",
    "skip", "warn", "info", "err", "banner", "have", "need", "require",
})


def detect_predcopy(root, subjects_index=None):
    """A test that DEFINES a function whose name also exists in its subject.

    The signature of mechanism G: the test hand-writes a copy of the rule it is
    checking, so both halves stay internally consistent while the real rule
    gains a condition the copy never learns about. Importing or extracting the
    subject's function has no such gap, because then there is only one copy.

    Deliberately imprecise, and the imprecision is one-directional: it reports
    a NAME COLLISION between a test's own definitions and its subject's, which
    is cheap to read and dismiss. It does not attempt to decide whether the two
    bodies agree -- that judgement is exactly the thing that fails silently.
    """
    findings = []
    if subjects_index is None:
        subjects_index = {}
        for p in walk(root, suffixes=(".py", ".sh")):
            if any(fnmatch.fnmatch(p.name, g) for g in TEST_GLOBS):
                continue
            names, _ = _def_names(p)
            for nm in names:
                subjects_index.setdefault(nm, []).append(p)

    for t in walk(root, globs=TEST_GLOBS):
        names, src = _def_names(t)
        if "blind-check-skip" in src:
            continue
        imported = set(re.findall(r"(?:^|\n)\s*(?:from|import)\s+([\w.]+)", src))
        for nm in sorted(names):
            if nm in _HARNESS_NAMES or nm.startswith("test") or len(nm) < 5:
                continue
            owners = subjects_index.get(nm, [])
            if not owners:
                continue
            # If the test imports the module that owns the name, it is probably
            # shadowing deliberately or the collision is incidental.
            owner_mods = {o.stem for o in owners}
            if owner_mods & {i.split(".")[-1] for i in imported}:
                continue
            findings.append({
                "detector": "predcopy", "path": rel(root, t), "member": nm,
                "detail": "test defines %s, also defined in %s -- a second copy "
                          "of the rule cannot see the first one change"
                          % (nm, ", ".join(sorted(rel(root, o) for o in owners[:3])))})
    return findings


# ----------------------------------------------------------------- reporting

DETECTORS = ("scope", "swallow", "predcopy")


def run_all(root, registry_path, only=None):
    out = {}
    if not only or "scope" in only:
        out["scope"] = detect_scope(root, registry_path)
    if not only or "swallow" in only:
        out["swallow"] = detect_swallow(root)
    if not only or "predcopy" in only:
        out["predcopy"] = detect_predcopy(root)
    return out


def print_findings(results):
    total = 0
    for det in DETECTORS:
        rows = results.get(det)
        if rows is None:
            continue
        # Flat, path-ordered. No ranking: see the module docstring.
        rows = sorted(rows, key=lambda r: (r.get("path", ""), r.get("line", 0),
                                           r.get("member", "")))
        print(f"\n=== {det}: {len(rows)} ===")
        for r in rows:
            loc = r.get("path", "")
            if r.get("line"):
                loc += f":{r['line']}"
            mem = r.get("member")
            print(f"  {loc}" + (f"  [{mem}]" if mem else ""))
            print(f"      {r['detail']}")
        total += len(rows)
    return total


def ratchet(results, baseline_path, write=False):
    """Ceiling, not cap. Growth fails; shrinkage tightens the baseline.

    Never truncates and never tolerates. The counts are the only thing stored:
    a baseline holding the findings themselves would go stale on every rename
    and teach everyone to regenerate it, which is how a ratchet becomes a
    rubber stamp.
    """
    counts = {d: len(results[d]) for d in results}
    bp = Path(baseline_path)
    try:
        base = json.loads(bp.read_text())["counts"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        bp.write_text(json.dumps({"schema": SCHEMA_VERSION, "counts": counts},
                                 indent=2, sort_keys=True) + "\n")
        print(f"RATCHET: baseline created at {counts}. Stage {bp}.")
        return 0
    rc = 0
    tightened = {}
    for det, n in sorted(counts.items()):
        allowed = base.get(det)
        if allowed is None:
            tightened[det] = n
            print(f"RATCHET: new detector {det} baselined at {n}")
            continue
        if n > allowed:
            print(f"RATCHET FAIL: {det} {allowed} -> {n} (+{n - allowed}). "
                  f"A new instance of this class was just added. Fix it, or "
                  f"mark the specific line with blind-check-skip and say why.",
                  file=sys.stderr)
            rc = 1
        elif n < allowed:
            tightened[det] = n
            print(f"RATCHET: tightened {det} {allowed} -> {n}")
        else:
            print(f"RATCHET PASS: {det} at {n}")
    if tightened and rc == 0:
        merged = dict(base)
        merged.update(tightened)
        merged.update({d: counts[d] for d in counts if d not in merged})
        bp.write_text(json.dumps({"schema": SCHEMA_VERSION, "counts": merged},
                                 indent=2, sort_keys=True) + "\n")
        print(f"RATCHET: baseline rewritten. Stage {bp} with this commit.")
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--only", action="append", choices=DETECTORS)
    ap.add_argument("--ratchet", action="store_true",
                    help="fail when any detector's count grows past the baseline")
    ap.add_argument("--cost", action="store_true",
                    help="print measured wall-clock and files walked")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                   capture_output=True, text=True
                                   ).stdout.strip() or ".").resolve()
    registry = Path(args.registry) if args.registry else (
        root / "q-system/.q-system/blind-check/scope-registry.json")
    baseline = Path(args.baseline) if args.baseline else (
        root / "q-system/.q-system/blind-check/blind-check-baseline.json")

    t0 = time.time()
    results = run_all(root, registry, args.only)
    elapsed = time.time() - t0

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        total = print_findings(results)
        print(f"\ntotal findings: {total}")
    if args.cost:
        walked = sum(1 for _ in walk(root, suffixes=(".py", ".sh", ".yml", ".yaml")))
        print(f"cost: {elapsed:.2f}s wall, {walked} files walked")

    if args.ratchet:
        sys.exit(ratchet(results, baseline))
    sys.exit(0)


if __name__ == "__main__":
    main()
