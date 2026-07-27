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
import re
import subprocess as subprocess_real
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


def _raise_unavailable(_ctx):
    """A detector that could not look at all, as opposed to one that found nothing."""
    raise fh.CrontabUnavailable("crontab -l exited 127")


class FakeLinear:
    """A whole in-memory Linear, so the update path is proven without an API call.

    Only the surface `file_findings` actually touches. Linear objects are
    permanent in production; a test that reached the real API could not be re-run.

    Issue STATE is modelled, not just the body. PR #11's second review found the
    update path rewriting a Done issue and never reopening it, so a fake that
    stored only {title, description} could not have caught the blocker.

    The READ path re-serializes markdown the way live Linear does (third review,
    finding 1): a fake that echoes bytes-as-written structurally cannot catch a
    staleness compare that trusts Linear to return markdown unchanged.
    """

    ISSUE_CREATE = "ISSUE_CREATE"
    ISSUE_UPDATE = "ISSUE_UPDATE"
    REOPEN_STATE_ID = "state-todo"

    def __init__(self):
        self.issues = {}       # linear_id -> {identifier, title, description, state_type}
        self.ledger = {}       # kipi-key -> record
        self.mutations = []    # (query, sorted input keys) in order, for assertions
        self._n = 0

    # --- test-side helpers, not part of the linear-sync surface -------------
    def close_issue(self, linear_id):
        """What the operator does after fixing the crontab: mark the rollup Done."""
        self.issues[linear_id]["state_type"] = "completed"

    @staticmethod
    def _linear_render(markdown):
        """What Linear does to a stored description on the read path: `- ` list
        bullets come back as `* `. Verified live on ASK-148 (third review,
        finding 1 — real output: bullet style sample ['* `sp-01', ...] on an
        issue no producer ever wrote `* ` into). HTML comments survive verbatim.
        """
        return re.sub(r"(?m)^- ", "* ", markdown)

    # --- the linear-sync surface fleet-health calls ------------------------
    def fetch_remote_state(self, _team_key, _repo):
        keys = {}
        for lid, node in self.issues.items():
            found = re.search(r"<!--\s*kipi-key:\s*(\S+)\s*-->", node["description"])
            if found:
                keys[found.group(1)] = {
                    "linear_id": lid,
                    "identifier": node["identifier"],
                    "description": self._linear_render(node["description"]),
                    "state_type": node["state_type"],
                    "state_name": node["state_type"],
                }
        return "team-1", {"id": "proj-1"}, keys

    def fetch_issue(self, linear_id):
        """One issue by id, in the record shape fetch_remote_state returns.

        On the base fake because it is part of the linear-sync surface
        `file_findings` calls, not a special case: a fake that only models the
        project-scoped listing cannot see an issue that left the project.
        """
        node = self.issues.get(linear_id)
        if not node:
            return {}
        return {
            "linear_id": linear_id,
            "identifier": node["identifier"],
            "description": self._linear_render(node["description"]),
            "state_type": node["state_type"],
            "state_name": node["state_type"],
            "team_id": "team-1",
        }

    def reopen_state_id(self, _team_id):
        return self.REOPEN_STATE_ID

    def read_ledger(self):
        return dict(self.ledger)

    def append_ledger(self, records):
        for rec in records:
            self.ledger[rec["key"]] = rec
        return len(records)

    def graphql(self, query, variables):
        self.mutations.append((query, sorted(variables.get("input", {}))))
        if query == self.ISSUE_CREATE:
            self._n += 1
            lid = f"id-{self._n}"
            self.issues[lid] = {
                "identifier": f"ISSUE-{self._n}",
                "title": variables["input"]["title"],
                "description": variables["input"]["description"],
                "state_type": "unstarted",
            }
            return {"issueCreate": {"success": True,
                                    "issue": {"id": lid, "identifier": f"ISSUE-{self._n}"}}}
        if query == self.ISSUE_UPDATE:
            node = self.issues[variables["id"]]
            node.update({k: v for k, v in variables["input"].items()
                         if k in ("title", "description")})
            if variables["input"].get("stateId") == self.REOPEN_STATE_ID:
                node["state_type"] = "unstarted"
            return {"issueUpdate": {"success": True,
                                    "issue": {"id": variables["id"],
                                              "identifier": node["identifier"]}}}
        raise AssertionError(f"unexpected mutation: {query!r}")

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

