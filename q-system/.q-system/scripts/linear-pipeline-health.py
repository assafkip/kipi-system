#!/usr/bin/env python3
"""Outside watcher for the Linear pipeline: pages ONCE per real breakage, with
the diagnosis and the command that fixes it.

WHY THIS EXISTS (ASK-223)
-------------------------
`converge.sh` and `linear-worker.sh` already page on nine failures, but every one
of those pagers lives INSIDE the thing that fails. When the process dies, so does
its ability to report. Proven twice on 2026-07-28: `linear-triage.py --apply`
died on a Linear API TimeoutError after commenting on 74 issues and closing 32,
and paged nobody (sp-b5dcf944); a crashed reviewer reaches nobody at all
(sp-3a0cac1c). Both were found by a human reading a log.

`launchd-health-check.py` already implements this shape for silent launchd job
death. This is the same idea pointed at the Linear pipeline: an outside observer
that can see the states no in-process pager can, because the process that would
have reported them is gone.

THE HARD PART IS NOT DETECTION, IT IS SILENCE
---------------------------------------------
Most unhappy paths are the system WORKING. REQUEST CHANGES is the reviewer doing
its job. A PR waiting on review is latency. An issue skipped for a missing DoR is
a documented refusal. A pager that cries wolf trains the founder to mute the
channel, which silently removes every alert including the real ones -- strictly
worse than not building this at all. So: unknown states go SILENT and get logged,
never paged, and every finding is deduped by state so a 10-minute watcher reports
one breakage once rather than 144 times a day.

Single notification channel: slack-notify.sh (founder-notifications rule). Silent
no-op when no webhook is configured. Always exits 0 -- a watcher must never become
the failing job it reports.

Usage:
  linear-pipeline-health.py           # observe, classify, page (deduped)
  linear-pipeline-health.py --dry     # print findings only; no ping, no state write

Test seam: KIPI_PIPELINE_OBSERVATIONS=<file.json> replaces the live collectors with
a fixture, so the suite drives the classifier and the dedupe ledger end-to-end
without ever calling gh, Linear, or Slack.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRY_FLAGS = ("--dry", "--dry-run", "-n")

# Every field the PR detectors read, in ONE place. `isDraft` is here because the
# detector that skips drafts is inert if the query never asks for the field:
# `pr.get("isDraft")` on an unrequested field is None, which is falsy, which is
# "not a draft". Round-3 review caught exactly that shape -- the suite asserts
# this list reaches gh, not just that the detector reads it.
PR_LIST_FIELDS = "number,updatedAt,statusCheckRollup,autoMergeRequest,isDraft"

# Binaries the collectors cannot work without. A MISSING binary is a permanent
# configuration error and pages; a binary that is present but whose call FAILED
# is transient and goes quiet (see collect_live). launchd hands a job
# PATH=/usr/bin:/bin:/usr/sbin:/sbin, where gh does not live -- a watcher that
# treats that as "nothing is broken" reports perfect health while blind.
REQUIRED_TOOLS = ("gh",)

LINEAR_TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")

# Re-arm window. A state that is still broken this long after its last page gets
# one more page; anything sooner is the same breakage and stays silent. Six hours
# matches launchd-health-check.py's FAIL_PING_TTL_SECONDS on purpose -- one
# re-ping cadence across every watchdog the founder gets paged by.
RE_PING_TTL_SECONDS = 6 * 3600

# A PR whose required checks are all green has nothing left to do but merge. Past
# this many minutes it is not "about to merge", it is the silent stall ASK-222
# arms auto-merge to prevent -- and the one state that most looks like success.
GREEN_STALL_MINUTES = 20

# An issue In Progress with no branch and no PR for this long means the agent
# holding it died. Under an hour is just an agent still working.
STRANDED_ISSUE_HOURS = 4


def state_dir():
    """Where the pipeline keeps its live state. Overridable so the suite cannot
    read the founder's real reviews or write their real ledger."""
    return Path(os.environ.get("KIPI_STATE_DIR", str(Path.home() / ".config" / "kipi")))


