#!/usr/bin/env python3
"""Pins alert-to-linear.py: the flood collapses, and a test can never file live.

Every message string below is a REAL line copied out of #general on 2026-08-10,
the day the founder said "I dont want to see any of these." The fixtures are the
evidence, not an invention -- an invented fixture would let the dedup pass here
and still flood Linear on the first real run.
"""
import importlib.util
import json
import os
import sys
import time

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


def _load():
    path = os.path.join(SCRIPTS, "alert-to-linear.py")
    spec = importlib.util.spec_from_file_location("alert_to_linear", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --- the 51 auto-commit messages are ONE alert -------------------------------

AUTOCOMMIT = [
    "[consulting] auto-commit left 3 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/pipeline/tests/test_hiring_harvest.py [2026-08-10 14:06:41 PDT]",
    "[consulting] auto-commit left 2 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json [2026-08-10 13:45:18 PDT]",
    "[consulting] auto-commit left 6 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/pipeline/apify_sync.py (+3 more) [2026-08-10 13:44:41 PDT]",
    "[consulting] auto-commit left 9 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/.q-system/apify-rules.md (+6 more) [2026-08-10 12:35:45 PDT]",
]

# The home directory is a PLACEHOLDER, and it has to stay one. This repo is
# public, and validate-separation.py's full skeleton sweep fails on the founder's
# real home prefix appearing anywhere under q-system/. What these two strings
# need to exercise is the SHAPE -- two path-shaped tokens that differ only by
# timestamp -- because fingerprint() scrubs any `\S*/\S*` token before hashing.
# The real username was never load-bearing; it was just what got pasted in.
#
# This comment does not spell that prefix out, and that is the point: the first
# version of it did, so the comment explaining the ban tripped the ban. A text
# rule that scans comments as well as code has to be written about the data
# class, never with a sample of the data.
CARVEOUT = [
    "[cole-gtm] Daily X tool post (2026-07-17): CARVE-OUT ACTIVE: /Users/founder/.config/kipi/cole.OFF is ON (the fleet is paused) but /Users/founder/.config/kipi/podcast-social.ON opts THIS lane back in. [2026-08-10 14:05:24 PDT]",
    "[cole-gtm] Daily X tool post (2026-07-17): CARVE-OUT ACTIVE: /Users/founder/.config/kipi/cole.OFF is ON (the fleet is paused) but /Users/founder/.config/kipi/podcast-social.ON opts THIS lane back in. [2026-08-10 13:48:02 PDT]",
]


def test_every_autocommit_message_shares_one_fingerprint():
    """51 tickets would be the same defect with a worse surface."""
    prints = {mod.fingerprint(m) for m in AUTOCOMMIT}
    assert len(prints) == 1, f"auto-commit split into {len(prints)} tickets"


def test_every_carveout_message_shares_one_fingerprint():
    prints = {mod.fingerprint(m) for m in CARVEOUT}
    assert len(prints) == 1, f"carve-out split into {len(prints)} tickets"


def test_different_alerts_do_not_collapse_together():
    """The negative self-test. A fingerprint that maps everything to one bucket
    would pass both tests above and silently swallow every real alert."""
    distinct = [
        AUTOCOMMIT[0],
        CARVEOUT[0],
        "[ask-317] SECURITY: unsanctioned .claude/ change -- 2 modified, 4 added, 0 removed",
        "[/] Meeting loop could not run: NOTION_TOKEN_ASK is not in the launchd environment.",
        "[example_instance] repo sync BLOCKED: /path/to/repo is not a git repo",
    ]
    prints = {mod.fingerprint(m) for m in distinct}
    assert len(prints) == len(distinct), "distinct alerts collapsed into one ticket"


def test_security_alerts_naming_different_files_stay_one_ticket():
    """Same condition, different file list -> still one ticket."""
    a = "[ask-317] SECURITY: q-system/.q-system/scripts/claude-integrity-tripwire.py was deleted; restored from git"
    b = "[ask-317] SECURITY: q-system/.q-system/scripts/claude-path-write-guard.py was deleted; restored from git"
    assert mod.fingerprint(a) == mod.fingerprint(b)


# --- the guard that matters most ---------------------------------------------

def test_pytest_can_never_file_a_real_ticket():
    """PYTEST_CURRENT_TEST is set by pytest itself for every test, so this holds
    for tests nobody has written yet. That is the point: the 2026-08-01 scar was
    a test paging the founder from a branch that carried no stub."""
    assert os.environ.get("PYTEST_CURRENT_TEST"), "pytest must set its own marker"
    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])
    assert rc == mod.EXIT_REFUSED_FIXTURE


def test_empty_message_is_a_no_op():
    assert mod.main(["alert-to-linear.py", ""]) == mod.EXIT_OK
    assert mod.main(["alert-to-linear.py"]) == mod.EXIT_OK


# --- the guard must not depend on WHICH runner was used (ASK-879) -------------
#
# SCAR, measured 2026-08-14 (sp-5a3e3b7b, source ASK-746). The refusal above is
# keyed on PYTEST_CURRENT_TEST, which pytest sets and nothing else does.
# test_launchd_health_check.py runs as plain python3 under a `__main__` guard, so
# it sets no such variable and was never refused: it reached repeat #5 on ASK-736
# from keyed machines and filed ASK-744 and ASK-745 for real. The 2026-08-10 scar
# was therefore only half closed -- closed for the runner that happened to be
# used that day. Bash suites are in the same position.
#
# Every case below CLEARS PYTEST_CURRENT_TEST first. Leaving it set would let the
# OLD signal answer, and the new one would be untested while reading green.


class GraphQLTripwire(Exception):
    """Raised if the writer reaches for Linear at all.

    Asserting exit 4 alone is not enough: a refusal that happens AFTER the client
    is loaded (or after a query goes out) is not a refusal, and the exit code
    cannot tell the two apart. `_load_linear` is the single seam every Linear call
    in this file goes through, so tripping it is what makes "no GraphQL was
    attempted" an assertion rather than a hope.
    """


def _tripwire(monkeypatch):
    """Explode on any Linear access. Returns the list that records the attempt."""
    touched = []

    def boom():
        touched.append(True)
        raise GraphQLTripwire("alert-to-linear reached for the Linear client")

    monkeypatch.setattr(mod, "_load_linear", boom)
    return touched


