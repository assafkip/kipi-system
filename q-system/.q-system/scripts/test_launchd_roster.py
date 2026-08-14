#!/usr/bin/env python3
"""Reproducer + regression suite for the launchd ROSTER check (ASK-717).

## The defect this pins

`com.cole.delivery-watch` -- the class fix built for the silent-delivery RCA
(rca-silent-delivery-class-2026-07-21, "reported live, delivers nothing, nothing
pages") -- stopped running on 2026-07-25 and nothing said so for 19 days.

`discover_problems()` was NOT blind to an unloaded plist; it has had the
`not_loaded` mode since the 2026-07-05 com.cole.daily-video scar. What silenced
this one is the layer above it: the label is listed in
`~/.config/kipi/cole-pause.state`, so it classified as `paused`, printed once per
run, and `problems_to_ping` skips `paused` on purpose. A pause ledger with no
expiry and no total is indistinguishable from coverage -- measured 2026-08-13,
22 of 26 com.cole plists were dark and every one of them was "paused on purpose".

So the missing instrument is not another per-label verdict. It is the ROSTER:
plists ON DISK compared against the labels launchd actually holds, counted BOTH
ways, printed every run. `4 loaded of 26 on disk` is a sentence no reader mistakes
for health; 22 lines saying "paused on purpose" is one every reader scrolls past.

## Why counted both ways

A shrink is only visible against a denominator. The ping fires on the DELTA (a
label newly dark, or the loaded count dropping), never on the standing set --
paging twice a day about 22 deliberately paused jobs is the alert-fatigue
mechanism that the 2026-07-26 scar in launchd-health-check.py already recorded
once, and a channel the founder learns to ignore protects nothing.

Run: python3 test_launchd_roster.py   (exit 0 = pass, 1 = fail)
"""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "wd", Path(__file__).resolve().parent / "launchd-health-check.py"
)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


def require_attr(name):
    """Report a missing function as a NAMED failure instead of an import crash.

    The reproducer has to be able to run and report RED against the pre-fix code;
    an AttributeError at module scope aborts the file and every later assertion
    goes unreported, which reads like a smaller gap than there is.
    """
    fn = getattr(wd, name, None)
    if fn is None:
        failures.append(
            f"MISSING: launchd-health-check.py has no {name}() -- nothing compares "
            f"plists on disk against loaded labels (ASK-717 acceptance 1/2)")
    return fn


# --- fixture: the measured 2026-08-13 shape, shrunk to its classes ------------
# One loaded, one dark-and-paused (delivery-watch's real state), one dark and NOT
# paused, and one loaded label with no plist on disk.
ON_DISK = [
    "com.cole.daily-podcast",     # loaded
    "com.cole.delivery-watch",    # on disk, NOT loaded, listed as paused
    "com.cole.reply-sweep",       # on disk, NOT loaded, listed as paused
    "com.cole.job-liveness",      # on disk, NOT loaded, NOT paused
]
LOADED = {
    "com.cole.daily-podcast",
    "com.cole.ghost-job",          # loaded, no plist on disk
    "com.unwatched.something",     # outside the watched prefixes
}
PAUSED = {"com.cole.delivery-watch", "com.cole.reply-sweep"}
PREFIXES = ("com.cole.",)


