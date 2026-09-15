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

# every shipped detector must be callable and return a list.
#
# It must not reach GitHub while doing so. default-branch-ci-red made this loop
# issue 48 live `gh` calls (46s), and on a runner where gh is not logged in every
# call exits 1, the detector raises blind, and the WHOLE suite exits 1 for a
# reason that has nothing to do with the code (PR #354 review, minor 5). The spy
# counts gh subprocess calls; the detector's own wiring is exercised against a
# hermetic gh below.
_gh_subprocess_calls = []
_saved_run = fh.subprocess.run


def _gh_spy(cmd, *args, **kwargs):
    if Path(str(list(cmd)[0])).name == "gh":
        _gh_subprocess_calls.append(list(cmd))
    return _saved_run(cmd, *args, **kwargs)


def _hermetic_gh(args):
    """Every registered repo reads as a readable, workflow-less, green branch."""
    if args[0] == "api" and "/actions/workflows" in args[1]:
        return {"total_count": 0, "workflows": []}
    return {"default_branch": "main"} if args[0] == "api" else []


_saved_gh = (fh.gh_binary, fh._gh_json_caller)
fh.gh_binary, fh._gh_json_caller = (lambda: "gh"), (lambda _gh: _hermetic_gh)
fh.subprocess.run = _gh_spy
try:
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
finally:
    fh.subprocess.run = _saved_run
    fh.gh_binary, fh._gh_json_caller = _saved_gh
print(f"  ok: all {len(fh.DETECTORS)} shipped detectors run and return findings with subjects")
check("the shipped-detector loop makes no live gh call", len(_gh_subprocess_calls), 0)

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

# --- sp-32b3438d: verify --dry-run is present in detect_promoted_audit
check(
    "detect_promoted_audit includes --dry-run",
    "--dry-run" in inspect.getsource(fh.detect_promoted_audit),
    True,
)


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

# ---------------------------------------------------------------------------
# launchd-never-installed (PR #296 round 9): a committed template nobody installed
# is invisible to BOTH the drift detector (it skips a template with no live copy)
# and the dark-job detector (it walks live copies). The job just never runs.
# ---------------------------------------------------------------------------
import tempfile as _tempfile

with _tempfile.TemporaryDirectory() as _tmp:
    _templates = Path(_tmp) / "scripts"
    _agents = Path(_tmp) / "LaunchAgents"
    _templates.mkdir()
    _agents.mkdir()
    (_templates / "com.kipi.installed-one.plist").write_text("<plist/>")
    (_templates / "com.kipi.never-installed.plist").write_text("<plist/>")
    (_agents / "com.kipi.installed-one.plist").write_text("<plist/>")
    _found = fh.never_installed_findings(template_dir=_templates, launch_agents=_agents)
    check("an uninstalled template is reported",
          [f["subject"] for f in _found], ["com.kipi.never-installed"])
    check("an installed one is not",
          any("installed-one" in f["subject"] for f in _found), False)
    check("the finding names the command that fixes it",
          "install-plist.sh com.kipi.never-installed" in _found[0]["body"], True)
    check("and warns against installing from a worktree",
          "worktree" in _found[0]["body"], True)
    # The negative control: install it and the finding must disappear, or the
    # detector is one that can never go green and will nag forever.
    (_agents / "com.kipi.never-installed.plist").write_text("<plist/>")
    check("installing it clears the finding",
          fh.never_installed_findings(template_dir=_templates, launch_agents=_agents), [])

check("launchd-never-installed is registered", "launchd-never-installed" in _by_id, True)
check("it declares an action",
      _by_id.get("launchd-never-installed", {}).get("action"), "file_issue")
check("its lesson slug is a real file",
      (_LESSONS / f"{_by_id['launchd-never-installed']['lesson']}.md").is_file(), True)

# ---------------------------------------------------------------------------
# default-branch-ci-red (ASK-1174): assafkip/ktlyst-saas-product sat RED on main
# from 2026-07-07 to 2026-09-14 and the only thing that surfaced it was a human
# reading 389 GitHub notifications. Nothing in the fleet watched default-branch CI.
# ---------------------------------------------------------------------------
check("an https remote resolves to its owner/repo",
      fh.github_slug("https://github.com/assafkip/ktlyst-saas-product.git"),
      "assafkip/ktlyst-saas-product")
