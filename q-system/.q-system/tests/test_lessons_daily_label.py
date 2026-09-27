#!/usr/bin/env python3
"""RED FIRST. Issue lr-lessons-label-collision (prd-lessons-rail-and-up-rail).

install-lessons-daily.sh lives under the fan-out path, so every instance
carries it; run in an instance it rebound com.kipi.lessons-daily to that
instance's copy of a skeleton-only job (the consulting checkout carried exactly
that copy on 2026-09-01). Now the installer refuses outside the skeleton, the
skeleton has a plist TEMPLATE for the job, and every label across templates
and installers is claimed exactly once.

Every run here uses a tmp tree, a fixture registry and a tmp HOME; the
installer is only ever invoked with --render-only, so launchd is never touched.
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INSTALLER = SCRIPTS / "install-lessons-daily.sh"
TEMPLATE = SCRIPTS / "com.kipi.lessons-daily.plist"


LABEL_RE = r"com\.kipi\.[A-Za-z0-9._-]+"


def _labels():
    """Every label CLAIMED by a template or an installer in the skeleton.

    An installer claims a label when it defines one: any `LABEL=` assignment
    (single, double or no quotes, with or without readonly/export/local) or a
    literal <key>Label</key> value inside a heredoc plist. Referencing a
    template (`install-plist.sh com.kipi.x`) is not a claim; those references
    are checked separately against the templates that exist (Codex standard
    review: the first version only matched one quoting style).
    """
    claims = collections.defaultdict(list)
    for plist in SCRIPTS.glob("com.kipi.*.plist"):
        m = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", plist.read_text())
        assert m, f"{plist.name} has no Label"
        claims[m.group(1)].append(plist.name)
    for sh in SCRIPTS.glob("install-*.sh"):
        src = sh.read_text()
        for m in re.finditer(rf"""^\s*(?:readonly\s+|export\s+|local\s+)?LABEL=['"]?({LABEL_RE})['"]?""", src, re.M):
            claims[m.group(1)].append(sh.name)
        for m in re.finditer(rf"<key>Label</key>\s*<string>({LABEL_RE})</string>", src):
            claims[m.group(1)].append(sh.name)
    return claims


def _references():
    """Labels an installer hands to install-plist.sh; each needs a template."""
    refs = collections.defaultdict(list)
    for sh in SCRIPTS.glob("install-*.sh"):
        if sh.name == "install-plist.sh":
            continue
        for m in re.finditer(rf"install-plist\.sh\"?\s+({LABEL_RE})", sh.read_text()):
            refs[m.group(1)].append(sh.name)
    return refs


def test_every_label_is_claimed_exactly_once():
    claims = _labels()
    assert claims, "no labels found under scripts/"
    twice = {k: v for k, v in claims.items() if len(v) != 1}
    assert not twice, f"labels claimed by more than one file: {twice}"
    assert claims["com.kipi.lessons-daily"] == ["com.kipi.lessons-daily.plist"], claims.get("com.kipi.lessons-daily")


def test_label_derivation_sees_every_assignment_form(tmp_path):
    """The derivation itself is tested against planted installers, so a new
    quoting style cannot slip a duplicate past it."""
    planted = {
        "install-a.sh": "LABEL='com.kipi.planted'\n",
        "install-b.sh": 'readonly LABEL="com.kipi.planted"\n',
        "install-c.sh": "export LABEL=com.kipi.planted\n",
        "install-d.sh": "cat > x <<EOF\n  <key>Label</key><string>com.kipi.planted</string>\nEOF\n",
        "install-e.sh": 'bash "$HERE/install-plist.sh" com.kipi.planted "$@"\n',
    }
    for name, body in planted.items():
        (tmp_path / name).write_text(body)
    import test_lessons_daily_label as me  # this module, re-pointed at the tmp dir
    original = me.SCRIPTS
    me.SCRIPTS = tmp_path
    try:
        claims = me._labels()
        refs = me._references()
    finally:
        me.SCRIPTS = original
    assert sorted(claims["com.kipi.planted"]) == ["install-a.sh", "install-b.sh", "install-c.sh", "install-d.sh"]
    assert refs["com.kipi.planted"] == ["install-e.sh"], "a template reference is not a claim"


def test_every_referenced_label_has_a_template():
    refs = _references()
    assert "com.kipi.lessons-daily" in refs
    for label, files in refs.items():
        assert (SCRIPTS / f"{label}.plist").exists(), f"{files} reference {label} but no template exists"


