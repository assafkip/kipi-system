#!/usr/bin/env python3
"""File a fleet alert as a Linear issue for Sana. The founder is never paged.

FOUNDER-DIRECTED 2026-08-10, verbatim: "I dont want to see any of these. Any of
the ones that need attention should go to Sana - not me." and then, on being
offered one carve-out for the fable-escalation cap: "the fable escalation should
be gone. I gave it clear instructions."

So there is no founder path here, and no flag that re-opens one. Every alert in
the fleet becomes a Linear ticket on team ASK labelled `owner:sana`, which is the
queue `kipi-dispatch.sh` already drains into agent sessions. That loop exists and
runs; this is a new producer for it, not a new consumer to build.

THE SCAR THIS REPLACES. #general on 2026-08-10 carried 100 messages between 09:35
and 14:06 PDT. 51 were auto-commit naming a file set that changed every turn; 35
were one cole-gtm carve-out notice re-announcing a CONFIG STATE once per run, in
duplicate pairs. The 6 that mattered -- four security reverts of unsanctioned
.claude/ changes, a Notion job dead since 13:00 -- were unreadable underneath.
A channel that reports an unchanged condition on every turn stops being read, and
then the one real alert arrives somewhere nobody looks.

DEDUP IS THE WHOLE POINT. Moving a flood from Slack to Linear would be the same
defect with a new surface, except worse: a Slack message scrolls away and a Linear
ticket has to be closed by hand. So a repeating alert is ONE issue with a comment
counter, keyed on a fingerprint that deliberately ignores the volatile parts (how
many files, which files, what time). "auto-commit left 3 file(s) ... a.py, b.py"
and "auto-commit left 9 file(s) ... c.py" are the same alert and get one ticket.

EXIT CONTRACT, mirroring slack-notify.sh so existing callers are unchanged:
  0  filed (created a ticket, or recorded a repeat on the open one)
  1  attempted and FAILED (reason on stderr, message text preserved there)
  3  no Linear API key configured -- a setup state, not an error
  4  refused: running under pytest (see the fixture guard)

Never raises. This is called from Stop hooks and launchd jobs; an alerting path
that can crash its caller is worse than the alert being lost.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4

TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")
OWNER_LABEL = "owner:sana"

# THE MARK THAT SAYS "A MACHINE FILED THIS, NOBODY ROUTED IT" (ASK-882).
#
# Measured on the live board 2026-08-16: 873 issues, 229 of them carrying no
# project at all -- created, never routed. Automated inflow outran manual triage,
# and the reason it could is that an auto-filed ticket lands in Backlog looking
# exactly like work a human scoped and put there. There is no field to filter on,
# so "everything a scanner filed today" is not a query anyone can write.
#
# WHY A LABEL AND NOT LINEAR'S OWN TRIAGE FEATURE. Team Triage is real and it IS
# reachable from the API -- `TeamUpdateInput.triageEnabled` exists, and ASK reads
# `triageEnabled: false` (introspected 2026-08-16, so this is measured, not
# assumed). It was still the wrong instrument here, for two reasons:
#
#   1. A triage-type state is NOT a backlog-type state, and both drains filter on
#      the type: linear-worker.sh:546 refuses anything whose state type is not in
#      ("backlog", "unstarted"), and linear-dor-drafter.py:194 draws its
#      DRAFTABLE_STATE_TYPES from the same pair. Flipping the flag would route
#      every new automated ticket into a state neither consumer can see, which
#      stops the flood by stopping the drain. That is not a gate, it is an outage.
#   2. Linear Triage terminates in a human pressing accept or decline. The board
#      problem was never that nobody could SEE the inflow; it was that outflow is
#      manual while inflow is not. A queue whose exit is a person is the same
#      bottleneck wearing a feature's name.
#
# So the mark is additive: the ticket still lands in Backlog where the existing
# drain already reaches it, and it carries one extra label that makes "unrouted
# machine output" a filterable set for the first time. Nothing is gated OFF.
TRIAGE_LABEL = "needs-triage"

TRIAGE_LABEL_DESCRIPTION = (
    "Filed by an automated producer, not routed by a human or a process. "
    "The issue is real work until triage says otherwise -- volume from one "
    "detector is a signal about the detector, not N separate problems. "
    "Cleared by giving the issue a project (routing it) or closing it. "
    "Written by any automated filer; measured by linear-triage-health.py."
)

# A repeat inside this window updates the counter silently. Past it, the ticket
# gets a comment so a condition that is STILL true a day later is visible as
# still-true rather than as one stale ticket nobody has touched.
REPEAT_COMMENT_AFTER_HOURS = 12

# THE MARKER A NON-PYTEST RUNNER EXPORTS (ASK-879).
#
# Presence, not truthiness: any non-blank value arms the refusal, `0` included.
# A safety guard whose off-switch is a value someone might export by accident is
# a guard that can be turned off by accident. Blank or unset is off, matching
# KIPI_ALERT_CAPTURE's own convention two functions down.
FIXTURE_ENV_MARKER = "KIPI_TEST_RUNNER"

# A test FILE, by this repo's own naming conventions (folder-structure.md): a
# `test_`/`test-` prefix or a `_test`/`-test` suffix on a .py or .sh. Matched with
# `.match` against the BASENAME only, so a production script living under a
# directory called `tests/` is not caught by its path, and `latest-run.py` -- which
# CONTAINS `test-run.py` -- is not caught by a substring. Deliberately not matched:
# `conftest.py` (pytest already sets its own marker) and any other extension.
#
# The leading anchor is `.match` itself and is NOT also written as `^`. It was, and
# that made the two redundant: a mutant dropping either alone left the other holding
# the property, the suite stayed green under both, and no test could tell them
# apart. One guard per property, so a test is able to fail for it.
_TEST_ENTRYPOINT_RE = re.compile(
    r"(?:test[_-].+|.+[_-]test)\.(?:py|sh)$", re.IGNORECASE)

# A script an interpreter was handed, test or not. Used ONLY to find where an
# ancestor's identity stops and its ARGUMENTS begin -- see `_entrypoint_of`.
_SCRIPT_TOKEN_RE = re.compile(r".+\.(?:py|sh)$", re.IGNORECASE)


def _entrypoints() -> list[str]:
    """The two places the RUNNING process's identity actually shows up.

    Both are read because they answer for different shapes. A plain-python3 test
    invoked as `python3 test_foo.py` puts the test in argv[0] AND in __main__;
    a runner that hands the interpreter a different argv still has __main__.
    Reading only one would leave a shape uncovered while looking covered.
    """
    found = [sys.argv[0] if sys.argv else ""]
    main_mod = sys.modules.get("__main__")
    found.append(getattr(main_mod, "__file__", "") or "")
    return [os.path.basename(p) for p in found if p]


# Deep enough for the real chain and several links of slack-notify.sh wrappers
# above it; short enough that the walk stops well before a login shell or the
# session leader, whose command lines have nothing to do with this run.
_ANCESTRY_MAX_DEPTH = 8


def _process_table() -> dict[int, tuple[int, str]]:
    """pid -> (ppid, command line) for every process, read in ONE `ps` call.

    One call rather than one per ancestor: this runs on an alerting path called
    from Stop hooks, and N subprocess spawns to answer one question is a cost
    paid on every alert. `-Ao pid=,ppid=,command=` is honoured by both macOS ps
    and procps, which are the two this fleet runs on.

    Returns {} on ANY failure, which is a deliberate fail-OPEN: see the boundary
    note in `_ancestor_entrypoints`.
    """
    ps = shutil.which("ps")
    if not ps:
        return {}
    try:
        out = subprocess.run(
            [ps, "-Ao", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=5, check=False).stdout
    except Exception:                                  # never crash a Stop hook
        return {}
    return _parse_process_table(out)


def _parse_process_table(out: str) -> dict[int, tuple[int, str]]:
    """Split apart from the `ps` call so a case can feed it a table directly.

    A parser reachable only through a live `ps` is a parser tested against
    whatever this machine happened to be running, which is the invented-fixture
    shape in reverse: real data nobody chose. Rows that do not start with two
    integers are skipped rather than raising -- ps prints a header on some
    platforms and this must not become the thing that breaks alerting.
    """
    table: dict[int, tuple[int, str]] = {}
    for row in out.splitlines():
        parts = row.split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2] if len(parts) > 2 else "")
    return table


def _ancestor_entrypoints(table: dict[int, tuple[int, str]] | None = None,
                          start: int | None = None) -> list[str]:
    """Basenames of every token on this process's ANCESTORS' command lines.

    WHY THIS EXISTS (PR #209 round 1, Codex major). `_entrypoints()` above reads
    the RUNNING process, and on the real chain the running process is this
    script: a suite calls slack-notify.sh, which runs alert-to-linear.py as a
    subprocess, so by the time the guard executes there is nothing test-shaped
    left to read. Every in-process case was blind to it -- calling `main()`
    directly makes argv the runner's, the one arrangement where reading self and
    reading the runner cannot be told apart. The env marker was written for this
    boundary and no runner exports it yet (sp-aecfe5d8), so until one does, the
    ancestry is the only signal that closes the measured shape.

    Exactly ONE name per ancestor, chosen by `_entrypoint_of`, never every token.
    Measured, not assumed: the first version read every token and the control
    chain went RED on `test_hiring_harvest.py` -- a path inside the ALERT TEXT,
    which slack-notify.sh passes to its child as an argument. Reading arguments
    means any alert that happens to name a test file gets swallowed, and an
    auto-commit alert naming an uncommitted test file is an ordinary Tuesday.

    HONEST BOUNDARY, and it is a fail-OPEN one on purpose. No `ps`, an
    unparseable table, a chain deeper than the cap, or a runner that daemonized
    away from its parent all yield no ancestors and therefore no refusal. A guard
    that fails CLOSED here would swallow real alerts whenever `ps` was
    unavailable, and this file already holds that a swallowed alert is worse than
    the bug it fixes. So this signal ADDS cover; it never becomes the reason an
    alert is believed to be safe.
    """
    if table is None:
        table = _process_table()
    pid = os.getppid() if start is None else start
    names: list[str] = []
    seen: set[int] = set()
    for _ in range(_ANCESTRY_MAX_DEPTH):
        if pid <= 1 or pid in seen or pid not in table:
            break
        seen.add(pid)                 # a cycle in a bad table must not spin here
        ppid, cmdline = table[pid]
        name = _entrypoint_of(cmdline)
        if name:
            names.append(name)
        pid = ppid
    return names


def _entrypoint_of(cmdline: str) -> str:
    """The script an ancestor was handed: its FIRST script-shaped token, or "".

    The interpreter comes first and the script's own arguments come after, so the
    first `.py`/`.sh` token is the boundary between what a process IS and what it
    was told to do. `python3 test_foo.py <msg>` and `python3 -u test_foo.py` both
    answer `test_foo.py`; `bash slack-notify.sh <msg>` answers `slack-notify.sh`
    and stops, so nothing in the message is ever read as an identity.

    Reading argv[0] alone would not do: a plain-python3 suite is argv[1], which is
    the whole shape this signal exists for.
    """
    for token in cmdline.split():
        base = os.path.basename(token)
        if _SCRIPT_TOKEN_RE.match(base):
            return base
    return ""


def fixture_context() -> str | None:
    """Why this run must NOT reach Linear, or None if it may. Read by main().

    SCAR, measured 2026-08-14 (sp-5a3e3b7b): this used to be one line reading
    PYTEST_CURRENT_TEST, which pytest sets and NOTHING else does. So the 2026-08-10
    refusal was closed for exactly the runner that happened to be used that day.
    test_launchd_health_check.py runs as plain python3 under a `__main__` guard,
    set no such variable, was never refused, and filed real tickets from keyed
    machines -- ASK-736 up to repeat #5, plus ASK-744 and ASK-745. Bash suites sat
    in the same hole.

    Three signals, on purpose, because each covers what the others cannot:

      1. The env marker. Propagates to grandchildren, so it survives the real
         call chain (suite -> slack-notify.sh -> this script as a subprocess),
         where nothing about the leaf process looks like a test. It costs one
         export in the runner, and today no runner pays it (sp-aecfe5d8).
      2. The entry point. Needs no cooperation at all, which is the whole point
         of a chokepoint: per-test stubbing only protects tests someone
         remembered to fix, and a marker nobody exported is per-test stubbing
         with extra steps. It cannot see across a subprocess boundary.
      3. The ANCESTRY (PR #209 round 1, Codex major). Signal 2 reads the running
         process, and across the boundary the running process is this script, so
         signals 1 and 2 together left the measured shape open while reading
         covered: signal 1 needs an export nobody makes, and signal 2 cannot see
         past the fork. Walking the parents needs neither. It fails OPEN when the
         table cannot be read -- see `_ancestor_entrypoints` -- so it is cover
         added, never cover assumed.

    Returns the reason so the stderr line names WHICH signal fired -- "REFUSED
    under pytest" and "REFUSED under KIPI_TEST_RUNNER" debug differently, and a
    swallowed alert with no attribution is the failure this path exists to
    prevent.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest"
    if (os.environ.get(FIXTURE_ENV_MARKER) or "").strip():
        return FIXTURE_ENV_MARKER
    for name in _entrypoints():
        if _TEST_ENTRYPOINT_RE.match(name):
            return f"a test entry point ({name})"
    for name in _ancestor_entrypoints():
        if _TEST_ENTRYPOINT_RE.match(name):
            return f"a test entry point in a parent process ({name})"
    return None


def _state_dir() -> str:
    """Fingerprint -> ticket map, OUTSIDE any repo.

    why (carried from auto-commit.py's ASK-603 fix): state written inside a
    project becomes an uncommitted file, which is a thing the fleet alerts ON,
    which would rewrite the state, which alerts again. The cache would be its
    own alarm.
    """
    return os.path.join(
        os.path.expanduser("~"), ".cache", "kipi", "alert-to-linear")


# Volatile spans, stripped before fingerprinting. Order matters: paths before
# bare numbers, or the digits inside a path are gone before the path matches.
#
# THE PATH RULE IS "CONTAINS A SLASH", not "starts with one. First attempt used
# `(?:/[\w.@+-]+){2,}` and the suite caught it immediately: every real
# auto-commit line names RELATIVE paths (`.prd-os/issues/lane-h.md`), so the
# anchored pattern matched nothing, the trailing filename was stripped by the
# extension rule, and the surviving `.prd-os/issues/` residue differed per
# message. Four identical alerts produced four fingerprints -- the exact flood
# this file exists to stop, reproduced inside the fix.
_VOLATILE = [
    (re.compile(r"\[\d{4}-\d{2}-\d{2}[^\]]*\]"), " "),      # trailing timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+Z-]+"), " "),     # iso stamps
    (re.compile(r"\d{4}-\d{2}-\d{2}"), " "),                # bare dates
    (re.compile(r"\S*/\S*"), " "),                          # any path-shaped token
    (re.compile(r"[\w.-]+\.(?:py|json|md|sh|yaml|yml|jsonl|html|txt|lock)\b"), " "),
    (re.compile(r"\(\+\d+ more\)"), " "),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), " "),               # sha / run ids
    (re.compile(r"\d+"), " "),                              # every remaining count
    # PUNCTUATION IS RESIDUE, and it split tickets. Found by a live check, not by
    # the suite: with 2 files the separators survive as ", ", with 1 file they do
    # not, so two firings of ONE condition hashed differently and opened two
    # tickets. The suite missed it because every real #general fixture names
    # paths WITH slashes, and `\S*/\S*` is greedy enough to swallow the trailing
    # comma along with the token -- so the bug is invisible exactly where the
    # fixtures live and appears on any message naming a bare filename.
    # Word content decides the fingerprint; nothing else does.
    (re.compile(r"[^a-z0-9 ]+"), " "),
    (re.compile(r"\s+"), " "),
]