# --- ASK-150: cron cannot authenticate `claude` (no keychain) ---------------
# Probed 2026-07-23: `keychain_read_rc=44`. The detector's job is to catch a
# crontab line that shells `claude` BEFORE it fails at 3am with an opaque auth
# error. The fixtures are fed in directly so the test never shells `crontab -l`
# (a test that reads live machine state passes or fails for the wrong reason).

CRON_WITH_CLAUDE = """\
# a comment line that mentions claude -p must NOT count
PATH=/usr/local/bin:/usr/bin:/bin
0 3 * * * cd ~/projects/kipi-system && timeout 1800 claude -p "sweep" </dev/null
"""

# The launchd-only machine: real cron lines, none of which invoke claude. Every
# line here is a decoy that a naive substring match would flag.
CRON_LAUNCHD_ONLY = """\
# claude -p "this is a comment, not a job"
CLAUDE_HOME=/Users/x/.claude
30 2 * * * bash ~/.claude/hooks/rotate-logs.sh
0 8 * * * cd ~/projects/claude && ./run_daily.sh
15 * * * * python3 ~/projects/kipi-system/q-system/.q-system/scripts/fleet-health-daily.py
"""

claude_findings = fh.detect_cron_shells_claude(None, cron_text=CRON_WITH_CLAUDE)
check("a crontab line shelling `claude -p` is detected", len(claude_findings), 1)
check(
    "the finding rolls up under ONE stable subject",
    claude_findings[0]["subject"] if claude_findings else None,
    "cron-shells-claude",
)
check(
    "a launchd-only crontab produces no finding",
    fh.detect_cron_shells_claude(None, cron_text=CRON_LAUNCHD_ONLY),
    [],
)
check("an empty crontab produces no finding", fh.detect_cron_shells_claude(None, cron_text=""), [])

# The false positives that would file a PERMANENT issue, asserted one by one.
check("`cd` into a dir named claude is not an invocation",
      fh._shells_claude("cd ~/projects/claude && ./run.sh"), False)
check("a script under ~/.claude/ is not an invocation",
      fh._shells_claude("bash ~/.claude/hooks/rotate-logs.sh"), False)
check("a claude-prefixed binary is not `claude`",
      fh._shells_claude("claude-code --version"), False)

# The true positives, including the wrapper shapes this fleet actually uses.
check("bare `claude -p` is an invocation", fh._shells_claude('claude -p "x"'), True)
check("`timeout 1800 claude` is an invocation",
      fh._shells_claude("timeout 1800 claude -p 'x' </dev/null"), True)
check("an absolute claude path is an invocation",
      fh._shells_claude("/Users/x/.claude/local/claude -p 'x'"), True)
check("claude inside `bash -lc` is an invocation",
      fh._shells_claude("bash -lc 'claude -p \"x\"'"), True)
check("claude after `&&` is an invocation",
      fh._shells_claude("cd ~/projects/x && claude -p 'x'"), True)

# The schedule fields must be stripped, and non-job lines must not be parsed.
check("a comment line yields no command", fh._cron_command("# 0 3 * * * claude -p 'x'"), "")
check("a crontab env assignment yields no command", fh._cron_command("MAILTO=me@example.com"), "")
check("a @daily line strips the special field",
      fh._cron_command("@daily claude -p 'x'"), "claude -p 'x'")

# --- PR #11 review, finding 1: housekeeping over a directory named `claude` ---
# The shipped v1 scored ANY token whose basename is `claude` followed by a flag,
# with no command-position guard. 4 of these 5 real, benign lines matched, and
# this fleet HAS a `~/projects/claude`. Each one would have filed a permanent
# Linear issue asserting a scheduler bug that does not exist.
BENIGN_OVER_A_CLAUDE_DIR = [
    "tar -czf /backup/claude.tgz ~/projects/claude --exclude=node_modules",
    "rsync -a ~/projects/claude/ /Volumes/backup/claude/ --checksum",
    "du -sh ~/projects/claude --block-size=M >> ~/disk.log",
    "/usr/bin/git -C ~/projects/claude pull --ff-only",
    "chmod -R 700 ~/projects/claude -v",
]
for benign in BENIGN_OVER_A_CLAUDE_DIR:
    check(f"housekeeping is not an invocation: {benign[:44]}",
          fh._shells_claude(benign), False)
check(
    "a crontab of ONLY housekeeping lines files nothing",
    fh.detect_cron_shells_claude(
        None, cron_text="".join(f"0 3 * * * {c}\n" for c in BENIGN_OVER_A_CLAUDE_DIR)),
    [],
)

