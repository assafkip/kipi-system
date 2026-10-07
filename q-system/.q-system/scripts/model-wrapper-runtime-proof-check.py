#!/usr/bin/env python3
"""model-wrapper-runtime-proof-check.py -- every model-calling WRAPPER needs a test
that proves it gated by running it (ASK-2540).

WHY. RCA token-burn-recurs-after-gate (2026-10-06), root cause #1: a wrapper was
counted gated because its source calls `model_gate.check`, but the check sat
below an early return the real caller always took. Source presence is not
coverage. The only accepted proof is a test that drives one call through the
wrapper with `voiceloop.gate_proof.prove()` / `assert_gated()`, which watches a
ledger row and a gate decision appear. This check lists every wrapper that has
no such test.

WHAT IS A WRAPPER. A module-level function or a method, outside test dirs, that
launches a model AND is imported by another non-test module (it is a door other
code walks through):
  * claude: its own AST, unparsed, matches voiceloop.call_sites.py_calls, the
    repo's one definition of a headless claude argv;
  * codex: an argv list naming a `codex` binary followed by `exec`;
  * SDK: a call to `<x>.messages.create(...)`, or `query(...)` / `ClaudeSDKClient`
    in a file importing claude_agent_sdk.
"Imported" means another module does `from <mod> import <func|Class>` or uses
`<alias>.<func>` on an alias bound to that module. A function reached only
through getattr or a string is not seen.

WHAT IS A PROOF. A green RECEIPT, never a parsed call. Test files holding a call
to `prove(...)` or `assert_gated(...)` with a constant `target=` are discovered by
AST (the registry is never a hand list), then this check RUNS each of them with
pytest, one file at a time, with KIPI_GATE_PROOF_RECEIPTS pointed at a temp file.
A wrapper is proven only when a file that PASSED left a receipt with ok=true
whose resolved code file is exactly that wrapper's file. A skipped, unreachable
or inverted test leaves no green receipt (PR #525 review: the first version
counted the call's presence, the sin the RCA names). A codex or SDK wrapper is
listed as `unprovable` rather than uncovered: gate_proof seals those providers
and proves claude wrappers only.

EXIT: 0 every claude wrapper proven, 1 at least one uncovered (the report lists them),
2 no root could be read, 3 an alert that was not delivered. This is a DAILY
fleet check (com.kipi.model-wrapper-runtime-proof-check.plist), not part of the
pytest collection, so a wrapper still waiting for its test cannot turn CI red.
Alerts go to slack-notify.sh (Sana's queue) on a STATE CHANGE only.

Test seams: --root (repeatable), --fleet, --state-dir, --no-alert, KIPI_ALERT_CMD.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "plugins" / "kipi-core"))
from voiceloop import call_sites as cs  # noqa: E402

_spec = importlib.util.spec_from_file_location("ffss", HERE / "fleet-full-suite-scan.py")
ffss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ffss)

PROOF_CALLS = {"prove", "assert_gated"}
#: One proof file is a handful of stubbed calls; ten minutes means it is hung.
PROOF_TIMEOUT_S = 600


def _is_test(rel: str) -> bool:
    return bool(cs._TEST_DIR.search(rel) or cs._SCRATCH.search(rel))


def _launch_kind(fn: ast.AST, sdk_file: bool) -> str | None:
    if cs.py_calls("# claude\n" + ast.unparse(fn)):
        return "claude"
    for node in ast.walk(fn):
        if isinstance(node, (ast.List, ast.Tuple)):
            strs = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if any(s == "codex" or s.endswith("/codex") for s in strs) and "exec" in strs:
                return "codex"
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "create" and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "messages"):
                return "sdk"
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if sdk_file and name in ("query", "ClaudeSDKClient"):
                return "sdk"
    return None


def _functions(tree: ast.Module):
    """(qualname, node) for module-level functions and methods of module-level classes."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{sub.name}", sub


