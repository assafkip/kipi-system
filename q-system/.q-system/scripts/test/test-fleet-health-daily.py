#!/usr/bin/env python3
"""Pairs with fleet-health-daily.py.

The contract under test is the founder's rule, 2026-07-26: "detection without a
path to action is useless... the system should learn." A detector that only alerts
has moved the work back onto the founder. Prose cannot hold that line, so the
registry validator does — and this file is what proves the validator refuses.

Also guards the false-positive case that was live on day one: matching cron
scripts by BASENAME flagged 3 jobs when only 1 was a real duplicate. Linear issues
cannot be deleted here, so a false positive is a permanent one.

Run: python3 test-fleet-health-daily.py   (exit 0 = pass)
"""

import importlib.util
import sys
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[1] / "fleet-health-daily.py"
_spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


def check_rejects(name, detector, needle):
    problems = fh.validate_detectors([detector])
    if not any(needle in p for p in problems):
        failures.append(f"{name}: expected a problem containing {needle!r}, got {problems!r}")
    else:
        print(f"  ok: {name}")


ok_detector = {
    "id": "x", "description": "d", "detect": lambda _c: [],
    "action": "file_issue", "lesson": "some-lesson",
}

# --- the shipped registry must satisfy its own contract ---------------------
check("the real registry is valid", fh.validate_detectors(), [])
check("registry is non-empty", len(fh.DETECTORS) > 0, True)

# --- THE RULE: detection with no action path is refused ---------------------
check_rejects(
    "a detector with no action is refused",
    {**ok_detector, "action": None},
    "action must be",
)
check_rejects(
    "a detector with a bogus action is refused",
    {**ok_detector, "action": "notify_founder"},
    "action must be",
)

# --- THE RULE: prevention outranks detection --------------------------------
d = {**ok_detector}
d.pop("lesson")
check_rejects("a detector that cannot learn is refused", d, "lesson")

check(
    "an explicit waiver satisfies the learning leg",
    fh.validate_detectors([{**d, "lesson_waived": "one-off by nature"}]),
    [],
)

# --- an auto_fix claim must actually be wired -------------------------------
check_rejects(
    "auto_fix without a fix() is refused",
    {**ok_detector, "action": "auto_fix"},
    "no fix() is wired",
)
check(
    "auto_fix WITH a fix() is accepted",
    fh.validate_detectors([{**ok_detector, "action": "auto_fix", "fix": lambda f: None}]),
    [],
)

# --- dedup keys must be stable, or every morning files a new permanent issue -
check(
    "finding_key is stable and namespaced",
    fh.finding_key("launchd-dark", "com.cole.daily-podcast"),
    "fleet-health/launchd-dark/com-cole-daily-podcast",
)
check(
    "finding_key is deterministic across calls",
    fh.finding_key("a", "B c!") == fh.finding_key("a", "B c!"),
    True,
)

# --- the false positive that was live on day one ----------------------------
# `run_daily.sh` exists under reddit-build-radar, daily-podcast AND story-podcast.
# Only the first is genuinely double-scheduled. Basename matching flagged all 3.
check(
    "slug() collapses punctuation so keys cannot fork on formatting",
    fh.slug("com.cole.reddit-radar-daily"),
    "com-cole-reddit-radar-daily",
)

# every shipped detector must be callable and return a list
for det in fh.DETECTORS:
    try:
        result = det["detect"](None)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"detector {det['id']} raised: {exc}")
        continue
    if not isinstance(result, list):
        failures.append(f"detector {det['id']} returned {type(result).__name__}, want list")
        continue
    for f in result:
        if not f.get("subject"):
            failures.append(f"detector {det['id']} emitted a finding with no stable subject")
print(f"  ok: all {len(fh.DETECTORS)} shipped detectors run and return findings with subjects")

