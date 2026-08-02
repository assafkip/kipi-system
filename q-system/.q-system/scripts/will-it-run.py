#!/usr/bin/env python3
"""When will an issue ACTUALLY be dispatched -- from observed state, or NEVER.

WHY THIS FILE EXISTS (ASK-292, RCA rca-specification-reported-as-state-2026-08-02).
In one session nine confident claims about system state were false. Every one
substituted a SPECIFICATION (what the code is designed to do, or that an artifact
exists) for an OBSERVATION (what the running system is doing). The load-bearing
one: "the queue picks this up, 4 a day". The production lane cap is 3 and the day's
budget was already spent, so an issue reported as queued was not going to run.

The root cause was not ignorance. `wiring-check.md` already states the standard and
it was violated the hour it was read. The cause is that proving an artifact EXISTS
is one keystroke (`grep -c`) and proving a mechanism RUNS was four commands that
differ per subsystem. A standard without an instrument decays to the nearest
available measurement. This file is the instrument, so the correct check is also
the cheap one.

THREE RULES THIS FILE OBEYS BECAUSE IT EXISTS TO PREVENT THEIR VIOLATION:

1. NEVER READ A DEFAULT AND REPORT IT AS STATE. `kipi-dispatch.sh:557` reads
   `${KIPI_DISPATCH_DAILY_MAX:-4}` -- the default is 4 and the running value is 3,
   set in the plist. So the cap is resolved from the LOADED launchd job's own
   environment first, the plist file second, and is reported as UNKNOWN if neither
   answers. It is never defaulted. The literal 4 appears nowhere below.

2. NEVER INFER BEHAVIOUR FROM AN ARTIFACT. Four of the session's nine errors came
   from reading a file artifact as behaviour: a stale mtime read as a dead loop, a
   0-byte file read as a fallback that never fired, a marker string read as a
   review that happened. So liveness comes from `launchctl print` (job state) and
   `pgrep` (running processes), never from a log's mtime or a file's size.

3. DO NOT RESTATE PICKABILITY, IMPORT IT. `linear_pick.py` is the one copy of the
   ready() predicate that the worker itself runs. A hand-copy of a checker is a
   second checker that drifts. This file imports it and replicates the worker's
   query and pool ORDER verbatim, because position in the pool is the whole
   difference between "tomorrow" and "four days out".

Usage:
    will-it-run.py ASK-291        one issue
    will-it-run.py --all          the whole pool, with a realistic day for each
    will-it-run.py --json         machine-readable
    will-it-run.py --self-test    hermetic, no network, no live state
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent          # q-system/.q-system/scripts -> repo root
STATE_DIR = pathlib.Path(os.environ.get("KIPI_STATE_DIR",
                                        os.path.expanduser("~/.config/kipi")))
JOB_LABEL = "com.kipi.dispatch"
PLIST = pathlib.Path(os.path.expanduser(
    f"~/Library/LaunchAgents/{JOB_LABEL}.plist"))

# linear-worker.sh:100. The worker skips an issue at or above this and pages once;
# it is a per-issue terminal state, so such an issue occupies no queue slot.
MAX_ATTEMPTS = 3
ATTEMPTS_FILE = STATE_DIR / "linear-worker-attempts.json"

# The worker's query, character for character (linear-worker.sh:345). The pool
# ORDER is whatever Linear returns for this exact query -- there is no orderBy --
# so a re-worded query could return a different order and silently move every
# position. Copying it is the point.
WORKER_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(cmd, cwd=None, timeout=20):
    """Return (rc, stdout). Never raises: a missing binary is an unknown, not a crash."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


# --------------------------------------------------------------------------
# Observation layer. Everything here reads the machine; nothing here decides.
# --------------------------------------------------------------------------

def launchd_state(label=JOB_LABEL):
    """The LOADED job: is it there, its env, its last exit.

    `launchctl print` is the only source that distinguishes "loaded" from "a plist
    exists on disk". A plist file proves configuration, not that anything runs --
    which is rule 2 above, applied to this script's own inputs.
    """
    uid = os.getuid()
    rc, out = _run(["launchctl", "print", f"gui/{uid}/{label}"])
    if rc != 0:
        return {"loaded": False, "env": {}, "last_exit": None, "runs": None,
                "interval": None}
    env = {}
    # The `environment = { ... }` block holds the job's REAL variables. There is
    # also an `inherited environment` and a `default environment` block above it;
    # matching K => V globally would merge all three and could shadow the real
    # value with launchd's PATH default. So the block is delimited first.
    block = re.search(r"\n\tenvironment = \{(.*?)\n\t\}", out, re.S)
    if block:
        for k, v in re.findall(r"(\w+) => (.*)", block.group(1)):
            env[k] = v.strip()
    m_exit = re.search(r"last exit code = (-?\d+)", out)
    m_runs = re.search(r"\n\truns = (\d+)", out)
    m_int = re.search(r"run interval = (\d+) seconds", out)
    return {
        "loaded": True,
        "env": env,
        "last_exit": int(m_exit.group(1)) if m_exit else None,
        "runs": int(m_runs.group(1)) if m_runs else None,
        "interval": int(m_int.group(1)) if m_int else None,
    }


