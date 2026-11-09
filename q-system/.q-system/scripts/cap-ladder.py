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

Both redrives skip a capout, the worker skips a ticket at 3 attempts, and
wip_release only fires at 5 open sana/ PRs in one repo. Measured 2026-11-08: no
target repo had more than 3, so every capped PR sat open with no mover
(dead-end audit, ~/.config/kipi/handoffs/2026-11-08-dead-end-audit.md).

THE FOUNDER'S RULINGS, the spec for the ladder below:
  2026-11-06 "after 3 failed merges we must stop, change agent and use fable to
             do a full rca"
  2026-11-08 "So you're telling me if Fable does the root cause and Opus still
             fails? After that it just hangs and goes nowhere."
  2026-11-08 "What's the point of timed retries? What's gonna change in seven,
             fourteen or 28 days?"
  2026-11-08 "but what happens if nothing changed? the ticket just stays?"
  iteration-speed.md rule 2: the same failure twice means stop and diagnose.

THE LADDER (one rung per cap event, per issue, counter kept)
------------------------------------------------------------
  rung 1  rca       a fresh model (Fable, fable-escalate.py --kind rca) writes an
                    RCA of the full packet, then the work continues.
  rung 2  runner    a new RCA, and the next attempt runs on Codex (ledger flag
                    ladder_runner_codex, read by linear-worker.sh).
  rung 3  rescope   a new RCA, needs-scope, and linear-dor-drafter.py --issue
                    rewrites the Definition of Ready in the same run.
  rung 4+ decide    NO TIMED RETRY. The RCA agent records exactly one decision:
                      SPLIT       sub-tickets filed (owner:sana, same project, a
                                  DoR each); the parent closes Done, "split into".
                      CLOSE       Canceled with the RCA path as the reason.
                      BLOCKED-ON  an open owned ticket or an open fleet PR.
                                  A FOUNDER-DECISION blocker is refused for now;
                                  its channel ships in ASK-4069 (see check_blocker).
                    A BLOCKED-ON answer that names anything else is refused and
                    the agent is asked again for SPLIT or CLOSE only; two invalid
                    answers in a row default to SPLIT on the RCA's own findings.

  A BLOCKED-ON ticket is held (ledger flag ladder_hold, read by the worker) and
  re-enters ONLY on an event since its decision: (a) its blocker closed, (b) a
  file its last attempt touched or its RCA names changed on origin/main, (c) its
  description changed, (d) the worker's model config changed. No event, no run,
  and one log line naming the event it waits on. A ticket that is the blocker of
  N held tickets is picked first in its priority band (cap-ladder-blockers.json).

So nothing just stays: every capped ticket either moves on a rung, ends on a
recorded decision, or waits on a named, owned event, and the report file lists
each one with what it waits on. Two rows are marked red there, and each has a
consumer: a capped ticket with no decision on file keeps its cap, so this script
asks again at its next nightly run; a blocker that lost its owner:* label gets
owner:sana back from linear-owner-sweep.py (com.kipi.linear-owner-sweep, 02:00),
before this script's 04:40 run reads it again.

HOW "CONTINUE" IS MADE REAL, AND WHY A NEW PR
---------------------------------------------
A review-capped PR gets no more reviews (its round count is review records on
disk, which nothing may delete), and a fresh pick of a ticket with no open PR
cuts its tree from origin/main with `worktree add -B`, so the old branch would be
reset and the push refused. So the ladder closes the capped PR (branch kept,
never --delete-branch) and opens a NEW PR on the same branch. The worker then
bases its tree on origin/<branch> and runs a rework round whose prompt reads the
Linear comments, where the RCA was posted.

SINGLE WRITERS. The ladder's own state, report and blockers files are written
only here, through a temp file and a rename under a lock. The attempts ledger is
written only through attempts-ledger.py. GitHub only through gh. Each outside
call is a seam the test drives.

Exit is always 0 under launchd; the summary line says what happened.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

