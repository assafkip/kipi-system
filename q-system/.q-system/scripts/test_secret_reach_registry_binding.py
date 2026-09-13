#!/usr/bin/env python3
"""The shipped secret-reach registry binds to the skeleton's decisions.md (ASK-1251).

SKELETON ONLY, declared in capability/skeleton_only/. canonical/decisions.md is
instance-owned, so in a synced instance it does not carry RULE-2026-09-13-A/B
and this check would report 20 unbound rows on every run. The PR #345 review
caught that when the check lived in the fleet-wide test file.

Reads two repo files and never a secret path: the fake HOME is empty and the
environment carries only PATH and HOME.
"""

import json
import os
import pathlib
import subprocess
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "secret-reach-inventory.py"
QROOT = SCRIPTS.parent.parent
REAL_REGISTRY = QROOT / ".q-system" / "secret-reach-registry.json"
REAL_DECISIONS = QROOT / "canonical" / "decisions.md"


def test_real_registry_binds_every_authority_row_to_a_tagged_decision(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--registry", str(REAL_REGISTRY),
         "--decisions", str(REAL_DECISIONS), "--home", str(home)],
        capture_output=True, text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = json.loads(REAL_REGISTRY.read_text())["rows"]
    assert any(r["class"] == "authority" for r in rows)
    assert "ask-crm-local-proof" in {r["id"] for r in rows}
