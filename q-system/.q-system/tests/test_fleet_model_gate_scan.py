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


def _run(tmp, *extra, projects="projects", labels=("t.unrelated",), today="2026-10-05", alert_rc=0,
         launchctl_rc=0):
    alerts = tmp / "alerts.txt"
    stub = tmp / "alert.sh"
    stub.write_text(f'#!/bin/bash\necho "$*" >> "{alerts}"\nexit {alert_rc}\n')
    stub.chmod(0o755)
    # SEALED: the real launchctl and the real LaunchAgents dir are never read
    # here. Without these two seams every test would scan this machine's jobs.
    agents = tmp / "agents"
    agents.mkdir(exist_ok=True)
    listing = tmp / "launchctl-list.txt"
    listing.write_text("PID\tStatus\tLabel\n" + "".join(f"-\t0\t{lab}\n" for lab in labels))
    lctl = tmp / "launchctl.sh"
    lctl.write_text(f'#!/bin/bash\ncat "{listing}"\nexit {launchctl_rc}\n')
    lctl.chmod(0o755)
    env = _env()
    env["KIPI_ALERT_CMD"] = str(stub)
    env["KIPI_LAUNCHCTL"] = str(lctl)
    env["KIPI_LAUNCHAGENTS_DIR"] = str(agents)
    env["KIPI_SCAN_TODAY"] = today
    env["HOME"] = str(tmp)  # launchd trees count only under $HOME; tmp is the home here
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

    def _run(tmp):  # state-change lines only; the weekly drain line has its own tests
        p, lines = globals()["_run"](tmp)
        return p, [ln for ln in lines if not ln.startswith("fleet-model-gate-scan weekly:")]

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


def test_the_wrapper_is_gated_only_when_its_code_calls_the_gate(tmp_path):
    """No exemption by path (PR #506 round 2, ASK-2402): the same wrapper bytes are
    ungated until the file actually calls model_gate.check."""
    rel = "plugins/kipi-core/voiceloop/prompt_render.py"
    direct = "import subprocess\n\ndef run_model(p):\n    return subprocess.run(['claude', '-p', p])\n"
    routed = ("import subprocess\nfrom . import model_gate\n\ndef run_model(p):\n"
              "    if not model_gate.check('voiceloop')['admit']:\n        return None\n"
              "    return subprocess.run(['claude', '-p', p])\n")
    projects = tmp_path / "projects"
    for name, text in (("unrouted", direct), ("routed", routed)):
        r = projects / name
        (r / rel).parent.mkdir(parents=True)
        (r / rel).write_text(text)
        for cmd in (["init", "-q"], ["add", "-A"]):
            subprocess.run(["git", "-C", str(r), *cmd], check=True, env=_env())
    p, _ = _run(tmp_path)
    assert p.returncode == 0, p.stderr
    rep = json.loads(p.stdout)
    assert [(Path(u["checkout"]).name, u["path"]) for u in rep["ungated"]] == [("unrouted", rel)]
    assert rep["sites"] == 2


# --- RCA token-burn-recurs-after-gate (2026-10-06, ASK-2540) --------------------


def _plist(tmp, label, workdir=None, args=()):
    import plistlib
    d = {"Label": label, "ProgramArguments": list(args) or ["/bin/true"]}
    if workdir:
        d["WorkingDirectory"] = str(workdir)
    (tmp / "agents").mkdir(exist_ok=True)
    # The filename is NOT the label on purpose: the reader must key on Label.
    with open(tmp / "agents" / f"file-{label}.plist", "wb") as f:
        plistlib.dump(d, f)


def _worktree(projects: Path, wt: Path, files: dict) -> Path:
    """A linked worktree of projects/bot, outside the projects root, carrying a
    call site the main checkout does not have: the live-runner shape."""
    env = _env()
    git = ["git", "-C", str(projects / "bot"), "-c", "user.email=t@t", "-c", "user.name=t"]
    if not subprocess.run(git + ["rev-parse", "-q", "--verify", "HEAD"], env=env,
                          capture_output=True).stdout:
        subprocess.run(git + ["commit", "-qm", "x"], check=True, env=env)
    subprocess.run(git + ["worktree", "add", "-q", "-b", wt.name, str(wt)], check=True, env=env)
    for rel, text in files.items():
        (wt / rel).write_text(text)
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, env=env)
    return wt