# --- a dead filer must not read like a clean run (ASK-181 review, finding 1) --
# file_findings catches its own network errors and returns skipped_no_key=N. This
# job's report printed created + existing only, so "Linear was unreachable and 5
# findings went nowhere" printed byte-identically to "the fleet is clean". Same
# defect, same fix as launchd-health-check.py -- fixing only the watchdog would
# have left the 08:15 job, which files the SAME findings, still lying.
_dead = {"created": 0, "existing": 0, "skipped_no_key": 2}
_clean = {"created": 0, "existing": 0, "skipped_no_key": 0}
check("a dead filer's report differs from a clean one",
      fh.outcome_line(_dead) == fh.outcome_line(_clean), False)
check("the report names findings that never reached Linear",
      "unfiled=2" in fh.outcome_line(_dead), True)
check("a clean run reports nothing unfiled", "unfiled=0" in fh.outcome_line(_clean), True)
check("the counts stay in the line",
      "filed=3" in fh.outcome_line({"created": 3, "existing": 1, "skipped_no_key": 0}), True)

# and the line must actually be the one main() prints, or the fix is a function
# nobody calls.
import inspect  # noqa: E402 - local to this assertion

check("main() reports through outcome_line", "outcome_line(" in inspect.getsource(fh.main), True)


# ===========================================================================
# ASK-204: a finding carries a REFERENCE, never untrusted text
#
# Nine PR #11 review rounds each found a new way past `_redact_secrets`. The fix
# is not a tenth pattern; it is that no crontab text is published at all. These
# assertions are what stops the redaction architecture coming back.
# ===========================================================================

# THE REPRODUCER. Both shapes are round 8 and 9's findings verbatim: a `lin_api_`
# value whose assignment starts after a BACKTICK (outside the old lookbehind's
# character class) and a backtick command substitution. Against the redaction
# design this body carried both secrets; the assertion is ZERO characters of the
# source line, which no denylist can satisfy and a line number satisfies trivially.
_SECRET_CRON = (
    "# a comment line, so line numbering has something to be wrong about\n"
    "0 3 * * * bash -lc '`LINEAR_API_KEY=lin_api_realvalue claude -p sweep`'\n"
    "0 4 * * * VAR=`echo secret` claude -p x\n"
)
_secret_findings = fh.detect_cron_shells_claude(None, cron_text=_SECRET_CRON)
check("the secret-bearing fixture is DETECTED (else the leak test proves nothing)",
      len(_secret_findings), 1)
_secret_body = _secret_findings[0]["body"] if _secret_findings else ""

for _leak in ("lin_api_realvalue", "LINEAR_API_KEY", "echo secret", "VAR="):
    check(f"the body carries no source-line fragment: {_leak!r}",
          _leak in _secret_body, False)

# Not just the secret -- no substring of either offending line survives. A body
# that leaked half a line would still pass a needle-by-needle check.
for _number, _line in enumerate(_SECRET_CRON.splitlines(), start=1):
    _payload = fh._cron_command(_line)
    if _payload:
        check(f"line {_number}'s command text is absent from the body",
              _payload in _secret_body, False)

# What it publishes INSTEAD: a reference the operator can follow. Numbered against
# raw splitlines, so the leading comment counts and the numbers match `cat -n`.
check("the body names the offending line numbers", "line 2" in _secret_body
      and "line 3" in _secret_body, True)
check("offending_cron_lines returns numbers, not text",
      fh.offending_cron_lines(_SECRET_CRON), [2, 3])
check("a clean crontab yields no numbers",
      fh.offending_cron_lines("0 3 * * * /usr/bin/rsync -a ~/a ~/b\n"), [])

# The redaction machinery is GONE, not tightened. Named explicitly because the
# failure mode this issue exists to stop is someone re-adding a pattern table.
for _dead in ("_redact_secrets", "_ASSIGNMENT_RE", "_SECRET_PATTERNS"):
    check(f"{_dead} no longer exists", hasattr(fh, _dead), False)
check("no redaction placeholder is emitted anywhere", "<redacted>" in _secret_body, False)

