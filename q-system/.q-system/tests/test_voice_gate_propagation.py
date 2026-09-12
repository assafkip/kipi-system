#!/usr/bin/env python3
"""RED FIRST. ASK-1304 (promoted from sp-0b8bec0d, source ASK-1197).

The fanout-LOSS hazard for voice-stop-gate.py is that `kipi update` rsyncs the
skeleton's copy over an instance copy that is AHEAD, destroying behaviour the
instance's own suite asserts. That happened twice in one afternoon on 2026-09-06
(sp-745f5962, sp-1ad08728) and the only check for it lived on a machine holding
the 25 instance clones. This suite pins a runner that FAILS LOUDLY there and
leaves a manifest CI can load.

Every tree here is tmp; the registry is a fixture. The ONE assertion that needs
the real fleet carries the ONE skip in this file, and
`test_exactly_one_skip_site_lives_in_this_file` pins that count so a second skip
cannot hide inside it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CHECK = SCRIPTS / "voice-gate-propagation-check.py"
PLIST = SCRIPTS / "com.kipi.voice-gate-propagation.plist"
GATE_REL = "q-system/.q-system/scripts/voice-stop-gate.py"

SKELETON_GATE = "def main():\n    return 0\n"
AHEAD_GATE = SKELETON_GATE + "\ndef enforce_route_receipt():\n    raise SystemExit(2)\n"


def _mod():
    spec = importlib.util.spec_from_file_location("voice_gate_propagation_check", CHECK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _git(root, *args):
    base = ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t"]
    return subprocess.run(base + list(args), capture_output=True, text=True, check=True)


def _fixture(tmp_path, instances=("consulting",), skeleton_path=None, commit=True):
    """A skeleton git repo plus one clone per name, both holding the gate file."""
    root = tmp_path / "skeleton"
    (root / GATE_REL).parent.mkdir(parents=True)
    (root / GATE_REL).write_text(SKELETON_GATE)
    clones = {}
    for name in instances:
        clone = tmp_path / name
        (clone / GATE_REL).parent.mkdir(parents=True)
        (clone / GATE_REL).write_text(SKELETON_GATE)
        clones[name] = clone
    (root / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(skeleton_path or root)},
        "instances": [{"name": n, "path": str(p)} for n, p in clones.items()]}))
    if commit:
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "base")
    return root, clones


def _run(root, *args, env_extra=None):
    env = dict(os.environ)
    env.pop("KIPI_TRIGGER", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(CHECK), "--root", str(root), *args],
                          capture_output=True, text=True, env=env, timeout=120)


# ---- the fanout-LOSS assertion, on synthetic trees (runs everywhere) ----------

def test_an_instance_ahead_of_the_skeleton_is_red(tmp_path):
    """THE REPRODUCER. The instance holds content the skeleton never had, so the
    next sync destroys it. Exit 2, the instance named, the word AHEAD present."""
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "consulting" in r.stdout and "AHEAD" in r.stdout, r.stdout


def test_a_synced_fleet_is_green(tmp_path):
    root, clones = _fixture(tmp_path)
    r = _run(root)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "AHEAD" not in r.stdout and "synced" in r.stdout, r.stdout


def test_an_instance_merely_behind_the_skeleton_is_not_loss(tmp_path):
    """A digest mismatch alone is not the hazard. The instance holding an OLDER
    skeleton version loses nothing to the next sync; calling that red would make
    the runner red on a normal fleet, which is how a gate gets switched off."""
    root, clones = _fixture(tmp_path)
    (root / GATE_REL).write_text(SKELETON_GATE + "\n# a later skeleton line\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "skeleton moved on")
    r = _run(root)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "behind" in r.stdout and "AHEAD" not in r.stdout, r.stdout


def test_an_instance_without_the_gate_file_says_could_not_read(tmp_path):
    """Never silently green: an unreadable instance is unknown, not synced.

    The EXIT CODE is the assertion that was missing here (PR #339 review, major).
    An instance that is genuinely ahead but unreadable at 06:30 -- a permission,
    a renamed directory, a stale registry row, a mid-sync moment -- used to score
    exit 0 with fingerprint `green`, so the one branch the docstring promised was
    never silently green was exactly the branch that was.
    """
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).unlink()
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "COULD NOT READ" in r.stdout, r.stdout
    assert "UNANSWERED" in r.stdout and "consulting" in r.stdout, r.stdout
    assert "synced" not in r.stdout.split("consulting")[-1].splitlines()[0]


def test_a_registry_with_zero_instances_is_not_a_clean_fleet(tmp_path):
    """lessons/zero-selected-items-is-a-failure-not-a-pass. A registry the run
    could parse but that names no instance means the scan covered nothing, which
    has the same bytes as a healthy fleet and none of the meaning."""
    root, _ = _fixture(tmp_path, instances=())
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "UNANSWERED" in r.stdout and "no instances in the registry" in r.stdout


def test_the_runner_refuses_unless_its_root_is_the_registry_skeleton(tmp_path):
    """a-fan-out-installer-must-refuse-where-its-job-cannot-run: this script sits
    under the fanned-out scripts dir, so all 25 instances carry it. Run in one, it
    would compare the fleet against an instance and call the skeleton drifted."""
    root, clones = _fixture(tmp_path, skeleton_path=tmp_path / "elsewhere")
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "skeleton: COULD NOT READ" in r.stdout, r.stdout
    assert "AHEAD" not in r.stdout


# ---- the alert: once, on state change, and only under the plist marker --------

def test_run_by_hand_prints_and_files_nothing(tmp_path):
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    m = _mod()
    filed = []
    out = m.run(str(root), notify=lambda msg: filed.append(msg), trigger=None)
    assert filed == [] and out["alert"]["skipped"] is True
    assert "not launched by the plist" in out["alert"]["reason"]


def test_the_alert_fires_once_per_state_change_not_once_per_run(tmp_path):
    """founder-notifications.md: alert on state change, once. A ticket every run
    while the fleet stays red is how an alert channel gets muted."""
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    m = _mod()
    filed = []
    notify = lambda msg: filed.append(msg)
    assert m.run(str(root), notify=notify, trigger="launchd")["alert"]["filed"] is True
    assert len(filed) == 1, filed
    m.run(str(root), notify=notify, trigger="launchd")          # still red, same fleet
    assert len(filed) == 1, "a second identical red must not file again"
    (clones["consulting"] / GATE_REL).write_text(SKELETON_GATE)  # recovered
    m.run(str(root), notify=notify, trigger="launchd")
    assert len(filed) == 2, "a red -> green transition is a state change"
    assert "recovered" in filed[1].lower(), filed[1]


def test_the_first_launchd_run_on_a_green_fleet_records_state_and_files_nothing(tmp_path):
    """PR #339 review, minor. On install `previous` is "" and `current` is
    "green", which is a state CHANGE by string comparison and was filed as
    "recovered" -- a ticket somebody closes by hand for a condition that never
    fired. `is_noise()` in alert-to-linear does not match that string, so it
    really does become a real ticket. Recovery still has to fire, so the state is
    RECORDED on that first quiet run rather than the run being skipped outright.
    """
    root, clones = _fixture(tmp_path)
    m = _mod()
    filed = []
    notify = lambda msg: filed.append(msg)
    out = m.run(str(root), notify=notify, trigger="launchd")
    assert filed == [], filed
    assert out["alert"]["skipped"] is True and "first run" in out["alert"]["reason"]
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)   # now it goes red
    assert m.run(str(root), notify=notify, trigger="launchd")["alert"]["filed"] is True
    assert len(filed) == 1, "the quiet first run must not have muted the real one"


def test_an_instance_that_cannot_be_read_files_once_not_every_run(tmp_path):
    """The unanswered set is part of the STATE, not just the exit code. Left out
    of the fingerprint an unreadable instance would either never alert or alert
    on every run, and a channel that repeats an unchanged condition stops being
    read (founder-notifications.md)."""
    root, clones = _fixture(tmp_path, instances=("consulting", "intel"))
    (clones["consulting"] / GATE_REL).unlink()
    m = _mod()
    filed = []
    notify = lambda msg: filed.append(msg)
    assert m.run(str(root), notify=notify, trigger="launchd")["alert"]["filed"] is True
    assert len(filed) == 1 and "consulting" in filed[0], filed
    m.run(str(root), notify=notify, trigger="launchd")
    assert len(filed) == 1, "the same unreadable instance must not file again"
    (clones["intel"] / GATE_REL).unlink()                      # the set changed
    m.run(str(root), notify=notify, trigger="launchd")
    assert len(filed) == 2, "a second unreadable instance is a new state"


def test_the_summary_leads_the_message_so_a_truncated_title_still_names_it(tmp_path):
    """PR #339 review, minor. alert-to-linear flattens the message to one line
    and truncates it for the ticket title, so a RED summary printed AFTER 25
    per-instance rows gives Sana a title reading "X: synced Y: synced...". The
    truncator is imported from the consumer that owns it rather than restated
    here: a copied 110 stops being the real bound the day that file changes."""
    names = tuple(f"inst{i:02d}" for i in range(25))
    root, clones = _fixture(tmp_path, instances=names)
    (clones["inst23"] / GATE_REL).write_text(AHEAD_GATE)
    m = _mod()
    message = m.render(m.scan(str(root)))
    spec = importlib.util.spec_from_file_location("a2l", SCRIPTS / "alert-to-linear.py")
    a2l = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a2l)
    title = a2l.title_for(message)
    assert "inst23" in title, title
    assert message.splitlines()[1].startswith("RED"), message.splitlines()[:3]


def test_a_launchd_run_whose_alert_did_not_file_exits_nonzero(tmp_path):
    """engineering_route.py::send: an absent notifier is not a filing. A red
    fleet whose only alert vanished behind exit 0 is read as fine by launchd."""
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    m = _mod()

    def broken(_msg):
        raise RuntimeError("slack-notify.sh exited 1")

    out = m.run(str(root), notify=broken, trigger="launchd")
    assert out["alert"]["filed"] is False and out["alert"]["error"], out["alert"]


# ---- the manifest CI can load ------------------------------------------------

def test_the_run_writes_a_manifest_ci_could_load(tmp_path):
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    r = _run(root)
    assert r.returncode == 2
    manifest = root / "q-system" / "output" / "voice-gate-propagation.json"
    data = json.loads(manifest.read_text())
    assert data["red"] is True and data["generated_at"]
    rows = {row["name"]: row["state"] for row in data["instances"]}
    assert rows == {"consulting": "ahead"}, rows


# ---- the live fleet: the ONE skip in this file -------------------------------

def test_the_real_fleet_has_no_instance_ahead_of_this_checkout():
    """CI-ONLY SKIP. The fanout-LOSS hazard is a property of the 25 instance
    clones, which exist on the founder's machine and nowhere in CI. The synthetic
    trees above pin the SCANNER; only this runs it against the fleet, and the
    scheduled plist is what makes it run where the clones are. Skipping here is
    correct; the runner not existing anywhere that fails loudly was the defect.
    """
    root = HERE.parent.parent.parent
    registry = root / "instance-registry.json"
    if not registry.exists():
        pytest.skip("no instance-registry.json: not a fleet checkout (CI)")
    m = _mod()
    report = m.scan(str(root))
    if report["skeleton_ok"] is False or not any(
            row["state"] != "could-not-read" for row in report["instances"]):
        pytest.skip("no readable sibling clones: not the fleet machine (CI)")
    ahead = [row["name"] for row in report["instances"] if row["state"] == "ahead"]
    assert ahead == [], f"these instances lose behaviour on the next sync: {ahead}"


def test_exactly_one_skip_site_lives_in_this_file():
    """The skip above is load-bearing and CI-only. Asserting its COUNT is what
    stops a second skip hiding inside the first one's justification: a suite that
    quietly skips its way to green reads exactly like a passing one."""
    src = Path(__file__).read_text()
    # the needle is ASSEMBLED, never written out: the first cut spelled it
    # literally and then counted its own pattern string as a third skip site. A
    # counter that matches itself measures the counter, not the suite.
    needle = "pytest" + "." + "skip("
    marker = "pytest" + "." + "mark" + "." + "skip"
    sites = re.findall(re.escape(needle) + "|" + re.escape(marker), src)
    assert len(sites) == 2, f"expected the 2 skip calls of ONE CI-only test, found {sites}"
    body = src.split("def test_the_real_fleet_has_no_instance_ahead_of_this_checkout")[1]
    body = body.split("def test_exactly_one_skip_site")[0]
    assert body.count(needle) == 2, "both skips belong to the live-fleet test"
    assert "CI-ONLY SKIP" in body, "the skip has to say it is CI-only in the file"


# ---- wiring -----------------------------------------------------------------

def test_the_plist_runs_it_and_carries_no_machine_path():
    src = PLIST.read_text()
    for placeholder in ("__KIPI_REPO__", "__HOME__", "__USER__"):
        assert placeholder in src, placeholder
    assert "/Users/" not in src, "a literal home path would fan out to 25 instances"
    assert "voice-gate-propagation-check.py</string>" in src
    assert "<key>KIPI_TRIGGER</key><string>launchd</string>" in src
    assert "<string>com.kipi.voice-gate-propagation</string>" in src
    assert "kipi-scope: skeleton-only" in src, "install-plist.sh --all honours this marker"


def test_this_file_runs_its_own_tests_under_python3():
    """The capability manifest declares runner `python3`, so without the
    __main__ block below `python3 <this file>` exits 0 having run nothing, and
    the gate reports a vacuous pass. The negative half (-k matching no test)
    proves the entry can still go red.

    The inner run returns early rather than calling pytest.skip, on purpose:
    test_exactly_one_skip_site_lives_in_this_file pins the skip count at the ONE
    CI-only site, and a guard skip here would spend that budget on bookkeeping.
    """
    if os.environ.get("KIPI_SELFTEST_INNER"):
        return
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env, timeout=300)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"],
                          capture_output=True, text=True, env=env, timeout=120)
    assert none.returncode != 0, "a run selecting zero tests must not report success"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