# --- PR #11 review, finding 4: `claude -p` as PROSE inside a quoted argument ---
# `.strip("'\"")` was per-token, so quoting gave no protection. A reminder to
# migrate OFF cron filed an issue saying you are ON cron.
check("`claude -p` inside a quoted message is not an invocation",
      fh._shells_claude('/usr/local/bin/notify-send "reminder: run claude -p sweep tomorrow"'),
      False)
check("`claude -p` inside a quoted echo is not an invocation",
      fh._shells_claude("echo 'migrate claude -p jobs to launchd' >> ~/todo.txt"), False)
check("an operator inside a quoted string does not open a new segment",
      fh._shells_claude('echo "step one; claude -p x"'), False)

# --- PR #11 review, finding 7: real invocation shapes v1 missed ----------------
check("`npx claude` is an invocation", fh._shells_claude("cd ~/projects/x && npx claude"), True)
check("claude in command position inside `zsh -lc`, no flag, is an invocation",
      fh._shells_claude("/bin/zsh -lc 'claude </dev/null'"), True)

# --- PR #11 review, finding 3: a credential must never reach the issue body ---
# `_command_token` deliberately steps PAST `VAR=value`, which makes
# `ANTHROPIC_API_KEY=... claude -p` a first-class detection target -- so the
# most likely offending line is the one carrying a live key. Linear issues
# cannot be deleted here: publishing the key is worse than missing the line.
SECRET = "sk-ant-api03-REDACTEDSECRET99"
secret_line = f'0 3 * * * ANTHROPIC_API_KEY={SECRET} claude -p "sweep"'
secret_findings = fh.detect_cron_shells_claude(None, cron_text=secret_line + "\n")
check("a keyed cron line is still detected", len(secret_findings), 1)
check(
    "the credential is NOT copied into the permanent issue body",
    SECRET in (secret_findings[0]["body"] if secret_findings else ""),
    False,
)
check(
    "the env var NAME survives redaction, so the line is still identifiable",
    "ANTHROPIC_API_KEY" in (secret_findings[0]["body"] if secret_findings else ""),
    True,
)
check("a bare sk- token anywhere on the line is redacted",
      SECRET in fh._redact_secrets(f"0 3 * * * claude -p 'use {SECRET}'"), False)

# --- PR #11 review, finding 5: "I could not look" must not print as "0" -------
# `crontab -l` exits non-zero BOTH when the user has no crontab (benign) and
# when the check could not run at all. v1 discarded returncode and stderr, so a
# detector whose whole value is a negative result reported all-clear either way.
check("no crontab for the user is a genuine empty",
      fh._read_crontab_result(1, "", "crontab: no crontab for assafkip"), "")
check("a readable crontab returns its text",
      fh._read_crontab_result(0, "0 3 * * * true\n", ""), "0 3 * * * true\n")
for rc, err in ((1, "crontab: permission denied"), (127, ""), (2, "crontab: command not found")):
    try:
        fh._read_crontab_result(rc, "", err)
        failures.append(f"an unreadable crontab (rc={rc}) must raise, got a value")
    except fh.CrontabUnavailable:
        print(f"  ok: an unreadable crontab (rc={rc}) raises rather than reporting all-clear")

# A detector that COULD NOT LOOK is reported as an error, never as a count of 0.
_boom = {"id": "boom", "description": "d", "detect": _raise_unavailable,
         "action": "file_issue", "lesson": "some-lesson"}
_, per_detector = fh.run_detectors([_boom])
check("a detector that could not look reports `error`, not 0",
      per_detector.get("boom"), "error")

# --- PR #11 review, finding 2: the rollup body must actually be updatable -----
# The rollup design's whole justification is "the offending lines live in the
# body, which is updatable". Without an update path the detector goes blind
# after its first hit: offender #2 is never surfaced to anyone, and the count in
# the body freezes at day-1 truth and drifts into a lie.
LINE_1 = "0 3 * * * cd ~/p && timeout 1800 claude -p 'sweep' </dev/null"
LINE_2 = "30 4 * * * claude -p 'second job added a month later'"


def _rollup(cron_text):
    """The findings `main` would file, keyed exactly as `main` keys them."""
    out = fh.detect_cron_shells_claude(None, cron_text=cron_text)
    for f in out:
        f["key"] = fh.finding_key("cron-shells-claude", f["subject"])
        f["detector"] = "cron-shells-claude"
    return out


fake = FakeLinear()
day1 = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=fake)
check("day 1 files exactly one rollup issue", day1["created"], 1)

day30 = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=fake)
check("day 30 does NOT fork a second issue", day30["created"], 0)
check("day 30 updates the one issue it already owns", day30["updated"], 1)
check("still exactly one issue exists", len(fake.issues), 1)

