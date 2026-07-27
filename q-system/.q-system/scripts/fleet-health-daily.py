#!/usr/bin/env python3
"""Daily fleet health check. Every detector must DETECT, ACT, and feed LEARNING.

THE RULE THIS FILE EXISTS TO ENFORCE (founder, 2026-07-26):

    "detection without a path to action is useless. Any detection artifact should
     be tied to a logged and automated action. I dont need to do them, I just need
     to know they were tracked and done. The more critical thing is that prevention
     is better than detection. When we detect, we should not only alert or fix or
     both, the system should learn."

The scar behind it: on 2026-07-26 the launchd watchdog detected all 26 paused
com.cole.* jobs correctly and Slacked every one. Detection worked perfectly and it
STILL felt like nothing was tracked -- because a Slack ping is not a work item. It
is read once and scrolls away. A detector whose only output is an alert has moved
the work back onto the founder, which is the exact inversion of the point.

So a detector here is not shippable without all three legs:

  DETECT  the check itself
  ACT     `file_issue`, `auto_fix`, or `both`. NEVER None. A Linear issue carries
          a stable kipi-key so the same finding is ONE issue forever, not a new
          one each morning.
  LEARN   `lesson` names the q-system/lessons/ entry this class of defect maps to,
          or `lesson_waived` states in words why this class cannot recur. One of
          the two is required.

`validate_detectors()` refuses to run if any detector breaks that contract, and
test-fleet-health-daily.py asserts it. Prose cannot hold this line; the registry can.

ALERTING: ONE Slack summary line, never one ping per finding. The findings live in
Linear where they hold state. Slack is a pointer, not a ledger.

Exit 0 always (a health check that fails its own launchd job is noise); the report
goes to stdout and the ledger.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
REPO_ROOT = QROOT.parent
NOTIFY = HERE / "slack-notify.sh"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
STATE = Path.home() / ".config" / "kipi" / "fleet-health-state.json"

# Where fleet-wide findings are filed. Per-repo findings could route to their own
# project later; today one project keeps the board readable.
HEALTH_PROJECT = "kipi-system"
TEAM_KEY = "ASK"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


# ---------------------------------------------------------------------------
# Detectors
#
# Each returns a list of findings: {"subject": <stable id>, "title", "body"}.
# `subject` MUST be stable across runs -- it is the dedup key, and an unstable
# one files a new permanent Linear issue every single morning.
# ---------------------------------------------------------------------------


def _launchd_labels() -> list:
    return sorted(p.stem for p in LAUNCH_AGENTS.glob("*.plist"))


def _paused_labels() -> set:
    """Reuse the watchdog's own ledger reader so 'paused' has ONE definition."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("wd", HERE / "launchd-health-check.py")
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)
    return wd.load_paused_labels()


