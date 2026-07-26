#!/usr/bin/env python3
"""Agent claim-lock: refuse an issue that another agent is already working.

Two agent sessions sharing one checkout overwrite each other's working tree
(2026-07-26: commit 53f2eeb came from a different session in this same checkout;
the collision was only noticed afterwards, by hand). Nothing in the fleet claimed
or locked an issue before this.

WHY THIS IS TWO HALVES
----------------------
A Python script cannot reach the Linear MCP server -- that is the whole reason
`linear-queue.py` (queue-and-drain) exists. So "set In Progress AND attach
`claimed:<agent>`" cannot be one script call. The split:

  * LOCAL LOCK  -- this file. One working tree, N sessions. The Linear label
    structurally CANNOT see this case: two sessions in one checkout share one
    MCP user and one label set, so only a local file can tell them apart.
  * REMOTE CLAIM -- the agent performs the MCP write. But the REFUSAL DECISION
    still lives here: the agent passes what it read from Linear as
    `--remote-state`, and this script refuses on it. One tested code path, not
    judgment spread across a prompt.

Each half covers what the other structurally cannot: the local lock is blind to
other checkouts, the remote claim is blind to sessions inside one checkout.

THE RESOURCE IS THE WORKING TREE, NOT THE ISSUE
-----------------------------------------------
Two sessions in one checkout stomp each other's files even when working
DIFFERENT issues, so there is one active claim per working tree.

FAIL CLOSED
-----------
A mutex that grants under doubt is worse than no mutex, because callers trust
it. An unreadable or corrupt lock refuses. A stale claim does not auto-expire
(that is a race) and is not permanent (that is a deadlock) -- breaking it takes
an explicit --break-stale.

Exit codes, shared with linear-sync.py so a caller can branch on them:
  0 ok   1 usage   3 collision (a refusal, NOT a crash)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_COLLISION = 3


def working_tree_root() -> str:
    """The tree being protected: the CALLER's, resolved at runtime.

    Deliberately NOT derived from this file's location. `kipi` invokes fleet
    scripts out of $KIPI_HOME (the skeleton), so a path computed from
    __file__ would lock the SKELETON no matter which instance the agent is
    actually working in -- every instance would share one lock and the tree
    at risk would have none. The resource is the caller's working tree.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return os.getcwd()

# States that mean someone has started. Matched case-insensitively against the
# snapshot the agent read from Linear.
STARTED_STATES = ("in progress", "in review")
CLAIM_LABEL_PREFIX = "claimed:"


