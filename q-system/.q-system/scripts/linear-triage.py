#!/usr/bin/env python3
"""The senior-engineer triage pass: read every open issue, decide, say why.

WHY THIS EXISTS

`capability-map-gen.py` reports what is wired and explicitly refuses to judge it:

    "it does not judge whether a capability is *good* ... The senior-engineer
     triage pass adds judgment on top of this; it does not replace it."

That pass was named, deferred to, and never built. This is it. Measured
2026-07-27: 190 open issues on the ASK board, 184 of them (96%) carrying zero
comments -- nothing on the issue said what was happening with it, so the board
was a dump rather than a tracker.

WHY IT MUST RUN BEFORE THE DoR DRAFTER, NOT AFTER

`com.kipi.linear-dor` is loaded and runs `kipi dor --limit 8 --apply` nightly at
03:00, writing a Definition of Ready onto any backlog issue lacking one. 130 of
190 open issues lacked one. At 8 a night that makes all 130 worker-READY inside
~16 nights with no judgment applied to any of them -- readiness manufactured
ahead of triage (sp-0126e55b). Drafting is inflow. Triage gates it.

WHAT THE MODEL IS AND IS NOT ASKED

It is asked to judge. It is NOT asked to invent facts: every issue reaches the
model with disk evidence this script gathered -- which of the paths the issue
names actually exist. Same discipline as capability-map-gen, whose every
`evidence` string is a fact read off disk. A verdict that contradicts the
evidence block is the reviewer's to catch, and the evidence is printed next to
the verdict so it can be.

WHY DRY BY DEFAULT, AND WHY `--apply` IS A SECOND RUN

Linear objects here are permanent: `mcp__linear__*delete*` and archive are both
blocked by `~/.claude/hooks/destructive-op-deny.sh` and an agent cannot set
ALLOW_DESTRUCTIVE=1 for itself. Closing is reversible; creating 116 wrong
comments is not. So the first run prints a table and writes nothing. Scar,
2026-07-27: `pr-receipt-gate.py` shipped with a header stating it avoided
failing its own PR, passed adversarial review saying so, and then failed its own
PR on the first CI run (sp-ac51aa81). Confident agent output that survives review
is exactly the thing to read before it touches 116 permanent objects.

EXIT CODES -- this script never lies about failure
  0  ran, and every issue it was asked to judge got a verdict
  1  usage error
  9  the run could not judge everything it fetched (model unavailable, timeout,
     malformed output). Partial results are still printed and, under --apply,
     still written -- but the exit code says the pass is incomplete.

Deliberately NOT `exit 0 always`. That shape is under review as its own defect
class (ASK-213): three silent-success bugs shipped on 2026-07-27, each one a
failure path that exited 0 and told nobody.

Usage:
  linear-triage.py --project kipi-system              # dry, prints the table
  linear-triage.py --project kipi-system --apply      # writes verdicts
  linear-triage.py --project kipi-system --limit 10   # bound the pass
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent

# The five buckets. Deliberately small: a taxonomy nobody can hold in their head
# gets ignored, and every extra bucket is a decision the reader has to re-make.
# Each one names an ACTION, not a feeling about the issue.
CATEGORIES = {
    "do-now":           "real, scoped, and worth working now",
    "needs-scope":      "real, but not actionable as written (no files, no check, or unclear outcome)",
    "batch":            "one of N near-identical siblings; work them as one change, not N",
    "not-planned":      "superseded, duplicate, already done, or not worth doing -- close it",
    "founder-decision": "cannot be decided by an engineer: needs a call on priority, money, or risk",
}

# Written into every comment this script posts. Re-running finds it and UPDATES
# that comment instead of appending a second one. Without this, a nightly triage
# pass would grow an unreadable comment stack on a permanent object -- the same
# cry-wolf failure as a Slack ping that fires twice a day on an unchanged fleet.
MARKER = "<!-- kipi-triage-verdict -->"

# Reuse, never re-derive: the drafter already solved "where is the claude binary
# when launchd's PATH does not say", and got it wrong once in production
# (8 of 8 drafts died on FileNotFoundError while launchd recorded exit 0).
# Importing it means one fix site, per the fleet-homogeneity rule.
DRAFTER = HERE / "linear-dor-drafter.py"

ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
  nodes{id identifier title description createdAt
        state{name type} project{name} labels{nodes{name}}
        comments{nodes{id body}}}
  pageInfo{hasNextPage endCursor}}}"""

