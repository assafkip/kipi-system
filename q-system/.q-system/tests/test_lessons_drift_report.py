#!/usr/bin/env python3
"""RED FIRST. Issue lr-drift-reporter (prd-lessons-rail-and-up-rail, plan 4c) and
issue lr-drift-trigger-proof. A scheduled reporter says what a declared hub
instance has that the skeleton lacks, resolves both paths from the registry
(the skeleton entry must be the reporter's own root, so a worktree never
reports as the skeleton), appends the propagation streak summary, and delivers
via slack_founder.deliver only when launched by its plist.

Every tree here is tmp; the registry and hubs file are fixtures.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
REPORT = SCRIPTS / "lessons-drift-report.py"
PLIST = SCRIPTS / "com.kipi.lessons-drift.plist"
HUBS = HERE.parent / "drift-hubs.json"


def _mod():
    spec = importlib.util.spec_from_file_location("lessons_drift_report", REPORT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fixture(tmp_path, hub_names=("ASK_AI_consultant",), skeleton_path=None):
    root = tmp_path / "skeleton"
    hub = tmp_path / "hub"
    for base in (root, hub):
        (base / "q-system" / "lessons").mkdir(parents=True)
        (base / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
        (base / "q-system" / "output").mkdir(parents=True)
    (root / "q-system" / "lessons" / "shared.md").write_text("---\ntitle: shared\n---\nsame\n")
    (hub / "q-system" / "lessons" / "shared.md").write_text("---\ntitle: shared\n---\nsame\n")
    (root / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(skeleton_path or root)},
        "instances": [{"name": "ASK_AI_consultant", "path": str(hub), "instance_q_dir": "q-consult", "type": "subtree"}]}))
    (root / "q-system" / ".q-system" / "drift-hubs.json").write_text(json.dumps({"hubs": list(hub_names)}))
    return root, hub


def _run(root, *args, env_extra=None):
    env = dict(os.environ)
    env.pop("KIPI_TRIGGER", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(REPORT), "--root", str(root), *args], capture_output=True, text=True, env=env, timeout=60)


def test_reports_lessons_and_scripts_the_hub_has_and_the_skeleton_lacks(tmp_path):
    root, hub = _fixture(tmp_path)
    (hub / "q-system" / "lessons" / "only-here.md").write_text("---\ntitle: only here\n---\nx\n")
    (hub / "q-system" / ".q-system" / "scripts" / "new-tool.py").write_text("print('x')\n")
    (hub / "q-system" / "lessons" / "changed.md").write_text("---\ntitle: c\n---\nhub version\n")
    (root / "q-system" / "lessons" / "changed.md").write_text("---\ntitle: c\n---\nskeleton version\n")
    r = _run(root, "--dry-run")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "ASK_AI_consultant has 2 the skeleton lacks" in out or "lacks" in out, out
    assert "lessons/only-here.md" in out and "scripts/new-tool.py" in out and "lessons/changed.md" in out, out
    assert "shared.md" not in out
    assert "no drift" not in out


def test_no_drift_when_equal(tmp_path):
    root, hub = _fixture(tmp_path)
    r = _run(root, "--dry-run")
    assert r.returncode == 0 and "no drift" in r.stdout, r.stdout


def test_hub_missing_from_the_registry_renders_could_not_read(tmp_path):
    root, hub = _fixture(tmp_path, hub_names=("ASK_AI_consultant", "ghost-hub"))
    r = _run(root, "--dry-run")
    assert r.returncode == 0
    assert "ghost-hub: COULD NOT READ" in r.stdout, r.stdout
    assert "ASK_AI_consultant" in r.stdout


def test_a_worktree_never_reports_as_the_skeleton(tmp_path):
    """The registry's skeleton entry must be the reporter's own root."""
    root, hub = _fixture(tmp_path, skeleton_path=tmp_path / "the-real-skeleton")
    r = _run(root, "--dry-run")
    assert r.returncode == 0 and "skeleton: COULD NOT READ" in r.stdout, r.stdout
    assert "lacks" not in r.stdout


def test_unreadable_hub_tree_renders_could_not_read(tmp_path):
    root, hub = _fixture(tmp_path)
    import shutil
    shutil.rmtree(hub)
    r = _run(root, "--dry-run")
    assert "ASK_AI_consultant: COULD NOT READ" in r.stdout, r.stdout


def test_streak_summary_is_appended(tmp_path):
    root, hub = _fixture(tmp_path)
    (root / "q-system" / "output" / "lessons-propagation-streak.json").write_text('{"streak": 4}')
    r = _run(root, "--dry-run")
    assert "streak 4, 0 escalations in 30d" in r.stdout, r.stdout


def test_delivery_goes_through_slack_founder_and_is_refused_under_pytest(tmp_path):
    root, hub = _fixture(tmp_path)
    (hub / "q-system" / "lessons" / "only-here.md").write_text("---\ntitle: only here\n---\nx\n")
    m = _mod()
    calls = []
    out = m.run(root=root, deliver=lambda msg: calls.append(msg) or {"delivered": True, "refused": False}, dry_run=False, trigger="launchd")
    assert len(calls) == 1 and "only-here.md" in calls[0]
    # the real sender refuses under pytest, and the module reports that honestly
    out = m.run(root=root, deliver=None, dry_run=False, trigger="launchd")
    assert out["delivery"]["refused"] is True and out["delivery"]["delivered"] is False


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path):
    root, hub = _fixture(tmp_path)
    (hub / "q-system" / "lessons" / "only-here.md").write_text("---\ntitle: only here\n---\nx\n")
    before = sorted(str(p) for p in root.rglob("*"))
    m = _mod()
    calls = []
    m.run(root=root, deliver=lambda msg: calls.append(msg), dry_run=True, trigger="launchd")
    assert calls == [] and sorted(str(p) for p in root.rglob("*")) == before


def test_never_references_the_fleet_alert_path():
    src = REPORT.read_text()
    assert "slack-notify" not in src, "founder-facing; never the Linear alert path"
    assert "slack_founder" in src


def test_plist_template_runs_it_monday_0645_with_the_trigger_marker():
    src = PLIST.read_text()
    for ph in ("__KIPI_REPO__", "__HOME__", "__USER__"):
        assert ph in src
    assert "/Users/" not in src
    assert "lessons-drift-report.py</string>" in src
    assert "<key>Weekday</key><integer>1</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>45</integer>" in src
    assert "<key>KIPI_TRIGGER</key><string>launchd</string>" in src
    assert "<string>com.kipi.lessons-drift</string>" in src


def test_hubs_file_names_registered_instances_only():
    hubs = json.loads(HUBS.read_text())["hubs"]
    registry = json.loads((HERE.parent.parent.parent / "instance-registry.json").read_text())
    names = {e.get("name") for e in registry.get("instances", [])}
    assert hubs and all(h in names for h in hubs), (hubs, sorted(names)[:5])


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
