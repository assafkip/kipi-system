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

PRODUCERS ARE THE ONE EXCEPTION, AND ASK-885 IS WHY. "Which bus files does
anything actually produce" used to be INFERRED from agent prompt prose, and five
successive definitions of "produced" were each wrong in a different direction
(map membership; every *.json; {{BUS_DIR}}-qualified only; {{BUS_DIR}} plus a
write verb, which counted READS as writes; the union with a `## Writes` section,
which read a prohibited q-system/memory/ write as a bus artifact). PR #202 was
closed after six review rounds each finding a defect of that same class. Prose
has no schema to check you. So producers now come from ONE declared file,
`agent-pipeline/bus-producers.json`, and from nothing else. There is deliberately
no write-verb regex left in this script; if you are about to add one back, that
is the regression this file exists to prevent.

Read-only, and never a gate in the PER-INSTANCE check suite. The fleet is the
wrong venue: this script's subject is skeleton-owned code, and the updater does
not preserve plugins/, verify-bus.py or agent-pipeline/agents/ in an instance,
so an instance cannot fix anything reported here -- a local edit is erased on
the next sync. A gate its population cannot satisfy gets switched off.

Usage:
  python3 q-system/.q-system/scripts/bus-vocabulary-drift.py
  python3 q-system/.q-system/scripts/bus-vocabulary-drift.py --self-test

Exit 0 = no drift, 1 = drift found, 2 = a source could not be parsed.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

QROOT = Path(__file__).resolve().parent.parent.parent
REPO = QROOT.parent

BRIDGE_PY = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_bridge.py"
MCP_VERIFIER_PY = REPO / "plugins/kipi-core/kipi-mcp/src/kipi_mcp/bus_verifier.py"
VERIFY_BUS_PY = QROOT / ".q-system/verify-bus.py"
SCHEMA_DIR = QROOT / ".q-system/agent-pipeline/schemas"
AGENT_DIR = QROOT / ".q-system/agent-pipeline/agents"
PRODUCERS_JSON = QROOT / ".q-system/agent-pipeline/bus-producers.json"


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


# ------------------------------------------------------- the declared producers
# THE one source. No prose, no heuristic, no second opinion. See the module
# docstring for the five inference definitions this replaced and why each failed.

def read_declared_producers(path: Path) -> tuple[set[str], list[tuple[str, str]]]:
    """Return (declared bus filenames, [(bus_file, repo-relative source path)]).

    The second element exists so the manifest can be CHECKED rather than
    trusted: a declaration naming a source file that is not on disk is drift of
    exactly the kind this script reports about everything else, and a manifest
    nobody validates is prose in a .json hat.

    Keys beginning with `_` are documentation blocks, not producers. Raises
    ValueError on a malformed manifest so a typo surfaces as exit 2 rather than
    as a silently empty producer set -- an empty set would make every required
    file look unproduced, which is a false-positive flood, not a quiet failure.
    """
    data = json.loads(path.read_text())
    producers = data.get("producers")
    if not isinstance(producers, dict):
        raise ValueError(f"{path}: 'producers' must be an object")

    names: set[str] = set()
    sources: list[tuple[str, str]] = []
    for bus_file, entries in producers.items():
        if bus_file.startswith("_"):
            continue
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{path}: producers[{bus_file!r}] must be a non-empty list")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("kind") not in ("agent", "script"):
                raise ValueError(f"{path}: producers[{bus_file!r}] entry needs kind agent|script")
            source = entry.get("source")
            if not isinstance(source, str) or not source:
                raise ValueError(f"{path}: producers[{bus_file!r}] entry needs a source path")
            sources.append((bus_file, source))
        names.add(bus_file)
    return names, sources


# --------------------------------------------------------- day-rule promotions
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"}