def _is_loaded(label: str) -> bool:
    try:
        return subprocess.run(
            ["launchctl", "list", label], capture_output=True, timeout=10
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot tell -> do not cry wolf


def detect_dark_jobs(_ctx) -> list:
    """A plist on disk, not loaded, and NOT in the paused ledger = silent death."""
    paused = _paused_labels()
    out = []
    for label in _launchd_labels():
        if not label.startswith(("com.kipi.", "com.cole.", "com.ask.", "com.assaf.",
                                 "com.claudedaddy.", "com.purespectrum.", "com.personal.")):
            continue
        if label in paused or _is_loaded(label):
            continue
        out.append({
            "subject": label,
            "title": f"launchd job is dark: {label}",
            "body": (
                f"`{label}` has a plist in `~/Library/LaunchAgents/` but is not loaded, "
                "and it is NOT in the paused ledger — so nothing recorded a decision to "
                "stop it.\n\n"
                "## Action\n"
                f"- Resume: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{label}.plist`\n"
                f"- Or record the pause: add `{label}` to `~/.config/kipi/launchd-paused.txt`\n\n"
                "Leaving it dark with no ledger entry is the state this detector exists to "
                "make impossible."
            ),
        })
    return out


def detect_failing_jobs(_ctx) -> list:
    """Loaded but last run exited non-zero."""
    out = []
    try:
        listing = subprocess.run(["launchctl", "list"], capture_output=True,
                                 text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return out
    for line in listing.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        _pid, status, label = parts[0], parts[1], parts[2].strip()
        if not label.startswith(("com.kipi.", "com.cole.", "com.ask.", "com.assaf.")):
            continue
        try:
            code = int(status)
        except ValueError:
            continue
        if code != 0:
            out.append({
                "subject": label,
                "title": f"launchd job failing: {label} (exit {code})",
                "body": (
                    f"`{label}` is loaded but its last run exited **{code}**.\n\n"
                    "## Action\nRead its StandardErrorPath, fix the cause, and confirm a "
                    "clean run. If the failure is environmental (auth expiry, server down), "
                    "say so on this issue rather than retrying — `self-healing-retry.md` "
                    "rule 5 stops environmental failures on attempt 1."
                ),
            })
    return out


def detect_duplicate_schedules(_ctx, cron_text=None) -> list:
    """The same script scheduled by BOTH launchd and crontab.

    Found live 2026-07-26: reddit-build-radar runs at 08:00 from
    com.cole.reddit-radar-daily AND from a crontab line. Two schedulers on one
    script means pausing one does nothing, which is how a 'paused' job keeps running.

    Reads the crontab through the SAME `_crontab_text()` as
    `detect_cron_shells_claude`, so one refused `crontab -l` cannot produce
    `schedule-duplicate: 0` and `cron-shells-claude: error` in the same report.
    PR #11's second review found exactly that: two readers of one command with
    opposite blind-spot semantics, one of the two lines a lie, and no way for the
    operator to tell which. Swallowing here was the older half of the pattern.
    """
    cron = _crontab_text() if cron_text is None else cron_text
    # Resolve to ABSOLUTE paths, never basenames. Measured 2026-07-26: matching on
    # the basename `run_daily.sh` hit 3 plists (reddit-radar-daily, daily-podcast,
    # story-podcast) when only ONE is a real duplicate -- the other two are
    # unrelated scripts that happen to share a very common filename. Filing those
    # would have created two PERMANENT false issues, and Linear issues cannot be
    # deleted here. A detector's false positives are as expensive as its misses.
    cron_scripts = set()
    for line in cron.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # cron lines commonly read `cd <dir> && ... scripts/foo.sh`, so a relative
        # script path resolves against that cd, not against $HOME.
        cd_match = re.search(r"\bcd\s+(\S+)", stripped)
        base_dir = Path(cd_match.group(1)) if cd_match else Path.home()
        for token in stripped.split():
            if not token.endswith((".sh", ".py")):
                continue
            path = Path(token)
            resolved = path if path.is_absolute() else (base_dir / path)
            cron_scripts.add(str(resolved))

    out = []
    for label in _launchd_labels():
        plist = LAUNCH_AGENTS / f"{label}.plist"
        try:
            text = plist.read_text(errors="ignore")
        except OSError:
            continue
        for name in cron_scripts:
            if name in text:
                out.append({
                    "subject": f"{label}--{slug(name)}",
                    "title": f"double-scheduled: {name} runs from both launchd and cron",
                    "body": (
                        f"`{name}` is scheduled by launchd (`{label}`) **and** by a crontab "
                        "entry.\n\n"
                        "Two schedulers on one script means pausing or unloading one has no "
                        "effect — the other keeps firing. That is how a job the operator "
                        "believes is stopped keeps running, and how a run gets duplicated.\n\n"
                        "## Action\nPick ONE scheduler. launchd is the fleet convention "
                        "(`launchd-health-check.py` watches it; crontab is invisible to that "
                        "watchdog). Remove the crontab line, or unload the plist."
                    ),
                })
    return out


# Wrappers that sit BEFORE the real command on a cron line. `timeout 1800 claude`
# is the shape this fleet actually uses (open-loops-heartbeat.sh), so a matcher
# that only reads the first token would miss every real invocation.
CRON_COMMAND_WRAPPERS = {"env", "nohup", "nice", "time", "timeout", "caffeinate",
                         "sudo", "exec", "stdbuf", "npx"}

# A shell in command position does not RUN what follows; it runs the string
# handed to its `-c` flag. `bash -lc 'claude -p ...'` is the shape a cron line
# uses to get a login environment, so the command inside the quotes has to be
# parsed as a command, not scanned as text.
SHELL_COMMANDS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}

# Tokens that END a command and open the next one. Redirections (`<`, `>`, `>>`)
# are deliberately NOT here: they take an argument, they do not start a command.
SHELL_OPERATORS = {"&&", "||", ";", "|", "&", "|&", "(", ")"}


class CrontabUnavailable(RuntimeError):
    """`crontab -l` could not be read. NOT the same as an empty crontab.

    This distinction is the whole point of the class. A detector whose value is a
    NEGATIVE result ("no cron line shells claude") must never print the same
    thing for "I looked and found nothing" and "I could not look". The first is
    an all-clear; the second is a blind spot wearing an all-clear's clothes.
    """


# `crontab -l` exits non-zero when the user simply has no crontab. That is the
# one benign non-zero, and it is identified by its stderr, not by its code.
_NO_CRONTAB_RE = re.compile(r"no crontab for", re.IGNORECASE)


def _read_crontab_result(returncode: int, stdout: str, stderr: str) -> str:
    """Interpret a `crontab -l` result. Pure, so the blind-spot case is testable.

    Raises CrontabUnavailable when the command ran but could not report the
    crontab (permission denied, crontab not installed, an unexpected code).
    """
    if returncode == 0:
        return stdout
    err = (stderr or "").strip()
    if _NO_CRONTAB_RE.search(err):
        return ""  # the user genuinely has no crontab: a real, readable empty
    raise CrontabUnavailable(
        f"crontab -l exited {returncode}: {err[:200] or '(no stderr)'}"
    )


def _crontab_text() -> str:
    """`crontab -l`. Empty ONLY when the user genuinely has no crontab."""
    try:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CrontabUnavailable(f"crontab -l did not run: {exc}") from exc
    return _read_crontab_result(res.returncode, res.stdout, res.stderr)


def _cron_command(line: str) -> str:
    """The command part of a crontab line, with the schedule fields removed."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    fields = stripped.split()
    if "=" in fields[0]:
        return ""  # a crontab env assignment (PATH=..., MAILTO=...), not a job
    if fields[0].startswith("@"):
        return " ".join(fields[1:])  # @daily / @reboot: one schedule field, not five
    if len(fields) < 6:
        return ""
    return " ".join(fields[5:])


def _is_claude_token(token: str) -> bool:
    """The token names the `claude` binary — by basename, so a path counts too."""
    return PurePosixPath(token).name == "claude"


def _command_token(tokens: list) -> str:
    """The real command in a shell segment, past env prefixes and wrappers."""
    for token in tokens:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            continue  # VAR=value prefix
        if token.startswith("-") or token.isdigit():
            continue  # a wrapper's own flag or arg, e.g. the 1800 in `timeout 1800`
        if PurePosixPath(token).name in CRON_COMMAND_WRAPPERS:
            continue
        return token
    return ""


def _lex(command: str) -> list:
    """Shell-aware tokens. Never None: an unparsable string still gets scored.

    `punctuation_chars=True` makes `&& || ; | ( )` their own tokens while leaving
    quoted strings intact, which is what lets the operator split below happen at
    the TOKEN level. Splitting the raw string on `;`/`&&` (the shipped v1) cut
    inside quoted arguments: `echo "step one; claude -p x"` produced a second
    segment whose first token was `claude`.

    Two places `shlex` is not `sh`, both found by PR #11's second review, both
    silent false negatives — the same shape `CrontabUnavailable` exists to
    eliminate, one layer down:

    - `shlex` starts a comment at `#` ANYWHERE; `sh` only at the start of a word.
      `curl https://ex.com/a#frag && claude -p ...` lexed to two tokens and the
      invocation vanished. `commenters = ""` hands `#` back as an ordinary
      character; word-initial `#` is then honoured in `_shell_segments`, where
      word boundaries actually exist.
    - An unbalanced quote raised, and returning None read as "not an invocation".
      `claude -p 'sweep the repo` is a REAL invocation with a typo. Falling back
      to a whitespace split keeps command position scorable; it cannot invent a
      match, because the fallback only ever splits more coarsely than sh.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def _shell_segments(command: str) -> list:
    """The command's shell segments, each as a token list."""
    segments, current = [], []
    for token in _lex(command):
        if token.startswith("#"):
            break  # sh: a word-initial `#` comments to end of LINE, not of segment
        if token in SHELL_OPERATORS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [s for s in segments if s]


def _shell_c_argument(tokens: list) -> str:
    """The string a shell will EXECUTE: the token after its `-c`-bearing flag.

    Only consulted when the command itself is a shell, so `tar -czf` (whose flag
    also contains a `c`) is never read this way.
    """
    for index, token in enumerate(tokens):
        if not token.startswith("-") or token.startswith("--"):
            continue
        if "c" in token[1:] and index + 1 < len(tokens):
            return tokens[index + 1]
    return ""


def _shells_claude(command: str, _depth: int = 0) -> bool:
    """True when the command INVOKES `claude`, not merely mentions it.

    COMMAND POSITION IS THE ONLY SIGNAL. v1 also scored any token whose basename
    was `claude` immediately followed by a flag, with no command-position guard.
    That clause was there to reach `bash -lc 'claude -p ...'`, and PR #11's review
    measured what it actually cost: 4 of 5 ordinary housekeeping lines over
    `~/projects/claude` (tar, rsync, du, chmod, each with a trailing flag) scored
    as invocations. This fleet HAS that directory, and a Linear issue filed here
    is permanent and cannot be deleted, so a false positive is forever.

    The quoted-shell case it was covering is handled properly instead: when a
    shell holds command position, the string it was handed is re-parsed as a
    command. `bash -lc 'claude -p "x"'` still matches, and
    `notify-send "run claude -p tomorrow"` no longer does.
    """
    if _depth > 2:  # `sh -c 'sh -c ...'` is not a shape worth chasing further
        return False
    for tokens in _shell_segments(command):
        command_token = _command_token(tokens)
        if _is_claude_token(command_token):
            return True
        if PurePosixPath(command_token).name in SHELL_COMMANDS:
            inner = _shell_c_argument(tokens)
            if inner and _shells_claude(inner, _depth + 1):
                return True
    return False


_SECRET_TOKEN_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})")