def notify_script():
    return Path(os.environ.get("KIPI_NOTIFY", str(HERE / "slack-notify.sh")))


# --- the classifier ---------------------------------------------------------
# Every state the watcher can observe, and whether it is BREAKAGE. This table is
# the whole "actually broken" decision, kept as data so the suite can assert on
# each row rather than on a code path that happens to reach it.
#
# Silent rows are still LOGGED (printed), never paged. Keeping them named rather
# than dropping them is what makes "we decided this is normal" auditable instead
# of invisible.
SILENT_STATES = {
    "request_changes": "reviewer asked for changes -- the loop working, not breaking",
    "awaiting_review": "PR is waiting on its review -- normal latency",
    "skipped_no_dor": "issue skipped for a missing Definition of Ready -- a documented refusal",
    # A green DRAFT is a PR the founder parked on purpose, and GitHub refuses
    # auto-merge on a draft, so the green-stall page would carry both a wrong
    # diagnosis and an unrunnable command. It is observed and printed rather than
    # dropped inside the detector: a skip nobody can see is how a wrong skip
    # survives (this repo's PR #4 sat green-and-draft for 27 days).
    "green_but_draft": "PR is green but still a DRAFT -- parked on purpose; auto-merge does not apply",
}

# States this table can classify that NO collector here emits, because the
# process that owns them pages for itself: converge.sh and linear-worker.sh
# send these directly. They stay in BROKEN_STATES so a future collector (or a
# log tailer) can feed them without re-deriving the wording -- but they are
# declared here so "declared but unreachable" is a decision on the record
# instead of an accident. The suite fails on any OTHER unreachable state.
IN_PROCESS_PAGED_STATES = ("round_cap", "no_verdict", "worker_infra")

# state -> (diagnosis template, action template). Both are formatted with the
# finding's facts. An action is REQUIRED: a page with no next action is the noise
# this issue exists to stop, so a state with no runnable command does not belong
# in this table.
BROKEN_STATES = {
    "round_cap": (
        "converge {issue} gave up after {rounds} rounds, still at '{verdict}'. "
        "PR #{pr} is open and nothing merged, so the work is stranded. A cap-out "
        "is almost always scope: 1-change issues converge in 1 round.",
        'split it -- kipi linear issue "<one change>", then close {issue} as superseded',
    ),
    "no_verdict": (
        "the review on PR #{pr} ({issue}) produced no verdict -- the reviewer "
        "crashed or timed out, so converge cannot decide anything and the loop "
        "stops here.",
        "kipi review {pr} --issue {issue} --post",
    ),
    "worker_infra": (
        "worker hit an environmental error on {issue} ({detail}) and did NO work. "
        "Nothing self-heals from an auth failure or a hard-down API.",
        "fix credentials/network, then re-run: kipi work --apply --issue {issue}",
    ),
    "green_not_merged": (
        "PR #{pr} has every required check GREEN and has not merged for {minutes} "
        "min -- auto-merge was never armed, so it sits green forever. This is the "
        "stall that looks most like success.",
        "gh pr merge --auto --squash {pr}",
    ),
    "unreviewed_head": (
        "PR #{pr} ({issue}) is approved at {reviewed_sha} but its head {head_sha} "
        "was never read by any reviewer -- unreviewed code is sitting at the head "
        "of an approved PR.",
        "kipi review {pr} --issue {issue} --post",
    ),
    "stranded_issue": (
        "{issue} has been In Progress for {hours}h with no branch and no PR. The "
        "agent that claimed it died holding the work; nothing will pick it back up.",
        "kipi linear claims, release the dead holder, then: kipi work --apply --issue {issue}",
    ),
    "dead_converge": (
        "converge {issue} logged '{line}' and no converge process is running -- it "
        "died mid-round. Whatever it was driving is stopped, and its own pager died "
        "with it.",
        "bash q-system/.q-system/scripts/converge.sh --issue {issue}",
    ),
    "main_red": (
        "main is RED on {workflow}. Every open PR now fails validate for a reason "
        "that is not its own, so the whole board is blocked behind one break.",
        "gh run view {run_id} --log-failed",
    ),
    "watcher_blind": (
        "the pipeline watcher cannot find `{tool}` on its PATH, so every check "
        "that needs it returns nothing and this watcher reports perfect health "
        "while seeing nothing at all. launchd runs jobs with "
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin.",
        "bash q-system/.q-system/scripts/install-plist.sh com.kipi.linear-pipeline-health "
        "(re-renders the plist so it execs through a login shell)",
    ),
}


