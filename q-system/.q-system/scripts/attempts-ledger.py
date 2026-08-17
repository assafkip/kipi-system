#!/usr/bin/env python3
"""THE single writer of linear-worker-attempts.json.

WHY THIS FILE EXISTS (codex round 5 on PR #47, major).

The ledger holds four independent budgets keyed per issue -- `count` (failed
attempts), `conflict_rounds`, `drift_rounds`, and the one-shot `*_paged` flags.
Six shell functions each shelled out to their own inline python doing an
unsynchronised read-modify-write. Two workers finishing together both read the
same dict and one update vanished, so an issue could exceed a cap and keep being
dispatched -- the exact runaway the caps exist to stop. sp-53b02cc4 recorded the
shape; nothing had fixed it.

Round 4 put a lock inside `bump_attempt` only, and I claimed in the commit
message that fixing "the shared helper" fixed all of them. That was wrong:
bump_attempt is one of six, and the other five kept racing on the same file.
Codex caught the claim. Hence ONE writer, here, rather than six copies of a lock
-- six copies of a lock is just the original defect with more places to drift.

THE LOCK WAS WORSE THAN NO LOCK (ASK-286, sp-626e9452). It used to PROCEED on
timeout -- break out of the retry loop and enter the transaction holding nothing
-- and its release removed the lock BY PATH. Together: a run that times out
believes it is serialized, walks in, and on the way out deletes the live lock of
the run that actually holds it. Both runs are then inside one read-decide-write,
which is precisely what this file exists to stop. It also propagated: on
2026-08-02 an agent was told to reuse an in-repo lock rather than invent a
fourth, copied THIS one including both defects, and cited the source as
justification. Citing a pattern is not verifying it.

WHY fcntl.flock AND NOT A TOKEN FILE (codex round 1 on PR #67, findings 1 + 3).
The first fix here back-ported converge.sh `receipt_transaction`: a token written
into a file, published with os.link, released only if it still carried this run's
token, and broken when the pid it named was not running. That is the right shape
FOR BASH, where converge.sh lives -- macOS ships no flock(1) BINARY, so a shell
script genuinely has to hand-roll one. It is the wrong shape here, and the
docstring that justified it with a flat "macOS ships no flock" was simply false:
this is Python, `fcntl.flock` works on both kernels this fleet runs on, and
`session_recall.py` was already using it a few files away.

Keeping the hand-rolled version cost three separate defects, all of them the
mechanism rather than the tuning:

  1. LIVENESS BY PID ANSWERS THE WRONG QUESTION. It asks "is some process with
     this number running", not "is that process holding this lock". Pids wrap, so
     a leftover lock eventually names a pid an unrelated live process now has --
     and is then honoured forever. The attempts counter freezes, no issue reaches
     MAX_ATTEMPTS, no issue reaches STUCK, and no human is paged. Silent and
     permanent, which is the failure class this ledger exists to kill. Every
     alternative is another heuristic with its own hole: an age cap breaks a slow
     holder and trusts the clock.
  2. RELEASE-BY-OWNER, ATOMIC PUBLISH, AND CORPSE-BREAKING ARE ~90 LINES OF
     HEURISTIC standing in for something the kernel already guarantees.

flock erases both. The lock is the open file description, so the kernel releases
it on close AND on process death: a dead holder blocks nothing, with no pid to
guess at and no timer to trust.

FINDING 4 IS A THIRD DEFECT AND IT IS NOT THE MECHANISM -- the retry budget was a
COUNT PRETENDING TO BE A CLOCK. `LOCK_TRIES=100` x `LOCK_SLEEP=0.1` was
documented as "the production 10s timeout" and measured 22.1s. The first guess,
that the 100 mkstemp/link/unlink publish attempts were the overhead, was wrong:

  $ python3 -c "import time; t=time.time()
  > [time.sleep(0.1) for _ in range(100)]; print(time.time()-t)"
  21.2

`time.sleep(0.1)` costs 212ms on this kernel, so the sleeps alone were 21.2s of
the 22.1. A count cannot express a duration on a kernel whose sleeps do not keep
to their argument, and switching mechanism would not have changed that by one
second. So the budget is a wall-clock DEADLINE now, and the number in the comment
is enforced rather than asserted. LOCK_TRIES survives as a second cap, because
the suite needs a way to make the contended path sub-second.

THE INVARIANTS, and where each now lives:

  1. A TIMEOUT RETURNS FAILURE -- still enforced here, in `_mutate`. The caller
     does no work and says so. A skipped increment is recoverable: the next
     scheduled run retries, and the run that DID hold the lock is counting. Two
     runs inside one read-decide-write is not recoverable.
  2. A RELEASE ONLY EVER DROPS THIS RUN'S OWN HOLD -- the kernel's, by
     construction. There is no path to release someone else's.
  3. THE LOCK NEVER EXISTS UN-ATTRIBUTABLE -- the kernel's. The lock IS the open
     file description; an empty or leftover lock FILE holds nothing.
  4. A DEAD OWNER NEVER WEDGES A WRITE -- the kernel's. No corpse can exist.

THE ONE WAY A FILE LOCK CAN STILL BE DEFEATED is two runs holding locks on two
different inodes at the same path, which is why this file NEVER UNLINKS THE LOCK.
A leftover zero-byte `.lock` is inert -- it carries no state, and the next run
locks the same inode. A pre-ASK-286 worker still breaks locks by unlinking, so
during a fleet rollout one can replace the file this run is holding; `_take_lock`
therefore re-checks that the inode it locked is still the inode at the path, and
retries on the live one if not.

CONCURRENCY, the other half. The write is temp-then-os.replace so a crash
mid-write cannot leave a truncated ledger, which would read as `{}` and silently
reset every budget in the file.

EXIT CODES, one meaning each (codex round 1 on PR #67, finding 2). Six call sites
in linear-worker.sh route on these, so an exit that means two things silently
drops a page:

  0  the op succeeded. For claim-flag: claimed HERE, first time -- go page.
  1  claim-flag ONLY: already claimed on an earlier run -- stay quiet.
  2  NOTHING WAS WRITTEN, and the cause is not contention. Two populations:
     a usage error (unknown op, wrong arity), and -- since the round-3
     catch-all in main() -- ANY unanticipated failure, e.g. an OSError from
     mkstemp / os.replace / json.dump on a full or read-only filesystem.
  3  NOTHING WAS WRITTEN because the lock could not be taken.

READ 2 AS OPEN-ENDED, NOT AS "a typo in a call site" (codex round 4, minor).
This line used to say only "usage error", which reads as a bounded, transient,
fix-the-invocation class -- and linear-worker.sh's page_once cited that reading
to justify paging anyway on 2 and 3, calling it "bounded". It is not bounded.
A read-only filesystem exits 2 on every run forever, so the caller's page fired
on every run forever, and at the stuck call site that page is a permanent Linear
comment. The catch-all is still right (see main(): the safe default for the
unanticipated is the code that says NOTHING WAS WRITTEN, never 1). What was
wrong was a doc that undersold what it covers, so keep this description as wide
as the except clause actually is.

The difference callers act on is not 2-vs-3 but WHETHER A LATER RUN RECOVERS:
3 leaves the flag unclaimed and the lock frees in milliseconds, so the next run
claims and pages. 2 can persist indefinitely, so no later run claims or pages
either.

Arity is validated up front for exactly this reason: `claim-flag ASK-1` with the
flag omitted used to raise IndexError and exit 1, and 1 is the one code that
tells the caller to stay quiet. A crash that reads as "already paged" is the
silent stall wearing the mechanism built to prevent it.
"""
import fcntl
import json
import os
import sys
import tempfile
import time
import traceback