COMMENT_UPDATE = """mutation($id:String!,$input:CommentUpdateInput!){
  commentUpdate(id:$id,input:$input){success comment{id}}}"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def claude_binary() -> str | None:
    """Delegate to the drafter's resolver so there is ONE answer fleet-wide."""
    try:
        return _load(DRAFTER, "dor").claude_binary()
    except Exception:
        # The drafter is a sibling script, not a hard dependency. If it cannot be
        # imported, fall back to PATH rather than failing the whole pass -- but
        # say so, because a silent degrade here is how the launchd bug hid.
        print("WARN: could not import linear-dor-drafter.py; falling back to PATH",
              file=sys.stderr)
        return shutil.which("claude")


# --- disk evidence ---------------------------------------------------------
# What the model gets INSTEAD of being trusted to imagine the repo. An issue that
# names a file which no longer exists is the single strongest not-planned signal
# available, and it is a fact, not a judgment.

# `~` is in the class deliberately. Without it, `~/Library/LaunchAgents/x.plist`
# matched nothing, so the out-of-repo branch below was unreachable for the
# dominant real case -- all 32 job-migration issues name their target that way,
# and every one of them would have been judged as if it declared no paths at all.
# Caught by test-linear-triage.sh, not by reading.
PATH_RE = re.compile(r"`(~?[A-Za-z0-9_./-]+\.(?:py|sh|md|json|yml|yaml|plist))`")


def disk_evidence(issue: dict) -> list:
    """Every repo-relative path the issue names, and whether it exists.

    Only paths inside this repo are checked. A `~/Library/LaunchAgents/...` or
    `/Users/...` path is reported as out-of-repo rather than missing: the loop
    cannot produce a diff for it, and calling that "missing" would read as a
    reason to close work that is simply machine-local.
    """
    desc = issue.get("description") or ""
    out, seen = [], set()
    for raw in PATH_RE.findall(desc):
        if raw in seen:
            continue
        seen.add(raw)
        if raw.startswith(("~", "/")):
            out.append({"path": raw, "state": "out-of-repo"})
            continue
        out.append({"path": raw,
                    "state": "exists" if (REPO / raw).exists() else "MISSING"})
        if len(out) >= 12:
            break
    return out


def structural_flags(issue: dict, ev: list) -> list:
    """Deterministic facts about the issue, computed here and never guessed.

    These are handed to the model as constraints. The model may not override
    them; it explains what to DO about them.
    """
    desc = issue.get("description") or ""
    flags = []
    if "Definition of Ready" not in desc:
        flags.append("no-DoR")
    if not re.search(r"\*\*Files:\*\*", desc):
        flags.append("no-Files-line")
    if ev and all(e["state"] == "out-of-repo" for e in ev):
        flags.append("all-paths-outside-repo")
    if any(e["state"] == "MISSING" for e in ev):
        flags.append("names-a-path-that-does-not-exist")
    if not issue["comments"]["nodes"]:
        flags.append("never-commented-on")
    m = re.search(r"kipi-key:\s*([^\s/]+)/", desc)
    if m:
        flags.append(f"machine-filed-by:{m.group(1)}")
    return flags


# --- in-flight work --------------------------------------------------------
# sp-d901c01e. The first dry pass judged ASK-210 `needs-scope` -- "add a
# **Files:** line, then re-triage" -- while PR #23 was open carrying that exact
# diff. Triage reasons from issue text plus disk, so an issue whose work is
# half-shipped looks identical to one nobody has touched.
#
# The fix is to hold no opinion. An issue with an open PR already has an owner
# (converge -> review -> merge). Re-scoping it from here races that loop, and
# under --apply writes a permanent Linear comment contradicting live work.
#
# Branch names only, never the PR title or body: titles routinely name issues
# they supersede ("re-file of ASK-208"), and claiming those would withhold real
# backlog from triage forever. ASK-210 settled the same question the same way
# for the receipt gate -- the branch is the reliable source, the body is not.
#
# TODO(sp-6d394dbb): collapse this onto plugins/kipi-dsse/scripts/linear_branch.py
# once PR #23 lands. That module is the canonical branch->issue convention, but
# PR #23 CREATES it; it is not on main yet, so importing it here today would
# make triage depend on an unmerged branch.
PR_BRANCH_RE = re.compile(r"(?:^|/)ask-0*(\d+)$", re.I)


