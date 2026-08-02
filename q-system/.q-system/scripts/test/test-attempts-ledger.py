#!/usr/bin/env python3
"""Reproducer + acceptance criterion for the attempts-ledger lock (ASK-286).

WHY THIS SUITE EXISTS
---------------------
`attempts-ledger.py` `_mutate` shipped a lock with two defects: it PROCEEDED on
timeout (returned success while holding nothing) and its release removed the
lock BY PATH (whichever run happened to hold it). Together they are worse than
no lock: a run that times out believes it is serialized, enters the critical
section, and its release then deletes the live lock of the run that actually
holds it -- so both runs are inside one read-decide-write.

The ledger guards the attempts counter. A lost increment means an issue exceeds
MAX_ATTEMPTS and keeps being dispatched, burning budget on work that already
failed three times and never reaching the STUCK state where a human is told.
That failure is silent and self-perpetuating.

THE TRAP THIS SUITE IS BUILT AROUND (learned on PR #42)
-------------------------------------------------------
The release is only reached AFTER a successful acquisition, so once the timeout
stops lying there is no ORDINARY path into it holding someone else's lock. A
mutant that reverts the release to an unconditional unlink therefore passes an
entire suite that never makes the lock change hands mid-transaction. Case 3
exists for exactly that: it stamps a foreign token over the lock from INSIDE the
critical section, which is the only shape that can fail a release-by-path.

ISOLATION: every case runs in its own tempdir against its own ledger file. This
suite never touches the live linear-worker-attempts.json.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LEDGER = ROOT / "q-system/.q-system/scripts/attempts-ledger.py"

PASSED = 0


def ok(msg: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  ok: {msg}")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def load_module():
    """Import attempts-ledger.py by path -- its name is not an identifier."""
    spec = importlib.util.spec_from_file_location("attempts_ledger", LEDGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(path: str, *args: str, tries: str = "3") -> subprocess.CompletedProcess:
    """One CLI invocation. `tries` keeps a contended case sub-second instead of
    sleeping out the production 10s timeout -- same posture as converge.sh's
    KIPI_RECEIPT_LOCK_TRIES, which production never sets."""
    env = dict(os.environ)
    env["KIPI_ATTEMPTS_LOCK_TRIES"] = tries
    return subprocess.run(
        [sys.executable, str(LEDGER), path, *args],
        capture_output=True, text=True, env=env,
    )


def read_ledger(path: str) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {}


def read_lock(lock: str) -> str:
    try:
        with open(lock) as fh:
            return fh.read().strip()
    except Exception:
        return ""


# --- 1. A TIMEOUT MUST NOT PROCEED -------------------------------------------
# The lock is held by a LIVE pid (this test process, which is by definition
# running), so the only correct outcome is to write nothing and say so. The old
# code broke out of the retry loop and entered the transaction holding nothing.
def case_timeout_does_not_proceed(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-timeout.json")
    with open(path, "w") as fh:
        json.dump({"ASK-1": {"count": 1}}, fh)
    lock = path + ".lock"
    held = "%d:0:0" % os.getpid()
    with open(lock, "w") as fh:
        fh.write(held + "\n")

    proc = run(path, "bump-attempt", "ASK-1", "because")

    if proc.returncode == 0:
        fail("THE DEFECT: the lock is held by a LIVE pid and bump-attempt reported success. "
             "A run that cannot take the lock must do no work and say so -- entering the "
             f"transaction here is two runs inside one read-decide-write. stdout={proc.stdout!r} "
             f"stderr={proc.stderr!r}")
    got = read_ledger(path).get("ASK-1", {}).get("count")
    if got != 1:
        fail("THE DEFECT: bump-attempt could not take the lock and mutated the ledger anyway "
             f"(count went 1 -> {got})")
    if read_lock(lock) != held:
        fail("THE DEFECT: the run that could not take the lock removed or overwrote the live "
             f"holder's lock. It now reads {read_lock(lock)!r}, not {held!r}")
    if "lock" not in (proc.stderr or "").lower():
        fail("the bump was skipped for lock contention and nothing said so, so a dropped "
             f"increment is invisible: stderr={proc.stderr!r}")
    ok("a timeout writes nothing, says so, and leaves the live holder's lock alone")


# --- 2. THE SAME, FOR THE ONCE-ONLY PAGE FLAG --------------------------------
# claim-flag's exit code IS the decision ("page or stay quiet"), so a lock
# failure must not land on 0. Exit 0 here would fire a page for a flag that was
# never claimed, and every later run would fire it again.
def case_claim_flag_timeout(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-claim.json")
    with open(path, "w") as fh:
        json.dump({}, fh)
    lock = path + ".lock"
    with open(lock, "w") as fh:
        fh.write("%d:0:0\n" % os.getpid())

    proc = run(path, "claim-flag", "ASK-2", "stuck_paged")

    if proc.returncode == 0:
        fail("THE DEFECT: claim-flag could not take the lock and answered 'claimed'. The "
             "caller pages on exit 0, so this is a page for a flag nothing recorded -- it "
             "fires again on every run after")
    if read_ledger(path).get("ASK-2", {}).get("stuck_paged"):
        fail("claim-flag could not take the lock and set the flag anyway")
    ok("claim-flag under contention neither claims nor reports a claim")


# --- 3. THE RELEASE ONLY EVER REMOVES A LOCK THIS RUN OWNS -------------------
# The mutation-killer. Reached only after a SUCCESSFUL acquisition, so nothing
# ordinary walks into the release holding a foreign lock: the case has to build
# that state on purpose. The mutation fn stamps a foreign token over the lock
# from INSIDE the critical section. A release that trusts the path deletes it;
# one that checks its own token leaves it.
def case_release_checks_ownership(tmp: str) -> None:
    mod = load_module()
    path = os.path.join(tmp, "attempts-own.json")
    lock = path + ".lock"

    def steal(d: dict) -> bool:
        with open(lock, "w") as fh:
            fh.write("foreign:0:0\n")
        d["ASK-3"] = {"count": 1}
        return True

    wrote = mod._mutate(path, steal)

    if not wrote:
        fail("the transaction itself did not complete; this case can only judge the RELEASE "
             "if the mutation ran")
    if not os.path.exists(lock):
        fail("THE DEFECT: the lock changed hands during the transaction and the release "
             "deleted it anyway. Releasing by path means whichever run finishes first unlocks "
             "the run that is still inside its own transaction")
    if read_lock(lock) != "foreign:0:0":
        fail("the release removed another run's lock and left something else in its place: "
             f"{read_lock(lock)!r}")
    ok("a release refuses to remove a lock that no longer carries this run's token")


# --- 4. A CORPSE LOCK DOES NOT WEDGE FUTURE WRITES ---------------------------
# The other side of refusing to force. Broken on OWNER LIVENESS, not a timer:
# pid 2147483647 is not running, so honouring its lock would mean no attempt is
# ever counted again on this ledger.
def case_corpse_lock(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-corpse.json")
    with open(path, "w") as fh:
        json.dump({}, fh)
    lock = path + ".lock"
    with open(lock, "w") as fh:
        fh.write("2147483647:0:0\n")

    proc = run(path, "bump-attempt", "ASK-4", "because")

    if proc.returncode != 0:
        fail("a lock left behind by a dead run blocked the increment permanently. Refusing to "
             "force a LIVE lock is right; honouring a corpse means the attempts counter "
             f"freezes and no issue ever reaches STUCK. stderr={proc.stderr!r}")
    if read_ledger(path).get("ASK-4", {}).get("count") != 1:
        fail(f"the corpse lock was broken but the bump never landed: {read_ledger(path)!r}")
    if os.path.exists(lock):
        fail("the run finished its transaction and left its own lock behind, so the next run "
             "has to break it as a corpse before it can do anything")
    ok("a lock left by a dead run is broken, written through, and released")


# --- 5. AN UNATTRIBUTABLE LOCK IS A CORPSE BY CONSTRUCTION -------------------
# Two shapes, one rule. A leftover DIRECTORY is what a pre-fix worker killed
# mid-transaction leaves behind (the old lock was `os.mkdir`), and an EMPTY file
# is the window a create-then-stamp lock leaves open. Neither can ever be
# attributed to a live owner, so honouring either wedges this ledger forever on
# the first upgrade. Both must break.
def case_unattributable_lock(tmp: str) -> None:
    for name, make in (("directory", os.mkdir), ("empty file", lambda p: open(p, "w").close())):
        path = os.path.join(tmp, "attempts-unattr-%s.json" % name.split()[0])
        with open(path, "w") as fh:
            json.dump({}, fh)
        make(path + ".lock")

        proc = run(path, "bump-attempt", "ASK-5", "because")

        if proc.returncode != 0:
            fail(f"a leftover lock {name} wedged the ledger permanently. Nothing can ever "
                 "prove it owns that lock, so waiting on it is waiting forever. "
                 f"stderr={proc.stderr!r}")
        if read_ledger(path).get("ASK-5", {}).get("count") != 1:
            fail(f"the leftover lock {name} was cleared but the bump never landed")
    ok("a lock nothing can ever own (stale mkdir directory, empty file) is broken, not honoured")


# --- 6. THE ORDINARY PATH STILL WORKS ----------------------------------------
# The guard is only worth having if every op still round-trips. clear-automerge
# is called out by name because it once existed only in the shell caller and
# exited 2 here, which made a once-only page permanently silent.
def case_ops_round_trip(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-ops.json")

    for args, want in (
        (("bump-attempt", "ASK-6", "why"), 0),
        (("bump-conflict", "ASK-6"), 0),
        (("bump-drift", "ASK-6"), 0),
        (("claim-flag", "ASK-6", "stuck_paged"), 0),
        (("claim-flag", "ASK-6", "stuck_paged"), 1),   # second claim is refused
        (("clear-conflict", "ASK-6"), 0),
        (("clear-drift", "ASK-6"), 0),
        (("clear-automerge", "ASK-6"), 0),
    ):
        proc = run(path, *args)
        if proc.returncode != want:
            fail(f"{' '.join(args)} exited {proc.returncode}, wanted {want}: "
                 f"stdout={proc.stdout!r} stderr={proc.stderr!r}")

    entry = read_ledger(path).get("ASK-6", {})
    if entry.get("count") != 1 or entry.get("why") != "why":
        fail(f"bump-attempt did not record the count and reason: {entry!r}")
    if entry.get("conflict_rounds") is not None or entry.get("drift_rounds") is not None:
        fail(f"the clear ops left their counters behind: {entry!r}")
    if not entry.get("stuck_paged"):
        fail(f"the claimed page flag did not survive the clears: {entry!r}")

    proc = run(path, "get", "ASK-6", "count", "0")
    if proc.stdout.strip() != "1":
        fail(f"get read back {proc.stdout!r}, wanted 1")
    if os.path.exists(path + ".lock"):
        fail("the ordinary path leaves its lock behind")
    ok("every op round-trips through the guarded writer and releases its lock")


def main() -> int:
    print("test-attempts-ledger: the lock around the attempts counter (ASK-286)")
    with tempfile.TemporaryDirectory() as tmp:
        case_timeout_does_not_proceed(tmp)
        case_claim_flag_timeout(tmp)
        case_release_checks_ownership(tmp)
        case_corpse_lock(tmp)
        case_unattributable_lock(tmp)
        case_ops_round_trip(tmp)
    print(f"PASS ({PASSED} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