check("an ssh remote resolves too",
      fh.github_slug("git@github.com:assafkip/kipi-system.git"), "assafkip/kipi-system")
check("a non-GitHub remote is not watched", fh.github_slug("https://gitlab.com/a/b.git"), None)
check("no remote at all is not watched", fh.github_slug(""), None)

import json as _json

with _tempfile.TemporaryDirectory() as _tmp:
    _reg = Path(_tmp) / "instance-registry.json"
    _reg.write_text(_json.dumps({
        "skeleton": {"remote": "https://github.com/o/skeleton.git"},
        "instances": [
            {"name": "declared", "path": "/p/declared",
             "dispatch": {"expected_remote": "https://github.com/o/declared.git"}},
            {"name": "from-origin", "path": "/p/origin"},
            {"name": "same-repo-again", "path": "/p/origin-sub"},
            {"name": "no-remote", "path": "/p/none"},
        ],
        "standalone": [{"name": "elsewhere", "path": "/p/gitlab"}],
    }))
    _origins = {"/p/origin": "git@github.com:o/shared.git",
                "/p/origin-sub": "https://github.com/o/shared.git",
                "/p/none": "", "/p/gitlab": "https://gitlab.com/o/x.git"}
    check("registered repos: skeleton + declared + origin, deduped, non-GitHub dropped",
          fh.registered_github_repos(_reg, origin_of=_origins.get),
          ["o/declared", "o/shared", "o/skeleton"])
    check("no registry (an instance, not the skeleton) watches nothing",
          fh.registered_github_repos(Path(_tmp) / "absent.json", origin_of=_origins.get), None)

    # GitHub slugs are case-insensitive and `slug()` lowercases, so `O/Shared` and
    # `o/shared` were two repos sharing ONE kipi-key: two findings in one run, both
    # created before either reached the ledger (PR #354 review, nit 8).
    _reg.write_text(_json.dumps({
        "skeleton": {"remote": "https://github.com/O/Shared.git"},
        "instances": [{"name": "lower", "path": "/p/origin"}],
    }))
    check("case-variant remotes for one repo are ONE repo",
          len(fh.registered_github_repos(_reg, origin_of=_origins.get)), 1)


_WORKFLOW_IDS = {}


def _wid(workflow):
    """A stable fake workflow database id per workflow name."""
    return _WORKFLOW_IDS.setdefault(workflow, 1000 + len(_WORKFLOW_IDS))


def _run(workflow, conclusion, created, status="completed", url=None, workflow_id=None,
         sha="abc1234def"):
    return {"workflowName": workflow, "conclusion": conclusion, "status": status,
            "createdAt": created, "url": url or f"https://gh/{workflow}/{created}",
            "headSha": sha, "workflowDatabaseId": workflow_id or _wid(workflow)}


def _active(*names, path=None):
    """The workflows API's rows for workflows that exist and are enabled."""
    return [{"id": _wid(n), "name": n, "state": "active",
             "path": path or f".github/workflows/{fh.slug(n)}.yml"} for n in names]


# The real shape on ktlyst-saas-product main, newest first as `gh run list` returns it.
_KTLYST_MAIN = [
    _run("Golden Tests", "skipped", "2026-08-01T18:56:22Z"),
    _run("PRD + Issue gates", "failure", "2026-08-01T18:56:22Z"),
    _run("Test Suites", "success", "2026-08-01T18:56:22Z"),
    _run("PRD + Issue gates", "failure", "2026-07-28T15:00:00Z"),
    _run("Golden Tests", "skipped", "2026-07-28T15:00:00Z"),
    _run("PRD + Issue gates", "failure", "2026-07-07T19:46:42Z"),
]
_KTLYST_WORKFLOWS = _active("Golden Tests", "PRD + Issue gates", "Test Suites")
_red = fh.red_workflows(_KTLYST_MAIN, _KTLYST_WORKFLOWS)
check("the failing workflow is red", [r["workflow"] for r in _red], ["PRD + Issue gates"])
check("red-since is the OLDEST run of the unbroken red streak",
      _red[0]["red_since"], "2026-07-07T19:46:42Z")
