#!/usr/bin/env python3
"""ASK-4283: install-rule-gate.sh, every branch, in a sandbox, with no root.

The founder runs the installer once with sudo against the live gate-locked folder, so
each refusal and the rollback must be seen working HERE first: a root-run script that
fails half-way on the live gate is the outage lock-gate.sh's header describes (a hook
pointing at a broken file blocks every tool in every session).

Overrides used (sudo's env_reset drops them on the founder's run): KIPI_GATE_LOCK,
KIPI_GATE_NO_CHOWN=1, KIPI_GATE_BASE_SHA256, KIPI_GATE_REPRODUCER, KIPI_GATE_PYTHON.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.join(HERE, "install-rule-gate.sh")
SOURCE = os.path.join(HERE, "rule_gate.py")
FAKE_BASE = b"# stand-in for the pre-ASK-4283 gate; only its hash is checked\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def lock(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    lk = tmp_path / "gate-locked"
    (lk / "hooks").mkdir(parents=True)
    gate = lk / "hooks" / "rule_gate.py"
    gate.write_bytes(FAKE_BASE)
    # The installed gate self-locates LOCK from these, so its reproducer run stays here.
    (lk / "baseline-v2.json").write_text(json.dumps({"sections": {}, "files": {}}))
    (lk / "managed-settings-path").write_text(str(tmp_path / "no-managed.json"))
    other = str(tmp_path / "other-protected-file")
    (lk / "protected-manifest.json").write_text(
        json.dumps({str(gate): sha(FAKE_BASE), other: "f" * 64}, indent=1))
    return {"tmp": tmp_path, "home": home, "lock": lk, "gate": gate,
            "manifest": lk / "protected-manifest.json", "other": other}


def install(lk, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER", "SUDO_UID")}
    env.update(HOME=str(lk["home"]), KIPI_GATE_LOCK=str(lk["lock"]), KIPI_GATE_NO_CHOWN="1",
               KIPI_GATE_BASE_SHA256=sha(FAKE_BASE), KIPI_GATE_PYTHON=sys.executable)
    env.update(extra)
    return subprocess.run(["bash", INSTALLER], capture_output=True, text=True, env=env, timeout=600)


def test_installer_pins_the_hash_of_the_source_beside_it():
    # The installer and the gate are one unit: editing rule_gate.py without repinning
    # PATCHED_SHA256 must fail here, not on the founder's sudo run.
    text = open(INSTALLER).read()
    pinned = re.search(r'^PATCHED_SHA256="([0-9a-f]{64})"', text, re.M).group(1)
    assert pinned == sha(open(SOURCE, "rb").read())


def test_install_swaps_the_gate_repins_the_manifest_and_keeps_a_backup(lock):
    r = install(lock)
    assert r.returncode == 0, r.stdout + r.stderr
    src = open(SOURCE, "rb").read()
    assert lock["gate"].read_bytes() == src
    man = json.loads(lock["manifest"].read_text())
    assert man[str(lock["gate"])] == sha(src)
    assert man[lock["other"]] == "f" * 64, "the repin touched another manifest row"
    backups = list((lock["lock"] / "backups").glob("*/rule_gate.py"))
    assert len(backups) == 1 and backups[0].read_bytes() == FAKE_BASE
    for n in ("1", "2", "3", "4", "5", "6", "7", "8", "10"):
        assert re.search(rf"^{n}\s+ok:", r.stdout, re.M), f"step {n} did not print ok:\n{r.stdout}"
    assert re.search(r"^9\s+skipped:", r.stdout, re.M)


def test_second_run_is_a_no_op(lock):
    assert install(lock).returncode == 0
    r = install(lock)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already the patched file" in r.stdout
    assert len(list((lock["lock"] / "backups").glob("*"))) == 1


def test_drifted_live_gate_is_refused_and_nothing_changes(lock):
    lock["gate"].write_bytes(FAKE_BASE + b"# someone edited the live gate\n")
    before_gate, before_man = lock["gate"].read_bytes(), lock["manifest"].read_text()
    r = install(lock)
    assert r.returncode == 67, r.stdout + r.stderr
    assert "drifted" in r.stdout
    assert lock["gate"].read_bytes() == before_gate
    assert lock["manifest"].read_text() == before_man
    assert not (lock["lock"] / "backups").exists()


def test_manifest_that_disagrees_with_the_gate_is_refused(lock):
    man = json.loads(lock["manifest"].read_text())
    man[str(lock["gate"])] = "0" * 64
    lock["manifest"].write_text(json.dumps(man))
    r = install(lock)
    assert r.returncode == 67, r.stdout + r.stderr
    assert lock["gate"].read_bytes() == FAKE_BASE


def test_red_reproducer_on_the_installed_gate_rolls_back(lock):
    # Green on the sandboxed source (step 3), red on the installed gate (step 8).
    bad = lock["tmp"] / "test_red_when_installed.py"
    bad.write_text("import os\n\ndef test_x():\n    assert not os.environ.get('RULE_GATE_UNDER_TEST')\n")
    r = install(lock, KIPI_GATE_REPRODUCER=str(bad))
    assert r.returncode == 1, r.stdout + r.stderr
    assert re.search(r"^8\s+FAILED", r.stdout, re.M)
    assert "rolled back" in r.stdout
    assert lock["gate"].read_bytes() == FAKE_BASE, "rollback left the patched gate live"
    assert json.loads(lock["manifest"].read_text())[str(lock["gate"])] == sha(FAKE_BASE)


def test_red_reproducer_on_the_source_touches_nothing_live(lock):
    bad = lock["tmp"] / "test_always_red.py"
    bad.write_text("def test_x():\n    assert False\n")
    r = install(lock, KIPI_GATE_REPRODUCER=str(bad))
    assert r.returncode == 66, r.stdout + r.stderr
    assert lock["gate"].read_bytes() == FAKE_BASE
    assert not (lock["lock"] / "backups").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
