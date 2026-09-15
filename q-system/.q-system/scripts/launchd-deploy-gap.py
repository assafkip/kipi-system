#!/usr/bin/env python3
"""Which git tree each LOADED launchd job runs from, and how far it is from default.

The gap this closes (ASK-1135, measured 2026-08-29): 32 loaded jobs execute from
working trees that are ahead of, and dirty against, their default branch.
One repo ran 14 jobs from a branch 127 commits ahead of origin with 93 dirty
files; two client instances were 174 and 168 ahead. Merging a fix does not deploy it,
and code that never passed a gate is what runs. ASK-1132 nearly slipped that way:
the DoR drafter fix was on main, and com.kipi.linear-dor ran `cd <repo> && ./kipi
dor --apply` from a checkout on a branch that did not have it.

Three rules, each from a measurement that got it wrong first:

- The default branch is what `origin/HEAD` names, NEVER an assumed `main`. The
  first version of ASK-1135 said "cole-gtm 405 behind main". cole-gtm's default is
  `master`; `git rev-list HEAD..origin/main` returned a number about a stale
  divergent `main` rather than an error. Against master it was 1 behind. With no
  `origin/HEAD` set the default is reported UNRESOLVED and no count is invented.
- Enumerate from `launchctl list`, never from the plist directory. 20 of the 56
  installed plists were paused, and a paused job cannot run stale code; counting
  them inflated the exposure about 2x.
- Report ahead and dirty, not only behind. Behind was 0 to 3 everywhere once
  measured correctly; the risk is code that never went through the default at all.

Counts are against the LOCAL remote-tracking ref, as of the tree's last fetch.
This script never fetches: it reads, it does not move refs under a running job.
`fetched` in the report is the age of FETCH_HEAD so a stale ref is visible.

The tree is the one the PLIST names. A wrapper that execs the real code from
another tree defeats that, so the known ones (`_REEXEC_WRAPPERS`) get NO ANSWER
and no rollup row. An unknown wrapper of that shape is read as the tree it lives in.

Usage:
  launchd-deploy-gap.py                 # report every loaded watched job; read-only
  launchd-deploy-gap.py --live SHA LABEL
                                        # is commit SHA in the tree LABEL runs from?
                                        #   exit 0 live, 1 not live, 2 no answer

Filing to Linear happens only through `run_check`, which launchd-health-check.py
calls on its schedule: ONE rollup issue, deduped by a stable key, pages nobody.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LINEAR_DETECTOR = "launchd-deploy-gap"
_ROLLUP_SUBJECT = "rollup"

# An absolute path token inside a ProgramArguments string. Catches the
# `bash -c "cd /repo && ./kipi dor --apply"` shape com.kipi.linear-dor uses, where
# the tree is named only inside a shell string.
_PATH_TOKEN = re.compile(r"(?<![\w.~])(/[^\s'\"`;&|()<>]+)")
_XML_COMMENT = re.compile(rb"<!--.*?-->", re.S)

# Wrappers that exec the job's real code from a tree the plist never names.
# kipi-dispatch-pinned.sh (com.kipi.dispatch) execs from a worktree it holds at
# origin/main, so the checkout in the plist said LIVE for a branch-only commit and
# NOT LIVE for a merged fix (PR #361 review r2, major). Such a job has no tree to
# answer about here: NO ANSWER, and no rollup row.
_REEXEC_WRAPPERS = ("kipi-dispatch-pinned.sh",)


def git(top, *args):
    """(returncode, stdout stripped). Never raises: a tree we cannot read is a
    finding, not a crash of the job that reports it.

    --no-optional-locks on every call: a plain `git status` refreshes a stat-stale
    index under .git/index.lock, in a tree a live job writes to. A concurrent
    `git add` there failed, and a timeout kill left the lock behind (PR #361 review).
    """
    try:
        proc = subprocess.run(["git", "--no-optional-locks", "-C", str(top), *args],
                              capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def resolve_default(top):
    """`origin/<default>` as origin/HEAD names it, or None. Never a guessed `main`."""
    rc, ref = git(top, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return ref if rc == 0 and ref else None


def fetch_age_hours(top):
    rc, gitdir = git(top, "rev-parse", "--git-common-dir")
    if rc != 0:
        return None
    head = Path(top, gitdir) / "FETCH_HEAD"
    try:
        return round((time.time() - head.stat().st_mtime) / 3600, 1)
    except OSError:
        return None


def tree_state(top):
    """Branch, resolved default, behind/ahead of it, and dirty count for one tree.

    dirty is None when `git status` fails: an empty stdout from a failed status
    read as 0 dirty, so a tree with a corrupt index reported clean (PR #361 r2).
    """
    default = resolve_default(top)
    _, branch = git(top, "rev-parse", "--abbrev-ref", "HEAD")
    rc, porcelain = git(top, "status", "--porcelain")
    state = {"tree": str(top), "branch": branch, "default": default,
             "behind": None, "ahead": None,
             "dirty": len([ln for ln in porcelain.splitlines() if ln.strip()]) if rc == 0 else None,
             "fetched_hours_ago": fetch_age_hours(top)}
    if default:
        rc, counts = git(top, "rev-list", "--left-right", "--count", f"{default}...HEAD")
        if rc == 0 and len(counts.split()) == 2:
            state["behind"], state["ahead"] = (int(n) for n in counts.split())
    return state


def risk_reasons(state, counts=True):
    """Why this tree is not the default branch, one short phrase each. [] = clean.

    counts=False drops the numbers and keeps the kinds. The Linear rollup is
    rewritten whenever its body changes, and behind/ahead/dirty counts move on
    every commit and fetch, so the filed body carries kinds only (PR #361 review).
    """
    default = state["default"]
    if not default:
        return ["default UNRESOLVED (origin/HEAD unset: `git remote set-head origin -a`)"]
    reasons = []
    short = default.split("/", 1)[1]
    if state["branch"] != short:
        reasons.append(f"on {state['branch']}, not {short}")
    if state["behind"] is None:
        reasons.append(f"{default} unreadable, no count")
    else:
        for n, word in ((state["behind"], "behind"), (state["ahead"], "ahead")):
            if n:
                reasons.append(f"{n} {word}" if counts else word)
    if state["dirty"] is None:
        reasons.append("status unreadable, dirty unknown")
    elif state["dirty"]:
        reasons.append(f"{state['dirty']} dirty" if counts else "dirty")
    return reasons


def filed_reasons(job):
    """The count-free reasons for the rollup. A job with no tree has no state to
    recompute from, and its reasons carry no counts to begin with."""
    return risk_reasons(job, counts=False) if job.get("tree") else job["reasons"]


def loaded_labels(listing, prefixes):
    """Labels from `launchctl list` output (PID, Status, Label) under a watched prefix."""
    labels = set()
    for line in listing.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[2].startswith(tuple(prefixes)):
            labels.add(parts[2].strip())
    return sorted(labels)


def read_program(plist_path):
    """The plist's dict, or None. XML comments are stripped first: a `--` inside
    one is tolerated by launchd and rejected by expat, so com.kipi.dispatch and
    com.kipi.linear-triage-health read as malformed to plistlib (ASK-1135)."""
    import plistlib

    try:
        return plistlib.loads(_XML_COMMENT.sub(b"", Path(plist_path).read_bytes()))
    except Exception:  # noqa: BLE001
        return None


def job_tree(program):
    """The git toplevel a job's code comes from, or "".

    WorkingDirectory first, then every absolute path in the arguments. A path that
    git IGNORES is skipped: /opt/homebrew is itself a git repo, and
    /opt/homebrew/bin/python3 would otherwise map every Homebrew-python job to
    Homebrew's tree (measured: `check-ignore` says bin/python3 is ignored there).
    """
    candidates = [program.get("WorkingDirectory") or ""]
    args = program.get("ProgramArguments") or [program.get("Program") or ""]
    for arg in args:
        candidates.extend(_PATH_TOKEN.findall(str(arg)))
    for raw in filter(None, candidates):
        path = Path(raw)
        folder = path if path.is_dir() else path.parent
        if not folder.is_dir():
            continue
        rc, top = git(folder, "rev-parse", "--show-toplevel")
        if rc != 0 or not top:
            continue
        if path.resolve() != Path(top).resolve() and git(top, "check-ignore", "-q", str(path))[0] == 0:
            continue
        return top
    return ""


def reexec_wrapper(program):
    """The known re-exec wrapper this job runs through, or ""."""
    args = program.get("ProgramArguments") or [program.get("Program") or ""]
    for arg in args:
        for token in _PATH_TOKEN.findall(str(arg)):
            if Path(token).name in _REEXEC_WRAPPERS:
                return Path(token).name
    return ""


def survey(listing, prefixes, agents_dir=LAUNCH_AGENTS):
    """One record per LOADED watched job: label, tree, tree state, reasons."""
    jobs, states = [], {}
    for label in loaded_labels(listing, prefixes):
        program = read_program(Path(agents_dir) / f"{label}.plist")
        if program is None:
            jobs.append({"label": label, "tree": "", "reasons": ["no plist, tree unknown"]})
            continue
        wrapper = reexec_wrapper(program)
        if wrapper:
            jobs.append({"label": label, "tree": "", "reasons": [],
                         "note": f"runs through {wrapper}, which execs from a tree the plist does not name"})
            continue
        top = job_tree(program)
        if not top:
            # Not a working-tree job (an installed artifact, a system binary).
            # Recorded with no reasons: it cannot run unmerged repo code.
            jobs.append({"label": label, "tree": "", "reasons": []})
            continue
        if top not in states:
            states[top] = tree_state(top)
        jobs.append({"label": label, **states[top], "reasons": risk_reasons(states[top])})
    return jobs


def commit_live(top, sha):
    """(True|False, why) -- does the tree's HEAD contain `sha`?"""
    rc, full = git(top, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if rc != 0:
        return False, f"{sha} is not in {top}'s object store, so its HEAD cannot contain it"
    rc, _ = git(top, "merge-base", "--is-ancestor", full, "HEAD")
    if rc == 0:
        return True, f"{full[:10]} is in HEAD of {top}"
    return False, f"{full[:10]} is NOT in HEAD of {top}"


def commit_live_for_job(label, sha, listing, prefixes, agents_dir=LAUNCH_AGENTS):
    """(True|False|None, why). None = no answer: not loaded, or no tree to check."""
    job = next((j for j in survey(listing, prefixes, agents_dir) if j["label"] == label), None)
    if job is None:
        return None, f"{label} is not a loaded watched job"
    if not job["tree"]:
        return None, f"{label} has no git tree to check ({_treeless_why(job)})"
    return commit_live(job["tree"], sha)


def _treeless_why(job):
    return job.get("note") or ", ".join(job["reasons"]) or "installed artifact"


def report_line(job):
    if not job["tree"]:
        return f"{job['label']}: {_treeless_why(job)}"
    counts = ("behind ? / ahead ?" if job["behind"] is None
              else f"behind {job['behind']} / ahead {job['ahead']}")
    dirty = "? dirty" if job["dirty"] is None else f"{job['dirty']} dirty"
    return (f"{job['label']}: {job['tree']} on {job['branch']}, default "
            f"{job['default'] or 'UNRESOLVED'}, {counts}, {dirty}, "
            f"fetched {job['fetched_hours_ago']}h ago"
            + (f" -- {'; '.join(job['reasons'])}" if job["reasons"] else ""))


def linear_findings(jobs, finding_key):
    """At most ONE rollup finding. A clean fleet files nothing, so a closed issue
    reopens only when a job goes off-default again (file_findings' lifecycle)."""
    at_risk = [j for j in jobs if j["reasons"]]
    if not at_risk:
        return []
    by_tree = {}
    for job in at_risk:
        by_tree.setdefault(job["tree"] or "(unknown tree)", []).append(job)
    sections = []
    for tree in sorted(by_tree):
        rows = by_tree[tree]
        sections.append(f"### {tree} ({len(rows)} job(s))\n\n"
                        f"{'; '.join(filed_reasons(rows[0]))}\n\n"
                        + "\n".join(f"- `{j['label']}`" for j in rows))
    body = ("These loaded launchd jobs run from a git tree that differs from its "
            "default branch as merged: another branch, commits behind or ahead, or "
            "uncommitted changes. A fix merged to the default does not reach them, "
            "and whatever is ahead or dirty in the tree runs without having passed "
            "a gate.\n\n"
            + "\n\n".join(sections)
            + "\n\n## Counts and one fix\n"
            "`python3 q-system/.q-system/scripts/launchd-deploy-gap.py` prints behind, "
            "ahead and dirty per job. They move on every commit and fetch, so they "
            "stay out of this issue.\n\n"
            "`python3 q-system/.q-system/scripts/launchd-deploy-gap.py --live <sha> <label>`\n"
            "\n---\nMeasured: `launchctl list` (loaded jobs only), the job's plist, "
            "and `git symbolic-ref refs/remotes/origin/HEAD` per tree.")
    return [{
        "subject": _ROLLUP_SUBJECT,
        "title": f"launchd deploy gap: {len(at_risk)} loaded job(s) do not run their default branch as merged",
        "body": body,
        "key": finding_key(LINEAR_DETECTOR, _ROLLUP_SUBJECT),
        "detector": LINEAR_DETECTOR,
    }]


def launchctl_listing():
    """`launchctl list` stdout. Every failure is a RuntimeError, so a caller has
    one exception to turn into NO ANSWER."""
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"launchctl list failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"launchctl list exited {proc.returncode}")
    return proc.stdout


def run_check(prefixes, fleet_health, dry_run, agents_dir=LAUNCH_AGENTS):
    """Survey, print, and file the rollup. Returns the file_findings outcome."""
    jobs = survey(launchctl_listing(), prefixes, agents_dir)
    for job in jobs:
        print(f"DEPLOY-GAP {'RISK' if job['reasons'] else 'ok'}: {report_line(job)}")
    at_risk = sum(1 for j in jobs if j["reasons"])
    print(f"deploy gap: {at_risk} of {len(jobs)} loaded watched job(s) off their default")
    findings = linear_findings(jobs, fleet_health.finding_key)
    outcome = fleet_health.file_findings(findings, apply=not dry_run, filer="launchd-deploy-gap.py")
    # Only this side knows how many were owed. Without it the watchdog's
    # unfiled_count fell back to skipped_no_key, and a refused write (errors=1)
    # printed the clean fleet's unfiled=0 (PR #361 review r2).
    outcome["owed"] = len(findings)
    return outcome


def _watched_prefixes():
    """The watchdog's prefix set, borrowed so the two never disagree on scope."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("wd", HERE / "launchd-health-check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_watched_prefixes()


def main(argv):
    if argv[:1] == ["--live"]:
        if len(argv) != 3:
            print("usage: launchd-deploy-gap.py --live SHA LABEL", file=sys.stderr)
            return 2
        try:
            listing = launchctl_listing()
        except RuntimeError as exc:
            # Exit 1 means "not live". A listing we could not read says nothing
            # about the commit, so it is NO ANSWER (PR #361 review).
            print(f"NO ANSWER: {exc}")
            return 2
        live, why = commit_live_for_job(argv[2], argv[1], listing, _watched_prefixes())
        print(("LIVE: " if live else "NOT LIVE: " if live is False else "NO ANSWER: ") + why)
        return {True: 0, False: 1}.get(live, 2)
    if argv:
        print(f"unrecognized: {' '.join(argv)}", file=sys.stderr)
        return 2
    jobs = survey(launchctl_listing(), _watched_prefixes())
    for job in jobs:
        print(f"{'RISK' if job['reasons'] else 'ok  '} {report_line(job)}")
    print(f"{sum(1 for j in jobs if j['reasons'])} of {len(jobs)} loaded watched job(s) off their default")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
