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

Read-only, and never a gate in the PER-INSTANCE check suite. The fleet is the
wrong venue: this script's subject is skeleton-owned code, and the updater does
not preserve plugins/, verify-bus.py or agent-pipeline/agents/ in an instance,
so an instance cannot fix anything reported here -- a local edit is erased on
the next sync. A gate its population cannot satisfy gets switched off.

It IS intended to gate the skeleton's own validate workflow, where the party
who can fix a finding is the party the gate stops. That arming rides ASK-874's
fix, because the script exits 1 today and a gate nobody can pass blocks the
very PR that would make it pass. Until then it is declared inert on purpose.

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


WRITE_VERB = re.compile(r"write|written|merge into|save|output to|emit|append|store", re.I)


def extract_producers(agent_text: str) -> tuple[set[str], set[str]]:
    """Return (produced, mentioned) from agent prompt text.

    A FUNCTION and not inline in main() so the self-test can drive it. Codex
    PR #202 round 2: the deleted-writer mutant fed `produced`/`mentioned`
    straight into find_drift, so reverting this split left the self-test green.
    A green test over the pure rule proves nothing about the code that BUILDS
    its inputs -- the same could-not-fire class this whole issue is about.

    Two writer conventions, and either one alone is wrong. Most agents write a
    {{BUS_DIR}}-qualified path; some bus files come from a SCRIPT the
    orchestrator shells out to, described as "writes X.json" (compliance.json,
    via compliance-check.py). Matching every *.json instead over-claimed,
    calling settings.json a bus artifact.

    Per LINE, so a write verb only credits names on its own line: agents both
    `Read {{BUS_DIR}}/calendar.json` and `Write log to {{BUS_DIR}}/x.json`.
    """
    produced: set[str] = set()
    mentioned: set[str] = set()
    for line in agent_text.splitlines():
        names = {m.rsplit("/", 1)[-1]
                 for m in re.findall(r"\{\{BUS_DIR\}\}/[A-Za-z0-9._-]+\.json", line)}
        names |= set(re.findall(r"writes\s+([A-Za-z0-9._-]+\.json)", line))
        mentioned |= names
        if WRITE_VERB.search(line):
            produced |= names
    return produced, mentioned


# ------------------------------------------------------------- the drift rules
# Pure function over already-extracted sets, so --self-test can drive it with
# synthetic input. A checker that can only run against the live tree cannot be
# shown to go red for the reason you think it does.