def classify(state, facts):
    """(is_broken, diagnosis, action) for one observation.

    An UNKNOWN state is silent, not broken. Borderline goes silent by design: a
    miss costs one unnoticed breakage, a false page costs the channel. The
    unknown state is still returned as its own diagnosis so it prints and can be
    promoted into a table row later, rather than vanishing.
    """
    if state in SILENT_STATES:
        return (False, SILENT_STATES[state], "")
    if state not in BROKEN_STATES:
        return (False, f"unclassified pipeline state '{state}' -- staying silent", "")
    diagnosis_template, action_template = BROKEN_STATES[state]
    try:
        return (True, diagnosis_template.format(**facts), action_template.format(**facts))
    except (KeyError, IndexError):
        # A fact the template wanted is missing. Still page -- the breakage is
        # real -- but say so instead of rendering "{pr}" at the founder.
        return (True,
                f"pipeline state '{state}' is broken; its detail fields are incomplete: {facts}",
                "read the run log: tail -100 ~/.config/kipi/linear-worker.log")


def page_text(subject, diagnosis, action):
    """The one message shape every page uses: what broke, why, what to do.

    `Do:` is a literal contract, not prose styling -- the suite greps for it on
    every page this fleet can emit, including the nine in converge.sh and
    linear-worker.sh. A page without a next action is the 3am noise this exists
    to stop.
    """
    return f"pipeline {subject}: {diagnosis} Do: {action}"


def finding_key(state, subject):
    return f"{state}:{subject}"


# --- observations -----------------------------------------------------------
# Each collector returns a list of {"state", "subject", "facts"} and NEVER raises:
# a watcher that dies because gh is slow stops watching, which is the silent death
# it exists to catch. Failures are printed and skipped.

def _gh_json(args):
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        return None


def _minutes_since(iso_timestamp, now):
    """Minutes between an ISO-8601 GitHub timestamp and now. None if unparseable."""
    try:
        stamp = time.strptime(iso_timestamp.replace("Z", "UTC"), "%Y-%m-%dT%H:%M:%S%Z")
    except Exception:
        return None
    return int((now - time.mktime(stamp) + time.timezone) / 60)