# --- detection coverage is UNCHANGED ---------------------------------------
# Salvaged from sana/ask-150's suite, which is nine rounds of measured shapes.
# The reference-only rewrite changed what a finding CARRIES; if any of these
# stops detecting, it changed what the detector SEES, which is the trade the
# issue forbids.
_MUST_DETECT = [
    'claude -p "x"',                                    # bare invocation
    "timeout 1800 claude -p 'x' </dev/null",            # wrapper + redirect
    "/Users/x/.claude/local/claude -p 'x'",             # absolute path
    "bash -lc 'claude -p \"x\"'",                       # quoted shell string
    "cd ~/projects/x && claude -p 'x'",                 # after an operator
    "OUT=`claude -p 'x'`",                              # backtick substitution
    "OUT=$(claude -p 'x')",                             # $( ) substitution
    'echo "$(claude -p x)"',                            # $( ) inside double quotes
    "xargs -I {} claude -p {} < list",                   # xargs placeholder
    "sudo -uH claude -p 'x'",                           # bundled short options
    "flock -n /tmp/x.lock claude -p 'x'",               # lock-file operand
    "ssh mini claude -p 'x'",                           # ssh destination operand
    "timeout 30m claude -p 'sweep'",                    # duration suffix
    "{ claude -p x ; }",                                # brace group
    "if claude -p x ; then true ; fi",                  # shell keyword
    "command claude -p x",                              # command wrapper
    "npx claude",                                       # npx
    "grep -q '#TODO' notes.txt && claude -p 'sweep'",   # quoted # is not a comment
    "claude -p 'sweep the repo",                        # unbalanced quote, still real
    # An APOSTROPHE inside a double-quoted span is literal in sh, so everything
    # after it is still double-quoted and a substitution there still runs
    # (PR #19 review, minor 2 — verified against /bin/sh with a stub `claude`).
    'echo "don\'t $(claude -p x)"',                     # apostrophe then $( )
    'echo "don\'t" `claude -p z`',                      # apostrophe then backtick
    'echo "isn\'t `claude -p q` done"',                 # apostrophe, same span
    # ssh JOINS its remote operands and hands one string to the far shell, which
    # lexes it there. The quoted form -- the one you write so the LOCAL shell does
    # not expand it -- reached `_is_claude_token` as a single token whose basename
    # was `claude -p sweep`, so the unquoted form above was pinned while this one
    # was a silent false negative (PR #19 round-3 review, minor 2).
    "ssh mini 'claude -p sweep'",                       # quoted remote command
    'ssh mini "claude -p sweep"',                       # double-quoted remote command
    "ssh mini -- 'claude -p sweep'",                    # after an end-of-options --
    "ssh mini timeout 30 'claude -p x'",                # a wrapper on the far side
    'ssh mini echo "a; claude -p x"',                   # ssh's own quoting gotcha
]
for _line in _MUST_DETECT:
    check(f"still detects: {_line}", fh._shells_claude(_line), True)

# The false positives the matcher was narrowed to refuse. A permanent Linear
# issue cannot be deleted, so each of these is as expensive as a miss.
_MUST_NOT_DETECT = [
    "cd ~/projects/claude && ./run.sh",                 # a directory named claude
    "bash ~/.claude/hooks/rotate-logs.sh",              # a path, not a command
    "claude-code --version",                            # a different binary
    "command -v claude",                                # a lookup, runs nothing
    "sudo -u claude /opt/svc/run.sh",                   # a service account
    "ssh claude@mini ./run.sh",                         # a remote user
    "flock -n /tmp/claude.lock /opt/svc/run.sh",        # a lock file
    'echo "step one; claude -p x"',                     # quoted, not an operator
    "echo 'reminder: && claude -p x",                   # unbalanced quote, prose
    "echo 'run `claude -p x` now'",                     # single quotes suppress `` ` ``
    "true && # claude -p 'x'",                          # a real comment
    "du -sh ~/projects/claude --block-size='M",         # housekeeping over the dir
    # ...and the same apostrophe must not push the walker INTO a single-quote
    # state, which made a genuinely single-quoted substitution later on the line
    # score as an invocation — a PERMANENT false-positive issue (PR #19, minor 2).
    'echo "don\'t" \'run `claude -p x` now\'',          # apostrophe then real quoting
    'echo "won\'t" \'note: $(claude -p z)\'',           # same, with $( )
    # An UNTERMINATED double quote is a syntax error: /bin/sh runs nothing on the
    # line, including what is inside the substitution. `_shell_segments` already
    # refused to invent a command position on an unparsable line; the substitution
    # walk bypassed that guard and filed a PERMANENT issue for a line that cannot
    # execute (PR #19 round-3 review, minor 3).
    'echo "reminder: $(claude -p x)',                   # unbalanced quote, $( )
    'echo "note: `claude -p x`',                        # unbalanced quote, backtick
    'VAR="x $(claude -p sweep)',                        # ...even in an assignment
    # ssh's remote command is re-parsed, which must not make ordinary remote
    # housekeeping over a `claude` directory look like an invocation.
    "ssh mini tar -czf ~/b.tgz ~/projects/claude",      # remote housekeeping
    "ssh mini echo 'run claude -p tomorrow'",           # remote prose
]
for _line in _MUST_NOT_DETECT:
    check(f"still refuses: {_line}", fh._shells_claude(_line), False)