def _non_pytest_runner(monkeypatch, entrypoint, main_file=None):
    """Stand the process up as `entrypoint` with no pytest marker and no capture.

    `main_file` defaults to `entrypoint` (a plain `python3 test_foo.py`, where both
    agree) and is passed separately when the two must DISAGREE. They are set
    independently because a guard reading only one of them still passes every case
    that moves both -- measured, not assumed: the `read argv[0] only, never
    __main__` mutant SURVIVED the first version of this suite, which moved both
    together in every case.
    """
    for var in ("PYTEST_CURRENT_TEST", "KIPI_TEST_RUNNER", "KIPI_ALERT_CAPTURE"):
        monkeypatch.delenv(var, raising=False)
    # The ancestry is part of the process's identity, so standing it up as a
    # non-test runner has to answer for it too. These cases genuinely run under
    # `python3 -m pytest test_alert_to_linear.py`, so the REAL parent is a test
    # runner and signal 3 would (correctly) refuse the two production controls
    # below for a reason that has nothing to do with what they assert. Signal 3
    # is pinned instead by the real-process reproducer and by the direct cases on
    # `_ancestor_entrypoints`, where it can be fed a chain the case chose.
    monkeypatch.setattr(mod, "_ancestor_entrypoints", lambda: [])
    monkeypatch.setattr(sys, "argv", [entrypoint, AUTOCOMMIT[0]])
    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        monkeypatch.setattr(
            main_mod, "__file__", main_file or entrypoint, raising=False)


PRODUCTION_ENTRYPOINT = "/opt/kipi/q-system/.q-system/scripts/launchd-health-check.py"


def test_explicit_marker_refuses_a_non_pytest_runner(monkeypatch):
    """The signal a bash suite or plain-python3 runner can export for itself."""
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(monkeypatch, PRODUCTION_ENTRYPOINT)
    monkeypatch.setenv("KIPI_TEST_RUNNER", "1")

    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

    assert rc == mod.EXIT_REFUSED_FIXTURE
    assert touched == [], "refused only AFTER reaching Linear"


def test_any_non_blank_marker_value_arms_the_refusal(monkeypatch):
    """Presence, not truthiness. `0` is a value someone exported on purpose."""
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(monkeypatch, PRODUCTION_ENTRYPOINT)
    monkeypatch.setenv("KIPI_TEST_RUNNER", "0")

    assert mod.main(["alert-to-linear.py", AUTOCOMMIT[0]]) == mod.EXIT_REFUSED_FIXTURE
    assert touched == []


def test_a_test_named_entrypoint_refuses_without_any_cooperation(monkeypatch):
    """The half no runner has to opt into.

    test_launchd_health_check.py is the measured case: plain python3, `__main__`
    guard, no marker exported. A guard that only honours an env var protects the
    runners someone remembered to edit, which is the per-suite stubbing this
    chokepoint exists to replace.
    """
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(
        monkeypatch,
        "/opt/kipi/q-system/.q-system/scripts/test_launchd_health_check.py",
    )

    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

    assert rc == mod.EXIT_REFUSED_FIXTURE
    assert touched == []


def test_a_bash_suite_entrypoint_is_refused_too(monkeypatch):
    """`test-break-glass-audit.sh` and siblings: hyphen, `.sh`, same class."""
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(
        monkeypatch,
        "/opt/kipi/q-system/.q-system/scripts/test-break-glass-audit.sh",
    )

    assert mod.main(["alert-to-linear.py", AUTOCOMMIT[0]]) == mod.EXIT_REFUSED_FIXTURE
    assert touched == []


def test_each_entry_point_is_read_on_its_own(monkeypatch):
    """One test name, one production name, one at a time. Both must refuse.

    Moving argv and `__main__` together in every case made them indistinguishable:
    a guard reading either one alone passed the whole section. Split so each read
    is pinned by a case the other cannot answer.
    """
    suite = "/opt/kipi/q-system/.q-system/scripts/test_launchd_health_check.py"

    for label, entrypoint, main_file in (
        ("argv[0] only", suite, PRODUCTION_ENTRYPOINT),
        ("__main__ only", PRODUCTION_ENTRYPOINT, suite),
    ):
        touched = _tripwire(monkeypatch)
        _non_pytest_runner(monkeypatch, entrypoint, main_file=main_file)

        rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

        assert rc == mod.EXIT_REFUSED_FIXTURE, f"not refused via {label}"
        assert touched == [], f"reached Linear via {label}"
        monkeypatch.undo()


def test_a_production_name_that_merely_contains_test_is_allowed(monkeypatch):
    """`latest-run.py` holds the substring `test-run.py`. It is not a test.

    The refusal matches from the START of the basename for this reason. Measured:
    swap that `.match` for a `.search` and every other case in this section still
    passes, so without this one the distinction is an unasserted claim -- and a
    guard that reads an ordinary production script as a fixture swallows its alerts
    in silence, which slack-notify.sh calls worse than the bug it fixes.
    """
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(
        monkeypatch, "/opt/kipi/q-system/.q-system/scripts/latest-run.py")

    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

    assert touched == [True], "a production script was read as a fixture"
    assert rc == mod.EXIT_FAILED


def test_a_production_runner_is_still_allowed_to_file(monkeypatch):
    """The control, and the reason the two cases above prove anything.

    Without it a guard hardwired to refuse everything would pass every assertion
    in this section and silently swallow every real alert -- the failure slack-
    notify.sh calls worse than the bug it fixes.
    """
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(monkeypatch, PRODUCTION_ENTRYPOINT)

    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

    assert touched == [True], "the guard refused a production run"
    assert rc == mod.EXIT_FAILED, "the tripwire should surface as a failed send"


def test_capture_hatch_still_wins_over_the_new_marker(monkeypatch, tmp_path):
    """KIPI_ALERT_CAPTURE is the sanctioned redirect and returns before the guard.

    Pinned because the new signal sits next to it: a guard placed one line too
    early would turn every capturing suite's asserted-on file into exit 4 and an
    empty file, and those suites read the FILE, so they would go red.
    """
    touched = _tripwire(monkeypatch)
    _non_pytest_runner(monkeypatch, PRODUCTION_ENTRYPOINT)
    monkeypatch.setenv("KIPI_TEST_RUNNER", "1")
    dest = tmp_path / "captured.txt"
    monkeypatch.setenv("KIPI_ALERT_CAPTURE", str(dest))

    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])

    assert rc == mod.EXIT_OK
    assert AUTOCOMMIT[0] in dest.read_text(encoding="utf-8")
    assert touched == []