def _redact_secrets(line: str) -> str:
    """Mask credentials before a raw crontab line is copied into a Linear issue.

    `_command_token` deliberately steps PAST `VAR=value` prefixes, which makes
    `ANTHROPIC_API_KEY=... claude -p` a FIRST-CLASS detection target — the action
    text below even anticipates the API-key shape. So the line most likely to be
    detected is the line most likely to be carrying a live key, and the object it
    gets copied into is permanent and cannot be deleted here. Detecting a secret
    and then publishing it is a worse outcome than not detecting it.

    Over-redaction is the deliberate bias: the variable NAME survives (the line
    stays identifiable), only its value is masked.
    """
    out = []
    for token in line.split():
        assignment = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.+)", token)
        if assignment:
            out.append(f"{assignment.group(1)}=<redacted>")
            continue
        out.append(_SECRET_TOKEN_RE.sub("<redacted>", token))
    return " ".join(out)


def detect_cron_shells_claude(_ctx, cron_text=None) -> list:
    """A crontab line that invokes `claude`. It cannot work: cron has no keychain.

    Probed 2026-07-23 (`reddit-build-radar/logs/cron-probe/result.txt`):
    `keychain_read_rc=44` and `{"is_error":true,...}`. cron starts from a bare
    environment with no keychain access, so subscription auth fails with an opaque
    error instead of a clean one — the failure reads as a broken prompt, not a
    broken scheduler, which is why it is worth catching at the crontab. launchd
    jobs DO have keychain access; every working `claude -p` job in this fleet is a
    LaunchAgent. Filed as ASK-150.

    ONE rollup finding, never one per line. A crontab line is an unstable string:
    editing the prompt inside it would fork a new PERMANENT Linear issue every
    time. The offending lines live in the body, which `file_findings` REWRITES on
    every run whose content changed — the same reasoning detect_open_spillover
    documents for its count. That update path is what makes the rollup honest: a
    second offending line added a month later lands on the same issue instead of
    disappearing behind an already-known dedup key.

    Raises CrontabUnavailable when the crontab could not be read at all, so a
    blind run is reported as an error rather than as a clean bill of health.
    """
    cron = _crontab_text() if cron_text is None else cron_text
    offenders = [_redact_secrets(line.strip()) for line in cron.splitlines()
                 if _shells_claude(_cron_command(line))]
    if not offenders:
        return []
    return [{
        "subject": "cron-shells-claude",
        "title": f"{len(offenders)} crontab line(s) shell `claude` — cron has no keychain access",
        "body": (
            f"**{len(offenders)} crontab line(s) invoke `claude`.** They cannot "
            "authenticate:\n\n"
            + "\n".join(f"- `{line}`" for line in offenders)
            + "\n\ncron runs from a bare environment with no keychain access, so "
              "subscription auth fails. Probed 2026-07-23 "
              "(`reddit-build-radar/logs/cron-probe/result.txt`):\n\n"
              "```\nkeychain_read_rc=44\n{\"is_error\":true,...,\"num_turns\":1,"
              "\"stop_reason\":\"stop_sequence\",...}\n```\n\n"
              "The error surfaces as a failed agent run, not as an auth failure, so "
              "the cause is easy to misread as a bad prompt.\n\n"
              "## Action\nMove the job to a LaunchAgent. launchd DOES have keychain "
              "access — every working `claude -p` job in this fleet "
              "(`open-loops-heartbeat.sh` under `com.kipi.openloops-heartbeat`) is one. "
              "Do not try to make cron work: there is no keychain workaround, and an "
              "API-key fallback would bill separately from the subscription.\n\n"
              "Constraint recorded in ASK-150."
        ),
    }]