body_now = fake.issues["id-1"]["description"]
check("the SECOND offending line is now visible on the issue",
      "second job added a month later" in body_now, True)
check("the first offending line is still there", "sweep" in body_now, True)
check("the count in the title is no longer frozen at day-1 truth",
      fake.issues["id-1"]["title"].startswith("2 crontab line(s)"), True)

# An unchanged crontab must not issue a no-op mutation every single morning.
day31 = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=fake)
check("an unchanged finding writes nothing", (day31["created"], day31["updated"]), (0, 0))

# --apply is the only thing that may mutate. A dry run counts, never writes.
dry_fake = FakeLinear()
dry = fh.file_findings(_rollup(LINE_1 + "\n"), apply=False, linear=dry_fake)
check("a dry run reports what it would create", dry["created"], 1)
check("a dry run creates nothing", len(dry_fake.issues), 0)

# --- second review, MINOR 4: one finding lands in exactly ONE bucket ----------
# `existing += 1` then `updated += 1` in the same iteration rendered a single
# finding as "1 updated, 1 already tracked", which reads as two items.
check("an updated finding is not ALSO counted as already-tracked", day30.get("existing"), 0)
check("an unchanged finding IS counted as already-tracked", day31.get("existing"), 1)

# --- second review, BLOCKER 1: a rewrite must REOPEN a closed rollup issue -----
# The prescribed remedy is "move the job to a LaunchAgent", after which the
# operator closes the rollup issue. That is the CORRECT end state. Without a
# stateId on the update, every later detection rewrites a Done issue nobody
# looks at while Slack says "board has them; nothing to do now" -- a false
# all-clear that is worse than the pre-PR behaviour, which never claimed to
# have surfaced anything.
reopen_fake = FakeLinear()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=reopen_fake)
reopen_fake.close_issue("id-1")
check("precondition: the operator's close really closed it",
      reopen_fake.issues["id-1"]["state_type"], "completed")

months_later = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"),
                                apply=True, linear=reopen_fake)
check("a closed rollup issue is reopened, not silently rewritten",
      reopen_fake.issues["id-1"]["state_type"] != "completed", True)
check("the reopen is counted so the operator can be told", months_later.get("reopened"), 1)
check("reopening does not fork a second permanent issue", len(reopen_fake.issues), 1)
check("the new offending line is on the reopened issue",
      "second job added a month later" in reopen_fake.issues["id-1"]["description"], True)

# An UNCHANGED body on a CLOSED issue must still reopen. The body-diff and the
# state check are independent: a finding that is still true while the board says
# it is done is exactly the blind spot, whether or not the text moved.
still_closed = FakeLinear()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=still_closed)
still_closed.close_issue("id-1")
same_body = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=still_closed)
check("a closed issue with an UNCHANGED body is still reopened", same_body.get("reopened"), 1)
check("...and its state really moved off completed",
      still_closed.issues["id-1"]["state_type"] != "completed", True)

# An OPEN issue must never have its state touched: filing must not drag an issue
# the operator moved to In Progress back to Todo every morning.
open_fake = FakeLinear()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=open_fake)
open_fake.mutations.clear()
fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=open_fake)
check("an OPEN issue is updated without a stateId",
      [k for q, keys in open_fake.mutations if q == "ISSUE_UPDATE" for k in keys],
      ["description", "title"])

# --- second review, MINOR 5: a dry run must not issue OR announce a mutation ---
dry_update = FakeLinear()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=dry_update)
dry_update.mutations.clear()
would = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=False, linear=dry_update)
check("a dry run reports what it WOULD update", would.get("updated"), 1)
check("a dry run issues no mutation", dry_update.mutations, [])
check("a dry run does not Slack a mutation it never issued",
      fh.should_notify(would, {"cron-shells-claude": 1}, apply=False), False)
check("the same outcome under --apply does Slack",
      fh.should_notify(would, {"cron-shells-claude": 1}, apply=True), True)

# --- second review, MAJOR 3: a blind detector must reach the founder ----------
# An errored detector produced one stderr line, "error" in a state file, exit 0,
# and NO Slack ping (the gate needed created-or-updated, both 0). The distinction
# CrontabUnavailable exists to preserve died at the notification boundary.
CLEAN = {"created": 0, "existing": 1, "updated": 0, "reopened": 0,
         "unfiled": 0, "unresolved": 0, "errors": 0}
check("a blind detector pings even with nothing filed",
      fh.should_notify(CLEAN, {"cron-shells-claude": fh.DETECTOR_ERROR}, apply=True), True)
