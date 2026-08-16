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


def declared_writes(agent_text: str) -> set[str]:
    """Names under an agent's `## Writes` heading - the DECLARED producer signal.

    Preferred over inferring from prose, but it cannot stand alone: measured
    2026-08-16, only 26 of 38 agents carry the section, and the 9 without it
    include 01-crm-pull.md, the canonical writer of crm.json. Trusting the
    declaration alone would invent 10 false "no producer" findings. So this is
    unioned with the verb heuristic rather than replacing it, and the union is
    what makes both halves safe: each covers names the other misses, and the
    three genuinely unproduced files (energy, dp-pipeline, tl-content) appear
    in NEITHER, so the true positives survive.
    """
    out: set[str] = set()
    for m in re.finditer(r"^## Writes\b(.*?)(?=^## |\Z)", agent_text, re.S | re.M):
        out |= set(re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json", m.group(1)))
    return out


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
    declared = declared_writes(agent_text)
    return produced | declared, mentioned | declared


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
               mentioned: set[str] | None = None,
               *, day_rules: dict) -> list[dict]:
    """`produced` = a WRITE was found. `mentioned` = the name appears at all.

    Codex PR #202 (major): keying the producer classes on mere mention treated
    every read as a write, so deleting a real writer left
    required-without-producer silent as long as some agent still READ the file.
    Agents both `Read {{BUS_DIR}}/calendar.json` and `Write log to
    {{BUS_DIR}}/daily-checklists.json`, so the two facts are separate inputs.
    """
    if mentioned is None:
        mentioned = produced
    # day_rules is keyword-ONLY and has no default on purpose (ASK-874 round 4).
    # It used to default to {}, so a caller that forgot it got a detector that
    # silently skipped D3b and reported GREEN on a phase that cannot pass. The
    # reviewer's own reproducer did exactly that. A missing argument is now a
    # loud TypeError instead of a quiet false negative.
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
    # A day-rule file IS known to a verifier, just conditionally. Leaving these
    # out made D6 call content-intel.json "unknown" while verify-bus requires it
    # every Monday - the detector contradicting data it had already loaded
    # (Codex PR #202 round 4). Fixing the day-rule blind spot in D3b relocated
    # the defect into the neighbouring rule instead of closing it.
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
        day_rules={},
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
        "## Instructions\n"
        "1. Read `{{BUS_DIR}}/reader-only.json` and parse it\n"
        "2. Write results to {{BUS_DIR}}/written.json\n"
        "3. Run the script - writes script-made.json\n"
        "4. Update settings.json with the new key\n"
        "\n"
        "## Writes\n"
        "- declared-only.json (no verb, no BUS_DIR - the declaration is the signal)\n"
        "\n"
        "## Reads\n"
        "- not-a-write.json\n"
    )
    got_produced, got_mentioned = extract_producers(sample)
    expect_p = {"written.json", "script-made.json", "declared-only.json"}
    expect_m = expect_p | {"reader-only.json"}
    for label, actual, expected in (
        ("produced", got_produced, expect_p),
        ("mentioned", got_mentioned, expect_m),
    ):
        if actual != expected:
            print(f"SELF-TEST FAIL: extractor {label} was {sorted(actual)}, "
                  f"expected {sorted(expected)}")
            return 1
    print("  ok  extractor: read-only line is mentioned but NOT produced; "
          "settings.json ignored")

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

    # The union must survive the DECLARED source going missing, because the MCP
    # verifier never opens that config and promotes anyway.
    config_gone = merge_day_rules({}, read_hardcoded_day_rules(MCP_VERIFIER_PY))
    promoted_without_config = config_gone.get("tuesday", {}).get("4", [])
    if "tl-content.json" not in promoted_without_config:
        print("SELF-TEST FAIL: with no config day_rules the union lost the "
              "tuesday promotion the MCP verifier still performs")
        return 1
    day_promoted_findings = [
        f for f in find_drift(**dict(clean, day_rules=config_gone))
        if f["class"] == "required-without-producer" and "tl-content.json" in f["detail"]
    ]
    if not day_promoted_findings:
        print("SELF-TEST FAIL: a runtime-promoted file with no producer emitted "
              "no required-without-producer finding")
        return 1
    print("  ok  day-rule union: survives a config with no day_rules, still flags "
          "the unproduced promotion")

    print(f"SELF-TEST PASS: clean input is silent, all {len(cases)} mutants caught, "
          "extractor + day-rule readers verified.")
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

    hardcoded_day_rules = {}
    for src in (MCP_VERIFIER_PY, VERIFY_BUS_PY):
        if src.is_file():
            hardcoded_day_rules = merge_day_rules(
                hardcoded_day_rules, read_hardcoded_day_rules(src))

    day_rules = merge_day_rules(config_day_rules, hardcoded_day_rules)

    findings = find_drift(bridge, mcp, vbus, schemas, produced, mentioned,
                          day_rules=day_rules)

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
