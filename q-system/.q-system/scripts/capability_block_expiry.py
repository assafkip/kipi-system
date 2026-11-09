#!/usr/bin/env python3
"""Re-test every `blocked:capability` block and clear the ones that now pass.

WHY THIS EXISTS (ASK-288)
-------------------------
`blocked:capability` was a one-way door. linear-worker.sh applies it when a
runner is not equipped for an issue whose spec is sound, and the picker then
excludes the issue forever. Nothing re-tested the environment. The Linear
comment ends "once it exists, remove this label and the loop picks the issue
straight back up" -- and the only actor who could do that was a human reading
a comment. Measured 2026-08-01: 10 issues parked, the worker logging one
consolidated count every 15 minutes, and no path back into the pool.

A capability that ARRIVED (a binary installed, a credential exported, a
directory created) left the board exactly as blocked as one that never came.
That is the defect: the state was recoverable in principle and terminal in
practice.

THE SHAPE OF THE FIX
--------------------
A block is only expirable if the run that created it recorded HOW to test it.
linear-worker.sh writes a machine-readable marker into the park comment:

    <!-- capability-probe: bin:codex -->

This script reads that marker back, runs the probe, and on a pass calls
`linear-sync.py unblock` so the picker offers the issue again. No human is the
next actor.

FAIL CLOSED, ALWAYS
-------------------
Un-parking is the unrecoverable direction. Once the label is gone the picker
dispatches the issue and a still-blocked run burns a real attempt; a block left
in place costs one log line. So every ambiguity -- no marker, an unknown kind, a
malformed value, a probe that raises -- leaves the block ALONE and is reported.
Only an affirmative pass clears it.

NO SHELL, EVER
--------------
The marker is agent-authored text read back later by an unattended job. If the
probe kinds were "run this command" then any run that could write a Linear
comment could execute arbitrary code at 3am under the founder's credentials.
The kinds below are a closed allowlist evaluated in-process. `cmd:` is not a
kind and never will be; it lands in the unknown-kind branch like any other
typo.

HONEST BOUNDARY (read this before trusting a green run)
-------------------------------------------------------
These probes test the ENVIRONMENT this script runs in. They do NOT test a
runner's harness. The most common real block -- Claude Code's sensitive-path
guard refusing Edit/Write under `.claude/**` -- is not liftable by
`permissions.allow` and cannot be observed from a plain Python process, so a
`write:` probe against `.claude/` would pass here and un-park an issue Sana
still cannot do. That class has no probe: the park records `none`, and this
script never guesses a probe for it.

FAIL CLOSED COVERS THE PROBES, NOT THE CALENDAR (ASK-3960, PR #668 round 1).
An unprobeable block is never cleared by a guess. It is not left parked
forever either: at day 14 it takes ONE route by the capability its runner
lines name (see route_unprobeable), and every route has a named consumer:
apply-claude-changes.sh, the founder's morning list, or cap-ladder.py. A route
whose consumer is missing, or whose write did not land, leaves the block alone
and the next run retries.

Usage:
  capability_block_expiry.py [--repo-project NAME] [--apply] [--team ASK]
Dry by default: says what it would clear and mutates nothing.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_USAGE = 1
# The sweep RAN and at least one removal it asked for did not land (codex, PR
# #77 round 6). Distinct from EXIT_USAGE, which means it never ran, and from
# EXIT_INFRA, which means Linear was unreachable: here the probes were re-tested
# and the recovery path is the thing that is broken. It exits nonzero because
# this job is unattended before every pick, so exit 0 plus a summary that adds
# up is all anyone downstream reads -- and a recovery that cannot recover
# reporting itself as a healthy run is the silence ASK-288 exists to end.
# linear-worker.sh branches on this value; test-capability-block-expiry.sh pins
# its copy of the number against this constant so the two cannot drift.
EXIT_PARTIAL = 2
# Matches linear-worker.sh: 9 means the ENVIRONMENT is down and this run did no
# work. A caller can tell a dead Linear from a bad invocation.
EXIT_INFRA = 9

HERE = pathlib.Path(__file__).resolve().parent
BLOCK_LABEL = "blocked:capability"

# The marker linear-worker.sh writes into the park comment. Non-greedy so a
# comment carrying two markers yields two matches rather than one span across
# both; the LAST one wins (a re-park after a re-scope records a fresh probe and
# the old one must not outvote it).
PROBE_MARKER = re.compile(r"<!--\s*capability-probe:\s*(.*?)\s*-->")

# The literal a park writes when the runner recorded no probe. Distinct from a
# MISSING marker on purpose: "this run considered it and had nothing to test" and
# "this issue was parked before probes existed" are the same outcome here, but
# only the first proves the park path ran the recording step.
PROBE_NONE = "none"


def _load_linear_sync():
    """Import linear-sync.py as a module (its filename is not importable)."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_EXIT_NOOP = None


def ls_exit_noop() -> int:
    """linear-sync's EXIT_NOOP, READ FROM THAT FILE rather than restated here.

    A literal `4` in this file would be a second copy of a contract to keep in
    step, and the entire reason this script shells out to linear-sync instead of
    writing its own mutation is that linear-sync is the one writer. Cached: the
    load execs the module, and the clear path can run once per parked issue.
    """
    global _EXIT_NOOP
    if _EXIT_NOOP is None:
        _EXIT_NOOP = _load_linear_sync().EXIT_NOOP
    return _EXIT_NOOP


# --- the probe allowlist -----------------------------------------------------
# A probe answers with a bool -- or with one of these, when "it passed" would be
# a stronger claim than the probe actually made. ROTATED clears the block like a
# pass and reports itself as unverified; see probe_env.
ROTATED = "rotated"
# Every status run_probe may return. A probe returning anything else is a defect
# in the probe, and this file's rule for anything it cannot account for is to
# fail closed rather than un-park on a string it does not recognise.
STATUSES = ("pass", ROTATED, "fail", "unprobeable", "unknown")
# The two that take the label off. Kept as one name because main() and the
# reporting both branch on it, and two copies of "which statuses clear" is how a
# status ends up clearing in one place and not the other.
CLEARING = ("pass", ROTATED)


# --- THE 14-DAY ROUTE FOR A BLOCK NOTHING CAN PROBE (ASK-3960) -----------------
# Measured 2026-11-08: 38 parked, 38 unprobeable, 0 clearable. A block with no
# probe was "hand-clear-only", which is the ticket that just stays. Founder,
# 2026-11-08: "but what happens if nothing changed? the ticket just stays?" So
# at 14 days every unprobeable block takes a route by the capability it lacks,
# read from its own park comment:
#   claude-write  a .claude/ write the harness refuses agents. Listed for
#                 apply-claude-changes.sh, the founder's one-command land.
#   credential    a credential or account. One line on the morning status list.
#   unknown       neither. Handed to cap-ladder.py as a capout and unblocked, so
#                 the ladder's RCA, runner change, re-scope and decision move it.
#                 Only when cap-ladder.py is on this tree: a capout with no
#                 consumer is a ticket unblocked into nothing (PR #668 round 1).
# The credential line goes to the morning status file through cap-ladder.py,
# and founder_asks.py lists it in /q-morning; nothing pages. Once he resolves
# it, the next run unblocks the ticket with his answer quoted.
ROUTE_AFTER_DAYS = 14
CLAUDE_WRITE_RE = re.compile(r"\.claude/|sensitive[- ]path|settings(\.local)?\.json|harness (guard|permission)", re.I)
CREDENTIAL_RE = re.compile(r"credential|\btoken\b|api[ _-]?key|log ?in\b|logged in|oauth|password|\baccount\b|secret", re.I)
# The runner blocks of a park comment, the only part a runner wrote about THIS
# block. A BLOCK, NOT A LINE (PR #668 round 2, minor 3): the Sana line carries
# `head -c 1500` of the runner's sentinel (linear-worker.sh), newlines and all,
# so a credential named on its line 2 read as unknown and took the capout. A
# block runs to the next runner line or to the template's next fixed paragraph,
# so the boilerplate after the runner list is still never read.
RUNNER_BLOCK_RE = re.compile(
    r"^- \*\*(?:Sana|Codex)\b.*?(?=^- \*\*(?:Sana|Codex)\b|^\*\*(?:The Definition of Ready|Next:)|\Z)",
    re.M | re.S)
