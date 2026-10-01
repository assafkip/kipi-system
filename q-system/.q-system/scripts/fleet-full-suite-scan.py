#!/usr/bin/env python3
"""fleet-full-suite-scan.py -- every repo of the account, every door that can run
a WHOLE test suite on a PR, a push or a local hook (RULE-2026-10-01-A).

WHY. Founder bar, 2026-10-01: "no 6000-test runs on small changes". Full-suite
runs kept returning through doors nobody had listed, in repos nobody had scanned.
A hand-made list of repos missed the very repo the rule was written in. So the
population is read at RUN TIME, never written down here: the repos come from
`gh repo list <owner>`, the owner from `gh api user`, the local checkouts from
instance-registry.json plus the git repos one level under the projects root.

WHAT IT READS (never writes to any repo, never runs a test or a hook):
  * CI: each repo's .github/workflows on its default branch, skipping workflows
    GitHub reports as disabled. Judged by full_suite_doors.workflow_doors, so
    the nightly class and measured exemptions (<60s, with a run id) pass.
  * local: lefthook.yml and the pre-commit / pre-push hooks of each checkout
    whose origin is the owner's (core.hooksPath honoured). Judged by hook_doors.

THE ALERT. On a STATE CHANGE only (the set of doors differs from the last run)
it sends one line to the fleet alert path, slack-notify.sh, which files it in
Sana's Linear queue and pages nobody. A daily job that alerts every day on the
same doors is noise; a door opening or closing is the event.

SINGLE WRITER of its state file (~/.config/kipi/fleet-full-suite/state.json).

EXIT: 0 no doors and no slow test step, 1 either, 2 could not read the population (an empty
listing is a failure, never an all-clear: a scanner that saw nothing must not
report zero doors).

Test seams: KIPI_GH (the gh command, split on spaces), KIPI_ALERT_CMD (the
alert command), --state-dir, --projects-root, --registry.

Usage: fleet-full-suite-scan.py [--owner X] [--no-local] [--no-ci] [--json]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import full_suite_doors as fsd  # noqa: E402

HOOK_NAMES = ("pre-commit", "pre-push")
# THE SECOND ESTIMATOR. Text cannot see a suite run from inside a script a step
# calls (measured 2026-10-01: a build-gate step ran 349s of pytest and the static
# detector read it as clean). A test-like step on a PR/push workflow that took
# longer than this on its last successful run is reported as SLOW, independent of
# what its text says. Its identity, never its duration, goes into the fingerprint,
# so a step that is slow every day alerts once.
SLOW_STEP_S = fsd.EXEMPT_MAX_S
TESTLIKE = __import__("re").compile(r"(?i)test|suite|pytest|gate|verify|jest|vitest")
LEFTHOOK_NAMES = ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")


class ScanError(RuntimeError):
    pass


def gh_cmd() -> list[str]:
    return shlex.split(os.environ.get("KIPI_GH", "gh"))


def gh_json(*args: str):
    p = subprocess.run(gh_cmd() + list(args), capture_output=True, text=True)
    if p.returncode != 0:
        # A failed `gh api` prints its error JSON to STDOUT, so stdout is not data here.
        raise ScanError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout or "null")


def gh_json_or_404(*args: str):
    p = subprocess.run(gh_cmd() + list(args), capture_output=True, text=True)
    if p.returncode != 0:
        if "Not Found" in (p.stdout + p.stderr) or "HTTP 404" in p.stderr:
            return None
        raise ScanError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout or "null")


def scan_ci(owner: str) -> tuple[list[dict], int]:
    repos = gh_json("repo", "list", owner, "--limit", "500", "--no-archived",
                    "--json", "name,defaultBranchRef")
    if not repos:
        raise ScanError(f"gh repo list {owner} returned no repos")
    doors, slow = [], []
    for r in repos:
        name = r["name"]
        branch = (r.get("defaultBranchRef") or {}).get("name") or "main"
        listing = gh_json_or_404("api", f"repos/{owner}/{name}/contents/.github/workflows?ref={branch}")
        if not listing:
            continue
        states, ids = {}, {}
        wfs = gh_json_or_404("api", f"repos/{owner}/{name}/actions/workflows?per_page=100") or {}
        for w in wfs.get("workflows", []):
            states[w.get("path", "")] = w.get("state", "")
            ids[w.get("path", "")] = w.get("id")
        texts = {}

        def read(rel, _name=name, _branch=branch, _texts=texts):
            if rel not in _texts:
                blob = gh_json_or_404("api", f"repos/{owner}/{_name}/contents/{rel}?ref={_branch}")
                _texts[rel] = (base64.b64decode(blob["content"]).decode("utf-8", "replace")
                               if blob and blob.get("content") else None)
            return _texts[rel]

        for item in listing:
            path = item.get("path", "")
            if not path.endswith((".yml", ".yaml")):
                continue
            if states.get(path, "active") != "active":
                continue            # disabled on GitHub: it runs on nothing
            text = read(path)
            if text is None:
                continue
            for d in fsd.resolve_local(fsd.workflow_doors(text), read):
                doors.append({"repo": name, "where": "ci", "door": path, "what": d})
            # An exemption does NOT silence the estimator (theia PR #6 review): it
            # certifies "under 60s", and this is the only code that notices when
            # that stops being true. Without it the line's "re-measure" had no reader.
            if fsd.runs_on_pr_or_push(text) and ids.get(path):
                slow += slow_steps(owner, name, path, ids[path])
    return doors, len(repos), slow


def _secs(a: str | None, b: str | None) -> int | None:
    from datetime import datetime
    if not a or not b:
        return None
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int((f(b) - f(a)).total_seconds())


def slow_steps(owner: str, repo: str, path: str, wid) -> list[dict]:
    runs = gh_json_or_404("api", f"repos/{owner}/{repo}/actions/workflows/{wid}/runs"
                          "?status=success&per_page=1") or {}
    out = []
    for run in runs.get("workflow_runs", [])[:1]:
        jobs = gh_json_or_404("api", f"repos/{owner}/{repo}/actions/runs/{run['id']}/jobs") or {}
        for job in jobs.get("jobs", []):
            for st in job.get("steps", []):
                s = _secs(st.get("started_at"), st.get("completed_at"))
                if s is not None and s > SLOW_STEP_S and TESTLIKE.search(st.get("name", "")):
                    out.append({"repo": repo, "door": path, "step": st["name"],
                                "seconds": s, "run": run["id"]})
    return out


def _git(path: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                        "GIT_OBJECT_DIRECTORY")}
    p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=env)
    return p.stdout.strip() if p.returncode == 0 else ""


def local_checkouts(registry: Path | None, projects_root: Path | None) -> list[Path]:
    cands = []
    if registry and registry.is_file():
        reg = json.loads(registry.read_text())
        cands.append((reg.get("skeleton") or {}).get("path"))
        for key in ("instances", "standalone"):
            cands += [e.get("path") for e in reg.get(key, []) if isinstance(e, dict)]
    if projects_root and projects_root.is_dir():
        cands += [str(p) for p in sorted(projects_root.iterdir()) if (p / ".git").exists()]
    seen, out = set(), []
    for c in cands:
        if not c or not Path(c).is_dir():
            continue
        top = _git(Path(c), "rev-parse", "--show-toplevel")
        if top and top not in seen:
            seen.add(top)
            out.append(Path(top))
    return out


def scan_local(owner: str, checkouts: list[Path]) -> list[dict]:
    doors = []
    for top in checkouts:
        url = _git(top, "remote", "get-url", "origin")
        if f"/{owner}/" not in url and f":{owner}/" not in url:
            continue
        repo = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        hooks = _git(top, "config", "--get", "core.hooksPath")
        hook_dir = Path(hooks) if hooks else Path(_git(top, "rev-parse", "--path-format=absolute",
                                                       "--git-path", "hooks") or top / ".git" / "hooks")
        if not hook_dir.is_absolute():
            hook_dir = top / hook_dir
        files = [hook_dir / h for h in HOOK_NAMES] + [top / n for n in LEFTHOOK_NAMES]
        for f in files:
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            for d in fsd.hook_doors(text):
                doors.append({"repo": repo, "where": "local", "door": f.name, "what": d})
    return doors


def fingerprint(doors: list[dict], slow: list[dict] = ()) -> str:
    keys = sorted(f"{d['repo']}|{d['where']}|{d['door']}|{d['what']}" for d in doors)
    keys += sorted(f"slow|{s['repo']}|{s['door']}|{s['step']}" for s in slow)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def write_state(state_dir: Path, report: dict) -> dict | None:
    """The ONE writer of state.json. Returns the previous state, if any."""
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "state.json"
    prev = None
    if f.is_file():
        try:
            prev = json.loads(f.read_text())
        except ValueError:
            prev = None             # a corrupt state reads as "changed", never as quiet
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True))
    os.replace(tmp, f)
    return prev


def alert(line: str) -> None:
    cmd = os.environ.get("KIPI_ALERT_CMD")
    argv = shlex.split(cmd) if cmd else ["bash", str(HERE / "slack-notify.sh")]
    subprocess.run(argv + [line], capture_output=True, text=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--owner", default="")
    ap.add_argument("--no-ci", action="store_true")
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-alert", action="store_true", help="measure only; never alert")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--projects-root", default="")
    ap.add_argument("--registry", default="")
    a = ap.parse_args(argv)

    home = Path.home()
    state_dir = Path(a.state_dir) if a.state_dir else home / ".config" / "kipi" / "fleet-full-suite"
    projects_root = Path(a.projects_root) if a.projects_root else home / "projects"
    registry = Path(a.registry) if a.registry else HERE.parents[2] / "instance-registry.json"
    try:
        owner = a.owner or gh_json("api", "user")["login"]
        doors, nrepos, slow = ([], 0, []) if a.no_ci else scan_ci(owner)
        nlocal = 0
        if not a.no_local:
            cos = local_checkouts(registry, projects_root)
            nlocal = len(cos)
            doors += scan_local(owner, cos)
    except (ScanError, KeyError, ValueError) as exc:
        print(f"fleet-full-suite-scan: could not read the population: {exc}", file=sys.stderr)
        return 2

    report = {"doors": doors, "slow_steps": slow, "fingerprint": fingerprint(doors, slow),
              "repos_scanned": nrepos, "checkouts_scanned": nlocal}
    prev = write_state(state_dir, report)
    changed = prev is None or prev.get("fingerprint") != report["fingerprint"]
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"fleet-full-suite-scan: {len(doors)} door(s) across {nrepos} repo(s) "
              f"and {nlocal} local checkout(s)")
        for d in doors:
            print(f"  {d['repo']} [{d['where']}] {d['door']}: {d['what'][:160]}")
        for s in slow:
            print(f"  SLOW {s['repo']} {s['door']} step '{s['step']}': {s['seconds']}s on run {s['run']}")
    if changed and not a.no_alert:
        was = len((prev or {}).get("doors", [])) if prev else "unknown"
        where = ", ".join(sorted({f"{d['repo']}:{d['door']}" for d in doors}))[:300]
        alert(f"fleet full-suite doors changed: {len(doors)} open (was {was}), "
              f"{len(slow)} slow test step(s). "
              f"{where or 'none open'}. RULE-2026-10-01-A: only the nightly may run a whole suite.")
    return 1 if doors or slow else 0


if __name__ == "__main__":
    sys.exit(main())