# The run that STARTED the streak, not the latest one: the latest changes on every
# failing push, and it rode in the hashed body, so each new red run rewrote the
# issue and fired a Slack line ending "nothing to do now" (PR #354 review, minor 4).
check("the run that started the red streak is the one linked",
      _red[0]["url"], "https://gh/PRD + Issue gates/2026-07-07T19:46:42Z")
check("a workflow that only ever skipped is not red (no verdict is not a failure)",
      any(r["workflow"] == "Golden Tests" for r in _red), False)
# Negative control: a later success clears it, or the detector can never go green.
check("a success after the failure clears it",
      fh.red_workflows([_run("W", "success", "2026-09-02T00:00:00Z"),
                        _run("W", "failure", "2026-09-01T00:00:00Z")], _active("W")), [])
check("a newer cancelled/skipped run does not hide the failure under it",
      [r["workflow"] for r in fh.red_workflows(
          [_run("W", "cancelled", "2026-09-03T00:00:00Z"),
           _run("W", "failure", "2026-09-01T00:00:00Z")], _active("W"))], ["W"])
check("an in-progress run is not a verdict either",
      [r["workflow"] for r in fh.red_workflows(
          [_run("W", "", "2026-09-03T00:00:00Z", status="in_progress"),
           _run("W", "timed_out", "2026-09-01T00:00:00Z")], _active("W"))], ["W"])

# --- only workflows that still EXIST can make a branch red (PR #354, major) --
# ktlyst-website has zero workflows and its last runs are failures of a deleted
# `Skeleton Validation`; those runs never age out, so the repo read red forever and
# closing the issue reopened it every morning.
check("runs of a DELETED workflow are not red (the workflows API no longer lists it)",
      fh.red_workflows([_run("Skeleton Validation", "failure", "2026-04-11T19:05:47Z")], []), [])
check("runs of a DISABLED workflow are not red",
      fh.red_workflows([_run("W", "failure", "2026-09-01T00:00:00Z")],
                       [{**_active("W")[0], "state": "disabled_manually"}]), [])
# A rename inside one file keeps the workflow id and changes the run's
# workflowName. Grouped by NAME, the old name's last failure stayed red forever
# next to the new name's green.
check("a renamed workflow's old failures are superseded by its newer success",
      fh.red_workflows([_run("Checks", "success", "2026-09-02T00:00:00Z", workflow_id=_wid("CI")),
                        _run("CI", "failure", "2026-09-01T00:00:00Z")], _active("CI")), [])
check("...and a red renamed workflow shows its CURRENT name",
      [r["workflow"] for r in fh.red_workflows(
          [_run("Old name", "failure", "2026-09-01T00:00:00Z", workflow_id=_wid("New name"))],
          _active("New name"))], ["New name"])
# GitHub-managed dynamic workflows are not the repo's CI (PR #354 review, minor 2):
# kipi-investigations read red only from a 2026-06-02 Dependency Graph run.
check("a dynamic GitHub-managed workflow (Dependency Graph) is not repo CI",
      fh.red_workflows([_run("Dependency Graph", "failure", "2026-06-02T00:00:00Z")],
                       _active("Dependency Graph", path="dynamic/dependabot/update-graph")), [])

# --- the hashed body is stable while the branch STAYS red (minor 4) ----------
_newer_red = [_run("PRD + Issue gates", "failure", "2026-09-10T00:00:00Z", sha="fff9999aaa")]
_body_before = fh._red_branch_finding("o/r", "main", _red)
_body_after = fh._red_branch_finding(
    "o/r", "main", fh.red_workflows(_newer_red + _KTLYST_MAIN, _KTLYST_WORKFLOWS))
check("a new failing run on a still-red branch does not change the finding hash",
      fh.finding_hash(_body_after), fh.finding_hash(_body_before))

# A streak longer than the read window has no visible start. Naming the oldest red
# run the window still reaches would move that date every day the window slides.
_full_red = [_run("W", "failure", f"2026-09-{d:02d}T00:00:00Z") for d in range(28, 0, -1)]
_saved_window = fh.RUN_WINDOW
fh.RUN_WINDOW = 20
try:
    _slid_a = fh.red_workflows(_full_red[:20], _active("W"), window_full=True)
    _slid_b = fh.red_workflows(_full_red[1:21], _active("W"), window_full=True)