# --- the subprocess boundary, in REAL processes (ASK-879, PR #209 round 1) ---
#
# CODEX MAJOR: "the fixture guard inspects the writer subprocess rather than its
# parent test runner, allowing unmarked bash and plain-Python tests to reach
# Linear." Correct, and the cases above cannot see it. Every one of them calls
# `mod.main()` in-process, so `sys.argv` and `__main__` ARE the runner's -- the
# one arrangement where reading self is indistinguishable from reading the
# runner. The real chain is `suite -> slack-notify.sh -> alert-to-linear.py as a
# subprocess`, where the leaf's argv[0] is the writer and nothing about it looks
# like a test. Signal 2 covers that shape and NO runner exports the marker yet
# (sp-aecfe5d8), so on the shipped head the hole is open in exactly the shape the
# scar was measured in.
#
# So these two cases fork real processes. A fixture built from monkeypatched
# module attributes cannot cross a process boundary, and a boundary is the defect.
#
# THE CROSS-PROCESS TRIPWIRE. `_tripwire` is a monkeypatch and does not survive
# `fork`, so "did it reach Linear" is asserted through the EXIT CODE against a
# HOME with no key file and no `KIPI_LINEAR_API_KEY`: exit 3 means the run got
# past the guard, loaded the client and asked for auth, which is reaching Linear.
# Exit 4 means refused. That same missing key is what makes running this safe --
# the RED state cannot file a real ticket, it can only prove it tried to.

_SHIM = """#!/bin/bash
# Stands in for slack-notify.sh: a bash link in the chain that runs the writer
# as a subprocess. Deliberately NOT named like a test -- it is production code.
set -euo pipefail
exec python3 "$1" "$2"
"""

_RUNNER = '''#!/usr/bin/env python3
"""Stands in for a plain-python3 suite: no pytest, so no PYTEST_CURRENT_TEST."""
import subprocess, sys
sys.exit(subprocess.run(["bash", sys.argv[1], sys.argv[2], sys.argv[3]]).returncode)
'''

# WHY THESE CHAINS ARE PADDED, and it is not ceremony.
#
# The control below has to show a production chain is NOT refused. But this suite
# genuinely runs as `python3 -m pytest test_alert_to_linear.py`, so pytest is a
# real ancestor of anything it forks, and the walk found it: the control went RED
# with `REFUSED under a test entry point in a parent process
# (test_alert_to_linear.py)`. That refusal was CORRECT -- the machine really was
# running a test -- and it made the control unable to fail for its own reason.
#
# So each chain is pushed past `_ANCESTRY_MAX_DEPTH` links away from pytest by
# production-named bash links, and the walk stops before reaching it. Both chains
# are padded identically, so the only difference between the reproducer and the
# control stays the one thing under test: what the runner is named.
_PAD = """#!/bin/bash
# A production-named link. Not `exec`: each level must stay a live parent, which
# is the whole point of the padding.
set -euo pipefail
n="$1"; shift
if [ "$n" -gt 0 ]; then bash "$0" "$((n - 1))" "$@"; else python3 "$@"; fi
"""

_PAD_LINKS = 8


def _chain(tmp_path, runner_name):
    """Write the padded chain and return the command that runs it."""
    runner = tmp_path / runner_name
    runner.write_text(_RUNNER, encoding="utf-8")
    shim = tmp_path / "notify-shim.sh"
    shim.write_text(_SHIM, encoding="utf-8")
    pad = tmp_path / "pipeline-link.sh"
    pad.write_text(_PAD, encoding="utf-8")
    writer = os.path.join(SCRIPTS, "alert-to-linear.py")
    return ["bash", str(pad), str(_PAD_LINKS),
            str(runner), str(shim), writer, AUTOCOMMIT[0]]


def _keyless_env(tmp_path):
    """No marker, no capture, and no reachable Linear key."""
    env = dict(os.environ)
    for var in ("PYTEST_CURRENT_TEST", "KIPI_TEST_RUNNER", "KIPI_ALERT_CAPTURE",
                "KIPI_LINEAR_API_KEY"):
        env.pop(var, None)
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)
    return env


def test_a_plain_python3_suite_cannot_file_through_a_bash_subprocess(tmp_path):
    """THE REPRODUCER for the round-1 finding. Real processes, no marker.

    `test_launchd_health_check.py` is the measured case and this is its shape:
    plain python3, a bash link, the writer as a grandchild. Seen RED on the
    shipped head -- exit 3, meaning the run reached Linear's auth -- because the
    guard was reading the grandchild's own identity, and the grandchild is
    alert-to-linear.py.
    """
    import subprocess

    proc = subprocess.run(
        _chain(tmp_path, "test_repro_chain.py"),
        env=_keyless_env(tmp_path), capture_output=True, text=True, timeout=60)

    assert proc.returncode == mod.EXIT_REFUSED_FIXTURE, (
        f"a test runner filed through a subprocess (rc={proc.returncode})\n"
        f"{proc.stderr}")


def test_a_production_chain_through_the_same_shim_still_reaches_linear(tmp_path):
    """The control, and the reason the reproducer proves anything.

    Same three links, same bash shim, same keyless env -- only the top process is
    named like production. A guard that walked the ancestry and refused whatever
    it found would pass the case above and swallow every alert slack-notify.sh
    raises, which this file already calls worse than the bug it fixes. Exit 3 is
    the assertion that the run got all the way to Linear's auth.
    """
    import subprocess

    proc = subprocess.run(
        _chain(tmp_path, "run_health_check.py"),
        env=_keyless_env(tmp_path), capture_output=True, text=True, timeout=60)

    assert proc.returncode == mod.EXIT_NO_KEY, (
        f"a production chain was refused (rc={proc.returncode})\n{proc.stderr}")


# --- the ancestry walk, fed a chain the case chose ---------------------------
#
# The two cases above fork real processes, which proves the signal works end to
# end and says nothing about WHY it decided. These feed the walk a table
# directly, so the parser, the depth cap and the entry-point rule each have a
# case that can fail for that one property. A signal reachable only through a
# live `ps` is a signal tested against whatever this machine was running.

def _table(*rows):
    """rows of (pid, ppid, cmdline), nearest ancestor first."""
    return {pid: (ppid, cmd) for pid, ppid, cmd in rows}


def test_the_walk_reads_the_script_an_ancestor_was_handed_not_its_arguments():
    """THE FALSE POSITIVE THAT WENT RED FIRST.

    slack-notify.sh passes the alert TEXT to its child, and an auto-commit alert
    routinely names uncommitted test files -- AUTOCOMMIT[0] carries
    `q-consult/pipeline/tests/test_hiring_harvest.py`. The first version read
    every token, so that message refused itself and the production control went
    RED. An alerting path that goes quiet whenever the alert mentions a test file
    is worse than the bug it fixes.
    """
    chain = _table(
        (10, 20, f"bash /opt/kipi/slack-notify.sh {AUTOCOMMIT[0]}"),
        (20, 1, "/opt/kipi/run_health_check.py"),
    )
    assert mod._ancestor_entrypoints(chain, start=10) == [
        "slack-notify.sh", "run_health_check.py"]