# --- the exception message is a reference too (ASK-204, `unfiled_reason`) ----


class _DeadLinear:
    """A linear-sync stand-in whose remote fetch fails with a talkative message."""

    LEAK = "Authorization: lin_api_leakedfromtheerror"

    def fetch_remote_state(self, *_a, **_k):
        raise RuntimeError(f"HTTP 401: {self.LEAK}")


_dead_out = fh.file_findings(
    [{"key": "fleet-health/x/y", "title": "t", "body": "b"}],
    apply=True, linear=_DeadLinear())
check("an unreachable Linear still counts every dropped finding",
      _dead_out["skipped_no_key"], 1)
check("the exception MESSAGE never reaches the outcome",
      _DeadLinear.LEAK in _dead_out.get("unfiled_reason", ""), False)
check("the exception TYPE does", "RuntimeError" in _dead_out.get("unfiled_reason", ""), True)
check("and it never reaches the Slack line either",
      _DeadLinear.LEAK in fh.notify_text(_dead_out, {}), False)

# ===========================================================================
# Operator-authored description content survives a rewrite (PR #11 major)
# ===========================================================================

_OPERATOR_NOTE = "Talked to Assaf 2026-07-20: line 3 is deliberate, do not remove."


class _FakeLinear:
    """Records mutations instead of sending them. ISSUE_* are opaque markers here."""

    ISSUE_CREATE = "create"
    ISSUE_UPDATE = "update"

    def __init__(self, description, state_type="unstarted"):
        self.tracked = {
            "linear_id": "id-1", "identifier": "ASK-1",
            "description": description, "state_type": state_type, "team_id": "team-1",
        }
        self.sent = []

    def fetch_remote_state(self, *_a, **_k):
        return "team-1", None, {"fleet-health/x/y": dict(self.tracked)}

    def read_ledger(self):
        return {}

    def append_ledger(self, records):
        self.sent.append(("ledger", records))
        return len(records)

    def reopen_state_id(self, _team_id):
        return "state-todo"

    def graphql(self, query, variables):
        self.sent.append((query, variables))
        if query == self.ISSUE_UPDATE:
            return {"issueUpdate": {"success": True, "issue": {"id": "id-1"}}}
        return {"issueCreate": {"issue": {"id": "id-2", "identifier": "ASK-2"}}}


_finding = {"key": "fleet-health/x/y", "title": "new title", "body": "new body"}
# A live issue as it exists TODAY: v1 rendering, no sentinel, operator note below.
_live_body = (
    "<!-- kipi-key: fleet-health/x/y -->\n\nold body\n\n"
    "Filed by `fleet-health-daily.py`.\n\n" + _OPERATOR_NOTE
)
_fake = _FakeLinear(_live_body)
_out = fh.file_findings([_finding], apply=True, linear=_fake)
check("a content change rewrites the tracked issue", _out["updated"], 1)
_sent_description = [v for q, v in _fake.sent if q == _FakeLinear.ISSUE_UPDATE][0]["input"]["description"]
check("the operator's note survives the rewrite", _OPERATOR_NOTE in _sent_description, True)
check("the new rendering is there too", "new body" in _sent_description, True)
check("the stale rendering is gone", "old body" in _sent_description, False)
check("exactly one kipi-key marker in the spliced body",
      _sent_description.count("<!-- kipi-key:"), 1)
