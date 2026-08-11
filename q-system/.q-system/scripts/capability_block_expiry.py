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
still cannot do. That class has no probe: the park records `none`, this script
reports it as unprobeable, and it stays parked. Reporting an unprobeable block
every run is the correct outcome, not a gap to paper over with a guess.

Usage:
  capability_block_expiry.py [--repo-project NAME] [--apply] [--team ASK]
Dry by default: says what it would clear and mutates nothing.
"""
from __future__ import annotations

import argparse
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
    nodes, after, seen_cursors = [], None, set()
    while True:
        conn = ((ls.graphql(PARK_COMMENTS, {"id": identifier, "s": since, "a": after})
                 .get("issue") or {}).get("comments")) or {}
        nodes += conn.get("nodes") or []
        info = conn.get("pageInfo") or {}
        cursor = info.get("endCursor")
        # Normal exit is hasNextPage. The other two guards are for the ways a
        # remote connection hands back a loop with no end -- a missing cursor,
        # or one that stops advancing -- and this runs unattended before every
        # pick, where a spin costs the whole pick rather than one issue.
        if not info.get("hasNextPage") or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        after = cursor
    nodes.sort(key=lambda n: n.get("createdAt") or "")
    found = None
    for node in nodes:
        if (node.get("createdAt") or "") < since:
            continue
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
    rc, detail = _sync("unblock", identifier, BLOCK_LABEL)
    if rc == ls_exit_noop():
        return NOOP, detail
    if rc != 0:
        return FAILED, detail
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
    # THE COMMENT'S EXIT CODE IS READ (codex, PR #77 round 5). It used to be
    # discarded, so a rejected commentCreate -- which linear-sync already
    # detects and exits nonzero on -- left the issue un-parked with NO record of
    # which probe cleared it. The recorded probe is the only evidence the
    # un-park was legitimate, and the run still reported an ordinary recovery:
    # silent loss of the only durable evidence, counted as success.
    #
    # The removal still counts. The label really did come off and the picker
    # will offer the issue again; reporting no recovery would be the opposite
    # lie, and it would also strand the issue -- a second sweep finds the label
    # already gone (NOOP) and never comments either. What changes is that the
    # missing evidence gets its own word, which travels into the run line and
    # the summary.
    #
    # ORDER IS DELIBERATE: remove first, comment second. Commenting first would
    # mean a failed removal leaves a permanent "the capability arrived" comment
    # on an issue that is still parked -- a false claim that cannot be deleted,
    # which is worse than a true recovery with no note attached.
    note_rc, note_detail = _sync("progress", identifier, note,
                                 "--agent", "capability-expiry",
                                 "--evidence", f"{probe} -> {evidence}")
    if note_rc != 0:
        return CLEARED_SILENT, f"{detail}; recovery COMMENT REJECTED: {note_detail}"
    return CLEARED, detail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-project", default=os.environ.get("REPO_PROJECT") or None,
                    help="only re-test blocks in this Linear project (default $REPO_PROJECT)")
    ap.add_argument("--team", default="ASK", help="Linear team key (default ASK)")
    ap.add_argument("--apply", action="store_true",
                    help="actually clear the blocks that pass; dry without it")
    args = ap.parse_args(argv)

    # Refused BEFORE the first API call, and refused for a dry run too. A dry
    # run that prints "ASK-906 WOULD BE CLEARED" for another repo's issue is a
    # lie about what --apply does, and the operator plans against the dry output.
    if not (args.repo_project or "").strip():
        print("BLOCK: no repo scope. This sweep clears blocks for ONE checkout; "
              "with no scope it would clear every parked block on team "
              f"{args.team}, including issues no runner here can check out. "
              "Pass --repo-project NAME or set $REPO_PROJECT "
              "(linear-worker.sh sets it from the checkout).", file=sys.stderr)
        return EXIT_USAGE

    ls = _load_linear_sync()
    try:
        parked = blocked_issues(ls, args.team, args.repo_project)
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
