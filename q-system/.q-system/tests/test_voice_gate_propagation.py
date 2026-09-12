#!/usr/bin/env python3
"""RED FIRST. ASK-1304 (promoted from sp-0b8bec0d, source ASK-1197).

The fanout-LOSS hazard for voice-stop-gate.py is that `kipi update` rsyncs the
skeleton's copy over an instance copy that is AHEAD, destroying behaviour the
instance's own suite asserts. That happened twice in one afternoon on 2026-09-06
(sp-745f5962, sp-1ad08728) and the only check for it lived on a machine holding
the 25 instance clones. This suite pins a runner that FAILS LOUDLY there and
leaves a local manifest of the scan.

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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CHECK = SCRIPTS / "voice-gate-propagation-check.py"
PLIST = SCRIPTS / "com.kipi.voice-gate-propagation.plist"
GATE_REL = "q-system/.q-system/scripts/voice-stop-gate.py"
REPO = HERE.parent.parent.parent
KIPI_UPDATE = REPO / "kipi-update.sh"
NOTIFY_SH = SCRIPTS / "slack-notify.sh"

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


def _fixture(tmp_path, instances=("consulting",), skeleton_path=None, commit=True,
             updater=True):
    """A skeleton git repo plus one clone per name, both holding the gate file.

    The skeleton also carries a COPY OF THE REAL `kipi-update.sh`, never a
    hand-written stand-in: the check derives the fan-out ref by executing that
    file's own `fleet_ship_ref`, so a fixture updater written here would test
    this fixture's idea of the updater (lessons/fixtures-come-from-producers).
    `updater=False` is the negative: an unresolvable ref must not read green.
    """
    root = tmp_path / "skeleton"
    (root / GATE_REL).parent.mkdir(parents=True)
    (root / GATE_REL).write_text(SKELETON_GATE)
    if updater:
        shutil.copy(KIPI_UPDATE, root / "kipi-update.sh")
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


def test_content_only_on_an_unmerged_branch_is_ahead_not_behind(tmp_path):
    """THE SECOND REPRODUCER (PR #339 review round 3, major). "The skeleton
    shipped it" is the FAN-OUT branch, not every ref in the clone. A blob that
    only ever existed on an unmerged feature branch was never rsynced to any
    instance, so an instance holding it is AHEAD and the next sync destroys it.

    This is the same boundary `kipi-update.sh` was tightened to on #151 round 7,
    and the recorded 2026-09-06 loss says the port was "still on an open PR" --
    exactly this input. Measured in the live clone: 1142 refs, 49 gate blobs
    reachable from --all, 8 from origin/main, so 41 blobs the old walk accepted
    were never shipped anywhere.
    """
    root, clones = _fixture(tmp_path)
    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    _git(root, "checkout", "-q", "-b", "feat/voice-gate-port")
    (root / GATE_REL).write_text(AHEAD_GATE)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "port, never merged")
    _git(root, "checkout", "-q", head)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "AHEAD" in r.stdout and "consulting" in r.stdout, r.stdout
    assert "behind" not in r.stdout, r.stdout


def test_the_fan_out_ref_is_derived_from_kipi_update_not_restated(tmp_path):
    """BOUND, not merely equal (lessons/derive-a-value-from-its-owner). The ref
    order lives in `kipi-update.sh::fleet_ship_ref` and this check executes that
    function out of its own source. Mutating the owner's preference has to move
    the answer; a copy of the list here would agree today and drift silently."""
    root, _ = _fixture(tmp_path)
    m = _mod()
    _git(root, "branch", "-q", "shipped-elsewhere")
    assert m._fan_out_ref(str(root)), "the real updater must resolve a ref"
    src = (root / "kipi-update.sh").read_text()
    mutated = src.replace('for ref in "refs/remotes/origin/$SKELETON_BRANCH"',
                          'for ref in "refs/heads/shipped-elsewhere"', 1)
    assert mutated != src, "the ref list moved in kipi-update.sh; re-pin this test"
    (root / "kipi-update.sh").write_text(mutated)
    assert m._fan_out_ref(str(root)) == "refs/heads/shipped-elsewhere"


def test_an_unresolvable_fan_out_ref_is_unanswered_not_behind(tmp_path):
    """No updater, no answer. Without the ship ref the check cannot tell AHEAD
    from BEHIND, and "cannot tell" must not print as the harmless one."""
    root, clones = _fixture(tmp_path, updater=False)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    r = _run(root)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    # the per-instance STATE, not a substring: the note itself says the words
    # "ahead or behind", and a bare `not in` on the whole message reads that as
    # a verdict the run never rendered.
    assert ": behind" not in r.stdout, r.stdout
    assert "UNANSWERED" in r.stdout and _mod().NO_FAN_OUT_REF in r.stdout, r.stdout
    assert "COULD NOT READ" in r.stdout, r.stdout


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


def test_an_unconfigured_notifier_is_a_setup_state_not_a_filing_failure(tmp_path):
    """PR #339 review round 3, minor. `slack-notify.sh` exit 3 is its own
    documented "no Linear API key configured (a setup state)". Mapped to a send
    FAILURE it made every 06:30 run on a keyless machine exit 2 into a log nobody
    reads, forever, with no ticket -- including on a fleet that is green. Not
    filed is still not filed, so the state is NOT advanced and the next run
    retries the moment a key exists."""
    root, clones = _fixture(tmp_path)
    m = _mod()

    def unconfigured(_msg):
        raise m.NotifierUnconfigured("slack-notify.sh exited 3: no Linear key")

    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    out = m.run(str(root), notify=unconfigured, trigger="launchd")
    assert out["alert"]["error"] == "", out["alert"]
    assert out["alert"]["filed"] is False and out["alert"]["skipped"] is True
    assert "not configured" in out["alert"]["reason"], out["alert"]
    filed = []
    out2 = m.run(str(root), notify=lambda msg: filed.append(msg), trigger="launchd")
    assert out2["alert"]["filed"] is True and len(filed) == 1, \
        "an unconfigured run must not have advanced the state past the real red"


def test_send_maps_the_notifiers_setup_exit_and_not_only_the_injected_fake(tmp_path):
    """The test above injects a fake that RAISES the exception, so it proves how
    `run` reacts and nothing about `_send`. Measured: deleting the rc-3 branch
    from `_send` left it green. This one drives a real notifier that exits 3 and
    one that exits 1, so the mapping itself is what is pinned
    (lessons/test-passes-for-the-wrong-reason)."""
    m = _mod()
    stub = tmp_path / "notify.sh"
    real = m.NOTIFY
    try:
        stub.write_text("#!/bin/bash\nexit %d\n" % m.NOTIFY_UNCONFIGURED_RC)
        m.NOTIFY = str(stub)
        with pytest.raises(m.NotifierUnconfigured):
            m._send("a red fleet")
        stub.write_text("#!/bin/bash\necho boom >&2\nexit 1\n")
        with pytest.raises(RuntimeError):
            m._send("a red fleet")
    finally:
        m.NOTIFY = real


def test_the_setup_exit_code_is_derived_from_slack_notifys_own_contract():
    """The 3 is slack-notify.sh's number, not ours. Read out of its EXIT CONTRACT
    block at test time so a renumbering there fails here instead of silently
    turning a setup state back into a send failure."""
    contract = NOTIFY_SH.read_text().split("EXIT CONTRACT", 1)[1].split("Usage:", 1)[0]
    rows = dict(re.findall(r"^#\s+(\d+)\s+(.*)$", contract, re.M))
    assert rows, "could not parse slack-notify.sh's exit contract"
    setup = [code for code, text in rows.items() if "setup state" in text]
    assert len(setup) == 1, rows
    assert _mod().NOTIFY_UNCONFIGURED_RC == int(setup[0]), rows


# ---- the manifest: a LOCAL run artifact, and the docs say only that -----------

def test_the_run_writes_a_local_manifest_of_the_scan(tmp_path):
    """PR #339 review round 3, minor. This file used to be described as a
    manifest continuous integration could load. It is not: `q-system/output/*.json`
    is gitignored, it is written only where the clones are, and a repo-wide grep
    finds no reader outside this suite. Deleting it would lose a real local
    artifact and adding a fake consumer would be worse, so what changed is the
    CLAIM. The shape is pinned here because a file nothing else parses drifts
    unnoticed. The prose above spells the phrase out rather than using it, for
    the same reason the needle below is assembled."""
    root, clones = _fixture(tmp_path)
    (clones["consulting"] / GATE_REL).write_text(AHEAD_GATE)
    r = _run(root)
    assert r.returncode == 2
    manifest = root / "q-system" / "output" / "voice-gate-propagation.json"
    data = json.loads(manifest.read_text())
    assert data["red"] is True and data["generated_at"]
    assert set(data) >= {"generated_at", "skeleton", "skeleton_ok", "instances",
                         "ahead", "unanswered", "red"}, sorted(data)
    rows = {row["name"]: row["state"] for row in data["instances"]}
    assert rows == {"consulting": "ahead"}, rows
    out = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q",
                          "q-system/output/voice-gate-propagation.json"])
    assert out.returncode == 0, "still gitignored, so no doc may promise CI reads it"
    # the needle is ASSEMBLED for the same reason the skip counter's is: written
    # out, this assertion is itself a match and the check measures the checker.
    needle = "CI " + "can load"
    assert needle not in CHECK.read_text(), "the script must not re-promise it"
    assert needle not in Path(__file__).read_text(), "nor this suite"


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
