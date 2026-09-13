#!/usr/bin/env python3
"""Tests for secret-reach-inventory.py (ASK-1251).

Every fixture lives under a pytest tmp_path: a fake HOME, a fake registry, a
fake decisions.md. The one test that reads the REAL registry and the REAL
decisions.md reads repo files, never a secret path, because the inventory's
job is a promise about those two files agreeing.
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

SECRET_VALUE = "sekrit-VALUE-must-never-print-4417"

DECISIONS_OK = """# Decisions

### RULE-TEST-A: keep the board key
- **Origin:** [SYSTEM-INFERRED]
- **Decision:** `board-key` and `BOARD_TOKEN` stay as they are.
"""


def run(tmp_path, registry, decisions=DECISIONS_OK, env_extra=None, sources=None):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(registry))
    dec = tmp_path / "decisions.md"
    dec.write_text(decisions)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    env.update(env_extra or {})
    cmd = [sys.executable, str(SCRIPT), "--registry", str(reg),
           "--decisions", str(dec), "--home", str(home)]
    for s in sources or []:
        cmd += ["--source", s]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc, home


def base_registry(**over):
    reg = {
        "scan_dirs": ["~/.config/kipi"],
        "shell_files": ["~/.zshrc"],
        "secret_name_re": "(?i)(token|key|secret|password|credential|webhook|proof)",
        "rows": [
            {"id": "board-key", "kind": "file", "path": "~/.config/kipi/board-key",
             "class": "authority", "grants": "writes the board",
             "decision": "RULE-TEST-A"},
            {"id": "BOARD_TOKEN", "kind": "env", "class": "authority",
             "grants": "writes the board", "decision": "RULE-TEST-A"},
            {"id": "PUBLIC_KEY", "kind": "env", "class": "knowledge",
             "grants": "nothing, it is public"},
        ],
    }
    reg.update(over)
    return reg


def write_secret(home, rel, mode=0o600):
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(SECRET_VALUE)
    os.chmod(p, mode)
    return p


def test_all_classified_and_bound_is_green(tmp_path):
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/board-key")
    proc, _ = run(tmp_path, base_registry(), env_extra={"BOARD_TOKEN": SECRET_VALUE})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "board-key" in proc.stdout and "0600" in proc.stdout
    assert "reachable" in proc.stdout


def test_values_are_never_printed(tmp_path):
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/board-key")
    write_secret(home, ".config/kipi/other-webhook")
    (home / ".zshrc").write_text(f"export NEW_TOKEN={SECRET_VALUE}\n")
    proc, _ = run(tmp_path, base_registry(),
                  env_extra={"BOARD_TOKEN": SECRET_VALUE, "ROGUE_KEY": SECRET_VALUE})
    assert SECRET_VALUE not in proc.stdout + proc.stderr


def test_unclassified_env_name_goes_red(tmp_path):
    proc, _ = run(tmp_path, base_registry(), env_extra={"ROGUE_API_KEY": SECRET_VALUE})
    assert proc.returncode == 1
    assert "UNCLASSIFIED" in proc.stdout and "ROGUE_API_KEY" in proc.stdout


def test_non_secret_env_name_is_ignored(tmp_path):
    proc, _ = run(tmp_path, base_registry(), env_extra={"EDITOR": "vim"})
    assert proc.returncode == 0, proc.stdout
    assert "EDITOR" not in proc.stdout


def test_shell_export_name_is_discovered(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text(
        "# comment\nexport NEW_TOKEN='x'\nexport BOARD_TOKEN=y\nalias ll='ls -l'\n")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    assert "NEW_TOKEN" in proc.stdout and "~/.zshrc" in proc.stdout


def test_secret_named_file_in_scan_dir_goes_red(tmp_path):
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/slack-webhook")
    write_secret(home, ".config/kipi/notes.txt")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    assert "slack-webhook" in proc.stdout
    assert "notes.txt" not in proc.stdout


def test_absent_declared_file_is_reported_not_red(tmp_path):
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 0, proc.stdout
    assert "absent" in proc.stdout


def test_authority_row_with_missing_decision_goes_red(tmp_path):
    reg = base_registry()
    reg["rows"][0]["decision"] = "RULE-TEST-NOPE"
    proc, _ = run(tmp_path, reg)
    assert proc.returncode == 1
    assert "RULE-TEST-NOPE" in proc.stdout


def test_authority_row_without_decision_field_goes_red(tmp_path):
    reg = base_registry()
    del reg["rows"][1]["decision"]
    proc, _ = run(tmp_path, reg)
    assert proc.returncode == 1
    assert "BOARD_TOKEN" in proc.stdout


def test_decision_that_does_not_name_the_row_goes_red(tmp_path):
    dec = DECISIONS_OK.replace("`board-key` and ", "")
    proc, _ = run(tmp_path, base_registry(), decisions=dec)
    assert proc.returncode == 1
    assert "board-key" in proc.stdout


def test_decision_without_origin_tag_goes_red(tmp_path):
    dec = DECISIONS_OK.replace("[SYSTEM-INFERRED]", "none")
    proc, _ = run(tmp_path, base_registry(), decisions=dec)
    assert proc.returncode == 1
    assert "origin tag" in proc.stdout


def test_empty_registry_refuses(tmp_path):
    proc, _ = run(tmp_path, base_registry(rows=[]))
    assert proc.returncode == 2


def test_unknown_class_refuses(tmp_path):
    reg = base_registry()
    reg["rows"][2]["class"] = "maybe"
    proc, _ = run(tmp_path, reg)
    assert proc.returncode == 2


def test_source_filter_skips_env(tmp_path):
    proc, _ = run(tmp_path, base_registry(), env_extra={"ROGUE_API_KEY": "x"},
                  sources=["file"])
    assert proc.returncode == 0, proc.stdout
    assert "ROGUE_API_KEY" not in proc.stdout


def test_real_registry_binds_every_authority_row_to_a_tagged_decision(tmp_path):
    """The shipped registry and the shipped decisions.md agree.

    Runs with an empty fake HOME and an empty environment so nothing live is
    touched; what is left is the binding check between the two repo files.
    """
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
