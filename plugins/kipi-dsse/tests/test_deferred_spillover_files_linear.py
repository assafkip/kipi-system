"""ASK-1552: a `deferred` disposition on the DSSE issue path files one Linear
issue for the spillover row it creates, the same as `spillover add`.

Founder, 2026-09-12: "Backlog where? In linear or is it going to disappear".
The row is written first through this plugin's existing ledger append; the
Linear link is appended after. Isolation: tmp repo, the real alert-to-linear.py
copied into the production layout, KIPI_ALERT_CAPTURE set.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ISSUE_FINDINGS = PLUGIN_ROOT / "scripts" / "issue_findings.py"
SKEL_SCRIPTS = PLUGIN_ROOT.parents[1] / "q-system" / ".q-system" / "scripts"
ISSUE_ID = "c2w-linear"
SID = f"defer-{ISSUE_ID}-finding-9"

# The scripts this suite deliberately exercises. Their sibling dependencies are
# DERIVED below, never listed here. Deliberately duplicated from prd-os's
# test_spillover_files_linear.py rather than imported across a plugin boundary:
# what must not be duplicated is the dependency LIST, and neither copy holds one.
ENTRY_SCRIPTS = ("alert-to-linear.py", "spillover-linear-check.py")


def sibling_modules(entry: Path, scripts: Path) -> set[str]:
    """Every sibling script `entry` imports, transitively, derived from its source.

    Scar (ASK-2012): alert-to-linear.py grew `import filer_cap` and the
    hand-maintained copy list here did not. The tmp repo got an incomplete
    production layout, the script died on ImportError, and this test failed on a
    broken fixture rather than on anything it asserts.
    """
    found: set[str] = set()
    queue = [entry]
    while queue:
        tree = ast.parse(queue.pop().read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in found or not (scripts / f"{name}.py").exists():
                    continue
                found.add(name)
                queue.append(scripts / f"{name}.py")
    return found


def install_skeleton_scripts(dest: Path) -> None:
    """Copy the entry scripts plus their derived siblings into a tmp repo."""
    names = set(ENTRY_SCRIPTS)
    for entry in ENTRY_SCRIPTS:
        names |= {f"{m}.py" for m in sibling_modules(SKEL_SCRIPTS / entry, SKEL_SCRIPTS)}
    # Floor: an empty derivation would silently reinstate the stale-list bug,
    # copying only the entry scripts and reading as a correct fixture.
    assert names - set(ENTRY_SCRIPTS), "derived no sibling module; the import parse is broken"
    for name in sorted(names):
        shutil.copy2(SKEL_SCRIPTS / name, dest / name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "issues" / "findings").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / "issues" / "findings" / f"{ISSUE_ID}-findings.jsonl").write_text(json.dumps({
        "id": "finding-9", "issue_id": ISSUE_ID, "source": "codex-adversarial",
        "severity": "major", "disposition": "pending",
        "body": "exporter drops non-ascii slugs", "out_of_scope": False,
        "affected_path": "q-consult/pipeline/exporters.py",
        "created_at": "2026-09-12T00:00:00Z"}) + "\n")
    dest = r / "q-system" / ".q-system" / "scripts"
    dest.mkdir(parents=True)
    install_skeleton_scripts(dest)
    return r


def _defer(repo: Path, capture: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo), KIPI_ALERT_CAPTURE=str(capture))
    return subprocess.run(
        [sys.executable, str(ISSUE_FINDINGS), "set-disposition", ISSUE_ID, "finding-9",
         "deferred", "--rationale", "later"],
        capture_output=True, text=True, env=env, cwd=str(repo), timeout=120)


def _ledger(repo: Path) -> dict:
    items: dict = {}
    for raw in (repo / ".prd-os" / "spillover.jsonl").read_text().splitlines():
        if raw.strip():
            rec = json.loads(raw)
            items[rec["id"]] = rec
    return items


def test_dsse_deferred_files_exactly_one_issue_and_links_the_row(repo, tmp_path):
    cap = tmp_path / "capture.txt"
    out = _defer(repo, cap)
    assert out.returncode == 0, out.stderr
    lines = cap.read_text().splitlines() if cap.exists() else []
    assert len(lines) == 1 and SID in lines[0], lines
    rec = _ledger(repo)[SID]
    assert rec["status"] == "open" and rec["linear"]["state"] == "captured"

    # A second defer is idempotent: no second row, no second issue.
    assert _defer(repo, cap).returncode == 0
    assert len(cap.read_text().splitlines()) == 1


def test_dsse_filer_failure_keeps_the_row(repo, tmp_path):
    cap = tmp_path / "capture-dir"
    cap.mkdir()
    out = _defer(repo, cap)
    assert out.returncode == 0, out.stderr
    rec = _ledger(repo)[SID]
    assert rec["status"] == "open"
    assert rec["linear"]["state"] == "failed" and rec["linear"]["exit"] == 1


@pytest.mark.parametrize("severity", ["minor", "low"])
def test_dsse_deferring_a_minor_is_refused(repo, tmp_path, severity):
    """Founder 2026-09-12: "New minor findings: fix or reject, never queue"."""
    fpath = repo / "issues" / "findings" / f"{ISSUE_ID}-findings.jsonl"
    rec = json.loads(fpath.read_text().splitlines()[0])
    rec["severity"] = severity
    fpath.write_text(json.dumps(rec) + "\n")
    cap = tmp_path / "capture.txt"
    out = _defer(repo, cap)
    assert out.returncode == 2, out.stdout + out.stderr
    assert ("a minor is fixed in this change or rejected with a reason; "
            "it is never queued (founder 2026-09-12)") in out.stderr
    assert json.loads(fpath.read_text().splitlines()[0])["disposition"] == "pending"
    assert not (repo / ".prd-os" / "spillover.jsonl").exists()
    assert not cap.exists()