# --- acceptance 1 + 2: absence is reported, not just failure ------------------
_roster = require_attr("roster")
if _roster:
    r = _roster(PREFIXES, ON_DISK, LOADED, PAUSED)

    # The DoR's literal check: a plist on disk whose label is absent from
    # `launchctl list` is REPORTED. Both the paused and the unpaused one.
    check("every on-disk-not-loaded label is reported",
          sorted(r["dark"] + r["paused_dark"]),
          ["com.cole.delivery-watch", "com.cole.job-liveness", "com.cole.reply-sweep"])

    # delivery-watch is the whole issue: it must land in the roster's dark set
    # even though the pause ledger silences its ping.
    check("the paused watchdog is still counted dark",
          "com.cole.delivery-watch" in r["paused_dark"], True)

    # Deliberate pause stays distinguishable from an accident. Same set, two
    # names, so the report can page on one and only print the other.
    check("unpaused dark is separated from paused dark",
          sorted(r["dark"]), ["com.cole.job-liveness"])

    # NEGATIVE SELF-TEST for the denominator. An implementation that filtered the
    # pause ledger out of `on_disk` would print "1 on disk, 1 loaded" -- a clean
    # bill of health for the exact machine that had 22 dark jobs. The count of
    # plists on disk is a fact about the filesystem and nothing may shrink it.
    check("pausing a job does NOT shrink the on-disk count",
          len(r["on_disk"]), 4)
    check("on_disk is the filesystem, pause ledger included",
          sorted(r["on_disk"]), sorted(ON_DISK))

    # The inverse direction, which per-label `launchctl list` polling structurally
    # cannot see: launchd holds a watched label with no plist behind it.
    check("loaded-with-no-plist is reported", sorted(r["ghost"]), ["com.cole.ghost-job"])

    # Scope: an unwatched family is neither counted nor reported.
    check("unwatched families stay out of the roster",
          "com.unwatched.something" in r["loaded"] + r["ghost"], False)

    check("loaded counts only watched labels backed by a plist",
          sorted(r["loaded"]), ["com.cole.daily-podcast"])


# --- acceptance 3: the count, both ways, in the printed line ------------------
_roster_line = require_attr("roster_line")
if _roster_line and _roster:
    line = _roster_line(_roster(PREFIXES, ON_DISK, LOADED, PAUSED))
    # Asserted as LITERAL substrings, not against a second call to the same
    # formatter. A baseline captured from the code under test moves whenever the
    # code moves and cannot fail on a wrong count.
    check("roster line states the on-disk count", "4 plist(s) on disk" in line, True)
    check("roster line states the loaded count", "1 loaded" in line, True)
    check("roster line states the dark count", "3 dark" in line, True)
    check("roster line names the paused share", "2 paused on purpose" in line, True)
    check("roster line names the ghost", "1 loaded with no plist" in line, True)


# --- acceptance 4: notify_attempted and notify_delivered, recorded SEPARATELY --
# slack-notify.sh is a silent no-op that STILL EXITS 0 when no webhook resolves.
# One boolean cannot answer both "did we try" and "did it leave", and collapsing
# them is the same defect the ping path already carries four scars for.
_notify = require_attr("roster_notify")
if _notify and _roster:
    def _dead_channel(_message):
        return False           # tried, went nowhere

    def _live_channel(_message):
        return True

    # A first run with dark jobs is a change from nothing -> it pages.
    state = {}
    r_now = _roster(PREFIXES, ON_DISK, LOADED, PAUSED)
    attempted, delivered = _notify(r_now, state, 1000, send=_dead_channel)
    check("a dead channel still records the ATTEMPT", attempted, True)
    check("a dead channel records delivery as False", delivered, False)
    check("attempted and delivered are SEPARATE recorded fields",
          (state["__roster__"]["notify_attempted"],
           state["__roster__"]["notify_delivered"]), (True, False))

    # NEGATIVE SELF-TEST: an undelivered page must NOT bank the roster as seen,
    # or the next run reads "unchanged" and the alert is lost for good. This is
    # the record_pings scar (PR #134 round 6) one detector over.
    check("an undelivered page does not bank the roster",
          state["__roster__"].get("banked_loaded"), None)
    attempted2, delivered2 = _notify(r_now, state, 2000, send=_dead_channel)
    check("the next run re-alerts after a dead channel", attempted2, True)

    # A delivered page banks it, and an unchanged roster then stays quiet.
    state_ok = {}
    _notify(r_now, state_ok, 1000, send=_live_channel)
    check("a delivered page banks the roster",
          state_ok["__roster__"]["banked_loaded"], 1)
    check("a delivered page records both fields true",
          (state_ok["__roster__"]["notify_attempted"],
           state_ok["__roster__"]["notify_delivered"]), (True, True))
    # Both booleans describe THIS run, so a quiet run is (False, False): nothing
    # was tried and nothing left. The caller's stranded test is therefore
    # `attempted and not delivered`, which a quiet run can never satisfy. A
    # sentinel True on the quiet path would have read as "delivered" in the state
    # file for a run that sent nothing.
    check("an unchanged roster does not page again",
          _notify(r_now, state_ok, 2000, send=_live_channel), (False, False))
    check("a quiet run is not stranded",
          state_ok["__roster__"]["notify_attempted"]
          and not state_ok["__roster__"]["notify_delivered"], False)
    check("a quiet run keeps the banked roster",
          state_ok["__roster__"]["banked_loaded"], 1)

    # THE REPRODUCER, in one assertion: a job that was loaded and stops being
    # loaded pages. This is precisely what did not happen on 2026-07-25.
    shrunk = _roster(PREFIXES, ON_DISK, set(), PAUSED)
    check("a silent shrink pages",
          _notify(shrunk, state_ok, 3000, send=_live_channel), (True, True))

    # ISOLATED shrink fixture. The assertion above does NOT pin the shrink
    # detector: dropping every label out of `loaded` also makes them newly dark,
    # so the page fires through that path and `shrank` is dead weight. Mutant M4
    # (`shrank = False`) survived the whole suite on exactly that redundancy.
    #
    # A flapping job isolates it. The label is ALREADY in banked_dark from an
    # earlier page, so it is not newly dark on the way back down, and the only
    # signal left that something stopped is the loaded count falling.
    flap_state = {"__roster__": {
        "banked_loaded": 2,
        "banked_dark": sorted(r_now["dark"] + r_now["paused_dark"]),
        "banked_ghost": list(r_now["ghost"]),
    }}
    check("a loaded count that falls pages even when nothing is NEWLY dark",
          _notify(r_now, flap_state, 4000, send=_live_channel), (True, True))
    check("...and the fixture really has no newly-dark label to page on instead",
          sorted(set(r_now["dark"] + r_now["paused_dark"])
                 - set(flap_state["__roster__"]["banked_dark"])), [])

    # A channel that RAISES is not a delivered page, and the pair has to survive
    # to say so. Mutant M2 (delivery claimed before the send) survived until this
    # existed, because on the non-raising path the post-send write covers it.
    def _raising_channel(_message):
        raise RuntimeError("webhook host unreachable")

    raise_state = {}
    check("a raising channel returns not-delivered",
          _notify(r_now, raise_state, 5000, send=_raising_channel), (True, False))
    check("a raising channel still records the pair as stranded",
          (raise_state["__roster__"]["notify_attempted"],
           raise_state["__roster__"]["notify_delivered"]), (True, False))
    check("a raising channel banks nothing",
          raise_state["__roster__"].get("banked_loaded"), None)