ATTEMPTS_FILE = os.environ.get("KIPI_ATTEMPTS") or os.path.expanduser(
    "~/.config/kipi/linear-worker-attempts.json")
LEDGER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attempts-ledger.py")
LADDER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cap-ladder.py")
# This job's one state file: when it first saw a park it could not date. ONE
# WRITER FUNCTION, MANY PROCESSES (PR #668 round 2, minor 4): the nightly job and
# a hand run both write it, two first sights read the same file, and the second
# rename dropped the first's stamp, so that park's 14 days restarted. Every
# read-modify-write holds SEEN_FILE.lock, the shape the attempts ledger and
# cap-ladder.py's status file already use. Then temp file and rename.
SEEN_FILE = os.environ.get("CAPABILITY_EXPIRY_SEEN") or os.path.expanduser(
    "~/.local/state/kipi/capability-expiry/first-seen.json")
EPOCH = "1970-01-01T00:00:00Z"


def dispatch_projects() -> list:
    """The Linear projects of every repo the dispatcher enters: the home row plus
    registry and overlay rows with dispatch.enabled true. The same opt-in set as
    kipi-dispatch.sh fleet_candidates, so a repo switched off (chief) is skipped.
    The probes test THIS machine, which every dispatch target shares."""
    home = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
    rows, out = [], []
    try:
        with open(os.path.join(home, "instance-registry.json"), encoding="utf-8") as fh:
            reg = json.load(fh)
        out.append((reg.get("skeleton") or {}).get("linear_project") or "")
        rows += reg.get("instances") or []
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.expanduser("~/.config/kipi/dispatch-targets.json"), encoding="utf-8") as fh:
            rows += json.load(fh).get("instances") or []
    except (OSError, ValueError):
        pass
    out += [r.get("linear_project") or r.get("name") or "" for r in rows
            if (r.get("dispatch") or {}).get("enabled") is True]
    seen = []
    for p in out:
        if p and p not in seen:
            seen.append(p)
    return seen


def classify(text: str) -> str:
    """The capability an unprobeable block lacks, from its park comment.

    ONLY THE RUNNER LINES ARE READ (codex, PR #668, P1). Every park comment ends
    with "A harness permission is an authorization decision", which matched
    `harness permission`, so every block classified as claude-write and a
    credential block got the .claude/ route. The runner lines are the only text a
    runner wrote about this block. A park comment without them (an older format)
    is read whole, minus its **Next:** paragraph, which is the same boilerplate.
    """
    lines = RUNNER_BLOCK_RE.findall(text or "")
    body = "\n".join(lines) if lines else "\n\n".join(
        p for p in (text or "").split("\n\n") if not p.lstrip().startswith("**Next:**"))
    if CLAUDE_WRITE_RE.search(body):
        return "claude-write"
    if CREDENTIAL_RE.search(body):
        return "credential"
    return "unknown"


def _park_comments(ls, identifier: str, since: str) -> list:
    """Every comment created at or after `since`, every page, oldest first.

    One loop for both readers (recorded_probe, park_text). park_text read
    `comments(first:100)` with no cursor and no date (PR #668 round 1 minor, and
    codex P2): a chatty ticket pushed its park comment off the only page read, and
    a park whose own comment failed to post was classified from an OLDER park's.
    """
    nodes, after, seen_cursors = [], None, set()
    while True:
        conn = ((ls.graphql(PARK_COMMENTS, {"id": identifier, "s": since, "a": after})
                 .get("issue") or {}).get("comments")) or {}
        nodes += conn.get("nodes") or []
        info = conn.get("pageInfo") or {}
        cursor = info.get("endCursor")
        # Normal exit is hasNextPage. The other two guards are for the ways a
        # remote connection hands back a loop with no end: a missing cursor,
        # or one that stops advancing.
        if not info.get("hasNextPage") or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        after = cursor
    nodes.sort(key=lambda n: n.get("createdAt") or "")
    return [n for n in nodes if (n.get("createdAt") or "") >= since]


def park_text(ls, identifier: str, since: str | None) -> str:
    """The newest comment of THIS park that names the missing capability.
    Undated, every comment is read: there is no older park to tell apart."""
    parks = [n for n in _park_comments(ls, identifier, since or EPOCH)
             if "missing capability" in (n.get("body") or "") or BLOCK_LABEL in (n.get("body") or "")]
    return (parks[-1].get("body") if parks else "") or ""


def credential_ask(identifier: str) -> str:
    """The one ask the credential route files. answered() matches on it, so the
    two can never disagree about which ask is this ticket's. Its second sentence
    is the one place the founder sees the resolve rule (see answered())."""
    return (f"access: {identifier} needs a credential or account the fleet cannot grant itself. "
            "Run the resolve in your own terminal: one run from an agent shell does not un-park it")


