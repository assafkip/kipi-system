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
The release is only reached AFTER a successful acquisition, so there is no
ORDINARY path into it holding someone else's lock. A mutant that reverts the
release to an unconditional unlink therefore passes an entire suite that never
makes the lock change hands mid-transaction. Case 3 exists for exactly that.

WHAT CHANGED IN ROUND 2 (codex round 1 on PR #67)
-------------------------------------------------
The first fix hand-rolled the lock: a token file, published with os.link,
released by token, broken when the pid it named was not running. Codex found
that pid liveness answers the wrong question -- pids wrap, so a leftover lock
eventually names a live process that never held it and is then honoured forever
(case 7). The mechanism is now `fcntl.flock`, which the kernel releases on close
AND on process death, so a corpse lock cannot exist (case 8).

That moves where the fixtures have to bite. A lock is now HELD, not DESCRIBED,
so the contention cases hold a real flock from a live subprocess instead of
writing a pid into a file. Two contracts inverted with the mechanism and are
asserted in their new form rather than dropped:

  * the lock FILE is never unlinked (case 6). Unlinking is what lets two runs
    hold locks on two different inodes at one path.
  * a leftover lock file is inert. It carries no state, so nothing about its
    contents can wedge a write (cases 4, 5, 7).

ISOLATION: every case runs in its own tempdir against its own ledger file. This
suite never touches the live linear-worker-attempts.json.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
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
    """One CLI invocation. `tries` keeps a contended case sub-second.

    Production leaves both KIPI_ATTEMPTS_LOCK_* unset, same posture as
    converge.sh's KIPI_RECEIPT_LOCK_TRIES. This comment used to claim a
    "production 10s timeout" while a blocked mutation really took 22.1s
    (measured 2026-08-02, codex round 1 on PR #67, finding 4). The budget was a
    COUNT -- 100 tries x 0.1s -- and `time.sleep(0.1)` costs 212ms on this
    kernel, so the sleeps alone were 21.2s of it. It is a wall-clock deadline
    now, so the documented number is the measured one. Verified below.
    """
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


@contextlib.contextmanager
def lock_held_by_live_process(lock: str):
    """Hold a real flock on `lock` from a separate live process.

    The lock is now the open file description, so contention has to be produced
    by actually holding it. Writing a pid into the file would describe a holder
    without being one, which is precisely the confusion case 7 exists to kill.
    """
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time\n"
         "fh=open(sys.argv[1],'a')\n"
         "fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n"
         "sys.stdout.write('held\\n'); sys.stdout.flush()\n"
         "time.sleep(300)\n",
         lock],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        if holder.stdout.readline().strip() != "held":
            fail("the holder subprocess never reported taking the lock")
        yield holder
    finally:
        holder.kill()
        holder.wait()


