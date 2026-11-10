#!/usr/bin/env python3
"""wait-has-consumer.py: name what will do the work a hold waits on (ASK-4306).

Rule-ID: RULE-2026-11-09-B
Founder, 2026-11-09: "No agent can be waiting on things that are never gonna get
done... It should be fixed in code."

  wait-has-consumer.py ASK-4195              # a ticket
  wait-has-consumer.py assafkip/kipi-system#701   # or  kipi-system#701 : a PR

Prints the named consumer and exits 0, or prints "nothing picks this up: <why>"
and exits 1. Exit 2 means the check could not look (Linear or GitHub did not
answer): that is neither a consumer nor proof of none, so a caller refuses on it.
Exit 64 is a bad argument. lane-mark.py hold calls consumer_for() in-process;
wait-guard.sh wraps the CLI for shell watchers (`--waiter ASK-n` names the waiting lane).

SCAR. 2026-11-09: ASK-3834's lane held V8 on ASK-4195 and V6 on ASK-4277. Both are
spillover tickets filed through the fleet-alert path, which linear-worker.sh
is_fleet_alert() skips, so no worker would ever pick them; the nightly triage
promotes 60 a night against 1,094 queued. The lane waited on work nothing would do.
test_no_handoff_to_nobody.py checks a message's wording and never a real wait.

FOUR CONSUMERS (a nightly queue counts only while the ticket is within its cap, so it acts inside 24h), EACH READ FROM THE CODE THAT ACTS, NEVER A COPY OF ITS RULE.
  * An open PR with an owner: pr-owner.py is imported, and its own repo set
    (fleet_repos), kill switch, archive guard and head-provenance test are asked.
    A PR in a repo pr-owner does not sweep, or a fork PR, has no owner.
  * A ticket the worker would pick: ready() is CUT OUT OF linear-worker.sh by AST
    (worker_rule) and run on the ticket, the way tests/test_hold_label_consumers.py
    cuts the same function for its census. A retyped ready() agrees on the day it
    is written and then drifts; this one cannot, and it fails loudly (CannotLook)
    if the worker's text changes shape instead of falling back to a private rule.
  * A ticket In Progress with a live lane-mark.py marker or a live worker claim:
    linear-sync.py lane_marker() and live_claim(), the same two the worker reads.
  * A nightly queue: linear-dor-drafter.py (no-DoR, needs-scope) and linear-alert-triage.py
    (alert tickets), only while the ticket's place in the job's own queue is under the
    --limit read from its plist. Beyond the cap: "queued behind N", a wait on nobody.
A started ticket with neither is judged by ready() too, because started_open
releases a ticket abandoned past the lane window back to the worker.
"""
import ast
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
TICKET_RX = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
PR_RX = re.compile(r"^(?:(?P<owner>[\w.-]+)/)?(?P<repo>[\w.-]+)#(?P<n>\d+)$")

NO_ONE = "nothing picks this up: "

ISSUE_Q = """query($id: String!) { issue(id: $id) {
  id identifier title description state { name type } startedAt project { name }
  labels { nodes { name } } } }"""

# What ready() needs from the worker's heredoc besides itself. Named, so a rename
# in the worker fails the cut rather than leaving ready() with a missing global.
_WORKER_FUNCS = ("project_of", "is_fleet_alert", "in_this_repo", "started_hold", "started_open", "ready")
_WORKER_ASSIGNS = ("ALERT_MARKER", "QUEUE_STATES", "STARTED_WHY", "_started_memo")


class CannotLook(Exception):
    """A source did not answer. Not the same claim as "there is no consumer"."""


_MODS = {}