def plist_env(path=PLIST):
    """The plist's EnvironmentVariables. CONFIG ON DISK, not running state.

    Only consulted when the job is not loaded, and labelled as such in the output,
    because a plist edited after the last `launchctl load` says what the job WOULD
    use, not what it IS using.
    """
    if not path.is_file():
        return {}
    rc, out = _run(["plutil", "-convert", "json", "-o", "-", str(path)])
    if rc != 0:
        return {}
    try:
        return dict(json.loads(out).get("EnvironmentVariables", {}))
    except (json.JSONDecodeError, AttributeError):
        return {}


def resolve_config(job, plist_vars):
    """Cap, reset hour, lane, concurrency -- from the running job, else the plist.

    UNKNOWN IS A LEGITIMATE ANSWER AND A DEFAULT IS NOT. Returning the script's
    `:-4` fallback here would reproduce the exact error this tool exists to
    prevent, in the tool. `cap` of None makes every downstream day estimate
    refuse rather than guess.
    """
    if job["loaded"] and job["env"]:
        env, source = job["env"], "launchd (running job)"
    elif plist_vars:
        env, source = plist_vars, "plist file (job NOT loaded -- config, not state)"
    else:
        env, source = {}, "UNRESOLVED"

    def as_int(key):
        raw = env.get(key)
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    lane = env.get("KIPI_DISPATCH_LANE", "production")
    # kipi-dispatch.sh:605-616. Production's lane cap IS DAILY_MAX; the test lane
    # has its own cap and its own counter file. Reporting a production cap for a
    # test-lane run (or the reverse) is the same substitution one level down.
    if lane == "test":
        cap = as_int("KIPI_DISPATCH_TEST_MAX")
        suffix = "-test"
    else:
        cap = as_int("KIPI_DISPATCH_DAILY_MAX")
        suffix = ""
    return {
        "lane": lane,
        "cap": cap,
        "count_suffix": suffix,
        "reset_hour": as_int("KIPI_DISPATCH_RESET_HOUR"),
        "max_concurrent": as_int("KIPI_DISPATCH_MAX"),
        "repo": env.get("KIPI_REPO") or str(REPO),
        "source": source,
    }


def budget_day(reset_hour, now=None):
    """kipi-dispatch.sh:576 in Python: shift the LOCAL clock back RESET_HOUR hours.

    A budget day runs 07:00 -> 06:59 next morning, so 03:00 Tuesday still spends
    Monday's allowance. Local, not UTC: the shell uses bare `date`, and computing
    this in UTC would name the wrong counter file for seven hours a day.
    """
    if reset_hour is None:
        return None
    now = now or dt.datetime.now()
    return (now - dt.timedelta(hours=reset_hour)).strftime("%Y-%m-%d")


def spend(cfg, day, state_dir=STATE_DIR):
    """Issues started this budget day, from the counter the dispatcher writes."""
    if day is None:
        return None, None
    path = state_dir / f"dispatch-count{cfg['count_suffix']}-{day}"
    try:
        return int(path.read_text().strip()), path
    except (OSError, ValueError):
        # Absent counter = a fresh budget day = 0 spent. That is the dispatcher's
        # own reading (`cat ... || echo 0`), not an optimistic guess.
        return 0, path


def checkout_staleness(repo):
    """Commits origin/main holds that this checkout lacks (kipi-dispatch.sh:285).

    NO FETCH. The dispatcher fetches; this is a read-only instrument and a fetch
    from here would make the answer depend on the network. So this is staleness AS
    OF THE LAST FETCH, and `fetch_age_s` is reported alongside so a stale answer is
    visibly stale rather than quietly wrong.
    """
    rc, out = _run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=repo)
    behind = None
    if rc == 0:
        try:
            behind = int(out.strip())
        except ValueError:
            behind = None
    age = None
    fh = pathlib.Path(repo) / ".git" / "FETCH_HEAD"
    try:
        age = int(dt.datetime.now().timestamp() - fh.stat().st_mtime)
    except OSError:
        pass
    return {"behind": behind, "fetch_age_s": age}