MAX_ATTEMPTS = 3                      # linear-worker.sh MAX_ATTEMPTS
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
    """(rc, stdout). On a failure the stderr rides along, so a caller can tell
    gh's 404 from a network fault."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        out = (p.stdout or "").strip()
        return p.returncode, out if p.returncode == 0 else (out + "\n" + (p.stderr or "")).strip()
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


def cap_sigs(e: dict, slug: str = "", pr_number=None, reviews: Path = REVIEWS) -> list:
    """Every cap signature one ledger entry holds, for one open PR or none.

    THE ONE DEFINITION OF "CAPPED". find_caps (this file) and ladder_owns (read
    by pr-owner.py, ASK-3962) both ask it, so the two consumers can never
    disagree about which PRs the ladder owns. Two copies of one rule is how a
    PR ends up with two writers, or with none.
    """
    out = []
    e = e if isinstance(e, dict) else {}
    if e.get("capout"):
        out.append(f"capout:{e.get('capout_at', '')}")
    if isinstance(e.get("count"), int) and e["count"] >= MAX_ATTEMPTS:
        out.append(f"attempts:{e.get('last', '')}")
    if e.get("conflict_paged"):
        out.append(f"conflict:{e.get('last_conflict', '')}")
    if pr_number is not None:
        for key in e:
            m = re.match(r"^review_escalated_[a-z]+_pr(\d+)_", key)
            if m and m.group(1) == str(pr_number):
                out.append(f"escalated:{key}")
        name = f".round-cap-{slug.replace('/', '_')}-pr-{pr_number}"
        # Both engines: pr-review-agent.sh writes the codex engine's marker one
        # directory down (ENGINE_DIR=$OUT_DIR/codex).
        if (reviews / name).exists() or (reviews / "codex" / name).exists():
            out.append(f"reviewcap:{slug}#{pr_number}")
    return out


def find_caps(ledger: dict, prs_by_issue: dict, slug_by_pr: dict) -> dict:
    """{issue: [signature, ...]} for every cap that holds a ticket or PR now.

    A signature names ONE cap event. The ladder clears what it consumed, so a
    signature still present on the next run is either new or a write that
    failed, and both deserve the next look. Only an OPEN PR carries the PR-keyed
    caps (escalation, review cap): a closed one is history.
    """
    caps: dict = {}
    for issue in set(ledger) | set(prs_by_issue):
        pr = prs_by_issue.get(issue)
        sigs = cap_sigs(ledger.get(issue) or {}, slug_by_pr.get((issue, pr["number"]), "") if pr else "",
                        pr["number"] if pr else None)
        if sigs:
            caps[issue] = sigs
    return caps


def ladder_owns(slug: str, number: int, branch: str, state_dir: str) -> str:
    """"" when cap-ladder.py does not own this PR, else a one-line reason.

    For pr-owner.py (ASK-3962), which loads this file by path and yields any PR
    the ladder owns. Lane branches (sana/<id>-<slug>) are never the ladder's:
    pr-owner.py owns them. `state_dir` is the worker's KIPI_STATE_DIR, where the
    attempts ledger and pr-reviews/ live.
    """
    issue = issue_of_branch(branch)
    if not issue or branch.lower() != f"{LANE_PREFIX}{issue.lower()}":
        return ""
    try:
        e = (json.loads((Path(state_dir) / "linear-worker-attempts.json").read_text()) or {}).get(issue) or {}
    except (OSError, ValueError):
        e = {}
    sigs = cap_sigs(e, slug, number, Path(state_dir) / "pr-reviews")
    if e.get(HOLD_FLAG):
        sigs.append("held on a BLOCKED-ON decision")
    if not sigs:
        return ""
    return f"cap-ladder owns it: {issue} holds {', '.join(s.split(':', 1)[0] for s in sigs)}"


HOLD_FLAG = "ladder_hold"             # read by linear-worker.sh, issue loop
BLOCKERS = env_path("CAP_LADDER_BLOCKERS", HOME / ".config/kipi/cap-ladder-blockers.json")
REPORT = env_path("CAP_LADDER_REPORT", HOME / ".local/state/kipi/cap-ladder/report.json")
OPEN_TYPES = ("backlog", "unstarted", "started", "triage")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, path)


# --- Linear: reads, and the three writes a decision needs ---------------------

_SYNC_MOD = None


def _sync():
    global _SYNC_MOD
    if _SYNC_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("kipi_linear_sync_ladder", str(HERE / "linear-sync.py"))
        _SYNC_MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_SYNC_MOD)
    return _SYNC_MOD


def ticket(issue: str) -> dict | None:
    """{state_type, labels, project, title, desc_hash, ...} or None when unreadable."""
    fixture = os.environ.get("CAP_LADDER_LINEAR_FIXTURE")
    try:
        if fixture:
            i = (json.loads(Path(fixture).read_text()) or {}).get(issue)
            if i is None:
                return None
            return dict(i, desc_hash=hashlib.sha256((i.get("description") or "").encode()).hexdigest()[:16])
        data = _sync().graphql(
            "query($id:String!){issue(id:$id){id title description state{type} team{id} "
            "project{id name} labels{nodes{name}}}}", {"id": issue})
        i = data.get("issue") or {}
        return {"state_type": (i.get("state") or {}).get("type", ""),
                "labels": [n["name"] for n in (i.get("labels") or {}).get("nodes") or []],
                "project": (i.get("project") or {}).get("name") or "", "title": i.get("title") or "",
                "desc_hash": hashlib.sha256((i.get("description") or "").encode()).hexdigest()[:16],
                "uuid": i.get("id"), "team_id": (i.get("team") or {}).get("id"),
                "project_id": (i.get("project") or {}).get("id")}
    except Exception as exc:  # noqa: BLE001 - one unreadable ticket must not stop the run
        say(f"WARN could not read {issue} from Linear ({str(exc)[:120]}); it waits for the next run")
        return None


def owned_open(t: dict | None) -> bool:
    return bool(t) and t.get("state_type") in OPEN_TYPES and any(
        l.startswith("owner:") for l in t.get("labels") or [])


def lin(op: str, **kw):
    """create -> new identifier; state / relate -> True. Seam: CAP_LADDER_LINEAR_LOG."""
    log = os.environ.get("CAP_LADDER_LINEAR_LOG")
    if log:
        with open(log, "a") as fh:
            fh.write(json.dumps(dict(op=op, **kw)) + "\n")
        return f"ASK-9{sum(1 for _ in open(log)):03d}" if op == "create" else True
    g = _sync().graphql
    if op == "create":
        p = ticket(kw["parent"]) or {}
        ids = []
        for name in kw.get("labels") or []:
            lab = g('query($n:String!){issueLabels(filter:{name:{eq:$n}}){nodes{id}}}', {"n": name})
            ids += [n["id"] for n in lab["issueLabels"]["nodes"]][:1]
        inp = {"teamId": p.get("team_id"), "title": kw["title"], "description": kw["description"],
               "parentId": p.get("uuid"), "labelIds": ids}
        if p.get("project_id"):
            inp["projectId"] = p["project_id"]
        res = g("mutation($i:IssueCreateInput!){issueCreate(input:$i){success issue{identifier}}}", {"i": inp})
        return ((res.get("issueCreate") or {}).get("issue") or {}).get("identifier") or ""
    if op == "state":
        t = ticket(kw["issue"]) or {}
        states = g('query($t:ID!){workflowStates(filter:{team:{id:{eq:$t}}}){nodes{id type}}}',
                   {"t": t.get("team_id")})["workflowStates"]["nodes"]
        sid = next((s["id"] for s in states if s["type"] == kw["type"]), None)
        res = g("mutation($id:String!,$i:IssueUpdateInput!){issueUpdate(id:$id,input:$i){success}}",
                {"id": kw["issue"], "i": {"stateId": sid}})
        return bool((res.get("issueUpdate") or {}).get("success"))
    if op == "relate":
        a, b = ticket(kw["blocker"]) or {}, ticket(kw["blocked"]) or {}
        res = g("mutation($i:IssueRelationCreateInput!){issueRelationCreate(input:$i){success}}",
                {"i": {"issueId": a.get("uuid"), "relatedIssueId": b.get("uuid"), "type": "blocks"}})
        return bool((res.get("issueRelationCreate") or {}).get("success"))
    raise ValueError(op)


def live(issue: str, pr: dict | None) -> bool:
    rc, table = run(PS, timeout=20)
    if rc != 0:
        return True   # cannot see the table: assume live, the cost is one night
    pats = [rf"converge\.sh\s+--issue\s+{issue}(\s|$)", rf"--issue\s+{issue}(\s|$)"]
    if pr:
        pats.append(rf"pr-review-agent\.sh\s+{pr['number']}(\s|$)")
    return any(re.search(p, table, re.M) for p in pats)


def ledger(op: list) -> bool:
    rc, out = run(LEDGER + [str(ATTEMPTS)] + op)
    if rc not in (0, 1):
        say(f"WARN attempts-ledger {' '.join(op)} exited {rc}: {out[:160]}")
        return False
    return True


def clear_caps(issue: str) -> None:
    for op in (["clear-capout", issue], ["clear-flag", issue, "count"],
               ["clear-flag", issue, "stuck_paged"], ["clear-conflict", issue]):
        ledger(op)


# --- GitHub ---------------------------------------------------------------------

def close_pr(slug: str, pr: dict, note: str) -> bool:
    """Close with the branch kept. NEVER --delete-branch: the branch is the resume point."""
    rc, _ = run(GH + ["pr", "close", str(pr["number"]), "-R", slug, "--comment", note])
    if rc != 0:
        say(f"WARN could not close PR #{pr['number']} in {slug}; it stays open")
    return rc == 0


def open_from_branch(slug: str, branch: str, title: str, body: str) -> tuple[bool, str]:
    """(ok, url). ok is False only when the branch holds work and the PR would not open."""
    rc, ahead = run(GH + ["api", f"repos/{slug}/compare/main...{branch}", "--jq", ".ahead_by"])
    # ONLY A 404 MEANS "NO BRANCH" (PR #662 review, major 2). Any other failure is
    # a gh or network fault, and reading it as "nothing to resume" cleared the cap
    # with no successor PR. So it is a refusal: the cap stays, the next run retries.
    if rc != 0:
        return ("404" in ahead or "Not Found" in ahead), ""
    if not ahead.strip().isdigit() or int(ahead) == 0:
        return True, ""        # the branch exists and holds nothing to resume
    rc, out = run(GH + ["pr", "create", "-R", slug, "--head", branch, "--base", "main",
                        "--title", title, "--body", body])
    return (rc == 0), (out.splitlines()[-1] if rc == 0 and out else "")


def changed_on_main(slug: str, since_sha: str) -> list:
    if not since_sha:
        return []
    rc, out = run(GH + ["api", f"repos/{slug}/compare/{since_sha}...main", "--jq", "[.files[].filename]"])
    try:
        return json.loads(out) if rc == 0 and out else []
    except ValueError:
        return []


def main_sha(slug: str) -> str:
    rc, out = run(GH + ["api", f"repos/{slug}/commits/main", "--jq", ".sha"])
    return out.strip() if rc == 0 else ""


def branch_files(slug: str, branch: str) -> list:
    rc, out = run(GH + ["api", f"repos/{slug}/compare/main...{branch}", "--jq", "[.files[].filename]"])
    try:
        return json.loads(out) if rc == 0 and out else []
    except ValueError:
        return []


def model_fp() -> str:
    """The worker's runner and model config, as one fingerprint (event d)."""
    fixed = os.environ.get("CAP_LADDER_MODEL_FP")
    if fixed:
        return fixed
    parts = []
    try:
        parts.append(str(json.loads((HOME / ".claude/settings.json").read_text()).get("model")))
    except (OSError, ValueError):
        parts.append("?")
    try:
        parts += [l for l in (HERE / "linear-worker.sh").read_text().splitlines()
                  if l.startswith(("CODEX_CMD=", "SECOND_RUNNER_FALLBACK="))]
    except OSError:
        pass
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