def _day_promotion_test(test: ast.expr) -> tuple[int | None, list[str]]:
    """Read `phase == N and <day> in ("tuesday", ...)` into (N, [days])."""
    phase, days = None, []
    parts = (test.values if isinstance(test, ast.BoolOp)
             and isinstance(test.op, ast.And) else [test])
    for part in parts:
        if not isinstance(part, ast.Compare) or len(part.ops) != 1:
            continue
        op, comp = part.ops[0], part.comparators[0]
        if (isinstance(op, ast.Eq) and isinstance(comp, ast.Constant)
                and isinstance(comp.value, int) and not isinstance(comp.value, bool)):
            phase = comp.value
        elif isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List)):
            days = [e.value.lower() for e in comp.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    and e.value.lower() in WEEKDAYS]
        elif (isinstance(op, ast.Eq) and isinstance(comp, ast.Constant)
                and isinstance(comp.value, str) and comp.value.lower() in WEEKDAYS):
            days = [comp.value.lower()]
    return phase, days


def read_hardcoded_day_rules(path: Path) -> dict:
    """Extract day-of-week promotions written as LITERALS in a verifier's source.

    WHY (scar, ASK-874 PR #202 round 4): round 3 taught the detector to read
    `day_rules` from `_cadence-config.json` and called that the declared source
    of truth. It is not the only one. The MCP `bus_verifier` never opens that
    config at all -- it hardcodes `phase == 4 and day_name in ("tuesday",
    "thursday")` -- and `verify-bus.py` keeps the same literal as its fallback
    for when the config is missing. Measured on a copy: delete `day_rules` from
    the config and the detector reports NO day-rule finding while both verifiers
    still promote tl-content.json at runtime. Reading one of three sources is
    how a checker reports GREEN on an unsatisfiable phase.

    Reachability is deliberately NOT considered: a literal a verifier can act on
    is a requirement the detector must model, fallback branch included.
    """
    rules: dict = {}
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.If):
            continue
        phase, days = _day_promotion_test(node.test)
        if phase is None or not days:
            continue
        files = sorted({
            c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
            and c.value.endswith(".json")
        })
        for day in days:
            bucket = rules.setdefault(day, {}).setdefault(str(phase), [])
            bucket.extend(f for f in files if f not in bucket)
    return rules


def merge_day_rules(*sources: dict) -> dict:
    """Union day->phase->files across every source that can promote at runtime."""
    merged: dict = {}
    for src in sources:
        for day, phases in (src or {}).items():
            for phase, files in (phases or {}).items():
                bucket = merged.setdefault(str(day).lower(), {}).setdefault(str(phase), [])
                bucket.extend(f for f in files if f not in bucket)
    return merged


# ------------------------------------------------------------- the drift rules
# Pure function over already-extracted sets, so --self-test can drive it with
# synthetic input. A checker that can only run against the live tree cannot be
# shown to go red for the reason you think it does.