finally:
    fh.RUN_WINDOW = _saved_window
check("a streak reaching past the read window reports no red-since date",
      _slid_a[0]["red_since"], None)
check("...so a sliding window does not rewrite the issue",
      fh.finding_hash(fh._red_branch_finding("o/r", "main", _slid_a)),
      fh.finding_hash(fh._red_branch_finding("o/r", "main", _slid_b)))

# --- the body does not promise a close nobody performs (minor 6) -------------
check("the body does not claim a green run clears the issue",
      "the next default-branch run does" in _body_before["body"], False)
check("...it says the issue does not close itself",
      "does not close itself" in _body_before["body"], True)


def _fake_gh(table):
    """`gh` stand-in: ('repo'|'workflows'|'runs', slug) -> the JSON that call returns.
    An int is the nonzero exit code the call fails with. A missing 'workflows' row
    means every workflow the repo's runs name is active."""
    calls = []

    def gh_json(args):
        if args[0] == "api":
            path = args[1].split("?")[0]
            kind = "workflows" if path.endswith("/actions/workflows") else "repo"
            slug = "/".join(path.split("/")[1:3])
        else:
            kind, slug = "runs", args[args.index("-R") + 1]
        calls.append((kind, slug, tuple(args)))
        if kind == "workflows" and (kind, slug) not in table:
            names = sorted({r["workflowName"] for r in table.get(("runs", slug)) or []})
            return {"total_count": len(names), "workflows": _active(*names)}
        got = table[(kind, slug)]
        if isinstance(got, int):
            raise fh.GhCallFailed(f"exit {got}")
        return got
    gh_json.calls = calls
    return gh_json


_gh = _fake_gh({
    ("repo", "o/red"): {"default_branch": "main"},
    ("runs", "o/red"): _KTLYST_MAIN,
    ("repo", "o/green"): {"default_branch": "trunk"},
    ("runs", "o/green"): [_run("CI", "success", "2026-09-01T00:00:00Z")],
    ("repo", "o/gone"): 1,
    ("repo", "o/deleted-only"): {"default_branch": "main"},
    ("workflows", "o/deleted-only"): {"total_count": 0, "workflows": []},
    ("runs", "o/deleted-only"): [_run("Skeleton Validation", "failure", "2026-04-11T19:05:47Z")],
})
_found = fh.default_branch_ci_findings(["o/deleted-only", "o/gone", "o/green", "o/red"], _gh)
_subjects = sorted(f["subject"] for f in _found)
check("one finding for the red repo, one rollup for the unreadable one, none for deleted-only",
      _subjects, ["default-branch-ci-unreadable", "o/red"])
_red_f = next(f for f in _found if f["subject"] == "o/red")
check("the red finding names the workflow", "PRD + Issue gates" in _red_f["body"], True)
check("...how long it has been red", "2026-07-07" in _red_f["body"], True)
check("...and links the run that turned it red",
      "https://gh/PRD + Issue gates/2026-07-07T19:46:42Z" in _red_f["body"], True)
check("the title names the repo and its branch",
      "o/red" in _red_f["title"] and "main" in _red_f["title"], True)
check("runs are read for the repo's ACTUAL default branch, not an assumed main",
      [c[2][c[2].index("--branch") + 1] for c in _gh.calls if c[0] == "runs" and c[1] == "o/green"],
      ["trunk"])
_gone_f = next(f for f in _found if f["subject"] == "default-branch-ci-unreadable")
check("the unreadable rollup names the repo and the exit code, never gh's text",
      "o/gone" in _gone_f["body"] and "exit 1" in _gone_f["body"], True)
check("a green-only fleet files nothing",
      fh.default_branch_ci_findings(["o/green"], _gh), [])
try:
    fh.default_branch_ci_findings(["o/gone"], _gh)
    check("every repo unreadable raises (blind), never an all-clear", "no raise", "raise")
except fh.GhCallFailed:
    check("every repo unreadable raises (blind), never an all-clear", True, True)