def _load(key, filename, modname):
    if key not in _MODS:
        spec = importlib.util.spec_from_file_location(modname, SCRIPTS / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        _MODS[key] = mod
    return _MODS[key]


def linear_sync():
    return _load("ls", "linear-sync.py", "linear_sync_for_wait")


def pr_owner():
    return _load("po", "pr-owner.py", "pr_owner_for_wait")


def state_dir() -> str:
    return os.environ.get("KIPI_STATE_DIR") or os.path.expanduser("~/.config/kipi")


def local_projects() -> set:
    """Board projects the DISPATCHER enters: where a worker can actually run.

    SCAR (PR #712 review, round 1): the first cut returned every registry row with a
    checkout, 14 projects, while the dispatcher's own set (fleet_candidates() in
    kipi-dispatch.sh, which requires dispatch.enabled) held 3. A hold on a ticket in
    Alice read "the worker would pick it" and nothing ever entered that checkout.
    So the set is pr-owner.py's fleet_repos(), which cuts fleet_candidates out of
    the dispatcher and runs it, minus any checkout with a .kipi-no-dispatch kill
    switch (repo-preflight.sh), joined to the board project by checkout path.
    """
    po = pr_owner()
    try:
        rows, targets = po.fleet_repos(po.ROOT)
    except SystemExit as exc:
        raise CannotLook(str(exc.code)[:160])
    lr = _load("lr", "linear_registry.py", "linear_registry_for_wait")
    facts = lr.registry_facts(lr.default_registry_path(), None, os.environ.get("KIPI_DISPATCH_TARGETS") or targets or None)
    if not facts.get("ok"):
        raise CannotLook("instance-registry.json could not be read, so which projects a worker covers is unknown")
    by_path = {os.path.realpath(r["path"]): r["project"] for r in facts.get("local_repos") or [] if r.get("project")}
    out = set()
    for _name, path, _remote in rows:
        if Path(path, ".kipi-no-dispatch").exists():
            continue
        proj = by_path.get(os.path.realpath(path))
        # The home row is the checkout running this (a worktree has a different
        # path from the registry row), and the registry names its project.
        if not proj and os.path.realpath(path) == os.path.realpath(po.ROOT):
            proj = facts.get("skeleton_project")
        if proj:
            out.add(proj)
    return out


def worker_rule(worker_text=None):
    """The ast.Module holding linear-worker.sh's ready() and what it needs, cut out by AST.

    Raises CannotLook when the worker's text no longer has the shape this cut
    needs. There is no fallback rule: a private copy is what this exists to avoid.
    """
    if worker_text is None:
        worker_text = (SCRIPTS / "linear-worker.sh").read_text()
    blocks = [b for b in re.findall(r"<<'PY'\n(.*?)\nPY\n", worker_text, flags=re.S) if "\ndef ready(" in b]
    if len(blocks) != 1:
        raise CannotLook(f"linear-worker.sh: expected one heredoc defining ready(), found {len(blocks)}")
    tree = ast.parse(blocks[0])
    keep, seen = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WORKER_FUNCS:
            keep.append(node)
            seen.add(node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name) and node.targets[0].id in _WORKER_ASSIGNS):
            keep.append(node)
            seen.add(node.targets[0].id)
    missing = (set(_WORKER_FUNCS) | set(_WORKER_ASSIGNS)) - seen
    if missing:
        raise CannotLook(f"linear-worker.sh no longer defines {sorted(missing)}, so its ready() cannot be cut out")
    module = ast.Module(body=keep, type_ignores=[])
    return module


def _worker_ready(issue: dict, project: str) -> tuple:
    """(ready, ns): linear-worker.sh's own ready() run on this ticket."""
    ls = linear_sync()
    ns = {"ls": ls, "now": datetime.now(timezone.utc), "state_dir": state_dir(), "repo_project": project}
    exec(compile(worker_rule(), "linear-worker.sh:ready", "exec"), ns)
    try:
        return bool(ns["ready"](issue)), ns
    except Exception as exc:
        raise CannotLook(f"the worker's ready() could not run on {issue.get('identifier')} ({str(exc)[:120]})")