# --- 1. A TIMEOUT MUST NOT PROCEED -------------------------------------------
# The lock is held by a live process, so the only correct outcome is to write
# nothing and say so. The old code broke out of the retry loop and entered the
# transaction holding nothing.
def case_timeout_does_not_proceed(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-timeout.json")
    with open(path, "w") as fh:
        json.dump({"ASK-1": {"count": 1}}, fh)

    with lock_held_by_live_process(path + ".lock"):
        proc = run(path, "bump-attempt", "ASK-1", "because")

        if proc.returncode == 0:
            fail("THE DEFECT: the lock is held by a live process and bump-attempt reported "
                 "success. A run that cannot take the lock must do no work and say so -- "
                 f"entering the transaction here is two runs inside one read-decide-write. "
                 f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        got = read_ledger(path).get("ASK-1", {}).get("count")
        if got != 1:
            fail("THE DEFECT: bump-attempt could not take the lock and mutated the ledger "
                 f"anyway (count went 1 -> {got})")
        if "lock" not in (proc.stderr or "").lower():
            fail("the bump was skipped for lock contention and nothing said so, so a dropped "
                 f"increment is invisible: stderr={proc.stderr!r}")
    ok("a timeout writes nothing and says so, leaving the live holder undisturbed")


# --- 2. THE SAME, FOR THE ONCE-ONLY PAGE FLAG --------------------------------
# claim-flag's exit code IS the decision ("page or stay quiet"), so a lock
# failure must land on neither 0 nor 1. Exit 0 fires a page for a flag that was
# never claimed; exit 1 retires a page that never fired.
def case_claim_flag_timeout(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-claim.json")
    with open(path, "w") as fh:
        json.dump({}, fh)

    with lock_held_by_live_process(path + ".lock"):
        proc = run(path, "claim-flag", "ASK-2", "stuck_paged")

        if proc.returncode == 0:
            fail("THE DEFECT: claim-flag could not take the lock and answered 'claimed'. The "
                 "caller pages on exit 0, so this is a page for a flag nothing recorded -- it "
                 "fires again on every run after")
        if proc.returncode == 1:
            fail("THE DEFECT: claim-flag could not take the lock and answered 1, which is the "
                 "code for 'already claimed on an earlier run'. The caller stays quiet, so a "
                 "page is dropped for a state no file records and no later run will retire")
        if read_ledger(path).get("ASK-2", {}).get("stuck_paged"):
            fail("claim-flag could not take the lock and set the flag anyway")
    ok("claim-flag under contention neither claims, nor reports a claim, nor reads as claimed")


# --- 3. THE RELEASE NEVER DISTURBS A LOCK THIS RUN DOES NOT OWN --------------
# The mutation-killer. Reached only after a SUCCESSFUL acquisition, so nothing
# ordinary walks into the release holding a foreign lock: the case has to build
# that state on purpose. It stamps a foreign token over the lock file from INSIDE
# the critical section. A release that trusts the path unlinks it; the flock
# release closes a file descriptor and touches no name at all.
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
             "removed it anyway. Releasing by path means whichever run finishes first unlocks "
             "the run that is still inside its own transaction")
    ok("a release removes no name, so it cannot take away a lock another run holds")


# --- 4. A LOCK LEFT BY A DEAD RUN DOES NOT WEDGE FUTURE WRITES ---------------
# The other side of refusing to force. A leftover lock file naming pid
# 2147483647 is inert: it holds no flock, so nothing has to reason about it.
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
    ok("a lock file left by a dead run holds nothing and blocks nothing")


# --- 5. THE PRE-FLOCK LEFTOVERS ARE BOTH SURVIVED ----------------------------
# Two shapes a pre-ASK-286 worker leaves at this path. A DIRECTORY is what the
# original os.mkdir lock leaves when its run is killed, and an EMPTY file is the
# window the token lock left between create and stamp. Neither can be opened-and-
# locked as-is, so the first fleet upgrade would wedge every ledger that has one.
def case_pre_flock_leftovers(tmp: str) -> None:
    for name, make in (("directory", os.mkdir), ("empty file", lambda p: open(p, "w").close())):
        path = os.path.join(tmp, "attempts-leftover-%s.json" % name.split()[0])
        with open(path, "w") as fh:
            json.dump({}, fh)
        make(path + ".lock")

        proc = run(path, "bump-attempt", "ASK-5", "because")

        if proc.returncode != 0:
            fail(f"a leftover lock {name} from a pre-flock worker wedged the ledger. The first "
                 "instance to take this upgrade with one on disk never counts an attempt "
                 f"again. stderr={proc.stderr!r}")
        if read_ledger(path).get("ASK-5", {}).get("count") != 1:
            fail(f"the leftover lock {name} was cleared but the bump never landed")
    ok("a pre-flock leftover (mkdir directory, empty token file) does not wedge the upgrade")


# --- 6. THE LOCK FILE IS NEVER UNLINKED --------------------------------------
# Inverted contract, asserted rather than dropped. The old lock deleted its file
# on release; this one must not. Unlinking is the ONE way a file lock is
# defeated: run A holds the inode, someone unlinks the name, run B creates a
# fresh inode at that path and locks it, and both are inside the transaction.
def case_lock_file_is_never_unlinked(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-persist.json")
    lock = path + ".lock"

    if run(path, "bump-attempt", "ASK-10", "why").returncode != 0:
        fail("the ordinary bump did not succeed, so this case cannot judge the release")
    if not os.path.exists(lock):
        fail("THE DEFECT: the release unlinked the lock file. A later run then creates a NEW "
             "inode at that path while a live run holds the old one, and both believe they "
             "are alone -- the two-inodes-one-path race a file lock exists to prevent")
    first = os.stat(lock).st_ino

    if run(path, "bump-attempt", "ASK-10", "why").returncode != 0:
        fail("the second bump did not succeed against the surviving lock file")
    if os.stat(lock).st_ino != first:
        fail("the second run replaced the lock inode instead of locking the one already there")
    if os.path.getsize(lock) != 0:
        fail(f"the lock file carries state ({os.path.getsize(lock)} bytes); it must be inert, "
             "or something will start reasoning about its contents again")
    ok("the lock file survives the release, is re-locked in place, and carries no state")


# --- 7. A LOCK NAMING A LIVE PID THAT IS NOT THE HOLDER MUST NOT WEDGE -------
# Codex round 1 on PR #67, MAJOR. Liveness-by-pid answers the wrong question: it
# asks "is some process with this number running", not "is that process holding
# this lock". Pids wrap, so a leftover lock file eventually names a pid that some
# unrelated live process now has -- and then it is honoured forever. The attempts
# counter freezes, no issue reaches MAX_ATTEMPTS, no issue reaches STUCK, and no
# human is ever paged. Silent and permanent, which is the exact failure class
# this ledger exists to kill.
#
# pid 1 makes it deterministic rather than probabilistic: launchd/init is always
# alive and is never the holder of this lock.
def case_live_pid_that_never_held_it(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-pidreuse.json")
    with open(path, "w") as fh:
        json.dump({}, fh)
    lock = path + ".lock"
    with open(lock, "w") as fh:
        fh.write("1:0:0\n")          # pid 1 is alive and never held this lock

    proc = run(path, "bump-attempt", "ASK-7", "because")

    if proc.returncode != 0:
        fail("THE DEFECT: a leftover lock naming a LIVE pid that never held it froze the "
             "ledger. Nothing releases that lock, so every future write is refused: the "
             "attempts counter stops, no issue reaches STUCK, and no human is paged. "
             f"stderr={proc.stderr!r}")
    if read_ledger(path).get("ASK-7", {}).get("count") != 1:
        fail(f"the stale lock was cleared but the bump never landed: {read_ledger(path)!r}")
    ok("a leftover lock naming a live pid that never held it does not freeze the ledger")


# --- 8. THE HOLDER'S DEATH RELEASES THE LOCK, WITH NO HEURISTIC --------------
# The positive form of case 7, and the reason case 7 is unreachable by
# construction rather than merely unlikely. A real holder blocks; the moment that
# holder dies the next run proceeds -- not after a timer, not after guessing at a
# pid, but because the kernel drops the lock with the process.
def case_holder_death_releases(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-death.json")
    with open(path, "w") as fh:
        json.dump({}, fh)

    with lock_held_by_live_process(path + ".lock"):
        proc = run(path, "bump-attempt", "ASK-8", "because")
        if proc.returncode == 0:
            fail("THE DEFECT: a run wrote the ledger while another process held the lock. "
                 f"stderr={proc.stderr!r}")

    proc = run(path, "bump-attempt", "ASK-8", "because")
    if proc.returncode != 0:
        fail("the holder is dead and its lock was still honoured, so the ledger is wedged "
             f"until something outside this program intervenes. stderr={proc.stderr!r}")
    if read_ledger(path).get("ASK-8", {}).get("count") != 1:
        fail(f"the dead holder's lock was released but the bump never landed: {read_ledger(path)!r}")
    ok("a live holder blocks the write and its death releases the lock with no heuristic")


# --- 9. THE LOCK TAKEN IS THE LOCK AT THE PATH -------------------------------
# A pre-ASK-286 worker breaks a lock by UNLINKING it, so during a fleet rollout
# one can replace the file this run is taking. A handle locked on an orphaned
# inode guards nothing: nobody else will ever contend on it. Acquiring is
# therefore not enough -- the inode locked has to still be the inode at the path.
def case_lock_taken_is_the_lock_at_the_path(tmp: str) -> None:
    mod = load_module()
    lock = os.path.join(tmp, "attempts-replaced.json.lock")

    # The replacement has to happen DURING acquisition, in the window between
    # opening the file and deciding we hold it. Replacing it beforehand proves
    # nothing -- the open lands on the live inode and an implementation with NO
    # guard at all looks correct, which is exactly how this case first shipped
    # decorative (its mutant survived).
    #
    # `mod.open` shadows the builtin inside that module, so this wraps the exact
    # call `_take_lock` makes: once, then it gets out of the way.
    real_open = open
    state = {"swapped": False}

    def open_then_replace(path, *a, **kw):
        fh = real_open(path, *a, **kw)
        if path == lock and not state["swapped"]:
            state["swapped"] = True
            orphan = os.fstat(fh.fileno()).st_ino
            os.unlink(lock)                                   # what an old worker does
            os.close(os.open(lock, os.O_CREAT | os.O_WRONLY, 0o644))
            if os.stat(lock).st_ino == orphan:
                fail("the fixture could not produce a second inode at the lock path")
        return fh

    mod.open = open_then_replace
    try:
        fh = mod._take_lock(lock)
    finally:
        del mod.open
    if fh is None:
        fail("the lock at a replaced path could not be taken at all")
    try:
        if not state["swapped"]:
            fail("the fixture never fired, so this case asserted nothing")
        if os.fstat(fh.fileno()).st_ino != os.stat(lock).st_ino:
            fail("THE DEFECT: the handle holds an inode that was unlinked out from under it "
                 "while the lock was being taken. Nobody will ever contend on that orphan, so "
                 "the next run locks the live inode and both are inside the transaction at "
                 "once -- two locks at one path is how a file lock is beaten")
    finally:
        mod._drop_lock(fh)
    ok("a lock file replaced mid-acquire is re-taken on the live inode, not held as an orphan")


# --- 10. THE ORDINARY PATH STILL WORKS ---------------------------------------
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
    ok("every op round-trips through the guarded writer")


# --- 11. A BAD INVOCATION EXITS 2, NEVER 1 -----------------------------------
# Codex round 1 on PR #67, finding 2, and the shape it does not name. Exit 1 is
# claim-flag's "already claimed on an earlier run, stay quiet". `claim-flag ASK-1`
# with the flag omitted used to raise IndexError, and an uncaught Python exception
# exits 1 -- so a typo in a call site read as "already paged" and the page was
# dropped for good. Each exit code has to mean exactly one thing.
def case_usage_errors_exit_two(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-usage.json")
    with open(path, "w") as fh:
        json.dump({}, fh)

    for args in (
        ("claim-flag", "ASK-11"),                       # flag omitted
        ("bump-attempt", "ASK-11"),                     # why omitted
        ("bump-conflict",),                             # issue omitted
        ("clear-automerge", "ASK-11", "extra"),         # one too many
        ("not-an-op", "ASK-11"),                        # unknown op
    ):
        proc = run(path, *args)
        if proc.returncode == 1:
            fail("THE DEFECT: `%s` exited 1, which is the code for 'already claimed, stay "
                 "quiet'. Six call sites in linear-worker.sh read that as a page already "
                 "sent, so a bad invocation silently drops the page. stderr=%r"
                 % (" ".join(args), proc.stderr))
        if proc.returncode != 2:
            fail(f"`{' '.join(args)}` exited {proc.returncode}, wanted 2 (usage): "
                 f"stderr={proc.stderr!r}")
    if read_ledger(path):
        fail(f"a usage error wrote to the ledger: {read_ledger(path)!r}")
    ok("a bad invocation exits 2 and writes nothing, never 1")


# --- 12. THE DOCUMENTED TIMEOUT IS THE MEASURED ONE --------------------------
# Codex round 1 on PR #67, finding 4. The old budget was a COUNT that everything
# described as a duration, and the two differed by 2.2x. A number in a comment
# that nothing checks drifts from the code the moment either changes; this asserts
# the refusal actually lands inside the budget it advertises.
def case_timeout_is_the_documented_budget(tmp: str) -> None:
    path = os.path.join(tmp, "attempts-budget.json")
    with open(path, "w") as fh:
        json.dump({}, fh)

    budget = 2.0
    env = dict(os.environ)
    env["KIPI_ATTEMPTS_LOCK_TIMEOUT"] = str(budget)
    env.pop("KIPI_ATTEMPTS_LOCK_TRIES", None)

    with lock_held_by_live_process(path + ".lock"):
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(LEDGER), path, "bump-attempt", "ASK-12", "why"],
            capture_output=True, text=True, env=env,
        )
        elapsed = time.monotonic() - started

    if proc.returncode != 3:
        fail(f"the contended bump exited {proc.returncode}, wanted 3: stderr={proc.stderr!r}")
    if elapsed < budget:
        fail(f"the refusal came back in {elapsed:.1f}s, inside its own {budget}s budget -- it "
             "gave up early, so a holder that was about to finish is not waited out")
    # Generous headroom: one sleep of slop plus interpreter startup. The defect
    # this catches is a budget that is off by a MULTIPLE, which is what a count
    # standing in for a clock produces.
    if elapsed > budget * 2:
        fail(f"THE DEFECT: the documented {budget}s budget took {elapsed:.1f}s. A retry budget "
             "expressed as a count is not a duration -- time.sleep(0.1) costs 212ms on this "
             "kernel, so 100 tries advertised as 10s really took 22.1s")
    ok(f"a contended refusal lands inside the budget it documents ({elapsed:.1f}s of {budget}s)")


# --- 13. AN OS ERROR ON THE WRITE PATH MUST NOT ANSWER 1 ---------------------
# Codex round 2 on PR #67, minor 3. `main` caught `Usage` and `LockUnavailable`
# and nothing else, so an OSError from mkstemp / os.replace / json.dump escaped
# as an uncaught exception -- and Python exits 1 on those. For claim-flag, 1 is
# the ONE code that means "already claimed on a prior run, stay quiet". So a
# write that failed hard read as a page already sent, for a flag no file records,
# which means no later run retires it either. Same silent-drop class as findings
# 2 and 3, arriving through the one door still left open.
#
# The trigger here is constructed (a read-only ledger directory); the natural
# producer is a full disk. That is why the exit code is what gets asserted rather
# than the specific errno -- the point is that EVERY unexpected failure lands on
# 2, not that this one does.
def case_write_failure_is_not_already_claimed(tmp: str) -> None:
    ro_dir = os.path.join(tmp, "readonly-ledger")
    os.mkdir(ro_dir)
    path = os.path.join(ro_dir, "attempts.json")
    with open(path, "w") as fh:
        json.dump({}, fh)
    # PRE-CREATE THE LOCK FILE. Without it the read-only directory stops the run
    # at lock CREATION, which already answers 3 -- so the fixture would pass
    # against an implementation that has none of this handling, testing the lock
    # path instead of the write path. The defect lives after acquisition: flock
    # opens an existing file fine, and `mkstemp` in the same directory is the
    # first thing that cannot proceed.
    open(path + ".lock", "a").close()
    os.chmod(ro_dir, 0o555)          # writable files, unwritable directory
    try:
        proc = subprocess.run(
            [sys.executable, str(LEDGER), path, "claim-flag", "ASK-13", "stuck_paged"],
            capture_output=True, text=True,
        )
    finally:
        os.chmod(ro_dir, 0o755)

    if proc.returncode == 0:
        fail("the failed write answered 0, so the caller pages off a flag no file records")
    if proc.returncode == 1:
        fail("THE DEFECT: the ledger write failed with an OSError and the process exited 1 -- "
             "the same answer as 'already claimed on a prior run'. page_once routes 1 to "
             "'stay quiet', so the page is dropped for a state nothing recorded and no later "
             f"run will retire. stderr tail={proc.stderr.strip().splitlines()[-1:]!r}")

    # And the flag really was not written, which is what makes 1 a lie.
    with open(path) as fh:
        after = json.load(fh)
    if after:
        fail(f"the ledger recorded {after!r} despite the write failing")
    ok(f"a hard write failure exits {proc.returncode}, not 1 ('already claimed'), and records nothing")


def main() -> int:
    print("test-attempts-ledger: the lock around the attempts counter (ASK-286)")
    with tempfile.TemporaryDirectory() as tmp:
        case_timeout_does_not_proceed(tmp)
        case_claim_flag_timeout(tmp)
        case_release_checks_ownership(tmp)
        case_corpse_lock(tmp)
        case_pre_flock_leftovers(tmp)
        case_lock_file_is_never_unlinked(tmp)
        case_live_pid_that_never_held_it(tmp)
        case_holder_death_releases(tmp)
        case_lock_taken_is_the_lock_at_the_path(tmp)
        case_ops_round_trip(tmp)
        case_usage_errors_exit_two(tmp)
        case_timeout_is_the_documented_budget(tmp)
        case_write_failure_is_not_already_claimed(tmp)
    print(f"PASS ({PASSED} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
