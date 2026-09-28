#!/usr/bin/env python3
"""Per-filer token bucket + the "recorded, not ticketed" list (ASK-2012, Step 6).

THE NUMBER THIS EXISTS FOR. Captured off the live ASK board on 2026-09-28, the
28-day window: 996 issues created, 152 completed. The `alert` filer alone
created 507 of them and 5 were ever completed -- one hour of it produced 105
tickets, one day produced 114. Inflow is machine-speed and outflow is a person,
so the board grows monotonically and a queue that only grows stops being read.
That is the same failure alert-to-linear.py was built to stop in Slack, arriving
one surface later: the dedup there collapses ONE repeating condition, and says
nothing about 105 DIFFERENT conditions in an hour.

SO THE FIX IS A BUDGET, NOT A FILTER. Nothing is judged and nothing is dropped.
A filer over its budget still gets its finding written down -- to the recorded
list here -- and the finding becomes a ticket the moment it proves it is not
noise by happening AGAIN. A one-off burst costs a list row. A real, repeating
failure costs a ticket, which is what a ticket is for.

FOUR RULES, in the order decide() applies them:

  1. PAUSED beats everything. A filer that creates more than it closes over 7
     days is paused by `reconcile`; while paused it creates nothing at all.
  2. RECURRENCE beats the cap. A fingerprint already on the list, seen again,
     is promoted to a ticket even with an empty bucket. A cap that could
     swallow a repeating failure would be a worse defect than the flood.
  3. A free token -> ticket, and the token is spent.
  4. No token -> recorded, not ticketed. Exit 0, the caller says so out loud.

A promotion SPENDS a token without CHECKING one. The bucket measures creates and
a promotion is a create, so not recording it would make the tripwire and the
hourly count lie; checking it would let a flood of first-sights starve the one
path that must always work.

HOW A "FILER" IS IDENTIFIED. No producer identity exists on the alert path today
-- ~30 call sites across six repos reach it and none of them name themselves. So
filer_for() is a ladder in alert-to-linear.project_candidates' own idiom, and no
rung invents anything: an explicit env statement, else the `[label]` repo prefix
the callers already write, else the chokepoint's own name. Coarse on purpose. A
ladder that guessed a producer would cap the wrong one.

WHERE THE STATE LIVES, and why not in a repo: `~/.cache/kipi/filer-cap/`. Carried
from alert-to-linear._state_dir (ASK-603) -- state written inside a project
becomes an uncommitted file, which is a thing the fleet alerts ON, which would
rewrite the state, which alerts again.

NEVER RAISES ON THE DECIDE PATH. This is called from inside alert-to-linear.py,
whose whole contract is that a secondary failure must never cost the primary
alert. Every failure here resolves to "ticket" -- the pre-ASK-2012 behaviour --
because a broken budget must fail OPEN. A cap that silences the fleet when its
own cache is unreadable is strictly worse than no cap.

CLI:
  filer_cap.py list [--filer F]            what is recorded and not ticketed
  filer_cap.py reconcile [--apply]         the 7-day creates-vs-closes tripwire
  filer_cap.py replay <payload.json>       ASK-2012's check: ticket vs listed
  filer_cap.py reset --filer F             clear one filer's bucket and list
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime
import fcntl
import json
import os
import re
import sys

# --- the calibrated numbers --------------------------------------------------
#
# CALIBRATED AGAINST THE CORPUS THE GATE CLAIMS TO ENCODE, not picked. Measured
# on the 28-day capture (q-system/.q-system/tests/fixtures/filer-cap-replay-28d.json):
#
#   filer          created  completed   p90/hour   peak/hour   completed peak/h,/d
#   alert              507          5          4         105              1,  2
#   radar               34          9         20          20              3,  4
#   fleet-health        13          4          4           4              1,  2
#   lgtm                 3          2          2           2              1,  1
#
# 6/hour sits above every filer's p90 hour except radar's, so an ORDINARY hour is
# unchanged for all of them and the 105-in-an-hour burst is the only thing cut.
# 20/day sits an order of magnitude above the completed-only peak of 2/day.
#
# The floor that matters is not these numbers, it is the replay gate: every
# ticket that was actually worked has to survive the cap. `replay` is that test
# and it is wired in test_filer_cap.py, so changing either number without
# re-running it goes red.
DEFAULT_CAP_HOUR = int(os.environ.get("KIPI_FILER_CAP_HOUR", "6"))
DEFAULT_CAP_DAY = int(os.environ.get("KIPI_FILER_CAP_DAY", "20"))

# A second sighting is the whole promotion rule. Not third: the corpus shows 55
# of 507 alert rows are repeats of a fingerprint, so a threshold of 3 would
# promote almost nothing and the list would become the drop this file refuses
# to be.
PROMOTE_AT = 2

# An entry nobody saw again for two weeks was a one-off. Dropped, not ticketed.
LIST_TTL_DAYS = 14

# The tripwire window from the DoR.
TRIPWIRE_DAYS = 7

# WHICH FILER CLASSES THE CAP ACTUALLY SEES, and the first replay is what taught
# this. Run with no scope at all, the gate failed 92/152: 59 COMPLETED rows in
# the `other` class came out listed. `other` is not a filer -- it is the
# unclassified remainder of the board, and it holds 132 of the 152 tickets
# somebody actually worked. Those are humans, the DoR drafter, prd_runner and
# linear-sync, none of which pass through a chokepoint this issue touches.
#
# That first run is the lesson "calibrate a gate against the corpus it claims to
# encode" arriving in its other form: not a gate too strict for its corpus, a
# gate pointed at the wrong corpus. A shared evaluator that takes no lane
# argument applies the first caller's assumptions to every caller. So the lane
# is explicit here and it is narrow: the capped classes are the ones whose
# create path calls decide().
#
# `alert` is this repo's chokepoint (alert-to-linear.py). chief's class joins
# this set in the same change that wires chief/chief/linear.py:151 -- that file
# is in another repo and is NOT in this one's diff (ASK-2012 spillover).
# `radar` and `lgtm` file through their own paths, uncapped, today.
CAPPED_FILERS = ("alert",)

# THE CHOKEPOINT, and it is a different thing from a bucket. A bucket is keyed by
# filer_for() -- at runtime that is the `[label]` repo prefix, so one chokepoint
# has many buckets (`consulting`, `cole-gtm`, `alert`). The capture's taxonomy
# knows only the CLASS: every row it labels `alert` was created by
# alert-to-linear.py, whatever repo wrote the message.
#
# WHY THAT DISTINCTION IS A DEFECT FIX AND NOT A CONCEPT (PR #465 review round 1,
# major). `reconcile --apply` read the tripwire's verdict, which is keyed by
# class, and called pause() with it -- writing `alert.json` and pausing exactly
# the one bucket whose messages carry no prefix. Every prefixed caller, which is
# most of them, kept filing. So arming the tripwire printed PAUSE and paused
# nothing that files. A pause that reads as protection and stops nothing is worse
# than no pause: it retires the question.
#
# The pause therefore lives at the chokepoint, which is what the tripwire
# measured, and decide() checks it before the bucket's own pause.
DEFAULT_CHOKEPOINT = "alert"

# Which capture classes this repo can actually pause, and it is deliberately
# short. `other` is the board's human work, `radar` and `lgtm` file through their
# own paths, and chief's create is in another repo (ASK-2012 spillover). Pausing
# a class with no chokepoint here would write a pause file nothing consults.
CLASS_TO_CHOKEPOINT = {"alert": DEFAULT_CHOKEPOINT}

HOUR = 3600.0
DAY = 86400.0

TICKET = "ticket"
LISTED = "listed"


# The run id every test bucket hangs under. Exported into the environment by the
# first process that needs it, so a subprocess joins the SAME run rather than
# starting its own -- see _test_run_root.
TEST_RUN_ENV = "KIPI_FILER_CAP_TEST_RUN"

# How long an abandoned test run's dirs are left alone before the sweep takes
# them. Generous: a long suite must never have its own dirs swept mid-run.
_TEST_RUN_SWEEP_AFTER = DAY


def _test_run_root() -> str:
    """The parent dir for THIS pytest run's buckets. Fresh per run, then swept.

    THE PER-RUN NONCE IS THE FIX FOR A REAL DEFECT, not tidiness (PR #465 review
    round 1, major). Keying the dir on the pytest node id alone made it outlive
    the run that created it, so run 2 opened run 1's bucket with its tokens
    already spent: the suite stayed green until the inherited spend reached the
    cap and then went red until it aged out, with nothing in the diff to explain
    it. Reproduced directly in test_the_pytest_state_dir_is_fresh_every_run --
    two processes with one node id, and the second saw the first's marker.

    The nonce is EXPORTED rather than recomputed, because the race suite forks
    writers that must land in their own test's bucket; a child recomputing a
    nonce would get a private dir and the race would stop being a race.

    CLEANED BY AGE, NOT BY atexit. An atexit handler runs in whichever process
    registered it, and a forked child exiting early would delete the parent's
    dirs mid-suite. A sweep of dirs older than a day cannot do that, and it also
    collects what a killed run left behind.
    """
    import tempfile
    run = os.environ.get(TEST_RUN_ENV)
    if not run:
        import uuid
        run = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        os.environ[TEST_RUN_ENV] = run
        _sweep_old_test_runs(tempfile.gettempdir(), run)
    return os.path.join(tempfile.gettempdir(), f"kipi-filer-cap-test-{run}")


def _sweep_old_test_runs(tmp: str, keep: str) -> None:
    """Delete this module's own abandoned test dirs. Never raises, never the
    current run's. Scoped by an exact prefix and by age, so there is no path
    here that can reach anything but a dir this module created."""
    import shutil
    prefix = "kipi-filer-cap-test-"
    now_ = _now()
    try:
        names = os.listdir(tmp)
    except OSError:
        return
    for name in names:
        if not name.startswith(prefix) or name == f"{prefix}{keep}":
            continue
        path = os.path.join(tmp, name)
        try:
            if now_ - os.path.getmtime(path) < _TEST_RUN_SWEEP_AFTER:
                continue
            shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _now() -> float:
    import time
    return time.time()


def state_dir(override: str | None = None) -> str:
    """Where the buckets live. Explicit argument, then env, then the cache.

    THE PYTEST RUNG IS A FIXTURE GUARD, NOT A CONVENIENCE (fable-discipline: a
    test must not touch a live data path). Found by running the change, not by
    reading it: wiring the cap into alert-to-linear.py turned four tests in the
    EXISTING suites red, because they reached the real
    `~/.cache/kipi/filer-cap` -- so a test spent the founder's production budget
    and then inherited whatever the previous test had already spent. Two defects
    in one: a suite that mutates live state, and cross-test bleed that makes a
    green run depend on test order.

    Keyed on the pytest NODE ID under a per-RUN root. The node id alone fixes the
    bleed between two tests and leaves the bleed between two RUNS, which is the
    same defect one level up; _test_run_root carries that half.

    It ISOLATES rather than disables. A guard that turned the cap off under test
    would mean no test ever exercises it, which is how the cap ships inert.
    """
    if override:
        return override
    env = os.environ.get("KIPI_FILER_CAP_DIR")
    if env:
        return env
    node = os.environ.get("PYTEST_CURRENT_TEST")
    if node:
        import hashlib
        key = hashlib.sha256(node.encode("utf-8")).hexdigest()[:16]
        return os.path.join(_test_run_root(), key)
    return os.path.join(os.path.expanduser("~"), ".cache", "kipi", "filer-cap")


_SAFE = re.compile(r"[^a-z0-9._-]+")


def _safe_name(filer: str) -> str:
    """A filename for a filer id. Lowercased and stripped to a known charset.

    A filer id reaches this from a `[label]` prefix in an alert message, which is
    caller-controlled text -- `[../../etc]` has to become a file inside the state
    dir or the cache becomes a write primitive. Collapsing to one charset and
    then taking the basename is two independent refusals of the same thing.
    """
    name = _SAFE.sub("-", (filer or "").strip().lower()).strip("-")
    return os.path.basename(name) or "unknown"


def filer_for(message: str) -> str:
    """Who is filing. A ladder; the first rung that answers wins.

    1. KIPI_ALERT_FILER -- an explicit statement by the caller. The rung that
       lets a producer opt into its own budget instead of sharing the repo's.
    2. The `[label]` prefix the alert callers already write. Coarse (it is the
       repo, not the producer) and honest about being coarse.
    3. `alert` -- the chokepoint's own name, so a message with no prefix shares
       one budget rather than getting an unlimited private one.

    NO RUNG INVENTS A NAME, the same rule alert-to-linear._registry_path follows.
    """
    env = (os.environ.get("KIPI_ALERT_FILER") or "").strip()
    if env:
        return env
    match = re.match(r"^\[([^\]]+)\]", (message or "").strip())
    if match and match.group(1).strip():
        return match.group(1).strip()
    return "alert"


def _path(filer: str, sdir: str) -> str:
    return os.path.join(sdir, f"{_safe_name(filer)}.json")


def _read(filer: str, sdir: str) -> dict:
    try:
        with open(_path(filer, sdir), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(filer: str, sdir: str, data: dict) -> None:
    """Write-then-rename. Carried verbatim from alert-to-linear._write_state:
    a reader catching the file mid-truncate reads `{}`, decides the bucket is
    empty, and the cap is gone for exactly as long as the truncate lasts."""
    try:
        os.makedirs(sdir, exist_ok=True)
        final = _path(filer, sdir)
        tmp = f"{final}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, final)
    except OSError:
        pass


@contextlib.contextmanager
def _lock(filer: str, sdir: str):
    """Serialize read-decide-write for ONE filer. Yields True when held.

    Same reasoning as alert-to-linear._fingerprint_lock and a DIFFERENT key on
    purpose: that lock serializes one fingerprint, this one serializes one
    filer's BUCKET, and two distinct fingerprints from one filer are exactly the
    pair that must not both spend the last token. Keyed per filer rather than
    globally so two filers never queue behind each other.

    A failed acquire yields False, and decide() then fails OPEN (ticket). That
    is the opposite call from the fingerprint lock, and deliberately: there, not
    holding the lock risks a DUPLICATE permanent object, so refusing is cheaper.
    Here, not holding it risks one ticket over budget, and the alternative is
    swallowing an alert. One extra ticket beats one lost alert.
    """
    handle = None
    try:
        os.makedirs(sdir, exist_ok=True)
        handle = open(os.path.join(sdir, f"{_safe_name(filer)}.lock"), "a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        held = True
    except OSError:
        held = False
    try:
        yield held
    finally:
        if handle is not None:
            with contextlib.suppress(OSError):
                if held:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()


def _prune(data: dict, now: float) -> dict:
    """Drop spend outside the day window and list rows unseen for the TTL."""
    spent = [t for t in (data.get("spent") or []) if isinstance(t, (int, float))
             and now - t < DAY]
    listed = {}
    for fp, row in (data.get("listed") or {}).items():
        try:
            last = float(row.get("last_at", 0))
        except (TypeError, ValueError):
            continue
        if now - last < LIST_TTL_DAYS * DAY:
            listed[fp] = row
    out = dict(data)
    out["spent"] = spent
    out["listed"] = listed
    return out


def _pause_until(data: dict, now: float) -> str | None:
    """The one reader of a pause record, used for buckets AND chokepoints."""
    until = data.get("paused_until")
    if until is None:
        return None
    try:
        if float(until) <= now:
            return None
    except (TypeError, ValueError):
        return None
    return str(data.get("paused_reason") or "paused")


def paused_reason(filer: str, now: float, sdir: str) -> str | None:
    return _pause_until(_prune(_read(filer, sdir), now), now)


# --- the chokepoint pause ----------------------------------------------------
#
# A subdirectory rather than a reserved filename in the bucket dir: `filers()`
# lists `*.json` in the state dir and would otherwise report a chokepoint as a
# filer, and _safe_name collapses any prefix a reserved name could use, so
# "chokepoint-alert.json" could collide with a real filer called that.

def _chokepoint_path(name: str, sdir: str) -> str:
    return os.path.join(sdir, "chokepoint", f"{_safe_name(name)}.json")


def _read_chokepoint(name: str, sdir: str) -> dict:
    try:
        with open(_chokepoint_path(name, sdir), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_chokepoint(name: str, sdir: str, data: dict) -> None:
    try:
        final = _chokepoint_path(name, sdir)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        tmp = f"{final}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, final)
    except OSError:
        pass


def chokepoint_paused(name: str, now: float, sdir: str | None = None) -> str | None:
    return _pause_until(_read_chokepoint(name, state_dir(sdir)), now)


def pause_chokepoint(name: str, reason: str, now: float,
                     days: float = TRIPWIRE_DAYS,
                     sdir: str | None = None) -> None:
    """Stop EVERY bucket filing through one chokepoint. What the tripwire means."""
    sdir = state_dir(sdir)
    _write_chokepoint(name, sdir, {"paused_until": now + days * DAY,
                                   "paused_reason": reason, "paused_at": now})


def unpause_chokepoint(name: str, sdir: str | None = None) -> None:
    sdir = state_dir(sdir)
    _write_chokepoint(name, sdir, {})


class Decision:
    """(action, reason). `action` is TICKET or LISTED; `reason` is for the log."""

    __slots__ = ("action", "reason")

    def __init__(self, action: str, reason: str):
        self.action = action
        self.reason = reason

    @property
    def ticket(self) -> bool:
        return self.action == TICKET

    def __repr__(self) -> str:                               # pragma: no cover
        return f"Decision({self.action!r}, {self.reason!r})"


def decide(filer: str, fp: str, now: float, sdir: str | None = None,
           cap_hour: int | None = None, cap_day: int | None = None,
           title: str = "", chokepoint: str = DEFAULT_CHOKEPOINT) -> Decision:
    """Ticket or list, and record whichever it was. Never raises.

    Called ONLY where a create is about to happen -- a caller that is counting
    an existing ticket must not reach here, or the budget would be spent on
    writes that create nothing.
    """
    try:
        return _decide(filer, fp, now, sdir, cap_hour, cap_day, title, chokepoint)
    except Exception as exc:                     # never cost the caller's alert
        return Decision(TICKET, f"cap unavailable ({exc}); failing open")


def exempt(filer: str, now: float, sdir: str | None = None,
           reason: str = "exempt") -> Decision:
    """A create that skips the budget but still SPENDS a token. Never raises.

    The caller decides what is exempt (alert-to-linear's security class); this
    only records it. Spent-not-checked for the same reason a promotion is: the
    bucket measures creates, and a create the tripwire cannot see makes the
    creates-vs-closes ratio understate the flood by exactly the exempt count.
    """
    try:
        sdir = state_dir(sdir)
        with _lock(filer, sdir) as held:
            if held:
                data = _prune(_read(filer, sdir), now)
                data["spent"] = list(data.get("spent") or []) + [now]
                _write(filer, sdir, data)
    except Exception:
        pass
    return Decision(TICKET, reason)


def _decide(filer: str, fp: str, now: float, sdir: str | None,
            cap_hour: int | None, cap_day: int | None, title: str,
            chokepoint: str = DEFAULT_CHOKEPOINT) -> Decision:
    sdir = state_dir(sdir)
    cap_hour = DEFAULT_CAP_HOUR if cap_hour is None else cap_hour
    cap_day = DEFAULT_CAP_DAY if cap_day is None else cap_day

    with _lock(filer, sdir) as held:
        if not held:
            return Decision(TICKET, "could not lock the bucket; failing open")

        data = _prune(_read(filer, sdir), now)

        # 1. Paused beats everything, including recurrence. A filer the tripwire
        #    stopped is one whose output nobody is closing; promoting inside that
        #    window would be the tripwire pausing nothing.
        #
        #    THE CHOKEPOINT IS CHECKED FIRST and the bucket second, because the
        #    tripwire measures the chokepoint. Reading only the bucket is what
        #    made `reconcile --apply` a no-op for every prefixed caller; see
        #    CLASS_TO_CHOKEPOINT.
        reason = _pause_until(_read_chokepoint(chokepoint, sdir), now)
        if reason:
            reason = f"chokepoint {chokepoint} paused: {reason}"
        else:
            reason = _pause_until(data, now)
        if reason:
            data = _list_row(data, fp, now, title)
            _write(filer, sdir, data)
            return Decision(LISTED, f"paused: {reason}")

        # 2. Recurrence beats the cap.
        row = (data.get("listed") or {}).get(fp)
        if row is not None:
            seen = int(row.get("count", 1)) + 1
            if seen >= PROMOTE_AT:
                listed = dict(data.get("listed") or {})
                listed.pop(fp, None)
                data["listed"] = listed
                # Spent, not checked. See the module docstring.
                data["spent"] = list(data.get("spent") or []) + [now]
                _write(filer, sdir, data)
                return Decision(TICKET,
                                f"promoted: fingerprint recorded {seen - 1}x "
                                f"before, seen again")
            data = _list_row(data, fp, now, title)
            _write(filer, sdir, data)
            return Decision(LISTED, f"recorded ({seen} sighting(s))")

        # 3./4. A free token, or the list.
        spent = list(data.get("spent") or [])
        in_hour = sum(1 for t in spent if now - t < HOUR)
        in_day = len(spent)
        if in_hour >= cap_hour:
            data = _list_row(data, fp, now, title)
            _write(filer, sdir, data)
            return Decision(LISTED,
                            f"{filer} is at its hourly cap "
                            f"({in_hour}/{cap_hour}); recorded, not ticketed")
        if in_day >= cap_day:
            data = _list_row(data, fp, now, title)
            _write(filer, sdir, data)
            return Decision(LISTED,
                            f"{filer} is at its daily cap "
                            f"({in_day}/{cap_day}); recorded, not ticketed")

        data["spent"] = spent + [now]
        _write(filer, sdir, data)
        return Decision(TICKET, f"within budget ({in_hour + 1}/{cap_hour} this "
                                f"hour, {in_day + 1}/{cap_day} today)")


def _list_row(data: dict, fp: str, now: float, title: str) -> dict:
    listed = dict(data.get("listed") or {})
    row = dict(listed.get(fp) or {})
    row["count"] = int(row.get("count", 0)) + 1
    row.setdefault("first_at", now)
    row["last_at"] = now
    if title and not row.get("title"):
        row["title"] = title[:110]
    listed[fp] = row
    out = dict(data)
    out["listed"] = listed
    return out


def listed_rows(filer: str, now: float, sdir: str | None = None) -> dict:
    return _prune(_read(filer, state_dir(sdir)), now).get("listed") or {}


def filers(sdir: str | None = None) -> list:
    sdir = state_dir(sdir)
    try:
        return sorted(f[:-5] for f in os.listdir(sdir) if f.endswith(".json"))
    except OSError:
        return []


def pause(filer: str, reason: str, now: float, days: float = TRIPWIRE_DAYS,
          sdir: str | None = None) -> None:
    sdir = state_dir(sdir)
    with _lock(filer, sdir):
        data = _prune(_read(filer, sdir), now)
        data["paused_until"] = now + days * DAY
        data["paused_reason"] = reason
        _write(filer, sdir, data)


def unpause(filer: str, now: float, sdir: str | None = None) -> None:
    sdir = state_dir(sdir)
    with _lock(filer, sdir):
        data = _prune(_read(filer, sdir), now)
        data.pop("paused_until", None)
        data.pop("paused_reason", None)
        _write(filer, sdir, data)


def reconcile_apply(verdict: dict, now: float, sdir: str | None = None) -> list:
    """Arm the tripwire. Returns one (class, action, note) row per class.

    ONLY a class this repo has a chokepoint for is paused, and the rest say so
    out loud. Pausing `other` would write a file nothing reads while printing the
    word PAUSE, which is the shape this function was rewritten to stop.
    """
    out = []
    for name, v in sorted(verdict.items()):
        if not v.get("pause"):
            out.append((name, "ok", ""))
            continue
        chokepoint = CLASS_TO_CHOKEPOINT.get(name)
        if not chokepoint:
            out.append((name, "NOT PAUSED",
                        "no chokepoint in this repo files as this class"))
            continue
        pause_chokepoint(chokepoint,
                         f"created {v.get('created')} and closed {v.get('closed')} "
                         f"over {TRIPWIRE_DAYS} days", now, sdir=sdir)
        out.append((name, "PAUSED", f"chokepoint {chokepoint}, "
                                    f"{TRIPWIRE_DAYS}d"))
    return out


# --- the reader ---------------------------------------------------------------
#
# WITHOUT THIS THE LIST IS A DROP WITH EXTRA STEPS (PR #465 review round 1,
# major). The recorded list had two writers -- decide() and the paused branch --
# and zero readers: no launchd job, no digest, nothing in any brief. The only
# thing that ever touched a row again was the 14-day prune, so a one-off finding
# was recorded and then deleted, which is the drop the list exists to refuse.
#
# The digest is the reader, and it is wired to Sana's queue, not the founder's
# (founder-notifications.md: engineering signal goes to Linear triage). ONE line
# per run, never one per row -- the whole issue is that one ping per finding is
# how a queue stops being read.

# A row this close to its TTL is about to be dropped. The digest exists so that
# does not happen in silence, so the warning window has to be wider than the gap
# between two digest runs (daily).
EXPIRY_WARN_DAYS = 3


def digest(now: float, sdir: str | None = None) -> dict:
    """Per filer: what is recorded, and what is about to be pruned unpromoted."""
    sdir = state_dir(sdir)
    out = {"filers": {}, "recorded": 0, "expiring": 0}
    for name in filers(sdir):
        rows = listed_rows(name, now, sdir=sdir)
        expiring = {fp: row for fp, row in rows.items()
                    if (now - float(row.get("last_at", now)))
                    >= (LIST_TTL_DAYS - EXPIRY_WARN_DAYS) * DAY}
        out["filers"][name] = {"rows": rows, "expiring": expiring,
                               "paused": paused_reason(name, now, sdir)}
        out["recorded"] += len(rows)
        out["expiring"] += len(expiring)
    return out


def digest_line(report: dict) -> str:
    """The one line that reaches Sana. Empty when there is nothing to say."""
    if not report["recorded"]:
        return ""
    per = ", ".join(f"{name} {len(v['rows'])}"
                    for name, v in sorted(report["filers"].items()) if v["rows"])
    line = (f"[kipi-system] filer-cap: {report['recorded']} finding(s) recorded "
            f"and not ticketed ({per})")
    if report["expiring"]:
        line += (f"; {report['expiring']} expire within {EXPIRY_WARN_DAYS}d "
                 f"unpromoted")
    return line + ". Read them with `filer_cap.py digest`."


def notify(line: str) -> int:
    """File the digest for Sana through the one alert sink. Its own filer id.

    KIPI_ALERT_FILER IS LOAD-BEARING, learned the hard way one commit ago: a
    message with no `[label]` prefix inherits the `alert` budget, and the first
    spillover capture after the cap shipped was swallowed that way. A monitor
    that spends the budget of the thing it monitors reports nothing on the day it
    matters.
    """
    import subprocess
    filer = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "alert-to-linear.py")
    env = dict(os.environ)
    env["KIPI_ALERT_FILER"] = "filer-cap-digest"
    try:
        res = subprocess.run([sys.executable, filer, line], env=env,
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"could not file the digest: {exc}", file=sys.stderr)
        return 1
    print((res.stdout or res.stderr or "").strip())
    return res.returncode


# --- the DoR's check ---------------------------------------------------------

def replay(rows: list, cap_hour: int | None = None, cap_day: int | None = None,
           sdir: str | None = None, only: tuple | None = None) -> dict:
    """Run real board rows through the cap in time order. No Linear calls.

    The rows come from capture_board_28d.py: one per issue actually created,
    carrying `fp` (alert-to-linear.fingerprint of the title), `created_at`,
    `filer` and `completed`. Replaying them answers the DoR's question directly
    -- with this cap in place, which of these would still have been a ticket --
    and the gate is the `completed` column: an issue somebody actually worked
    must not come out as a list row.

    `only` scopes it to CAPPED_FILERS. A row outside that set never reaches
    decide() in production, so scoring it here measures a cap that does not
    exist; see the CAPPED_FILERS comment for the run that proved it.

    TWO THINGS THIS CANNOT DO, said out loud rather than buried.

    The replay groups by the taxonomy CLASS (`alert`), while at runtime
    filer_for() keys the bucket per repo (`[consulting]`, `[cole-gtm]`). That is
    a coarser grouping than production, so every row competes for one budget
    instead of several. Splitting one bucket into N sub-buckets at the same cap
    can only raise the ticket count, never lower it -- so this number is a LOWER
    BOUND on tickets and an upper bound on listings. The gate is therefore
    strictly harder here than in production, which is the safe direction. It is
    also why the fixture does not carry the repo label: this repo is public.

    And it assumes the same events in the same order. It cannot model the world
    where an alert that was listed instead of ticketed CHANGES what happens next
    (a job nobody fixed, and therefore fired again). It bounds the cap against
    history; it does not predict the future.
    """
    sdir = state_dir(sdir)
    only = CAPPED_FILERS if only is None else only
    out = {"ticket": 0, "listed": 0, "by_filer": {},
           "completed_total": 0, "completed_ticketed": 0,
           "completed_listed": [], "skipped_uncapped": 0}
    for row in rows:
        filer = row.get("filer") or "other"
        if only and filer not in only:
            out["skipped_uncapped"] += 1
            continue
        fp = row.get("fp") or ""
        now = _epoch(row.get("created_at"))
        if now is None:
            continue
        d = decide(filer, fp, now, sdir=sdir, cap_hour=cap_hour, cap_day=cap_day)
        bucket = out["by_filer"].setdefault(filer, {"ticket": 0, "listed": 0,
                                                    "completed": 0,
                                                    "completed_listed": 0})
        out[d.action] += 1
        bucket[d.action] += 1
        if row.get("completed"):
            out["completed_total"] += 1
            bucket["completed"] += 1
            if d.ticket:
                out["completed_ticketed"] += 1
            else:
                bucket["completed_listed"] += 1
                out["completed_listed"].append(
                    {"fp": fp, "filer": filer, "created_at": row.get("created_at"),
                     "reason": d.reason})
    return out


def _epoch(stamp) -> float | None:
    if not stamp:
        return None
    try:
        text = str(stamp).replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def tripwire(rows: list, now: float, days: int = TRIPWIRE_DAYS) -> dict:
    """Per filer over the window: created, closed, and whether it should pause.

    Closed means completed OR canceled: both are a human spending attention to
    take the row off the board, which is the outflow the ratio is about. A filer
    creating faster than the board absorbs is the condition; WHY each one closed
    is Step 7's question, not this one's.
    """
    cutoff = now - days * DAY
    created = collections.Counter()
    closed = collections.Counter()
    for row in rows:
        at = _epoch(row.get("created_at"))
        if at is None or at < cutoff:
            continue
        filer = row.get("filer") or "other"
        created[filer] += 1
        if (row.get("state_type") or "") in ("completed", "canceled"):
            closed[filer] += 1
    return {f: {"created": created[f], "closed": closed[f],
                "pause": created[f] > closed[f]}
            for f in sorted(created)}


# --- CLI ---------------------------------------------------------------------

def _load_payload(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str]) -> int:
    import time

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="what is recorded and not ticketed")
    p_list.add_argument("--filer")

    p_dig = sub.add_parser("digest", help="the reader: what is recorded, what "
                                         "is about to expire unpromoted")
    p_dig.add_argument("--notify", action="store_true",
                       help="file ONE line for Sana through alert-to-linear.py")

    p_rec = sub.add_parser("reconcile", help="the 7-day creates-vs-closes tripwire")
    p_rec.add_argument("--payload", required=True,
                       help="a capture_board_28d.py payload")
    p_rec.add_argument("--apply", action="store_true",
                       help="actually pause the filers over the line")

    p_rep = sub.add_parser("replay", help="ASK-2012's check: ticket vs listed")
    p_rep.add_argument("payload")
    p_rep.add_argument("--cap-hour", type=int)
    p_rep.add_argument("--cap-day", type=int)
    p_rep.add_argument("--filers", default=",".join(CAPPED_FILERS),
                       help="filer classes the cap sees; 'all' scores every row")

    p_res = sub.add_parser("reset", help="clear one filer's bucket and list")
    p_res.add_argument("--filer", required=True)

    args = ap.parse_args(argv[1:])
    now = time.time()

    if args.cmd == "list":
        names = [args.filer] if args.filer else filers()
        if not names:
            print("nothing recorded (no filer state yet)")
            return 0
        for name in names:
            rows = listed_rows(name, now)
            held = paused_reason(name, now)
            head = f"{name}: {len(rows)} recorded, not ticketed"
            print(f"{head}{'  [PAUSED: ' + held + ']' if held else ''}")
            for fp, row in sorted(rows.items(),
                                  key=lambda kv: -kv[1].get("last_at", 0)):
                age = (now - float(row.get("last_at", now))) / DAY
                print(f"  {fp}  seen {row.get('count', 1)}x  "
                      f"last {age:.1f}d ago  {row.get('title', '')}")
        return 0

    if args.cmd == "reset":
        unpause(args.filer, now)
        with _lock(args.filer, state_dir()):
            _write(args.filer, state_dir(), {"spent": [], "listed": {}})
        print(f"reset {args.filer}")
        return 0

    if args.cmd == "digest":
        report = digest(now)
        line = digest_line(report)
        for name, v in sorted(report["filers"].items()):
            if not v["rows"]:
                continue
            head = f"{name}: {len(v['rows'])} recorded, not ticketed"
            if v["paused"]:
                head += f"  [PAUSED: {v['paused']}]"
            print(head)
            for fp, row in sorted(v["rows"].items(),
                                  key=lambda kv: kv[1].get("last_at", 0)):
                age = (now - float(row.get("last_at", now))) / DAY
                mark = "  EXPIRING" if fp in v["expiring"] else ""
                print(f"  {fp}  seen {row.get('count', 1)}x  last {age:.1f}d ago"
                      f"  {row.get('title', '')}{mark}")
        print(f"\n{line or 'nothing recorded; nothing to report'}")
        if args.notify and line:
            return notify(line)
        return 0

    if args.cmd == "reconcile":
        rows = _load_payload(args.payload)["rows"]
        verdict = tripwire(rows, now)
        for filer, v in sorted(verdict.items()):
            mark = "PAUSE" if v["pause"] else "ok"
            print(f"{filer:16s} created={v['created']:4d} "
                  f"closed={v['closed']:4d}  {mark}")
        if not args.apply:
            print("\n(dry: nothing paused. --apply to write the pause.)")
            return 0
        print()
        for name, action, note in reconcile_apply(verdict, now):
            if action != "ok":
                print(f"{name:16s} {action}  {note}")
        return 0

    if args.cmd == "replay":
        payload = _load_payload(args.payload)
        only = () if args.filers == "all" else tuple(
            f.strip() for f in args.filers.split(",") if f.strip())
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = replay(payload["rows"], cap_hour=args.cap_hour,
                         cap_day=args.cap_day, sdir=tmp, only=only)
        prov = payload.get("provenance", {})
        print(f"payload: {prov.get('row_count')} rows, "
              f"{prov.get('window_days')}d to {prov.get('captured_at')}")
        print(f"cap: {args.cap_hour or DEFAULT_CAP_HOUR}/hour, "
              f"{args.cap_day or DEFAULT_CAP_DAY}/day per filer")
        print(f"scored: {args.filers}  (skipped {out['skipped_uncapped']} rows "
              f"from filers no chokepoint caps)\n")
        print(f"{'filer':16s} {'ticket':>7s} {'listed':>7s} {'completed':>10s} "
              f"{'completed listed':>17s}")
        for filer, b in sorted(out["by_filer"].items(),
                               key=lambda kv: -(kv[1]["ticket"] + kv[1]["listed"])):
            print(f"{filer:16s} {b['ticket']:7d} {b['listed']:7d} "
                  f"{b['completed']:10d} {b['completed_listed']:17d}")
        print(f"\nTOTAL ticket={out['ticket']} listed={out['listed']}")
        print(f"GATE completed {out['completed_ticketed']}/{out['completed_total']} "
              f"still ticketed")
        if out["completed_listed"]:
            print("\nFAIL -- these were worked and the cap would have listed them:")
            for row in out["completed_listed"][:20]:
                print(f"  {row['filer']} {row['created_at']} {row['fp']} :: {row['reason']}")
            return 1
        return 0

    return 0                                                 # pragma: no cover


if __name__ == "__main__":
    sys.exit(main(sys.argv))
