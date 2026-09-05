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


def test_a_hub_that_is_merely_behind_the_skeleton_is_not_reported_as_drift(tmp_path):
    """PR #294 review round 6, major: the digest comparison was symmetric, so
    every file the skeleton edited since the hub's last sync read as hub drift
    (53 lines on the one declared hub, 12 of them that PR's own edits). A hub
    file whose content is a version the skeleton's git history holds is
    BEHIND; only content the skeleton never had is drift."""
    import subprocess
    root, hub = _fixture(tmp_path)
    old = "---\ntitle: c\n---\nold skeleton version\n"
    (root / "q-system" / "lessons" / "changed.md").write_text(old)
    git = ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "old"], check=True)
    (root / "q-system" / "lessons" / "changed.md").write_text("---\ntitle: c\n---\nnew skeleton version\n")
    (hub / "q-system" / "lessons" / "changed.md").write_text(old)          # hub is behind
    (hub / "q-system" / "lessons" / "forked.md").write_text("---\ntitle: f\n---\nhub-only content\n")
    (root / "q-system" / "lessons" / "forked.md").write_text("---\ntitle: f\n---\nskeleton content\n")
    m = _mod()
    absent, changed, behind = m.drift(str(hub), str(root))
    assert behind == ["q-system/lessons/changed.md"] and changed == ["q-system/lessons/forked.md"] and absent == [], (absent, changed, behind)
    out = m.build(str(root))
    assert "differs  q-system/lessons/forked.md" in out and "changed.md" not in out and "1 more are just behind" in out, out


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


def test_an_empty_skeleton_path_never_passes_even_from_the_root(tmp_path):
    """Codex (issue 13): realpath('') is the cwd, so an empty registry entry
    passed whenever the reporter ran from its own root."""
    root, hub = _fixture(tmp_path)
    reg = json.loads((root / "instance-registry.json").read_text())
    for bad in ("", "   ", None):
        reg["skeleton"]["path"] = bad
        (root / "instance-registry.json").write_text(json.dumps(reg))
        r = subprocess.run([sys.executable, str(REPORT), "--root", str(root), "--dry-run"], capture_output=True, text=True, cwd=root, timeout=60)
        assert r.returncode == 0 and "skeleton: COULD NOT READ" in r.stdout, (bad, r.stdout)


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


def test_loading_helpers_leaves_the_bytecode_flag_as_it_found_it(tmp_path):
    """Codex adversarial (issue 13): _load set sys.dont_write_bytecode for the
    whole process and never restored it."""
    root, hub = _fixture(tmp_path)
    m = _mod()
    saved = sys.dont_write_bytecode
    try:
        for start in (False, True):  # whatever the caller had, it keeps
            sys.dont_write_bytecode = start
            m.run(root=root, deliver=lambda msg: {}, dry_run=True, trigger=None)
            assert sys.dont_write_bytecode is start
    finally:
        sys.dont_write_bytecode = saved
    assert not list((SCRIPTS / "__pycache__").glob("lessons_streak*")) if (SCRIPTS / "__pycache__").exists() else True


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


# ---- issue lr-drift-trigger-proof (Codex finding-7 on the PRD) -----------------
# Removing the trigger provably stops delivery: the reporter sends only under the
# plist's environment marker and has exactly one caller in the tree.

def test_no_trigger_means_deliver_is_called_zero_times(tmp_path):
    root, hub = _fixture(tmp_path)
    (hub / "q-system" / "lessons" / "only-here.md").write_text("---\ntitle: only here\n---\nx\n")
    m = _mod()
    calls = []
    fake = lambda msg: calls.append(msg) or {"delivered": True, "refused": False}
    out = m.run(root=root, deliver=fake, dry_run=False, trigger=None)
    assert calls == [] and out["delivery"]["skipped"] is True and "not launched by the plist" in out["delivery"]["reason"]
    out = m.run(root=root, deliver=fake, dry_run=False, trigger="cron")
    assert calls == []
    out = m.run(root=root, deliver=fake, dry_run=False, trigger="launchd")
    assert len(calls) == 1 and out["delivery"]["delivered"] is True


def test_cli_without_the_marker_prints_and_says_it_did_not_send(tmp_path):
    root, hub = _fixture(tmp_path)
    (hub / "q-system" / "lessons" / "only-here.md").write_text("---\ntitle: only here\n---\nx\n")
    r = _run(root)  # KIPI_TRIGGER stripped by _run
    assert r.returncode == 0 and "only-here.md" in r.stdout and "delivery: not launched by the plist" in r.stdout, r.stdout
    r = _run(root, env_extra={"KIPI_TRIGGER": "launchd"})
    assert "delivery: refused" in r.stdout, "under pytest the real sender refuses, and the CLI says so"
    assert r.returncode == 2, "a launchd run whose only alert was refused must not exit 0 (PR #294 review)"


def test_a_launchd_run_whose_delivery_fails_exits_nonzero_and_a_delivered_one_exits_zero(tmp_path, monkeypatch, capsys):
    """PR #294 review, major: main() returned 0 after Slack refused, so the
    scheduled reporter's only alert vanished with a success exit that launchd,
    the deadman and run-step-audit all read as fine. Three shapes, one rule:
    launched by the plist and not delivered is a failure; printed-not-sent
    (no plist marker) and dry-run stay 0 because nothing was owed."""
    root, hub = _fixture(tmp_path)
    m = _mod()
    monkeypatch.setenv("KIPI_TRIGGER", "launchd")
    assert m.main(["--root", str(root)], deliver=lambda msg: {"delivered": False, "refused": True}) == 2
    assert m.main(["--root", str(root)], deliver=lambda msg: {}) == 2, "an empty answer is not a delivery"
    assert m.main(["--root", str(root)], deliver=lambda msg: {"delivered": True, "refused": False}) == 0
    assert m.main(["--root", str(root), "--dry-run"], deliver=lambda msg: {"refused": True}) == 0
    monkeypatch.delenv("KIPI_TRIGGER")
    assert m.main(["--root", str(root)], deliver=lambda msg: {"refused": True}) == 0
    assert "delivery: refused" in capsys.readouterr().out


def test_single_caller_the_plist_template_is_the_only_one_in_the_tree():
    """EXACTLY the plist template and this test name the reporter's file; a
    second caller or a removed template is RED. The tree is the set of TRACKED
    files (git grep), which by construction leaves out dead worktree copies
    under .claude/worktrees/ and .wt-*, bytecode, and the untracked DSSE
    runtime state under .claude/state/; nothing else under .claude is excluded
    (Codex, issue 14). .prd-os/ (issue specs and receipts describing this work)
    and docs/ (the handbook, which NAMES the file so a reader can open it) are
    filtered afterwards, by name: a page that mentions a script is not a caller.
    Measured 2026-09-05: docs/systems/10 and docs/reference/scripts.md turned
    this RED on PR #306 with zero new callers in the tree."""
    root = HERE.parent.parent.parent
    out = subprocess.run(["git", "-C", str(root), "grep", "-l", "--", "lessons-drift-report.py"], capture_output=True, text=True).stdout
    rel = sorted(l for l in out.splitlines()
                 if l and not l.startswith(".prd-os/") and not l.startswith("docs/"))
    assert rel == ["q-system/.q-system/scripts/com.kipi.lessons-drift.plist",
                   "q-system/.q-system/tests/test_lessons_drift_report.py"], rel


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