def test_a_loaded_launchd_job_running_from_a_linked_worktree_is_scanned(tmp_path):
    """RC#1: the scanner skipped linked worktrees, and every live runner tree is
    one, so the code launchd actually runs was never read."""
    projects = _fleet(tmp_path)
    runners = tmp_path / "runners"
    by_wd = _worktree(projects, runners / "run-a", {"engine.sh": "#!/bin/bash\nclaude -p hi\n"})
    by_arg = _worktree(projects, runners / "run-b",
                       {"argjob.py": "import subprocess\nsubprocess.run(['claude', '-p', 'x'])\n"})
    unloaded = _worktree(projects, runners / "run-c", {"idle.sh": "#!/bin/bash\nclaude -p hi\n"})
    vendor = tmp_path.parent / f"{tmp_path.name}-vendor"  # a git repo OUTSIDE $HOME
    _repo(vendor.parent, vendor.name, {"v.sh": "#!/bin/bash\nclaude -p hi\n"})
    _plist(tmp_path, "t.by-wd", workdir=by_wd)
    _plist(tmp_path, "t.by-arg", args=["/bin/bash", "-lc", f"python3 {by_arg}/argjob.py"])
    _plist(tmp_path, "t.unloaded", workdir=unloaded)
    _plist(tmp_path, "t.vendor", workdir=vendor)
    p, _ = _run(tmp_path, labels=("t.by-wd", "t.by-arg", "t.vendor"))
    assert p.returncode == 0, p.stderr
    rep = json.loads(p.stdout)
    paths = {(Path(u["checkout"]).resolve().name, u["path"]) for u in rep["ungated"]}
    assert ("run-a", "engine.sh") in paths, rep
    assert ("run-b", "argjob.py") in paths, rep
    assert not any(n == "run-c" for n, _ in paths)  # a plist that is not LOADED runs nothing
    assert rep["checkouts"] == 3  # bot + two runner trees, each counted once
    # PR #526 review: a worktree of a counted repo adds only its NEW files, not
    # a second copy of direct.py and run.sh per runner.
    assert len(rep["ungated"]) == 4, rep["ungated"]
    assert rep["sites"] == 5  # run.sh, direct.py, routed.py, engine.sh, argjob.py


def test_an_unreadable_launchctl_refuses_instead_of_filing_progress(tmp_path):
    _fleet(tmp_path)
    p, lines = _run(tmp_path, launchctl_rc=1)
    assert p.returncode == 2 and "launchctl" in p.stderr
    assert lines == [] and not (tmp_path / "state" / "weekly.json").exists()


def test_an_empty_launchctl_listing_is_unreadable_not_no_jobs(tmp_path):
    _fleet(tmp_path)
    p, lines = _run(tmp_path, labels=())
    assert p.returncode == 2 and lines == []


def test_a_checkout_dropping_out_is_not_progress(tmp_path):
    """PR #526 review round 2: a loaded job whose plist stops parsing dropped its
    runner tree, the total fell, "delta -1" was filed and became the baseline."""
    projects = _fleet(tmp_path)
    runner = _worktree(projects, tmp_path / "runners" / "run-a", {"e.sh": "#!/bin/bash\nclaude -p hi\n"})
    _plist(tmp_path, "t.run", workdir=runner)
    p, _ = _run(tmp_path, labels=("t.run",), today="2026-10-05")  # W41: 3 ungated
    assert p.returncode == 0, p.stderr
    (tmp_path / "agents" / "file-t.run.plist").write_text("not a plist")  # still LOADED
    p, lines = _run(tmp_path, labels=("t.run",), today="2026-10-12")
    assert p.returncode == 4, p.stderr  # nothing was fixed
    assert "delta +0" in _weekly(lines)[-1] and "1 checkouts dropped out" in _weekly(lines)[-1]
    _plist(tmp_path, "t.run", workdir=runner)  # repaired, zero code changed
    p, _ = _run(tmp_path, labels=("t.run",), today="2026-10-19")
    assert p.returncode == 4  # still flat, not a phantom regression from a fake baseline
    # Fixing bot/run.sh alone would NOT count: the runner's own copy still runs
    # ungated, and the dedupe then counts it. Fix a file only the runner has.
    (runner / "e.sh").write_text("#!/bin/bash\necho no model\n")
    p, lines = _run(tmp_path, labels=("t.run",), today="2026-10-26")
    assert p.returncode == 0 and "delta -1" in _weekly(lines)[-1], (p.stderr, lines)