check("exactly one kipi-hash marker in the spliced body",
      _sent_description.count("<!-- kipi-hash:"), 1)

# Round-trip: the body this run WROTE must survive the next run's splice too, or
# the note is preserved once and lost on the following morning.
_fake2 = _FakeLinear(_sent_description)
fh.file_findings([{"key": "fleet-health/x/y", "title": "t3", "body": "b3"}],
                 apply=True, linear=_fake2)
_second = [v for q, v in _fake2.sent if q == _FakeLinear.ISSUE_UPDATE][0]["input"]["description"]
check("the note survives a SECOND rewrite", _OPERATOR_NOTE in _second, True)
check("and is not duplicated by it", _second.count(_OPERATOR_NOTE), 1)

# An unrecognisable body is preserved whole rather than deleted (rule 3).
check("an unknown body is treated as operator-owned",
      "hand-written, no markers" in fh.operator_tail("hand-written, no markers"), True)

# An UNCHANGED finding issues no mutation at all -- the guard that stops a daily
# rewrite of an issue nothing changed on.
_settled_body = fh.issue_description(_finding["key"], _finding)
_fake3 = _FakeLinear(_settled_body)
_out3 = fh.file_findings([_finding], apply=True, linear=_fake3)
check("an unchanged finding is left alone", _out3["existing"], 1)
check("and sends no mutation", [q for q, _ in _fake3.sent], [])

# ===========================================================================
# An unlocatable ledger key has a CLEARING PATH (PR #11 minor)
# ===========================================================================


class _VanishedLinear(_FakeLinear):
    """The ledger names an issue id; Linear no longer has it."""

    def __init__(self):
        super().__init__("")
        self.created = 0

    def fetch_remote_state(self, *_a, **_k):
        return "team-1", None, {}          # not in the health project

    def read_ledger(self):
        return {"fleet-health/x/y": {"key": "fleet-health/x/y", "linear_id": "gone-1"}}

    def fetch_issue(self, _linear_id):
        return {}                           # ...and not anywhere else either

    def graphql(self, query, variables):
        if query == self.ISSUE_CREATE:
            self.created += 1
        return super().graphql(query, variables)


_vanished = _VanishedLinear()
_out4 = fh.file_findings([_finding], apply=True, linear=_vanished)
check("a vanished tracked issue is re-filed, not counted and forgotten",
      _out4["relisted"], 1)
check("re-filing means a real create", _vanished.created, 1)
check("the ledger gets the NEW issue id, so the next run resolves the key",
      [r[1][0]["linear_id"] for r in _vanished.sent if r[0] == "ledger"], ["id-2"])
check("the run still earns a Slack line while it is unresolved",
      fh.should_notify(_out4, {}, apply=True), True)
check("and the line says what happened", "re-filed" in fh.notify_text(_out4, {}), True)

# ===========================================================================
# ASK-181 contract: this is the fleet's ONE filer
# ===========================================================================
check("file_findings still accepts a filer",
      "filer" in inspect.signature(fh.file_findings).parameters, True)
check("outcome_line survives a 3-key outcome built by launchd-health-check.py",
      "unfiled=2" in fh.outcome_line({"created": 0, "existing": 0, "skipped_no_key": 2}), True)
_fake_filer = _FakeLinear("")
_fake_filer.tracked = {}
fh.file_findings([_finding], apply=True, linear=_VanishedLinear(),
                 filer="launchd-health-check.py")
check("the filer name reaches the rendered body",
      "launchd-health-check.py" in fh.issue_description(
          "k", _finding, filer="launchd-health-check.py"), True)
check("and the v1 trailer anchor recognises BOTH filers, so neither loses a note",
      fh.operator_tail("x\n\nFiled by `launchd-health-check.py`.\n\n" + _OPERATOR_NOTE),
      _OPERATOR_NOTE)

# ===========================================================================
# One crontab reader, and a blind read is never an all-clear
# ===========================================================================
check("a genuinely empty crontab is a real, readable empty",
      fh._read_crontab_result(1, "", "crontab: no crontab for assaf"), "")