def fingerprint(message: str) -> str:
    """Stable id for 'the same alert, said again'.

    Everything that varies between two firings of one condition is removed, so
    the dedup key is the SHAPE of the alert. This is what turns 51 auto-commit
    messages into one ticket. Tested directly: test_alert_to_linear.py pins the
    real 2026-08-10 #general strings as same-fingerprint pairs.
    """
    norm = message.strip().lower()
    for pattern, repl in _VOLATILE:
        norm = pattern.sub(repl, norm)
    return hashlib.sha256(norm.strip().encode("utf-8")).hexdigest()[:16]


def title_for(message: str) -> str:
    """A ticket title a human can scan in a list. One line, bounded."""
    line = " ".join(message.strip().split())
    return line[:110] + ("..." if len(line) > 110 else "")


# Alert shapes that are pure all-clear / no-op confirmations: nothing is broken
# and nothing needs Sana's attention, so filing+closing a ticket for each one is
# pure overhead. Evidence: the Linear cleanup on 2026-08-16 found 50 open
# tickets matching these exact shapes, none carrying content beyond the
# confirmation itself. An EXPLICIT allowlist, not a heuristic -- a message that
# matches nothing here still files a ticket, so widening this list is a
# deliberate decision, not drift.
_NOISE_PATTERNS = [
    # "kipi heartbeat: RESUMED after 99 min down" (ASK-771/807/813) -- the
    # outage already ended by the time this fires; nothing is left to fix.
    re.compile(r"heartbeat:\s*RESUMED after \d+\s*min down", re.IGNORECASE),
    # "armed .claude/ integrity tripwire: 45 file(s) baselined" (ASK-862/790/
    # 703/814) -- establishing a baseline, not a detected change. The
    # unsanctioned/reverted override below is what keeps this from ever
    # matching a real detection like ASK-870.
    re.compile(r"armed .*tripwire.*baselined", re.IGNORECASE),
    # "Reddit paste-list ...: nothing due to paste. Job ran fine" (ASK-720) --
    # explicit no-op, the job's own text says nothing happened.
    re.compile(r"nothing due to paste\.?\s*Job ran fine", re.IGNORECASE),
    # "Daily X tool post scheduled for ... (auto-posted, cancel in Publer if
    # off)" (ASK-704) -- confirms a routine scheduled action already
    # completed successfully.
    re.compile(r"scheduled for .*\(auto-posted", re.IGNORECASE),
    # "converge ASK-700: APPROVE, PR #141 auto-merge armed" (ASK-706) -- a
    # SUCCESS confirmation. Contrast with "converge ... stalled at 'BLOCK'",
    # which must still file (ASK-702).
    re.compile(r"converge .*:\s*APPROVE.*auto-merge armed", re.IGNORECASE),
    # "delivery self-heal tier 3 STARTED on ...: dispatching a fix-agent"
    # (ASK-723) -- the self-heal loop already owns this; a STARTED notice is
    # not a thing for Sana to act on. A tier that FAILED or gave up still
    # files, since this pattern only matches STARTED.
    re.compile(r"delivery self-heal tier \d+ STARTED", re.IGNORECASE),
    # "probe: local endpoints only, ASK-447" (ASK-737/739) -- a routine probe
    # result with no failure described.
    re.compile(r"probe: local endpoints only", re.IGNORECASE),
    # "kipi dispatch: hit the daily cap of 10 issues (~60 agent sessions). Not
    # an error -- the loop is resting until 7am..." (ASK-884) -- a rate limit
    # working as designed. The alert's own text says "Not an error", and the
    # loop resumes by itself at the reset hour, so there is nothing to act on.
    # Filed 21:17 on 2026-08-16, AFTER this list shipped earlier the same day:
    # the shape was simply unseen, not excluded.
    #
    # NARROW ON PURPOSE. kipi-dispatch.sh pages about three other things
    # (:449 could not record a live run, :1335 could not launch, :1379 launched
    # but died immediately) and every one of those is a real problem from the
    # SAME emitter. Anchoring on the literal cap phrase plus the digits means a
    # dispatch FAILURE can never ride in behind the routine cap notice; a
    # bare "dispatch:" prefix match would have swallowed all three.
    re.compile(r"dispatch:\s*hit the daily cap of \d+ issues", re.IGNORECASE),
]


