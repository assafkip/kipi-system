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
}
SIBLING_CALL = re.compile(r"_load_sibling\(\s*[\"']([\w-]+)[\"']\s*\)")
SIBLING_PATH = re.compile(r"[\"']((?:design|check_technique)[\w-]*\.py)[\"']")


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


def sibling_loads(path: Path) -> set[str]:
    text = path.read_text()
    names = {f"{m}.py" for m in SIBLING_CALL.findall(text)}
    names |= {m for m in SIBLING_PATH.findall(text) if m != path.name}
    return names


class Census(unittest.TestCase):
    def test_the_census_found_scripts_at_all(self):
        # a glob that matches nothing turns every check below into a green no-op
        self.assertGreaterEqual(len(design_scripts()), len(EXPECTED))

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

    def test_third_party_imports_are_declared(self):
        found = set()
        for p in design_scripts():
            found |= third_party_imports(p)
        found -= {p.stem.replace("-", "_") for p in design_scripts()}
        self.assertEqual(found - DECLARED_THIRD_PARTY, set(), "undeclared third-party import")
        self.assertIn("PIL", found, "Pillow is declared but nothing imports it: the scan is unbound")


if __name__ == "__main__":
    unittest.main()