def detect_open_spillover(_ctx) -> list:
    """Open spillover items — real findings someone decided not to fix yet."""
    runner = REPO_ROOT / "plugins/prd-os/scripts/prd_runner.py"
    if not runner.is_file():
        return []
    try:
        # `--open` is load-bearing. Without it the command lists RESOLVED items too,
        # and the ledger is append-only so an id appears once per state change --
        # scraping the unfiltered output reported 115 when the truth was 81. A
        # health check that files a wrong number into a permanent issue is worse
        # than one that files nothing.
        res = subprocess.run(["python3", str(runner), "spillover", "list", "--open"],
                             capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return []
    open_ids = sorted(set(re.findall(r"\[open\]\s+(sp-[0-9a-f]{8})", res.stdout or "")))
    if not open_ids:
        return []
    shown = open_ids[:25]
    more = len(open_ids) - len(shown)
    return [{
        # Stable subject: ONE standing issue, re-read each day, never a new issue
        # per morning. The count lives in the body, which is updatable; putting it
        # in the dedup key would fork a permanent issue every time it changed.
        "subject": "open-spillover",
        "title": "Open spillover backlog is blocking the closeout gates",
        "body": (
            f"**{len(open_ids)} open spillover item(s).** `prd_runner.py gates run` stays "
            "RED while any is open, so these block every closeout in the repo.\n\n"
            + "\n".join(f"- `{i}`" for i in shown)
            + (f"\n- ...and {more} more (`prd_runner.py spillover list --open`)" if more else "")
            + "\n\n## Action\nEach leaves the ledger exactly two ways: fixed through the "
              "normal issue flow then `spillover resolve <id> --resolution-ref <closed-issue>`, "
              "or `spillover resolve <id> --void \"<reason>\"`. There is no third way, and "
              "hand-clearing the gate is not possible."
        ),
    }]


# ---------------------------------------------------------------------------
# The registry. `action` and the learning leg are REQUIRED.
# ---------------------------------------------------------------------------

def detect_untracked_unwired(_ctx) -> list:
    """A repo with UNWIRED engines but no open audit issue tracking them.

    The founder's ask, 2026-07-26: "I am also seeing projects where it says things
    are not wired - we need to track that and have a plan for action. nothing
    should be left hanging."

    capability-map-gen.py already FINDS unwired engines. Before this, that finding
    lived in a JSON file nobody opens. The audit issues (ASK-119..146) tracked the
    ones known on 2026-07-26; this detector is what keeps it true as maps change,
    so a newly-unwired engine cannot go untracked just because the sweep already ran.
    """
    maps_dir = QROOT / "output" / "capability-maps"
    if not maps_dir.is_dir():
        return []
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
        ls = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ls)
        ledger = ls.read_ledger()
    except Exception:  # noqa: BLE001
        return []

    out = []
    for path in sorted(maps_dir.glob("*.json")):
        try:
            cmap = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        repo = cmap.get("repo") or path.stem
        unwired = [c for c in (cmap.get("capabilities") or [])
                   if c.get("track", True)
                   and str(c.get("status", "")).upper() == "UNWIRED"]
        if not unwired:
            continue
        audit_key = f"{slug(repo)}/unwired-engine-audit"
        if audit_key in ledger:
            continue  # already tracked by its audit issue
        out.append({
            "subject": f"{slug(repo)}-unwired-untracked",
            "title": f"{len(unwired)} unwired engine(s) in {repo} with no audit issue",
            "body": (
                f"`capability-map-gen.py` reports **{len(unwired)} unwired engine(s)** in "
                f"`{repo}` — no paired test and no reference on any wiring surface — and "
                f"there is no open audit issue (`{audit_key}`) tracking them.\n\n"
                "Unwired does not mean dead. It means nothing in the repo *says* the code "
                "is alive, which is the position every future reader starts from.\n\n"
                "## Action\n```bash\nkipi linear remote --repo " + repo + " --out /tmp/r.json\n"
                "kipi linear plan --map q-system/output/capability-maps/" + path.name +
                " \\\n  --remote /tmp/r.json --out /tmp/p.json --filter actionable --rollup\n"
                "kipi linear create --plan /tmp/p.json --apply\n```\n"
                "That files the repo's audit issue with the full engine list, which is what "
                "this detector is checking for."
            ),
        })
    return out


