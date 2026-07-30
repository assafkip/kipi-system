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

CONCURRENCY. mkdir is the mutex because it is atomic on POSIX and needs no
flock; macOS ships no flock, and this fleet runs on both kernels. The write is
temp-then-os.replace so a crash mid-write cannot leave a truncated ledger, which
would read as `{}` and silently reset every budget in the file.

A lock we cannot take within the timeout is TAKEN ANYWAY rather than skipping
the mutation. A dropped bump is the defect this file exists to prevent, and a
stale lock left by a killed worker is far likelier than a live worker holding it
for ten seconds.
"""
import json
import os
import sys
import tempfile
import time

LOCK_TRIES = 100
LOCK_SLEEP = 0.1


def _mutate(path, fn):
    """Take the lock, apply fn(d) -> bool(changed), write atomically."""
    lock = path + ".lock"
    for _ in range(LOCK_TRIES):
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            time.sleep(LOCK_SLEEP)
        except OSError:
            break          # unwritable dir: proceed unlocked rather than lose the count
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
        try:
            os.rmdir(lock)
        except Exception:
            pass


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