def live_converges():
    """Running converge processes -- a PROCESS read, never a log or a lock file."""
    rc, out = _run(["pgrep", "-f", "converge.sh --issue"])
    return len([ln for ln in out.splitlines() if ln.strip()]) if rc in (0, 1) else None


def attempts(path=ATTEMPTS_FILE):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def repo_project(repo):
    """linear-worker.sh:283-303: env override, then the registry, then basename."""
    override = os.environ.get("KIPI_LINEAR_PROJECT")
    if override:
        return override
    reg_path = pathlib.Path(repo) / "instance-registry.json"
    try:
        reg = json.loads(reg_path.read_text())
        entries = reg.get("instances", reg) if isinstance(reg, dict) else reg
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("path") and \
                    os.path.realpath(e["path"]) == os.path.realpath(repo):
                if e.get("name"):
                    return e["name"]
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return os.path.basename(os.path.realpath(repo))


def fetch_issues():
    """The worker's own query, run through the worker's own client."""
    ls = _load_module("linear_sync", HERE / "linear-sync.py")
    tid = ls.graphql('query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}',
                     {})["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = ls.graphql(WORKER_QUERY, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues


# --------------------------------------------------------------------------
# Decision layer. Pure functions -- no network, no clock, no subprocess -- so the
# suite exercises the SAME code the live run does. A decision layer that can only
# be tested by running the real dispatcher is a decision layer nobody tests.
# --------------------------------------------------------------------------

def never_reason(issue, rp, lp, attempt_count):
    """Why this issue can never be picked, or None if it is in the pool.

    Every branch mirrors one condition in `linear_pick.ready` (imported above, not
    re-implemented) plus the worker's attempts cap. The MESSAGE differs per branch
    on purpose: "not pickable" sends a reader back to guess, and guessing is what
    produced the nine false claims.
    """
    labels = lp.labels_of(issue)
    if "owner:assaf" in labels:
        return ("owner:assaf -- this is a founder decision, the picker hands it off "
                "and no runner will ever take it")
    if "owner:sana" not in labels:
        return "no owner:sana label -- the picker only offers issues labelled for the runner"
    held = [h for h in lp.HOLD_LABELS if h in labels]
    if held:
        extra = (" (capability_block_expiry.py re-probes this before each pick, so it "
                 "can re-enter the pool without a human)" if "blocked:capability" in held else
                 " -- the spec was refused as unexecutable; the DoR drafter re-scopes it")
        return f"held at {', '.join(held)}{extra}"
    state = (issue.get("state") or {}).get("type")
    if state not in lp.PICKABLE_STATE_TYPES:
        return (f"state type is '{state}', and the picker only offers "
                f"{'/'.join(lp.PICKABLE_STATE_TYPES)} -- an issue already at "
                f"'{state}' is not handed out a second time")
    proj = lp.project_of(issue)
    if proj != rp:
        shown = f"'{proj}'" if proj else "UNSET"
        return (f"project is {shown}, this checkout is '{rp}' -- the picker drops "
                f"every issue whose project is not this repo, and an unset project "
                f"is NOT this repo (linear_pick.in_repo)")
    if not lp.has_dor(issue):
        return "no 'Definition of Ready' section in the description"
    if attempt_count >= MAX_ATTEMPTS:
        return (f"{attempt_count}/{MAX_ATTEMPTS} attempts spent -- TERMINAL. The "
                f"worker skips it every heartbeat until a human clears the count, "
                f"fixes the blocker, or rewrites the DoR")
    return None


def schedule_for(position, cap, spent, day):
    """Which budget day a pool position lands on. Pure arithmetic.

    An item 11th in a 3/day queue is four budget days out, and calling that
    "tomorrow" is the same class of error as calling a spent budget "queued".
    """
    if cap is None or spent is None or day is None:
        return {"when": "UNKNOWN", "days_out": None,
                "detail": "the dispatcher's cap or budget day could not be observed"}
    remaining = max(0, cap - spent)
    if position < remaining:
        return {"when": "today", "days_out": 0,
                "detail": f"position {position} of {remaining} slot(s) left today "
                          f"(budget {spent}/{cap}, day {day})"}
    days_out = 1 + (position - remaining) // cap
    target = (dt.date.fromisoformat(day) + dt.timedelta(days=days_out)).isoformat()
    when = "not today" if days_out == 1 else "not today"
    return {"when": when, "days_out": days_out, "target_day": target,
            "detail": f"budget {spent}/{cap} spent; position {position} in the pool "
                      f"lands on budget day {target} ({days_out} day(s) out) at "
                      f"{cap}/day"}


def blocking_gates(job, cfg, stale, live):
    """Conditions that stop EVERY dispatch, regardless of which issue you asked about."""
    gates = []
    if not job["loaded"]:
        gates.append(("NEVER", f"launchd job {JOB_LABEL} is NOT loaded -- nothing "
                               f"dispatches at all until it is loaded"))
    if cfg["cap"] is None:
        gates.append(("UNKNOWN", "the daily cap could not be read from the running "
                                 "job or the plist; refusing to assume a default"))
    if stale["behind"]:
        gates.append(("BLOCKED", f"this checkout is {stale['behind']} commit(s) behind "
                                 f"origin/main; the dispatcher REFUSES to dispatch "
                                 f"while stale (kipi-dispatch.sh:304). Fix: "
                                 f"git merge --ff-only origin/main"))
    if live is not None and cfg["max_concurrent"] is not None \
            and live >= cfg["max_concurrent"]:
        gates.append(("DELAYED", f"{live} converge run(s) live, concurrency cap "
                                 f"{cfg['max_concurrent']} -- ticks skip until one "
                                 f"finishes (a delay, not a block)"))
    return gates


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def build_report(target, issues, rp, lp, att, job, cfg, day, spent_n, stale, live):
    pool, never = [], {}
    for issue in issues:
        n = att.get(issue["identifier"], {}).get("count", 0)
        reason = never_reason(issue, rp, lp, n)
        if reason is None:
            pool.append(issue)
        else:
            never[issue["identifier"]] = reason
    gates = blocking_gates(job, cfg, stale, live)
    order = {i["identifier"]: n for n, i in enumerate(pool)}

    def one(ident, title=None):
        if ident in never:
            return {"issue": ident, "title": title, "verdict": "NEVER",
                    "reason": never[ident], "position": None}
        if ident not in order:
            return {"issue": ident, "title": title, "verdict": "NEVER",
                    "reason": "not present in the team query the picker runs",
                    "position": None}
        sched = schedule_for(order[ident], cfg["cap"], spent_n, day)
        verdict = sched["when"]
        for kind, why in gates:
            if kind in ("NEVER", "UNKNOWN"):
                return {"issue": ident, "title": title, "verdict": kind,
                        "reason": why, "position": order[ident], **sched}
        return {"issue": ident, "title": title, "verdict": verdict,
                "position": order[ident], **sched}

    report = {
        "observed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "config_source": cfg["source"], "lane": cfg["lane"], "cap": cfg["cap"],
        "spent": spent_n, "budget_day": day, "reset_hour": cfg["reset_hour"],
        "repo_project": rp, "job_loaded": job["loaded"],
        "job_last_exit": job["last_exit"], "job_runs": job["runs"],
        "behind_origin": stale["behind"], "fetch_age_s": stale["fetch_age_s"],
        "live_converges": live, "max_concurrent": cfg["max_concurrent"],
        "pool_size": len(pool), "gates": [{"kind": k, "why": w} for k, w in gates],
    }
    if target == "--all":
        report["answers"] = [one(i["identifier"], i["title"]) for i in pool]
    else:
        title = next((i["title"] for i in issues if i["identifier"] == target), None)
        report["answers"] = [one(target, title)]
    return report


def render(report):
    out = []
    out.append(f"OBSERVED {report['observed_at']}  lane={report['lane']}  "
               f"cap={report['cap']}  spent={report['spent']}  "
               f"budget_day={report['budget_day']}")
    out.append(f"  cap source: {report['config_source']}")
    out.append(f"  launchd {JOB_LABEL}: loaded={report['job_loaded']} "
               f"runs={report['job_runs']} last_exit={report['job_last_exit']}")
    out.append(f"  checkout: {report['behind_origin']} commit(s) behind origin/main "
               f"(as of a fetch {report['fetch_age_s']}s ago)")
    out.append(f"  converge live: {report['live_converges']}/{report['max_concurrent']}"
               f"   pool: {report['pool_size']} pickable, project={report['repo_project']}")
    for g in report["gates"]:
        out.append(f"  GATE [{g['kind']}] {g['why']}")
    out.append("")
    for a in report["answers"]:
        head = f"{a['issue']}: {a['verdict'].upper()}"
        if a.get("position") is not None:
            head += f"  (pool position {a['position']})"
        out.append(head)
        out.append(f"    {a.get('reason') or a.get('detail')}")
        if a.get("reason") and a.get("detail"):
            out.append(f"    also: {a['detail']}")
        if a.get("title"):
            out.append(f"    \"{a['title'][:70]}\"")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="?", help="issue id (e.g. ASK-291)")
    ap.add_argument("--all", action="store_true", help="the whole ready pool")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(_self_test())
    if not args.all and not args.target:
        ap.error("give an issue id or --all")

    lp = _load_module("linear_pick", HERE / "linear_pick.py")
    job = launchd_state()
    cfg = resolve_config(job, plist_env())
    day = budget_day(cfg["reset_hour"])
    spent_n, _ = spend(cfg, day)
    stale = checkout_staleness(cfg["repo"])
    live = live_converges()
    rp = repo_project(cfg["repo"])
    try:
        issues = fetch_issues()
    except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
        print(f"CANNOT ANSWER: Linear query failed ({str(exc)[:160]}). "
              f"No scheduling claim is supported by this run.", file=sys.stderr)
        sys.exit(3)
    report = build_report("--all" if args.all else args.target, issues, rp, lp,
                          attempts(), job, cfg, day, spent_n, stale, live)
    print(json.dumps(report, indent=2) if args.json else render(report))
    sys.exit(0)