def find_drift(bridge: set[str], mcp: dict, vbus: dict,
               schemas: set[str], produced: set[str],
               mentioned: set[str] | None = None,
               day_rules: dict | None = None) -> list[dict]:
    """`produced` = a WRITE was found. `mentioned` = the name appears at all.

    Codex PR #202 (major): keying the producer classes on mere mention treated
    every read as a write, so deleting a real writer left
    required-without-producer silent as long as some agent still READ the file.
    Agents both `Read {{BUS_DIR}}/calendar.json` and `Write log to
    {{BUS_DIR}}/daily-checklists.json`, so the two facts are separate inputs.
    """
    if mentioned is None:
        mentioned = produced
    day_rules = day_rules or {}
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
                    "detail": f"{label} phase {phase} requires {f}, but no agent prompt "
                              f"shows a WRITE of it - phase cannot pass",
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

    # D3b - a file promoted to REQUIRED only on certain weekdays. Both verifiers
    # move tl-content.json from optional to required on Tue/Thu at phase 4, at
    # RUNTIME, so a reader of the static spec never sees it as required (Codex
    # PR #202 round 3, major). tl-content.json has no producer, so phase 4
    # cannot pass two days a week and the static read reported nothing. A
    # conditional requirement is still a requirement.
    for day, phases in sorted(day_rules.items()):
        for phase, files in sorted(phases.items()):
            for f in sorted(set(files) - produced):
                findings.append({
                    "class": "required-without-producer",
                    "detail": f"day-rule {day} phase {phase} promotes {f} to required, "
                              f"but no agent prompt shows a WRITE of it - "
                              f"phase cannot pass on {day}s",
                })

    # D6 - a bus artifact the agents reference that neither map knows about.
    # Codex PR #199: the candidate set used to be (bridge | verifier), so this
    # direction was invisible. Keyed on MENTION, and says so: proving a write
    # from prose is not reliable, and the class does not need it to be useful.
    for f in sorted(mentioned - bridge - verifier_all):
        findings.append({
            "class": "unmapped-artifact",
            "detail": f"agent prompts reference {f}, but no verifier and no bridge entry knows it",
        })

    # D7 - a schema with no consumer on any map. Same blind spot, other end.
    for f in sorted(schemas - bridge - verifier_all - mentioned):
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
        "unmapped-artifact": dict(clean, mentioned={"a.json", "p.json"}),
        # The deleted-writer case: still READ (so mentioned), no longer written.
        # This is the mutant that was silent before the write/mention split.
        "required-without-producer-when-only-read": dict(
            clean, produced=set(), mentioned={"a.json"}),
        "schema-only": dict(clean, schemas={"a.json", "y.json"}),
        # Day-promoted requirement with no writer. Silent before round 3.
        "required-without-producer-when-day-promoted": dict(
            clean, day_rules={"tuesday": {"4": ["d.json"]}}),
        }
    for name, kwargs in cases.items():
        # The mutant NAME may describe a scenario; the class it must emit is the
        # name up to the first "-when-". Asserting a specific class matters: an
        # assertion that accepts "any finding" passes for the wrong reason.
        want = name.split("-when-")[0]
        classes = {f["class"] for f in find_drift(**kwargs)}
        if want not in classes:
            print(f"SELF-TEST FAIL: mutant {name!r} did not emit {want!r} (got {classes or 'none'})")
            return 1
        print(f"  ok  {name}: caught")

    # Drive the REAL extractor over real agent-prompt phrasing. Without this the
    # write/read split could be reverted with every case above still green,
    # because they hand find_drift its inputs directly (Codex PR #202 round 2).
    sample = (
        "1. Read `{{BUS_DIR}}/reader-only.json` and parse it\n"
        "2. Write results to {{BUS_DIR}}/written.json\n"
        "3. Run the script - writes script-made.json\n"
        "4. Update settings.json with the new key\n"
    )
    got_produced, got_mentioned = extract_producers(sample)
    for label, actual, expected in (
        ("produced", got_produced, {"written.json", "script-made.json"}),
        ("mentioned", got_mentioned, {"reader-only.json", "written.json", "script-made.json"}),
    ):
        if actual != expected:
            print(f"SELF-TEST FAIL: extractor {label} was {sorted(actual)}, "
                  f"expected {sorted(expected)}")
            return 1
    print("  ok  extractor: read-only line is mentioned but NOT produced; "
          "settings.json ignored")

    print(f"SELF-TEST PASS: clean input is silent, all {len(cases)} mutants caught, "
          "extractor verified.")
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

    # Not every schema in this directory describes a BUS file. schedule-data is
    # written to {{QROOT}}/output/schedule-data-{{DATE}}.json by 07-synthesize,
    # so it has no bus entry by design and flagging it was a false alarm on every
    # run (Codex PR #202, major). An alert that is wrong every time trains the
    # reader to skip the whole report.
    NON_BUS_SCHEMAS = {"schedule-data.json"}
    schemas = ({p.name.replace(".schema.json", ".json") for p in SCHEMA_DIR.glob("*.schema.json")
                if not p.name.startswith("_")} - NON_BUS_SCHEMAS) if SCHEMA_DIR.is_dir() else set()

    agent_text = "\n".join(p.read_text(errors="ignore") for p in AGENT_DIR.glob("*.md")) \
        if AGENT_DIR.is_dir() else ""
    produced, mentioned = extract_producers(agent_text)

    cadence = AGENT_DIR / "_cadence-config.json"
    try:
        day_rules = json.loads(cadence.read_text()).get("day_rules", {}) if cadence.is_file() else {}
    except (OSError, json.JSONDecodeError):
        day_rules = {}

    findings = find_drift(bridge, mcp, vbus, schemas, produced, mentioned, day_rules)

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
