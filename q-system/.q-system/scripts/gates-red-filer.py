#!/usr/bin/env python3
"""gates-red-filer.py: a red nightly files ONE issue per (check, breaking commit).

WHY (ASK-3828, RCA 2026-11-06 root cause #6). A required PR check that can go
red for files the PR never touched cannot be made green by the PR's author, so
the PR waits for a human or the floor gets bypassed. The PR job now grades only
what its diff introduced; the tree-wide checks run in the nightly gates.yml on
main. A tree-wide red is then nobody's PR, so it needs an owner of its own: the
commit that broke it. Before this file the nightly opened one issue titled
"gates-red: nightly gates failed" and commented on it every red night. It named
no check and no commit, so whoever picked it up started from a 47-minute log.

WHAT IT DOES (the report-red job, after the gates job failed):
  1. Reads the gates job's steps and log through the GitHub API (built-in token).
  2. The failed step becomes findings. Each capability-gate `RED:` line is one
     finding; any other failed step is one finding.
  3. A finding an open gates-red issue already carries is not filed again. Its
     issue gets one "still red" comment per run. Never a second issue.
  4. Each NEW finding is bisected over main's first-parent commits since the
     last green nightly, re-running only that finding's probe (one test, or the
     gate's structure pass), never the 47-minute suite.
  5. One issue per (step, breaking commit), listing that commit's findings.
  6. An issue whose step ran tonight and whose findings are all gone is closed.
     report-green still closes everything on a green night.

THE CONSUMER is the gates-red detector in fleet-health-daily.py: one Linear
ticket per OPEN gates-red issue, keyed by issue number. One GitHub issue per
(check, commit) is therefore one Linear ticket per (check, commit).

--fixture DIR replaces the GitHub API with JSON files (jobs.json, log-<id>.txt,
green_sha.txt, issues.json, which it rewrites), so the dedup and the bisect run
end to end in a test without filing anything real. --dry-run reads GitHub and
prints the writes instead of making them. stdlib only: the report-red runner has
no PyYAML, and the probes check out older commits under this script's feet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LABEL = "gates-red"
# The ONE step whose findings are per-line. test_gates_workflow.py pins that
# gates.yml has a step of exactly this name running capability-gate.py.
CAPABILITY_STEP = "Capability gate, full suite"
GATE = "q-system/.q-system/scripts/capability-gate.py"
# Every other check step, with the command that re-runs it at one commit. A
# restated command drifts from the workflow, so test_gates_workflow.py pins
# each argv verbatim in the gates.yml step of the same name.
STEP_PROBES = {
    "Coverage declarations are real": (
        ["python3", "q-system/.q-system/scripts/covers-lint.py", "--repo-root", "."], {}),
    "Skeleton separation, phase 1": (
        ["python3", "validate-separation.py", "1", "--verbose"],
        {"CI": "true", "CAPABILITY_GATE_SKIP": "1"}),
    "prd-os tests": (["pytest", "plugins/prd-os/tests/", "-q"], {}),
}
STRUCTURE_KINDS = {"present-but-undeclared", "declared-but-missing",
                   "declared-but-missing (outside scan root)", "required-data-missing",
                   "inert-engine"}
TEST_KINDS = {"test-failed", "test-timeout", "zero-execution test"}
MAX_BISECTED = 10          # new findings bisected per run; the rest name the head
PROBE_TIMEOUT_S = 1200
# All probes of one run share this budget, well inside report-red's 60-minute
# cap (#608 review, major: 6 probes of a 600 s test is the whole hour, and a
# job cancelled mid-bisect filed nothing). Past it a finding is filed against
# head, unbisected, rather than lost with the job.
PROBE_BUDGET_S = 35 * 60
TS_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")
GROUP_RE = re.compile(r"<!-- gates-red-group: (.+?)@([0-9a-f]{7,40}) -->")
FIND_RE = re.compile(r"<!-- gates-red-finding: ([0-9a-f]{16}) -->")


# ---------------------------------------------------------------- findings
def normalize(line: str) -> tuple[str, str | None, str]:
    """(kind, path, key) for one gate RED line. The key drops what changes
    between runs of the same failure (the rc, the timeout) so night two
    recognises night one's finding."""
    first = line.strip().splitlines()[0] if line.strip() else ""
    kind, sep, rest = first.partition(": ")
    if not sep:
        return first[:160], None, first[:160]
    kind = re.sub(r" rc=-?\d+$| \(\d+s\)$", "", kind)
    tok = rest.split()[0] if rest.split() else ""
    path = tok if ("/" in tok or "." in tok) else None
    return kind, path, (f"{kind}: {path}" if path else f"{kind}: {rest}"[:160])


