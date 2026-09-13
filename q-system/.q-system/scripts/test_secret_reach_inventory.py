#!/usr/bin/env python3
"""Tests for secret-reach-inventory.py (ASK-1251).

Every fixture lives under a pytest tmp_path: a fake HOME, a fake registry, a
fake decisions.md. This file runs fleet-wide, so it reads no instance-owned
file. The check that the REAL registry and the REAL decisions.md agree lives in
test_secret_reach_registry_binding.py, declared skeleton_only: an instance's
decisions.md does not carry the skeleton's RULE-2026-09-13 sections (PR #345
review, major).
"""

import json
import os
import pathlib
import subprocess
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "secret-reach-inventory.py"

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
    # A timeout, so a hang (the FIFO case) fails the test instead of the suite.
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
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


def test_every_shell_assignment_shape_is_discovered(tmp_path):
    """PR #345 review: the old `^export NAME=` regex saw one shape of five."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".extra").write_text("export SOURCED_TOKEN=v\n")
    (home / ".zshrc").write_text(
        "ASSIGNED_TOKEN=v\nexport ASSIGNED_TOKEN\n"
        "export MULTI_A_TOKEN=v MULTI_B_TOKEN='w x'\n"
        "typeset -x TYPESET_TOKEN=v\n"
        "declare -gx DECLARED_TOKEN=v\n"
        "[ -f ~/.extra ] && source ~/.extra\n"
        "source $ZSH/oh-my-zsh.sh\n")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    for name in ("ASSIGNED_TOKEN", "MULTI_A_TOKEN", "MULTI_B_TOKEN", "TYPESET_TOKEN",
                 "DECLARED_TOKEN", "SOURCED_TOKEN"):
        assert f"[UNCLASSIFIED] {name}" in proc.stdout, name
    assert "[NOT-SCANNED] $ZSH/oh-my-zsh.sh" in proc.stdout


def test_a_function_local_or_a_value_is_not_a_name(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text(
        "f() { local LOCAL_TOKEN=v; }\n"
        "export SAFE=\"a b_TOKEN=c\"\n"
        "echo KEY_TOKEN=v\n")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 0, proc.stdout
    assert "LOCAL_TOKEN" not in proc.stdout and "b_TOKEN" not in proc.stdout
    assert "KEY_TOKEN" not in proc.stdout


def test_a_sourcing_loop_terminates(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("source ~/.zshrc\nexport LOOP_TOKEN=v\n")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    assert proc.stdout.count("[UNCLASSIFIED] LOOP_TOKEN") == 1


def test_nested_secret_file_is_found_but_a_git_checkout_is_not_entered(tmp_path):
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/sub/deeper/nested-token")
    write_secret(home, ".config/kipi/worktrees/wt/.git")
    write_secret(home, ".config/kipi/worktrees/wt/scripts/api_key.py")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    assert "~/.config/kipi/sub/deeper/nested-token" in proc.stdout
    assert "api_key.py" not in proc.stdout


def test_unreadable_profile_and_scan_dir_go_red_by_name(tmp_path):
    """PR #345 review: a permission error used to read exactly like absent."""
    home = tmp_path / "home"
    home.mkdir()
    profile = home / ".zshrc"
    profile.write_text("export HIDDEN_TOKEN=v\n")
    scan = home / ".config" / "kipi"
    scan.mkdir(parents=True)
    profile.chmod(0)
    scan.chmod(0)
    try:
        proc, _ = run(tmp_path, base_registry())
    finally:
        profile.chmod(0o600)
        scan.chmod(0o700)
    assert proc.returncode == 1
    assert "[UNREADABLE] ~/.zshrc: PermissionError" in proc.stdout
    assert "[UNREADABLE] ~/.config/kipi: PermissionError" in proc.stdout


def test_absent_profile_and_scan_dir_stay_quiet(tmp_path):
    proc, _ = run(tmp_path, base_registry(shell_files=["~/.nope"], scan_dirs=["~/.nodir"]))
    assert proc.returncode == 0, proc.stdout
    assert "UNREADABLE" not in proc.stdout


def test_file_row_without_path_refuses_with_exit_2(tmp_path):
    reg = base_registry()
    del reg["rows"][0]["path"]
    proc, _ = run(tmp_path, reg)
    assert proc.returncode == 2
    assert "needs a non-empty path" in proc.stderr and "Traceback" not in proc.stderr


def test_rejected_recommendation_binds_nothing(tmp_path):
    dec = DECISIONS_OK.replace("[SYSTEM-INFERRED]", "[CLAUDE-RECOMMENDED -> REJECTED]")
    proc, _ = run(tmp_path, base_registry(), decisions=dec)
    assert proc.returncode == 1
    assert "binds nothing" in proc.stdout