check("an all-clear run with nothing new does not ping",
      fh.should_notify(CLEAN, {"cron-shells-claude": 0}, apply=True), False)
blind_text = fh.notify_text(CLEAN, {"cron-shells-claude": fh.DETECTOR_ERROR})
check("the blind detector is NAMED in the Slack line",
      "cron-shells-claude" in blind_text, True)
check("a blind run never says nothing-to-do",
      "nothing to do now" in blind_text, False)
check("a clean run still says nothing-to-do",
      "nothing to do now" in fh.notify_text(
          {**CLEAN, "created": 1}, {"cron-shells-claude": 1}), True)
check("a reopen is announced, not folded into 'already tracked'",
      "reopened" in fh.notify_text(
          {**CLEAN, "reopened": 1}, {"cron-shells-claude": 1}), True)

# --- second review, MAJOR 2: ONE crontab reader, one blind-spot semantics ------
# `detect_duplicate_schedules` and `detect_cron_shells_claude` read the same
# command and had opposite semantics: `schedule-duplicate: 0` and
# `cron-shells-claude: error` in the same report from the same refused command.
# One of those two lines is a lie and the operator cannot tell which.
class _RefusedCrontab:
    """Stands in for `subprocess` so `crontab -l` is refused, nothing else runs."""

    CalledProcessError = subprocess_real.CalledProcessError
    TimeoutExpired = subprocess_real.TimeoutExpired

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "crontab: you are not allowed to use this program"

    @staticmethod
    def run(cmd, *a, **kw):
        if cmd[:2] == ["crontab", "-l"]:
            return _RefusedCrontab._Result()
        return subprocess_real.run(cmd, *a, **kw)


fh.subprocess = _RefusedCrontab
try:
    for det_id, fn in (("cron-shells-claude", fh.detect_cron_shells_claude),
                       ("schedule-duplicate", fh.detect_duplicate_schedules)):
        try:
            fn(None)
            failures.append(
                f"{det_id}: a refused `crontab -l` returned a value instead of raising")
        except fh.CrontabUnavailable:
            print(f"  ok: {det_id} raises rather than reporting all-clear on a refused crontab")
    _, refused = fh.run_detectors([
        {"id": "schedule-duplicate", "description": "d",
         "detect": fh.detect_duplicate_schedules, "action": "file_issue", "lesson": "l"},
        {"id": "cron-shells-claude", "description": "d",
         "detect": fh.detect_cron_shells_claude, "action": "file_issue", "lesson": "l"},
    ])
    check("both crontab readers report the SAME thing for the same refusal",
          refused, {"schedule-duplicate": "error", "cron-shells-claude": "error"})
finally:
    fh.subprocess = subprocess_real

# --- second review, MINOR 6: the lexer must not diverge from sh silently -------
# `shlex` treats `#` as a comment start ANYWHERE; sh only at the start of a word.
# And an unbalanced quote returned None, which read as "not an invocation" --
# the same silent-clean shape CrontabUnavailable was built to eliminate, one
# layer down.
check("a mid-word `#` does not truncate the line before `claude`",
      fh._shells_claude("curl https://ex.com/a#frag && claude -p 'sweep'"), True)
check("a word-initial `#` still comments out the rest of the line",
      fh._shells_claude("true && # claude -p 'x'"), False)
check("an unbalanced quote does not read as an all-clear",
      fh._shells_claude("claude -p 'sweep the repo"), True)
check("an unbalanced quote on a benign line is still benign",
      fh._shells_claude("du -sh ~/projects/claude --block-size='M"), False)
check("a mid-word `#` line is caught end to end",
      len(fh.detect_cron_shells_claude(
          None, cron_text="0 3 * * * curl https://ex.com/a#frag && claude -p 'sweep'\n")), 1)

# --- third review, MAJOR 1: staleness must settle through Linear's re-serializer
# `tracked.description != description` compared raw bytes, and Linear rewrites
# `- ` bullets as `* ` on the read path. Every bulleted rollup body was therefore
# stale on every run, forever: a daily Linear mutation and a daily false Slack
# "1 updated" ping for an UNCHANGED crontab — which trains the operator to ignore
# the one channel the blind-spot design depends on.
settle = FakeLinear()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=settle)
mutations_after_create = len(settle.mutations)
for morning in range(2, 7):
    day = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=settle)
    check(f"morning {morning}: an unchanged crontab settles through the re-serializer",
          (day["updated"], day["reopened"], day["existing"]), (0, 0, 1))