# --- the RCA and the decision ---------------------------------------------------

DECISION_RE = re.compile(r"^\s*DECISION:\s*(SPLIT|CLOSE|BLOCKED-ON)\b[ \t]*(.*)$", re.M)
SUB_RE = re.compile(r"^\s*SUBTICKET:\s*(.+?)\s*::\s*(.+?)\s*$", re.M)
PATH_RE = re.compile(r"[\w./-]+\.(?:py|sh|json|md|plist|yml|yaml|ts|js)\b")


def rca(issue: str, kind: str, why: str, pr: dict | None, slug: str, decide: str = "") -> tuple[str, str]:
    """(path, text) of a fresh RCA. Empty when Fable produced none."""
    argv = FABLE + ["--kind", "rca", "--issue", issue, "--site", kind, "--reason", why, "--json"]
    if decide:
        argv += ["--decide", decide]
    if pr:
        argv += ["--pr", str(pr["number"]), "--branch", pr["headRefName"], "--repo-args", f"-R {slug}"]
    rc, out = run(argv, timeout=600)
    try:
        path = (json.loads(out.splitlines()[-1]) if out else {}).get("rca_path") or ""
    except (ValueError, IndexError):
        path = ""
    try:
        return path, Path(path).read_text() if path else ""
    except OSError:
        return path, ""