def _ticket(ident: str):
    ls = linear_sync()
    try:
        node = (ls.graphql(ISSUE_Q, {"id": ident}) or {}).get("issue")
    except ls.LinearAPIError as exc:
        if ls._ENTITY_NOT_FOUND_RE.search(str(exc)):
            return None
        raise CannotLook(f"Linear did not answer for {ident} ({str(exc)[:100]})")
    except Exception as exc:
        raise CannotLook(f"Linear did not answer for {ident} ({str(exc)[:100]})")
    return node


WITHIN_HOURS = 24  # a consumer counts only if it acts inside this window (RULE-2026-11-09-B)


def _plist_limit(name: str) -> int:
    """The nightly cap, READ from the job's plist so this check cannot drift from the job."""
    try:
        text = (SCRIPTS / name).read_text()
    except OSError as exc:
        raise CannotLook(f"{name} could not be read ({exc})")
    # Inside a <string> element only, so a comment or a description that mentions
    # --limit cannot be read as the job's cap (PR #715 review, round 1 nit).
    m = re.search(r"<string>[^<]*--limit\s+(\d+)[^<]*</string>", text)
    if not m:
        raise CannotLook(f"{name} no longer passes --limit, so the nightly cap is unknown")
    return int(m.group(1))


def _dor_queue() -> list:
    """[(mode, identifier)] in the order linear-dor-drafter.py would take them tonight
    (its own fetch_draftable + prioritise, the same two calls its main() makes). The
    mode is kept because a "terminal" pass uses a cap slot and writes no Definition of
    Ready (PR #715 review, round 1 major)."""
    dd = _load("dd", "linear-dor-drafter.py", "linear_dor_drafter_for_wait")
    ls = linear_sync()
    try:
        tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % dd.TEAM_KEY, {})["teams"]["nodes"][0]["id"]
        return [(mode, i["identifier"]) for mode, i in dd.prioritise(dd.fetch_draftable(ls, tid))]
    except Exception as exc:
        raise CannotLook(f"the DoR drafter's queue could not be read ({str(exc)[:100]})")


def _triage_queue() -> list:
    """Identifiers in the order linear-alert-triage.py takes them: its own lane_pools()
    eligible list, oldest first. Held and refused alerts are not in it."""
    at = _load("at", "linear-alert-triage.py", "linear_alert_triage_for_wait")
    try:
        eligible, _refused, _held = at.lane_pools(linear_sync())
        return [i["identifier"] for i in eligible]
    except Exception as exc:
        raise CannotLook(f"the alert triage queue could not be read ({str(exc)[:100]})")


def _queue_consumer(ident: str, issue: dict, labels: set, projects: set) -> tuple:
    """(consumer_text | None, note). A nightly job counts only while the ticket sits
    within its cap, so it acts inside WITHIN_HOURS. Beyond the cap the note says
    how far behind it is: that is a wait on nobody, tonight and tomorrow.
    """
    if "owner:sana" not in labels or labels & {"owner:assaf", "blocked:capability"}:
        return None, ""
    proj = (issue.get("project") or {}).get("name") or ""
    if proj not in projects:
        return None, ""
    desc = issue.get("description") or ""
    if "kipi-alert-fingerprint" in desc:
        queue, job, plist, what = _triage_queue, "linear-alert-triage.py (com.kipi.linear-alert-triage)", \
            "com.kipi.linear-alert-triage.plist", "promote-or-hold"
    elif "needs-scope" in labels or "Definition of Ready" not in desc:
        queue, job, plist, what = _dor_queue, "linear-dor-drafter.py (com.kipi.linear-dor, 03:00)", \
            "com.kipi.linear-dor.plist", "write its Definition of Ready"
    else:
        return None, ""
    raw = queue()
    # The DoR queue carries (mode, id); the triage queue carries bare ids.
    order = [x[1] if isinstance(x, tuple) else x for x in raw]
    modes = {x[1]: x[0] for x in raw if isinstance(x, tuple)}
    if ident not in order:
        return None, ""
    cap = _plist_limit(plist)
    behind = order.index(ident)
    if queue is _dor_queue and modes.get(ident) not in ("draft", "redraft"):
        return None, f"; {job.split()[0]} would only mark {ident} {modes.get(ident) or 'unknown'}, which writes no Definition of Ready"
    if behind < cap:
        return (f"{job} will {what} for {ident} tonight (position {behind + 1} of {len(order)}, "
                f"cap {cap} a night, inside {WITHIN_HOURS}h)"), ""
    return None, f"; queued behind {behind} in {job.split()[0]}, which takes {cap} a night, so not inside {WITHIN_HOURS}h"