DETECTORS = [
    {
        "id": "unwired-untracked",
        "description": "a repo has unwired engines but no audit issue tracking them",
        "detect": detect_untracked_unwired,
        "action": "file_issue",
        "lesson": "a-defect-absence-gate-is-a-floor-not-a-finish-line",
    },
    {
        "id": "launchd-dark",
        "description": "plist on disk, not loaded, not in the paused ledger",
        "detect": detect_dark_jobs,
        "action": "file_issue",
        "lesson": "a-freshness-deadman-must-live-off-the-machine-it-watches",
    },
    {
        "id": "launchd-failing",
        "description": "loaded but last run exited non-zero",
        "detect": detect_failing_jobs,
        "action": "file_issue",
        "lesson": "a-freshness-deadman-must-live-off-the-machine-it-watches",
    },
    {
        "id": "schedule-duplicate",
        "description": "same script scheduled by both launchd and crontab",
        "detect": detect_duplicate_schedules,
        "action": "file_issue",
        "lesson_waived": (
            "One scheduler per script is a fleet convention, not a recurring defect "
            "class — the detector exists to catch drift when a script is migrated "
            "between schedulers, which is a one-off event per script."
        ),
    },
    {
        "id": "cron-shells-claude",
        "description": "a crontab line invokes `claude`, which cannot authenticate under cron",
        "detect": detect_cron_shells_claude,
        "action": "file_issue",
        "lesson": "a-scheduled-job-runs-in-a-bare-environment-not-your-shell",
    },
    {
        "id": "open-spillover",
        "description": "open spillover items blocking the closeout gates",
        "detect": detect_open_spillover,
        "action": "file_issue",
        "lesson_waived": (
            "Spillover is BY DESIGN a standing ledger of deferred work; its being "
            "non-empty is not a defect to prevent, only to keep visible."
        ),
    },
]