def test_the_walk_finds_a_suite_passed_as_an_interpreter_argument():
    """`python3 test_launchd_health_check.py` -- the measured shape. The suite is
    argv[1], so a rule reading argv[0] would answer `python3` and cover nothing.
    """
    chain = _table(
        (10, 20, "bash /opt/kipi/slack-notify.sh alert text"),
        (20, 1, "python3 -u /opt/kipi/tests/test_launchd_health_check.py"),
    )
    assert "test_launchd_health_check.py" in mod._ancestor_entrypoints(chain, start=10)


def _ancestry(monkeypatch, names):
    """Stand the ancestry up as `names` on an otherwise production-looking run."""
    for var in ("PYTEST_CURRENT_TEST", "KIPI_TEST_RUNNER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", [PRODUCTION_ENTRYPOINT])
    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        monkeypatch.setattr(main_mod, "__file__", PRODUCTION_ENTRYPOINT,
                            raising=False)
    monkeypatch.setattr(mod, "_ancestor_entrypoints", lambda: list(names))


def test_a_test_named_ancestor_is_what_makes_the_guard_refuse(monkeypatch):
    """The ancestry branch drives the refusal on its own, self looking clean.

    Paired with the case below: one asserts it fires, one asserts it does not, so
    neither can be satisfied by a branch that is hardwired either way.
    """
    _ancestry(monkeypatch, ["test_launchd_health_check.py"])
    reason = mod.fixture_context()
    assert reason and "parent process" in reason, reason


def test_a_production_ancestor_named_like_a_test_substring_is_not_a_test(monkeypatch):
    """`latest-run.py` one layer up. THE ANCHOR, asserted on the branch.

    Measured: swapping the ancestor `.match` for a `.search` SURVIVED the first
    version of this section, because the only thing pinning the anchor was a case
    asserting the regex directly -- which the guard's own branch is free to ignore.
    A production script whose name merely contains `test-run.py` must file, or the
    walk turns an ordinary alert into silence one process further out.
    """
    _ancestry(monkeypatch, ["latest-run.py", "slack-notify.sh"])
    assert mod.fixture_context() is None


def test_the_walk_really_hands_that_production_name_to_the_guard():
    """Kept separate from the case above, which STUBS the walk out.

    Without this, that case could be passing because the ancestry was empty
    rather than because the name was allowed -- an assertion satisfied by the
    stub instead of by the code. Asserted on the real walk, so the pair covers
    both halves: the walk produces `latest-run.py`, and the guard allows it.
    """
    chain = _table((10, 1, "python3 /opt/kipi/latest-run.py"),)
    assert mod._ancestor_entrypoints(chain, start=10) == ["latest-run.py"]


def test_the_walk_stops_at_the_depth_cap():
    """An unbounded walk on a deep chain is work done on every alert, and the
    real chain is three links. Cap asserted directly so a case can fail for it.
    """
    deep = _table(*[(pid, pid + 1, f"python3 /opt/link_{pid}.py")
                    for pid in range(10, 40)])
    got = mod._ancestor_entrypoints(deep, start=10)
    assert len(got) == mod._ANCESTRY_MAX_DEPTH


def test_a_cyclic_table_terminates_instead_of_spinning():
    """A `ps` table is read, not trusted. This runs inside a Stop hook."""
    cyclic = _table((10, 20, "python3 /opt/a.py"), (20, 10, "python3 /opt/b.py"))
    assert mod._ancestor_entrypoints(cyclic, start=10) == ["a.py", "b.py"]


def test_an_unreadable_process_table_refuses_nothing():
    """THE FAIL-OPEN, asserted rather than documented.

    No `ps`, or a table this cannot parse, must yield no ancestors and therefore
    no refusal. Failing CLOSED here would make every alert on a machine without
    `ps` disappear silently, which is the failure this whole file exists to
    prevent -- so the boundary is a property, not a comment.
    """
    assert mod._parse_process_table("") == {}
    assert mod._parse_process_table("PID PPID COMMAND\nnot a row\n") == {}
    assert mod._ancestor_entrypoints({}, start=10) == []


def test_the_table_parser_keeps_the_whole_command_line():
    """Two integers then the rest, with spaces intact -- splitting on every space
    would truncate the command at its first argument and lose the script."""
    parsed = mod._parse_process_table(
        "  10  20 python3 /opt/test_x.py --flag a b\n"
        "  20   1 /sbin/launchd\n"
        "bad row without pids\n")
    assert parsed[10] == (20, "python3 /opt/test_x.py --flag a b")
    assert parsed[20] == (1, "/sbin/launchd")
    assert len(parsed) == 2


# --- dedup behaviour against a stubbed Linear --------------------------------

class FakeLinear:
    """Records calls. Stands in for linear-sync.py's module surface."""

    def __init__(self, state_type="unstarted"):
        self.calls = []
        self.state_type = state_type
        self.created = 0
        self.comments = 0
        # The payload the last issueCreate actually sent. ASK-839 is a defect in
        # a FIELD OF THE PAYLOAD, so the fixture has to keep the payload; a test
        # that only reads the returned identifier cannot see the field at all.
        self.create_input = None
        self.labels_created = []
        self.projects = [{"id": "proj-kipi", "name": "kipi-system",
                          "description": ""}]

    def linear_api_key(self):
        return "stub"

    def graphql(self, query, variables):
        self.calls.append(query)
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [
                {"id": "lab-1", "name": "owner:sana"}]}}}
        if "issueLabelCreate" in query:
            # The team owns `owner:sana` and NOT `needs-triage`, so the healthy
            # path creates the second one. This branch was missing: the mutation
            # fell through to `return {}`, `needs-triage` never resolved, and
            # every "healthy" file in this suite was quietly DEGRADED with no
            # test able to see it -- the fixture was modelling a broken Linear
            # and calling it the happy path (found by the round-5 control).
            self.labels_created.append(variables["input"]["name"])
            return {"issueLabelCreate": {"issueLabel": {
                "id": f"lab-new-{len(self.labels_created)}"}}}
        if "projects(first" in query:
            return {"team": {"projects": {"nodes": self.projects}}}
        if "issueCreate" in query:
            self.created += 1
            self.create_input = variables["input"]
            return {"issueCreate": {"success": True, "issue": {
                "id": f"iss-{self.created}", "identifier": f"ASK-{100 + self.created}",
                "url": "https://linear.app/x"}}}
        if "issue(id" in query:
            return {"issue": {"id": "iss-1", "identifier": "ASK-101",
                              "url": "https://linear.app/x",
                              "state": {"type": self.state_type}}}
        if "commentCreate" in query:
            self.comments += 1
            return {"commentCreate": {"success": True}}
        return {}


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_state_dir", lambda: str(tmp_path))
    return tmp_path