# TWO CAPS, whichever comes first. LOCK_TIMEOUT is what a caller actually cares
# about -- "how long before this refuses" -- and it is measured, so it stays true
# no matter what a sleep really costs. LOCK_TRIES only bounds the iteration count
# so a wedged clock cannot spin; it is overridable ONLY so the suite can make the
# contended path sub-second. Production sets neither, same posture as converge.sh's
# KIPI_RECEIPT_LOCK_TRIES.
LOCK_TIMEOUT = float(os.environ.get("KIPI_ATTEMPTS_LOCK_TIMEOUT") or 10.0)
LOCK_TRIES = int(os.environ.get("KIPI_ATTEMPTS_LOCK_TRIES") or 1000)
LOCK_SLEEP = 0.1


class LockUnavailable(Exception):
    """The lock could not be taken. NEVER swallowed: the caller writes nothing."""


class Usage(Exception):
    """Wrong op or wrong arity. Exits 2, never 1: see the exit-code table above."""


def _same_file(fh, lock):
    """True when the handle we locked is still the file at `lock`.

    Holding a lock on an inode that has been unlinked out from under us means
    holding nothing anyone else can see -- the exact two-inodes-one-path race
    that makes a file lock useless.
    """
    try:
        live = os.stat(lock)
    except OSError:
        return False
    held = os.fstat(fh.fileno())
    return (live.st_ino, live.st_dev) == (held.st_ino, held.st_dev)