def validate_detectors(detectors=None) -> list:
    """Refuse a detector that detects without acting, or that cannot learn.

    This is the deterministic form of the founder's rule. A detector added later
    without an action path fails here rather than silently becoming another
    alert-only checker.
    """
    problems = []
    for d in detectors if detectors is not None else DETECTORS:
        did = d.get("id", "<unnamed>")
        if not d.get("id"):
            problems.append("a detector has no id")
        if d.get("action") not in ("file_issue", "auto_fix", "both"):
            problems.append(
                f"{did}: action must be file_issue|auto_fix|both, got {d.get('action')!r}. "
                "Detection with no action path is the thing this file exists to prevent."
            )
        if not callable(d.get("detect")):
            problems.append(f"{did}: detect is not callable")
        if d.get("action") in ("auto_fix", "both") and not callable(d.get("fix")):
            problems.append(f"{did}: action claims auto_fix but no fix() is wired")
        if not d.get("lesson") and not d.get("lesson_waived"):
            problems.append(
                f"{did}: needs `lesson` (a q-system/lessons/ slug) or `lesson_waived` "
                "(why this class cannot recur). Prevention outranks detection."
            )
    return problems


# ---------------------------------------------------------------------------
# Acting: file each finding as ONE permanent Linear issue
# ---------------------------------------------------------------------------