def test_zero_ungated_is_green_every_week(tmp_path):
    _repo(tmp_path / "projects", "clean", {"a.sh": "#!/bin/bash\necho hi\n"})
    for day in ("2026-10-05", "2026-10-12", "2026-10-19"):
        p, _ = _run(tmp_path, today=day)
        assert p.returncode == 0, (day, p.returncode, p.stderr)


def test_a_corrupt_weekly_history_refuses_rather_than_resets(tmp_path):
    _fleet(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "weekly.json").write_text("{not json")
    p, _ = _run(tmp_path, today="2026-10-12")
    assert p.returncode == 2 and "weekly.json" in p.stderr


def test_the_baseline_is_the_count_that_was_filed(tmp_path):
    projects = _fleet(tmp_path)
    _run(tmp_path, today="2026-10-05")  # W41 files 2
    (projects / "bot" / "run.sh").write_text("#!/bin/bash\necho no model\n")
    p, _ = _run(tmp_path, today="2026-10-12")  # W42 files 1: fell, green
    assert p.returncode == 0, p.stderr
    for n in ("m1.sh", "m2.sh"):
        (projects / "bot" / n).write_text("#!/bin/bash\nclaude -p hi\n")
    subprocess.run(["git", "-C", str(projects / "bot"), "add", "-A"], check=True, env=_env())
    p, _ = _run(tmp_path, today="2026-10-14")  # same-week regression to 3: red now
    assert p.returncode == 4
    state = json.loads((tmp_path / "state" / "weekly.json").read_text())
    assert state["weeks"]["2026-W42"]["ungated"] == 1  # the filed count, not the last run
    p, _ = _run(tmp_path, today="2026-10-19")  # W43 at 3 vs the filed 1: red
    assert p.returncode == 4


def test_a_runner_tree_already_in_the_registry_population_is_counted_once(tmp_path):
    projects = _fleet(tmp_path)
    _plist(tmp_path, "t.main", workdir=projects / "bot")
    p, _ = _run(tmp_path, labels=("t.main",))
    rep = json.loads(p.stdout)
    assert rep["checkouts"] == 1 and len(rep["ungated"]) == 2


def _weekly(lines):
    return [ln for ln in lines if ln.startswith("fleet-model-gate-scan weekly:")]


def test_the_ungated_count_must_fall_week_over_week(tmp_path):
    """RC#2: 357 ungated four runs in a row and nothing failed. One filing per
    ISO week with the delta, and a red exit when the count did not fall."""
    projects = _fleet(tmp_path)
    p, lines = _run(tmp_path, today="2026-10-05")  # W41, first week: record only
    assert p.returncode == 0, p.stderr
    assert len(_weekly(lines)) == 1 and "2 ungated" in _weekly(lines)[0]
    p, lines = _run(tmp_path, today="2026-10-07")  # same week: no second filing
    assert p.returncode == 0 and len(_weekly(lines)) == 1
    p, lines = _run(tmp_path, today="2026-10-12")  # W42, flat
    assert p.returncode == 4, (p.returncode, p.stderr)
    assert len(_weekly(lines)) == 2 and "delta +0" in _weekly(lines)[1]
    p, _ = _run(tmp_path, today="2026-10-13")  # still flat: still red, not re-filed
    assert p.returncode == 4
    (projects / "bot" / "run.sh").write_text("#!/bin/bash\necho no model\n")
    p, lines = _run(tmp_path, today="2026-10-19")  # W43, fell by one
    assert p.returncode == 0, p.stderr
    assert len(_weekly(lines)) == 3 and "delta -1" in _weekly(lines)[2]


def test_an_undelivered_weekly_filing_is_retried_not_recorded(tmp_path):
    _fleet(tmp_path)
    p, _ = _run(tmp_path, alert_rc=1)
    assert p.returncode == 3
    assert not (tmp_path / "state" / "weekly.json").exists()
    p, lines = _run(tmp_path)
    assert p.returncode == 0 and len(_weekly(lines)) == 1