def _take_lock(lock):
    """Return an open handle holding an exclusive flock, or None if it timed out.

    Opened "a": never truncates, so a concurrent holder's file is untouched, and
    creates the file when it is absent.
    """
    parent = os.path.dirname(lock) or "."
    os.makedirs(parent, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT
    for attempt in range(LOCK_TRIES):
        if attempt and time.monotonic() >= deadline:
            return None
        # A DIRECTORY here is what the original `os.mkdir` lock leaves when its
        # run is killed. It cannot be opened, so the first instance to take this
        # upgrade with one on disk would never count an attempt again. It also
        # cannot be held by anything: no flock lives on it, and the writer that
        # made it released by path, so it was never a reliable claim to begin
        # with. Clearing it is the only outcome that is not a permanent wedge.
        if os.path.isdir(lock):
            try:
                os.rmdir(lock)
                sys.stderr.write(
                    "attempts-ledger: cleared the leftover pre-flock lock DIRECTORY at %s\n"
                    % lock)
            except OSError:
                pass
        try:
            fh = open(lock, "a")
        except OSError as exc:
            raise LockUnavailable(
                "the lock at %s cannot be opened (%s)" % (lock, exc))
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            time.sleep(LOCK_SLEEP)
            continue
        if _same_file(fh, lock):
            return fh
        # Someone replaced the path while we were taking it. What we hold is an
        # orphan inode nobody else will ever contend on, so it guards nothing.
        fh.close()
        if attempt + 1 < LOCK_TRIES:
            time.sleep(LOCK_SLEEP)
    return None


def _drop_lock(fh):
    """Close the handle. The kernel drops the flock with it -- and would drop it
    anyway if this process died, which is what makes a corpse lock impossible.
    The lock FILE is deliberately left in place: unlinking it is what lets two
    runs end up holding two different inodes at one path."""
    try:
        fh.close()
    except OSError:
        pass


def _mutate(path, fn):
    """Take the lock, apply fn(d) -> bool(changed), write atomically.

    Raises LockUnavailable rather than proceeding: see invariant 1 above.
    """
    lock = path + ".lock"
    fh = _take_lock(lock)
    if fh is None:
        raise LockUnavailable(
            "another run still holds the lock at %s. NOT entering the transaction -- "
            "a run that cannot take the lock writes nothing rather than racing the "
            "run that can." % lock)
    try:
        try:
            with open(path) as fp:
                d = json.load(fp)
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        if not fn(d):
            return False
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent)
        try:
            with os.fdopen(fd, "w") as fp:
                json.dump(d, fp, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    finally:
        _drop_lock(fh)


def op_bump(d, issue, counter, ts_key, ts, why=None):
    e = d.setdefault(issue, {})
    e[counter] = e.get(counter, 0) + 1
    if ts_key:
        e[ts_key] = ts
    if why is not None:
        e["why"] = why
    return True


def op_clear(d, issue, keys):
    e = d.get(issue)
    # Nothing to clear is NOT a write. Rewriting the file for a no-op would touch
    # mtime on every scheduled run and make "when did this last change" useless.
    if not e or not any(e.get(k) for k in keys):
        return False
    for k in keys:
        e.pop(k, None)
    return True


def op_capout(d, issue, why, ts):
    """Record that converge stopped this issue at its round cap.

    KEYED PER ISSUE, and that is the whole point (ASK-871). Every other bound in
    this loop keys on a PR and a head sha -- deliberately, so a PR that pushes a
    real fix earns a fresh attempt. Nothing bounded DISPATCHES PER ISSUE, so on
    2026-08-16 ASK-830 spent six converge rounds and five Opus reviews in one
    morning: converge capped out at 15:59, the redrive handed the same issue back
    at 16:14, and each round moved the head, so every per-sha cap read as fresh.

    ALWAYS A WRITE, never a claim. `op_claim` answers False the second time, and
    a caller reading that as "nothing to do" would leave a stale `capout_why`
    from an older cap-out sitting next to a newer one. A cap-out that happens
    twice is two facts, and the later one is the true one.
    """
    e = d.setdefault(issue, {})
    e["capout"] = True
    e["capout_at"] = ts
    e["capout_why"] = why
    return True


def op_claim(d, issue, flag):
    """True the FIRST time this flag is claimed, False every time after."""
    e = d.setdefault(issue, {})
    if e.get(flag):
        return False
    e[flag] = True
    return True


def main(argv):
    if len(argv) < 3:
        print("usage: attempts-ledger.py <ledger-path> <op> [args...]", file=sys.stderr)
        return 2
    path, op, rest = argv[1], argv[2], argv[3:]
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        return _run(path, op, rest, ts)
    except Usage as exc:
        # 2, never 1. For claim-flag, 1 means "already claimed, stay quiet", so a
        # bad invocation answering 1 would suppress a page nothing recorded.
        sys.stderr.write("attempts-ledger: %s\n" % exc)
        return 2
    except LockUnavailable as exc:
        # 3, deliberately not 1 and never 0. For claim-flag, 1 already means
        # "already claimed, stay quiet" and 0 means "claimed, go page" -- a lock
        # failure is neither. Nothing was claimed, so the next run can still
        # claim it; answering 0 would page off a flag no file records, and
        # answering 1 would retire a page that never fired.
        sys.stderr.write("attempts-ledger: `%s` wrote nothing -- %s\n" % (op, exc))
        return 3
    except Exception:
        # 2, and the catch-all is the point (codex round 2 on PR #67, minor 3).
        # This block used to name only the two exceptions above, so an OSError
        # from mkstemp / os.replace / json.dump on a full or read-only filesystem
        # escaped as an uncaught exception -- and Python exits 1 on those. For
        # claim-flag, 1 is the ONE code that means "already claimed on a prior
        # run, stay quiet". So a write that failed hard read as a page already
        # sent, for a flag no file records, which means no later run retires it
        # either. That is the same silent drop findings 2 and 3 closed, arriving
        # through the one door still left open.
        #
        # Enumerating OSError instead would leave the next unnamed exception on
        # 1. The safe default for "something we did not anticipate" is the code
        # that says NOTHING WAS WRITTEN, so the caller pages and says so.
        # The traceback still goes to stderr, because a swallowed error here is
        # how a real bug becomes a shrug.
        traceback.print_exc()
        sys.stderr.write(
            "attempts-ledger: `%s` failed unexpectedly and wrote nothing (exit 2)\n" % op)
        return 2


def _args(op, rest, want):
    """Exactly `want` arguments, or exit 2. An IndexError here would exit 1, and
    1 is the code that tells six call sites to stay quiet."""
    if len(rest) != want:
        raise Usage(
            "`%s` takes %d argument(s), got %d (%r). Nothing was written."
            % (op, want, len(rest), rest))
    return rest


def _run(path, op, rest, ts):
    if op == "get":                       # get <issue> <key> [default]
        if len(rest) not in (2, 3):
            raise Usage("`get` takes <issue> <key> [default], got %r" % (rest,))
        issue, key = rest[0], rest[1]
        default = rest[2] if len(rest) > 2 else "0"
        try:
            with open(path) as fh:
                d = json.load(fh)
        except Exception:
            d = {}
        print(d.get(issue, {}).get(key, default))
        return 0

    if op == "bump-attempt":              # bump-attempt <issue> <why>
        issue, why = _args(op, rest, 2)
        _mutate(path, lambda d: op_bump(d, issue, "count", "last", ts, why))
        return 0
    if op == "bump-conflict":             # bump-conflict <issue>
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_bump(d, issue, "conflict_rounds", "last_conflict", ts))
        return 0
    if op == "bump-drift":                # bump-drift <issue>
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_bump(d, issue, "drift_rounds", "last_drift", ts))
        return 0
    if op == "clear-conflict":            # clear-conflict <issue>
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_clear(d, issue, ("conflict_rounds", "conflict_paged", "last_conflict")))
        return 0
    if op == "clear-automerge":           # clear-automerge <issue>
        # The op my previous edit claimed to add and did not. The shell side was
        # rewritten to call it, the direct-write count went to 0, and I reported
        # "routed" -- but nothing here answered the call, so clear_automerge_pages
        # became a no-op exiting 2. Consequence: the once-only auto-merge page
        # could never be cleared, so a PR that was armed, unarmed, then armed again
        # went PERMANENTLY SILENT. Caught by test-severity-floor, not by me: I had
        # verified the caller and the write count, never the round trip.
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_clear(
            d, issue, ("automerge_unarmed_paged", "automerge_unknown_paged")))
        return 0
    if op == "clear-drift":               # clear-drift <issue>
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_clear(d, issue, ("drift_rounds", "drift_paged", "last_drift")))
        return 0
    if op == "clear-flag":                # clear-flag <issue> <flag>
        # THE UNDO FOR A FLAG CLAIMED BY MISTAKE, and it exists because one was
        # (ASK-352). review-redrive.py's `select` was documented read-only and
        # called ci-redrive's `ledger_recorded`, which is a WRITE wearing a
        # reader's name -- it runs claim-flag and answers True on rc 0 (just
        # claimed) as well as rc 1 (already claimed). One read-only invocation
        # claimed 14 flags, and a claimed flag suppresses the dispatch it stands
        # for, so 13 PRs were silently made ineligible for a redrive that had
        # never happened.
        #
        # Without this op the only remedies were hand-editing the ledger --
        # around the single writer and the lock, which is how two runs corrupt it
        # -- or renaming the flag scheme to strand the bad rows as permanent
        # garbage. Both are worse than an op that goes through _mutate like
        # every other write. Same family as clear-conflict / clear-drift /
        # clear-automerge above.
        #
        # Idempotent: clearing an unset flag is 0 and writes nothing meaningful,
        # so a caller does not have to know the current state to be correct.
        issue, flag = _args(op, rest, 2)
        _mutate(path, lambda d: op_clear(d, issue, (flag,)))
        return 0

    if op == "record-capout":             # record-capout <issue> <why>
        # THE MACHINE-READABLE HALF OF A CAP-OUT (ASK-871). converge.sh's exit-2
        # path used to `say` a log line and Slack the founder and stop, so the
        # only two consumers that could re-enter the issue -- ci-redrive.py and
        # review-redrive.py -- had no way to learn its rounds were spent. This
        # is deliberately the SAME ledger those two already read rather than a
        # new state file: a second store for one issue's budget is how the four
        # budgets above ended up racing in the first place.
        issue, why = _args(op, rest, 2)
        _mutate(path, lambda d: op_capout(d, issue, why, ts))
        return 0
    if op == "clear-capout":              # clear-capout <issue>
        # THE HUMAN'S WAY OUT, and it ships in the same change as the park on
        # purpose. A cap-out nobody can clear is a permanent park, and a park
        # with no exit is a quieter version of the 29-hour outage the redrives
        # were built to end. The cap-out page names this command.
        (issue,) = _args(op, rest, 1)
        _mutate(path, lambda d: op_clear(d, issue, ("capout", "capout_at", "capout_why")))
        return 0

    if op == "claim-flag":                # claim-flag <issue> <flag> -> 0 first time, 1 after
        issue, flag = _args(op, rest, 2)
        claimed = _mutate(path, lambda d: op_claim(d, issue, flag))
        return 0 if claimed else 1

    print("unknown op: %s" % op, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