# --- acceptance 4, wiring: the page uses the one founder channel --------------
if _notify:
    import inspect  # noqa: E402 - local to this assertion
    src = inspect.getsource(wd)
    check("the roster pages through send_ping (slack-notify.sh), not osascript",
          "osascript" in src, False)


# THE GHOST-LABEL REGRESSION (Codex review of #142, major). The healthy-run
# cleanup cleared the WHOLE ping-state dict, and run_roster_check writes
# ROSTER_STATE_KEY earlier in the same run. discover_problems() does not judge the
# roster, so a run with a ghost label but no per-job problem wiped the record that
# the ghost had been paged, and it paged again every cycle for ever.
#
# A source assertion, and said plainly rather than dressed as behavioural: driving
# it needs a live launchctl and a real state file. It pins the one property that
# was wrong -- the cleanup must not blindly write an empty dict.
_HC = Path(__file__).parent / "launchd-health-check.py"
_hc_src = _HC.read_text() if _HC.exists() else ""
if "write_state({})  # everything recovered" in _hc_src:
    failures.append(
        "healthy-run cleanup writes an empty dict, erasing ROSTER_STATE_KEY banked "
        "earlier in the same run: a ghost label re-pages every cycle")
elif _hc_src and "ROSTER_STATE_KEY" not in _hc_src.split("everything recovered")[0][-800:] \
        and "kept = load_state().get(ROSTER_STATE_KEY)" not in _hc_src:
    failures.append("healthy-run cleanup does not preserve ROSTER_STATE_KEY")


def _report() -> int:
    if failures:
        print("FAIL:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(f"PASS: launchd roster checks green ({len(ON_DISK)} fixture plists)")
    return 0


def test_launchd_roster():
    """Pytest entry point: same assertions, surfaced as one test."""
    assert not failures, "launchd roster failures:\n  - " + "\n  - ".join(failures)


if __name__ == "__main__":
    sys.exit(_report())