try:
    fh._read_crontab_result(1, "", "crontab: permission denied")
    check("an unreadable crontab raises", "no raise", "CrontabUnavailable")
except fh.CrontabUnavailable:
    check("an unreadable crontab raises rather than reporting clean", True, True)
check("both cron detectors accept injected text",
      ["cron_text" in inspect.signature(fn).parameters
       for fn in (fh.detect_cron_shells_claude, fh.detect_duplicate_schedules)],
      [True, True])

# THE REPRODUCER (PR #19 review, minor 4): the assertion above was labelled "so
# neither shells out twice" and proved no such thing -- it checked that a
# PARAMETER existed. `run_detectors` called `detect(None)`, so `cron_text` stayed
# None and each cron detector ran its own `crontab -l`. The claim is now measured
# by spying on the subprocess call, which is the only thing that can go red if the
# wiring is removed again.
_CRON_FIXTURE = "0 3 * * * claude -p sweep\n"


class _FakeCrontab:
    """A `crontab -l` CompletedProcess stand-in, scripted per case."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_cron_detectors(returncode, stdout, stderr):
    """(crontab -l invocations, per_detector) for the two cron detectors only.

    Spies on the module's own `subprocess.run` so anything that is NOT the crontab
    read (launchctl, prd_runner) still reaches the real command -- a stub that
    swallowed every call would prove the detectors ran, not what they ran.
    """
    invocations = []
    saved = fh.subprocess.run

    def spy(cmd, *args, **kwargs):
        if list(cmd)[:2] == ["crontab", "-l"]:
            invocations.append(list(cmd))
            return _FakeCrontab(returncode, stdout, stderr)
        return saved(cmd, *args, **kwargs)

    registry = [d for d in fh.DETECTORS
                if d["id"] in ("cron-shells-claude", "schedule-duplicate")]
    fh.subprocess.run = spy
    try:
        _, per_detector = fh.run_detectors(registry)
    finally:
        fh.subprocess.run = saved
    return invocations, per_detector


_cron_reads, _cron_per = _run_cron_detectors(0, _CRON_FIXTURE, "")
check("run_detectors reads the crontab ONCE for both cron detectors",
      len(_cron_reads), 1)
check("and the shared read still reaches the detector that files on it",
      _cron_per["cron-shells-claude"], 1)

# The layer above the dedup: one read must not collapse two blind spots into one.
# A crontab that cannot be read still has to mark BOTH detectors unknown, or the
# dedup buys a silent all-clear for the second one.
_blind_reads, _blind_per = _run_cron_detectors(1, "", "crontab: permission denied")
check("an unreadable crontab is still read only once", len(_blind_reads), 1)
check("...and BOTH cron detectors are reported blind, not clean",
      sorted(did for did, n in _blind_per.items() if n == fh.DETECTOR_ERROR),
      ["cron-shells-claude", "schedule-duplicate"])
check("a blind detector is reported as unknown, not zero",
      fh.blind_detectors({"cron-shells-claude": fh.DETECTOR_ERROR, "launchd-dark": 0}),
      ["cron-shells-claude"])
check("and it earns a Slack line on its own",
      fh.should_notify({}, {"cron-shells-claude": fh.DETECTOR_ERROR}, apply=True), True)
check("the all-clear sentence is withheld when a detector was blind",
      "nothing to do now" in fh.notify_text({}, {"cron-shells-claude": fh.DETECTOR_ERROR}),
      False)

# The registry entry both cron detectors need to survive with.
_by_id = {d["id"]: d for d in fh.DETECTORS}
for _did in ("cron-shells-claude", "schedule-duplicate"):
    check(f"{_did} is still registered", _did in _by_id, True)
    check(f"{_did} declares an action", _by_id.get(_did, {}).get("action"), "file_issue")
    check(f"{_did} carries a learning leg",
          bool(_by_id.get(_did, {}).get("lesson") or _by_id.get(_did, {}).get("lesson_waived")),
          True)
_LESSONS = Path(__file__).resolve().parents[3] / "lessons"
check("cron-shells-claude's lesson slug is a real file",
      (_LESSONS / f"{_by_id['cron-shells-claude']['lesson']}.md").is_file(), True)

# ===========================================================================
# The bypass sweep detector: a finding is not spent until Linear takes it,
# and a sweeper that cannot look is blind, not clean (PR #66 review)
# ===========================================================================

import json as _json
import tempfile as _tempfile

_tmpdir = _tempfile.TemporaryDirectory()
fh.BYPASS_PENDING = Path(_tmpdir.name) / "linear-bypass-pending.json"


def _pending_now():
    if not fh.BYPASS_PENDING.is_file():
        return []
    return _json.loads(fh.BYPASS_PENDING.read_text())


class _StubSweep:
    """Stands in for the linear-bypass-sweep.py subprocess."""

    def __init__(self, payload=None, returncode=0, stdout=None):
        self.returncode = returncode
        self.stdout = _json.dumps(payload) if stdout is None else stdout


def _with_sweeper(payload=None, returncode=0, stdout=None, exists=True):
    """Run the detector against a stubbed sweeper. Returns its findings."""
    real_run, real_isfile = fh.subprocess.run, Path.is_file
    fh.subprocess.run = lambda *_a, **_k: _StubSweep(payload, returncode, stdout)
    Path.is_file = lambda self: exists if self.name == "linear-bypass-sweep.py" \
        else real_isfile(self)
    try:
        return fh.detect_unaccounted_commits(None)
    finally:
        fh.subprocess.run, Path.is_file = real_run, real_isfile


def _blind(name, **kwargs):
    try:
        _with_sweeper(**kwargs)
    except RuntimeError:
        print(f"  ok: {name}")
        return
    failures.append(f"{name}: reported a clean result instead of going blind")


_OK = {"status": "ok", "fetched": "ok", "commits": ["deadbeef1"], "recorded": 1,
       "unaccounted": 1, "scanned": 10, "rev": "origin/main"}

# --- a sweeper that could not look must not read as "nothing found" ---------
_blind("a missing sweeper is blind, not zero", exists=False)
_blind("a sweeper that exited non-zero is blind", payload=_OK, returncode=1)
_blind("unparseable sweeper output is blind", stdout="not json")
_blind("a sweeper that could not resolve the rev is blind",
       payload={**_OK, "status": "rev-not-found"})
_blind("a sweeper whose ledger write failed is blind",
       payload={**_OK, "status": "ledger-write-failed"})
_blind("a stale ref (fetch failed) is blind, because the count may be low",
       payload={**_OK, "fetched": "failed"})

# --- the finding is not spent until Linear takes it -------------------------
_first = _with_sweeper(payload=_OK)
check("a newly recorded sha produces a finding", len(_first), 1)
check("the sha is held pending until it is filed", _pending_now(), ["deadbeef1"])

# The sweep dedupes on sha forever, so the SECOND run reports nothing new. Before
# this fix that meant the finding vanished if the first filing never landed.
_again = _with_sweeper(payload={**_OK, "commits": [], "recorded": 0})
check("an unfiled sha is re-surfaced on the next run", len(_again), 1)
check("and it is still the same sha", _again[0]["body"].count("deadbeef1"), 1)

# A dry run files nothing, so it reports nothing and clears nothing.
_again[0]["key"] = "fleet-health/x/y"
fh.file_findings([_again[0]], apply=False, linear=_FakeLinear(_live_body))
check("a dry run does not clear the pending shas", _pending_now(), ["deadbeef1"])

# Linear unreachable: the filing is counted as dropped and the sha stays owed.
fh.file_findings([_again[0]], apply=True, linear=_DeadLinear())
check("an unreachable Linear does not clear the pending shas",
      _pending_now(), ["deadbeef1"])

# Accepted: now, and only now, the sha is spent.
fh.file_findings([_again[0]], apply=True, linear=_FakeLinear(_live_body))
check("a filed finding clears the pending shas", _pending_now(), [])

_clean = _with_sweeper(payload={**_OK, "commits": [], "recorded": 0})
check("with nothing owed and nothing new, there is no finding", _clean, [])

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