def claims_path() -> str:
    """Single source for the lock location.

    KIPI_LINEAR_CLAIMS exists so the test suite never touches the live lock --
    the same override discipline as KIPI_LINEAR_LEDGER and KIPI_LINEAR_QUEUE.
    """
    return os.environ.get(
        "KIPI_LINEAR_CLAIMS", os.path.join(working_tree_root(), ".linear-claims.json")
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CorruptLock(Exception):
    """The lock exists but cannot be understood. Callers must refuse, not grant."""


def read_claim() -> dict | None:
    """Current holder, or None when the tree is free.

    Raises CorruptLock rather than returning None on damage. Returning None
    would silently GRANT the lock to the next caller, which is the one outcome
    a mutex must never produce from an error.
    """
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
    """Replace the lock atomically, or remove it when `record` is None.

    Temp-file + os.replace so a reader never observes a half-written lock: a
    torn write would read as CorruptLock and deadlock the tree until a human
    cleared it.
    """
    path = claims_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    if record is None:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
        fh.write("\n")
    os.replace(tmp, path)


class _CriticalSection:
    """O_EXCL guard so two concurrent claims cannot both read "free" and both win.

    Without this the check-then-write is a TOCTOU race, which is precisely the
    two-sessions-racing case this lock exists to stop. Held only across the
    read-decide-write, never across the caller's work.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self.guard = f"{claims_path()}.guard"
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> "_CriticalSection":
        os.makedirs(os.path.dirname(self.guard) or ".", exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    # Another process held the section longer than the timeout.
                    # Refuse rather than barge in.
                    raise CorruptLock(
                        f"another process is holding {self.guard}; refusing"
                    ) from None
                time.sleep(0.05)

    def __exit__(self, *_exc) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            os.remove(self.guard)
        except FileNotFoundError:
            pass


def remote_collision(remote: dict, agent: str) -> str | None:
    """Reason the REMOTE state refuses this agent, or None when it is free.

    The agent reads Linear over MCP and passes the snapshot here, so the refusal
    rule is one tested code path rather than a prompt instruction.
    """
    labels = remote.get("labels") or []
    for label in labels:
        if not isinstance(label, str) or not label.startswith(CLAIM_LABEL_PREFIX):
            continue
        holder = label[len(CLAIM_LABEL_PREFIX):]
        if holder != agent:
            return f"Linear already carries {label}"
    state = (remote.get("state") or "").strip().lower()
    if state in STARTED_STATES:
        assignee = (remote.get("assignee") or "").strip()
        # Our own claim label already cleared us above; reaching here with a
        # started state means someone else (or nobody named) is on it.
        if assignee != agent:
            who = assignee or "an unnamed user"
            return f"Linear shows it {remote.get('state')!r} under {who}"
    return None


def load_remote(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("--remote-state must contain a JSON object")
    return data


def cmd_claim(args: argparse.Namespace) -> int:
    try:
        with _CriticalSection():
            try:
                held = read_claim()
            except CorruptLock as exc:
                sys.stderr.write(
                    f"REFUSED: the lock is unreadable ({exc}). Failing closed -- a "
                    "mutex that grants on a damaged lock is worse than none. "
                    f"Inspect {claims_path()} and remove it deliberately.\n"
                )
                return EXIT_COLLISION

            if held is not None:
                same_agent = held.get("agent") == args.agent
                same_issue = held.get("issue_id") == args.issue_id
                if same_agent and same_issue:
                    held["refreshed_at"] = _now_iso()
                    write_claim(held)
                    print(f"already held by {args.agent}: {args.issue_id}")
                    return EXIT_OK
                if not args.break_stale:
                    sys.stderr.write(
                        f"REFUSED: this working tree is claimed by "
                        f"{held.get('agent')} on {held.get('issue_id')} since "
                        f"{held.get('acquired_at')}. Two sessions in one checkout "
                        "overwrite each other's files even on different issues, so "
                        "the tree is the resource. Release it "
                        f"(`linear-claim.py release {held.get('issue_id')} --agent "
                        f"{held.get('agent')}`), use a separate git worktree, or "
                        "pass --break-stale if that session is known dead.\n"
                    )
                    return EXIT_COLLISION

            if args.remote_state:
                try:
                    remote = load_remote(args.remote_state)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    sys.stderr.write(f"--remote-state unreadable: {exc}\n")
                    return EXIT_USAGE
                reason = remote_collision(remote, args.agent)
                if reason is not None:
                    sys.stderr.write(
                        f"REFUSED: {reason}. Claiming it would take work another "
                        "agent has already started.\n"
                    )
                    return EXIT_COLLISION

            write_claim(
                {
                    "issue_id": args.issue_id,
                    "agent": args.agent,
                    "acquired_at": _now_iso(),
                    "pid": os.getpid(),
                }
            )
            print(f"claimed {args.issue_id} for {args.agent}")
            return EXIT_OK
    except CorruptLock as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return EXIT_COLLISION


def cmd_release(args: argparse.Namespace) -> int:
    try:
        with _CriticalSection():
            try:
                held = read_claim()
            except CorruptLock as exc:
                sys.stderr.write(f"REFUSED: {exc}\n")
                return EXIT_COLLISION
            if held is None:
                print(f"not held: {args.issue_id}")
                return EXIT_OK
            if held.get("agent") != args.agent:
                sys.stderr.write(
                    f"REFUSED: {args.agent} does not hold this tree; "
                    f"{held.get('agent')} does (on {held.get('issue_id')}). An "
                    "agent releasing another's claim is how the lock silently "
                    "stops working.\n"
                )
                return EXIT_COLLISION
            write_claim(None)
            print(f"released {held.get('issue_id')} held by {args.agent}")
            return EXIT_OK
    except CorruptLock as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return EXIT_COLLISION


def cmd_status(_args: argparse.Namespace) -> int:
    try:
        held = read_claim()
    except CorruptLock as exc:
        sys.stderr.write(f"lock unreadable: {exc}\n")
        return EXIT_COLLISION
    if held is None:
        print("no claim held in this working tree")
        return EXIT_OK
    print(
        f"{held.get('issue_id')} claimed by {held.get('agent')} "
        f"since {held.get('acquired_at')}"
    )
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("claim", help="claim an issue for this working tree")
    p.add_argument("issue_id")
    # --agent is validated by hand, not marked required=True: argparse exits 2
    # on a missing required arg, and 2 is not this tool's vocabulary. A usage
    # error must be distinguishable from a refusal (3).
    p.add_argument("--agent")
    p.add_argument("--remote-state", help="JSON snapshot the agent read from Linear")
    p.add_argument(
        "--break-stale",
        action="store_true",
        help="break a claim left by a session known to be dead",
    )
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("release", help="drop this working tree's claim")
    p.add_argument("issue_id")
    p.add_argument("--agent")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("status", help="who holds this working tree")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help(sys.stderr)
        return EXIT_USAGE
    if args.cmd in ("claim", "release") and not args.agent:
        sys.stderr.write(
            f"--agent is required for `{args.cmd}`. The lock records WHO holds "
            "the tree; an anonymous claim cannot be refused or released.\n"
        )
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