def is_noise(message: str) -> bool:
    """True for a pure all-clear/no-op alert that should never become a ticket.

    THE OVERRIDE COMES FIRST AND WINS. ASK-870 ("SECURITY: unsanctioned
    .claude/ change -- 1 modified ... reverted 1") was wrongly canceled during
    the 2026-08-16 cleanup by a reviewer that treated it as the same shape as
    the routine "armed tripwire: N baselined" tickets. A real detected change
    always carries "unsanctioned" or "reverted" or "SECURITY" in its text; a
    routine baseline-arm never does. Checking that first means a future
    pattern added to _NOISE_PATTERNS can never repeat that mistake by
    accident -- the override applies to every pattern above, not just the
    tripwire one.
    """
    if re.search(r"unsanctioned|reverted|SECURITY", message, re.IGNORECASE):
        return False
    return any(p.search(message) for p in _NOISE_PATTERNS)


def _noise_log_path() -> str:
    return os.path.join(_state_dir(), "noise.log")


def _log_noise(message: str, now: float) -> None:
    """Never drop an alert silently -- log it locally instead of filing a
    ticket. Never raises, same posture as every other write on this path."""
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(_noise_log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"{now:.0f} {message}\n")
    except OSError:
        pass


def _load_linear():
    """Import linear-sync.py for its auth + graphql. Hyphen forces importlib.

    SINGLE WRITER for how this fleet talks to Linear. Reimplementing the key
    lookup or the errors-array handling here would be a second place to fix when
    Linear changes, and linear-sync.py's graphql() already knows that Linear
    returns HTTP 200 with an `errors` key on application failures.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "linear-sync.py")
    spec = importlib.util.spec_from_file_location("kipi_linear_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEAM_QUERY = """