def gate_red_lines(text: str) -> list[str]:
    """Top-level `  RED: ` lines of the LAST capability-gate run in a log.

    Exactly two spaces: report() indents a multi-line error's tail with a `|`
    gutter (capability-gate.py), so a nested gate's output inside a failing
    test's tail can never read as a finding of this run."""
    lines = [TS_PREFIX.sub("", l) for l in text.splitlines()]
    starts = [i for i, l in enumerate(lines) if l.startswith("##[group]Run ") and "capability-gate.py" in l]
    lines = lines[starts[-1]:] if starts else lines
    return [l[len("  RED: "):] for l in lines if l.startswith("  RED: ")]


def finding_id(step: str, key: str) -> str:
    return hashlib.sha1(f"{step}\n{key}".encode()).hexdigest()[:16]


def findings_for(step: str, log_text: str) -> list[dict]:
    if step == CAPABILITY_STEP:
        out = []
        for red in gate_red_lines(log_text):
            kind, path, key = normalize(red)
            out.append({"step": step, "kind": kind, "path": path, "key": key})
        if out:
            return out
        key = "exited red with no RED line"
    else:
        key = "step failed"
    return [{"step": step, "kind": "step", "path": None, "key": key}]


# ---------------------------------------------------------------- git
def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def first_parent_range(repo: Path, base: str | None, head: str) -> list[str] | None:
    """Main's commits after the last green nightly, oldest first, or None when
    there is no usable baseline (never green, or not an ancestor of head)."""
    if not base:
        return None
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=str(repo),
                      capture_output=True).returncode != 0:
        return None
    out = git(repo, "rev-list", "--first-parent", "--reverse", f"{base}..{head}")
    return out.split() if out else []


class ProbeError(Exception):
    pass


class Prober:
    """Re-runs one finding's check at one commit, in a throwaway worktree.

    A worktree, not a checkout of the job's own clone: a probe at an old commit
    must not leave that commit's tree (or a test's leftovers) under the next
    probe, and the clone stays at the head the gates job graded."""

    def __init__(self, repo: Path, budget_s: float = PROBE_BUDGET_S):
        self.repo, self.trees, self.cache = repo, {}, {}
        self.deadline = time.monotonic() + budget_s
        self.tmp = Path(tempfile.mkdtemp(prefix="gates-red-probe-"))
        self.count = 0
        # THIS run's gate, for a test probe at a commit whose own gate predates
        # --only (ASK-3828 added it). Without it every commit before the flag
        # exits 2, and the first red nights after it landed could never bisect a
        # test. A structure probe always uses the commit's own gate: if the gate
        # itself got stricter, that commit is the one to name.
        self.tools = self.tmp / "tools"
        self.tools.mkdir()
        scripts = repo / GATE.rsplit("/", 1)[0]
        for name in ("capability-gate.py", "capability_manifest.py"):
            if (scripts / name).is_file():
                shutil.copy2(scripts / name, self.tools / name)

    def tree(self, sha: str) -> Path:
        if sha not in self.trees:
            path = self.tmp / sha[:12]
            try:
                git(self.repo, "worktree", "add", "--detach", "-q", str(path), sha)
            except RuntimeError as exc:   # a commit that cannot answer, not a crash
                raise ProbeError(f"no worktree at {sha[:7]}: {exc}")
            self.trees[sha] = path
        return self.trees[sha]

    def run(self, sha: str, argv: list[str], env: dict) -> tuple[int, str]:
        k = (sha, tuple(argv), tuple(sorted(env.items())))
        if k not in self.cache:
            left = self.deadline - time.monotonic()
            if left < 60:
                raise ProbeError(f"this run's {PROBE_BUDGET_S // 60}-minute probe budget is spent")
            limit = int(min(PROBE_TIMEOUT_S, left))
            self.count += 1
            try:
                p = subprocess.run(argv, cwd=str(self.tree(sha)), env=dict(os.environ, **env),
                                   capture_output=True, text=True, timeout=limit)
            except subprocess.TimeoutExpired:
                raise ProbeError(f"timed out after {limit}s at {sha[:7]}")
            except OSError as exc:
                raise ProbeError(f"could not run {argv[0]} at {sha[:7]}: {exc}")
            self.cache[k] = (p.returncode, p.stdout + p.stderr)
        return self.cache[k]

    def red(self, finding: dict, sha: str) -> bool:
        """True red, False green; ProbeError when the commit cannot answer."""
        step, kind = finding["step"], finding["kind"]
        if step == CAPABILITY_STEP and kind != "step":
            if kind in TEST_KINDS and finding["path"]:
                own = self.tree(sha) / GATE
                gate = GATE if own.is_file() and '"--only"' in own.read_text() \
                    else str(self.tools / "capability-gate.py")
                argv = ["python3", gate, "--repo-root", ".", "--only", finding["path"]]
            else:
                argv = ["python3", GATE, "--repo-root", ".", "--check-only"]
            rc, out = self.run(sha, argv, {})
            if rc not in (0, 1):
                raise ProbeError(f"capability gate exited {rc} at {sha[:7]}: {out.strip()[-200:]}")
            for red in [l[len("  RED: "):] for l in out.splitlines() if l.startswith("  RED: ")]:
                k2, p2, key2 = normalize(red)
                if key2 == finding["key"]:
                    return True
                if kind in TEST_KINDS and k2 in TEST_KINDS and p2 == finding["path"]:
                    return True
            return False
        if step in STEP_PROBES:
            argv, env = STEP_PROBES[step]
            rc, _ = self.run(sha, argv, env)
            return rc != 0
        raise ProbeError(f"no probe re-runs `{step}` by itself")

    def close(self):
        # Only trees this Prober added, under its own mkdtemp. --force because a
        # probe's test may leave files behind, and these trees are scratch.
        for path in self.trees.values():
            subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=str(self.repo),
                           capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=str(self.repo), capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