def finding_key(detector_id: str, subject: str) -> str:
    return f"fleet-health/{detector_id}/{slug(subject)}"


def issue_description(key: str, finding: dict) -> str:
    """The issue body for a finding. ONE renderer, used by create AND update.

    Two renderers would drift, and the drift would be invisible: the created body
    and the updated body only ever exist on different days.
    """
    return (f"<!-- kipi-key: {key} -->\n\n{finding['body']}\n\n"
            "Filed by `fleet-health-daily.py`.")


# Linear WorkflowState.type values that mean the issue is off the board. Held
# here rather than read off the injected linear module so the reopen decision is
# this file's, testable without a Linear surface that must agree about it.
CLOSED_STATE_TYPES = ("completed", "canceled")


def file_findings(findings: list, apply: bool, linear=None) -> dict:
    """Create a Linear issue per finding, deduped by kipi-key; UPDATE it if stale.

    Reuses linear-sync's graphql + remote guard so 'already exists' has exactly one
    definition fleet-wide. Linear objects are permanent, so the guard is refetched
    here rather than trusted from any cache.

    A known key is not the end of the story. Findings here roll up under stable
    subjects on purpose (`cron-shells-claude`, `open-spillover`), so their CONTENT
    changes while their identity does not. `continue`-on-known — the shipped v1 —
    meant the second offending crontab line, and every one after it, was never
    surfaced to anyone: the detector reported 1 finding forever and the count in
    the body drifted into a lie. So a known key whose rendered body differs from
    what Linear currently holds is rewritten in place, and an unchanged one still
    writes nothing (an unchanged crontab must not issue a mutation every morning).

    `linear` injects the linear-sync module, so the create AND update paths are
    provable against an in-memory fake. A test that reached real Linear would
    leave permanent objects behind and could not be re-run.
    """
    result = {"created": 0, "existing": 0, "updated": 0, "reopened": 0, "skipped_no_key": 0}
    if not findings:
        return result
    ls = linear
    if ls is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
        ls = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ls)

    try:
        team_id, project, remote_keys = ls.fetch_remote_state(TEAM_KEY, HEALTH_PROJECT)
    except Exception as exc:  # noqa: BLE001 - a health check must not crash its job
        print(f"  linear unreachable, findings NOT filed: {exc}", file=sys.stderr)
        result["skipped_no_key"] = len(findings)
        return result

    ledger = ls.read_ledger()
    known = set(ledger) | set(remote_keys)

    for f in findings:
        key = f["key"]
        title = f["title"][:250]
        description = issue_description(key, f)
        if key in known:
            tracked = remote_keys.get(key)
            # Ledger-only keys (the issue was moved out of the health project)
            # have no body to compare against, so they are left alone rather
            # than rewritten from a guess.
            if not tracked:
                result["existing"] += 1
                continue
            body_stale = tracked.get("description") != description
            # A CLOSED rollup issue is the correct end state of the fix: the
            # operator moved the job to a LaunchAgent and closed it. If the
            # finding is back, rewriting a Done issue puts it where nobody looks
            # while the run reports it as handled -- a false all-clear, worse
            # than never surfacing it. State is what carries visibility.
            # Independent of body_stale on purpose: a finding that is STILL TRUE
            # while the board says done is the blind spot whether or not the text
            # moved. An OPEN issue's state is never touched, so an issue the
            # operator moved to In Progress is not dragged back to Todo daily.
            closed = tracked.get("state_type") in CLOSED_STATE_TYPES
            if not body_stale and not closed:
                result["existing"] += 1
                continue
            # ONE finding lands in exactly ONE bucket. Incrementing `existing`
            # and `updated` in the same iteration rendered a single finding as
            # "1 updated, 1 already tracked", which reads as two items.
            result["reopened" if closed else "updated"] += 1
            if not apply:
                continue
            update: dict = {"title": title, "description": description}
            if closed:
                state_id = ls.reopen_state_id(team_id)
                if state_id:
                    update["stateId"] = state_id
            ls.graphql(ls.ISSUE_UPDATE, {"id": tracked["linear_id"], "input": update})
            verb = "reopened" if closed else "updated"
            print(f"  {verb} {tracked.get('identifier')}  {title[:70]}")
            continue
        if not apply:
            result["created"] += 1  # would create
            continue
        payload = {
            "title": title,
            "description": description,
            "teamId": team_id,
        }
        if project:
            payload["projectId"] = project["id"]
        data = ls.graphql(ls.ISSUE_CREATE, {"input": payload})
        node = (data.get("issueCreate") or {}).get("issue") or {}
        if node.get("id"):
            ls.append_ledger([{
                "key": key, "kind": "issue", "linear_id": node["id"],
                "identifier": node.get("identifier"), "source": "fleet-health",
            }])
            result["created"] += 1
            print(f"  filed {node.get('identifier')}  {f['title'][:70]}")
    return result


