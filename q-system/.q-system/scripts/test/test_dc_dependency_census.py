#!/usr/bin/env python3
"""Dependency census for the design-chain scripts, taken by code.

Scar, 2026-09-18 (ASK-1796): a census that read static imports only reported "stdlib plus
playwright" and missed design-ink-coverage.py, which design-gap-check.py loads BY FILENAME
through _load_sibling(), and which needs Pillow. A PRD was written on that false claim and
an adversarial review caught it. So this follows filename loads as well as imports.

Read-only over the scripts directory. Touches no data path.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
# Third-party modules the design-chain scripts may import. Adding one is a decision: it
# becomes something every instance that declares the matching stage has to have installed.
DECLARED_THIRD_PARTY = {"playwright", "PIL"}
EXPECTED = {
    "design-chain-gate.py", "design-standard-check.py", "design-gap-check.py",
    "design-impeccable-check.py", "design-exemplar-capture.py",
    "design-standard-from-exemplars.py", "design-ink-coverage.py", "design-axis-coverage.py",
    "check_technique_parity.py",
    "design-reader-gate.py",       # dc-06: the reader gate
    "design-engine-door.py",       # dc-18: the one door on the Skill tool
}
# A sibling reference is ANY string constant naming a design script, with or without ".py".
# Scar, same day, caught by both reviewers of this file's first version: it matched
# _load_sibling("x") and quoted "x.py" literals only, so design-axis-coverage.py's own
# loader, load("design-gap-check") -> HERE / f"{mod}.py", returned NOTHING. A helper loaded
# that way was deleted in a copy and this census stayed green while the script died with
# FileNotFoundError. Matching the loader's spelling misses the next loader; matching the
# NAME does not care how the path is built.
SIBLING_NAME = re.compile(r"^(design-[a-z0-9-]+|check_technique_parity)(\.py)?$")
# Executables and out-of-repo paths the scripts shell out to. The only hard non-Python
# dependency in the set is here: node plus a detector that lives in another repo.
DECLARED_EXECUTABLES = {"node", "git", "claude"}   # claude: the reader gate's model runner (dc-06)
DECLARED_EXTERNAL_PATHS = {
    "~/projects/cole-gtm/.agents/skills/impeccable/scripts/detector/detect-antipatterns.mjs",
    "~/.config/kipi/design-chain",      # the gate's per-session ledger directory
}


def design_scripts():
    return sorted(p for p in SCRIPTS.glob("*.py")
                  if p.name.startswith("design-") or p.name == "check_technique_parity.py")


def third_party_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return {m for m in mods if m not in sys.stdlib_module_names}


def string_constants(path: Path) -> list[str]:
    return [n.value for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def engine_names() -> set[str]:
    """Design ENGINE names (skills, not files) from the registry that owns them. The door names
    'design-room' as an engine, and the sibling scan read it as a missing design-room.py (dc-18)."""
    import json
    reg = json.loads((SCRIPTS / "design-engines.json").read_text())
    names = {e["skill"] for e in reg["engines"]}
    assert names, "design-engines.json lists no engines"
    return names


def sibling_loads(path: Path) -> set[str]:
    names = set()
    # only the door names engines; anywhere else a design-* string is a file (review of 1ab27d24)
    engines = engine_names() if path.name == "design-engine-door.py" else set()
    for value in string_constants(path):
        if value.strip() in engines:
            continue
        m = SIBLING_NAME.match(value.strip())
        if m and f"{m.group(1)}.py" != path.name:
            names.add(f"{m.group(1)}.py")
    return names


def shelled_executables(path: Path) -> set[str]:
    """First element of a list literal passed to subprocess.run / check_output / Popen."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"run", "check_output", "check_call", "Popen", "call"}
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
            continue
        if node.args and isinstance(node.args[0], ast.List) and node.args[0].elts:
            first = node.args[0].elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def external_paths(path: Path) -> set[str]:
    return {v for v in string_constants(path) if v.startswith("~/") or v.startswith("/Users/")}


class Census(unittest.TestCase):
    def test_the_population_is_exactly_the_declared_set(self):
        # Equality, not >=. A floor on len(EXPECTED) stayed green while the tree shrank as
        # soon as one design-*.py existed outside the list. A new script (dc-06 adds one)
        # turns this red until it is added here on purpose, which is the point.
        self.assertEqual({p.name for p in design_scripts()}, EXPECTED)

    def test_every_expected_script_is_present(self):
        have = {p.name for p in design_scripts()}
        self.assertEqual(EXPECTED - have, set(), "design-chain scripts missing from the tree")

    def test_every_sibling_loaded_by_filename_exists(self):
        missing = {}
        for p in design_scripts():
            gone = {n for n in sibling_loads(p) if not (SCRIPTS / n).is_file()}
            if gone:
                missing[p.name] = sorted(gone)
        self.assertEqual(missing, {}, "a script loads a sibling by filename that is not in the tree")

    def test_the_sibling_scan_is_bound(self):
        # design-gap-check.py is the script that taught this lesson; if the scan stops seeing
        # its filename load, the check above is reading nothing
        self.assertIn("design-ink-coverage.py", sibling_loads(SCRIPTS / "design-gap-check.py"))

    def test_the_scan_sees_a_load_built_from_a_variable(self):
        # the loader the first version of this file could not see
        self.assertIn("design-gap-check.py", sibling_loads(SCRIPTS / "design-axis-coverage.py"))

    def test_shelled_executables_are_declared(self):
        found = set()
        for p in design_scripts():
            found |= shelled_executables(p)
        self.assertEqual(found - DECLARED_EXECUTABLES, set(), "undeclared executable shelled out to")
        self.assertIn("node", found, "node is declared but nothing shells it: the scan is unbound")

    def test_out_of_repo_paths_are_declared(self):
        found = set()
        for p in design_scripts():
            found |= external_paths(p)
        self.assertEqual(found - DECLARED_EXTERNAL_PATHS, set(), "undeclared path outside the repo")
        self.assertEqual(DECLARED_EXTERNAL_PATHS - found, set(), "declared external path nothing references")

    def test_third_party_imports_are_declared(self):
        found = set()
        for p in design_scripts():
            found |= third_party_imports(p)
        found -= {p.stem.replace("-", "_") for p in design_scripts()}
        self.assertEqual(found - DECLARED_THIRD_PARTY, set(), "undeclared third-party import")
        self.assertIn("PIL", found, "Pillow is declared but nothing imports it: the scan is unbound")


if __name__ == "__main__":
    unittest.main()