def _why_not(issue: dict, ns: dict, projects: set, note: str = "") -> str:
    labels = {l["name"] for l in issue["labels"]["nodes"]}
    proj = (issue.get("project") or {}).get("name")
    if "owner:assaf" in labels:
        return "it carries owner:assaf, which the worker never takes"
    if "owner:sana" not in labels:
        return "it has no owner:sana label"
    if "needs-scope" in labels:
        return "it carries needs-scope, which the worker refuses as unexecutable" + note
    if "blocked:capability" in labels:
        return "it carries blocked:capability, which the worker refuses"
    if ns["is_fleet_alert"](issue):
        return "it is a fleet alert ticket (kipi-alert-fingerprint), which linear-worker.sh is_fleet_alert() skips" + note
    if not proj or proj not in projects:
        return f"its project {proj or '(none)'!r} has no checkout a worker runs in"
    desc = issue.get("description") or ""
    if "Definition of Ready" not in desc:
        return "it has no Definition of Ready, so the worker does not pick it" + note
    state = issue["state"]
    if state["type"] == "started":
        held = ns["started_hold"](issue)
        return (f"it is {state['name']} with no live lane marker and no worker claim "
                f"({held or 'the worker declined it'})")
    return f"linear-worker.sh ready() refuses it in state {state['name']}"


def _consumer_for_ticket(ident: str, waiter: str = "") -> tuple:
    ls = linear_sync()
    if waiter and waiter == ident:
        return False, NO_ONE + f"{ident} is the lane's own ticket; a lane cannot be the consumer of its own wait"
    issue = _ticket(ident)
    if not issue:
        return False, NO_ONE + f"{ident} does not exist on the board"
    state = issue["state"]
    if state["type"] in ("completed", "canceled"):
        return False, NO_ONE + f"{ident} is {state['name']}, so there is no work left for a hold to wait on"
    if state["type"] == "started":
        marker = ls.lane_marker(ident)
        if marker.startswith("its lane marker"):
            # lane_marker() reads an unreadable marker as live so the fleet stays
            # off the ticket (fail closed). For THIS question the direction inverts:
            # a marker nobody can read is not proof anyone is working.
            raise CannotLook(marker)
        if marker:
            return True, f"{ident} is {state['name']} with a live lane marker ({marker})"
        claim = ls.live_claim(os.path.join(state_dir(), "worktrees"), ident)
        if claim:
            return True, f"{ident} is {state['name']} with {claim}"
    projects = local_projects()
    proj = (issue.get("project") or {}).get("name") or ""
    ready, ns = _worker_ready(issue, proj if proj in projects else "\0no-checkout")
    if ready:
        return True, f"linear-worker.sh would pick {ident} (owner:sana, a Definition of Ready, project {proj})"
    labels = {l["name"] for l in issue["labels"]["nodes"]}
    found, note = _queue_consumer(ident, issue, labels, projects)
    if found:
        return True, found
    return False, NO_ONE + f"{ident}: " + _why_not(issue, ns, projects, note)