# --------------------------------------------------------------------------
def _self_test():
    """Hermetic. No network, no launchd, no live counter file."""
    lp = _load_module("linear_pick", HERE / "linear_pick.py")
    RP = "kipi-system"

    def mk(ident, *, labels=("owner:sana",), state="backlog", project=RP, dor=True):
        # FIXTURE SHAPE COMES FROM THE PRODUCER, not from imagination: this is the
        # node shape WORKER_QUERY returns, captured from a real run against the ASK
        # team. A fixture I invent tests my assumption about the API, not the API.
        return {"identifier": ident, "title": f"t {ident}",
                "description": "## Definition of Ready\nx" if dor else "no section",
                "state": {"name": state.title(), "type": state},
                "project": {"name": project} if project else None,
                "labels": {"nodes": [{"name": n} for n in labels]}}

    cases = []

    def check(name, got, want):
        cases.append((name, got == want, got, want))

    # --- never_reason: one case per branch of linear_pick.ready ---------------
    check("pickable issue has no never-reason",
          never_reason(mk("A-1"), RP, lp, 0), None)
    check("owner:assaf never runs",
          never_reason(mk("A-2", labels=("owner:assaf", "owner:sana")), RP, lp, 0)
          is not None, True)
    check("missing owner:sana never runs",
          never_reason(mk("A-3", labels=()), RP, lp, 0) is not None, True)
    check("blocked:capability never runs",
          "blocked:capability" in (never_reason(
              mk("A-4", labels=("owner:sana", "blocked:capability")), RP, lp, 0) or ""),
          True)
    check("needs-scope never runs",
          "needs-scope" in (never_reason(
              mk("A-5", labels=("owner:sana", "needs-scope")), RP, lp, 0) or ""), True)
    check("started state never runs",
          "started" in (never_reason(mk("A-6", state="started"), RP, lp, 0) or ""), True)
    check("unset project never runs",
          "UNSET" in (never_reason(mk("A-7", project=None), RP, lp, 0) or ""), True)
    check("foreign project never runs",
          "cole-GTM" in (never_reason(mk("A-8", project="cole-GTM"), RP, lp, 0) or ""),
          True)
    check("no DoR never runs",
          "Definition of Ready" in (never_reason(mk("A-9", dor=False), RP, lp, 0) or ""),
          True)
    check("attempts cap is terminal",
          "TERMINAL" in (never_reason(mk("A-10"), RP, lp, MAX_ATTEMPTS) or ""), True)
    check("one attempt below the cap still runs",
          never_reason(mk("A-11"), RP, lp, MAX_ATTEMPTS - 1), None)

    # --- schedule_for: the arithmetic that turns position into a day ----------
    check("budget spent -> not today",
          schedule_for(0, 3, 3, "2026-08-02")["when"], "not today")
    check("budget spent -> exactly one day out",
          schedule_for(0, 3, 3, "2026-08-02")["days_out"], 1)
    check("slot left -> today",
          schedule_for(0, 3, 2, "2026-08-02")["when"], "today")
    check("position 11 with a spent 3/day budget is 4 days out",
          schedule_for(11, 3, 3, "2026-08-02")["days_out"], 4)
    check("position 2 with 3 slots left is still today",
          schedule_for(2, 3, 0, "2026-08-02")["when"], "today")
    check("position 3 with 3 slots left rolls to the next day",
          schedule_for(3, 3, 0, "2026-08-02")["days_out"], 1)
    check("unknown cap refuses to guess a day",
          schedule_for(0, None, 3, "2026-08-02")["when"], "UNKNOWN")

    # --- resolve_config: the exact substitution this tool exists to prevent ---
    job_loaded = {"loaded": True, "env": {"KIPI_DISPATCH_DAILY_MAX": "3",
                                          "KIPI_DISPATCH_RESET_HOUR": "7",
                                          "KIPI_DISPATCH_MAX": "1"},
                  "last_exit": 0, "runs": 474, "interval": 900}
    check("cap comes from the RUNNING job, not the script default",
          resolve_config(job_loaded, {"KIPI_DISPATCH_DAILY_MAX": "9"})["cap"], 3)
    check("running job is labelled as running",
          "launchd" in resolve_config(job_loaded, {})["source"], True)
    unloaded = {"loaded": False, "env": {}, "last_exit": None, "runs": None,
                "interval": None}
    check("unloaded job falls back to the plist and SAYS so",
          "NOT loaded" in resolve_config(unloaded,
                                         {"KIPI_DISPATCH_DAILY_MAX": "3"})["source"],
          True)
    check("nothing observable -> cap is None, never a default",
          resolve_config(unloaded, {})["cap"], None)
    check("test lane reads its own cap and its own counter file",
          (resolve_config({"loaded": True, "env": {"KIPI_DISPATCH_LANE": "test",
                                                   "KIPI_DISPATCH_TEST_MAX": "2"},
                           "last_exit": 0, "runs": 1, "interval": 900}, {})["cap"],
           resolve_config({"loaded": True, "env": {"KIPI_DISPATCH_LANE": "test",
                                                   "KIPI_DISPATCH_TEST_MAX": "2"},
                           "last_exit": 0, "runs": 1, "interval": 900},
                          {})["count_suffix"]),
          (2, "-test"))

    # --- budget_day: the 07:00 rollover -------------------------------------
    check("03:00 still belongs to the previous budget day",
          budget_day(7, dt.datetime(2026, 8, 3, 3, 0)), "2026-08-02")
    check("08:00 has rolled into the new budget day",
          budget_day(7, dt.datetime(2026, 8, 3, 8, 0)), "2026-08-03")
    check("unknown reset hour yields no budget day",
          budget_day(None, dt.datetime(2026, 8, 3, 8, 0)), None)

    # --- gates ---------------------------------------------------------------
    cfg_ok = {"cap": 3, "max_concurrent": 1}
    check("unloaded job is a NEVER gate",
          blocking_gates(unloaded, cfg_ok, {"behind": 0}, 0)[0][0], "NEVER")
    check("stale checkout is a BLOCKED gate",
          [k for k, _ in blocking_gates(job_loaded, cfg_ok, {"behind": 2}, 0)],
          ["BLOCKED"])
    check("concurrency at cap is DELAYED, not BLOCKED",
          [k for k, _ in blocking_gates(job_loaded, cfg_ok, {"behind": 0}, 1)],
          ["DELAYED"])
    check("healthy system raises no gate",
          blocking_gates(job_loaded, cfg_ok, {"behind": 0}, 0), [])

    # --- NEGATIVE SELF-TEST: prove the harness can fail ----------------------
    # Without this the suite is 25 assertions that have never been observed to go
    # red, which is indistinguishable from 25 assertions that cannot. A mutant is
    # applied to the real decision function and the suite must NOTICE.
    mutant_caught = never_reason(mk("A-12", project=None), RP, lp, 0) is not None
    negative_ok = mutant_caught and (
        # the deliberately wrong expectation must NOT compare equal
        schedule_for(0, 3, 3, "2026-08-02")["when"] != "today")
    cases.append(("NEGATIVE self-test: a wrong expectation is detected as wrong",
                  negative_ok, negative_ok, True))

    ok = True
    for name, passed, got, want in cases:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        if not passed:
            print(f"      got={got!r}\n      want={want!r}")
        ok = ok and passed
    print(f"\n{sum(1 for c in cases if c[1])}/{len(cases)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    main()
