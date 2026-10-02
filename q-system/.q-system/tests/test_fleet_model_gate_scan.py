"""The daily scan lists every model call site that skips the gate (ASK-2395).

why: RCA token-waste-loops (2026-10-02). Caps were put on paths listed from
memory; this scan reads the call sites from source. Every repo here is a temp
git repo; the alert command is a stub, the state dir a temp dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fleet-model-gate-scan.py"


def _env():
    # A hook exports GIT_DIR, and it outranks -C: scrub every GIT_* var.
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _repo(root: Path, name: str, files: dict) -> Path:
    r = root / name
    r.mkdir(parents=True)
    for rel, text in files.items():
        (r / rel).write_text(text)
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(r), *cmd], check=True, env=_env())
    return r


def _run(tmp, *extra, projects="projects"):
    alerts = tmp / "alerts.txt"
    stub = tmp / "alert.sh"
    stub.write_text(f'#!/bin/bash\necho "$*" >> "{alerts}"\n')
    stub.chmod(0o755)
    env = _env()
    env["KIPI_ALERT_CMD"] = str(stub)
    p = subprocess.run([sys.executable, str(SCRIPT), "--registry", str(tmp / "none.json"),
                        "--projects-root", str(tmp / projects), "--state-dir", str(tmp / "state"),
                        "--json", *extra], capture_output=True, text=True, env=env, timeout=120)
    lines = alerts.read_text().splitlines() if alerts.exists() else []
    return p, lines


def _fleet(tmp):
    projects = tmp / "projects"
    _repo(projects, "bot", {
        "run.sh": "#!/bin/bash\nclaude -p \"$PROMPT\"\n",
        "gated.sh": "#!/bin/bash\nbash model-gate.sh --job bot --item o/r#1 -- claude -p \"$PROMPT\"\n",
        "direct.py": "import subprocess\nsubprocess.run(['claude', '-p', 'hi'])\n",
        "routed.py": "import subprocess\nGATE = 'q-system/.q-system/scripts/model-gate.sh'\n"
                     "subprocess.run(['bash', GATE, '--job', 'x', '--', 'claude', '-p', 'hi'])\n",
    })
    return projects


def test_only_the_direct_sites_are_ungated_and_blind_spots_are_printed(tmp_path):
    _fleet(tmp_path)
    p, _ = _run(tmp_path)
    assert p.returncode == 0, p.stderr
    rep = json.loads(p.stdout)
    assert sorted(u["path"] for u in rep["ungated"]) == ["direct.py", "run.sh"]
    assert rep["sites"] == 3  # routed.py is detected and then read as gated
    assert rep["unscanned"]


def test_alerts_once_per_state_change(tmp_path):
    projects = _fleet(tmp_path)
    _, first = _run(tmp_path)
    _, second = _run(tmp_path)
    assert len(first) == 1 and "2 model call sites" in first[0]
    assert len(second) == 1  # same state: no new alert
    (projects / "bot" / "run.sh").write_text("#!/bin/bash\necho no model\n")
    _, third = _run(tmp_path)
    assert len(third) == 2 and "1 model call sites" in third[1]


def test_fail_flag_and_an_empty_population(tmp_path):
    _fleet(tmp_path)
    p, _ = _run(tmp_path, "--fail-on-ungated")
    assert p.returncode == 1
    (tmp_path / "empty").mkdir()
    p, _ = _run(tmp_path, projects="empty")
    assert p.returncode == 2


# --- review round 1 (PR #506) --------------------------------------------------


def test_a_comment_naming_the_door_does_not_gate_a_direct_call(tmp_path):
    _repo(tmp_path / "projects", "bot", {
        "todo.py": "import subprocess\n# TODO: route through model-gate.sh\n"
                   "subprocess.run(['claude', '-p', 'hi'])\n",
        "doc.py": '"""Will route through model-gate.sh"""\nimport subprocess\n'
                  "subprocess.run(['claude', '-p', 'hi'])\n",
    })
    p, _ = _run(tmp_path)
    assert sorted(u["path"] for u in json.loads(p.stdout)["ungated"]) == ["doc.py", "todo.py"]


def test_a_linked_worktree_is_not_a_second_checkout(tmp_path):
    projects = _fleet(tmp_path)
    env = _env()
    subprocess.run(["git", "-C", str(projects / "bot"), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], check=True, env=env)
    subprocess.run(["git", "-C", str(projects / "bot"), "worktree", "add", "-q",
                    str(projects / "bot-wt")], check=True, env=env)
    p, _ = _run(tmp_path)
    rep = json.loads(p.stdout)
    assert rep["checkouts"] == 1 and len(rep["ungated"]) == 2