def _lane_pr(waiter: str) -> str:
    """The `pr` the waiting lane's own marker says it drives ('' when none or unreadable)."""
    d = os.environ.get("KIPI_LANES_DIR") or os.path.expanduser("~/.config/kipi/lanes")
    try:
        return str(json.load(open(os.path.join(d, waiter + ".json"))).get("pr") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _consumer_for_pr(m, waiter: str = "") -> tuple:
    mine = _lane_pr(waiter) if waiter else ""
    if mine and mine != "-":
        mm = PR_RX.match(mine) or re.match(r"^(?P<n>\d+)$", mine)
        # A bare number carries no repo, so it is read against any repo: refusing a
        # wait on a different repo's same-numbered PR is the safe side (pr-owner.py
        # defers to a live lane on the PR it drives).
        if mm and mm.group("n") == m["n"] and (not mm.groupdict().get("repo") or mm.group("repo") == m["repo"]):
            return False, NO_ONE + f"{m['repo']}#{m['n']} is the PR the lane itself drives; pr-owner.py defers to a live lane, so it cannot be the consumer of that lane's wait"
    po = pr_owner()
    ci = po.ci_redrive()
    repo, number, owner = m["repo"], int(m["n"]), m["owner"]
    try:
        rows, targets = po.fleet_repos(po.ROOT)
    except SystemExit as exc:
        raise CannotLook(str(exc.code)[:160])
    for name, path, _remote in rows:
        slug = po.slug_for(po.ROOT, path, targets)
        if not slug or slug.split("/")[-1] != repo or (owner and slug.split("/")[0] != owner):
            continue
        try:
            if po.archived(path, name) or po.archived(path, slug):
                return False, NO_ONE + f"{slug} is behind the archive guard, which pr-owner.py does not read (RULE-2026-10-23-B)"
        except RuntimeError as exc:
            raise CannotLook(str(exc)[:160])
        if Path(path, ".kipi-no-dispatch").exists():
            return False, NO_ONE + f"{slug} has a .kipi-no-dispatch kill switch, so pr-owner.py skips it"
        try:
            raw = po.gh_json(["pr", "view", str(number), "-R", slug, "--json", "state,isCrossRepository,number"])
        except (RuntimeError, ValueError) as exc:
            raise CannotLook(f"gh could not read {slug}#{number} ({str(exc)[:100]})")
        if not raw or str(raw.get("state")).upper() != "OPEN":
            return False, NO_ONE + f"{slug}#{number} is not open"
        if ci.head_provenance(raw) != ci.SAME_REPO:
            return False, NO_ONE + f"{slug}#{number} has a head outside the repo (a fork or unstated), and pr-owner.py acts on none of those"
        return True, f"pr-owner.py (hourly, com.kipi.pr-owner) owns open PR {slug}#{number}"
    return False, NO_ONE + f"{repo} is not in the fleet set pr-owner.py sweeps, so nothing reviews, fixes or merges {repo}#{number}"


def consumer_for(ref: str, waiter: str = "") -> tuple:
    """(True, consumer) or (False, "nothing picks this up: why"). Raises CannotLook.

    `waiter` is the lane's own ticket: its own marker is never the consumer of its wait.
    """
    ref = (ref or "").strip()
    if TICKET_RX.match(ref):
        return _consumer_for_ticket(ref, waiter)
    m = PR_RX.match(ref)
    if m:
        return _consumer_for_pr(m, waiter)
    raise ValueError(f"{ref!r} is neither a ticket id like ASK-123 nor a PR like owner/repo#12")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    waiter = ""
    if len(argv) == 3 and argv[1] == "--waiter":
        waiter = argv[2]
        argv = argv[:1]
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 64
    try:
        ok, text = consumer_for(argv[0], waiter)
    except ValueError as exc:
        print(f"wait-has-consumer: {exc}", file=sys.stderr)
        return 64
    except CannotLook as exc:
        print(f"wait-has-consumer: could not check: {exc}", file=sys.stderr)
        return 2
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