def _imports(tree: ast.Module) -> tuple[set, set]:
    """({(module basename, name) imported by name}, {(module basename, attr) used via alias})."""
    named, aliases = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = (node.module or "").rsplit(".", 1)[-1]
            for a in node.names:
                if base:
                    named.add((base, a.name))
                # `from pkg import mod` binds a module alias too
                aliases[a.asname or a.name] = a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name.rsplit(".", 1)[-1]
                else:
                    aliases[a.name.split(".")[0]] = a.name.split(".")[0]
    # Hyphenated scripts cannot be imported by name; the fleet loads them with
    # spec_from_file_location(..., HERE / "x-y.py") then module_from_spec(spec).
    # Missing this shape hid every script-level wrapper from the population.
    specs = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call)):
            continue
        call, var = node.value, node.targets[0].id
        fname = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        if fname == "spec_from_file_location":
            for c in ast.walk(call):
                if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith(".py"):
                    specs[var] = Path(c.value).stem
        elif fname == "module_from_spec" and call.args and isinstance(call.args[0], ast.Name) \
                and call.args[0].id in specs:
            aliases[var] = specs[call.args[0].id]
    attrs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            attrs.add((aliases[node.value.id], node.attr))
        # `import a.b.mod` then `a.b.mod.func`: the attribute's owner is the dotted chain
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            attrs.add((node.value.attr, node.attr))
    return named, attrs


