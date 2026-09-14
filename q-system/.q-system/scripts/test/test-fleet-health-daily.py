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


def _run(workflow, conclusion, created, status="completed", url=None):
    return {"workflowName": workflow, "conclusion": conclusion, "status": status,
            "createdAt": created, "url": url or f"https://gh/{workflow}/{created}",
            "headSha": "abc1234def"}


# The real shape on ktlyst-saas-product main, newest first as `gh run list` returns it.
_KTLYST_MAIN = [
    _run("Golden Tests", "skipped", "2026-08-01T18:56:22Z"),
    _run("PRD + Issue gates", "failure", "2026-08-01T18:56:22Z"),
    _run("Test Suites", "success", "2026-08-01T18:56:22Z"),
    _run("PRD + Issue gates", "failure", "2026-07-28T15:00:00Z"),
    _run("Golden Tests", "skipped", "2026-07-28T15:00:00Z"),
    _run("PRD + Issue gates", "failure", "2026-07-07T19:46:42Z"),
]
_red = fh.red_workflows(_KTLYST_MAIN)
check("the failing workflow is red", [r["workflow"] for r in _red], ["PRD + Issue gates"])
check("red-since is the OLDEST run of the unbroken red streak",
      _red[0]["red_since"], "2026-07-07T19:46:42Z")
check("and the latest red run is the one linked",
      _red[0]["url"], "https://gh/PRD + Issue gates/2026-08-01T18:56:22Z")
check("a workflow that only ever skipped is not red (no verdict is not a failure)",
      any(r["workflow"] == "Golden Tests" for r in _red), False)
# Negative control: a later success clears it, or the detector can never go green.
check("a success after the failure clears it",
      fh.red_workflows([_run("W", "success", "2026-09-02T00:00:00Z"),
                        _run("W", "failure", "2026-09-01T00:00:00Z")]), [])
check("a newer cancelled/skipped run does not hide the failure under it",
      [r["workflow"] for r in fh.red_workflows(
          [_run("W", "cancelled", "2026-09-03T00:00:00Z"),
           _run("W", "failure", "2026-09-01T00:00:00Z")])], ["W"])
check("an in-progress run is not a verdict either",
      [r["workflow"] for r in fh.red_workflows(
          [_run("W", "", "2026-09-03T00:00:00Z", status="in_progress"),
           _run("W", "timed_out", "2026-09-01T00:00:00Z")])], ["W"])


def _fake_gh(table):
    """`gh` stand-in: ('repo', slug) -> default branch, ('runs', slug) -> run list.
    A value that is an int is the nonzero exit code that call returns."""
    calls = []

    def gh_json(args):
        kind = "repo" if args[0] == "api" else "runs"
        slug = args[1].split("/", 1)[1] if kind == "repo" else args[args.index("-R") + 1]
        calls.append((kind, slug, tuple(args)))
        got = table[(kind, slug)]
        if isinstance(got, int):
            raise fh.GhCallFailed(got)
        return got
    gh_json.calls = calls
    return gh_json


_gh = _fake_gh({
    ("repo", "o/red"): {"default_branch": "main"},
    ("runs", "o/red"): _KTLYST_MAIN,
    ("repo", "o/green"): {"default_branch": "trunk"},
    ("runs", "o/green"): [_run("CI", "success", "2026-09-01T00:00:00Z")],
    ("repo", "o/gone"): 1,
})
_found = fh.default_branch_ci_findings(["o/gone", "o/green", "o/red"], _gh)
_subjects = sorted(f["subject"] for f in _found)
check("one finding for the red repo, one rollup for the unreadable one",
      _subjects, ["default-branch-ci-unreadable", "o/red"])
_red_f = next(f for f in _found if f["subject"] == "o/red")
check("the red finding names the workflow", "PRD + Issue gates" in _red_f["body"], True)
check("...how long it has been red", "2026-07-07" in _red_f["body"], True)
check("...and links the failing run",
      "https://gh/PRD + Issue gates/2026-08-01T18:56:22Z" in _red_f["body"], True)
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