def attribute(prober, finding: dict, commits: list[str] | None, base: str | None, head: str) -> dict:
    """{sha, found, why}. `found` is True only when a probe pinned one commit."""
    def out(sha, found, why):
        return {"sha": sha, "found": found, "why": why}
    if commits is None:
        return out(head, False, "no usable green nightly on main to bisect from "
                                "(none, or its commit is not an ancestor of this head)")
    if not commits:
        return out(head, False, "head is the last green nightly's commit")
    try:
        if not prober.red(finding, head):
            return out(head, False, "not reproduced when re-run at head (flaky, or it depends on the run)")
        if prober.red(finding, base):
            return out(base, False, f"red at the last green nightly's commit {base[:7]} too when re-run "
                                    "now, so no commit in range caused it (time, network or runner)")
        lo, hi = -1, len(commits) - 1          # commits[hi] is red; base (lo) is green
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if prober.red(finding, commits[mid]):
                hi = mid
            else:
                lo = mid
    except ProbeError as exc:
        return out(head, False, f"not bisected: {exc}")
    except Exception as exc:  # noqa: BLE001 -- a bisect bug must not lose the finding
        return out(head, False, f"not bisected: {type(exc).__name__}: {str(exc)[:160]}")
    return out(commits[hi], True, "bisected" if len(commits) > 1 else
               "the only commit since the last green nightly")


# ---------------------------------------------------------------- GitHub
class GitHub:
    def __init__(self, repo: str, dry: bool = False):
        self.repo, self.dry = repo, dry

    def _api(self, *args: str) -> str:
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
        if p.returncode != 0:
            where = next((a for a in args if a.startswith("repos/")), args[0])
            raise RuntimeError(f"gh api {where}: {(p.stderr or p.stdout).strip()[:300]}")
        return p.stdout

    def jobs(self, run_id: str) -> list:
        return json.loads(self._api(f"repos/{self.repo}/actions/runs/{run_id}/jobs?per_page=100"))["jobs"]

    def job_log(self, job_id) -> str:
        # A job log is full of ANSI colour codes, and gh 2.103 refuses to print
        # one without --allow-escape-sequences (measured 2026-11-06 on job
        # 127813136293). An older gh on the runner has no such flag and no such
        # refusal, so the flag is retried away only on "unknown flag".
        path = f"repos/{self.repo}/actions/jobs/{job_id}/logs"
        try:
            return self._api("--allow-escape-sequences", path)
        except RuntimeError as exc:
            if "unknown flag" not in str(exc):
                raise
            return self._api(path)

    def last_green_sha(self, workflow: str) -> str | None:
        runs = json.loads(self._api(
            f"repos/{self.repo}/actions/workflows/{workflow}/runs?branch=main&status=success&per_page=1"))
        return runs["workflow_runs"][0]["head_sha"] if runs.get("workflow_runs") else None

    def open_issues(self) -> list:
        items = json.loads(self._api(f"repos/{self.repo}/issues?labels={LABEL}&state=open&per_page=100"))
        return [{"number": i["number"], "title": i["title"], "body": i.get("body") or ""}
                for i in items if "pull_request" not in i]

    def _write(self, what: str, *args: str):
        if self.dry:
            print(f"DRY-RUN would {what}")
            return None
        return self._api(*args)

    def create(self, title: str, body: str):
        out = self._write(f"create issue: {title}", "-X", "POST", f"repos/{self.repo}/issues",
                          "-f", f"title={title}", "-f", f"body={body}", "-f", f"labels[]={LABEL}")
        return json.loads(out)["number"] if out else None

    def comment(self, number: int, body: str):
        self._write(f"comment on #{number}: {body.splitlines()[0]}", "-X", "POST",
                    f"repos/{self.repo}/issues/{number}/comments", "-f", f"body={body}")

    def set_body(self, number: int, body: str):
        self._write(f"rewrite the body of #{number}", "-X", "PATCH",
                    f"repos/{self.repo}/issues/{number}", "-f", f"body={body}")

    def close(self, number: int, why: str):
        self.comment(number, why)
        self._write(f"close #{number}", "-X", "PATCH", f"repos/{self.repo}/issues/{number}",
                    "-f", "state=closed")


