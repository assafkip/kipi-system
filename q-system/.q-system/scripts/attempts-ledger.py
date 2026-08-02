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

CONCURRENCY. No flock: macOS ships none and this fleet runs on both kernels, so
the mutex is a file whose creation is O_EXCL. The write is temp-then-os.replace
so a crash mid-write cannot leave a truncated ledger, which would read as `{}`
and silently reset every budget in the file.

THE LOCK WAS WORSE THAN NO LOCK (ASK-286, sp-626e9452, back-ported from the
version PR #42 proved in converge.sh `receipt_transaction`). It used to PROCEED
on timeout -- break out of the retry loop and enter the transaction holding
nothing -- and its release removed the lock BY PATH. Together: a run that times
out believes it is serialized, walks in, and on the way out deletes the live
lock of the run that actually holds it. Both runs are then inside one
read-decide-write, which is precisely what this file exists to stop.

It also propagated. On 2026-08-02 an agent was told to reuse an in-repo lock
rather than invent a fourth, copied THIS one including both defects, and cited
the source as justification. Citing a pattern is not verifying it.

FOUR INVARIANTS, all absent from the version this replaces:

  1. A TIMEOUT RETURNS FAILURE. The caller does no work and says so. A skipped
     increment is recoverable -- the next scheduled run retries, and the run
     that DID hold the lock is counting. Two runs inside one read-decide-write
     is not recoverable.
  2. A RELEASE REMOVES ONLY A LOCK CARRYING THIS RUN'S OWN TOKEN, never one
     identified by path alone.
  3. THE LOCK IS CREATED ALREADY CARRYING ITS OWNER. The token is written into a
     temp file first and `os.link` publishes it at the lock path atomically, so
     the lock never exists un-attributable for even an instant. mkdir left that
     window open, and a run killed inside it left a lock nothing could ever own.
  4. STALE LOCKS BREAK ON OWNER LIVENESS, so refusing to force does not let a
     corpse wedge every future write. A lock whose pid is gone is broken; so is
     one that carries no attributable owner at all -- an empty file, or the
     leftover DIRECTORY a pre-fix worker killed mid-transaction leaves behind,
     since by invariant 3 this writer can never produce either.

RESIDUAL, named rather than papered over: the token is re-read immediately
before a break, but that is still a narrow TOCTOU window, and pid reuse can make
a corpse look live. Both degrade in the SAFE direction -- either the write is
skipped and says so, or a break happens that the re-read guard makes vanishingly
unlikely. Neither can silently delete a live run's lock, which is the property
that was actually broken.
"""
import json
import os
import random
import sys
import tempfile
import time

# Overridable ONLY so the suite can assert the contended path without a 10s sleep
# per case. Production never sets it, same posture as converge.sh's
# KIPI_RECEIPT_LOCK_TRIES.
LOCK_TRIES = int(os.environ.get("KIPI_ATTEMPTS_LOCK_TRIES") or 100)
LOCK_SLEEP = 0.1


class LockUnavailable(Exception):
    """The lock could not be taken. NEVER swallowed: the caller writes nothing."""


def _new_token():
    return "%d:%d:%d" % (os.getpid(), int(time.time()), random.randrange(1 << 30))


def _read_lock(lock):
    """The token a lock carries, or "" if it carries none (missing, empty, or a
    stale directory from the pre-ASK-286 writer)."""
    try:
        with open(lock) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _publish_lock(lock, token):
    """Create `lock` already carrying `token`, or raise FileExistsError.

    os.link is the atomic publish: the content is complete in the temp file
    before the name exists, so there is no instant at which the lock is present
    without an owner. Raises OSError for an unwritable parent -- which is a
    refusal to write, not a licence to proceed unlocked.
    """
    parent = os.path.dirname(lock) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(token + "\n")
        os.link(tmp, lock)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _owner_is_alive(seen):
    """True unless the lock names a pid that is provably gone.

    A lock carrying no parseable pid is NOT alive: nothing can ever prove it
    owns the lock, so honouring it means waiting forever.
    """
    pid = seen.split(":", 1)[0]
    if not pid.isdigit() or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True            # exists but not ours to signal
    return True


def _break_if_dead(lock):
    """Remove a lock whose owner is gone. Leaves a live holder's lock alone."""
    seen = _read_lock(lock)
    if _owner_is_alive(seen):
        return
    # Re-read: a lock that changed hands between the liveness check and here
    # belongs to someone else now and is not ours to break.
    if _read_lock(lock) != seen:
        return
    try:
        if os.path.isdir(lock):
            os.rmdir(lock)
        else:
            os.unlink(lock)
    except OSError:
        return
    sys.stderr.write(
        "attempts-ledger: broke the lock at %s -- it was left by a run that is no "
        "longer alive\n" % lock)


def _take_lock(lock, token):
    for _ in range(LOCK_TRIES):
        try:
            _publish_lock(lock, token)
            return True
        except FileExistsError:
            _break_if_dead(lock)
        except OSError as exc:
            raise LockUnavailable(
                "the lock at %s cannot be created (%s)" % (lock, exc))
        time.sleep(LOCK_SLEEP)
    return False


def _drop_lock(lock, token):
    """Only ever removes a lock carrying this run's token. A release that trusts
    the path deletes whichever run happens to hold it."""
    if _read_lock(lock) != token:
        sys.stderr.write(
            "attempts-ledger: NOT releasing %s -- it no longer carries this run's "
            "token, so it belongs to another run now\n" % lock)
        return
    try:
        os.unlink(lock)
    except OSError:
        pass


def _mutate(path, fn):
    """Take the lock, apply fn(d) -> bool(changed), write atomically.

    Raises LockUnavailable rather than proceeding: see invariant 1 above.
    """
    lock = path + ".lock"
    token = _new_token()
    if not _take_lock(lock, token):
        raise LockUnavailable(
            "another run still holds the lock at %s. NOT entering the transaction -- "
            "a run that cannot take the lock writes nothing rather than racing the "
            "run that can." % lock)
    try:
        try:
            with open(path) as fh:
                d = json.load(fh)
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
            with os.fdopen(fd, "w") as fh:
                json.dump(d, fh, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    finally:
        _drop_lock(lock, token)


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
    except LockUnavailable as exc:
        # 3, deliberately not 1 and never 0. For claim-flag, 1 already means
        # "already claimed, stay quiet" and 0 means "claimed, go page" -- a lock
        # failure is neither. Nothing was claimed, so the next run can still
        # claim it; answering 0 would page off a flag no file records, and
        # answering 1 would retire a page that never fired.
        sys.stderr.write("attempts-ledger: `%s` wrote nothing -- %s\n" % (op, exc))
        return 3


def _run(path, op, rest, ts):
    if op == "get":                       # get <issue> <key> [default]
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
        _mutate(path, lambda d: op_bump(d, rest[0], "count", "last", ts, rest[1]))
        return 0
    if op == "bump-conflict":             # bump-conflict <issue>
        _mutate(path, lambda d: op_bump(d, rest[0], "conflict_rounds", "last_conflict", ts))
        return 0
    if op == "bump-drift":                # bump-drift <issue>
        _mutate(path, lambda d: op_bump(d, rest[0], "drift_rounds", "last_drift", ts))
        return 0
    if op == "clear-conflict":            # clear-conflict <issue>
        _mutate(path, lambda d: op_clear(d, rest[0], ("conflict_rounds", "conflict_paged", "last_conflict")))
        return 0
    if op == "clear-automerge":           # clear-automerge <issue>
        # The op my previous edit claimed to add and did not. The shell side was
        # rewritten to call it, the direct-write count went to 0, and I reported
        # "routed" -- but nothing here answered the call, so clear_automerge_pages
        # became a no-op exiting 2. Consequence: the once-only auto-merge page
        # could never be cleared, so a PR that was armed, unarmed, then armed again
        # went PERMANENTLY SILENT. Caught by test-severity-floor, not by me: I had
        # verified the caller and the write count, never the round trip.
        _mutate(path, lambda d: op_clear(
            d, rest[0], ("automerge_unarmed_paged", "automerge_unknown_paged")))
        return 0
    if op == "clear-drift":               # clear-drift <issue>
        _mutate(path, lambda d: op_clear(d, rest[0], ("drift_rounds", "drift_paged", "last_drift")))
        return 0
    if op == "claim-flag":                # claim-flag <issue> <flag> -> exit 0 first time, 1 after
        claimed = _mutate(path, lambda d: op_claim(d, rest[0], rest[1]))
        return 0 if claimed else 1

    print("unknown op: %s" % op, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
