#!/usr/bin/env python3
"""fleet-full-suite-scan.py against a stubbed GitHub and throwaway checkouts.

No network: `gh` is a recording stub (KIPI_GH) answering from a table, and the
alert is a recording stub (KIPI_ALERT_CMD). State lives under tmp_path. Holds:
  * the population is READ, and an empty listing exits 2, never an all-clear
  * a PR/push door is found; a disabled workflow and the nightly class are not
  * the slow-step estimator sees a suite hidden inside a script
  * a local pre-push door is found only in a checkout whose origin is the owner's
  * the alert fires on a state change and stays quiet on a repeat
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fleet-full-suite-scan.py"
OWNER = "acme"

FULL = "on:\n  pull_request:\njobs:\n  j:\n    steps:\n      - run: pytest tests/\n"
NIGHTLY = "on:\n  schedule:\n    - cron: '0 9 * * *'\njobs:\n  j:\n    steps:\n      - run: pytest tests/\n"
HIDDEN = "on:\n  push:\njobs:\n  j:\n    steps:\n      - name: Run build gate\n        run: python3 build.py\n"

STUB = r'''
import json, sys
table = json.load(open(sys.argv[1]))
key = " ".join(sys.argv[2:])
with open(sys.argv[1] + ".calls", "a") as f:
    f.write(key + "\n")
rc, out = table.get(key, [1, "gh: Not Found (HTTP 404)"])
print(out)
sys.exit(rc)
'''


def _b64(s):
    return {"content": base64.b64encode(s.encode()).decode()}


def _table(repos):
    t = {"api user": [0, json.dumps({"login": OWNER})],
         f"repo list {OWNER} --limit 500 --no-archived --json name,defaultBranchRef":
             [0, json.dumps([{"name": r, "defaultBranchRef": {"name": "main"}} for r in repos])]}
    wf = f"repos/{OWNER}/app/contents/.github/workflows?ref=main"
    t[f"api {wf}"] = [0, json.dumps([{"path": ".github/workflows/full.yml"},
                                      {"path": ".github/workflows/off.yml"},
                                      {"path": ".github/workflows/nightly.yml"},
                                      {"path": ".github/workflows/hidden.yml"}])]
    t[f"api repos/{OWNER}/app/actions/workflows?per_page=100"] = [0, json.dumps({"workflows": [
        {"path": ".github/workflows/full.yml", "state": "active", "id": 1},
        {"path": ".github/workflows/off.yml", "state": "disabled_manually", "id": 2},
        {"path": ".github/workflows/nightly.yml", "state": "active", "id": 3},
        {"path": ".github/workflows/hidden.yml", "state": "active", "id": 4}]})]
    for name, text in (("full", FULL), ("off", FULL), ("nightly", NIGHTLY), ("hidden", HIDDEN)):
        t[f"api repos/{OWNER}/app/contents/.github/workflows/{name}.yml?ref=main"] = [0, json.dumps(_b64(text))]
    for wid, rid in ((1, 11), (4, 44)):
        t[f"api repos/{OWNER}/app/actions/workflows/{wid}/runs?status=success&per_page=1"] = \
            [0, json.dumps({"workflow_runs": [{"id": rid}]})]
    step = lambda n, a, b: {"name": n, "started_at": f"2026-10-01T00:{a}Z", "completed_at": f"2026-10-01T00:{b}Z"}
    t[f"api repos/{OWNER}/app/actions/runs/11/jobs"] = [0, json.dumps({"jobs": [{"steps": [step("pytest", "00:00", "00:10")]}]})]
    t[f"api repos/{OWNER}/app/actions/runs/44/jobs"] = [0, json.dumps({"jobs": [{"steps": [step("Run build gate", "00:00", "05:49")]}]})]
    return t


def _run(tmp_path, table, *extra):
    tf = tmp_path / "gh.json"
    tf.write_text(json.dumps(table))
    stub = tmp_path / "gh_stub.py"
    stub.write_text(STUB)
    alerts = tmp_path / "alerts.txt"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(KIPI_GH=f"{sys.executable} {stub} {tf}",
               KIPI_ALERT_CMD=f"{sys.executable} -c \"import sys; open('{alerts}','a').write(sys.argv[1]+chr(10))\"",
               HOME=str(tmp_path))
    p = subprocess.run([sys.executable, str(SCRIPT), "--json", "--state-dir", str(tmp_path / "state"),
                        "--registry", str(tmp_path / "none.json"), *extra],
                       env=env, capture_output=True, text=True)
    lines = alerts.read_text().splitlines() if alerts.exists() else []
    return p, lines


def _checkout(root: Path, name: str, origin: str, hook: str):
    d = root / name
    d.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(d)], check=True, env=env)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin", origin], check=True, env=env)
    h = d / ".git" / "hooks" / "pre-push"
    h.write_text(hook)
    return d


def test_ci_doors_disabled_nightly_and_hidden(tmp_path):
    p, alerts = _run(tmp_path, _table(["app"]), "--no-local")
    assert p.returncode == 1, p.stderr
    rep = json.loads(p.stdout)
    assert [d["door"] for d in rep["doors"]] == [".github/workflows/full.yml"], rep["doors"]
    assert [(s["door"], s["seconds"]) for s in rep["slow_steps"]] == [(".github/workflows/hidden.yml", 349)]
    assert len(alerts) == 1 and "1 open" in alerts[0], alerts


def test_an_exempted_workflow_that_grew_slow_is_still_reported(tmp_path):
    t = _table(["app"])
    exempt = "# full-suite-exempt: 20s measured on run 1 (2026-10-01)\n" + HIDDEN
    t[f"api repos/{OWNER}/app/contents/.github/workflows/hidden.yml?ref=main"] = [0, json.dumps(_b64(exempt))]
    p, _ = _run(tmp_path, t, "--no-local")
    rep = json.loads(p.stdout)
    assert [(s["door"], s["seconds"]) for s in rep["slow_steps"]] == [(".github/workflows/hidden.yml", 349)]


def test_a_repeat_is_quiet_and_a_change_alerts(tmp_path):
    t = _table(["app"])
    _, a1 = _run(tmp_path, t, "--no-local")
    _, a2 = _run(tmp_path, t, "--no-local")
    assert len(a2) == len(a1) == 1, "the same doors twice is one alert, not two"
    t[f"api repos/{OWNER}/app/contents/.github/workflows/full.yml?ref=main"] = \
        [0, json.dumps(_b64(FULL.replace("pytest tests/", "pytest tests/test_a.py")))]
    p, a3 = _run(tmp_path, t, "--no-local")
    assert len(a3) == 2 and "0 open" in a3[-1], a3


def test_an_empty_population_is_a_failure_not_an_all_clear(tmp_path):
    p, alerts = _run(tmp_path, _table([]), "--no-local")
    assert p.returncode == 2 and alerts == [], (p.returncode, p.stderr)


def test_local_hook_door_only_in_the_owners_checkouts(tmp_path):
    root = tmp_path / "projects"
    _checkout(root, "mine", f"https://github.com/{OWNER}/mine.git", "#!/bin/sh\npython3 -m pytest\n")
    _checkout(root, "theirs", "https://github.com/someone-else/theirs.git", "#!/bin/sh\npython3 -m pytest\n")
    _checkout(root, "scoped", f"git@github.com:{OWNER}/scoped.git",
              "#!/bin/sh\nbash q-system/.q-system/verify.sh --changed\n")
    p, _ = _run(tmp_path, _table(["app"]), "--no-ci", "--projects-root", str(root))
    rep = json.loads(p.stdout)
    assert [(d["repo"], d["door"]) for d in rep["doors"]] == [("mine", "pre-push")], rep["doors"]
    assert rep["checkouts_scanned"] == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