query($key: String!) {
  teams(filter: { key: { eq: $key } }) { nodes { id key } }
}
"""

LABELS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { labels(first: 250) { nodes { id name } } }
}
"""

LABEL_CREATE = """
mutation($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) { success issueLabel { id name } }
}
"""

ISSUE_CREATE = """
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}
"""

ISSUE_STATE_QUERY = """
query($id: String!) {
  issue(id: $id) { id identifier url state { type } }
}
"""

COMMENT_CREATE = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success }
}
"""


def _read_state(fp: str) -> dict:
    try:
        with open(os.path.join(_state_dir(), f"{fp}.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_state(fp: str, data: dict) -> None:
    """Remember which ticket owns this fingerprint. Never raises.

    WRITTEN THEN RENAMED, not written in place. A reader that catches the file
    mid-truncate gets `{}` back from _read_state, decides no ticket exists, and
    opens a second permanent one -- the same duplicate this file's lock exists to
    prevent, arriving by a different door. Inside the lock that cannot happen;
    the rename is what protects the ONE path that runs without it, the bounded
    fallback in _fingerprint_lock. os.replace is atomic within a directory.
    """
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        final = os.path.join(_state_dir(), f"{fp}.json")
        tmp = f"{final}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, final)
    except OSError:
        pass


# HOW LONG A SECOND CALLER WAITS FOR THE FIRST ONE'S TICKET.
#
# THIS NUMBER WAS 25 AND THAT WAS THE BUG (PR #198 review round 5, major, and
# the finding is right). The comment sized it "against the work the lock covers"
# and then picked a value SHORTER than one HTTP call's own cap. A holder that is
# slow rather than stuck outlives the wait, the waiter gives up, and the
# duplicate this whole mechanism removes comes straight back. Codex reproduced
# it: two threads, wait scaled below the request duration, creates=2.
#
# So the wait is now DERIVED, not picked. linear-sync.py:374 caps each HTTP call
# at 30s, and the locked section makes at most six of them -- issue-state, team,
# labels, label-create, label-refetch, projects, issueCreate -- so a holder doing
# genuinely slow work can legitimately take minutes. Anyone adding a query inside
# _file_alert_serialized should raise the call count here in the same change.
#
# Sizing it correctly is only half the fix, and deliberately the weaker half. The
# structural half is in file_alert: a caller that does NOT hold the lock never
# creates. That is what makes the duplicate impossible for ANY value of this
# number, instead of unlikely for a well-chosen one.
#
# A long wait cannot hang a Stop hook: slack-notify.sh caps the whole call at
# `timeout 20` and reports a failed send, which is the honest answer and still
# not a duplicate. This value governs direct callers with no outer cap.
_LINEAR_HTTP_TIMEOUT = 30      # linear-sync.py:374, urlopen(..., timeout=30)
_MAX_HTTP_CALLS_LOCKED = 6     # the queries _file_alert_serialized can make
LOCK_WAIT_SECONDS = float(os.environ.get(
    "KIPI_ALERT_LOCK_WAIT_SECONDS",
    str(_LINEAR_HTTP_TIMEOUT * _MAX_HTTP_CALLS_LOCKED)))


@contextlib.contextmanager
def _fingerprint_lock(fp: str, wait: float | None = None):
    """Serialize read-state -> create-issue -> write-state for ONE fingerprint.

    THE DEFECT (PR #198 review round 4, major). file_alert reads the fingerprint
    state, and only if it finds no open ticket does it create one. Two callers
    that reach the read before either reaches the write both see "no ticket" and
    both create. The result is two PERMANENT Linear objects for one condition,
    which is expensive in a way a duplicate log line is not: nothing collapses
    them, a human closes each by hand, and a queue that repeats itself is a queue
    people learn to skim. The heartbeat is one caller that can overlap with
    itself -- each instance is bounded at 1800s, so a wide sweep can outlive the
    gap to the next fire -- but it is not the only one: ~30 call sites across six
    repos reach this writer, and launchd fires several of their jobs on the hour.

    WHY A LOCK, over the two alternatives:

      * An idempotency key on the create would be the strongest answer, and
        Linear's IssueCreateInput has no such field. There is no server-side
        dedupe to key on, so this is ruled out by the API, not by taste.
      * A claim file (O_CREAT|O_EXCL) makes the loser give up. The loser then has
        no way to learn the winner's issue id, so it either drops its occurrence
        -- losing the count that makes a repeating alert visible as repeating --
        or files anyway, which is the bug. A lock makes the loser WAIT and then
        take the existing repeat path: one ticket, count 2. That is the behaviour
        the file already documents, restored under concurrency.

    Keyed PER FINGERPRINT, not globally. A global lock would pass the duplicate
    test above and queue every unrelated alert behind the slowest HTTP call in
    the fleet; test_alert_to_linear.py measures that two different shapes still
    proceed in parallel, so a global lock fails a test rather than shipping
    quietly.

    A FAILED ACQUIRE YIELDS False AND THE CALLER MUST NOT CREATE. The first cut
    of this yielded False and let the caller file anyway, reasoning that a
    swallowed alert is worse than a duplicate one. The reasoning holds; the
    conclusion did not. It made "no duplicates" contingent on LOCK_WAIT_SECONDS
    being longer than the slowest holder, and the value shipped was shorter than
    a single HTTP timeout (PR #198 review round 5, major, reproduced by the
    reviewer with creates=2). _file_alert_serialized's may_create gate is what
    replaced it: unlocked callers may COUNT an existing ticket, never create one,
    and an unlocked caller with nothing to count returns EXIT_FAILED with the
    message intact rather than silently dropping it.

    The lock file is never unlinked. Unlinking one is its own race: a process can
    hold the lock on an inode another process has already replaced, and then both
    are "holding the lock" on different files. They are empty, one per distinct
    alert shape, and bounded by the number of shapes the fleet can emit.
    """
    wait = LOCK_WAIT_SECONDS if wait is None else wait
    handle = None
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        handle = open(os.path.join(_state_dir(), f"{fp}.lock"), "a+")
    except OSError:
        handle = None

    held = False
    if handle is not None:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
    try:
        yield held
    finally:
        if handle is not None:
            if held:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                handle.close()
            except OSError:
                pass


# The fleet convention for where the skeleton sits when nothing else can say.
# Same constant voice-dna-loader.py:63 already falls back to, deliberately: two
# scripts guessing the skeleton two different ways is a derivation split waiting
# to be found. LAST rung, never first -- see _registry_path.
CANONICAL_SKELETON = os.path.join(os.path.expanduser("~"), "projects",
                                  "kipi-system")


def _registry_path() -> str:
    """instance-registry.json. KIPI_INSTANCE_REGISTRY is the test seam.

    THE REGISTRY LIVES ONLY AT THE SKELETON ROOT, AND THIS SCRIPT SHIPS TO EVERY
    INSTANCE (ASK-839, PR #191 review round 4). The fleet updater copies
    `q-system/` and nothing at the repo root, so three-levels-up from an
    INSTANCE's scripts/ named a file that is not there. `_registry_rows()` then
    returned [] and rungs 2 (repo path), 3 (label vs registry name) and 5 (own
    checkout) were dead at once -- in the instances, which is where alerts are
    raised. Measured 2026-08-15 against the live registry: 24 of 25 instances
    ship this writer, 25 of 25 lack the registry, and 8 have a basename that is
    not their board alias. The shapes: an alias that adds a brand prefix the
    directory lacks, one written as spaced prose, one that drops a prefix the
    directory keeps, and one client engagement. The live pairs stay in
    instance-registry.json and are deliberately not copied here -- this file
    ships to every instance of a PUBLIC repo, so naming them is the leak
    validate-separation Gate 1.2 exists to refuse.
    For those 8, rung 4 offers the bare directory name, no project carries it,
    and the alert files unset -- the defect this issue is about, still live in
    every instance after three rounds fixed it in the skeleton.

    A LADDER, and the first rung that EXISTS wins:

    1. The path beside this script. FIRST so a skeleton checkout always reads its
       own registry and can never be answered by a stale copy under the canonical
       home path -- including this repo's own worktrees and CI clones.
    2. The `kipi` CLI on PATH, resolved through its symlink. A derivation from
       how the CLI is actually installed, not a constant, so it is correct for a
       skeleton at any location. `shutil.which` reads PATH in-process: no
       subprocess on the never-raises alert path, the same rule
       `_common_repo_root()` follows.
    3. CANONICAL_SKELETON. This is what covers a launchd job, whose PATH carries
       no `/opt/homebrew` -- 3 of this repo's 5 plists set no PATH at all and
       inherit the minimal one, and those are alert producers.

    NO RUNG INVENTS A NAME. When every rung misses, this returns the in-place
    path so `_registry_rows()` reads nothing and the candidate list is whatever
    the caller's own label supplied. A ladder that ended in a guess would file
    every instance's alerts under one wrong project and look fixed
    (test_an_instance_with_no_registry_anywhere_invents_nothing).
    """
    env = os.environ.get("KIPI_INSTANCE_REGISTRY")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    in_place = os.path.join(here, "..", "..", "..", "instance-registry.json")
    candidates = [in_place]
    try:
        cli = shutil.which("kipi")
        if cli:
            candidates.append(os.path.join(
                os.path.dirname(os.path.realpath(cli)), "instance-registry.json"))
    except OSError:
        pass
    candidates.append(os.path.join(CANONICAL_SKELETON, "instance-registry.json"))
    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                return candidate
        except OSError:
            continue
    return in_place


def _registry_rows() -> list:
    """Every registry row, or [] when it cannot be read. Never raises.

    THE SKELETON IS A ROW TOO, and reading only `instances` dropped it (ASK-839,
    PR #191 review round 3). The skeleton is not an instance: it is the
    registry's own top-level `skeleton` key, and it is the checkout this script
    LIVES in and the fleet's single biggest alert producer. Both rungs that
    search these rows -- the repo path (2) and this script's own checkout (5) --
    were therefore dead for it, so an alert raised from kipi-system or any of its
    worktrees resolved to no project at all unless its bare `[label]` happened to
    name a board project.

    Measured on the live board 2026-08-15, 82 open alert tickets: 22 labelled `/`
    (a cwd with no repo, so nothing is exported and no label resolves -- rung 5
    is their only cover) and 18 labelled with a kipi-system worktree directory,
    whose --git-common-dir path is the skeleton -- rung 2. 40 of 82 had no live
    rung.

    `standalone` rows stay out on purpose rather than by oversight: they carry
    `has_skeleton: false`, so they ship no slack-notify.sh and cannot reach this
    code path at all. Adding them would lengthen the candidate list with names no
    alert can ever arrive under.
    """
    try:
        with open(_registry_path(), encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(reg, dict):
        entries = reg
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    entries = reg.get("instances", reg)
    rows = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    skeleton = reg.get("skeleton")
    if isinstance(skeleton, dict) and skeleton.get("path"):
        # Tagged rather than positional so a caller can ask "which row is the
        # skeleton" without counting on it being first.
        rows = [dict(skeleton, is_skeleton=True)] + rows
    return rows


def _linear_project_of(entry: dict) -> str:
    """The name this row carries ON THE BOARD.

    THE ALIAS IS A FIELD, NOT A GUESS -- the same rule linear-worker.sh applies
    (ASK-840), and the same order: explicit `linear_project` first, `name`
    second. Deriving the board name from the directory is what produced that bug,
    and a smarter derivation would only move the day it breaks. Measured on the
    live board 2026-08-15: of the 81 unset alert tickets, only 33 carried a
    `[label]` prefix that is an exact project name.
    """
    return (entry.get("linear_project") or entry.get("name") or "").strip()


def project_candidates(message: str) -> list[str]:
    """Board-project names to try for this alert, best evidence FIRST.

    A LIST, not one answer, and that is the load-bearing part. The first cut
    returned a single name and the `[/]` case proved it wrong immediately: 22 of
    the 81 unset tickets carry the prefix `[/]` (a cwd of `/`), and another 16
    carry a worktree directory (`.wt-ask791`, `kipi-wt-ask729`, `cleanmain`).
    Each of those is a plausible-looking label that matches no project, so
    returning it as THE answer filed the ticket unset all over again while
    looking like a fix. Returning candidates lets an unresolvable label fall
    through to the fallback instead of consuming the decision.

    1. KIPI_ALERT_PROJECT -- an explicit statement by the caller.
    2. The repo PATH the alert was raised from, through the registry. This is the
       only rung that survives a worktree or a renamed directory, which is why
       slack-notify.sh resolves the path rather than passing its own label.
    3. The `[label]` prefix matched against a registry row's own name. Covers a
       caller that set KIPI_INSTANCE_NAME but no path.
    4. The `[label]` prefix taken at face value, resolved case-insensitively
       against the board later (`cole-gtm` is `cole-GTM` there).
    5. The checkout THIS SCRIPT runs from. 22 of the 81 unset tickets were raised
       from a cwd of `/` with no repo at all; the code that raised them still ran
       out of a registered checkout, so this is a derivation and not an invention.
    """
    out: list[str] = []

    def offer(name: str) -> None:
        name = (name or "").strip()
        if name and name not in out:
            out.append(name)

    offer(os.environ.get("KIPI_ALERT_PROJECT") or "")

    rows = _registry_rows()
    path = (os.environ.get("KIPI_ALERT_REPO_PATH") or "").strip()
    if path:
        try:
            want = os.path.realpath(path)
        except OSError:
            want = ""
        for row in rows:
            row_path = row.get("path")
            if not row_path:
                continue
            try:
                if want and os.path.realpath(row_path) == want:
                    offer(_linear_project_of(row))
            except OSError:
                continue

    match = re.match(r"^\[([^\]]+)\]", message.strip())
    label = (match.group(1).strip() if match else "")
    if label:
        for row in rows:
            if (row.get("name") or "").strip().lower() == label.lower():
                offer(_linear_project_of(row))
        offer(label)

    offer(os.environ.get("KIPI_ALERT_FALLBACK_PROJECT") or "")
    offer(_own_checkout_project(rows))
    return out


def _own_checkout_root() -> str:
    """The directory three levels up from this scripts/ dir. The test seam for
    the rung below, so a worktree layout can be exercised without one."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "..")


def _common_repo_root(root: str) -> str:
    """`root`, or the repo it is a linked worktree OF.

    A worktree is never its own registry row, and the fleet's agents all run in
    one -- 18 of the 82 live alert tickets on 2026-08-15 were labelled with a
    worktree directory. Without this, rung 5 misses in exactly the checkouts that
    raise the most alerts.

    Read from the `.git` FILE rather than shelled out to `git rev-parse
    --git-common-dir`: this function is on the never-raises alert path, where a
    subprocess is a new way to lose the ticket, and the file is the same fact.
    slack-notify.sh does shell out, and that is not a second derivation of one
    value -- it answers a different question (the repo the CALLER was in) at a
    point where git is already required.
    """
    try:
        with open(os.path.join(root, ".git"), encoding="utf-8") as fh:
            head = fh.read(4096).strip()
    except (OSError, ValueError):
        return root
    if not head.startswith("gitdir:"):
        return root
    gitdir = head.split(":", 1)[1].strip()
    marker = os.path.join(".git", "worktrees")
    if marker not in gitdir:
        return root
    common = gitdir.split(marker)[0]
    return common or root


def _own_checkout_project(rows: list) -> str:
    """The board project of the checkout THIS SCRIPT lives in.

    The last rung, and a derivation rather than a guess: an alert raised from a
    cwd of `/` still came from code executing out of a registered checkout, and
    that checkout is the one honest thing left to say about its origin.

    It is also the ONLY rung covering the 22 `[/]` tickets, since no path is
    exported and no label resolves for them. KIPI_ALERT_FALLBACK_PROJECT is not
    that cover: nothing in this repo sets it (one reader, no writer), so a case
    that supplies it by hand is testing an invention.
    """
    try:
        root = os.path.realpath(_common_repo_root(_own_checkout_root()))
    except OSError:
        return ""
    for row in rows:
        row_path = row.get("path")
        if not row_path:
            continue
        try:
            if os.path.realpath(row_path) == root:
                return _linear_project_of(row)
        except OSError:
            continue
    return ""


# This file already keeps its own copies of TEAM_QUERY and LABELS_QUERY rather
# than reaching into linear-sync for them, and this follows that shape. Reaching
# for `ln.TEAM_PROJECTS_QUERY` was tried first and failed silently in exactly the
# way this path must never fail: the attribute read sits inside the never-raises
# try, so a stub without that constant returned "no project" instead of erroring,
# and the reproducer stayed red with the fix already in place.
PROJECTS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { projects(first: 250) { nodes { id name } } }
}
"""


def _project_id_for(ln, team_id: str, names: list) -> str | None:
    """First of `names` that resolves to a board project id, or None.

    Matched case-insensitively on purpose: registry names and board names differ
    only by case for real rows (`cole-gtm` vs `cole-GTM`), and a case-sensitive
    compare would file those tickets unset -- the exact defect being fixed.

    NEVER RAISES, for the same reason _owner_label_id does not: a ticket with no
    project is worth far more than a dropped alert. The alert path exists because
    a swallowed alert is the worst outcome available here.
    """
    if not names:
        return None
    try:
        team = (ln.graphql(PROJECTS_QUERY, {"teamId": team_id}) or {}).get("team") or {}
        nodes = ((team.get("projects") or {}).get("nodes")) or []
    except Exception:
        return None
    by_lower = {}
    for node in nodes:
        key = (node.get("name") or "").strip().lower()
        if key and key not in by_lower:
            by_lower[key] = node.get("id")
    for name in names:
        found = by_lower.get(name.strip().lower())
        if found:
            return found
    return None


def _label_ids(ln, team_id: str, wanted: list, missing: list | None = None) -> list:
    """Ids for `wanted` label names, creating any the team lacks.

    `missing` is an optional out-list: names that could not be resolved are
    appended to it, so a caller can report a degraded file without this
    function changing its return shape or gaining the power to block.

    ONE ROUND TRIP FOR ALL OF THEM, not one per label. The previous shape took a
    single name and did its own LABELS_QUERY; adding `needs-triage` beside
    `owner:sana` by copying it would have doubled the query count on the alert
    path for no new information, and given two places to fix when Linear changes.

    A missing label must never cost the ticket: an alert filed with no label is
    still an alert Sana can find, whereas raising here would drop it entirely.
    That is also why this returns the ids it DID resolve rather than all-or-
    nothing -- losing the `needs-triage` mark is a worse board, losing the ticket
    is a lost alert, and those are not the same size of mistake.

    Names are compared lowercased because that is how the previous single-label
    version compared, and `owner:sana` on the live board is stored lowercase.
    """
    found: dict = {}
    try:
        team = (ln.graphql(LABELS_QUERY, {"teamId": team_id}) or {}).get("team") or {}
        for node in ((team.get("labels") or {}).get("nodes") or []):
            name = (node.get("name") or "").lower()
            if name in wanted and name not in found:
                found[name] = node.get("id")
    except Exception as exc:
        # THE EARLY RETURN MUST STILL REPORT, and this one did not. The round-4
        # fix taught the per-label create path to record an unresolved name, so
        # a lost-then-unrecoverable label reached the caller's `[DEGRADED: ...]`
        # suffix. This branch -- the LABELS_QUERY itself failing -- kept its
        # original bare `return []` and skipped both out-lists, so a labels
        # endpoint timeout filed a ticket with NO labels at all, exit 0, and a
        # result line reading `filed ASK-9` with nothing to distinguish it from
        # a fully-labelled file. Reproduced on the PR head: degraded_visible=
        # False, labelIds absent (Codex major round 5, PR #204).
        #
        # Same posture as every other failure here: never block the alert, never
        # let the failure be silent. Nothing is resolvable when the read failed,
        # so every wanted name is unresolved.
        for name in wanted:
            _warn_label_unresolved(name, exc)
        if missing is not None:
            missing.extend(wanted)
        return []

    for name in wanted:
        if name in found:
            continue
        # Created one at a time and each in its own try: a team that already has
        # `owner:sana` but not `needs-triage` must still come away with the id it
        # did have. A single try around the whole loop would throw away a
        # resolved id because a LATER create failed.
        try:
            payload = {"name": name, "teamId": team_id}
            if name == TRIAGE_LABEL:
                payload["description"] = TRIAGE_LABEL_DESCRIPTION
            made = ln.graphql(LABEL_CREATE, {"input": payload})
            new_id = (((made or {}).get("issueLabelCreate") or {})
                      .get("issueLabel") or {}).get("id")
            if new_id:
                found[name] = new_id
        except Exception as exc:
            # LOSING THE CREATE RACE IS NOT THE SAME AS HAVING NO LABEL. Two
            # filers running at once both read the team before either created
            # `needs-triage`; the loser's create fails because the label now
            # EXISTS, and dropping the name here filed that ticket unmarked and
            # invisible to the health script -- the failure mode being silent is
            # what made it worth a fix (Codex major, PR #204).
            #
            # The recheck is a refetch, not a parse of Linear's error prose: the
            # question "does this label exist now" is answerable directly, and
            # an answer beats matching a message string this fleet has never
            # measured. A create that failed for any OTHER reason finds nothing
            # and falls through to the old behaviour unchanged.
            existing = _refetch_label_id(ln, team_id, name)
            if existing:
                found[name] = existing
                continue
            # The refetch answered "still absent", so this was NOT a lost create
            # race -- it is a real failure (a permission error looks exactly like
            # this). Still never raises, per the rule above; it gets said out
            # loud instead.
            _warn_label_unresolved(name, exc)
            continue

    if missing is not None:
        missing.extend(n for n in wanted if n not in found)
    return [found[n] for n in wanted if n in found]


def _warn_label_unresolved(name: str, exc: Exception) -> None:
    """Say out loud that a label could not be attached. Never raises.

    THE ALERT STILL GOES OUT. This file's standing posture is that a secondary
    failure must never cost the primary alert, because a dropped alert is worse
    than an unlabelled one. But "never blocks" had quietly become "never
    observable": a create that failed for a REAL reason (a permission error,
    not a lost create race) refetched nothing, dropped the name, and the run
    still reported `filed ASK-9` with no hint the mark was missing.
    `needs-triage` is the field the entire ASK-882 queue measurement reads, so
    losing it silently makes the queue depth quietly WRONG rather than loudly
    broken -- a monitor that undercounts is worse than one that errors
    (Codex major round 4, PR #204).
    """
    print(f"alert-to-linear: WARNING could not attach the {name!r} label "
          f"({exc}). The ticket is still being filed. While {TRIAGE_LABEL!r} "
          f"is missing, the triage-queue measurement undercounts this ticket "
          f"and it needs backfilling by hand.", file=sys.stderr)


def _refetch_label_id(ln, team_id: str, name: str) -> str | None:
    """The team's id for `name`, read fresh. None when it is still absent.

    Its own function so the create loop keeps one level of nesting, and so the
    "never let a lookup cost the ticket" rule holds here too: this runs on a
    path that is ALREADY failing, so it swallows and returns None rather than
    turning a missing label into a lost alert.
    """
    try:
        team = (ln.graphql(LABELS_QUERY, {"teamId": team_id}) or {}).get("team") or {}
    except Exception:
        return None
    for node in ((team.get("labels") or {}).get("nodes") or []):
        if (node.get("name") or "").lower() == name.lower():
            return node.get("id")
    return None


def file_alert(message: str, now: float | None = None) -> tuple[int, str]:
    """(exit_code, human line). The whole job, in one place.

    The decide-and-create half runs under this fingerprint's lock -- see
    _fingerprint_lock for why two concurrent callers otherwise open two
    permanent tickets for one condition. The noise check and the key lookup stay
    OUTSIDE it on purpose: neither can create anything, and every caller on the
    machine queueing behind a lock to be told "no key configured" would be a
    stall this path invented for itself.
    """
    now = time.time() if now is None else now
    if is_noise(message):
        _log_noise(message, now)
        return EXIT_OK, f"suppressed (noise, logged not filed): {title_for(message)}"
    fp = fingerprint(message)
    ln = _load_linear()

    try:
        ln.linear_api_key()
    except Exception as exc:
        return EXIT_NO_KEY, f"no Linear key configured ({exc}); NOT filed: {message}"

    with _fingerprint_lock(fp) as held:
        return _file_alert_serialized(message, fp, ln, now, may_create=held)


def _file_alert_serialized(message: str, fp: str, ln, now: float,
                           may_create: bool = True) -> tuple[int, str]:
    """Read state -> decide -> create -> write state. Under the fingerprint lock.

    Split out rather than indented in place so the lock's extent is the function
    boundary. An `if`-shaped critical section is the kind that grows a new early
    `return` above the write and silently stops being covered.

    may_create IS THE STRUCTURAL HALF OF THE DEDUPE (PR #198 review round 5).
    The first cut of this fix proceeded normally when the lock could not be
    taken, on the reasoning that a swallowed alert is worse than a duplicate one.
    That reasoning is still true and the conclusion was still wrong: it made the
    duplicate depend on LOCK_WAIT_SECONDS being generous enough, and it was not.
    Creation is now gated on actually holding the lock, so no value of that
    number can bring the duplicate back.

    The counting path stays open without the lock, because it creates nothing.
    Two callers both counting overstates a repeat counter; that is a wrong
    number, and a wrong number is not a permanent object a human has to close.
    """
    prior = _read_state(fp)

    # A ticket already exists for this shape. Is it still open?
    if prior.get("issue_id"):
        try:
            issue = (ln.graphql(ISSUE_STATE_QUERY,
                                {"id": prior["issue_id"]}) or {}).get("issue") or {}
        except Exception:
            issue = {}
        state_type = ((issue.get("state") or {}).get("type") or "").lower()
        still_open = bool(issue.get("id")) and state_type not in ("completed", "canceled")
        if still_open:
            count = int(prior.get("count", 1)) + 1
            last_comment = float(prior.get("last_comment_at", prior.get("first_at", 0)))
            said = False
            if (now - last_comment) >= REPEAT_COMMENT_AFTER_HOURS * 3600:
                try:
                    ln.graphql(COMMENT_CREATE, {"input": {
                        "issueId": prior["issue_id"],
                        "body": (f"Still firing. {count} occurrence(s) since this "
                                 f"ticket opened.\n\nMost recent:\n```\n{message}\n```"),
                    }})
                    said = True
                except Exception:
                    pass
            _write_state(fp, {**prior, "count": count,
                              "last_at": now,
                              "last_comment_at": now if said else last_comment})
            return EXIT_OK, (f"repeat #{count} on {prior.get('identifier', '?')}"
                             f"{' (commented)' if said else ' (counted)'}")
        # Closed or gone: Sana dealt with it and it came back. That is a NEW
        # ticket on purpose -- reopening a closed one hides the recurrence,
        # which is the signal worth having.

    # THE ONE DOOR TO A PERMANENT LINEAR OBJECT, and it is barred to anyone not
    # holding this fingerprint's lock. Everything above this line either counts
    # an existing ticket or returns; everything below creates one. Placed here
    # rather than at the top of the function on purpose: the counting path is
    # safe unlocked and refusing it would drop occurrences for no gain.
    #
    # NOT SILENT. EXIT_FAILED with the message intact is slack-notify.sh's
    # documented "attempted and FAILED", which its callers already handle -- the
    # heartbeat's halt branch turns exactly this into a non-zero exit, so the
    # condition still reaches Linear through the launchd detector. A repeat that
    # is reported as unfiled costs one generic ticket that dedupes; a duplicate
    # create costs a permanent one that does not.
    if not may_create:
        return EXIT_FAILED, (
            f"another writer holds this alert's lock and did not publish a "
            f"ticket within {LOCK_WAIT_SECONDS:g}s; refusing to create a "
            f"duplicate. NOT filed: {message}")

    # Bound BEFORE the try, never inside it. A name first assigned inside a
    # try/except is only bound on the paths that got that far, and the read of
    # it below sits outside the block -- the shape that turns one failure into a
    # NameError wearing the wrong failure's name.
    unresolved_labels: list = []

    try:
        teams = (ln.graphql(TEAM_QUERY, {"key": TEAM_KEY}) or {}).get("teams") or {}
        nodes = teams.get("nodes") or []
        if not nodes:
            return EXIT_FAILED, f"no Linear team {TEAM_KEY!r}; NOT filed: {message}"
        team_id = nodes[0]["id"]

        payload = {
            "title": title_for(message),
            "teamId": team_id,
            "description": (
                f"Filed automatically by the fleet alert path. The founder is not "
                f"paged for these.\n\n```\n{message}\n```\n\n"
                f"Repeats of this same alert will be counted on THIS ticket rather "
                f"than opening new ones. If it recurs after you close it, that is a "
                f"fresh ticket and a real recurrence.\n\n"
                f"<!-- kipi-alert-fingerprint: {fp} -->"
            ),
        }
        # BOTH labels, and `needs-triage` only on a ticket being CREATED. A
        # repeat lands in the branch above and never reaches here, so re-marking
        # an issue a human already routed is structurally impossible rather than
        # merely avoided -- if this ran on the repeat path it would undo triage
        # every time the condition fired again.
        label_ids = _label_ids(ln, team_id, [OWNER_LABEL, TRIAGE_LABEL],
                               unresolved_labels)
        if label_ids:
            payload["labelIds"] = label_ids

        # A PROJECT IS ROUTING, NOT DECORATION (ASK-839). This payload carried
        # teamId + labelIds and nothing else, so every alert landed project-unset.
        # An unset project cannot route to any checkout: linear-worker.sh's
        # in_this_repo() is false for it in every repo at once, so no rotation, no
        # cursor and no clone reaches it. Measured on the live board 2026-08-15:
        # 81 open alert tickets, all unset, and the DoR drafter had already
        # promoted 19 of them into ready-shaped work that was therefore
        # permanently UNREACHABLE -- 43% of that whole bucket. The `[repo]` prefix
        # this file already writes into the TITLE was that same fact, sitting in a
        # field no query can filter on.
        project_id = _project_id_for(ln, team_id, project_candidates(message))
        if project_id:
            payload["projectId"] = project_id

        data = ln.graphql(ISSUE_CREATE, {"input": payload})
        issue = ((data or {}).get("issueCreate") or {}).get("issue") or {}
        if not issue.get("id"):
            return EXIT_FAILED, f"issueCreate returned no issue; NOT filed: {message}"
    except Exception as exc:
        return EXIT_FAILED, f"Linear create failed ({exc}); NOT filed: {message}"

    _write_state(fp, {"issue_id": issue["id"],
                      "identifier": issue.get("identifier"),
                      "count": 1, "first_at": now, "last_at": now,
                      "last_comment_at": now})
    line = f"filed {issue.get('identifier')} {issue.get('url', '')}".strip()
    if unresolved_labels:
        # STILL EXIT_OK: the alert landed, which is the job. The suffix is so the
        # run's own summary line cannot read as an unqualified success while the
        # label the triage measurement depends on is absent.
        line += f" [DEGRADED: no {', '.join(unresolved_labels)} label]"
    return EXIT_OK, line


def main(argv: list[str]) -> int:
    message = (argv[1] if len(argv) > 1 else "").strip()
    if not message:
        return EXIT_OK

    # CAPTURE HATCH -- the isolation seam bash suites need, and the reason this
    # block exists at all.
    #
    # SCAR, 2026-08-10, ten minutes old when this was written. The bash guard
    # suite isolates itself by pointing KIPI_SLACK_WEBHOOK at a local capture
    # server, then asserts on what arrived. The moment the destination became
    # Linear that stub addressed nothing, so the suite's deliberate "a
    # production run still alerts" cases filed a REAL ticket (ASK-635, canceled).
    # Switching a chokepoint's destination silently invalidates every test stub
    # aimed at the old one, and the tests keep passing their own assertions right
    # up until they write to production.
    #
    # So the capture seam is part of the destination, not part of the caller: any
    # runner that can set an env var can redirect the write. Nothing is dropped
    # -- the message is appended to the file -- and it announces itself on
    # stderr, so this can never be mistaken for a delivered alert in a job log.
    capture = os.environ.get("KIPI_ALERT_CAPTURE")
    if capture:
        try:
            with open(capture, "a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except OSError as exc:
            print(f"alert-to-linear: capture to {capture} failed ({exc}); "
                  f"NOT filed: {message}", file=sys.stderr)
            return EXIT_FAILED
        print(f"alert-to-linear: CAPTURED to {capture} (not filed to Linear): "
              f"{message}", file=sys.stderr)
        return EXIT_OK

    # FIXTURE GUARD (the same chokepoint fable-escalate.py uses for model calls).
    # SCAR 2026-08-01: three tests were found paging the founder's real Slack,
    # and while the fix sat unmerged an agent ran one from a worktree without it
    # and paged again. Per-test stubbing only protects tests someone remembered
    # to fix. A test written tomorrow must not be able to open a real ticket, so
    # the refusal lives here rather than in each suite.
    reason = fixture_context()
    if reason:
        print(f"alert-to-linear: REFUSED under {reason}. NOT filed: {message}",
              file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    try:
        code, line = file_alert(message)
    except Exception as exc:                       # never crash a Stop hook
        print(f"alert-to-linear: unexpected {exc!r}; NOT filed: {message}",
              file=sys.stderr)
        return EXIT_FAILED

    # A failed alert stays readable in the job log. A silently swallowed alert is
    # the exact failure mode this whole path exists to prevent.
    print(f"alert-to-linear: {line}", file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