class FixtureGitHub:
    """The same surface over files, for tests and by-hand proofs."""

    def __init__(self, d: Path):
        self.d = d
        self.f = d / "issues.json"
        self.issues = json.loads(self.f.read_text()) if self.f.is_file() else []

    def _save(self):
        self.f.write_text(json.dumps(self.issues, indent=1))

    def jobs(self, run_id):
        return json.loads((self.d / "jobs.json").read_text())["jobs"]

    def job_log(self, job_id):
        p = self.d / f"log-{job_id}.txt"
        return p.read_text() if p.is_file() else ""

    def last_green_sha(self, workflow):
        p = self.d / "green_sha.txt"
        return p.read_text().strip() or None if p.is_file() else None

    def open_issues(self):
        # Copies, as the real API returns: a fixture that hands back the dicts it
        # later mutates hid a stale-snapshot bug in run() (found 2026-11-06).
        return [json.loads(json.dumps(i)) for i in self.issues if i["state"] == "open"]

    def _get(self, number):
        return next(i for i in self.issues if i["number"] == number)

    def create(self, title, body):
        n = max([i["number"] for i in self.issues] + [0]) + 1
        self.issues.append({"number": n, "title": title, "body": body, "state": "open", "comments": []})
        self._save()
        return n

    def comment(self, number, body):
        self._get(number)["comments"].append(body)
        self._save()

    def set_body(self, number, body):
        self._get(number)["body"] = body
        self._save()

    def close(self, number, why):
        self.comment(number, why)
        self._get(number)["state"] = "closed"
        self._save()


# ---------------------------------------------------------------- the run
def issue_text(group: dict, findings: list, run_url: str, repo: Path, base, head, probes) -> tuple[str, str]:
    sha, step = group["sha"], group["step"]
    subject = git(repo, "log", "-1", "--format=%s", sha, check=False)[:90]
    if group["found"]:
        title = f"gates-red: {step}: red since {sha[:7]} {subject}"
        line = f"Breaking commit: {sha} ({subject}). {group['why']}."
    else:
        title = f"gates-red: {step}: red at {sha[:7]}, breaking commit not found"
        line = f"Breaking commit not found: {group['why']}. Newest commit graded: {head}."
    span = f"{base[:7]}..{head[:7]}" if base else f"(no green baseline)..{head[:7]}"
    body = "\n".join([
        f"<!-- gates-red-group: {step}@{sha} -->",
        f"The nightly gates run {run_url} is red on `{step}`.", "",
        line, f"Range searched: {span}; {probes} probe run(s) so far in this filer run.", "",
        "Findings:",
        *[f"- `{f['key']}` <!-- gates-red-finding: {finding_id(step, f['key'])} -->" for f in findings],
        "",
        "Read by the gates-red detector in fleet-health-daily.py, which files it to Linear "
        "triage. Closed by gates-red-filer.py once every finding above is gone from a nightly "
        "run in which this step ran, or by report-green on a green night.",
    ])
    return title[:240], body


