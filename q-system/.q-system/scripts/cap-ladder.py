#!/usr/bin/env python3
"""cap-ladder.py: the one consumer of every cap in the fleet (ASK-3824).

WHY THIS FILE EXISTS
--------------------
Every cap in the loop ended in a page and a parked state that nothing read:

    converge.sh       3 rounds, record-capout, "Parked -- until you clear it"
    pr-review-agent   3 review rounds, PENDING status, "needs a human decision"
    linear-worker.sh  3 attempts, "Human action needed", skipped every tick
    linear-worker.sh  2 rebase rounds, conflict_paged, "needs a human"
    review-redrive    one machine attempt per head, then a page, then nothing

Both redrives skip a capout (ci-redrive.py capout_skip), the worker skips a
ticket at 3 attempts, and wip_release only fires at 5 open sana/ PRs in one
repo. Measured 2026-11-08: no target repo had more than 3, so every capped PR
sat open with no mover (dead-end audit, ~/.config/kipi/handoffs/2026-11-08-dead-end-audit.md).

THE FOUNDER'S RULINGS, the spec for the ladder below:
  2026-11-06 "after 3 failed merges we must stop, change agent and use fable to
             do a full rca"
  2026-11-08 "So you're telling me if Fable does the root cause and Opus still
             fails? After that it just hangs and goes nowhere. But that's
             against my direction. That doesn't work."
  iteration-speed.md rule 6: at round 3, hand off to a fresh agent, which
             writes an RCA and continues. Hand off, never stop.

THE LADDER (one rung per cap event, per issue, counter kept forever)
--------------------------------------------------------------------
  rung 1  rca       a fresh model (Fable, fable-escalate.py --kind rca) writes
                    an RCA of the full packet, then the work continues.
  rung 2  runner    a new RCA, and the next attempt runs on a different runner
                    (ledger flag ladder_runner_codex, read by linear-worker.sh).
  rung 3  rescope   a new RCA, needs-scope, and linear-dor-drafter.py --issue
                    rewrites the Definition of Ready in the same run.
  rung 4+ reentry   a timed re-entry: 7, then 14, then every 28 days, a new RCA
                    each time, the runner alternating. Never terminal.

THE 11-07 AMENDMENT IS NOT FOLLOWED, ON PURPOSE. It ended the ladder in a park
that chief E2 closes at 14 days. A park is a terminal state wearing a date, and
E2 closes 0 parks a day behind its 200-write cap (measured 2026-11-08). The
founder's 2026-11-08 ruling above supersedes it; main approved this ladder.

HOW "CONTINUE" IS MADE REAL, AND WHY A NEW PR
---------------------------------------------
A capped PR cannot continue in place: a review-capped PR gets no more reviews
(its round count is review records on disk, which nothing may delete), and a
fresh pick of a ticket with no open PR cuts its tree from origin/main with
`worktree add -B` (linear-worker.sh), so the old branch would be reset under it
and the push refused. So the ladder closes the capped PR (branch kept, never
--delete-branch) and opens a NEW PR on the same branch. The worker then sees an
open PR, bases its tree on origin/<branch>, and runs a rework round whose prompt
reads the Linear comments, where the RCA was posted. review-redrive sees the new
PR's absent reviewer slot and re-reviews it. Both are existing consumers.

SINGLE WRITERS. The ladder's own state is one file, written only here, through a
temp file and a rename under a lock. The attempts ledger is written only through
attempts-ledger.py. Linear is written only through linear-sync.py. GitHub only
through gh. Each is a seam so the test drives every one of them.

Exit is always 0 under launchd; the summary line says what happened.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

MAX_ATTEMPTS = 3                      # linear-worker.sh MAX_ATTEMPTS
COOLDOWN_DAYS = (7, 14, 28)           # rung 4, rung 5, rung 6 and every rung after
RUNG_NAMES = {1: "rca", 2: "runner", 3: "rescope"}
RUNNER_FLAG = "ladder_runner_codex"   # read by linear-worker.sh ladder_runner_for
JOB = "cap-ladder.py (com.kipi.cap-ladder, nightly 04:40)"
LANE_PREFIX = "sana/"


def env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name) or default)


STATE = env_path("CAP_LADDER_STATE", HOME / ".local/state/kipi/cap-ladder/state.json")
ATTEMPTS = env_path("CAP_LADDER_ATTEMPTS", HOME / ".config/kipi/linear-worker-attempts.json")
REVIEWS = env_path("CAP_LADDER_REVIEWS", HOME / ".config/kipi/pr-reviews")
LEDGER = [sys.executable, str(HERE / "attempts-ledger.py")]


def cmd(name: str, default: list) -> list:
    """A seam: the env var holds a command line, else the real one."""
    raw = os.environ.get(name)
    return shlex.split(raw) if raw else default


GH = cmd("CAP_LADDER_GH", ["gh"])
SYNC = cmd("CAP_LADDER_SYNC", [sys.executable, str(HERE / "linear-sync.py")])
FABLE = cmd("CAP_LADDER_FABLE", [sys.executable, str(HERE / "fable-escalate.py")])
DRAFTER = cmd("CAP_LADDER_DRAFTER", [sys.executable, str(HERE / "linear-dor-drafter.py")])
PS = cmd("CAP_LADDER_PS", ["ps", "-Ao", "args="])


def now() -> datetime:
    fixed = os.environ.get("CAP_LADDER_NOW")
    return datetime.fromisoformat(fixed) if fixed else datetime.now(timezone.utc)


def run(argv: list, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, str(exc)


def say(msg: str) -> None:
    print(f"{now().strftime('%Y-%m-%dT%H:%M:%SZ')} cap-ladder: {msg}", flush=True)


# --- state: one writer, temp + rename under a lock ---------------------------

def read_state() -> dict:
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, STATE)


# --- targets and their open PRs ----------------------------------------------

def slug_of(remote: str) -> str:
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?/?$", remote or "")
    return m.group(1) if m else ""


def targets() -> list:
    """[{slug, project}] for the repos the dispatcher enters.

    The same opt-in set as kipi-dispatch.sh fleet_candidates: the home row, plus
    registry and overlay rows with dispatch.enabled true. A row switched off
    (chief, 2026-11-08) is left out, so the ladder never enters a repo the
    dispatcher would not.
    """
    raw = os.environ.get("CAP_LADDER_TARGETS")
    if raw:
        return json.loads(raw)
    out, seen = [], set()
    reg_path = HERE.parent.parent.parent / "instance-registry.json"
    rows = []
    try:
        reg = json.loads(reg_path.read_text())
        sk = reg.get("skeleton") or {}
        out.append({"slug": slug_of(sk.get("remote", "")), "project": sk.get("linear_project", "")})
        rows += reg.get("instances") or []
    except (OSError, ValueError):
        pass
    try:
        rows += json.loads((HOME / ".config/kipi/dispatch-targets.json").read_text()).get("instances") or []
    except (OSError, ValueError):
        pass
    for r in rows:
        d = r.get("dispatch") or {}
        if d.get("enabled") is True:
            out.append({"slug": slug_of(d.get("expected_remote", "")),
                        "project": r.get("linear_project") or r.get("name", "")})
    final = []
    for t in out:
        if t["slug"] and t["slug"] not in seen:
            seen.add(t["slug"])
            final.append(t)
    return final


def open_prs(slug: str) -> list:
    rc, out = run(GH + ["pr", "list", "-R", slug, "--state", "open", "--limit", "200", "--json",
                        "number,headRefName,headRefOid,title,baseRefName,url"])
    if rc != 0:
        say(f"WARN gh could not list open PRs in {slug}; its caps wait for the next run")
        return []
    try:
        return json.loads(out or "[]")
    except ValueError:
        return []


def issue_of_branch(branch: str) -> str:
    m = re.match(r"^sana/(ask-\d+)(?:-.*)?$", branch or "")
    return m.group(1).upper() if m else ""


# --- the cap events -----------------------------------------------------------

def read_ledger() -> dict:
    try:
        data = json.loads(ATTEMPTS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def find_caps(ledger: dict, prs_by_issue: dict, slug_by_pr: dict) -> dict:
    """{issue: [signature, ...]} for every cap that holds a ticket or PR now.

    A signature names ONE cap event. The ladder clears what it consumed, so a
    signature that is still present on the next run is either new or a write
    that failed, and both deserve the next look.
    """
    caps: dict = {}

    def add(issue, sig):
        caps.setdefault(issue, []).append(sig)

    for issue, e in ledger.items():
        if not isinstance(e, dict):
            continue
        if e.get("capout"):
            add(issue, f"capout:{e.get('capout_at', '')}")
        if isinstance(e.get("count"), int) and e["count"] >= MAX_ATTEMPTS:
            add(issue, f"attempts:{e.get('last', '')}")
        if e.get("conflict_paged"):
            add(issue, f"conflict:{e.get('last_conflict', '')}")
        for key in e:
            m = re.match(r"^review_escalated_[a-z]+_pr(\d+)_", key)
            pr = prs_by_issue.get(issue)
            if m and pr and str(pr["number"]) == m.group(1):
                add(issue, f"escalated:{key}")
    # The reviewer's cap leaves a marker per repo and PR, and a PENDING status no
    # redrive reads. Only an OPEN PR is a live cap; a closed one is history.
    for issue, pr in prs_by_issue.items():
        slug = slug_by_pr[(issue, pr["number"])]
        name = f".round-cap-{slug.replace('/', '_')}-pr-{pr['number']}"
        # Both engines: pr-review-agent.sh writes the codex engine's marker one
        # directory down (ENGINE_DIR=$OUT_DIR/codex).
        if (REVIEWS / name).exists() or (REVIEWS / "codex" / name).exists():
            add(issue, f"reviewcap:{slug}#{pr['number']}")
    return caps


# --- Linear -------------------------------------------------------------------

_SYNC_MOD = None


def ticket(issue: str) -> dict | None:
    """{state_type, labels, project, title} or None when it cannot be read."""
    fixture = os.environ.get("CAP_LADDER_LINEAR_FIXTURE")
    if fixture:
        return (json.loads(Path(fixture).read_text()) or {}).get(issue)
    global _SYNC_MOD
    try:
        if _SYNC_MOD is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location("kipi_linear_sync_ladder",
                                                          str(HERE / "linear-sync.py"))
            _SYNC_MOD = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_SYNC_MOD)
        data = _SYNC_MOD.graphql(
            "query($id:String!){issue(id:$id){title state{type} project{name} labels{nodes{name}}}}",
            {"id": issue})
        i = data.get("issue") or {}
        return {"state_type": (i.get("state") or {}).get("type", ""),
                "labels": [n["name"] for n in (i.get("labels") or {}).get("nodes") or []],
                "project": (i.get("project") or {}).get("name") or "",
                "title": i.get("title") or ""}
    except Exception as exc:  # noqa: BLE001 - one unreadable ticket must not stop the run
        say(f"WARN could not read {issue} from Linear ({str(exc)[:120]}); it waits for the next run")
        return None


def live(issue: str, pr: dict | None) -> bool:
    rc, table = run(PS, timeout=20)
    if rc != 0:
        return True   # cannot see the table: assume live, the cost is one night
    pats = [rf"converge\.sh\s+--issue\s+{issue}(\s|$)", rf"--issue\s+{issue}(\s|$)"]
    if pr:
        pats.append(rf"pr-review-agent\.sh\s+{pr['number']}(\s|$)")
    return any(re.search(p, table, re.M) for p in pats)


# --- one rung -----------------------------------------------------------------

def rung_name(r: int) -> str:
    return RUNG_NAMES.get(r, "reentry")


def cooldown_days(r: int) -> int:
    return 0 if r < 4 else COOLDOWN_DAYS[min(r - 4, len(COOLDOWN_DAYS) - 1)]


def next_step_line(r: int) -> str:
    nxt = r + 1
    wait = cooldown_days(nxt)
    when = "at its next nightly run after the cap" if not wait else f"{wait} days after this step"
    return (f"If this caps again, {JOB} takes rung {nxt} ({rung_name(nxt)}) {when}. "
            "The ladder has no last rung.")


def ledger(op: list) -> bool:
    rc, out = run(LEDGER + [str(ATTEMPTS)] + op)
    if rc not in (0, 1):
        say(f"WARN attempts-ledger {' '.join(op)} exited {rc}: {out[:160]}")
        return False
    return True


def swap_pr(slug: str, pr: dict, issue: str, r: int, rca: str) -> str:
    """Close the capped PR (branch kept) and open a new one on the same branch.

    Returns the new PR's URL, or "" when it could not be opened.
    """
    branch = pr["headRefName"]
    sha = (pr.get("headRefOid") or "")[:12]
    close_note = (f"Closed by {JOB}, rung {r} ({rung_name(r)}) of the cap ladder (ASK-3824). "
                  f"Branch {branch} is kept at {sha}; the work continues on a new PR from it. "
                  f"RCA: {rca or 'none produced'}. Nothing was deleted; reopen this PR to undo.")
    rc, _ = run(GH + ["pr", "close", str(pr["number"]), "-R", slug, "--comment", close_note])
    if rc != 0:
        say(f"WARN could not close PR #{pr['number']} in {slug}; it stays open")
        return ""
    body = (f"Resumes #{pr['number']} after it capped. {issue}, cap ladder rung {r} "
            f"({rung_name(r)}). RCA: {rca or 'none produced'}. "
            f"Read the RCA comment on {issue} first: its STOP section names the approach that looped.")
    rc, out = run(GH + ["pr", "create", "-R", slug, "--head", branch, "--base",
                        pr.get("baseRefName") or "main", "--title", pr.get("title") or issue,
                        "--body", body])
    if rc != 0:
        say(f"WARN closed PR #{pr['number']} but could not open its successor on {branch}: {out[:160]}")
        return ""
    return out.splitlines()[-1] if out else "(opened)"


def climb(issue: str, sigs: list, t: dict, pr: dict | None, slug: str, state: dict,
          apply: bool) -> str:
    """Apply the next rung to one capped issue. Returns a one-line outcome."""
    row = state.get(issue) or {}
    r = int(row.get("rung", 0)) + 1
    wait = cooldown_days(r)
    if wait and row.get("last_at"):
        due = datetime.fromisoformat(row["last_at"]) + timedelta(days=wait)
        if now() < due:
            return f"{issue}: rung {r} ({rung_name(r)}) is due {due.date().isoformat()}; nothing to do yet"
    kind = sigs[0].split(":", 1)[0]
    why = f"{kind} cap ({', '.join(s.split(':', 1)[0] for s in sigs)})"
    if not apply:
        return f"[dry] {issue}: would take rung {r} ({rung_name(r)}) on its {why}"

    # 1. The RCA, every rung: a fresh model, the full packet, never the implementer.
    argv = FABLE + ["--kind", "rca", "--issue", issue, "--site", kind, "--reason", why, "--json"]
    if pr:
        argv += ["--pr", str(pr["number"]), "--branch", pr["headRefName"], "--repo-args", f"-R {slug}"]
    rc, out = run(argv, timeout=600)
    try:
        rca = (json.loads(out.splitlines()[-1]) if out else {}).get("rca_path") or ""
    except (ValueError, IndexError):
        rca = ""
    # A failed RCA does not cost the cap its exit: the work still continues.

    # 2. The runner. Rung 2 and every even re-entry run on the other runner.
    ledger(["claim-flag" if (r == 2 or (r >= 4 and r % 2 == 0)) else "clear-flag", issue, RUNNER_FLAG])

    # 3. Rung 3 re-scopes: the label goes on BEFORE the ticket can be picked, and
    #    the drafter rewrites the DoR in this same run and drops the label.
    if r == 3:
        run(SYNC + ["label", issue, "needs-scope"])

    # 4. Continue: the work needs an OPEN PR on sana/<id> whenever that branch
    #    holds commits, because a fresh pick without one cuts its tree from main
    #    and resets the branch. A PR that cannot be opened stops the rung HERE,
    #    before the clears, so the cap record survives and tomorrow retries it.
    branch = f"{LANE_PREFIX}{issue.lower()}"
    new_pr = ""
    if pr and pr["headRefName"].lower() == branch:
        new_pr = swap_pr(slug, pr, issue, r, rca)
        if not new_pr:
            return f"{issue}: rung {r} could not move PR #{pr['number']} to a new PR; the cap stays, the next run retries"
    elif pr:
        say(f"{issue}: PR #{pr['number']} is on lane branch {pr['headRefName']}; "
            "pr-owner.py (ASK-3962) owns lane PRs, so the ticket continues on a fresh branch")
    else:
        rc, ahead = run(GH + ["api", f"repos/{slug}/compare/main...{branch}", "--jq", ".ahead_by"])
        if rc == 0 and ahead.strip().isdigit() and int(ahead) > 0:
            rc, out = run(GH + ["pr", "create", "-R", slug, "--head", branch, "--base", "main",
                                "--title", t.get("title") or issue,
                                "--body", f"Resumes {branch} after {issue} capped (cap ladder rung {r}). RCA: {rca or 'none produced'}."])
            if rc != 0:
                return f"{issue}: rung {r} could not open a PR from {branch}; the cap stays, the next run retries"
            new_pr = out.splitlines()[-1] if out else "(opened)"

    # 5. Clear what the cap left, so every consumer sees a live ticket again.
    for op in (["clear-capout", issue], ["clear-flag", issue, "count"],
               ["clear-flag", issue, "stuck_paged"], ["clear-conflict", issue]):
        ledger(op)
    run(SYNC + ["requeue", issue, "--exit", f"cap-ladder-rung-{r}",
                "--why", f"{why}; rung {r} ({rung_name(r)}); RCA {rca or 'none'}", "--agent", "sana"])
    if r == 3:
        run(DRAFTER + ["--issue", issue, "--limit", "1", "--apply"], timeout=900)

    note = (f"**Cap ladder, rung {r} ({rung_name(r)}).** {issue} hit a {why}. "
            f"RCA: {rca or 'none produced (the work continues anyway)'}. "
            + (f"New PR {new_pr} on {branch}, which is kept" + ("; the capped PR is closed. " if pr else ". ") if new_pr else "")
            + ("The next attempt runs on the other runner (Codex). " if r == 2 or (r >= 4 and r % 2 == 0) else "")
            + ("The Definition of Ready is rewritten by linear-dor-drafter.py in this run. " if r == 3 else "")
            + next_step_line(r))
    run(SYNC + ["progress", issue, note, "--agent", "sana"])

    # The state is written LAST: a run that dies above leaves the rung unspent,
    # and the next night redoes it rather than skipping it.
    state[issue] = {"rung": r, "last_at": now().isoformat(), "handled": sigs,
                    "history": (row.get("history") or [])[-20:] + [
                        {"rung": r, "at": now().isoformat(), "sigs": sigs, "rca": rca, "new_pr": new_pr}]}
    return f"{issue}: rung {r} ({rung_name(r)}) taken on its {why}" + (f", new PR {new_pr}" if new_pr else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write; without it, print the plan")
    ap.add_argument("--limit", type=int, default=5, help="caps climbed per run (bounds RCA spend)")
    args = ap.parse_args(argv)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("CAP_LADDER_STATE"):
        print("cap-ladder: REFUSED under pytest without CAP_LADDER_STATE (live data path)", file=sys.stderr)
        return 4

    tgts = targets()
    project_slug = {t["project"]: t["slug"] for t in tgts if t.get("project")}
    prs_by_issue, slug_by_pr = {}, {}
    for t in tgts:
        for pr in open_prs(t["slug"]):
            issue = issue_of_branch(pr.get("headRefName", ""))
            if issue and issue not in prs_by_issue:
                prs_by_issue[issue] = pr
                slug_by_pr[(issue, pr["number"])] = t["slug"]

    caps = find_caps(read_ledger(), prs_by_issue, slug_by_pr)
    state = read_state()
    lock_path = STATE.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            say("another cap-ladder run holds the lock; this one exits")
            return 0
        done = 0
        for issue in sorted(caps):
            if done >= args.limit:
                say(f"limit {args.limit} reached; the rest climb tomorrow")
                break
            sigs = sorted(caps[issue])
            # HANDLED IS A 20-HOUR MEMORY, NOT A FOREVER SKIP. The ladder clears
            # what it consumes, so a signature still here a night later means a
            # clear failed. Skipping it for good would rebuild the dead end this
            # file exists to remove; acting again is the recovery.
            row = state.get(issue) or {}
            if (set(sigs) <= set(row.get("handled") or []) and row.get("last_at")
                    and now() - datetime.fromisoformat(row["last_at"]) < timedelta(hours=20)):
                continue
            t = ticket(issue)
            if t is None:
                continue
            if t.get("state_type") in ("completed", "canceled", "duplicate"):
                state.pop(issue, None)
                continue
            pr = prs_by_issue.get(issue)
            slug = slug_by_pr.get((issue, pr["number"])) if pr else project_slug.get(t.get("project", ""))
            if not slug:
                say(f"{issue}: project {t.get('project') or '(none)'} has no dispatch target; "
                    "the router tickets (ASK-3959, ASK-3958) own that, the ladder waits")
                continue
            if live(issue, pr):
                say(f"{issue}: a run is live on it; the ladder looks again tomorrow")
                continue
            say(climb(issue, sigs, t, pr, slug, state, args.apply))
            done += 1
        if args.apply:
            write_state(state)
    say(f"run complete: {len(caps)} capped, {done} climbed{'' if args.apply else ' (dry)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
