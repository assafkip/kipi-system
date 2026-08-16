#!/usr/bin/env python3
"""Enumerate bus-filename vocabulary drift across the copies that hand-maintain it.

Pairs with the architecture-review finding on the bus protocol (ASK-871).

WHY THIS SHAPE (scar, 2026-08-16): the bus protocol's filename vocabulary is
hand-maintained in four independent places. An architecture pass called this a
future drift RISK. It is not a risk; measuring it showed the drift had already
happened and no test could see it:

  - `verify-bus.py` requires `crm.json` at phase 1 while the MCP `bus_verifier`
    requires `notion.json` for the same phase. Two live verifiers, two names.
  - Both copies register a structure check for `canonical-digest.json` on a
    phase where that file is in neither `required` nor `optional`, so the check
    loop never reaches it. It reads as protection and can never fire.
  - `energy.json` is `required` at phase 0 and NO agent produces it. Phase 0
    cannot pass on a real run. The suite is green only because the test writes
    `energy.json` itself, so the fixture manufactures the file the pipeline
    never creates.

So the deliberate design choice here is a READER, not a single source of truth.
Collapsing the four copies into one manifest was the obvious fix and it is the
wrong one: `_phase_specs` carries lambdas (not JSON-serializable) and phase
grouping, `BUS_TO_STEPS` carries step-id fanout, and the schemas carry
structure. They are three different relations that happen to share a filename
vocabulary. Unifying them is a refactor of live morning-pipeline infra to buy
consistency in the one dimension a reader can check for free.

Read-only. Never a blocking gate: this script ships to every instance via
`kipi update`, and a hard block here would land on all of them at once.

Usage:
  python3 q-system/.q-system/scripts/bus-vocabulary-drift.py
  python3 q-system/.q-system/scripts/bus-vocabulary-drift.py --self-test

Exit 0 = no drift, 1 = drift found, 2 = a source could not be parsed.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QROOT = Path(__file__).resolve().parent.parent.parent
REPO = QROOT.parent

BRIDGE_PY = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_bridge.py"
MCP_VERIFIER_PY = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_verifier.py"
VERIFY_BUS_PY = QROOT / ".q-system/verify-bus.py"
SCHEMA_DIR = QROOT / ".q-system/agent-pipeline/schemas"
AGENT_DIR = QROOT / ".q-system/agent-pipeline/agents"


# ---------------------------------------------------------------- AST readers
# AST, not import: verify-bus.py runs argument parsing at module scope and the
# spec dicts hold lambdas. Parsing is the only way to read all copies the same
# way without executing any of them.

def _dict_literal_keys(node: ast.Dict) -> dict:
    """Return {phase_int: {"required": [...], "optional": [...], "checks": [...]}}."""
    out = {}
    for k, v in zip(node.keys, node.values):
        if not isinstance(k, ast.Constant) or not isinstance(v, ast.Dict):
            continue
        entry = {"required": [], "optional": [], "checks": []}
        for sk, sv in zip(v.keys, v.values):
            if not isinstance(sk, ast.Constant):
                continue
            name = sk.value
            if name in ("required", "optional") and isinstance(sv, ast.List):
                entry[name] = [e.value for e in sv.elts if isinstance(e, ast.Constant)]
            elif name == "checks" and isinstance(sv, ast.Dict):
                entry["checks"] = [
                    e.value for e in sv.keys if isinstance(e, ast.Constant)
                ]
        out[k.value] = entry
    return out


def read_phase_specs(path: Path, func_name: str | None, var_name: str | None) -> dict:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if func_name and isinstance(node, ast.FunctionDef) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    return _dict_literal_keys(sub.value)
        if var_name and isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name and isinstance(node.value, ast.Dict):
                    return _dict_literal_keys(node.value)
    raise ValueError(f"could not locate phase specs in {path}")


def read_bridge_map(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "BUS_TO_STEPS" and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "BUS_TO_STEPS":
                    return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise ValueError(f"could not locate BUS_TO_STEPS in {path}")


def _files(spec: dict) -> set[str]:
    return {f for e in spec.values() for f in e["required"] + e["optional"]}


# ------------------------------------------------------------- the drift rules
# Pure function over already-extracted sets, so --self-test can drive it with
# synthetic input. A checker that can only run against the live tree cannot be
# shown to go red for the reason you think it does.

def find_drift(bridge: set[str], mcp: dict, vbus: dict,
               schemas: set[str], produced: set[str]) -> list[dict]:
    findings: list[dict] = []

    # D1 - a structure check registered for a file the loop never visits.
    for label, spec in (("mcp:bus_verifier", mcp), ("verify-bus.py", vbus)):
        for phase, entry in sorted(spec.items()):
            live = set(entry["required"]) | set(entry["optional"])
            for dead in sorted(set(entry["checks"]) - live):
                findings.append({
                    "class": "dead-check",
                    "detail": f"{label} phase {phase}: check registered for {dead}, "
                              f"but it is in neither required nor optional - can never fire",
                })

    # D2 - the two live verifiers disagree about the same phase.
    for phase in sorted(set(mcp) & set(vbus)):
        for kind in ("required", "optional"):
            a, b = set(mcp[phase][kind]), set(vbus[phase][kind])
            if a != b:
                findings.append({
                    "class": "verifier-disagreement",
                    "detail": f"phase {phase} {kind}: mcp={sorted(a - b) or '-'} "
                              f"only, verify-bus={sorted(b - a) or '-'} only",
                })

    # D3 - a file a verifier REQUIRES that no agent produces (unsatisfiable).
    for label, spec in (("mcp:bus_verifier", mcp), ("verify-bus.py", vbus)):
        for phase, entry in sorted(spec.items()):
            for f in sorted(set(entry["required"]) - produced):
                findings.append({
                    "class": "required-without-producer",
                    "detail": f"{label} phase {phase} requires {f}, "
                              f"but no agent prompt names it - phase cannot pass",
                })

    # D4 - bridge and verifier vocabularies diverge.
    verifier_all = _files(mcp) | _files(vbus)
    for f in sorted(bridge - verifier_all):
        findings.append({"class": "bridge-only",
                         "detail": f"{f} is mapped to morning-log steps but no verifier knows it"})
    for f in sorted(verifier_all - bridge):
        findings.append({"class": "verifier-only",
                         "detail": f"{f} is verified but never bridged into the morning-log"})

    # D5 - informational: bus file with no schema.
    for f in sorted((bridge | verifier_all) - schemas):
        findings.append({"class": "no-schema", "detail": f"{f} has no JSON schema"})

    # D6 - a file an agent WRITES that neither map knows about.
    # Codex PR #199: the candidate set used to be (bridge | verifier), so a
    # producer-only artifact was invisible to every rule above - the scanner
    # could not report the one direction that has a real writer behind it.
    for f in sorted(produced - bridge - verifier_all):
        findings.append({
            "class": "producer-only",
            "detail": f"an agent writes {f}, but no verifier and no bridge entry knows it",
        })

    # D7 - a schema with no consumer on any map. Same blind spot, other end.
    for f in sorted(schemas - bridge - verifier_all - produced):
        findings.append({
            "class": "schema-only",
            "detail": f"{f} has a schema but no producer, verifier or bridge entry",
        })

    return findings


# ------------------------------------------------------------------ self-test
def self_test() -> int:
    """Negative control: the checker must go green on agreement AND red on drift."""
    clean = dict(
        bridge={"a.json"},
        mcp={0: {"required": ["a.json"], "optional": [], "checks": ["a.json"]}},
        vbus={0: {"required": ["a.json"], "optional": [], "checks": ["a.json"]}},
        schemas={"a.json"},
        produced={"a.json"},
    )
    got = find_drift(**clean)
    if got:
        print("SELF-TEST FAIL: clean input produced findings:", got)
        return 1

    # One mutant per drift class. Codex PR #199 caught that this set covered only
    # 4 of the classes, so deleting the no-schema or verifier-only branch left the
    # self-test green - a detector that never fires reads exactly like one that
    # works. Every class find_drift can emit MUST have a mutant here.
    cases = {
        "dead-check": dict(clean, mcp={0: {"required": [], "optional": [], "checks": ["a.json"]}},
                           vbus={0: {"required": [], "optional": [], "checks": []}}),
        "verifier-disagreement": dict(clean, vbus={0: {"required": ["b.json"], "optional": [], "checks": []}},
                                      produced={"a.json", "b.json"}, schemas={"a.json", "b.json"},
                                      bridge={"a.json", "b.json"}),
        "required-without-producer": dict(clean, produced=set()),
        "bridge-only": dict(clean, bridge={"a.json", "z.json"}, schemas={"a.json", "z.json"}),
        "verifier-only": dict(clean,
                              mcp={0: {"required": ["a.json", "b.json"], "optional": [], "checks": []}},
                              vbus={0: {"required": ["a.json", "b.json"], "optional": [], "checks": []}},
                              schemas={"a.json", "b.json"}, produced={"a.json", "b.json"}),
        "no-schema": dict(clean, schemas=set()),
        "producer-only": dict(clean, produced={"a.json", "p.json"}),
        "schema-only": dict(clean, schemas={"a.json", "y.json"}),
    }
    for want, kwargs in cases.items():
        classes = {f["class"] for f in find_drift(**kwargs)}
        if want not in classes:
            print(f"SELF-TEST FAIL: mutant for {want!r} was not caught (got {classes or 'none'})")
            return 1
        print(f"  ok  {want}: caught")

    print(f"SELF-TEST PASS: clean input is silent, all {len(cases)} mutants caught.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true",
                    help="prove the checker goes green on agreement and red on each drift class")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    try:
        bridge = read_bridge_map(BRIDGE_PY)
        mcp = read_phase_specs(MCP_VERIFIER_PY, "_phase_specs", None)
        vbus = read_phase_specs(VERIFY_BUS_PY, None, "phase_files")
    except (OSError, ValueError, SyntaxError) as e:
        print(f"bus-vocabulary-drift: cannot read a source: {e}", file=sys.stderr)
        return 2

    schemas = {p.name.replace(".schema.json", ".json") for p in SCHEMA_DIR.glob("*.schema.json")
               if not p.name.startswith("_")} if SCHEMA_DIR.is_dir() else set()

    agent_text = "\n".join(p.read_text(errors="ignore") for p in AGENT_DIR.glob("*.md")) \
        if AGENT_DIR.is_dir() else ""
    # Match the agents' own convention for a bus artifact: a {{BUS_DIR}}-qualified
    # path. Two earlier shapes were both wrong. Deriving the candidates from
    # (bridge | verifier) made producer-only structurally unable to fire, since a
    # file no map lists could never enter the set - green self-test, dead in
    # production. Widening to every *.json in the prompts then over-claimed,
    # reporting settings.json and morning-log.json as bus artifacts an agent
    # "writes". "An agent writes X" is a strong claim, so it is keyed on the
    # qualified path and nothing looser.
    # Two writer conventions, and keying on either one alone is wrong. Most
    # agents write a {{BUS_DIR}}-qualified path, but some bus files are produced
    # by a SCRIPT the orchestrator shells out to, described as "writes X.json"
    # (compliance.json comes from compliance-check.py that way). Keying on the
    # qualified path alone reported compliance.json as having no producer, which
    # is simply false - and a checker that states a false thing is worse than no
    # checker, because someone will act on it.
    produced = {m.rsplit("/", 1)[-1]
                for m in re.findall(r"\{\{BUS_DIR\}\}/[A-Za-z0-9._-]+\.json", agent_text)}
    produced |= set(re.findall(r"writes\s+([A-Za-z0-9._-]+\.json)", agent_text))

    findings = find_drift(bridge, mcp, vbus, schemas, produced)

    if args.json:
        print(json.dumps({"findings": findings, "count": len(findings)}, indent=2))
    else:
        by_class: dict[str, list[str]] = {}
        for f in findings:
            by_class.setdefault(f["class"], []).append(f["detail"])
        for cls, items in by_class.items():
            print(f"\n[{cls}] {len(items)}")
            for d in items:
                print(f"  - {d}")
        print(f"\nTOTAL: {len(findings)} finding(s) across "
              f"{len(bridge | _files(mcp) | _files(vbus))} bus filenames.")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