def test_install_all_skips_the_skeleton_only_template_outside_the_skeleton(tmp_path):
    """Codex adversarial (issue 5): --all globs every template, so without the
    marker it would arm the skeleton-only job from an instance checkout."""
    root, installer, home = _tree(tmp_path, "instance-all", tmp_path / "elsewhere" / "kipi-system")
    scripts = installer.parent
    shutil.copy(SCRIPTS / "com.kipi.weekly-improve.plist", scripts / "com.kipi.weekly-improve.plist")
    (root / ".git").mkdir()  # --all refuses from a worktree; a tmp primary checkout has a .git DIR
    env = dict(os.environ, HOME=str(home), KIPI_LAUNCHCTL="true")
    r = subprocess.run(["/bin/bash", str(scripts / "install-plist.sh"), "--all"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "skipped (skeleton-only): com.kipi.lessons-daily" in r.stdout, r.stdout
    agents = home / "Library" / "LaunchAgents"
    assert not (agents / "com.kipi.lessons-daily.plist").exists(), "the skeleton-only job must not be armed in an instance"
    assert (agents / "com.kipi.weekly-improve.plist").exists(), "ordinary templates still install"
    assert "kipi-scope: skeleton-only" in TEMPLATE.read_text()


def test_template_has_the_placeholder_shape_and_the_weekly_schedule():
    src = TEMPLATE.read_text()
    for ph in ("__KIPI_REPO__", "__HOME__", "__USER__"):
        assert ph in src, ph
    assert "/Users/" not in src, "a literal home path would fan out to 25 instances"
    assert re.search(r"<key>Weekday</key><integer>1</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer>", src)
    assert "lessons-daily.sh</string>" in src


def _tree(tmp_path, name, skeleton_path):
    root = tmp_path / name
    scripts = root / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    for f in (INSTALLER, TEMPLATE, SCRIPTS / "install-plist.sh"):
        shutil.copy(f, scripts / f.name)
    (root / "instance-registry.json").write_text(json.dumps({"skeleton": {"path": str(skeleton_path)}, "instances": []}))
    home = tmp_path / f"home-{name}"
    home.mkdir()
    return root, scripts / INSTALLER.name, home


def _run(installer, home, *args):
    env = dict(os.environ, HOME=str(home))
    env.pop("KIPI_REGISTRY_FILE", None)
    return subprocess.run(["/bin/bash", str(installer), *args], capture_output=True, text=True, env=env)


def test_installer_refuses_in_an_instance_and_writes_nothing(tmp_path):
    root, installer, home = _tree(tmp_path, "instance", tmp_path / "elsewhere" / "kipi-system")
    out = tmp_path / "rendered.plist"
    r = _run(installer, home, "--render-only", str(out))
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "skeleton-only" in r.stderr and "Nothing written" in r.stderr
    assert not out.exists() and not (home / "Library").exists()


def test_installer_refuses_without_a_registry(tmp_path):
    root, installer, home = _tree(tmp_path, "bare", tmp_path / "bare")
    (root / "instance-registry.json").unlink()
    r = _run(installer, home, "--render-only", str(tmp_path / "x.plist"))
    assert r.returncode == 2 and "skeleton-only" in r.stderr
    assert not (tmp_path / "x.plist").exists()


def test_installer_renders_the_template_in_the_skeleton(tmp_path):
    root, installer, home = _tree(tmp_path, "skeleton", tmp_path / "skeleton")
    out = tmp_path / "rendered.plist"
    r = _run(installer, home, "--render-only", str(out))
    assert r.returncode == 0, r.stderr
    rendered = out.read_text()
    assert "__KIPI_REPO__" not in rendered and "__HOME__" not in rendered and "__USER__" not in rendered
    assert f"{root.resolve()}/q-system/.q-system/scripts/lessons-daily.sh" in rendered
    assert f"<key>HOME</key><string>{home}</string>" in rendered
    assert "<string>com.kipi.lessons-daily</string>" in rendered


def test_installer_has_one_source_for_the_plist():
    src = INSTALLER.read_text()
    assert "install-plist.sh" in src and "lessons-daily" in src
    assert "cat >" not in src and "<plist" not in src, "the installer must render the template, not carry its own plist"
    assert 'LABEL="com.kipi' not in src


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