def ladder_const(name: str):
    """A top-level literal of cap-ladder.py (JOB, DEAD_TYPES), or None.

    READ FROM THAT FILE, not restated here, for the reason ls_exit_noop reads
    EXIT_NOOP: a second copy of the ladder's job name drifts from the one it
    stamps on its rows. PARSED, NOT IMPORTED: an import runs the whole script to
    read one literal."""
    try:
        tree = ast.parse(pathlib.Path(LADDER_SCRIPT).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def _founder_ctx(ctx, want: dict) -> bool:
    """A resolve's recorded context matches every key of FOUNDER_RESOLVE_CTX."""
    return isinstance(ctx, dict) and all(ctx.get(k) == v for k, v in want.items())


def answered(identifier: str, ask: str, after, refused: list | None = None) -> dict | None:
    """The founder's resolved answer to `ask`, resolved after `after`, or None.

    THE ANSWERED ASK WAS ASKED AGAIN. cap-ladder.py dedupes only against OPEN
    asks, and the label stays on a credential block, so once the founder ran
    --resolve the next night filed the same ask as a new row: a decision he made
    came back every morning, and the ticket never moved. Read-only: cap-ladder.py
    is the file's one writer. An answer older than this park belongs to an
    earlier park and does not count.

    THE LADDER'S OWN RESOLUTION IS NOT AN ANSWER (PR #668 round 2, major 1).
    cap-ladder.py sweep_dead_asks resolves an open ask by itself once the ticket
    closes, with resolved_by=JOB and a "moot:" note. Read as an answer, a
    reopened ticket was unblocked under a permanent comment saying the founder
    answered an ask he never saw. Every resolution the ladder makes on its own
    carries its JOB name; a person's --resolve carries his --by. With no JOB to
    compare against, nothing counts: an answer this job cannot tell from the
    janitor's never un-parks.

    ONLY A RESOLVE FROM THE FOUNDER'S TERMINAL IS HIS ANSWER (PR #668 round 3,
    finding 2; the decision and its reason sit on FOUNDER_RESOLVE_CTX in
    cap-ladder.py). The JOB check above was a denylist: a --resolve run in an
    agent shell (resolved_ctx.agent_env ['CLAUDECODE'], resolved_by "unnamed")
    passed it and un-parked the ticket under "the founder answered". The rule is
    now the allowlist the ladder already records the evidence for. A row with no
    context, or no rule to compare against, does not count. A refused row is
    appended to `refused`, so the route line can say why the ask came back.
    """
    from datetime import datetime
    job = ladder_const("JOB")
    want = ladder_const("FOUNDER_RESOLVE_CTX")
    if not (isinstance(job, str) and job and isinstance(want, dict) and want):
        return None
    path = os.environ.get("CAP_LADDER_STATUS") or os.path.expanduser("~/.local/state/kipi/morning-status.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    except (OSError, ValueError):
        return None
    hits = []
    for r in rows:
        if not (r.get("issue") == identifier and r.get("kind") == "founder-decision"
                and r.get("resolved") and r.get("ask") == ask):
            continue
        # [:80]: status_resolve stores resolved_by clipped to 80 characters.
        if (r.get("resolved_by") or "") == job[:80]:
            continue
        try:
            if datetime.fromisoformat((r.get("resolved_at") or "").replace("Z", "+00:00")) < after:
                continue
        except (TypeError, ValueError):
            continue
        if not _founder_ctx(r.get("resolved_ctx"), want):
            if refused is not None:
                refused.append(r)
            continue
        hits.append(r)
    return hits[-1] if hits else None


def _seen(identifier: str, now, apply: bool, forget: bool = False):
    """When this job first saw an undated park (stamped at first sight, under
    --apply), or drop the stamp once the ticket has taken its route."""
    from datetime import datetime

    def read() -> dict:
        try:
            with open(SEEN_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    if not (apply or forget):
        # A dry run stamps nothing, so it takes no lock: the rename keeps every
        # read a whole file.
        try:
            return datetime.fromisoformat(read()[identifier])
        except (KeyError, TypeError, ValueError):
            return now
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    # The lock file is never unlinked: two inodes at one path are two locks.
    with open(f"{SEEN_FILE}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read()
        if forget:
            if identifier not in data:
                return None
            data.pop(identifier)
        else:
            try:
                return datetime.fromisoformat(data[identifier])
            except (KeyError, TypeError, ValueError):
                pass
            data[identifier] = now.isoformat()
        tmp = f"{SEEN_FILE}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, SEEN_FILE)
    return now


def _founder_ask(identifier: str, ask: str) -> tuple[bool, str]:
    """Hand one ask to the morning status file through its ONE writer,
    cap-ladder.py --founder-ask (ASK-3824). Never appended here: two writers on
    one file is the race the ladder's lock exists to prevent."""
    if not os.path.isfile(LADDER_SCRIPT):
        return False, "cap-ladder.py is not on this tree, so the ask has no writer yet"
    p = subprocess.run([sys.executable, LADDER_SCRIPT, "--founder-ask", identifier, "founder-decision", ask],
                       capture_output=True, text=True, timeout=60)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


def _fixture_run() -> bool:
    """A run against a loopback Linear (a test fixture) that has NOT redirected the
    ledger and the status file. The first test run of this route wrote two capout
    records into the LIVE attempts ledger (ASK-903, ASK-908, 2026-11-08, undone
    with clear-capout): the Linear writes went to the fixture, the local ones did
    not. So a fixture run may only write local state it was pointed at."""
    url = os.environ.get("KIPI_LINEAR_API_URL") or ""
    loop = re.search(r"//(localhost|127\.\d+\.\d+\.\d+|\[::1\])[:/]", url)
    return bool(loop) and not (os.environ.get("KIPI_ATTEMPTS") and os.environ.get("CAP_LADDER_STATUS")
                               and os.environ.get("CAPABILITY_EXPIRY_SEEN"))


def route_unprobeable(ls, identifier: str, since: str | None, apply: bool, now_iso: str = "",
                      state_type: str = "") -> str:
    """One line: what happened to an unprobeable block. Writes only with apply."""
    if apply and _fixture_run():
        return ("unprobeable; REFUSED to route: a fixture Linear with the live ledger, status "
                "file or first-seen file (set KIPI_ATTEMPTS, CAP_LADDER_STATUS and CAPABILITY_EXPIRY_SEEN)")
    from datetime import datetime, timedelta, timezone
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    # A CLOSED TICKET TAKES NO ROUTE (PR #668 round 2, with PR #695). The listing
    # keeps closed tickets that still carry the label. The picker never offers
    # one, so an unblock or a requeue moves nothing, a capout sends the ladder
    # after a finished ticket, and since #695 `--founder-ask` refuses it with exit
    # 1, which read here as a failed ask every night. Closed is cap-ladder.py's
    # DEAD_TYPES, the set its sweep calls an ask moot on. The first-seen stamp is
    # dropped, so the file holds only tickets that can still route.
    #
    # NO DEAD_TYPES, NO ROUTE (PR #668 round 3, minor 3). This read `or ()`, so
    # with no readable cap-ladder.py nothing counted as closed and a completed
    # ticket got the full claude-write route and its permanent comment. The
    # file's header rule is fail closed for anything that un-parks, and answered()
    # already fails closed on the same file. So no ticket routes this run.
    dead = ladder_const("DEAD_TYPES")
    if not (isinstance(dead, (tuple, list)) and dead and all(isinstance(s, str) for s in dead)):
        return (f"unprobeable; NOT routed this run (fail closed): DEAD_TYPES is unreadable in {LADDER_SCRIPT}, "
                "so a closed ticket cannot be told from an open one; the next run with a readable ladder routes it")
    if state_type and state_type in dead:
        if apply:
            _seen(identifier, now, apply, forget=True)
        return f"unprobeable; {state_type} in Linear, so not routed (the picker never offers a closed ticket)"
    try:
        parked = datetime.fromisoformat((since or "").replace("Z", "+00:00"))
    except ValueError:
        parked = None
    # UNDATED IS NOT OLD (PR #668 round 1, major 2). With no park time this
    # skipped the 14 days and routed the same night. parked_at() reads the first
    # 100 history entries, so a busy ticket's park can sit outside them. The 14
    # days then count from the first night this job saw the park.
    start = parked or _seen(identifier, now, apply)
    if now - start < timedelta(days=ROUTE_AFTER_DAYS):
        due = (start + timedelta(days=ROUTE_AFTER_DAYS)).date().isoformat()
        return (f"unprobeable; routed by kind on {due} (day {ROUTE_AFTER_DAYS})"
                + ("" if parked else ", counted from the first night this job saw it (no park time on record)"))
    text = park_text(ls, identifier, since if parked else None)
    kind = classify(text)
    if kind == "claude-write":
        # NOT A MISSING CAPABILITY. apply_claude_changes.py is built to be run by
        # an agent ("There is no privileged caller"), so a .claude/ write the
        # Write tool refuses still has a coded path. The ticket goes back with
        # that path named, once per ticket; a second park after it falls through
        # to the ladder below instead of repeating.
        flag = "capability_route_claude_write"
        once = subprocess.run([sys.executable, LEDGER_SCRIPT, ATTEMPTS_FILE, "get", identifier, flag, ""],
                              capture_output=True, text=True).stdout.strip()
        if once != "True":
            if not apply:
                return "unprobeable claude-write; would unblock and requeue it through apply-claude-changes.sh"
            # `get` only picks the route. unblock_then_post picks the one writer:
            # the removal this run made, then the claim-flag one-shot (PR #668
            # round 2, major 2), then the notes.
            outcome, urc, detail = unblock_then_post(identifier, [
                ("progress", "**Unblocked by capability_block_expiry.py (ASK-3960).** The block was a .claude/ "
                 "write the Write tool refuses. That is not a missing capability: the fleet lands .claude/ edits "
                 "through `bash q-system/.q-system/scripts/apply-claude-changes.sh <proposal.json>`, which an "
                 "agent may run. Write the change as a proposal and apply it with that command. If this parks "
                 "again, cap-ladder.py takes it.", "--agent", "sana"),
                ("requeue", "--exit", "capability-route", "--why",
                 ".claude/ write routed through apply-claude-changes.sh", "--agent", "sana"),
            ], claim=flag)
            if outcome == FAILED:
                return (f"unprobeable claude-write; the unblock did NOT land (rc {urc}: {detail[:120]}); "
                        "no flag, no note, the next run retries")
            # The label is off, so this park's stamp goes whoever removed it: a
            # stale stamp would route an undated re-park the night it is seen.
            _seen(identifier, now, apply, forget=True)
            return "unprobeable claude-write; " + {
                NOOP: "a concurrent run removed the label first and posts its note, so none here",
                CLAIM_LOST: f"unblocked (rc {urc}), but a concurrent run claimed this route first and posts "
                            "its note, so none here",
                CLAIM_FAILED: f"unblocked (rc {urc}), but the one-shot claim did not land ({detail[:120]}), so "
                              "no note was posted; if it parks again this route runs again",
                CLEARED_SILENT: f"unblocked (rc {urc}), but a note did NOT post ({detail[:160]})",
            }.get(outcome, f"unblocked (rc {urc}) and requeued through apply-claude-changes.sh")
        kind = "unknown"
    if kind == "credential":
        ask = credential_ask(identifier)
        refused: list = []
        done = answered(identifier, ask, start, refused)
        if done:
            if not apply:
                return f"unprobeable credential; the founder answered {done.get('id')}; would unblock and requeue"
            # THROUGH THE ONE HELPER (PR #668 round 3, major 1). This branch
            # gated its note on "landed", which let EXIT_NOOP through, so the run
            # that LOST the unblock race posted a second "the founder answered".
            outcome, urc, detail = unblock_then_post(identifier, [
                ("progress", f"**Unblocked by capability_block_expiry.py (ASK-3960).** The founder answered the "
                 f"credential ask ({done.get('id')}, resolved by {done.get('resolved_by') or 'unnamed'} from a "
                 f"terminal): \"{(done.get('note') or 'no note given')[:300]}\". The next attempt runs with that "
                 "answer. If it parks again, the 14 days start over and a new ask is filed.", "--agent", "sana"),
                ("requeue", "--exit", "capability-route", "--why",
                 f"credential ask {done.get('id')} answered by the founder", "--agent", "sana"),
            ])
            if outcome == FAILED:
                return (f"unprobeable credential; answered, but the unblock did NOT land (rc {urc}: "
                        f"{detail[:120]}); the next run retries")
            _seen(identifier, now, apply, forget=True)
            return f"unprobeable credential; the founder answered {done.get('id')}: " + {
                NOOP: "a concurrent run removed the label first and posts the note, so none here",
                CLEARED_SILENT: f"unblocked, but a note did NOT post ({detail[:160]})",
            }.get(outcome, "unblocked and requeued")
        why = (f"; {len(refused)} resolve(s) of this ask ran outside the founder's terminal "
               f"({refused[-1].get('resolved_ctx') or 'no context recorded'}), which does not count as his answer"
               if refused else "")
        if not apply:
            return f"unprobeable credential; would add one line to the morning status list{why}"
        ok, detail = _founder_ask(identifier, ask)
        return f"unprobeable credential; {'ask listed' if ok else 'ask NOT listed'} ({detail}){why}"
    # A CAPOUT NEEDS ITS CONSUMER ON THIS TREE (PR #668 round 1, major 1). Written
    # with no cap-ladder.py to read it, the capout was a record nothing acts on and
    # the unblock sent the ticket back into the pool with no RCA. The ladder runs
    # at 04:40, after this job's 04:20, and takes rung 1 on the capout.
    if not os.path.isfile(LADDER_SCRIPT):
        return ("unprobeable, kind unknown; cap-ladder.py is not on this tree, so nothing would consume "
                "a capout: it stays parked and this job routes it once the ladder is here")
    if not apply:
        return "unprobeable, kind unknown; would hand to cap-ladder.py (capout) and unblock"
    rc = subprocess.run([sys.executable, LEDGER_SCRIPT, ATTEMPTS_FILE, "record-capout", identifier,
                         f"blocked:capability {ROUTE_AFTER_DAYS}+ days, no probe, no known capability kind"],
                        capture_output=True, text=True).returncode
    if rc != 0:
        return "unprobeable, kind unknown; the capout did NOT record, so it stays parked and the next run retries"
    # No note, so a lost race costs nothing here; it still goes through the one
    # helper, so the census can say every Linear write in this file is in one place.
    outcome, urc, detail = unblock_then_post(identifier, [])
    if outcome == FAILED:
        return (f"unprobeable, kind unknown; capout recorded, but the unblock did NOT land (rc {urc}: "
                f"{detail[:120]}); the next run retries the unblock")
    _seen(identifier, now, apply, forget=True)
    return (f"unprobeable, kind unknown; handed to cap-ladder.py (capout recorded, unblock rc {urc})"
            + ("; a concurrent run removed the label first" if outcome == NOOP else ""))

# Each returns (passed, evidence). The evidence string goes onto the Linear issue
# verbatim: "I ran X and got Y" is this repo's bar, and an unblock that says only
# "the probe passed" cannot be checked by the person reading it later.


def probe_path(value: str):
    """The capability is a file or directory that now exists."""
    target = os.path.expanduser(value)
    exists = os.path.exists(target)
    return exists, f"os.path.exists({target!r}) -> {exists}"


def probe_bin(value: str):
    """The capability is a binary on PATH."""
    found = shutil.which(value)
    return bool(found), f"shutil.which({value!r}) -> {found!r}"


def _env_fingerprint(name: str, value: str) -> str:
    """A short, non-reversing witness that a variable held a PARTICULAR value.

    Not a secret in itself: recovering the credential from 12 hex characters of
    a salted sha256 means guessing the credential, and anyone who can guess it
    already has it. What it carries is only "is this still the same string".
    """
    material = f"kipi-capability-probe\0{name}\0{value}".encode()
    return __import__("hashlib").sha256(material).hexdigest()[:12]


_FINGERPRINT = re.compile(r"^[0-9a-f]{12}$")


def probe_env(value: str):
    """The capability is a credential or setting present in the environment.

    TWO FORMS, AND THE SECOND EXISTS BECAUSE NONBLANK IS NOT WORKING
    (codex, PR #77). `env:NAME` asks "is it set". An EXPIRED credential is set.
    So a park whose whole reason was "this token no longer authenticates"
    re-tested as a pass against the unchanged environment and un-parked itself
    on the first sweep -- spending a dispatch to reach the identical wall. And
    "an expired credential" is not a corner case here; linear-worker.sh names it
    in the refusal instructions as a worked example of the capability class.

    `env:NAME@<fingerprint>` is what a park writes when the variable was ALREADY
    set at park time. It then takes a CHANGE of value, not mere presence: the
    credential was rotated, which is the event the block is actually waiting on.
    Presence still answers the other case, where the variable was genuinely
    absent when the park was written and unset -> set is real evidence.

    A ROTATION IS NOT AN ARRIVAL (codex, PR #77 round 4). The fingerprint proves
    the value CHANGED. Nothing in this process can prove the replacement
    authenticates -- pasting a second expired token rotates the value exactly as
    well as pasting a working one -- so the rotation branch returns its own
    status instead of `pass`. It still clears the block, because a rotation is
    precisely the event the park is waiting on and refusing would make the
    commonest capability block hand-clear-only again, which is the defect
    ASK-288 exists to remove. What changes is the claim: an unverified clear is
    reported and commented as unverified, and if the new credential is also dead
    the next run parks it again with a fresh fingerprint. Bounded without a cap:
    every cycle costs one human rotation, so nothing here can loop on its own.

    Reports SET/UNSET and the length, never the value. This string is posted to
    Linear, and a probe that proves a token exists by printing it is a leak.
    """
    name, sep, fingerprint = value.rpartition("@")
    if not (sep and _FINGERPRINT.match(fingerprint)):
        name, fingerprint = value, None
    raw = os.environ.get(name) or ""
    present = bool(raw.strip())
    state = "set" if present else "unset"
    if fingerprint is None:
        return present, f"os.environ[{name!r}] -> {state} (len {len(raw)})"
    if not present:
        return False, (f"os.environ[{name!r}] -> unset; the park recorded a value, "
                       f"so an unset variable is a regression, not an arrival")
    changed = _env_fingerprint(name, raw) != fingerprint
    return (ROTATED if changed else False), (
        f"os.environ[{name!r}] -> set (len {len(raw)}), "
        f"{'differs from' if changed else 'IDENTICAL to'} the value "
        f"the park refused (fingerprint {fingerprint})")


def probe_write(value: str):
    """The capability is write access to THE NAMED DIRECTORY. No parent fallback.

    Tests by create-and-remove rather than os.access: os.access answers from the
    permission bits, which is the wrong answer on a read-only mount, inside a
    container, or under any guard that intercepts the write itself. The bits are
    not the capability; writing is.

    THE PARENT IS NOT THE TARGET (codex, PR #77 round 6). This used to read
    `target if os.path.isdir(target) else os.path.dirname(target)`, so a park
    over a directory that DOES NOT EXIST YET -- which is the commonest shape of
    this kind, since a directory you can already write to is not a block --
    tested the parent instead. The parent is normally writable, so the probe
    passed at park time, and validate_recorded_probe then discarded it as
    already-passing and wrote `none`. `none` is hand-clear-only: the one probe
    kind whose capability is most often genuinely absent became the one kind
    that could never expire, which is this issue's defect wearing a fallback.

    A missing target is now a FAIL, which is the honest answer and the one that
    lets the probe be recorded: the block clears itself the run after the
    directory arrives. A target that exists and is not a directory is also a
    fail rather than a redirect to its parent -- linear-worker.sh documents this
    kind as `write:</abs/dir>`, so anything else is a probe that did not record
    what its author meant, and guessing at intent is the un-parking direction.
    """
    target = os.path.expanduser(value)
    if not os.path.isdir(target):
        return False, (f"{target} is not a directory (exists={os.path.exists(target)}) "
                       f"-- there is nothing to write into yet")
    directory = target
    stamp = os.path.join(directory, f".capability-probe-{os.getpid()}")
    if os.path.exists(stamp):
        # Never overwrite. A probe that clobbers a file to prove it can write is
        # a probe that destroys data on a name collision.
        return False, f"refused: probe file {stamp} already exists"
    try:
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write("probe")
        os.unlink(stamp)
    except OSError as exc:
        return False, f"write to {directory} -> {type(exc).__name__}: {exc}"
    return True, f"write to {directory} -> created and removed {os.path.basename(stamp)}"


PROBES = {
    "path": probe_path,
    "bin": probe_bin,
    "env": probe_env,
    "write": probe_write,
}


def run_probe(spec: str):
    """Evaluate one recorded probe. Returns (status, evidence).

    status is one of STATUSES. Only the CLEARING ones may unblock, and only
    `pass` may be reported as the capability having arrived.
    """
    spec = (spec or "").strip()
    if not spec or spec.lower() == PROBE_NONE:
        return "unprobeable", "no probe was recorded when this block was parked"
    if ":" not in spec:
        return "unknown", f"malformed probe {spec!r}: expected <kind>:<value>"
    kind, _, value = spec.partition(":")
    kind, value = kind.strip().lower(), value.strip()
    fn = PROBES.get(kind)
    if fn is None:
        return "unknown", (f"unknown probe kind {kind!r} (known: "
                           f"{', '.join(sorted(PROBES))}) -- not executed")
    if not value:
        return "unknown", f"probe {kind!r} carries no value"
    try:
        passed, evidence = fn(value)
    except Exception as exc:  # noqa: BLE1 -- fail closed on ANY probe defect
        return "fail", f"probe {spec!r} raised {type(exc).__name__}: {exc}"
    if isinstance(passed, str):
        # A probe may answer with a status of its own when "it passed" would
        # overstate what it checked. An unrecognised one is a defect in the
        # probe, and un-parking on a string this file cannot account for is the
        # unrecoverable direction, so it fails closed rather than being trusted.
        if passed not in STATUSES:
            return "unknown", (f"probe {spec!r} returned unknown status "
                               f"{passed!r} -- not trusted. {evidence}")
        return passed, evidence
    return ("pass" if passed else "fail"), evidence


def validate_recorded_probe(spec: str) -> str:
    """What a park is allowed to WRITE for this issue. Returns a probe or `none`.

    THIS RUNS AT RECORD TIME, in linear-worker.sh, and it lives here so the
    writer and the reader cannot drift: a probe validated by one set of rules
    and evaluated by another is a block that looks expirable and is not.

    A PROBE THAT ALREADY PASSES CANNOT PROVE ARRIVAL. That is the whole rule.
    If `bin:codex` passes on the machine that just refused the issue, then codex
    is on PATH and the block is about something else -- recording it un-parks
    the issue on the very next sweep, spends a dispatch, and parks it again. So
    an already-passing probe is refused and the park honestly records `none`.

    `env:` is the one kind with somewhere better to go. A credential that is
    present and expired makes the probe pass while nothing has arrived, and it
    is the most common capability block this fleet has. Rather than dropping it
    to `none` (which would make the commonest block hand-clear-only, i.e. the
    exact defect ASK-288 removes), the park records a fingerprint of the value
    it refused, and the re-test then requires a ROTATION.
    """
    spec = (spec or "").strip().splitlines()
    spec = spec[0].strip() if spec else ""
    kind, sep, value = spec.partition(":")
    kind, value = kind.strip().lower(), value.strip()
    # "-->" would close the HTML comment the marker lives in and let the rest of
    # the value escape into the rendered body, so a probe carrying one is refused
    # rather than sanitised: a probe that had to be edited to be storable is not
    # the probe the runner meant to record.
    if not (sep and kind in PROBES and value and "-->" not in spec):
        return PROBE_NONE
    normalized = f"{kind}:{value}"
    status, _ = run_probe(normalized)
    if status != "pass":
        return normalized
    if kind != "env":
        return PROBE_NONE
    if "@" in value:
        # The fingerprint suffix is the only thing allowed after an `@`, and an
        # env var name cannot contain one. A value that does is either already
        # fingerprinted or malformed; either way this park did not produce it.
        return PROBE_NONE
    return f"env:{value}@{_env_fingerprint(value, os.environ.get(value) or '')}"


# --- Linear reads ------------------------------------------------------------

# `labels{nodes{id name}}`: the id is what issueRemoveLabel and the park-time
# history lookup both name. Matching on the NAME and mutating by id keeps the
# label's display name a presentation detail.
BLOCKED_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title state{name type} project{name}
       labels{nodes{id name}}} pageInfo{hasNextPage endCursor}}}"""

# When this issue's CURRENT park started. Verified against the live API on
# 2026-08-03 (ASK-281 returned one row: addedLabelIds carrying the block label,
# createdAt 2026-08-01T20:15:06Z) rather than assumed from the schema -- a
# fixture built from my own picture of a producer is a test of the picture.
PARK_HISTORY = """query($id:String!){issue(id:$id){
 history(first:100){nodes{createdAt addedLabelIds}}}}"""

TEAM_ID_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'

# The park's own comments, and ONLY those. linear-sync.ISSUE_COMMENTS asks for
# `comments(first: 100)` with no cursor, which is right for a human reading a
# thread and wrong for this: see recorded_probe. Both the `gte` filter and the
# pageInfo shape were verified against the live API on 2026-08-11 (ASK-288
# returned 10 comments for a gte of that morning, and hasNextPage true with an
# endCursor at first:3) rather than read off the schema.
PARK_COMMENTS = """query($id:String!,$s:DateTimeOrDuration!,$a:String){issue(id:$id){
 comments(first:100,after:$a,filter:{createdAt:{gte:$s}}){
  nodes{id createdAt body} pageInfo{hasNextPage endCursor}}}}"""


def blocked_issues(ls, team_key: str, repo_project: str | None):
    """Every parked issue this checkout owns. A repo scope is REQUIRED.

    The scope check used to read `if repo_project and ...`, so an unset scope
    silently meant NO FILTER (codex, PR #77 round 3) -- the sweep listed every
    parked issue on the team and `--apply` cleared other repos' blocks from a
    checkout that cannot check any of them out. That is the inverse of what the
    filter was written for, and it is unrecoverable in the same way every other
    un-park is: the label is gone and the picker will not offer the issue again.

    Raising here rather than only in main() is deliberate: the guard belongs at
    the read that produces the issue list, so a future caller that skips the
    argument parser cannot walk around it.
    """
    if not (repo_project or "").strip():
        raise ValueError(
            "no repo scope: refusing to list parked blocks across the whole team. "
            "Pass --repo-project NAME or set $REPO_PROJECT.")
    team = ls.graphql(TEAM_ID_QUERY, {"k": team_key})["teams"]["nodes"]
    if not team:
        raise ls.LinearAPIError(f"no team with key {team_key}")
    tid = team[0]["id"]
    issues, after = [], None
    while True:
        page = ls.graphql(BLOCKED_QUERY, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    out = []
    for i in issues:
        labels = {n["name"] for n in (i.get("labels") or {}).get("nodes", [])}
        if BLOCK_LABEL not in labels:
            continue
        # SCOPED TO THIS CHECKOUT, same rule the picker uses. Unblocking an
        # issue this repo cannot check out does not restart it, it just moves
        # the stall to a queue nobody is draining. An issue with NO project is
        # not this repo either (the picker's in_this_repo comment carries the
        # same reasoning), which the inequality below already answers.
        if (i.get("project") or {}).get("name") != repo_project:
            continue
        out.append(i)
    return out


def parked_at(ls, identifier: str, block_label_id: str) -> str | None:
    """When the CURRENT park began: the last time the block label was added."""
    issue = ls.graphql(PARK_HISTORY, {"id": identifier}).get("issue")
    if not issue:
        return None
    stamps = [n.get("createdAt") for n in (issue.get("history") or {}).get("nodes") or []
              if block_label_id in (n.get("addedLabelIds") or [])]
    return max(stamps) if stamps else None


def recorded_probe(ls, identifier: str, since: str | None) -> str | None:
    """The probe THIS park recorded, or None if this park recorded nothing.

    Sorted explicitly by createdAt: linear-sync.cmd_comments carries a comment
    about Linear returning this connection newest-first, and a re-park writes a
    fresh probe that must outvote the one before it.

    SCOPED TO THE CURRENT PARK, not to the whole thread (codex, PR #77). The park
    comment is posted best-effort -- linear-worker.sh ends that call with
    `|| true`, because a park whose label landed must not be undone by a comment
    that did not. The consequence is a thread whose newest marker can belong to
    an OLDER park: a different capability, asked about in a different month,
    already cleared. It can pass. "Last marker on the thread wins" then un-parks
    an issue whose current block was never tested, and the label is gone.

    `since` is when this park started. A marker older than that describes a
    question nobody asked this time and is ignored. No `since` at all (history
    unreadable, or a label applied outside the history window) means the marker
    cannot be dated against the park, so nothing is trusted -- fail closed, the
    same direction every other ambiguity in this file takes.

    AND IT READS EVERY PAGE (codex, PR #77 round 6). This used to borrow
    linear-sync.ISSUE_COMMENTS, which asks for `comments(first: 100)` with no
    cursor. Linear serves that connection NEWEST-FIRST, so 100 comments arriving
    after a park pushed the park's own marker off the only page anyone looked
    at, and the sweep then reported a live, passing probe as "no probe recorded"
    -- parked forever, with a human the only way out. That is not a corner case
    on this board: a reviewed issue collects a park comment, a review round and
    a reply every pass, and this very issue is past 28.

    Two changes doing two different jobs. The `gte` filter is pushed to the
    SERVER so the pages walked are only the ones that can hold the marker; the
    client-side `< since` check below stays, because the trust boundary for
    what counts as this park belongs here and not in a remote filter argument.
    The cursor loop is what makes it CORRECT -- a filter alone still truncates
    at 100 when the park itself is the chatty one.
    """
    if not since:
        return None
    found = None
    for node in _park_comments(ls, identifier, since):
        for match in PROBE_MARKER.findall(node.get("body") or ""):
            found = match
    return found


# --- Linear writes -----------------------------------------------------------
# Both go through linear-sync.py rather than a second copy of the mutations.
# That file is the one writer of Linear state in this fleet; a hand-rolled
# labelIds update here would be a second read-modify-write to keep in step with
# it, which is the drift sp-53b02cc4 already records for the attempts ledger.


def _sync(*args) -> tuple[int, str]:
    """Run one linear-sync verb. Returns its EXIT CODE, not a boolean.

    A boolean collapsed `unblock`'s two success codes into one answer, which is
    the whole of the duplicate-comment defect below.
    """
    proc = subprocess.run(
        [sys.executable, str(HERE / "linear-sync.py"), *args],
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


# What clear_block did. Only CLEARED and CLEARED_SILENT removed the label, so
# only those two count as a recovery; NOOP and FAILED both mean this process
# changed nothing, for opposite reasons a reader of the log has to be able to
# tell apart. CLEARED_SILENT is a real recovery whose EVIDENCE did not land --
# see clear_block for why that is its own word and not a warning inside CLEARED.
CLEARED, CLEARED_SILENT, NOOP, FAILED = "cleared", "cleared_no_evidence", "noop", "failed"
# This run removed the label, but the route's one-shot claim went to another run
# (CLAIM_LOST) or did not land (CLAIM_FAILED). Nothing was posted either way.
CLAIM_LOST, CLAIM_FAILED = "claim_lost", "claim_failed"


def unblock_then_post(identifier: str, posts: list, claim: str = "") -> tuple[str, int, str]:
    """Remove the block label, then post the notes, ONLY when this run is the one
    writer. The one function in this file that writes to Linear.

    ONE PLACE, NOT THREE (PR #668 round 3; RCA
    q-system/output/rca/rca-capability-expiry-round-3-2026-11-09.md). Three paths
    unblocked and then posted a comment Linear cannot delete: clear_block, the
    claude-write route and the credential route. Each decided for itself when to
    post. clear_block gated on exit 0 since PR #77 round 3. The two routes gated
    on "landed" (0 or EXIT_NOOP), and EXIT_NOOP is the run that LOST the race, so
    the loser posted a second permanent note. Round 2 fixed one route, round 3
    found the other. test_capability_route.py census() reads every _sync call and
    every call of this function from the source and checks them against its
    SITES table, and races two real processes on each site.

    Posts only when both hold:
      - unblock exits 0: THIS run removed the label. linear-sync takes a host
        lock around its read-decide-write (_IssueLock), so of two racers exactly
        one gets 0 and the other gets EXIT_NOOP.
      - with a `claim`, the attempts ledger's claim-flag exits 0: the one-shot
        record across parks (attempts-ledger.py: 0 claimed here, 1 already
        claimed). Claimed only AFTER a removal, so a refused unblock never leaves
        the flag set (codex, PR #668, P2).
    REMOVE FIRST, POST SECOND: a failed removal must not leave a permanent "it
    came back" note on an issue still parked (PR #77). Every post's exit code is
    read (PR #77 round 5): one that did not land makes CLEARED_SILENT, because
    the label is off either way and only the record is missing.

    Returns (outcome, unblock rc, detail).
    """
    rc, detail = _sync("unblock", identifier, BLOCK_LABEL)
    if rc == ls_exit_noop():
        return NOOP, rc, detail
    if rc != 0:
        return FAILED, rc, detail
    if claim:
        crc = subprocess.run([sys.executable, LEDGER_SCRIPT, ATTEMPTS_FILE, "claim-flag", identifier, claim],
                             capture_output=True, text=True).returncode
        if crc == 1:
            return CLAIM_LOST, rc, detail
        if crc != 0:
            return CLAIM_FAILED, rc, f"ledger rc {crc}"
    rejected = []
    for verb, *args in posts:
        prc, pdetail = _sync(verb, identifier, *args)
        if prc != 0:
            rejected.append(f"{verb} comment REJECTED (rc {prc}): {pdetail}")
    return (CLEARED_SILENT, rc, f"{detail}; " + "; ".join(rejected)) if rejected else (CLEARED, rc, detail)


def clear_block(identifier: str, probe: str, evidence: str,
                verified: bool = True) -> tuple[str, str]:
    """Remove the block label and, ONLY on a real removal, say why it came back.

    TWO SWEEPS CAN BE IN FLIGHT (codex, PR #77 round 3). The worker runs this
    before every pick and a scheduled sweep runs it on its own clock, so two
    runs can each list the parked board, each probe, and each call unblock. One
    of them does the removal. The other's removal is a no-op -- and it used to
    exit 0 like a real one, so BOTH counted a clear and BOTH posted the
    permanent "the capability arrived" comment. The comment is the damage: a
    Linear comment cannot be deleted, so the duplicate is on the issue forever
    and the recovery reads as having happened twice.

    linear-sync now separates the two with EXIT_NOOP, so the caller stops
    guessing. The overlapping half -- both sweeps inside linear-sync's own
    read-decide-write together, both answered success -- is closed there too
    (round 4), by a host lock around that critical section; see _IssueLock.

    `verified` is the difference between "the capability arrived" and "the thing
    the park was waiting on changed". Only a probe that tested the capability
    itself may claim the first. See probe_env: a rotated credential is a real
    reason to retry and is not evidence that the new credential works.
    """
    # The comment is how a reader learns why the issue reappeared. Posted only
    # on a state CHANGE -- a re-test that changes nothing must not write a
    # comment, or a 15-minute loop becomes a comment every 15 minutes on an
    # object whose comments cannot be deleted. For the same reason the headline
    # must be true the first time: there is no editing it later.
    if verified:
        note = (
            f"**The capability arrived. Un-parked automatically.** `{BLOCK_LABEL}` removed; "
            f"the picker offers this issue again on the next run.\n\n"
            f"Recorded probe: `{probe}`\n\n"
            f"**Next:** normal dispatch. No founder action, no capability grant pending. "
            f"If the block is still real, the run will park it again with a fresh probe."
        )
    else:
        note = (
            f"**The blocked precondition changed. Un-parked automatically, UNVERIFIED.** "
            f"`{BLOCK_LABEL}` removed; the picker offers this issue again on the next run.\n\n"
            f"Recorded probe: `{probe}`\n\n"
            f"**What was checked:** the value this park refused is no longer the value "
            f"in the environment. That is the event this block was waiting on. It is "
            f"**not proof** the replacement works -- nothing here can authenticate a "
            f"credential on the runner's behalf.\n\n"
            f"**Next:** normal dispatch. If the new value is dead too, the run parks it "
            f"again with a fresh fingerprint and no human is in the path either way."
        )
    # THE COMMENT'S EXIT CODE IS READ (codex, PR #77 round 5): a rejected
    # commentCreate left the issue un-parked with NO record of which probe
    # cleared it, reported as an ordinary recovery. The removal still counts (the
    # label did come off, and a second sweep would find it gone and never
    # comment), so the missing evidence gets its own word, CLEARED_SILENT, which
    # travels into the run line and the summary. The order (remove, then post)
    # and the read of every exit code live in unblock_then_post.
    outcome, _rc, detail = unblock_then_post(identifier, [
        ("progress", note, "--agent", "capability-expiry", "--evidence", f"{probe} -> {evidence}"),
    ])
    return outcome, detail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-project", default=os.environ.get("REPO_PROJECT") or None,
                    help="only re-test blocks in this Linear project (default $REPO_PROJECT)")
    ap.add_argument("--dispatch-targets", action="store_true",
                    help="re-test every repo the dispatcher enters (the nightly job passes this)")
    ap.add_argument("--team", default="ASK", help="Linear team key (default ASK)")
    ap.add_argument("--apply", action="store_true",
                    help="actually clear the blocks that pass; dry without it")
    args = ap.parse_args(argv)

    # Refused BEFORE the first API call, and refused for a dry run too. A dry
    # run that prints "ASK-906 WOULD BE CLEARED" for another repo's issue is a
    # lie about what --apply does, and the operator plans against the dry output.
    projects = dispatch_projects() if args.dispatch_targets else [args.repo_project]
    if args.dispatch_targets and not projects:
        print("BLOCK: --dispatch-targets found no dispatch-enabled project in the registry "
              "or ~/.config/kipi/dispatch-targets.json", file=sys.stderr)
        return EXIT_USAGE
    if not args.dispatch_targets and not (args.repo_project or "").strip():
        print("BLOCK: no repo scope. This sweep clears blocks for ONE checkout; "
              "with no scope it would clear every parked block on team "
              f"{args.team}, including issues no runner here can check out. "
              "Pass --repo-project NAME or set $REPO_PROJECT "
              "(linear-worker.sh sets it from the checkout).", file=sys.stderr)
        return EXIT_USAGE

    ls = _load_linear_sync()
    try:
        parked = [i for proj in projects for i in blocked_issues(ls, args.team, proj)]
    except ls.LinearAPIError as exc:
        print(f"INFRA: linear unreachable ({exc}). No block was re-tested.", file=sys.stderr)
        return EXIT_INFRA
    except Exception as exc:  # noqa: BLE1
        print(f"BLOCK: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    counts = {"pass": 0, ROTATED: 0, "fail": 0, "unprobeable": 0, "unknown": 0,
              "cleared": 0, "cleared_unverified": 0, "already_cleared": 0,
              "cleared_without_evidence": 0, "unblock_failed": 0}
    if not parked:
        print(f"capability-expiry: no issue parked at {BLOCK_LABEL}"
              + (f" in {args.repo_project}" if args.repo_project else ""))
        return EXIT_OK

    for issue in parked:
        ident = issue["identifier"]
        block_label_id = next(
            (n["id"] for n in (issue.get("labels") or {}).get("nodes", [])
             if n.get("name") == BLOCK_LABEL), None)
        try:
            probe = recorded_probe(ls, ident, parked_at(ls, ident, block_label_id))
        except ls.LinearAPIError as exc:
            # One unreadable thread does not stop the sweep: the other blocks
            # are still worth re-testing, and a whole run lost to one bad read
            # is a loop that stops recovering for a reason nobody sees.
            print(f"capability-expiry: {ident} comments unreadable ({exc}) -- left parked")
            counts["fail"] += 1
            continue
        status, evidence = run_probe(probe if probe is not None else PROBE_NONE)
        counts[status] = counts.get(status, 0) + 1

        if status == "unprobeable":
            print(f"capability-expiry: {ident} "
                  + route_unprobeable(ls, ident, parked_at(ls, ident, block_label_id), args.apply,
                                      state_type=(issue.get("state") or {}).get("type") or ""))
            continue
        if status not in CLEARING:
            reason = {"unprobeable": "no recorded probe -- stays parked, nothing to re-test",
                      "unknown": "probe not runnable -- stays parked (fail closed)",
                      "fail": "still blocked"}[status]
            print(f"capability-expiry: {ident} {reason} [{evidence}]")
            continue

        # A rotation clears, but it is never called a pass. The word travels
        # into the dry-run line, the run log and the permanent Linear comment,
        # and an operator plans against all three.
        verified = status == "pass"
        verdict = "passed" if verified else "changed (UNVERIFIED)"
        if not args.apply:
            print(f"capability-expiry: {ident} WOULD BE CLEARED "
                  f"(probe `{probe}` {verdict}: {evidence}) -- dry, use --apply")
            continue
        outcome, detail = clear_block(ident, probe, evidence, verified=verified)
        if outcome in (CLEARED, CLEARED_SILENT):
            # Both removed the label, so both are recoveries. The one that lost
            # its comment is ALSO counted apart, because "this issue came back"
            # and "this issue came back and says why" are different states and
            # only the second one can be audited later from the issue itself.
            counts["cleared" if verified else "cleared_unverified"] += 1
            if outcome == CLEARED_SILENT:
                counts["cleared_without_evidence"] += 1
                print(f"capability-expiry: {ident} CLEARED but its recovery comment "
                      f"did NOT post ({detail}) -- the issue is un-parked with no "
                      f"record of the probe `{probe}` that cleared it")
            else:
                print(f"capability-expiry: {ident} CLEARED -- probe `{probe}` {verdict} ({evidence})")
        elif outcome == NOOP:
            # A concurrent sweep got there first. Reported, never counted: the
            # recovery is real but it is not THIS run's, and a count that adds
            # both sweeps says two blocks lifted when one did.
            counts["already_cleared"] += 1
            print(f"capability-expiry: {ident} already un-parked by a concurrent "
                  f"sweep ({detail}) -- no second recovery comment posted")
        else:
            # Same reasoning as the worker's failed-label branch: if the write
            # did not land, the issue is still parked and saying "cleared" would
            # report a recovery that did not happen.
            #
            # AND IT IS COUNTED (codex, PR #77 round 6). This branch used to
            # print and nothing else: no counter, absent from `still_blocked`,
            # and the process exited 0. So the one outcome that means "the
            # recovery path itself is broken" was the one outcome invisible to
            # every reader downstream of the line -- a run whose summary added
            # up and whose exit code said healthy. An unattended job reporting
            # its own failure as success is the same shape as the never-expiring
            # block: real state, nobody notified, no next actor.
            counts["unblock_failed"] += 1
            print(f"capability-expiry: {ident} probe passed but the unblock did NOT "
                  f"apply ({detail}) -- still parked")

    print("capability-expiry: " + json.dumps({
        "parked": len(parked),
        "cleared": counts["cleared"],
        # Reported separately, never folded in: a reader asking "how many blocks
        # lifted on evidence" gets a different number from "how many lifted
        # because a precondition moved", and one total cannot answer both.
        "cleared_unverified": counts["cleared_unverified"],
        # A SUBSET of the two counts above, not a fourth bucket: these issues
        # were un-parked and carry no comment saying why. A reader auditing the
        # board from Linear alone will find nothing on them.
        "cleared_without_evidence": counts["cleared_without_evidence"],
        "already_cleared": counts["already_cleared"],
        # Probe-failed PLUS removal-refused. Both leave the label on the issue,
        # and a reader asking "how many are still parked" is asking about the
        # BOARD, not about which step fell over. Leaving the refused ones out
        # made the summary add up to a healthier board than Linear held.
        "still_blocked": counts["fail"] + counts["unblock_failed"],
        # ...and named apart, because it is the only still-blocked this process
        # is responsible for: the probe said the capability is there and the
        # write did not land.
        "unblock_failed": counts["unblock_failed"],
        "unprobeable": counts["unprobeable"],
        "unrunnable_probe": counts["unknown"],
        "applied": bool(args.apply),
    }))
    # A refused removal is the recovery path failing, so the process says so in
    # the only field a supervisor reads without parsing. Probe failures are NOT
    # in here: "the capability still is not there" is this job working.
    return EXIT_PARTIAL if counts["unblock_failed"] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
