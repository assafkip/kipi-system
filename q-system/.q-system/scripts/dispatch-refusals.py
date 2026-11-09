#!/usr/bin/env python3
"""THE single writer of dispatch-refusals.tsv: how long each repo has been refused.

WHY THIS EXISTS (ASK-3958). kipi-dispatch.sh's pick_list() runs repo-preflight.sh
on every opted-in repo each tick and drops a refused one from the rotation. Until
this file it logged one "preflight REFUSED" line per tick and nothing else, so a
refusal that never heals left that repo's tickets with no consumer: 469 identical
lines for one repo in one run, and no ticket.

WHY A PERSISTENCE THRESHOLD AND NOT THE 2ND REFUSAL. Measured on dispatch.log
(2026-07-28 to 2026-11-08): 25 refusal runs on live checks, all `hooks` parity,
the longest 7.6h, none over 12h. Each one healed at the next skeleton
propagation. Filing at the 2nd refused tick would have filed all 25, which is
detector volume, not 25 problems. 12h sits above the longest measured transient
and still catches a permanent refusal inside half a day.

WHY NO TICKET PARKING. A refused repo's tickets are not stuck in a way a park
fixes: pick_list re-tests the repo every tick, so the pass itself is the event
that puts them back. A `repo-refused` park would need its own unpark consumer,
which is a new dead end.

WHY A KILL SWITCH IS NOT A REFUSAL HERE (PR #681 r1 major). `.kipi-no-dispatch`
is a decision. Its writers live outside this repo: ~/.config/kipi/usage-pacer.py
writes one starting "PACER usage pause", and the 2026-11-08 usage pause wrote
ones starting "D35 usage pause" (~/.config/kipi/d35-resume.sh lifts those). A
repo's own permanent one is the client's "stay out". Clocking it filed a ticket
at 12h, and again every 24h, telling Sana to undo the gate that protects client
work. So it records nothing and files nothing. preflight stops at the kill
switch, so that tick says nothing about any other check either: the repo's other
rows are left as they were, neither cleared nor advanced.

That last step leans on preflight printing the kill switch as its ONLY FAIL line
(repo-preflight.sh exits right after it). test-repo-preflight.sh case 2a pins it
(PR #681 r2): a kill-switched repo that would also fail `remote` must print one
FAIL line. If that shape ever changes, case 2a goes red before a real fault
sharing a tick with the kill switch can lose its clock here.

WHY A 48H GAP BOUND (PR #681 r1 minor). The threshold reads `first`, so two
refusals 30 days apart (a row off and on again, a dispatcher down) looked like
30 days of refusal. A row whose `last` is older than the gap bound restarts its
clock. The bound is 48h, not a tick or two, because pick_list does not run every
tick: measured on dispatch.log (2026-08-14 to 2026-11-09, 1971 pick_list runs),
the daily cap stops it ~23.3h a day (max 24.1h, one 34.5h outlier). A bound under
that restarts every clock daily and nothing is ever filed. The cost: a check that
heals and breaks again inside an unobserved day still counts as one episode. That
is one ticket, cleared by the next pass.

Usage (stdout is the dispatcher's input, one line per action):
  dispatch-refusals.py refused <repo> <check> [<check> ...]
      Records this tick's refused checks for <repo>. Prints `DUE <check>` for each
      check refused for at least the threshold, and `CLEARED <check>` for each check
      this repo was refused on before that is no longer failing.
  dispatch-refusals.py passed <repo>
      The repo cleared preflight. Drops its rows and prints `CLEARED <check>` for each.

Env: KIPI_DISPATCH_REFUSALS (state path), KIPI_DISPATCH_REFUSAL_HOURS (default
12), KIPI_DISPATCH_REFUSAL_GAP_HOURS (default 48), KIPI_DISPATCH_NOW (epoch
seconds; the test clock).
"""
from __future__ import annotations

import fcntl
import os
import sys
import tempfile
import time

DEFAULT_PATH = os.path.expanduser("~/.config/kipi/dispatch-refusals.tsv")
DEFAULT_HOURS = 12.0
DEFAULT_GAP_HOURS = 48.0
# Checks that are a decision, not a fault. See the docstring.
DELIBERATE = frozenset({"kill-switch"})

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED_FIXTURE = 4


def state_path() -> str:
    return os.environ.get("KIPI_DISPATCH_REFUSALS") or DEFAULT_PATH


def now() -> int:
    raw = os.environ.get("KIPI_DISPATCH_NOW", "")
    return int(raw) if raw.isdigit() else int(time.time())


def hours_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default)) * 3600
    except ValueError:
        return default * 3600


def threshold_seconds() -> float:
    return hours_env("KIPI_DISPATCH_REFUSAL_HOURS", DEFAULT_HOURS)


def gap_seconds() -> float:
    return hours_env("KIPI_DISPATCH_REFUSAL_GAP_HOURS", DEFAULT_GAP_HOURS)


def read_rows(path: str) -> list:
    """(repo, check, first, last) rows. A malformed line is dropped, never fatal:
    a bad row costs one refusal its clock, a crash costs every repo its consumer."""
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 4 and parts[2].isdigit() and parts[3].isdigit():
                    rows.append((parts[0], parts[1], int(parts[2]), int(parts[3])))
    except FileNotFoundError:
        pass
    return rows


def write_rows(path: str, rows: list) -> None:
    # Temp then os.replace, so a reader never sees half a file (attempts-ledger.py).
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".dispatch-refusals.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write("\t".join(str(x) for x in r) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply(rows: list, op: str, repo: str, checks: list, t: int, limit: float,
          gap: float = DEFAULT_GAP_HOURS * 3600):
    """Pure: the new rows and the action lines. Other repos are never touched."""
    if op == "refused" and DELIBERATE.intersection(checks):
        return rows, []
    mine = {r[1]: r for r in rows if r[0] == repo}
    others = [r for r in rows if r[0] != repo]
    out = []
    keep = []
    wanted = [] if op == "passed" else list(dict.fromkeys(checks))
    for check in sorted(set(mine) - set(wanted)):
        out.append(f"CLEARED {check}")
    for check in wanted:
        # A check keeps its OWN first-seen time. A repo refused on `hooks` for 11h
        # that starts failing `remote` has not been refused on `remote` for 11h.
        prev = mine.get(check)
        first = prev[2] if prev and t - prev[3] <= gap else t
        keep.append((repo, check, first, t))
        if t - first >= limit:
            out.append(f"DUE {check}")
    return others + keep, out


def main(argv: list) -> int:
    if len(argv) < 2 or argv[0] not in ("refused", "passed"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return EXIT_USAGE
    op, repo, checks = argv[0], argv[1], argv[2:]
    if op == "refused" and not checks:
        print("refused needs at least one check", file=sys.stderr)
        return EXIT_USAGE
    path = state_path()
    # THE FIXTURE CHOKEPOINT. A suite must set KIPI_DISPATCH_REFUSALS; a test that
    # forgot would otherwise reset the live clock of a repo refused in production.
    if os.environ.get("PYTEST_CURRENT_TEST") and os.path.realpath(path) == os.path.realpath(DEFAULT_PATH):
        print("dispatch-refusals: REFUSED under pytest on the live path", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # flock on a sibling lock file, released by the kernel on close or death.
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows = read_rows(path)
        new, out = apply(rows, op, repo, checks, now(), threshold_seconds(), gap_seconds())
        if new != rows:
            write_rows(path, new)
    for line in out:
        print(line)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