DETECTOR_ERROR = "error"


def run_detectors(detectors=None) -> tuple:
    """(findings, {detector_id: count | "error"}).

    A detector that RAISED is recorded as "error", never as 0. v1 swallowed the
    exception and reported a count of 0, so "I could not look" and "I looked and
    found nothing" printed identically — the worst possible failure mode for a
    detector whose entire value is a negative result. `crontab -l` failing on a
    locked-down machine would have read as a clean bill of health forever.
    """
    all_findings = []
    per_detector = {}
    for d in detectors if detectors is not None else DETECTORS:
        try:
            found = d["detect"](None) or []
        except Exception as exc:  # noqa: BLE001 - a health check must not crash its job
            print(f"  detector {d['id']} errored: {exc}", file=sys.stderr)
            per_detector[d["id"]] = DETECTOR_ERROR
            continue
        for f in found:
            f["key"] = finding_key(d["id"], f["subject"])
            f["detector"] = d["id"]
        per_detector[d["id"]] = len(found)
        all_findings.extend(found)
    return all_findings, per_detector


def blind_detectors(per_detector: dict) -> list:
    """Detectors that could not look. Their result is unknown, not clean."""
    return sorted(did for did, n in per_detector.items() if n == DETECTOR_ERROR)


def should_notify(outcome: dict, per_detector: dict, apply: bool) -> bool:
    """Whether this run has earned the ONE Slack line. Pure, so it is testable.

    A blind detector pings even with nothing filed. Before this, an errored
    detector produced one stderr line, `"error"` in a state file, exit 0, and NO
    ping — the gate needed created-or-updated, both 0. The distinction
    `CrontabUnavailable` exists to preserve died at the notification boundary,
    which is the only place the operator actually reads.

    Nothing pings without `--apply`. A dry run issues no mutation, so announcing
    one is announcing something that did not happen. The 08:15 LaunchAgent always
    passes `--apply`.
    """
    if not apply:
        return False
    return bool(outcome["created"] or outcome["updated"] or outcome["reopened"]
                or blind_detectors(per_detector))


def notify_text(outcome: dict, per_detector: dict) -> str:
    """The ONE Slack line, never one per finding. Pure, so its claims are testable."""
    blind = blind_detectors(per_detector)
    counts = (f"{outcome['created']} new issue(s) filed, "
              f"{outcome['reopened']} reopened, {outcome['updated']} updated, "
              f"{outcome['existing']} already tracked")
    if blind:
        # No all-clear language while a detector is blind: "nothing to do now"
        # over an unknown result is the exact lie the error state exists to stop.
        return (f"fleet health: BLIND SPOT — {', '.join(blind)} could not run, so "
                f"that result is UNKNOWN, not clean. Also: {counts}.")
    return f"fleet health: {counts}. Board has them; nothing to do now."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually file Linear issues")
    ap.add_argument("--quiet", action="store_true", help="no Slack line")
    args = ap.parse_args()

    problems = validate_detectors()
    if problems:
        print("BLOCK: detector registry is invalid:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    all_findings, per_detector = run_detectors()

    print(f"fleet-health {_now()}")
    for did, n in per_detector.items():
        print(f"  {did}: {n}")

    outcome = file_findings(all_findings, args.apply)
    print(f"  filed={outcome['created']} already-tracked={outcome['existing']} "
          f"rewritten={outcome['updated']} reopened={outcome['reopened']}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"ran_at": _now(), "per_detector": per_detector, "outcome": outcome}, indent=2))

    if not args.quiet and should_notify(outcome, per_detector, args.apply) and NOTIFY.exists():
        subprocess.run(["bash", str(NOTIFY), notify_text(outcome, per_detector)],
                       timeout=20, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