check("no mutation was issued on any settled morning",
      len(settle.mutations), mutations_after_create)

# The same raw compare silently REVERTED any operator edit to a tracked open
# issue's body every morning. The hash marker pins only what the renderer owns,
# so an operator's note on the issue survives the 08:15 run.
settle.issues["id-1"]["description"] += "\n\noperator note: waiting on the mini"
after_edit = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=settle)
check("an operator's edit to the body is not reverted by the morning run",
      "operator note" in settle.issues["id-1"]["description"], True)
check("...because an unchanged finding issues no rewrite over it", after_edit["updated"], 0)

# A live pre-hash issue (ASK-148 shape: kipi-key marker, no hash marker) migrates
# with exactly ONE rewrite, then settles. Without the missing-marker-is-stale
# rule it would never gain a hash and never settle.
legacy = FakeLinear()
_legacy_finding = _rollup(LINE_1 + "\n")[0]
legacy.issues["id-legacy"] = {
    "identifier": "ASK-148",
    "title": _legacy_finding["title"],
    "description": (f"<!-- kipi-key: {_legacy_finding['key']} -->\n\n"
                    f"{_legacy_finding['body']}\n\nFiled by `fleet-health-daily.py`."),
    "state_type": "unstarted",
}
mig1 = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=legacy)
check("a pre-hash live issue is migrated with one rewrite", mig1["updated"], 1)
mig2 = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=legacy)
check("...and settles the morning after", (mig2["updated"], mig2["reopened"]), (0, 0))

# --- third review, MINOR 2: a shell RUNNING A SCRIPT keeps its flags -----------
# `bash backup.sh -c <arg>` hands `-c <arg>` to the script, not to bash. Reading
# any later `-c` as the shell's own flag scored a line that never runs claude.
check("a script's own -c flag is not read as the shell's -c",
      fh._shells_claude("bash q-repro-innocent.sh -c ~/projects/claude"), False)
check("a long option before -c is still an option, not an operand",
      fh._shells_claude("bash --norc -c 'claude -p x'"), True)

# --- third review, MINOR 3: silent false negatives on real invocation shapes ---
check("`timeout 30m claude` is an invocation (GNU duration suffix)",
      fh._shells_claude("timeout 30m claude -p 'sweep'"), True)
check("a quoted #-leading ARGUMENT does not comment out the invocation",
      fh._shells_claude("grep -q '#TODO' notes.txt && claude -p 'sweep'"), True)

# --- third review, MINOR 5: the lexer fallback must not INVENT a match ---------
# An unbalanced quote fell back to a whitespace split, which re-exposed a `&&`
# that posix parsing had absorbed into the string — creating a command position
# sh never creates. The fallback now scores the line as ONE segment, so it can
# only ever be coarser than sh, never finer.
check("an unbalanced quote cannot re-expose a quoted operator as a segment",
      fh._shells_claude("echo 'reminder: && claude -p x"), False)

# --- third review, MINOR 4: redaction must survive quotes and non-sk shapes ----
# Composed from a variable (like SECRET above) so the source never contains a
# literal KEY="value" assignment for gitleaks to flag at commit time.
_TWO_HALVES = "sk-ant-api03-SECRETHALF1 SECRETHALF2"
_QUOTED_KEY_LINE = f'0 3 * * * ANTHROPIC_API_KEY="{_TWO_HALVES}" claude -p x'
_red = fh._redact_secrets(_QUOTED_KEY_LINE)
check("a quoted env value is masked past its first space", "SECRETHALF2" in _red, False)
check("...and the variable NAME still survives", "ANTHROPIC_API_KEY" in _red, True)
check("...and the command itself survives", "claude -p x" in _red, True)
check("a Slack webhook path is masked",
      "T000/B000" in fh._redact_secrets(
          "0 3 * * * curl -d x https://hooks.slack.com/services/T000/B000/XXX && claude -p y"),
      False)
# Composed so the source holds no literal curl auth header for gitleaks.
_BEARER = "tok4bcdef123456"
check("a bearer token is masked",
      _BEARER in fh._redact_secrets(
          f'0 3 * * * curl -H "Authorization: Bearer {_BEARER}" https://x && claude -p y'),
      False)

# --- third review, MINOR 6: never announce a reopen that was not sent ----------
# `reopened` incremented before the state id was known; with no reopenable state
# the update carried no stateId, the issue stayed completed, and Slack said it
# was back on the board.
class _NoReopenState(FakeLinear):
    def reopen_state_id(self, _team_id):
        return ""