def test_repeat_updates_one_ticket_instead_of_creating_more(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)

    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and "filed ASK-101" in line
    assert fake.created == 1

    # Same shape, different file list and count. Must NOT create a second ticket.
    for msg in AUTOCOMMIT[1:]:
        code, line = mod.file_alert(msg, now=1001.0)
        assert code == mod.EXIT_OK
    assert fake.created == 1, "a repeating alert opened more than one ticket"
    assert "repeat #4" in line


def test_repeat_inside_the_window_counts_without_commenting(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    mod.file_alert(AUTOCOMMIT[1], now=1000.0 + 60)
    assert fake.comments == 0, "commented on a repeat inside the quiet window"


def test_repeat_after_the_window_comments_once(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    later = 1000.0 + mod.REPEAT_COMMENT_AFTER_HOURS * 3600 + 1
    code, line = mod.file_alert(AUTOCOMMIT[1], now=later)
    assert fake.comments == 1 and "commented" in line


def test_recurrence_after_close_opens_a_fresh_ticket(isolated_state, monkeypatch):
    """Reopening a closed ticket would hide the recurrence, which is the signal."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    fake.state_type = "completed"
    code, line = mod.file_alert(AUTOCOMMIT[1], now=2000.0)
    assert code == mod.EXIT_OK and fake.created == 2, "closed ticket was not re-raised"


def test_missing_key_is_reported_not_swallowed(isolated_state, monkeypatch):
    class NoKey(FakeLinear):
        def linear_api_key(self):
            raise RuntimeError("no Linear API key")

    monkeypatch.setattr(mod, "_load_linear", lambda: NoKey())
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_NO_KEY
    assert AUTOCOMMIT[0] in line, "the undelivered message must stay readable"


def test_create_failure_preserves_the_message(isolated_state, monkeypatch):
    class Broken(FakeLinear):
        def graphql(self, query, variables):
            if "issueCreate" in query:
                raise RuntimeError("HTTP 500")
            return FakeLinear.graphql(self, query, variables)

    monkeypatch.setattr(mod, "_load_linear", lambda: Broken())
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_FAILED and AUTOCOMMIT[0] in line


def test_label_failure_still_files_the_ticket(isolated_state, monkeypatch):
    """A missing label must never cost the alert."""
    class NoLabels(FakeLinear):
        def graphql(self, query, variables):
            if "labels(first" in query or "issueLabelCreate" in query:
                raise RuntimeError("no label perms")
            return FakeLinear.graphql(self, query, variables)

    monkeypatch.setattr(mod, "_load_linear", lambda: NoLabels())
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and line  # filed anyway
    # ROUND 5: this test used to stop at "filed anyway", and that weak
    # assertion is what let the finding through -- it is true of both a
    # correctly-degraded file and a silently unlabelled one.
    assert "DEGRADED" in line, line


def test_the_label_query_failing_outright_is_reported_degraded(
        isolated_state, monkeypatch):
    """ROUND 5 MAJOR. Two failure points, only one of them visible.

    The round-4 fix taught the per-label CREATE path to record an unresolved
    name, so a create that failed for a real reason reached the caller's
    `[DEGRADED: ...]` suffix. The earlier point -- the LABELS_QUERY itself
    raising -- kept a bare `return []` and skipped both out-lists. A labels
    endpoint timeout therefore filed a ticket with NO labels, exit 0, and a
    result line indistinguishable from a fully-labelled file, which is the one
    thing the triage measurement cannot afford to be blind to.

    Reproduced on the PR head: degraded_visible=False, labelIds absent.
    """
    class LabelsEndpointDown(FakeLinear):
        def graphql(self, query, variables):
            if "labels(first" in query:
                raise RuntimeError("labels endpoint timeout")
            return FakeLinear.graphql(self, query, variables)

    fake = LabelsEndpointDown()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)

    # the alert still lands: a dropped alert is worse than an unlabelled one
    assert code == mod.EXIT_OK
    assert fake.created == 1
    assert "labelIds" not in (fake.create_input or {})
    # and the run's own summary line says so
    assert "DEGRADED" in line, line
    assert mod.TRIAGE_LABEL in line, line


def test_a_fully_labelled_file_is_never_marked_degraded(
        isolated_state, monkeypatch):
    """The negative control. A suffix that is always present says nothing.

    FakeLinear resolves `owner:sana` from the team and creates `needs-triage`,
    so this is the healthy path and it must come back clean.
    """
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK
    assert "DEGRADED" not in line, line


def test_title_is_one_bounded_line():
    long_msg = "[x] " + ("word " * 80)
    title = mod.title_for(long_msg)
    assert "\n" not in title and len(title) <= 113


# --- noise suppression: pure all-clear pings never become a ticket -----------
#
# THE SCAR. The 2026-08-16 Linear cleanup found 50 open tickets that were pure
# status confirmations -- heartbeat resumed, tripwire baselined, a scheduled
# post posted -- filed by this script alongside real problems, indistinguishable
# without opening each one. The founder asked for the source fixed so it stops
# happening, not just cleaned up once.
#
# Every message string below is a REAL line read directly from a live Linear
# ticket during that cleanup (get_issue, not paraphrased), same evidence
# standard as the AUTOCOMMIT fixtures above.

NOISE_EXAMPLES = [
    "[kipi-system] kipi heartbeat: RESUMED after 885 min down",
    "[dryco] kipi heartbeat: RESUMED after 99 min down",
    "[assafkip_kipi-system__pr-191] armed .claude/ integrity tripwire: 45 file(s) baselined",
    "[cole-gtm] Reddit paste-list 2026-08-13: nothing due to paste. Job ran fine",
    "[/] Daily X tool post scheduled for 2026-08-13T14:00:00-04:00. Tags: "
    "@guillaumemeyer @cathrynlavery @dillon_mulroy. (auto-posted, cancel in Publer if off)",
    "[kipi-system] converge ASK-700: APPROVE, PR #141 auto-merge armed",
    "[/] delivery self-heal tier 3 STARTED on build-radar-needs: build-radar-needs: "
    "log stale 440h (> 72h) -- the delivery job may have stopped running entirely. "
    "— dispatching a fix-agent (reproduce → fix → test → commit).",
    "[kipi-wt-729base] probe: local endpoints only, ASK-447",
    # ASK-884, filed 2026-08-16T21:17 AFTER the classifier shipped earlier the
    # same day -- a shape nobody had seen when the list above was built. Text
    # read from the ticket (get_issue) and matched byte for byte against its
    # producer, kipi-dispatch.sh:818.
    "[kipi-system] kipi dispatch: hit the daily cap of 10 issues (~60 agent "
    "sessions). Not an error -- the loop is resting until 7am, then it picks "
    "up again on its own. Do: nothing, or raise KIPI_DISPATCH_DAILY_MAX in "
    "com.kipi.dispatch.plist to go faster.",
]


def test_every_noise_example_is_recognized_as_noise():
    for msg in NOISE_EXAMPLES:
        assert mod.is_noise(msg), f"should be suppressed, was not: {msg}"


def test_real_problems_are_never_suppressed():
    """The negative self-test. A classifier broad enough to catch the noise
    examples above must not also catch messages describing an actual problem
    -- these are REAL lines from tickets that had to stay filed."""
    real_problems = [
        "[/] Daily podcast failed (2026-08-12): candidate contract failed "
        "(invented URL or missing evidence)",
        "[/] BLOCK daily-podcast: uncaught exit rc=1",
        "[kipi-system] review-redrive: ASK-294 PR #72 still has "
        "kipi/reviewer-approved failing after the machine tier.",
        "[kipi-system] converge ASK-701: stalled at 'BLOCK', no code change in round 2",
        "[kipi-system] SECURITY: unsanctioned .claude/ change -- 1 modified, "
        "0 added, 0 removed: .claude/rules/skill-hook-pairing.md | reverted 1, "
        "quarantined at q-system/output/claude-integrity/quarantine/20260816T173315Z",
        # The two OTHER things kipi-dispatch.sh can page about (its own
        # kipi-dispatch.sh:1335 and :1379 strings). The daily-cap pattern is
        # written narrowly so a dispatch FAILURE never rides in behind the
        # routine cap notice -- these are the same emitter, opposite meaning.
        "[kipi-system] kipi dispatch: could not launch the converge run for "
        "ASK-884, so NO work is happening even though the loop looks alive. "
        "Do: run `bash kipi-dispatch.sh` by hand and read the error.",
        "[kipi-system] kipi dispatch: ASK-884 was launched but died immediately "
        "-- the loop is spending budget and doing no work. Do: check "
        "~/.config/kipi/converge-ASK-884.log and whether launchd is reaping the child.",
    ]
    for msg in real_problems:
        assert not mod.is_noise(msg), f"a real problem was suppressed: {msg}"


def test_the_security_override_beats_every_noise_pattern():
    """THE ASK-870 REGRESSION TEST. A tripwire message that both mentions
    'armed'/'tripwire' (the noise shape) AND 'unsanctioned'/'reverted' (a real
    detection) must file, every time. This is the exact confusion that caused
    ASK-870 to be wrongly canceled by a reviewer during the 2026-08-16 cleanup."""
    real_detection = (
        "[kipi-system] SECURITY: unsanctioned .claude/ change -- 1 modified, "
        "0 added, 0 removed: .claude/rules/skill-hook-pairing.md | reverted 1, "
        "quarantined at q-system/output/claude-integrity/quarantine/20260816T173315Z"
    )
    assert not mod.is_noise(real_detection)
    # Also guard the inverse shape directly, independent of the fixture above
    # drifting: "armed" + "tripwire" alone is noise, the same message plus
    # "reverted" must not be.
    baseline_only = "[x] armed .claude/ integrity tripwire: 3 file(s) baselined"
    with_revert = baseline_only + " | 1 unsanctioned change reverted"
    assert mod.is_noise(baseline_only)
    assert not mod.is_noise(with_revert)


def test_noise_is_logged_locally_not_filed_as_a_ticket(isolated_state, monkeypatch):
    """A suppressed alert is never dropped -- it goes to a local log instead of
    Linear, so nothing here can accidentally hide a message that should have
    filed. Linear is never touched: no fake client is even wired up, so a
    regression that stopped checking is_noise would fail this test by trying
    to load the real module and hitting the missing-key path, not by a mock
    silently accepting a create call."""
    code, line = mod.file_alert(NOISE_EXAMPLES[0], now=1000.0)
    assert code == mod.EXIT_OK
    assert "suppressed" in line.lower()
    with open(mod._noise_log_path(), encoding="utf-8") as fh:
        logged = fh.read()
    assert NOISE_EXAMPLES[0] in logged


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --- the live-check regression -----------------------------------------------

def test_bare_filenames_without_a_directory_still_collapse():
    """Found by a LIVE check, not by this suite, which is the point of keeping it.

    Every fixture above names paths with slashes, and the path rule is greedy
    enough to swallow a trailing comma with the token. So separator residue was
    invisible here and split real tickets: with two files the ", " survived,
    with one file it did not, and one condition opened two tickets."""
    a = "[consulting] auto-commit left 3 file(s) uncommitted in consulting: a.md, b.json"
    b = "[consulting] auto-commit left 9 file(s) uncommitted in consulting: c.py (+6 more)"
    assert mod.fingerprint(a) == mod.fingerprint(b)


def test_punctuation_alone_never_decides_a_ticket():
    """Trailing punctuation, quoting and separators are formatting, not identity."""
    base = "[x] huntkit sync BLOCKED: not a git repo"
    for variant in (base + ".", base + "!", base.replace(":", " --"),
                    base.replace("BLOCKED:", "BLOCKED --"), '"' + base + '"'):
        assert mod.fingerprint(variant) == mod.fingerprint(base), variant


# --- ASK-839: every filed ticket carries a project ---------------------------
#
# THE DEFECT. issueCreate was built with teamId + labelIds and no projectId, so
# every alert landed project-unset. Measured against the live board 2026-08-15:
# 81 open alert tickets, all unset; the DoR drafter had already promoted 19 of
# them into ready-shaped work, and an unset project cannot route to any checkout,
# so those 19 were 43% of the worker's permanently-UNREACHABLE bucket.
#
# Asserted on the PAYLOAD, not on the returned identifier. The old fixture read
# only the identifier back, which is why a suite of 15 cases could not see a
# missing field in the input it never inspected.

def test_a_filed_ticket_carries_the_project_of_the_alerting_repo(isolated_state, monkeypatch, tmp_path):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    repo = tmp_path / "some-checkout"
    repo.mkdir()
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps([{"name": "kipi-system", "path": str(repo)}]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(repo))

    code, _ = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi", (
        "the ticket was filed with no project, so no checkout can ever route it")


def test_the_registry_alias_decides_the_project_not_the_directory_name(
        isolated_state, monkeypatch, tmp_path):
    """A registry row's board name and its directory routinely differ (ASK-840).

    Measured on the live board: of 81 unset alert tickets, only 33 carried a
    `[label]` prefix that is an exact project name. `consulting` lives on the
    board as another name entirely, so deriving from the directory would file
    those into nothing."""
    fake = FakeLinear()
    fake.projects = [{"id": "proj-cons", "name": "ASK Consulting", "description": ""}]
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    repo = tmp_path / "consulting"
    repo.mkdir()
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps(
        [{"name": "consulting", "linear_project": "ASK Consulting", "path": str(repo)}]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(repo))

    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert fake.create_input.get("projectId") == "proj-cons"


def test_an_unresolvable_repo_still_gets_a_project_and_still_files(
        isolated_state, monkeypatch, tmp_path):
    """22 of the 81 were raised from a cwd of `/` with no repo at all.

    They must not go back to being unset, and they must never be dropped: losing
    an alert is the failure this whole path exists to prevent. The fallback is
    the checkout this script itself runs from, which is a derivation, not a guess.
    """
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps([]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.setenv("KIPI_ALERT_FALLBACK_PROJECT", "kipi-system")

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing", now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_a_broken_project_lookup_never_costs_the_alert(isolated_state, monkeypatch):
    """Same posture as the label: a ticket with no project is worth far more than
    a dropped alert, so a lookup failure degrades rather than raises."""
    class NoProjects(FakeLinear):
        def graphql(self, query, variables):
            if "projects(first" in query:
                raise RuntimeError("no project read perms")
            return FakeLinear.graphql(self, query, variables)

    fake = NoProjects()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    code, _ = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and fake.created == 1


# --- the skeleton is a registry row too (ASK-839, PR #191 review round 3) ----
#
# `_registry_rows()` read only `reg["instances"]`, and the skeleton -- the
# checkout this script itself lives in and the single biggest alert producer on
# the board -- is NOT an instances row. It is the registry's own top-level
# `skeleton` key. So the skeleton was absent from the rows that rung 2 (repo
# path) and rung 5 (own checkout) both search, and both rungs were dead for it.
#
# Measured on the live board 2026-08-15, 82 open alert tickets: 22 carry the
# label `/` (a cwd with no repo, so no path is exported and no label resolves --
# rung 5 is their ONLY cover) and 18 carry a kipi-system worktree directory
# (`.wt-ask791`, `kipi-wt-ask729`, `cleanmain`, `dispatch-checkout`, ...), whose
# --git-common-dir path is the skeleton -- rung 2. 40 of 82 had no live rung at
# all.
#
# The registry fixture below carries the REAL file's shape, top-level `skeleton`
# alongside `instances`, because that shape IS the defect. A fixture shaped as a
# bare list -- which is what every earlier case in this file uses -- cannot see
# it, which is how a 21-case suite stayed green over a dead production path.

SKELETON_REGISTRY_SHAPE = {
    "skeleton": {"path": "/tmp/skel", "remote": "https://example.invalid/x.git",
                 "linear_project": "kipi-system"},
    "instances": [{"name": "consulting", "linear_project": "ASK Consulting",
                   "path": "/tmp/consulting"}],
}


def _registry_with_skeleton(tmp_path, skel_path, **skel_extra):
    reg = tmp_path / "instance-registry.json"
    body = json.loads(json.dumps(SKELETON_REGISTRY_SHAPE))
    body["skeleton"]["path"] = str(skel_path)
    body["skeleton"].update(skel_extra)
    reg.write_text(json.dumps(body))
    return reg


def test_the_skeleton_is_one_of_the_registry_rows(monkeypatch, tmp_path):
    """Rungs 2 and 5 both search `_registry_rows()`. A skeleton missing from that
    list is a skeleton neither rung can ever resolve."""
    reg = _registry_with_skeleton(tmp_path, tmp_path / "skel")
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))

    paths = {r.get("path") for r in mod._registry_rows()}
    assert str(tmp_path / "skel") in paths, (
        "the skeleton is absent from the rows, so an alert raised from it "
        "resolves to no project at all")


def test_an_alert_raised_from_the_skeleton_carries_the_skeleton_project(
        isolated_state, monkeypatch, tmp_path):
    """Rung 2, for the 18 worktree-labelled tickets.

    slack-notify.sh exports --git-common-dir, so a worktree alert arrives with
    the SKELETON path and a label (`.wt-ask791`) that names no project. Rung 2 is
    the whole answer for that shape."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    skel = tmp_path / "kipi-system"
    skel.mkdir()
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, skel)))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(skel))
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert(
        "[.wt-ask791] auto-commit left 3 file(s) uncommitted", now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_the_last_resort_rung_works_without_an_env_production_never_sets(
        isolated_state, monkeypatch, tmp_path):
    """Rung 5, for the 22 `[/]` tickets.

    The existing `[/]` case sets KIPI_ALERT_FALLBACK_PROJECT by hand, and NOTHING
    in this repo sets it -- grep finds one reader and no writer. So that case was
    passing on an invented fixture while the rung it claims to cover returned "".
    This one removes the env and leaves rung 5 to do the work it documents."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    # Through _common_repo_root, so this case reads the same root the rung does
    # whether the suite runs in the skeleton or in a worktree of it. Hardcoding
    # SCRIPTS/../../.. passed only in the skeleton and is a false RED elsewhere.
    own_root = os.path.realpath(mod._common_repo_root(mod._own_checkout_root()))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, own_root)))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing",
                             now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_a_skeleton_row_with_no_alias_offers_nothing_rather_than_a_guess(
        monkeypatch, tmp_path):
    """The negative self-test. Including the skeleton row must not smuggle in a
    basename derivation -- that is the ASK-840 defect this file's own docstring
    refuses. A skeleton with no `linear_project` contributes no candidate."""
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps({
        "skeleton": {"path": str(tmp_path / "kipi-system"),
                     "remote": "https://example.invalid/x.git"},
        "instances": []}))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(tmp_path / "kipi-system"))
    monkeypatch.delenv("KIPI_ALERT_PROJECT", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    assert "kipi-system" not in mod.project_candidates("[x] something broke")


def test_rung_five_survives_running_out_of_a_worktree(
        isolated_state, monkeypatch, tmp_path):
    """A worktree is never its own registry row, and the fleet's agents all run
    in one -- 18 of the 82 live alert tickets are labelled with a worktree
    directory. The last-resort rung has to reach the common repo root, the same
    fact slack-notify.sh resolves with --git-common-dir, or it is dead in exactly
    the checkouts that raise the most alerts."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    skel = tmp_path / "kipi-system"
    (skel / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt-ask999"
    wt.mkdir()
    # The real shape git writes for a linked worktree: .git is a FILE naming the
    # common dir, and the common dir's parent is the skeleton.
    (wt / ".git").write_text(f"gitdir: {skel}/.git/worktrees/wt\n")
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, skel)))
    monkeypatch.setattr(mod, "_own_checkout_root", lambda: str(wt))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing",
                             now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_the_shipped_registry_states_its_own_board_name(monkeypatch):
    """The data half, which the code half cannot supply.

    The board alias is a FIELD, never derived (ASK-840), so the skeleton row has
    to carry one or the rung stays dead with the code correct. Reading the real
    file on purpose: a fixture would pass while the shipped registry drifted.

    Asserted on the SKELETON row, not on "the checkout this test runs from" --
    the first draft did the latter and it is false by construction in a worktree,
    which is where the fleet's agents run."""
    monkeypatch.delenv("KIPI_INSTANCE_REGISTRY", raising=False)
    skel = [r for r in mod._registry_rows() if r.get("is_skeleton")]
    assert skel, "the shipped registry contributes no skeleton row"
    assert mod._linear_project_of(skel[0]), (
        "the skeleton row names no board project, so rungs 2 and 5 resolve "
        "nothing for the checkout this script lives in")