def open_pr_by_issue(prs: list) -> dict:
    """Map ASK-n -> the open PR number claiming it, from branch names alone.

    Lowest PR number wins, so a stale branch and its re-cut do not make the
    answer flicker between passes. Which of the two is reported matters far
    less than the mapping being stable.
    """
    out: dict = {}
    for pr in prs:
        m = PR_BRANCH_RE.search((pr.get("headRefName") or "").strip())
        if not m:
            continue
        key = f"ASK-{int(m.group(1))}"
        num = pr.get("number")
        if key not in out or num < out[key]:
            out[key] = num
    return out


def fetch_open_prs() -> list:
    """Open PRs for this repo, or [] when gh cannot answer.

    Degrading to [] restores the pre-fix behaviour: every issue stays
    triageable. That is the safe direction. A missed skip costs one wrong
    verdict a human can read and argue with; a wrongly-claimed issue would be
    withheld from triage silently, and nothing would ever surface it again.

    KIPI_GH overrides the binary -- the same seam converge.sh uses for NOTIFY --
    so the suite can drive this without a network or a live board.
    """
    gh = os.environ.get("KIPI_GH", "gh")
    try:
        out = subprocess.run(
            [gh, "pr", "list", "--state", "open", "--limit", "100",
             "--json", "number,headRefName"],
            cwd=REPO, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    try:
        parsed = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def partition_in_flight(issues: list, pr_map: dict) -> tuple:
    """Split into (triageable, [(issue, pr_number), ...]).

    A partition, not a filter: the caller PRINTS the second list. Dropping them
    silently would read as "triage saw 116 issues and had no opinion on 4", the
    same silent-success class as a guard that exits 0 on failure.
    """
    keep, flight = [], []
    for issue in issues:
        num = pr_map.get(issue["identifier"])
        if num is None:
            keep.append(issue)
        else:
            flight.append((issue, num))
    return keep, flight


PROMPT = """You are a senior staff engineer triaging a backlog you did not create.

Decide, for EACH issue below, which ONE bucket it belongs in:

{buckets}

RULES

- Volume is not junk. Many of these were filed automatically, but a scanner
  filing 32 issues can mean 32 real jobs. Judge the issue, not its filer.
- `batch` is for issues that share a shape AND a fix. If working them as one
  change would be one script plus N config lines, that is `batch`.
- `not-planned` needs a concrete reason: superseded by X, duplicate of Y,
  already true on disk, or the target no longer exists. "Low value" alone is
  not a reason -- that is `needs-scope` or `founder-decision`.
- `founder-decision` is for priority, money, and risk calls ONLY. Scoping and
  sequencing are engineering calls and belong to you.
- The STRUCTURAL FLAGS are facts computed from disk, and `enforce_flags()` in
  this script REWRITES your answer if it contradicts them: an issue flagged
  `no-Files-line` or `all-paths-outside-repo` cannot produce a diff, so a
  `do-now` on it is downgraded to `needs-scope` before anything is written.
  Saying `do-now` there does not make it so; it just loses you the `why`.

OUTPUT

One JSON object per line, nothing else. No prose, no fences, no preamble.

{{"id": "ASK-n", "category": "<bucket>", "why": "<one sentence, concrete, names the evidence>", "action": "<the next concrete step, or 'none'>"}}

The `why` is written onto a permanent Linear issue and is the only explanation
anyone will ever read for this decision. Make it specific enough to argue with.

ISSUES

{issues}
"""


# Flags that mean the autonomous worker structurally cannot finish this issue:
# its flow is worktree -> commit -> PR -> review -> merge, so an issue that
# yields no diff in THIS repo produces no PR, converge.sh exits 7 ("no PR after
# round 1"), and the issue burns an attempt. Measured 2026-07-27: of 56 issues
# the worker considered READY, 13 carried no `**Files:**` line and 1 named only
# machine-local paths -- 5 in 6 of its own queue could never reach a terminal
# state.
UNDISPATCHABLE_FLAGS = ("no-Files-line", "all-paths-outside-repo")


def enforce_flags(v: dict, flags: list) -> dict:
    """Deterministic override of a verdict that contradicts disk facts.

    The prompt DESCRIBES this function; it does not substitute for it. A rule
    that lives only in prompt text is a wish -- this repo blocks that claim at
    write time (`prompt-only-enforcement-guard.py`), and it was right to: the
    model is the one thing here with an incentive to call a vague issue
    actionable, because `do-now` is the most helpful-sounding answer.

    The original verdict is preserved in `overridden_from` so miscalibration
    stays visible rather than being silently corrected -- the same reason
    pr-verdict-lib.sh records the reviewer's STATED verdict beside the DERIVED
    one instead of overwriting it.
    """
    if v.get("category") != "do-now":
        return v
    blocking = [f for f in flags if f in UNDISPATCHABLE_FLAGS]
    if not blocking:
        return v
    v = dict(v)
    v["overridden_from"] = "do-now"
    v["category"] = "needs-scope"
    v["why"] = (f"Cannot be dispatched as written ({', '.join(blocking)}): the worker "
                f"produces no diff for it, so no PR and no review. Original triage read: "
                f"{v['why']}")
    v["action"] = "Add a **Files:** line naming in-repo paths, then re-triage."
    return v


def render_issue(i: dict, ev: list, flags: list) -> str:
    body = (i.get("description") or "(empty)")
    return (f"--- {i['identifier']} ---\n"
            f"title: {i.get('title')}\n"
            f"state: {i['state']['name']}\n"
            f"structural flags: {', '.join(flags) or 'none'}\n"
            f"paths named: {json.dumps(ev) if ev else 'none'}\n"
            f"description:\n{body[:1800]}\n")


def judge_batch(batch: list, timeout: int) -> tuple:
    """One `claude -p` call over N issues. Returns (verdicts, reason_or_empty).

    Batched rather than one-per-issue because 116 separate calls on the founder's
    SUBSCRIPTION competes with interactive work -- the same reasoning that made
    the DoR drafter a bounded nightly drip.
    """
    binary = claude_binary()
    if not binary:
        return [], "no claude binary found"
    blocks, flags_by_id = [], {}
    for i in batch:
        ev = disk_evidence(i)
        flags_by_id[i["identifier"]] = structural_flags(i, ev)
        blocks.append(render_issue(i, ev, flags_by_id[i["identifier"]]))
    prompt = PROMPT.format(
        buckets="\n".join(f"  {k:17s} {v}" for k, v in CATEGORIES.items()),
        issues="\n".join(blocks),
    )
    try:
        res = subprocess.run([binary, "-p", prompt],
                             capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"claude call failed ({type(exc).__name__} after {timeout}s)"
    if res.returncode != 0:
        return [], f"claude exited rc={res.returncode}"

    verdicts, ids = [], {i["identifier"] for i in batch}
    for line in (res.stdout or "").splitlines():
        line = line.strip().strip("`")
        if not line.startswith("{"):
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        # A verdict for an issue we did not ask about is a hallucinated id, not a
        # bonus. Drop it -- writing it would put a comment on the wrong permanent
        # object, and there is no delete.
        if v.get("id") not in ids or v.get("category") not in CATEGORIES:
            continue
        if not (v.get("why") or "").strip():
            # A verdict with no reasoning is the one thing this pass exists to
            # stop: 96% of the board already had no explanation on it.
            continue
        verdicts.append(enforce_flags(v, flags_by_id.get(v["id"], [])))
    missing = ids - {v["id"] for v in verdicts}
    return verdicts, (f"no verdict for {sorted(missing)}" if missing else "")


# --- writing ---------------------------------------------------------------

def comment_body(v: dict) -> str:
    # An override is stated on the issue, never applied quietly. A reader who
    # disagrees needs to see that a machine rule beat the reviewer's judgement.
    override = ""
    if v.get("overridden_from"):
        override = (f"\n\n> Downgraded from `{v['overridden_from']}` by "
                    f"`enforce_flags()` on disk evidence, not by judgement.")
    return (f"{MARKER}\n"
            f"**Triage: `{v['category']}`** — {CATEGORIES[v['category']]}{override}\n\n"
            f"{v['why']}\n\n"
            f"**Next:** {v.get('action') or 'none'}\n\n"
            f"<sub>`linear-triage.py` {_now()}. Re-running updates this comment "
            f"in place. Disagree? Change the state or say so here; the next pass "
            f"reads existing comments.</sub>")


def existing_verdict_comment(issue: dict) -> str | None:
    for c in issue["comments"]["nodes"]:
        if MARKER in (c.get("body") or ""):
            return c["id"]
    return None


def closed_state_id(ls, team_id: str) -> str | None:
    """The 'canceled'-type state, which is Linear's 'not planned'.

    Never 'completed': closing an untriaged issue as Done would claim work was
    finished that nobody did, and that lie outlives the board.
    """
    states = (((ls.graphql(ls.TEAM_STATES_QUERY, {"teamId": team_id}) or {})
               .get("team") or {}).get("states") or {}).get("nodes") or []
    for s in states:
        if s.get("type") == "canceled":
            return s["id"]
    return None


def apply_one(ls, issue: dict, v: dict, close_id: str | None) -> str:
    """Write the verdict. Returns a short outcome string for the report."""
    body = comment_body(v)
    existing = existing_verdict_comment(issue)
    if existing:
        ls.graphql(COMMENT_UPDATE, {"id": existing, "input": {"body": body}})
        wrote = "comment-updated"
    else:
        ls.graphql(ls.COMMENT_CREATE, {"input": {"issueId": issue["id"], "body": body}})
        wrote = "comment-added"
    if v["category"] == "not-planned":
        if not close_id:
            return wrote + " / NOT CLOSED (no canceled-type state on this team)"
        ls.graphql(ls.ISSUE_UPDATE, {"id": issue["id"], "input": {"stateId": close_id}})
        return wrote + " / closed"
    return wrote


# --- main ------------------------------------------------------------------

def fetch_open(ls, team_id: str, project: str | None) -> list:
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    out = [i for i in issues if i["state"]["type"] not in ("completed", "canceled")]
    if project:
        out = [i for i in out if ((i.get("project") or {}).get("name") or "") == project]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default="kipi-system",
                    help="only triage this project (default kipi-system). "
                         "Cross-repo judgement needs that repo on disk; see --project all")
    ap.add_argument("--apply", action="store_true", help="write verdicts to Linear")
    ap.add_argument("--limit", type=int, default=0, help="max issues (0 = all)")
    ap.add_argument("--batch", type=int, default=6, help="issues per model call")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per model call")
    ap.add_argument("--out", default="", help="also write verdicts as JSONL here")
    args = ap.parse_args()

    ls = _load(HERE / "linear-sync.py", "ls")
    team_id = ls.graphql('query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}',
                         {})["teams"]["nodes"][0]["id"]
    project = None if args.project == "all" else args.project
    issues = fetch_open(ls, team_id, project)
    if args.limit:
        issues = issues[:args.limit]
    if not issues:
        print(f"no open issues in project {args.project!r}")
        return 0

    # sp-d901c01e: work that is already moving is not this pass's to re-scope.
    issues, in_flight = partition_in_flight(
        issues, open_pr_by_issue(fetch_open_prs()))
    if in_flight:
        print(f"{len(in_flight)} issue(s) skipped -- an open PR already owns "
              f"them, so the review loop decides what happens next:")
        for issue, num in in_flight:
            print(f"  {issue['identifier']:<10} PR #{num}  {issue['title'][:60]}")
        print()
    if not issues:
        print("every open issue is in flight; nothing left to triage")
        return 0

    print(f"triaging {len(issues)} open issue(s) in {args.project!r} "
          f"({'APPLY' if args.apply else 'dry run, writes nothing'})\n")

    verdicts, problems = [], []
    for n in range(0, len(issues), args.batch):
        chunk = issues[n:n + args.batch]
        got, reason = judge_batch(chunk, args.timeout)
        verdicts += got
        if reason:
            problems.append(reason)
            print(f"  ! batch {n // args.batch + 1}: {reason}", file=sys.stderr)

    by_id = {i["identifier"]: i for i in issues}
    close_id = closed_state_id(ls, team_id) if args.apply else None

    counts = {}
    print(f"{'ISSUE':<10} {'CATEGORY':<17} WHY")
    print("-" * 100)
    for v in sorted(verdicts, key=lambda x: (x["category"], x["id"])):
        counts[v["category"]] = counts.get(v["category"], 0) + 1
        line = f"{v['id']:<10} {v['category']:<17} {v['why'][:70]}"
        if args.apply:
            line += "  [" + apply_one(ls, by_id[v["id"]], v, close_id) + "]"
        print(line)

    print("\nSUMMARY")
    for k in CATEGORIES:
        print(f"  {counts.get(k, 0):4d}  {k}")
    judged, total = len(verdicts), len(issues)
    print(f"  {judged}/{total} judged")

    if args.out:
        Path(args.out).write_text("".join(json.dumps(v) + "\n" for v in verdicts))
        print(f"  verdicts -> {args.out}")

    if judged < total or problems:
        print(f"\nINCOMPLETE: {total - judged} issue(s) got no verdict. "
              f"{'; '.join(problems[:3])}", file=sys.stderr)
        return 9
    return 0


if __name__ == "__main__":
    sys.exit(main())