def green_not_merged_findings(prs, now, threshold_minutes=GREEN_STALL_MINUTES):
    """Pure: open PRs whose checks are all green and which have sat unmerged.

    A PR with no check results yet is NOT green -- it is early. Only an explicit
    all-SUCCESS rollup counts, so a PR whose checks have not started cannot be
    reported as a stall.

    A DRAFT is not a stall either. `gh pr merge --auto` is refused on a draft, so
    the page would name a wrong cause and hand over a command that cannot run.
    Drafts come back as a SILENT observation rather than a `continue`, because a
    skip that leaves no line in the log is indistinguishable from a detector that
    never ran.
    """
    findings = []
    for pr in prs or []:
        rollup = pr.get("statusCheckRollup") or []
        if not rollup:
            continue
        states = {(check.get("conclusion") or check.get("state") or "").upper()
                  for check in rollup}
        if not states <= {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            continue
        if pr.get("autoMergeRequest"):
            continue  # armed: the platform lands it, nothing to page about
        minutes = _minutes_since(pr.get("updatedAt", ""), now)
        if minutes is None or minutes < threshold_minutes:
            continue
        if pr.get("isDraft"):
            findings.append({
                "state": "green_but_draft",
                "subject": f"PR #{pr['number']}",
                "facts": {"pr": pr["number"], "minutes": minutes},
            })
            continue
        findings.append({
            "state": "green_not_merged",
            "subject": f"PR #{pr['number']}",
            "facts": {"pr": pr["number"], "minutes": minutes},
        })
    return findings


DISPATCH_LINE = re.compile(r"converge\[(?P<issue>[A-Z]+-\d+)\]\s+round\s+\d+/\d+\s+dispatching")


def dead_converge_findings(log_text, live_issues):
    """Pure: issues whose LAST converge log line is a dispatch, with no process.

    `dispatching` is the line converge writes immediately before handing a round
    to the worker. If it is the last thing an issue ever logged and no converge
    process holds that issue, the driver died inside the round -- and a dead
    driver cannot page. Any later line for that issue (a verdict, a STOP, a DONE)
    means it got past the dispatch and is not this failure.

    `live_issues` is the set of issues with a running converge, passed in rather
    than probed here so this stays a pure function the suite can drive.
    """
    last_line_by_issue = {}
    for line in (log_text or "").splitlines():
        match = DISPATCH_LINE.search(line)
        if match:
            last_line_by_issue[match.group("issue")] = ("dispatching", line.strip())
            continue
        other = re.search(r"converge\[(?P<issue>[A-Z]+-\d+)\]", line)
        if other:
            last_line_by_issue[other.group("issue")] = ("other", line.strip())
    findings = []
    for issue, (kind, line) in sorted(last_line_by_issue.items()):
        if kind != "dispatching" or issue in (live_issues or set()):
            continue
        findings.append({
            "state": "dead_converge",
            "subject": issue,
            "facts": {"issue": issue, "line": line.split("] ", 1)[-1]},
        })
    return findings


def live_converge_issues():
    """Issues with a converge process actually running right now.

    Reads `ps` rather than a pid file: converge writes no pid, and a pid file
    that outlives its process is the same lie the claim ledger already scarred on.
    """
    try:
        result = subprocess.run(["ps", "-Ao", "args="], capture_output=True,
                                text=True, timeout=15,
                                env={**os.environ, "LC_ALL": "C"})
    except Exception:
        return set()
    issues = set()
    for line in result.stdout.splitlines():
        if "converge.sh" not in line:
            continue
        match = re.search(r"--issue\s+([A-Z]+-\d+)", line)
        if match:
            issues.add(match.group(1))
    return issues


def unreviewed_head_findings(records, head_shas):
    """Pure: approved PRs whose recorded review sha is not the current head.

    An empty or absent head sha is NOT a finding: gh could not answer, and
    "unknown" must never render as "unreviewed" or this pages on every network
    blip.
    """
    findings = []
    for record in records or []:
        verdict = (record.get("verdict") or "").upper()
        if not verdict.startswith("APPROVE"):
            continue
        pr = record.get("pr")
        reviewed = (record.get("head_sha") or "").strip()
        head = (head_shas or {}).get(pr, "").strip()
        if not reviewed or not head or reviewed == head:
            continue
        findings.append({
            "state": "unreviewed_head",
            "subject": f"PR #{pr}",
            "facts": {"pr": pr, "issue": record.get("issue", "?"),
                      "reviewed_sha": reviewed[:8], "head_sha": head[:8]},
        })
    return findings


def main_red_findings(runs):
    """Pure: main's latest validate run concluded in failure."""
    for run in (runs or [])[:1]:
        if (run.get("conclusion") or "").lower() in ("failure", "timed_out", "startup_failure"):
            return [{
                "state": "main_red",
                "subject": "main",
                "facts": {"workflow": run.get("workflowName", "validate"),
                          "run_id": run.get("databaseId", "<run-id>")},
            }]
    return []


ISSUE_ID = re.compile(r"\b([A-Z][A-Z0-9]*-\d+)\b")


def issue_ids_in_prs(prs):
    """Every issue id any PR references, from its branch name, title or body.

    One id anywhere on a PR is enough to say the work reached a PR, which is the
    only question stranded_issue_findings asks of this.
    """
    ids = set()
    for pr in prs or []:
        blob = " ".join(str(pr.get(field) or "")
                        for field in ("headRefName", "title", "body"))
        ids.update(ISSUE_ID.findall(blob.upper()))
    return ids


def stranded_issue_findings(issues, pr_issue_ids, branch_names, now,
                            hours=STRANDED_ISSUE_HOURS):
    """Pure: In Progress past the window with no branch AND no PR.

    This is the state the DoR names as "agent died holding work". A branch or a
    PR means somebody got somewhere; only the issue with neither, hours after it
    was started, says the holder died before writing anything down.

    An issue with no start timestamp is SKIPPED, not reported: unknown age must
    never render as old, or every issue Linear cannot date pages at once.
    """
    branches_blob = " ".join(branch_names or ()).upper()
    findings = []
    for issue in issues or []:
        identifier = (issue.get("identifier") or "").upper()
        if not identifier:
            continue
        started = issue.get("startedAt") or issue.get("updatedAt") or ""
        minutes = _minutes_since(started, now)
        if minutes is None or minutes < hours * 60:
            continue
        if identifier in (pr_issue_ids or set()):
            continue
        if identifier in branches_blob:
            continue
        findings.append({
            "state": "stranded_issue",
            "subject": identifier,
            "facts": {"issue": identifier, "hours": minutes // 60},
        })
    return findings


def fetch_in_progress_issues():
    """Issues Linear has in a `started` state. None -- never [] -- on failure.

    The distinction is the whole point: [] means "Linear answered, nothing is In
    Progress", None means "we could not look". Collapsing the two is what let a
    transient failure read as a state that cleared.
    """
    try:
        spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = module.graphql(
            "query($team: String!) { issues(first: 100, filter: {"
            "team: {key: {eq: $team}}, state: {type: {eq: \"started\"}}}) "
            "{ nodes { identifier startedAt updatedAt } } }",
            {"team": LINEAR_TEAM_KEY},
        )
        return data["issues"]["nodes"]
    except Exception as exc:  # noqa: BLE001
        print(f"linear in-progress query failed: {exc}", file=sys.stderr)
        return None


def missing_tool_findings(missing):
    """A binary the collectors need that is not on PATH.

    Permanent and fixable, so unlike a failed CALL this one pages. The founder
    otherwise gets a watchdog that is loaded, exits 0 every 15 minutes, and can
    see nothing -- the exact silent death this whole script exists to catch,
    reproduced in the catcher.
    """
    return [{"state": "watcher_blind", "subject": tool, "facts": {"tool": tool}}
            for tool in missing or ()]


def collect_live():
    """(observations, unobserved_states) against the real world. Never raises.

    UNOBSERVED IS NOT EMPTY. Every collector whose data source failed names the
    states it could not rule on, and run() carries those ledger keys forward
    untouched instead of treating the silence as "it cleared". Without this, one
    `gh` timeout re-pages every breakage on the next successful cycle.
    """
    now = time.time()
    findings = []
    unobserved = set()

    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    findings += missing_tool_findings(missing)

    prs = None
    try:
        prs = _gh_json(["pr", "list", "--state", "open", "--limit", "50",
                        "--json", PR_LIST_FIELDS])
        if prs is None:
            unobserved.add("green_not_merged")
        else:
            findings += green_not_merged_findings(prs, now)
    except Exception as exc:  # noqa: BLE001
        unobserved.add("green_not_merged")
        print(f"green-stall check skipped: {exc}", file=sys.stderr)
    try:
        records = []
        for path in sorted((state_dir() / "pr-reviews").glob("pr-*.verdict.json")):
            try:
                records.append(json.loads(path.read_text()))
            except Exception:
                continue
        heads = {}
        blind = False
        for record in records:
            pr = record.get("pr")
            if pr is None:
                continue
            data = _gh_json(["pr", "view", str(pr), "--json", "headRefOid,state"])
            if data is None:
                blind = True  # one unanswered PR is enough to make this partial
                continue
            if (data.get("state") or "").upper() == "OPEN":
                heads[pr] = data.get("headRefOid", "")
        if blind:
            unobserved.add("unreviewed_head")
        findings += unreviewed_head_findings(records, heads)
    except Exception as exc:  # noqa: BLE001
        unobserved.add("unreviewed_head")
        print(f"unreviewed-head check skipped: {exc}", file=sys.stderr)
    try:
        log = state_dir() / "linear-worker.log"
        text = log.read_text(errors="replace") if log.exists() else ""
        # Only the tail matters: an issue that dispatched and died last week is
        # not actionable, and the whole log grows without bound.
        findings += dead_converge_findings("\n".join(text.splitlines()[-2000:]),
                                           live_converge_issues())
    except Exception as exc:  # noqa: BLE001
        unobserved.add("dead_converge")
        print(f"dead-converge check skipped: {exc}", file=sys.stderr)
    try:
        runs = _gh_json(["run", "list", "--branch", "main", "--limit", "1",
                         "--json", "conclusion,workflowName,databaseId"])
        if runs is None:
            unobserved.add("main_red")
        else:
            findings += main_red_findings(runs)
    except Exception as exc:  # noqa: BLE001
        unobserved.add("main_red")
        print(f"main-red check skipped: {exc}", file=sys.stderr)
    try:
        issues = fetch_in_progress_issues()
        # All three inputs must be real. A PR list or a branch list we could not
        # read would make every In Progress issue look branchless.
        all_prs = _gh_json(["pr", "list", "--state", "all", "--limit", "100",
                            "--json", "number,title,body,headRefName"])
        branches = _gh_json(["api", "repos/{owner}/{repo}/branches?per_page=100"])
        if issues is None or all_prs is None or branches is None:
            unobserved.add("stranded_issue")
        else:
            findings += stranded_issue_findings(
                issues, issue_ids_in_prs(all_prs),
                [branch.get("name", "") for branch in branches], now)
    except Exception as exc:  # noqa: BLE001
        unobserved.add("stranded_issue")
        print(f"stranded-issue check skipped: {exc}", file=sys.stderr)
    return findings, unobserved


def collect():
    """(observations, unobserved) from the fixture when the seam is set, else live.

    The fixture takes either a bare list (observations only) or an object with
    `observations` and `unobserved`, so the suite can drive a BLIND cycle -- the
    one the live code gets from a gh timeout and the one that used to wipe the
    ledger.
    """
    fixture = os.environ.get("KIPI_PIPELINE_OBSERVATIONS")
    if fixture:
        try:
            payload = json.loads(Path(fixture).read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"observation fixture unreadable: {exc}", file=sys.stderr)
            return [], set()
        if isinstance(payload, dict):
            return payload.get("observations", []), set(payload.get("unobserved", []))
        return payload, set()
    return collect_live()


# --- dedupe ledger ----------------------------------------------------------

def state_file():
    return state_dir() / "linear-pipeline-health-state.json"


def load_state():
    try:
        return json.loads(state_file().read_text())
    except Exception:
        return {}


def write_state(state):
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def findings_to_page(broken, previous, now, ttl=RE_PING_TTL_SECONDS):
    """The subset that has not already been paged for this same state.

    THE DEDUPE IS THE FEATURE. On a 10-minute watcher, a breakage that pages
    every cycle is 144 pages a day for one problem, and the founder mutes the
    channel -- which silently removes every alert including the real ones. So:
    page on the TRANSITION into a state, not on the level. Re-page only after the
    re-arm window, so a breakage nobody fixed does not disappear forever either.
    """
    due = []
    for finding in broken:
        key = finding_key(finding["state"], finding["subject"])
        prior = previous.get(key, {})
        last_paged = prior.get("paged_at", 0)
        if not prior or now - last_paged >= ttl:
            due.append(finding)
    return due


def send_page(message):
    """Best-effort. A broken notifier must not break the pipeline it watches, so
    a missing script or a failed send is logged and swallowed."""
    script = notify_script()
    if not script.exists():
        print(f"notify script missing ({script}); page not sent: {message}", file=sys.stderr)
        return
    try:
        subprocess.run(["bash", str(script), message], timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"page not sent ({exc}): {message}", file=sys.stderr)


def carry_forward(ledger, previous, unobserved):
    """Keep prior entries for states nobody could observe this cycle.

    A cleared state is DROPPED so re-breaking reads as a transition and pages.
    An UNOBSERVED state cannot be called cleared -- we did not look -- so its
    keys survive and the next successful cycle sees the same key, not a new one.
    The cost is bounded and stated: if the breakage really did clear while we
    were blind and then broke again, the re-page waits for RE_PING_TTL_SECONDS
    instead of firing at once. One late page beats a stream of false ones.
    """
    for key, entry in (previous or {}).items():
        if key not in ledger and entry.get("state") in unobserved:
            ledger[key] = entry
    return ledger


def run(dry_run):
    observations, unobserved = collect()
    now = int(time.time())

    broken = []
    for observation in observations:
        state = observation.get("state", "")
        subject = observation.get("subject", "?")
        is_broken, diagnosis, action = classify(state, observation.get("facts") or {})
        if not is_broken:
            # Printed, never paged. Silence that leaves no trace is how a wrong
            # silent-row decision survives unexamined.
            print(f"SILENT: {subject} [{state}] -- {diagnosis}")
            continue
        message = page_text(subject, diagnosis, action)
        print(f"BROKEN: {message}")
        broken.append({**observation, "message": message})

    if unobserved:
        # The report has to say this out loud. "0 broken" from a cycle that could
        # not see is the same sentence as "0 broken" from a healthy pipeline, and
        # the founder reads both as good news.
        print(f"DEGRADED: could not observe {', '.join(sorted(unobserved))} "
              f"-- prior findings for those states carried forward, not cleared")

    previous = load_state()
    due = findings_to_page(broken, previous, now)

    if dry_run:
        print(f"[dry] would page {len(due)} of {len(broken)} broken state(s)")
        return

    for finding in due:
        send_page(finding["message"])

    # The ledger holds what is broken right now, PLUS the keys we could not look
    # at. Dropping keys that genuinely cleared is what makes a state that breaks
    # again page again: re-breaking arrives as a fresh key, which is a
    # transition, which is the thing worth waking someone for.
    ledger = {}
    for finding in broken:
        key = finding_key(finding["state"], finding["subject"])
        paged_at = now if finding in due else previous.get(key, {}).get("paged_at", now)
        ledger[key] = {"paged_at": paged_at, "state": finding["state"],
                       "subject": finding["subject"]}
    write_state(carry_forward(ledger, previous, unobserved))
    print(f"paged {len(due)} of {len(broken)} broken state(s)")


def parse_mode(argv):
    """('live'|'dry'|'refuse', unrecognized). Same contract as
    launchd-health-check.py: an unrecognized flag REFUSES rather than silently
    taking the live path, because that near-miss already paged the founder once
    from a run that was meant to be read-only (ASK-181)."""
    unrecognized = [arg for arg in argv if arg not in DRY_FLAGS]
    if unrecognized:
        return ("refuse", unrecognized)
    return ("dry" if any(arg in DRY_FLAGS for arg in argv) else "live", [])


def main(argv):
    """Always 0. A watcher that exits non-zero becomes the failing job it reports,
    and launchd would then page about the pager."""
    mode, unrecognized = parse_mode(argv)
    if mode == "refuse":
        print(f"unrecognized flag(s): {' '.join(unrecognized)} -- refusing to run. "
              f"Dry: {' / '.join(DRY_FLAGS)}. Live: no flags at all.", file=sys.stderr)
        return 0
    try:
        run(mode == "dry")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