def test_the_punctuation_strip_did_not_collapse_everything():
    """Re-guards the negative case at the new, more aggressive normalization."""
    distinct = [
        "[a] auto-commit left 2 file(s) uncommitted",
        "[a] SECURITY: unsanctioned .claude/ change",
        "[a] Meeting loop could not run: NOTION_TOKEN_ASK missing",
        "[a] huntkit sync BLOCKED: not a git repo",
    ]
    assert len({mod.fingerprint(m) for m in distinct}) == len(distinct)


# --- the registry lives at the SKELETON root; this script ships to instances ---
# ASK-839, PR #191 review round 4. The fleet updater copies q-system/ and nothing
# at the repo root, so three-levels-up from an INSTANCE's scripts/ names a file
# that is not there. Measured 2026-08-15 against the live registry: 24 of 25
# instances ship this writer, 25 of 25 lack the registry, and 8 have a basename
# that is not their board alias -- so rungs 2, 3 and 5 were dead in every instance
# at once and rung 4 handed back a name no project carries.
#
# These cases load the writer FROM the copied instance tree rather than patching a
# path, because the defect is a property of where the running copy sits.

import shutil as _shutil


def _instance_checkout(tmp_path, name):
    """A kipi instance as the fleet updater leaves it: q-system/ copied in, and
    no instance-registry.json at the repo root."""
    scripts = tmp_path / name / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    _shutil.copy2(os.path.join(SCRIPTS, "alert-to-linear.py"),
                  scripts / "alert-to-linear.py")
    _shutil.copy2(os.path.join(SCRIPTS, "linear-sync.py"), scripts / "linear-sync.py")
    return tmp_path / name, scripts / "alert-to-linear.py"