def test_approved_recommendation_binds(tmp_path):
    dec = DECISIONS_OK.replace("[SYSTEM-INFERRED]", "[CLAUDE-RECOMMENDED -> APPROVED]")
    proc, _ = run(tmp_path, base_registry(), decisions=dec)
    assert proc.returncode == 0, proc.stdout


def glob_registry():
    reg = base_registry(secret_name_re="(?i)(token|key|secret|cookie)")
    reg["rows"] += [
        {"id": "browser-profiles", "kind": "file",
         "glob": "~/.config/kipi/browser-profiles/*", "class": "authority",
         "grants": "logged-in sessions", "decision": "RULE-TEST-A"},
        {"id": "ratchet-acks", "kind": "file", "glob": "~/.config/kipi/ratchet-ack/*",
         "class": "knowledge", "grants": "nothing, a dated receipt"},
    ]
    return reg


def test_glob_row_classifies_a_generated_tree_and_stops_at_its_boundary(tmp_path):
    """PR #345 review rounds 2 and 3: exact paths cannot classify files a
    browser profile or the spillover ratchet keeps minting."""
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/browser-profiles/p1/Default/Cookies")
    write_secret(home, ".config/kipi/browser-profiles/new-one/Default/Trust Tokens")
    write_secret(home, ".config/kipi/ratchet-ack/2026-09-13-token-guard.py-abc")
    write_secret(home, ".config/kipi/browser-profiles-token")
    dec = DECISIONS_OK.replace("`board-key` and", "`board-key`, `browser-profiles` and")
    proc, _ = run(tmp_path, glob_registry(), decisions=dec)
    assert proc.returncode == 1, proc.stdout
    assert "[AUTHORITY] browser-profiles  (file ~/.config/kipi/browser-profiles/p1" in proc.stdout
    assert "[KNOWLEDGE] ratchet-acks" in proc.stdout
    unclassified = [ln for ln in proc.stdout.splitlines() if "[UNCLASSIFIED]" in ln]
    assert len(unclassified) == 1 and "browser-profiles-token" in unclassified[0]


def test_glob_authority_row_needs_its_decision_too(tmp_path):
    home = tmp_path / "home"
    write_secret(home, ".config/kipi/browser-profiles/p1/Default/Cookies")
    proc, _ = run(tmp_path, glob_registry())
    assert proc.returncode == 1
    assert "[UNBOUND] browser-profiles" in proc.stdout


def test_a_glob_that_blankets_a_scan_dir_or_wildcards_a_name_refuses(tmp_path):
    for bad in ("~/.config/kipi/*", "~/.config/kipi/*-profile/*", "~/.config/kipi/x"):
        reg = base_registry()
        reg["rows"].append({"id": "wide", "kind": "file", "glob": bad,
                            "class": "knowledge", "grants": "x"})
        proc, _ = run(tmp_path, reg)
        assert proc.returncode == 2, bad
        assert "glob" in proc.stderr and "Traceback" not in proc.stderr, proc.stderr


def test_shell_keyword_one_liners_are_read(tmp_path):
    """PR #345 review round 3: the gcloud installer writes `if ...; then source ...; fi`."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".extra").write_text("export SOURCED_TOKEN=v\n")
    (home / ".zshrc").write_text(
        "if true; then export THEN_TOKEN=v; fi\n"
        "{ export BRACE_TOKEN=v; }\n"
        "while false; do export DO_TOKEN=v; done\n"
        "if [ -f ~/.extra ]; then source ~/.extra; fi\n"
        "then\n")
    proc, _ = run(tmp_path, base_registry())
    assert proc.returncode == 1
    for name in ("THEN_TOKEN", "BRACE_TOKEN", "DO_TOKEN", "SOURCED_TOKEN"):
        assert f"[UNCLASSIFIED] {name}" in proc.stdout, name


def test_a_fifo_under_a_scan_dir_is_not_opened(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "kipi").mkdir(parents=True)
    os.mkfifo(home / ".config" / "kipi" / "relay-token")
    proc, _ = run(tmp_path, base_registry())
    assert "~/.config/kipi/relay-token  (file, not-regular" in proc.stdout


def test_an_instance_checkout_refuses_without_an_explicit_decisions_file(tmp_path):
    """PR #345 review round 3: instances do not carry the skeleton's decisions."""
    scripts = tmp_path / "inst" / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("secret-reach-inventory.py", "decision-origin-tag-lint.py"):
        (scripts / name).write_text((SCRIPTS / name).read_text())
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(base_registry()))
    cmd = [sys.executable, str(scripts / "secret-reach-inventory.py"),
           "--registry", str(reg), "--home", str(tmp_path / "home")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "instance-registry.json" in proc.stderr
    (tmp_path / "inst" / "instance-registry.json").write_text("{}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode != 2 or "instance-registry.json" not in proc.stderr