def section(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.+)$", text or "", re.M)
    return m.group(1).strip() if m else ""


def check_blocker(arg: str, tgts: list) -> tuple[str, str]:
    """(kind, why_refused). kind is ticket, pr, founder or free; why is "" when valid.

    THE FOUNDER'S QUESTION IS THE RULE: "what happens if nothing changed? the
    ticket just stays?" A blocker nobody owns is a ticket that just stays, so it
    is refused HERE, when the decision is written, and the agent is asked again.
    """
    arg = arg.strip()
    if re.fullmatch(r"ASK-\d+", arg):
        t = ticket(arg)
        if not t:
            return "ticket", f"{arg} could not be read"
        if t.get("state_type") not in OPEN_TYPES:
            return "ticket", f"{arg} is already {t.get('state_type')}"
        if not owned_open(t):
            return "ticket", f"{arg} has no owner:* label, so nothing would ever close it"
        return "ticket", ""
    m = re.fullmatch(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", arg)
    if m:
        if m.group(1) not in {t["slug"] for t in tgts}:
            return "pr", f"{m.group(1)} is not a fleet repo, so pr-owner.py (ASK-3962) does not own it"
        rc, st = run(GH + ["pr", "view", m.group(2), "-R", m.group(1), "--json", "state", "--jq", ".state"])
        return "pr", "" if rc == 0 and st.strip() == "OPEN" else f"PR {arg} is not open"
    # FOUNDER-DECISION IS REFUSED UNTIL ITS CHANNEL SHIPS (ASK-4069). PR #662 spent
    # three review rounds on the founder-ask channel (status file, resolve, hold
    # release), and each fix caused the next round's major, so main split it out.
    # Accepted here with no writer and no reader, the hold would wait on an ask
    # nobody can see or resolve: the ticket that "just stays". So the agent is
    # asked again for SPLIT or CLOSE, the same path a free-text blocker takes.
    if re.match(r"\s*FOUNDER-DECISION\b", arg, re.I):
        return "founder", ("FOUNDER-DECISION is not accepted until ASK-4069 ships its channel; "
                           "pick SPLIT, CLOSE, or BLOCKED-ON an owned ticket or a fleet PR")
    return "free", f"'{arg[:80]}' is free text, not an owned ticket or a fleet PR"


def validated_decision(ask, parse, label: str, again_for: str, default, say_fn=None) -> dict | None:
    """THE ONE VALIDATED-DECISION LOOP. Ask, validate, ask once more, then default.

    Two callers: decide() below, and linear-route-decide.py (ASK-3959 stage 2),
    which loads this file for it. ONE LOOP ON PURPOSE: the brief for stage 2 said
    "do not write a second one", because two copies of "refuse, ask again, then
    default" drift, and the founder's rule they both carry ("what happens if
    nothing changed? the ticket just stays?") is the part that must not drift.

    ask(attempt, refused) -> (path, text). Attempt 1 is the open question,
      attempt 2 the narrowed one. An empty text on attempt 1 means no answer at
      all, and returns None: that is a failed call, never a decision.
    parse(text, attempt) -> (decision dict, "") when valid, else (None, why).
    default(path, text, refused) -> the decision two refusals land on.
    say_fn: the caller's own log line, so another job's log does not read "cap-ladder".
    """
    say_fn = say_fn or say
    path, text = ask(1, [])
    if not text:
        return None
    refused = []
    for attempt in (1, 2):
        d, no = parse(text, attempt)
        if d is not None:
            return {**d, "rca": path, "text": text, "refused": refused}
        refused.append(no)
        say_fn(f"{label}: decision refused ({no}); asking again for {again_for} only")
        if attempt == 1:
            path2, text2 = ask(2, refused)
            if text2:
                path, text = path2, text2
    return default(path, text, refused)


def decide(issue: str, kind: str, why: str, pr: dict | None, slug: str, tgts: list) -> dict | None:
    """One validated decision, or None when Fable answered nothing at all."""
    def ask(attempt: int, _refused: list) -> tuple[str, str]:
        return rca(issue, kind, why, pr, slug, decide="any" if attempt == 1 else "split-close")

    def parse(text: str, attempt: int) -> tuple[dict | None, str]:
        m = DECISION_RE.search(text)
        d = m.group(1) if m else ""
        if d in ("SPLIT", "CLOSE"):
            return {"kind": d}, ""
        if d == "BLOCKED-ON" and attempt == 2:
            return None, "BLOCKED-ON again, when only SPLIT or CLOSE was asked"
        if d == "BLOCKED-ON":
            bkind, no = check_blocker(m.group(2), tgts)
            if not no:
                return {"kind": d, "target": m.group(2).strip(), "target_kind": bkind}, ""
            return None, no
        return None, "no DECISION line"

    # Two invalid answers in a row: SPLIT on the RCA's own findings.
    return validated_decision(
        ask, parse, issue, "SPLIT or CLOSE",
        lambda path, text, refused: {"kind": "SPLIT", "rca": path, "text": text,
                                     "refused": refused, "defaulted": True})


def apply_decision(issue: str, d: dict, t: dict, pr: dict | None, slug: str, r: int, row: dict) -> str:
    branch = f"{LANE_PREFIX}{issue.lower()}"
    rca_ref = d.get("rca") or "none"
    if d["kind"] in ("SPLIT", "CLOSE") and pr:
        close_pr(slug, pr, f"Closed by {JOB}: {issue} {d['kind']} on cap ladder rung {r}. "
                           f"Branch {pr['headRefName']} is kept. RCA: {rca_ref}.")
    if d["kind"] == "SPLIT":
        subs = SUB_RE.findall(d.get("text") or "")
        if not subs:
            nxt = section(d.get("text", ""), "NEXT") or "Resume the work the parent's RCA names."
            subs = [(f"{t.get('title') or issue} (split after cap)", nxt)]
        made = []
        for title, outcome in subs[:5]:
            dor = (f"Split from {issue} by {JOB}, rung {r}. RCA: {rca_ref}.\n\n"
                   f"## Definition of Ready\n\n* **Outcome:** {outcome}\n"
                   f"* **Files:** start from branch {branch} and the RCA's NEXT section.\n"
                   f"* **Check:** {section(d.get('text', ''), 'REFUTE') or 'the parent RCA REFUTE line'}\n"
                   f"* **Not doing:** anything outside this outcome.\n")
            # needs-triage: an unattended filer marks its output (ASK-882,
            # linear-filer-label-lint.py). The DoR makes it workable anyway.
            ident = lin("create", parent=issue, title=title[:200], description=dor,
                        labels=["owner:sana", "needs-triage"])
            if ident:
                made.append(ident)
        if not made:
            return f"{issue}: SPLIT filed no sub-ticket; the cap stays and the next run retries"
        lin("state", issue=issue, type="completed")
        run(SYNC + ["progress", issue, f"**Split into {', '.join(made)}** by {JOB} after rung {r}. "
                    f"RCA: {rca_ref}." + (" (Defaulted to SPLIT after two refused decisions.)" if d.get("defaulted") else ""),
                    "--agent", "sana"])
        clear_caps(issue)
        return f"{issue}: SPLIT into {', '.join(made)}"
    if d["kind"] == "CLOSE":
        lin("state", issue=issue, type="canceled")
        run(SYNC + ["progress", issue, f"**Canceled by {JOB}** after rung {r}: wrong premise or obsolete "
                    f"work. Reason: RCA {rca_ref}. Reopen to undo.", "--agent", "sana"])
        clear_caps(issue)
        return f"{issue}: CLOSE (Canceled, RCA {rca_ref})"
    # BLOCKED-ON. The hold goes on FIRST: if it does not land, nothing is cleared,
    # so the cap record still keeps the worker off and the next run retries.
    if not ledger(["claim-flag", issue, HOLD_FLAG]):
        return f"{issue}: BLOCKED-ON could not set the hold; the cap stays and the next run retries"
    target = d["target"]
    if d["target_kind"] == "ticket":
        lin("relate", blocker=target, blocked=issue)
    if pr:
        close_pr(slug, pr, f"Closed by {JOB}: {issue} is BLOCKED-ON {target}. Branch "
                           f"{pr['headRefName']} is kept; the ladder reopens work from it when the blocker moves.")
    clear_caps(issue)
    row["snapshot"] = {"desc_hash": t.get("desc_hash"), "model_fp": model_fp(), "main_sha": main_sha(slug),
                       "files": sorted(set(branch_files(slug, branch)) | set(PATH_RE.findall(d.get("text") or "")))}
    row["held"] = True
    run(SYNC + ["progress", issue, f"**BLOCKED-ON {target}** (cap ladder rung {r}). Held by {JOB}: it "
                f"re-enters when the blocker closes, a file it touched or its RCA names changes on main, "
                f"its description changes, or the worker's model config changes. RCA: {rca_ref}.",
                "--agent", "sana"])
    return f"{issue}: BLOCKED-ON {target} (held)"


def event_for(issue: str, row: dict, t: dict, slug: str) -> str:
    """The event that releases a held ticket, or ""."""
    d, snap = row.get("decision") or {}, row.get("snapshot") or {}
    target = d.get("target", "")
    if d.get("target_kind") == "ticket":
        bt = ticket(target)
        if bt and bt.get("state_type") not in OPEN_TYPES:
            return f"(a) blocker {target} closed"
    elif d.get("target_kind") == "pr":
        m = re.fullmatch(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", target)
        if m:
            rc, st = run(GH + ["pr", "view", m.group(2), "-R", m.group(1), "--json", "state", "--jq", ".state"])
            if rc == 0 and st.strip() != "OPEN":
                return f"(a) blocker {target} closed"
    hit = sorted(set(changed_on_main(slug, snap.get("main_sha", ""))) & set(snap.get("files") or []))
    if hit:
        return f"(b) {hit[0]} changed on origin/main"
    if snap.get("desc_hash") and t.get("desc_hash") != snap["desc_hash"]:
        return "(c) its description changed"
    if snap.get("model_fp") and model_fp() != snap["model_fp"]:
        return "(d) the worker's model config changed"
    return ""


# --- rungs 1 to 3: a change, then continue --------------------------------------

def rung_name(r: int) -> str:
    return RUNG_NAMES.get(r, "decide")


def next_step_line(r: int) -> str:
    if r < 3:
        return f"If this caps again, {JOB} takes rung {r + 1} ({rung_name(r + 1)}) at its next nightly run."
    return (f"If this caps again, {JOB} takes rung 4: one recorded decision (SPLIT, CLOSE or BLOCKED-ON "
            "an owned blocker), never a timed retry.")


def climb(issue: str, sigs: list, t: dict, pr: dict | None, slug: str, state: dict,
          apply: bool, tgts: list, report: list) -> str:
    row = state.get(issue) or {}
    r = int(row.get("rung", 0)) + 1
    kind = sigs[0].split(":", 1)[0]
    why = f"{kind} cap ({', '.join(s.split(':', 1)[0] for s in sigs)})"
    if not apply:
        return f"[dry] {issue}: would take rung {r} ({rung_name(r)}) on its {why}"

    if r >= 4:
        d = decide(issue, kind, why, pr, slug, tgts)
        if d is None:
            report.append({"issue": issue, "rung": r, "decision": None, "red": True,
                           "note": "capped with no decision record: Fable produced no RCA; retried next run"})
            return f"{issue}: rung {r}: no decision record (RED in the report); the cap stays"
        out = apply_decision(issue, d, t, pr, slug, r, row)
        if "retries" in out:
            report.append({"issue": issue, "rung": r, "decision": d["kind"], "red": True, "note": out})
            return out
        row.update(rung=r, last_at=now().isoformat(), handled=sigs,
                   decision={k: v for k, v in d.items() if k != "text"})
        state[issue] = row
        return out

    rca_path, _ = rca(issue, kind, why, pr, slug)
    ledger(["claim-flag" if r == 2 else "clear-flag", issue, RUNNER_FLAG])
    if r == 3:
        run(SYNC + ["label", issue, "needs-scope"])
    # Continue: an OPEN PR on sana/<id> whenever that branch holds commits. A PR
    # that cannot be opened stops the rung before the clears, so the cap record
    # survives and the next run retries it.
    branch = f"{LANE_PREFIX}{issue.lower()}"
    body = (f"{issue}, cap ladder rung {r} ({rung_name(r)}). RCA: {rca_path or 'none produced'}. "
            f"Read the RCA comment on {issue} first: its STOP section names the approach that looped.")
    new_pr = ""
    if pr and pr["headRefName"].lower() == branch:
        if not close_pr(slug, pr, f"Closed by {JOB}, rung {r} ({rung_name(r)}). Branch {branch} is kept; "
                                  f"the work continues on a new PR from it. Reopen this PR to undo."):
            return f"{issue}: rung {r} could not close PR #{pr['number']}; the cap stays, the next run retries"
        ok, new_pr = open_from_branch(slug, branch, pr.get("title") or issue, f"Resumes #{pr['number']}. " + body)
        if not ok:
            return f"{issue}: rung {r} closed PR #{pr['number']} but could not open its successor; the next run retries"
    elif pr:
        say(f"{issue}: PR #{pr['number']} is on lane branch {pr['headRefName']}; pr-owner.py (ASK-3962) owns lane PRs")
    else:
        ok, new_pr = open_from_branch(slug, branch, t.get("title") or issue, body)
        if not ok:
            return f"{issue}: rung {r} could not open a PR from {branch}; the cap stays, the next run retries"
    clear_caps(issue)
    run(SYNC + ["requeue", issue, "--exit", f"cap-ladder-rung-{r}",
                "--why", f"{why}; rung {r} ({rung_name(r)}); RCA {rca_path or 'none'}", "--agent", "sana"])
    if r == 3:
        run(DRAFTER + ["--issue", issue, "--limit", "1", "--apply"], timeout=900)
    note = (f"**Cap ladder, rung {r} ({rung_name(r)}).** {issue} hit a {why}. RCA: {rca_path or 'none produced'}. "
            + (f"New PR {new_pr} on {branch}, which is kept. " if new_pr else "")
            + ("The next attempt runs on the other runner (Codex). " if r == 2 else "")
            + ("The Definition of Ready is rewritten by linear-dor-drafter.py in this run. " if r == 3 else "")
            + next_step_line(r))
    run(SYNC + ["progress", issue, note, "--agent", "sana"])
    # The state is written LAST: a run that dies above leaves the rung unspent.
    row.update(rung=r, last_at=now().isoformat(), handled=sigs)
    row["history"] = (row.get("history") or [])[-20:] + [{"rung": r, "at": now().isoformat(), "sigs": sigs,
                                                          "rca": rca_path, "new_pr": new_pr}]
    state[issue] = row
    return f"{issue}: rung {r} ({rung_name(r)}) taken on its {why}" + (f", new PR {new_pr}" if new_pr else "")


def release(issue: str, row: dict, t: dict, slug: str, ev: str, apply: bool) -> str:
    if not apply:
        return f"[dry] {issue}: would re-enter on {ev}"
    branch = f"{LANE_PREFIX}{issue.lower()}"
    ok, new_pr = open_from_branch(slug, branch, t.get("title") or issue,
                                  f"{issue} re-enters after its BLOCKED-ON hold: {ev}.")
    if not ok:
        return f"{issue}: {ev}, but no PR would open from {branch}; still held, the next run retries"
    ledger(["clear-flag", issue, HOLD_FLAG])
    run(SYNC + ["requeue", issue, "--exit", "cap-ladder-event", "--why", ev, "--agent", "sana"])
    run(SYNC + ["progress", issue, f"**Re-entered** by {JOB}: {ev}." + (f" New PR {new_pr} on {branch}." if new_pr else "")
                + " If it caps again, the ladder asks for a new decision.", "--agent", "sana"])
    row["held"] = False
    row["reentered_on"] = ev
    return f"{issue}: re-entered on {ev}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write; without it, print the plan")
    ap.add_argument("--limit", type=int, default=5, help="caps climbed per run (bounds RCA spend)")
    args = ap.parse_args(argv)
    # FIRST, before anything reads or writes a live path (PR #662 round 2, minor:
    # two verbs once ran above this check and wrote a real state file under pytest).
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("CAP_LADDER_STATE"):
        print("cap-ladder: REFUSED under pytest without CAP_LADDER_STATE (live data path)", file=sys.stderr)
        return 4

    tgts = targets()
    project_slug = {t["project"]: t["slug"] for t in tgts if t.get("project")}
    prs_by_issue, slug_by_pr = {}, {}
    for tg in tgts:
        for pr in open_prs(tg["slug"]):
            issue = issue_of_branch(pr.get("headRefName", ""))
            if issue and issue not in prs_by_issue:
                prs_by_issue[issue] = pr
                slug_by_pr[(issue, pr["number"])] = tg["slug"]

    caps = find_caps(read_ledger(), prs_by_issue, slug_by_pr)
    state = read_state()
    report: list = []
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
            sigs = sorted(caps[issue])
            row = state.get(issue) or {}
            # HANDLED IS A 20-HOUR MEMORY, NOT A FOREVER SKIP: a signature still
            # here a night later means a clear failed, and acting again recovers it.
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
                report.append({"issue": issue, "rung": row.get("rung", 0), "waiting_on": "routing (ASK-3959, ASK-3958)"})
                continue
            if live(issue, pr):
                say(f"{issue}: a run is live on it; the ladder looks again tomorrow")
                continue
            if done >= args.limit:
                say(f"{issue}: over the limit of {args.limit}; it climbs at the next run")
                report.append({"issue": issue, "rung": row.get("rung", 0), "waiting_on": "the next run (limit)"})
                continue
            out = climb(issue, sigs, t, pr, slug, state, args.apply, tgts, report)
            say(out)
            done += 1
        # THE HELD TICKETS: no event, no run, one line naming what it waits on.
        for issue, row in sorted(state.items()):
            if not row.get("held") or issue in caps:
                continue
            t = ticket(issue)
            if t is None:
                continue
            if t.get("state_type") in ("completed", "canceled", "duplicate"):
                state.pop(issue, None)
                continue
            d = row.get("decision") or {}
            slug = project_slug.get(t.get("project", "")) or (tgts[0]["slug"] if tgts else "")
            # UNREADABLE IS NOT OWNERLESS (PR #662 round 4, minor). ticket() is None on a
            # failed read and owned_open(None) is False, so the row went red as "lost its
            # owner" and named linear-owner-sweep.py for a fault it cannot fix. A failed
            # read is read again at the next run, like every other read here.
            bt = ticket(d.get("target", "")) if d.get("target_kind") == "ticket" else None
            red = bt is not None and not owned_open(bt)
            ev = event_for(issue, row, t, slug)
            if ev:
                say(release(issue, row, t, slug, ev, args.apply))
                continue
            wait = (f"held on {d.get('target')}: waiting for it to close, a touched file to change on main, "
                    "its description to change, or the model config to change")
            say(f"{issue}: {wait}" + ("; RED: the blocker has no owner" if red else ""))
            report.append({"issue": issue, "rung": row.get("rung"), "decision": "BLOCKED-ON",
                           "waiting_on": wait, "red": red,
                           "note": "the blocker lost its owner, so it is a dead end" if red else ""})
        blockers: dict = {}
        for row in state.values():
            d = row.get("decision") or {}
            if row.get("held") and d.get("target_kind") == "ticket":
                blockers[d["target"]] = blockers.get(d["target"], 0) + 1
        if args.apply:
            write_state(state)
            write_json(BLOCKERS, blockers)
            write_json(REPORT, {"at": now().isoformat(), "rows": report})
    say(f"run complete: {len(caps)} capped, {done} climbed, "
        f"{sum(1 for r in state.values() if r.get('held'))} held{'' if args.apply else ' (dry)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