no_state = _NoReopenState()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=no_state)
no_state.close_issue("id-1")
stuck = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=no_state)
check("with no reopenable state, a reopen is NOT announced", stuck["reopened"], 0)
check("...the body rewrite is counted as what it was: an update", stuck["updated"], 1)
check("...and no stateId was sent",
      any("stateId" in keys for q, keys in no_state.mutations if q == "ISSUE_UPDATE"), False)
check("...so the issue honestly remains closed",
      no_state.issues["id-1"]["state_type"], "completed")

# --- fourth review, MAJOR 1: Linear unreachable must not read as a clean run ---
# `file_findings` caught everything from fetch_remote_state, counted the dropped
# findings, and returned -- but the notify gate never consulted that bucket. A
# real finding was discarded with one stderr line into a file nobody reads, exit
# 0, and the LAST WORD to the operator was "Board has them; nothing to do now".
# The rule the crontab reader follows (a run that could not look is not clean)
# was applied to the DETECT half and not to the FILE half.
class _LinearDown(FakeLinear):
    def fetch_remote_state(self, _team_key, _repo):
        raise RuntimeError("network: [Errno 8] nodename nor servname provided")


down = _LinearDown()
dropped = fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=down)
check("a finding Linear could not accept is counted as unfiled", dropped["unfiled"], 1)
check("...and nothing was created", (dropped["created"], len(down.issues)), (0, 0))
check("a run that dropped a finding PINGS the operator",
      fh.should_notify(dropped, {"cron-shells-claude": 1}, apply=True), True)
down_text = fh.notify_text(dropped, {"cron-shells-claude": 1})
check("...and never claims the board has it",
      "nothing to do now" in down_text, False)
check("...and says how many findings were dropped", "1" in down_text, True)
check("...and names the reason so 3am has somewhere to start",
      "Linear" in down_text or "unreachable" in down_text, True)
check("a dry run that could not reach Linear still does not ping",
      fh.should_notify(dropped, {"cron-shells-claude": 1}, apply=False), False)

# --- fourth review, MAJOR 2: a rollup outside the health project must not go dark
# `known = ledger | remote_keys`, but only remote_keys carries a body. Moving the
# issue to another project -- ordinary triage -- made `tracked` None forever, so
# every later run took `existing += 1; continue`: zero writes, zero pings, and
# the one sentence the operator saw was "nothing to do now" while the crontab
# grew from 1 offending line to 5. The ledger already holds the linear_id; the
# fix is to go get the issue rather than give up because it moved.
class _MovedOutOfProject(FakeLinear):
    """The issue exists and is reachable by id; it is just not in this project."""

    def __init__(self):
        super().__init__()
        self.hide_from_project = set()

    def fetch_remote_state(self, team_key, repo):
        team_id, project, keys = super().fetch_remote_state(team_key, repo)
        for key in self.hide_from_project:
            keys.pop(key, None)
        return team_id, project, keys


moved = _MovedOutOfProject()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=moved)
moved.hide_from_project.add("fleet-health/cron-shells-claude/cron-shells-claude")
grown = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=moved)
check("a rollup moved out of the health project is still updated", grown["updated"], 1)
check("...it is not silently counted as already-tracked", grown["existing"], 0)
check("...the mutation really went out",
      [q for q, _ in moved.mutations if q == "ISSUE_UPDATE"], ["ISSUE_UPDATE"])
check("...and the new offending line is visible on it",
      "second" in moved.issues["id-1"]["description"], True)
check("...without forking a second permanent issue", len(moved.issues), 1)


class _IssueGone(_MovedOutOfProject):
    """In the ledger, not in the project, and not reachable by id (deleted)."""

    def fetch_issue(self, _linear_id):
        return {}


gone = _IssueGone()
fh.file_findings(_rollup(LINE_1 + "\n"), apply=True, linear=gone)
gone.hide_from_project.add("fleet-health/cron-shells-claude/cron-shells-claude")
lost = fh.file_findings(_rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=gone)
check("a known key whose issue cannot be located is counted as unresolved",
      lost["unresolved"], 1)
check("...it is NOT reported as already-tracked", lost["existing"], 0)
check("...the operator is pinged rather than told nothing-to-do",
      fh.should_notify(lost, {"cron-shells-claude": 1}, apply=True), True)
check("...and the Slack line drops the all-clear language",
      "nothing to do now" in fh.notify_text(lost, {"cron-shells-claude": 1}), False)