def _load_at(path, tag):
    spec = importlib.util.spec_from_file_location(f"alert_at_{tag}", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _kipi_on_path(tmp_path, skeleton, monkeypatch):
    """The CLI as it is actually installed: a symlink on PATH whose realpath is
    the skeleton root (measured on this machine, /opt/homebrew/bin/kipi)."""
    # The executable bit is load-bearing, not housekeeping: shutil.which tests
    # X_OK, so a 0644 stand-in makes this fixture answer "no CLI on PATH" and the
    # case would pass or fail for a reason that has nothing to do with the rung.
    (skeleton / "kipi").write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(skeleton / "kipi", 0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    os.symlink(str(skeleton / "kipi"), str(bindir / "kipi"))
    monkeypatch.setenv("PATH", str(bindir))


@pytest.fixture
def no_registry_env(monkeypatch, tmp_path):
    """Nothing about the real machine may decide these cases."""
    for var in ("KIPI_INSTANCE_REGISTRY", "KIPI_ALERT_PROJECT",
                "KIPI_ALERT_REPO_PATH", "KIPI_ALERT_FALLBACK_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    return empty_home


def test_an_instance_alert_resolves_its_board_alias_through_the_cli(
        no_registry_env, monkeypatch, tmp_path):
    """`consulting` is `ASK Consulting` on the board. Rung 4 offers the bare
    label and no project carries it, so the registry is the only thing that can
    answer -- and from an instance it is only reachable off the skeleton."""
    inst, writer = _instance_checkout(tmp_path, "consulting")
    skel = tmp_path / "skel"
    skel.mkdir()
    (skel / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(skel), "linear_project": "kipi-system"},
        "instances": [{"name": "ASK_AI_consultant",
                       "linear_project": "ASK Consulting", "path": str(inst)}],
    }), encoding="utf-8")
    _kipi_on_path(tmp_path, skel, monkeypatch)
    m = _load_at(writer, "cli")
    got = m.project_candidates("[consulting] auto-commit left 3 file(s)")
    assert "ASK Consulting" in got, got