def run(gh, repo: Path, run_id: str, run_url: str, workflow: str) -> list[str]:
    actions = []
    jobs = gh.jobs(run_id)
    gates = next((j for j in jobs if j["name"] == "gates"), None)
    if gates is None:
        raise RuntimeError(f"run {run_id} has no `gates` job")
    steps = gates.get("steps") or []
    ran = {s["name"] for s in steps if s.get("conclusion") in ("success", "failure")}
    failed = [s["name"] for s in steps if s.get("conclusion") == "failure"]
    log = gh.job_log(gates["id"]) if failed else ""
    found = []
    for step in failed:
        found += findings_for(step, log)
    if not failed and gates.get("conclusion") not in ("success", None):
        found.append({"step": "gates job", "kind": "step", "path": None,
                      "key": f"job ended {gates.get('conclusion')} with no failed step"})
    tonight = {finding_id(f["step"], f["key"]) for f in found}

    issues = gh.open_issues()
    carried = {}                                     # finding id -> issue number
    groups = {}                                      # (step, sha) -> issue
    for i in issues:
        g = GROUP_RE.search(i["body"])
        if g:
            groups[(g.group(1), g.group(2))] = i
            for fid in FIND_RE.findall(i["body"]):
                carried[fid] = i["number"]

    for n in sorted({carried[fid] for fid in tonight if fid in carried}):
        gh.comment(n, f"Still red: {run_url}")
        actions.append(f"still-red #{n}")

    new = [f for f in found if finding_id(f["step"], f["key"]) not in carried]
    head = git(repo, "rev-parse", "HEAD")
    base = gh.last_green_sha(workflow) if new else None
    commits = first_parent_range(repo, base, head) if new else None
    # ATTRIBUTE ONE, FILE ONE (#608 review, major). Bisecting every finding
    # before filing any meant one cancelled job or one crash filed nothing for a
    # red nightly, and this filer is that red's only route to the queue. Each
    # finding is filed the moment it is attributed; a later one joins the issue
    # an earlier one opened for the same (step, commit).
    prober = Prober(repo)
    try:
        for k, f in enumerate(new):
            if k < MAX_BISECTED:
                a = attribute(prober, f, commits, base, head)
            else:
                a = {"sha": head, "found": False,
                     "why": f"not bisected: more than {MAX_BISECTED} new findings in one run"}
            step = f["step"]
            line = f"- `{f['key']}` <!-- gates-red-finding: {finding_id(step, f['key'])} -->"
            old = groups.get((step, a["sha"]))
            if old:
                # The snapshot is updated too: the close pass below reads it, and
                # an issue extended tonight must not close for the findings it lost.
                old["body"] = old["body"].replace("\nFindings:\n", f"\nFindings:\n{line}\n", 1)
                gh.set_body(old["number"], old["body"])
                gh.comment(old["number"], f"Also red since this commit: {run_url}\n{line}")
                actions.append(f"extended #{old['number']} +1")
                continue
            group = {"step": step, "sha": a["sha"], "found": a["found"], "why": a["why"]}
            title, body = issue_text(group, [f], run_url, repo, base, head, prober.count)
            number = gh.create(title, body)
            groups[(step, a["sha"])] = {"number": number, "body": body, "fresh": True}
            actions.append(f"created: {title}")
    finally:
        prober.close()

    for (step, _sha), i in groups.items():
        fids = set(FIND_RE.findall(i["body"]))
        if not i.get("fresh") and step in ran and not (fids & tonight):
            gh.close(i["number"], f"Green for this check in {run_url}")
            actions.append(f"closed #{i['number']}")
    if found:
        for i in issues:
            if not GROUP_RE.search(i["body"]):
                gh.close(i["number"], "Superseded by one issue per (check, breaking commit) from "
                                      f"gates-red-filer.py (ASK-3828). Tonight's run: {run_url}")
                actions.append(f"closed legacy #{i['number']}")
    return actions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--repo", default=os.environ.get("GH_REPO", ""))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-url", default="")
    ap.add_argument("--workflow", default="gates.yml")
    ap.add_argument("--dry-run", action="store_true", help="read GitHub, print the writes")
    ap.add_argument("--fixture", help="a directory of JSON files standing in for GitHub")
    a = ap.parse_args(argv)
    repo = Path(a.repo_root).resolve()
    if a.fixture:
        gh = FixtureGitHub(Path(a.fixture))
    elif not a.repo:
        ap.error("--repo (or GH_REPO) is required without --fixture")
    else:
        gh = GitHub(a.repo, dry=a.dry_run)
    for line in run(gh, repo, a.run_id, a.run_url or f"run {a.run_id}", a.workflow):
        print(f"gates-red-filer: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
