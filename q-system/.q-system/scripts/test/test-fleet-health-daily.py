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
    """

    ISSUE_CREATE = "ISSUE_CREATE"
    ISSUE_UPDATE = "ISSUE_UPDATE"

    def __init__(self):
        self.issues = {}       # linear_id -> {identifier, title, description}
        self.ledger = {}       # kipi-key -> record
        self._n = 0

    # --- the linear-sync surface fleet-health calls ------------------------
    def fetch_remote_state(self, _team_key, _repo):
        keys = {}
        for lid, node in self.issues.items():
            found = re.search(r"<!--\s*kipi-key:\s*(\S+)\s*-->", node["description"])
            if found:
                keys[found.group(1)] = {
                    "linear_id": lid,
                    "identifier": node["identifier"],
                    "description": node["description"],
                }
        return "team-1", {"id": "proj-1"}, keys

    def read_ledger(self):
        return dict(self.ledger)

    def append_ledger(self, records):
        for rec in records:
            self.ledger[rec["key"]] = rec
        return len(records)

    def graphql(self, query, variables):
        if query == self.ISSUE_CREATE:
            self._n += 1
            lid = f"id-{self._n}"
            self.issues[lid] = {
                "identifier": f"ISSUE-{self._n}",
                "title": variables["input"]["title"],
                "description": variables["input"]["description"],
            }
            return {"issueCreate": {"success": True,
                                    "issue": {"id": lid, "identifier": f"ISSUE-{self._n}"}}}
        if query == self.ISSUE_UPDATE:
            node = self.issues[variables["id"]]
            node.update({k: v for k, v in variables["input"].items()
                         if k in ("title", "description")})
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

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: fleet-health-daily contract holds")
sys.exit(0)