def test_a_launchd_alert_finds_the_registry_with_no_cli_on_path(
        no_registry_env, tmp_path):
    """3 of this repo's 5 plists set no PATH, so they inherit the minimal one and
    /opt/homebrew is absent. The canonical-home rung is what covers them."""
    inst, writer = _instance_checkout(tmp_path, "strategy")
    skel = no_registry_env / "projects" / "kipi-system"
    skel.mkdir(parents=True)
    (skel / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(skel), "linear_project": "kipi-system"},
        # Synthetic alias, not a live instance name: this repo is public and
        # validate-separation Gate 1.2 refuses a shipped file that names one.
        # What the case needs is only basename != alias, which this has.
        "instances": [{"name": "Brandprefix_strategy", "path": str(inst)}],
    }), encoding="utf-8")
    m = _load_at(writer, "launchd")
    got = m.project_candidates("[strategy] harvest failed")
    assert "Brandprefix_strategy" in got, got


def test_an_instance_with_no_registry_anywhere_invents_nothing(
        no_registry_env, tmp_path):
    """THE NEGATIVE SELF-TEST. A ladder that ends in a guess is worse than the
    dead rung it replaces: it would file every instance's alerts under one wrong
    project and still look fixed. With no registry on any rung, the only candidate
    left is the bare label the caller supplied."""
    _inst, writer = _instance_checkout(tmp_path, "website")
    m = _load_at(writer, "nothing")
    assert m.project_candidates("[website] deploy failed") == ["website"]


def test_a_skeleton_checkout_still_reads_the_registry_beside_it(
        no_registry_env, tmp_path):
    """The in-place rung stays FIRST: a skeleton checkout must read its own
    registry, never a stale one under the canonical home path."""
    root = tmp_path / "skelroot"
    scripts = root / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    _shutil.copy2(os.path.join(SCRIPTS, "alert-to-linear.py"),
                  scripts / "alert-to-linear.py")
    _shutil.copy2(os.path.join(SCRIPTS, "linear-sync.py"), scripts / "linear-sync.py")
    (root / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(root), "linear_project": "in-place"}}),
        encoding="utf-8")
    stale = no_registry_env / "projects" / "kipi-system"
    stale.mkdir(parents=True)
    (stale / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(root), "linear_project": "stale"}}),
        encoding="utf-8")
    m = _load_at(scripts / "alert-to-linear.py", "inplace")
    got = m.project_candidates("[skelroot] auto-commit left 1 file(s)")
    assert "in-place" in got, got
    assert "stale" not in got, got