def _run_proofs(top: Path, files: list) -> list:
    """Run each proof test file; return green receipts from files that passed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.pop("PYTEST_CURRENT_TEST", None)
    green = []
    with tempfile.TemporaryDirectory(prefix="gate-proof-receipts-") as tmp:
        for i, rel in enumerate(sorted(files)):
            receipts = os.path.join(tmp, f"{i}.jsonl")
            env["KIPI_GATE_PROOF_RECEIPTS"] = receipts
            try:
                rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", rel],
                                    cwd=top, env=env, capture_output=True, text=True,
                                    timeout=PROOF_TIMEOUT_S).returncode
            except subprocess.TimeoutExpired:
                continue
            if rc != 0:
                continue  # a failing file's receipts prove nothing
            try:
                with open(receipts, encoding="utf-8") as fh:
                    rows = [json.loads(ln) for ln in fh if ln.strip()]
            except (OSError, ValueError):
                rows = []
            green += [{**r, "test": rel} for r in rows if r.get("ok") is True]
    return green


def _proof_targets(tree: ast.Module) -> set:
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        if name not in PROOF_CALLS:
            continue
        for kw in node.keywords:
            if kw.arg == "target" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                out.add(kw.value.value)
    return out


def scan_root(top: Path) -> dict:
    """{"wrappers": [{path, qualname, kind}], "targets": [...]} for one checkout."""
    parsed = {}
    for rel in cs.tracked(top):
        if not rel.endswith(".py"):
            continue
        try:
            parsed[rel] = ast.parse((top / rel).read_text(errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
    targets, imported, proof_files = set(), {}, []
    for rel, tree in parsed.items():
        if _is_test(rel):
            found = _proof_targets(tree)
            targets |= found
            if found:
                proof_files.append(rel)
        else:
            imported[rel] = _imports(tree)
    wrappers = []
    for rel, tree in parsed.items():
        if _is_test(rel):
            continue
        src = ast.unparse(tree)
        sdk_file = "claude_agent_sdk" in src
        base = Path(rel).stem
        for qual, fn in _functions(tree):
            kind = _launch_kind(fn, sdk_file)
            if not kind:
                continue
            head = qual.split(".")[0]
            used = any((base, head) in named or (base, head) in attrs
                       for other, (named, attrs) in imported.items() if other != rel)
            if used:
                wrappers.append({"path": rel, "qualname": qual, "kind": kind})
    receipts = _run_proofs(top, proof_files) if wrappers and proof_files else []
    return {"wrappers": wrappers, "targets": sorted(targets), "receipts": receipts}


def covered(top: Path, wrapper: dict, receipts) -> bool:
    # Exact resolved file, not a path suffix: a vendored copy at another path with
    # the same module tail is a different wrapper (PR #525 review finding 3).
    path = os.path.realpath(top / wrapper["path"])
    return any(r.get("file") == path and r.get("qualname") == wrapper["qualname"] for r in receipts)


def check(roots: list[Path]) -> dict:
    scans, errors = {}, []
    for top in roots:
        try:
            scans[str(top)] = scan_root(top)
        except RuntimeError as exc:
            errors.append({"checkout": str(top), "error": str(exc)[:200]})
    targets = sorted({t for s in scans.values() for t in s["targets"]})
    receipts = [r for s in scans.values() for r in s["receipts"]]
    uncovered, proven, unprovable = [], [], []
    for top, s in scans.items():
        for w in s["wrappers"]:
            row = {"checkout": top, **w}
            if w["kind"] != "claude":
                unprovable.append(row)
            elif covered(Path(top), w, receipts):
                proven.append(row)
            else:
                uncovered.append(row)
    return {"checkouts": len(scans), "uncovered": uncovered, "proven": proven,
            "unprovable": unprovable, "targets": targets, "receipts": receipts, "errors": errors}


def fingerprint(report: dict) -> str:
    keys = sorted(f"{u['checkout']}|{u['path']}:{u['qualname']}" for u in report["uncovered"])
    keys += sorted(f"error|{e['checkout']}" for e in report["errors"])
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", action="append", default=[], help="a checkout to scan (repeatable)")
    ap.add_argument("--fleet", action="store_true", help="scan every local checkout the fleet scans use")
    ap.add_argument("--registry", default="")
    ap.add_argument("--projects-root", default="")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--no-alert", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    home = Path(os.path.expanduser("~"))
    roots = [Path(r) for r in a.root]
    if a.fleet:
        registry = Path(a.registry) if a.registry else ROOT / "instance-registry.json"
        projects = Path(a.projects_root) if a.projects_root else home / "projects"
        roots += ffss.local_checkouts(registry, projects)
    if not roots:
        roots = [ROOT]
    report = check(roots)
    if not report["checkouts"]:
        print("model-wrapper-runtime-proof-check: no checkout could be read; refusing to report zero",
              file=sys.stderr)
        return 2
    report["fingerprint"] = fingerprint(report)
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"checkouts {report['checkouts']}  wrappers {len(report['uncovered']) + len(report['proven'])}  "
              f"proven {len(report['proven'])}  uncovered {len(report['uncovered'])}  "
              f"errors {len(report['errors'])}")
        for u in report["uncovered"]:
            print(f"  UNCOVERED {u['checkout']}  {u['path']}:{u['qualname']}  ({u['kind']})")
        for p in report["unprovable"]:
            print(f"  unprovable {p['checkout']}  {p['path']}:{p['qualname']}  "
                  f"({p['kind']}: gate_proof proves claude only)")
        for p in report["proven"]:
            print(f"  proven    {p['checkout']}  {p['path']}:{p['qualname']}")
        if report["uncovered"]:
            print("  fix: a test calling voiceloop.gate_proof.assert_gated(lambda claude_bin: <one call>, "
                  "target=\"<module>:<qualname>\")")
    if not a.no_alert:
        state_dir = Path(a.state_dir) if a.state_dir else home / ".config" / "kipi" / "model-wrapper-runtime-proof"
        prev = ffss.read_state(state_dir)
        if (prev or {}).get("fingerprint") != report["fingerprint"]:
            was = len(prev.get("uncovered", [])) if prev else "unknown"
            line = (f"model-wrapper-runtime-proof-check: {len(report['uncovered'])} model-calling wrappers "
                    f"have no runtime gate proof (was {was}); run "
                    f"model-wrapper-runtime-proof-check.py --fleet for the list")
            if not ffss.alert(line):
                print("model-wrapper-runtime-proof-check: alert not delivered; state left unchanged",
                      file=sys.stderr)
                return 3
        ffss.write_state(state_dir, report)
    return 1 if report["uncovered"] else 0


if __name__ == "__main__":
    sys.exit(main())