def find_drift(bridge: set[str], mcp: dict, vbus: dict,
               schemas: set[str], produced: set[str],
               *, day_rules: dict, producer_sources: list[tuple[str, str]],
               source_exists) -> list[dict]:
    """`produced` = the set declared in bus-producers.json. Nothing infers it.

    `day_rules` and `producer_sources`/`source_exists` are keyword-ONLY with no
    defaults on purpose (ASK-874 round 4). `day_rules` used to default to `{}`,
    so a caller that forgot it got a detector that silently skipped D3b and
    reported GREEN on a phase that cannot pass -- the reviewer's own reproducer
    did exactly that. A missing argument is now a loud TypeError instead of a
    quiet false negative, and the same reasoning applies to the manifest check.
    """
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

    # D3 - a file a verifier REQUIRES that bus-producers.json does not declare.
    for label, spec in (("mcp:bus_verifier", mcp), ("verify-bus.py", vbus)):
        for phase, entry in sorted(spec.items()):
            for f in sorted(set(entry["required"]) - produced):
                findings.append({
                    "class": "required-without-producer",
                    "detail": f"{label} phase {phase} requires {f}, but bus-producers.json "
                              f"declares no producer for it - phase cannot pass",
                })

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
                    "detail": f"day-rule {day} phase {phase} promotes {f} to required, but "
                              f"bus-producers.json declares no producer for it - "
                              f"phase cannot pass on {day}s",
                })

    # D4 - bridge and verifier vocabularies diverge.
    # A day-rule file IS known to a verifier, just conditionally. Leaving these
    # out made the verifier-only rule call content-intel.json "unknown" while
    # verify-bus requires it every Monday - the detector contradicting data it
    # had already loaded (Codex PR #202 round 4).
    day_rule_files = {f for phases in day_rules.values()
                      for files in phases.values() for f in files}
    verifier_all = _files(mcp) | _files(vbus) | day_rule_files
    for f in sorted(bridge - verifier_all):
        findings.append({"class": "bridge-only",
                         "detail": f"{f} is mapped to morning-log steps but no verifier knows it"})
    for f in sorted(verifier_all - bridge):
        findings.append({"class": "verifier-only",
                         "detail": f"{f} is verified but never bridged into the morning-log"})

    # D5 - informational: bus file with no schema.
    for f in sorted((bridge | verifier_all) - schemas):
        findings.append({"class": "no-schema", "detail": f"{f} has no JSON schema"})

    # D8 - the manifest declares a producer whose source file is not on disk.
    # This is what keeps the declared source honest. Without it, moving or
    # deleting an agent leaves a producer declaration standing and the detector
    # reports GREEN on a bus file nothing writes any more - the same could-not-
    # fire class the inference era kept producing, relocated into the fix.
    for bus_file, source in sorted(set(producer_sources)):
        if not source_exists(source):
            findings.append({
                "class": "producer-source-missing",
                "detail": f"bus-producers.json declares {source} as a producer of "
                          f"{bus_file}, but that file does not exist",
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
        day_rules={},
        producer_sources=[("a.json", "agents/a.md")],
        source_exists=lambda s: True,
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
        # Day-promoted requirement with no declared producer. Silent before round 3.
        "required-without-producer-when-day-promoted": dict(
            clean, day_rules={"tuesday": {"4": ["d.json"]}}),
        # The manifest-rot case: the declaration stands, the source is gone.
        "producer-source-missing": dict(clean, source_exists=lambda s: False),
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

    # Drive the REAL manifest reader over the REAL manifest. Every mutant above
    # hands find_drift a synthetic `produced` set, so all of them stay green if
    # the reader is broken -- the same "green test over the pure rule proves
    # nothing about the code that BUILDS its inputs" hole Codex found in PR #202
    # round 2.
    if not PRODUCERS_JSON.is_file():
        print(f"SELF-TEST FAIL: missing declared producer manifest {PRODUCERS_JSON}")
        return 1
    declared, sources = read_declared_producers(PRODUCERS_JSON)
    if not declared or not sources:
        print("SELF-TEST FAIL: manifest reader returned an empty producer set")
        return 1
    # A name only a SCRIPT produces. The whole reason a `## Writes` section on an
    # agent could not be the declared source (ASK-885): compliance.json comes
    # from compliance-check.py, which has no agent file to carry a declaration.
    if "compliance.json" not in declared:
        print("SELF-TEST FAIL: manifest reader lost the script-produced compliance.json")
        return 1
    # The three files that must NEVER read as produced. They survived all five
    # inference definitions and they are the regression bar for this rewrite.
    for name in ("energy.json", "dp-pipeline.json", "tl-content.json"):
        if name in declared:
            print(f"SELF-TEST FAIL: {name} is declared as produced; it has no producer")
            return 1
    # The shipped false positive that closed PR #202: a q-system/memory/ write
    # read as a bus artifact because it appeared under an agent's `## Writes`.
    if "sycophancy-log.json" in declared:
        print("SELF-TEST FAIL: sycophancy-log.json is a memory file, not a bus artifact")
        return 1
    print(f"  ok  manifest reader: {len(declared)} declared producers, script-produced "
          "names included, the three unproduced files excluded")

    # A malformed manifest must RAISE, not return an empty set. An empty set
    # makes every required file look unproduced, which is a false-positive flood
    # dressed as a finding.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write('{"producers": {"x.json": []}}')
        bad = Path(fh.name)
    try:
        read_declared_producers(bad)
    except ValueError:
        print("  ok  manifest reader: a malformed entry raises instead of returning empty")
    else:
        print("SELF-TEST FAIL: a malformed manifest entry was accepted silently")
        return 1
    finally:
        bad.unlink(missing_ok=True)

    # Drive the REAL day-rule source readers over the REAL verifier sources.
    # Every mutant above hands find_drift a synthetic day_rules dict, so all of
    # them stayed green while the detector read only _cadence-config.json and
    # was blind to the literals both verifiers carry (ASK-874 round 4). Measured
    # on a copy: removing day_rules from the config silenced the finding
    # entirely. This case is the one that goes red for that reason.
    for src, label in ((MCP_VERIFIER_PY, "mcp:bus_verifier"),
                       (VERIFY_BUS_PY, "verify-bus.py")):
        if not src.is_file():
            print(f"SELF-TEST FAIL: cannot read day rules from missing {label}")
            return 1
        got = read_hardcoded_day_rules(src)
        for day in ("tuesday", "thursday"):
            promoted = got.get(day, {}).get("4", [])
            if "tl-content.json" not in promoted:
                print(f"SELF-TEST FAIL: {label} hardcodes a {day} phase-4 promotion "
                      f"of tl-content.json that the reader missed (got {promoted or 'none'})")
                return 1
    print("  ok  day-rule reader: both verifiers' hardcoded Tue/Thu promotions parsed")

    # The union must survive the DECLARED config going missing, because the MCP
    # verifier never opens that config and promotes anyway.
    config_gone = merge_day_rules({}, read_hardcoded_day_rules(MCP_VERIFIER_PY))
    if "tl-content.json" not in config_gone.get("tuesday", {}).get("4", []):
        print("SELF-TEST FAIL: with no config day_rules the union lost the "
              "tuesday promotion the MCP verifier still performs")
        return 1

    # End to end over the REAL manifest and the REAL day rules: tl-content.json
    # must come back as required-without-producer. This is the ASK-885
    # non-negotiable regression, asserted against live inputs rather than a
    # fixture, because a fixture I invent tests my assumption.
    live = find_drift(**dict(clean, day_rules=config_gone, produced=declared))
    if not [f for f in live if f["class"] == "required-without-producer"
            and "tl-content.json" in f["detail"]]:
        print("SELF-TEST FAIL: tl-content.json is promoted at runtime, has no declared "
              "producer, and emitted no required-without-producer finding")
        return 1
    print("  ok  day-rule union: survives a config with no day_rules, still flags "
          "the unproduced tl-content.json promotion")

    print(f"SELF-TEST PASS: clean input is silent, all {len(cases)} mutants caught, "
          "manifest + day-rule readers verified against live sources.")
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
        produced, producer_sources = read_declared_producers(PRODUCERS_JSON)
    except (OSError, ValueError, SyntaxError, json.JSONDecodeError) as e:
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

    # Three independent sources can promote a file to required at RUNTIME, so
    # all three are read and unioned. The config is the DECLARED source; it is
    # not the only one, and it is the only one that can go missing (ASK-874
    # round 4 -- see read_hardcoded_day_rules for the measurement).
    cadence = AGENT_DIR / "_cadence-config.json"
    try:
        config_day_rules = json.loads(cadence.read_text()).get("day_rules", {}) \
            if cadence.is_file() else {}
    except (OSError, json.JSONDecodeError):
        config_day_rules = {}

    hardcoded_day_rules: dict = {}
    for src in (MCP_VERIFIER_PY, VERIFY_BUS_PY):
        if src.is_file():
            hardcoded_day_rules = merge_day_rules(
                hardcoded_day_rules, read_hardcoded_day_rules(src))

    day_rules = merge_day_rules(config_day_rules, hardcoded_day_rules)

    findings = find_drift(bridge, mcp, vbus, schemas, produced,
                          day_rules=day_rules,
                          producer_sources=producer_sources,
                          source_exists=lambda s: (REPO / s).exists())

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