# More workflows than one page returns: the unseen ones would silently read clean.
_gh_paged = _fake_gh({
    ("repo", "o/big"): {"default_branch": "main"},
    ("workflows", "o/big"): {"total_count": 150, "workflows": _active("W")},
    ("runs", "o/big"): [],
    ("repo", "o/green"): {"default_branch": "trunk"},
    ("runs", "o/green"): [_run("CI", "success", "2026-09-01T00:00:00Z")],
})
check("a repo with more workflows than one page is unreadable, not clean",
      [f["subject"] for f in fh.default_branch_ci_findings(["o/big", "o/green"], _gh_paged)],
      ["default-branch-ci-unreadable"])

# --- one repo's hung or missing gh must not blind every repo (minor 3) -------
# TimeoutExpired and OSError are not GhCallFailed, so they escaped the per-repo
# catch, `run_detectors` recorded the WHOLE detector as blind, and 23 readable
# repos went unreported because one timed out. Driven through the real
# `_gh_json_caller`, with only `subprocess.run` scripted.


class _Proc:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, "", returncode


def _scripted_run(cmd, *args, **kwargs):
    joined = " ".join(str(c) for c in cmd)
    if "o/hung" in joined:
        raise fh.subprocess.TimeoutExpired(cmd, 60)
    if "o/broken" in joined:
        raise OSError("exec format error")
    if "o/garbled" in joined:
        return _Proc("<html>not json</html>")
    if "/actions/workflows" in joined:
        return _Proc(_json.dumps({"total_count": 1, "workflows": _active("CI")}))
    if joined.split()[1] == "api":
        return _Proc(_json.dumps({"default_branch": "main"}))
    return _Proc(_json.dumps([_run("CI", "failure", "2026-09-01T00:00:00Z")]))


fh.subprocess.run = _scripted_run
try:
    _mixed = fh.default_branch_ci_findings(
        ["o/broken", "o/garbled", "o/hung", "o/red"], fh._gh_json_caller("gh"))
    _mixed_error = None
except Exception as exc:  # noqa: BLE001 - the assertion below is on exactly this
    _mixed, _mixed_error = [], exc
finally:
    fh.subprocess.run = _saved_run
check("a timeout, an OSError and non-JSON stay per-repo, never blind the detector",
      type(_mixed_error).__name__ if _mixed_error else None, None)
check("...the readable red repo is still reported",
      any(f["subject"] == "o/red" for f in _mixed), True)
_mixed_rollup = next((f["body"] for f in _mixed
                      if f["subject"] == "default-branch-ci-unreadable"), "")
check("...and all three land in the unreadable rollup",
      all(r in _mixed_rollup for r in ("o/broken", "o/garbled", "o/hung")), True)
check("the rollup names the exception type, never its message",
      "exec format error" in _mixed_rollup, False)

# The launchd job runs with PATH=/usr/bin:/bin, and gh lives in /opt/homebrew/bin.
# A bare `gh` would fail every morning while the terminal run passes.
with _tempfile.TemporaryDirectory() as _tmp:
    _fake_bin = Path(_tmp) / "gh"
    _fake_bin.write_text("#!/bin/sh\n")
    _fake_bin.chmod(0o755)
    _saved_which, _saved_fallbacks = fh.shutil.which, fh.GH_FALLBACKS
    fh.shutil.which = lambda _name: None
    try:
        fh.GH_FALLBACKS = (str(Path(_tmp) / "missing-gh"), str(_fake_bin))
        check("gh off PATH still resolves from a known install location",
              fh.gh_binary(), str(_fake_bin))
        fh.GH_FALLBACKS = (str(Path(_tmp) / "missing-gh"),)
        try:
            fh.gh_binary()
            check("no gh anywhere raises (blind)", "no raise", "GhUnavailable")
        except fh.GhUnavailable:
            check("no gh anywhere raises (blind), never an all-clear", True, True)
    finally:
        fh.shutil.which, fh.GH_FALLBACKS = _saved_which, _saved_fallbacks

check("default-branch-ci-red is registered", "default-branch-ci-red" in _by_id, True)
check("it declares an action",
      _by_id.get("default-branch-ci-red", {}).get("action"), "file_issue")
check("its lesson slug is a real file",
      (_LESSONS / f"{_by_id.get('default-branch-ci-red', {}).get('lesson')}.md").is_file(), True)

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
