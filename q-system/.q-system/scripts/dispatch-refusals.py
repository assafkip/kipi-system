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

Usage (stdout is the dispatcher's input, one line per action):
  dispatch-refusals.py refused <repo> <check> [<check> ...]
      Records this tick's refused checks for <repo>. Prints `DUE <check>` for each
      check refused for at least the threshold, and `CLEARED <check>` for each check
      this repo was refused on before that is no longer failing.
  dispatch-refusals.py passed <repo>
      The repo cleared preflight. Drops its rows and prints `CLEARED <check>` for each.

Env: KIPI_DISPATCH_REFUSALS (state path), KIPI_DISPATCH_REFUSAL_HOURS (default
12), KIPI_DISPATCH_NOW (epoch seconds; the test clock).
"""
from __future__ import annotations

import fcntl
import os
import sys
import tempfile
import time

DEFAULT_PATH = os.path.expanduser("~/.config/kipi/dispatch-refusals.tsv")
DEFAULT_HOURS = 12.0

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED_FIXTURE = 4


def state_path() -> str:
    return os.environ.get("KIPI_DISPATCH_REFUSALS") or DEFAULT_PATH


def now() -> int:
    raw = os.environ.get("KIPI_DISPATCH_NOW", "")
    return int(raw) if raw.isdigit() else int(time.time())


def threshold_seconds() -> float:
    try:
        return float(os.environ.get("KIPI_DISPATCH_REFUSAL_HOURS", DEFAULT_HOURS)) * 3600
    except ValueError:
        return DEFAULT_HOURS * 3600


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


def apply(rows: list, op: str, repo: str, checks: list, t: int, limit: float):
    """Pure: the new rows and the action lines. Other repos are never touched."""
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
        first = mine[check][2] if check in mine else t
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
        new, out = apply(rows, op, repo, checks, now(), threshold_seconds())
        if new != rows:
            write_rows(path, new)
    for line in out:
        print(line)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
