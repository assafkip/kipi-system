#!/usr/bin/env python3
"""Agent claim-lock: refuse an issue that another agent session is already working.

Two agent sessions sharing one checkout overwrite each other's working tree
(2026-07-26: commit 53f2eeb came from a different session in this same checkout;
the collision was only noticed afterwards, by hand).

WHY THIS IS TWO HALVES
----------------------
A Python script cannot reach the Linear MCP server -- the reason
`linear-queue.py` (queue-and-drain) exists. So "set In Progress AND attach
`claimed:<agent>`" cannot be one script call. The split:

  * LOCAL LOCK  -- this file. One working tree, N sessions. The Linear label
    structurally CANNOT see this case: two sessions in one checkout share one
    MCP user and one label set, so only a local file tells them apart.
  * REMOTE CLAIM -- the agent performs the MCP write. The REFUSAL DECISION
    still lives here: the agent passes the `mcp__linear__get_issue` response as
    `--remote-state` and this script refuses on it.

THE RESOURCE IS THE WORKING TREE, NOT THE ISSUE
-----------------------------------------------
Two sessions in one checkout stomp each other's files even on different issues,
so there is one active claim per tree.

IDENTITY IS (agent, session), NEVER agent ALONE
-----------------------------------------------
Scar, found by adversarial review 2026-07-26: with `--agent` as the whole
identity, two Claude sessions in one checkout that both call themselves "claude"
were BOTH granted -- the exact two-sessions-one-checkout case this lock exists
to stop, and the likely case rather than the edge case. So a session token is
required and it, not the display name, decides collisions.

A pid cannot serve as that token: this is a CLI that exits immediately after
writing the lock, so the recorded pid is a dead process within milliseconds.
The token comes from the session's own environment.

THE HOLDER'S LIVENESS IS A SEPARATE, OPTIONAL FIELD (ASK-189)
-------------------------------------------------------------
Because the session token says WHO holds the tree but nothing says whether that
holder still exists, a killed session leaked its claim forever. Measured twice
2026-07-27: a run was SIGKILLed, the claim stayed held by a session with zero
processes alive, and a human had to run `release --holder`. SIGKILL cannot be
trapped, so no in-process cleanup can ever close this -- the lock must be able
to tell ON READ that its holder is gone.

The caller therefore names a process that lives for the WHOLE run via
`--holder-pid` (linear-worker.sh passes its own `$$`). That is the piece that was
missing: not that pids are useless here, but that nothing long-lived was ever
written down.

The direction of doubt is one-way and load-bearing: a reclaim happens only on
POSITIVE PROOF of death. A missing field, an unreadable `ps`, a permission error
-- anything unknown -- reads as ALIVE and the claim stands. Leaking a lock wedges
a board and a human notices; reclaiming a LIVE holder's tree hands two workers
the same files, which is scar 53f2eeb and nobody notices.

FAIL CLOSED, EVERYWHERE
-----------------------
A mutex that grants under doubt is worse than none, because callers trust it.
Unreadable lock -> refuse. Unrecognized `--remote-state` shape -> refuse.
Cannot identify the working tree -> refuse (never fall back to cwd: that
invents a per-directory resource and grants every session).

Exit codes, shared with linear-sync.py so callers can branch:
  0 ok   1 usage   3 collision (a refusal, NOT a crash)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_COLLISION = 3

CLAIM_LABEL_PREFIX = "claimed:"
# Linear's statusType vocabulary. `started` is the one that means someone is on
# it. Prefer this over the status NAME: workflow state names are customizable
# per team, so matching "In Progress" as a string breaks on any team that
# renamed it.
STARTED_STATUS_TYPES = ("started",)
# Fallback only, for a snapshot that carries a name but no statusType.
STARTED_STATUS_NAMES = ("in progress", "in review")

GUARD_TIMEOUT_SECONDS = 5.0
# `ps` is a local read that normally returns in milliseconds. The bound exists so
# a wedged process table can never hang the mutex; a timeout reads as "unknown",
# which reads as alive.
PS_TIMEOUT_SECONDS = 5.0

# `ps -o lstart=` renders the start time in the READING process's timezone and
# locale. The write and the read are different processes, hours apart, so an
# unpinned render turned a LIVE holder into "the pid was recycled" the moment the
# system timezone moved -- macOS sets the zone automatically and a laptop that
# travels flips it. That is the mutex handing a live worker's tree to a second
# worker, which is scar 53f2eeb and the one direction this feature must never go.
# Measured 2026-07-27, one pid, same instant:
#   TZ=UTC        -> 'Tue Jul 28 01:52:53 2026'
#   TZ=Asia/Tokyo -> 'Tue Jul 28 10:52:53 2026'
# Both the write and the read go through _proc_snapshot, so pinning it in one
# place is what keeps the two sides of the comparison rendering identically.
_PS_ENV = {**os.environ, "TZ": "UTC", "LC_ALL": "C"}

# THE KEY CARRIES ITS FORMAT, because the format changed once. Records written
# before the pin above hold a LOCAL-time render under the old name
# `holder_pid_start`; comparing one of those against a UTC render says "recycled
# pid" about a holder that is alive and working -- this fix causing the exact
# defect it fixes, for the length of the upgrade window (a `kipi update` can
# replace this script while a claim is held). Under a new name an old record
# simply has no recorded start time, which already reads as unknown, which reads
# as alive. Downgrade is safe for the same reason, in the other direction.
HOLDER_START_KEY = "holder_pid_start_utc"


class CorruptLock(Exception):
    """The lock exists but cannot be understood. Callers refuse, never grant."""


class RemoteShapeError(Exception):
    """The remote snapshot is not a shape we recognize, so it cannot be judged.

    Raised rather than skipped. Silently ignoring an unknown label or status
    shape is how a gate reports success while checking nothing -- and the whole
    remote half of this lock is that one check.
    """


class TreeUnknown(Exception):
    """The working tree could not be identified, so there is no resource to lock."""


def working_tree_root() -> str:
    """The tree being protected: the CALLER's, resolved at runtime.

    Deliberately NOT derived from __file__. `kipi` invokes fleet scripts out of
    $KIPI_HOME (the skeleton), so a __file__-derived path would lock the
    SKELETON no matter which instance the agent works in.

    Raises TreeUnknown rather than falling back to os.getcwd(). Scar, found by
    adversarial review 2026-07-26: the cwd fallback fired whenever git failed
    (dubious ownership under another uid, git absent, a non-repo cwd) and then
    handed out ONE LOCK PER SUBDIRECTORY of a single tree -- every session won.
    A mutex that cannot identify its resource must refuse.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise TreeUnknown(f"git could not be executed: {exc}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or "").strip().splitlines()
        raise TreeUnknown(
            "`git rev-parse --show-toplevel` failed"
            + (f": {detail[0]}" if detail else " (not a git working tree)")
        )
    return result.stdout.strip()


def claims_path() -> str:
    """Single source for the lock location.

    KIPI_LINEAR_CLAIMS exists so the suite never touches the live lock -- the
    same override discipline as KIPI_LINEAR_LEDGER and KIPI_LINEAR_QUEUE.
    """
    override = os.environ.get("KIPI_LINEAR_CLAIMS")
    if override:
        return override
    return os.path.join(working_tree_root(), ".linear-claims.json")


def session_token(explicit: str | None) -> str | None:
    """What actually discriminates two sessions in one checkout.

    Order: --session, then the session id the runtime exports. Returns None when
    nothing identifies this session, and the caller then refuses: an anonymous
    claim cannot be distinguished from another session's, which is the defect
    this exists to close.
    """
    if explicit:
        return explicit
    for var in ("KIPI_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = os.environ.get(var)
        if value:
            return value
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except (OverflowError, ValueError, TypeError):
        return False
    return True


def _proc_snapshot(pid: int) -> tuple[str, str] | None:
    """(start_time, state) for `pid` as `ps` sees it, or None when it cannot say.

    `lstart` is the process's ABSOLUTE start time, which is what distinguishes
    the recorded holder from an unrelated process that later inherited its pid.
    `state` is here because a SIGKILLed process stays a ZOMBIE until its parent
    reaps it, and `os.kill(pid, 0)` succeeds on a zombie -- so the pid check
    alone reads a killed holder as alive for as long as nobody waits on it.

    The environment is PINNED (`_PS_ENV`): `lstart` is rendered in the reading
    process's timezone, and the writer and the reader are different processes.

    None on any doubt (ps missing, non-zero, unparseable, slow). Callers must
    treat None as "cannot prove death", never as death.
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "lstart=,state="],
            capture_output=True,
            text=True,
            check=False,
            timeout=PS_TIMEOUT_SECONDS,
            env=_PS_ENV,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().rsplit(None, 1)
    if len(parts) != 2 or not parts[0].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def holder_death_reason(record: dict) -> str | None:
    """Why this claim's holder is PROVABLY gone, or None when it must be respected.

    The one-way doubt rule from the module docstring is implemented here and
    nowhere else: every path that cannot prove death returns None.
    """
    pid = record.get("holder_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None  # no long-lived holder was ever recorded; respect the claim
    if not _pid_alive(pid):
        return f"holder process {pid} no longer exists"
    snapshot = _proc_snapshot(pid)
    if snapshot is None:
        return None  # ps could not answer, and silence is not proof
    started, state = snapshot
    if state.upper().startswith("Z"):
        return f"holder process {pid} was killed and is a zombie awaiting reap"
    recorded_start = record.get(HOLDER_START_KEY)
    if isinstance(recorded_start, str) and recorded_start and recorded_start != started:
        return (
            f"pid {pid} now belongs to a process started {started!r}, not the "
            f"holder recorded at {recorded_start!r} (the pid was recycled)"
        )
    return None


def holder_fields(pid: int | None) -> dict:
    """The liveness fields to store for a claim, empty when no holder was named.

    Empty is the correct answer for a caller that has nothing long-lived to
    point at, and it is why THIS process never records its own pid: the CLI
    exits milliseconds after writing the lock, so a self-recorded pid would make
    every claim instantly reclaimable -- the mutex disabled outright.

    A pid whose start time cannot be read is still recorded, with no start key.
    That is strictly better than recording nothing: `_pid_alive` alone still
    catches the plain "holder is gone" case, and the absent key only costs the
    recycling refinement.
    """
    if pid is None:
        return {}
    fields: dict = {"holder_pid": pid}
    snapshot = _proc_snapshot(pid)
    if snapshot is not None:
        fields[HOLDER_START_KEY] = snapshot[0]
    return fields


# ---------------------------------------------------------------------------
# Lock file


def read_claim() -> dict | None:
    path = claims_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError as exc:
        raise CorruptLock(f"cannot read {path}: {exc}") from exc
    if not text:
        return None
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptLock(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(record, dict) or not record.get("agent"):
        raise CorruptLock(f"{path} does not hold a claim record")
    return record


def write_claim(record: dict | None) -> None:
    """Replace the lock atomically, or remove it when `record` is None."""
    path = claims_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if record is None:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        # A crash between write and replace used to leave .tmp.<pid> forever.
        if os.path.exists(tmp):
            os.remove(tmp)


def sweep_tmp_files() -> None:
    """Remove leftover .tmp.<pid> files whose writer is gone.

    Only ever runs inside the critical section, so a live writer's temp file
    cannot be swept out from under it.
    """
    for leftover in glob.glob(f"{claims_path()}.tmp.*"):
        suffix = leftover.rsplit(".", 1)[-1]
        try:
            pid = int(suffix)
        except ValueError:
            continue
        if not _pid_alive(pid):
            try:
                os.remove(leftover)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Critical section


class _CriticalSection:
    """O_EXCL guard so two concurrent claims cannot both read "free" and win.

    Without it, check-then-write is a TOCTOU race -- the two-sessions-racing
    case this lock exists to stop.

    The guard records the holder's pid, and unlike the claim itself that pid IS
    meaningful: the guard is only ever held while a process sits inside the
    section. Scar, adversarial review 2026-07-26: a claimant SIGKILLed inside
    the section leaked the guard and bricked the tree permanently -- every claim
    and release burned the timeout then refused, forever, with --break-stale
    unreachable behind the very thing that was stuck. So a guard whose writer is
    dead is reclaimable.

    __exit__ removes the guard only when WE still own it. Blind removal let a
    second process enter while the first was still inside.
    """

    def __init__(self, timeout: float = GUARD_TIMEOUT_SECONDS) -> None:
        self.guard = f"{claims_path()}.guard"
        self.timeout = timeout
        self.token = f"{os.getpid()}:{time.time()}"

    def _read_guard_pid(self) -> int | None:
        try:
            with open(self.guard, encoding="utf-8") as fh:
                return int(fh.read().split(":")[0])
        except (OSError, ValueError, IndexError):
            return None

    def __enter__(self) -> "_CriticalSection":
        os.makedirs(os.path.dirname(self.guard) or ".", exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as fh:
                    fh.write(self.token)
                return self
            except FileExistsError:
                holder = self._read_guard_pid()
                if holder is not None and not _pid_alive(holder):
                    # The writer is gone; the guard is debris, not a lock.
                    try:
                        os.remove(self.guard)
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise CorruptLock(
                        f"another live process ({holder}) has held {self.guard} "
                        f"for more than {self.timeout}s; refusing rather than "
                        "barging into the critical section"
                    ) from None
                time.sleep(0.05)

    def __exit__(self, *_exc) -> None:
        try:
            with open(self.guard, encoding="utf-8") as fh:
                if fh.read() != self.token:
                    return  # someone else owns it now; not ours to remove
        except OSError:
            return
        try:
            os.remove(self.guard)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Remote snapshot


def _label_names(raw) -> list[str]:
    """Label names from either shape Linear emits, refusing anything else."""
    if raw is None:
        return []
    if isinstance(raw, dict) and isinstance(raw.get("nodes"), list):
        raw = raw["nodes"]
    if not isinstance(raw, list):
        raise RemoteShapeError(f"`labels` is {type(raw).__name__}, not a list")
    names: list[str] = []
    for item in raw:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        else:
            raise RemoteShapeError(
                f"a label entry is {type(item).__name__} with no usable name"
            )
    return names


def _person_name(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("name", "displayName", "email"):
            if isinstance(raw.get(key), str):
                return raw[key].strip()
        raise RemoteShapeError("assignee object carries no name/displayName/email")
    raise RemoteShapeError(f"assignee is {type(raw).__name__}")


def _is_started(remote: dict) -> bool:
    """Whether the snapshot says someone has started, refusing if it cannot tell.

    Prefers `statusType` ("started"), the stable vocabulary, over the status
    NAME, which teams rename freely. An empty snapshot raises rather than
    reading as "not started" -- an agent whose MCP fetch failed must not get a
    clean claim out of it.
    """
    status_type = remote.get("statusType")
    if isinstance(status_type, str) and status_type.strip():
        return status_type.strip().lower() in STARTED_STATUS_TYPES
    status = remote.get("status")
    if isinstance(status, dict):
        for key in ("type", "name"):
            if isinstance(status.get(key), str):
                status = status[key]
                break
    if isinstance(status, str) and status.strip():
        return status.strip().lower() in STARTED_STATUS_NAMES
    raise RemoteShapeError(
        "snapshot carries neither `statusType` nor a usable `status`; "
        "cannot tell whether the issue is already started"
    )


def remote_collision(remote: dict, agent: str) -> str | None:
    """Why the REMOTE state refuses this agent, or None when it is free.

    Reads the verbatim `mcp__linear__get_issue` response. Scar, adversarial
    review 2026-07-26: this read `state`, a key the MCP never emits (it emits
    `status` + `statusType`), so the check silently evaluated None and GRANTED
    every time -- while a hand-rolled test fixture using the invented key stayed
    green. The remote half is the ONLY cover for a collision across checkouts,
    so it was the one gate that had to work and the one that did nothing.
    """
    for label in _label_names(remote.get("labels")):
        if label.startswith(CLAIM_LABEL_PREFIX):
            holder = label[len(CLAIM_LABEL_PREFIX):]
            if holder != agent:
                return f"Linear already carries `{label}`"
    if _is_started(remote):
        assignee = _person_name(remote.get("assignee"))
        if assignee != agent:
            who = assignee or "an unnamed user"
            label = remote.get("status") or remote.get("statusType")
            return f"Linear shows it {label!r} under {who}"
    return None


def load_remote(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RemoteShapeError("--remote-state must contain a JSON object")
    return data


# ---------------------------------------------------------------------------
# Commands


def _describe(held: dict) -> str:
    return (
        f"{held.get('agent')} (session {held.get('session')}) on "
        f"{held.get('issue_id')} since {held.get('acquired_at')}"
    )


def cmd_claim(args: argparse.Namespace) -> int:
    session = session_token(args.session)
    if not session:
        sys.stderr.write(
            "--session is required (or export KIPI_SESSION_ID / CLAUDE_SESSION_ID).\n"
            "The display name alone is NOT an identity: two sessions in one "
            "checkout that both call themselves the same thing would both be "
            "granted, which is the exact collision this lock exists to stop.\n"
        )
        return EXIT_USAGE

    with _CriticalSection():
        sweep_tmp_files()
        held = read_claim()

        if held is not None:
            same_session = held.get("session") == session
            if same_session:
                held.update(
                    issue_id=args.issue_id, refreshed_at=_now_iso(), agent=args.agent
                )
                # Refresh liveness too, so a long run's record keeps describing a
                # process that is really there. A re-claim that names no holder
                # leaves the recorded one alone rather than dropping to "no
                # liveness" -- same direction of doubt as everywhere else.
                held.update(holder_fields(args.holder_pid))
                write_claim(held)
                print(f"already held by this session: {args.issue_id}")
                return EXIT_OK

            gone = holder_death_reason(held)
            if gone is not None:
                # Said out loud, on stderr, every time. A mutex that silently
                # hands a resource from one holder to another is indistinguishable
                # from a mutex that never worked, and the operator debugging a
                # two-workers-one-tree collision has to be able to see this line.
                sys.stderr.write(
                    f"RECLAIMED: the claim held by {_describe(held)} is stale -- "
                    f"{gone}. Taking the tree; no --break-stale needed.\n"
                )
                held = None

        if held is not None:
            if args.break_stale:
                # Compare-and-swap, not a blind steal. Scar, adversarial review
                # 2026-07-26: --break-stale took a demonstrably LIVE claim on
                # the tool's own advice, and two agents could ping-pong it. The
                # breaker must name the exact holder it looked at, so it cannot
                # break a claim that changed underneath it.
                if args.holder != held.get("session"):
                    sys.stderr.write(
                        "REFUSED: --break-stale needs --holder <session> naming the "
                        f"claim you looked at. This tree is held by {_describe(held)}. "
                        f"Re-run with --holder {held.get('session')} if that session "
                        "is genuinely dead.\n"
                    )
                    return EXIT_COLLISION
                sys.stderr.write(f"WARNING: breaking the claim held by {_describe(held)}\n")
            else:
                sys.stderr.write(
                    f"REFUSED: this working tree is claimed by {_describe(held)}. "
                    "Two sessions in one checkout overwrite each other's files even "
                    "on different issues, so the tree is the resource. Use a separate "
                    "git worktree, have that session release it, or -- only if it is "
                    f"genuinely dead -- pass --break-stale --holder {held.get('session')}.\n"
                )
                return EXIT_COLLISION

        if args.remote_state:
            try:
                remote = load_remote(args.remote_state)
                reason = remote_collision(remote, args.agent)
            except (OSError, json.JSONDecodeError) as exc:
                sys.stderr.write(f"--remote-state unreadable: {exc}\n")
                return EXIT_USAGE
            except RemoteShapeError as exc:
                # Fail closed: an unrecognized shape means the gate cannot judge,
                # and a gate that cannot judge must not grant.
                sys.stderr.write(
                    f"REFUSED: --remote-state is not a shape this can judge ({exc}). "
                    "Pass the verbatim mcp__linear__get_issue response.\n"
                )
                return EXIT_COLLISION
            if reason is not None:
                sys.stderr.write(
                    f"REFUSED: {reason}. Claiming it would take work another agent "
                    "has already started.\n"
                )
                return EXIT_COLLISION

        write_claim(
            {
                "issue_id": args.issue_id,
                "agent": args.agent,
                "session": session,
                "acquired_at": _now_iso(),
                **holder_fields(args.holder_pid),
            }
        )
        print(f"claimed {args.issue_id} for {args.agent} (session {session})")
        return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    session = session_token(args.session)
    if not session:
        sys.stderr.write("--session is required (or export KIPI_SESSION_ID).\n")
        return EXIT_USAGE
    with _CriticalSection():
        held = read_claim()
        if held is None:
            print(f"not held: {args.issue_id}")
            return EXIT_OK
        if held.get("session") != session:
            sys.stderr.write(
                f"REFUSED: this session does not hold the tree; {_describe(held)} does. "
                "An agent releasing another's claim is how the lock silently stops "
                "working.\n"
            )
            return EXIT_COLLISION
        if held.get("issue_id") != args.issue_id:
            # Asymmetric with claim otherwise: release ignored its issue_id and
            # dropped the lock for whatever was held.
            sys.stderr.write(
                f"REFUSED: this tree holds {held.get('issue_id')}, not "
                f"{args.issue_id}. Release the issue that is actually held.\n"
            )
            return EXIT_COLLISION
        write_claim(None)
        print(f"released {held.get('issue_id')} held by {held.get('agent')}")
        return EXIT_OK


def cmd_status(_args: argparse.Namespace) -> int:
    held = read_claim()
    if held is None:
        print("no claim held in this working tree")
        return EXIT_OK
    line = f"{held.get('issue_id')} claimed by {_describe(held)}"
    # `status` is what a human runs on a board that looks wedged. Reporting a
    # provably-dead holder as a live claim is the REPORT contradicting the
    # detector: `claim` reclaims that same record one line later. The fix landing
    # on the detector alone would leave the operator reading the wrong answer
    # from the one command they actually type.
    #
    # APPENDED, never substituted, and the exit code stays 0: the existing text
    # has a reader (test-linear-claim.sh case 20 pulls the session token out of
    # this line with sed), and a rewritten line or a new non-zero exit would
    # break callers while every assertion about staleness still passed. This
    # tells the truth; it does not become a new gate.
    gone = holder_death_reason(held)
    if gone is not None:
        line += f" [STALE: {gone} -- the next claim will reclaim this tree]"
    print(line)
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("claim", help="claim this working tree BEFORE branching")
    p.add_argument("issue_id")
    # Validated by hand, not required=True: argparse exits 2 on a missing
    # required arg, and 2 is not this tool's vocabulary. A usage error must stay
    # distinguishable from a refusal (3).
    p.add_argument("--agent", help="human-readable actor name")
    p.add_argument("--session", help="unique session token; what decides collisions")
    p.add_argument("--remote-state", help="verbatim mcp__linear__get_issue response")
    p.add_argument("--break-stale", action="store_true", help="requires --holder")
    p.add_argument("--holder", help="the session token you are deliberately breaking")
    # Deliberately NOT type=int: argparse exits 2 on a bad value, and 2 is not
    # this tool's vocabulary -- same reason --agent is validated by hand below.
    p.add_argument(
        "--holder-pid",
        help="pid of a process that lives for the WHOLE run (the worker shell's "
        "$$), so a killed holder's claim can be reclaimed on read",
    )
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("release", help="drop this working tree's claim")
    p.add_argument("issue_id")
    p.add_argument("--agent")
    p.add_argument("--session")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("status", help="who holds this working tree")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help(sys.stderr)
        return EXIT_USAGE
    if args.cmd in ("claim", "release") and not args.agent:
        sys.stderr.write(f"--agent is required for `{args.cmd}`.\n")
        return EXIT_USAGE
    if args.cmd == "claim":
        # A junk --holder-pid is a USAGE error, never a quietly dropped field. A
        # caller that believes it recorded liveness and did not has a lock that
        # leaks exactly as before, with nothing on screen to say so.
        raw_pid = getattr(args, "holder_pid", None)
        if raw_pid is None:
            args.holder_pid = None
        else:
            try:
                args.holder_pid = int(raw_pid)
            except (TypeError, ValueError):
                sys.stderr.write(f"--holder-pid must be a pid; got {raw_pid!r}.\n")
                return EXIT_USAGE
            if args.holder_pid <= 0:
                sys.stderr.write(
                    f"--holder-pid must be a positive pid; got {args.holder_pid}.\n"
                )
                return EXIT_USAGE
    try:
        return args.func(args)
    except TreeUnknown as exc:
        sys.stderr.write(
            f"REFUSED: cannot identify the working tree to lock ({exc}). Falling "
            "back to the current directory would invent one lock per subdirectory "
            "and grant every session, so this refuses instead. Run inside a git "
            "working tree, or set KIPI_LINEAR_CLAIMS explicitly.\n"
        )
        return EXIT_COLLISION
    except CorruptLock as exc:
        sys.stderr.write(
            f"REFUSED: {exc}. Failing closed -- a mutex that grants on a damaged "
            "lock is worse than none.\n"
        )
        return EXIT_COLLISION


if __name__ == "__main__":
    sys.exit(main())
