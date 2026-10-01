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

EXIT: 0 a completed scan (doors are the alert's job, not the exit code's; with
--fail-on-doors, 1 when any are open), 3 an alert that was not delivered, 2 could not read the population (an empty
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
# Whole words: unanchored, `gate` matched inside "aggregate" and `test` inside
# "latest" and "Attest" (PR #492 review).
TESTLIKE = __import__("re").compile(r"(?i)\b(?:tests?|suites?|pytest|gates?|verify|jest|vitest)\b")
LEFTHOOK_NAMES = ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")


class ScanError(RuntimeError):
    pass


# Every sibling daily job bounds its subprocesses. Without this a hung `gh` held
# the run forever and the watchdog read a hung job as a healthy one (PR #492 review).
GH_TIMEOUT_S = int(os.environ.get("KIPI_GH_TIMEOUT_S", "60"))  # env: test seam


def _gh(args):
    try:
        return subprocess.run(gh_cmd() + list(args), capture_output=True, text=True,
                              timeout=GH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ScanError(f"gh {' '.join(args[:3])} timed out after {GH_TIMEOUT_S}s")


def gh_cmd() -> list[str]:
    return shlex.split(os.environ.get("KIPI_GH", "gh"))


def gh_json(*args: str):
    p = _gh(args)
    if p.returncode != 0:
        # A failed `gh api` prints its error JSON to STDOUT, so stdout is not data here.
        raise ScanError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout or "null")


def gh_json_or_404(*args: str):
    p = _gh(args)
    if p.returncode != 0:
        if "Not Found" in (p.stdout + p.stderr) or "HTTP 404" in p.stderr:
            return None
        raise ScanError(f"gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout or "null")


def scan_ci(owner: str) -> tuple[list[dict], int, list[dict], list[dict]]:
    repos = gh_json("repo", "list", owner, "--limit", "500", "--no-archived",
                    "--json", "name,defaultBranchRef")
    if not repos:
        raise ScanError(f"gh repo list {owner} returned no repos")
    doors, slow, red = [], [], []
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
            if "schedule" in fsd.triggers(text) and ids.get(path):
                red += red_nightly(owner, name, path, ids[path])
    return doors, len(repos), slow, red


def red_nightly(owner: str, repo: str, path: str, wid) -> list[dict]:
    """The nightly is the ONE place the full suite runs, so its result needs a
    reader (cole-gtm PR #16 review: nothing read it). The last completed
    scheduled run, if it did not succeed, is reported here."""
    runs = gh_json_or_404("api", f"repos/{owner}/{repo}/actions/workflows/{wid}/runs"
                          "?event=schedule&status=completed&per_page=1") or {}
    out = []
    for run in runs.get("workflow_runs", [])[:1]:
        if run.get("conclusion") not in ("success", "skipped"):
            out.append({"repo": repo, "door": path, "run": run["id"],
                        "conclusion": run.get("conclusion")})
    return out


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
    try:
        p = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                           env=env, timeout=GH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # The third subprocess family round 1 left unbounded (PR #492 review).
        raise ScanError(f"git -C {path.name} {args[0]} timed out after {GH_TIMEOUT_S}s")
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


def fingerprint(doors: list[dict], slow: list[dict] = (), red: list[dict] = ()) -> str:
    keys = sorted(f"{d['repo']}|{d['where']}|{d['door']}|{d['what']}" for d in doors)
    keys += sorted(f"slow|{s['repo']}|{s['door']}|{s['step']}" for s in slow)
    # Identity, not the run id (PR #492 review): a nightly red for a week is ONE
    # state, alerted once, the same rule slow_steps follows for its seconds.
    keys += sorted(f"red|{r['repo']}|{r['door']}" for r in red)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def read_state(state_dir: Path) -> dict | None:
    f = state_dir / "state.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except ValueError:
        return None                 # a corrupt state reads as "changed", never as quiet


def write_state(state_dir: Path, report: dict) -> None:
    """The ONE writer of state.json. Called only AFTER an alert was delivered (or
    none was due): written first, a failed alert left the new state recorded and
    the door was never announced again (PR #492 review)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True))
    os.replace(tmp, f)


def alert(line: str) -> bool:
    """True only when the alert path accepted the line."""
    cmd = os.environ.get("KIPI_ALERT_CMD")
    argv = shlex.split(cmd) if cmd else ["bash", str(HERE / "slack-notify.sh")]
    try:
        return subprocess.run(argv + [line], capture_output=True, text=True,
                              timeout=GH_TIMEOUT_S).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--owner", default="")
    ap.add_argument("--no-ci", action="store_true")
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-alert", action="store_true",
                    help="measure only: never alert and never touch the state file")
    ap.add_argument("--fail-on-doors", action="store_true",
                    help="exit 1 when doors or slow steps are open (for a CLI caller; the "
                         "daily job leaves it off so the watchdog reads exit != 0 as broken)")
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
        doors, nrepos, slow, red = ([], 0, [], []) if a.no_ci else scan_ci(owner)
        nlocal = 0
        if not a.no_local:
            cos = local_checkouts(registry, projects_root)
            if not cos:
                # Same rule as the repo listing (PR #492 review): zero checkouts is
                # a scanner that saw nothing, never "zero local doors".
                raise ScanError("no local checkouts found (registry and projects root both empty)")
            nlocal = len(cos)
            doors += scan_local(owner, cos)
    except (ScanError, KeyError, ValueError) as exc:
        print(f"fleet-full-suite-scan: could not read the population: {exc}", file=sys.stderr)
        return 2

    report = {"doors": doors, "slow_steps": slow, "red_nightlies": red,
              "fingerprint": fingerprint(doors, slow, red),
              "repos_scanned": nrepos, "checkouts_scanned": nlocal}
    prev = read_state(state_dir)
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
        for r in red:
            print(f"  NIGHTLY RED {r['repo']} {r['door']}: {r['conclusion']} on run {r['run']}")
    if a.no_alert:
        pass                        # measure only: the dedup state is the job's, not ours
    elif not changed:
        write_state(state_dir, report)
    else:
        was = len((prev or {}).get("doors", [])) if prev else "unknown"
        where = ", ".join(sorted({f"{d['repo']}:{d['door']}" for d in doors}))[:300]
        # The population sizes ride in the line (PR #492 review): a scan that saw
        # fewer repos reads as doors closing unless the reader can see it shrank.
        pr_, pc = ((prev or {}).get("repos_scanned", "?"), (prev or {}).get("checkouts_scanned", "?"))
        if alert(f"fleet full-suite doors changed: {len(doors)} open (was {was}), "
                 f"{len(slow)} slow test step(s), {len(red)} red nightly run(s); "
                 f"scanned {nrepos} repos (was {pr_}), {nlocal} checkouts (was {pc}). "
                 f"{where or 'none open'}. RULE-2026-10-01-A: only the nightly may run a whole suite."):
            write_state(state_dir, report)
        else:
            # Not recorded, so the next run sees the change again and retries.
            print("fleet-full-suite-scan: alert NOT delivered; state left unchanged", file=sys.stderr)
            return 3
    # EXIT 0 ON A COMPLETED SCAN, doors or not (PR #492 review): launchd-health-check
    # reads a non-zero exit as a broken job and pages, twice a day, and a normal
    # "doors open" day was indistinguishable from a blind scan (2).
    return 1 if a.fail_on_doors and (doors or slow or red) else 0


if __name__ == "__main__":
    sys.exit(main())