# --- fourth review, MINOR 3: a Linear error mid-loop must not kill the run -----
# Exactly one network call was guarded. reopen_state_id, ISSUE_UPDATE and
# ISSUE_CREATE were not, so a 429 on finding 1 propagated out of file_findings
# and out of main(): finding 2 was never attempted, the state file kept
# yesterday's ran_at, and no Slack line was ever sent.
class _RateLimited(FakeLinear):
    def __init__(self, fail_on=1):
        super().__init__()
        self.fail_on = fail_on
        self.attempts = 0

    def graphql(self, query, variables):
        if query == self.ISSUE_CREATE:
            self.attempts += 1
            if self.attempts == self.fail_on:
                raise RuntimeError('HTTP 429: {"errors":[{"message":"rate limited"}]}')
        return super().graphql(query, variables)


two_findings = [
    {"key": "fleet-health/x/first", "subject": "first", "title": "first finding",
     "body": "b1", "detector": "x"},
    {"key": "fleet-health/x/second", "subject": "second", "title": "second finding",
     "body": "b2", "detector": "x"},
]
limited = _RateLimited(fail_on=1)
survived = fh.file_findings(list(two_findings), apply=True, linear=limited)
check("a Linear error on one finding does not propagate out of file_findings",
      survived["errors"], 1)
check("...the NEXT finding is still attempted and filed", survived["created"], 1)
check("...and the one that landed is the second one",
      [n["title"] for n in limited.issues.values()], ["second finding"])
check("a run with a filing error pings the operator",
      fh.should_notify(survived, {"x": 2}, apply=True), True)
check("...and the Slack line says filing failed",
      "failed" in fh.notify_text(survived, {"x": 2}), True)

# --- fourth review, MINOR 4: a wrapper's option ARGUMENT is not command position
# `_command_index` skipped `-u` as a flag and then handed `claude` -- the VALUE
# of that flag -- straight to `_is_claude_token`. A machine with a service
# account named `claude` files a permanent false issue. Same asymmetry the third
# review fixed for shells at `_shell_c_argument` (stop at the first operand) and
# did not fix for wrappers.
for benign_wrapper in [
    "sudo -u claude /opt/svc/run.sh",
    "sudo -u claude -H /opt/svc/run.sh",
    "sudo --user claude /opt/svc/run.sh",
    "env -u claude /opt/svc/run.sh",
    "npx -p claude ./build.sh",
    "nice -n 10 /opt/svc/run.sh",
]:
    check(f"a wrapper option's value is not command position: {benign_wrapper[:40]}",
          fh._shells_claude(benign_wrapper), False)
check("...but the wrapper still passes a REAL invocation through",
      fh._shells_claude("sudo -u root claude -p 'x'"), True)
check("...including with no option at all", fh._shells_claude("sudo claude -p 'x'"), True)
check("...and `timeout -k 30 1800 claude` still matches",
      fh._shells_claude("timeout -k 30 1800 claude -p 'x'"), True)

# --- fourth review, MINOR 5: real invocations behind an unlisted wrapper --------
# 4 of 15 real shapes were missed silently. `flock -n <lock> claude -p` is the
# standard way a cron job stops overlapping itself, and this fleet has a "mini"
# box it reaches over ssh. A miss here is the detector's whole job, undone.
check("`flock -n <lock> claude -p` is an invocation",
      fh._shells_claude("flock -n /tmp/x.lock claude -p 'x'"), True)
check("`flock -w 5 <lock> claude` is an invocation",
      fh._shells_claude("flock -w 5 /tmp/x.lock claude -p 'x'"), True)
check("`ssh <host> claude -p` is an invocation",
      fh._shells_claude("ssh mini claude -p 'x'"), True)
check("3-deep shell nesting is an invocation",
      fh._shells_claude("""sh -c 'sh -c "sh -c \\"claude -p x\\""'"""), True)
check("a lock FILE named claude is not an invocation",
      fh._shells_claude("flock -n /tmp/claude.lock /opt/svc/run.sh"), False)
check("an ssh USER named claude is not an invocation",
      fh._shells_claude("ssh claude@mini ./run.sh"), False)
check("an ssh HOST named claude is not an invocation",
      fh._shells_claude("ssh claude /opt/svc/run.sh"), False)

# every shipped detector must be callable and return a list
for det in fh.DETECTORS:
    try:
        result = det["detect"](None)
    except fh.CrontabUnavailable as exc:
        # On a crontab-locked machine the RAISE is the designed behaviour (second
        # review, MAJOR 2); `run_detectors` records it as "error". The suite must
        # not go red on machine state alone (third review, finding 7).
        print(f"  ok: {det['id']} raised CrontabUnavailable on this machine (designed): {exc}")
        continue
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

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
