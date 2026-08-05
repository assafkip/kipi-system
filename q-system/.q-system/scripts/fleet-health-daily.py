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

A FINDING CARRIES A REFERENCE, NEVER UNTRUSTED TEXT (ASK-204):

    A Linear issue filed here is PERMANENT. Any detector that reads arbitrary
    operator input -- a crontab line, an exception message -- publishes a
    reference to it (which line, which exception type) and never the input
    itself. The previous design copied the crontab line in with best-effort
    regex redaction over it; that is a denylist against unbounded shell syntax,
    and nine review rounds found nine distinct bypasses (a Slack webhook path, a
    Bearer token, a `bash -lc 'KEY=... claude'` credential, a backtick word
    start, `lin_api_`/`ntn_` shapes). Each fix was correct; the architecture was
    not. The operator opens their own crontab. Nothing untrusted crosses into a
    permanent external record, so there is nothing to redact and no bypass left
    to find.

    This constrains what a finding CARRIES, not what a detector READS. Deciding
    whether a line shells `claude` still parses the line in full, including
    quoting and command substitution.

ALERTING: ONE Slack summary line, never one ping per finding. The findings live in
Linear where they hold state. Slack is a pointer, not a ledger.

Exit 0 always (a health check that fails its own launchd job is noise); the report
goes to stdout and the ledger.
"""

from __future__ import annotations

import argparse
import hashlib
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


# ---------------------------------------------------------------------------
# ONE rendering per launchd kipi-key, shared by BOTH filers
# ---------------------------------------------------------------------------
# Two scripts file against these keys: this one at 08:15 and
# launchd-health-check.py at 09:30 and 21:30 (ASK-181 made them share the key on
# purpose -- a private namespace on either side files a SECOND permanent issue for
# the same dead job). `finding_hash` covers title + body, so sharing a key while
# rendering different text means every alternating run sees a stale hash and
# rewrites the issue: 13 Linear mutations a week and a "1 updated ... nothing to
# do now" Slack line every morning on a fleet where nothing moved. That is the
# checker training the operator to skip the line the real alert has to compete
# with (PR #19 round-3 review, major). One key, one renderer -- both callers come
# through here so the next edit cannot land on one side only.
LAUNCHD_FINDING_IDS = ("launchd-failing", "launchd-dark")


def launchd_exit_detail(list_status) -> str:
    """`exit N` for a `launchctl list` STATUS column value.

    The two readers see one machine state in TWO encodings: `launchctl list`
    prints a SIGNED status while `launchctl list <label>` prints the RAW wait
    status that launchd-health-check.py's `normalize_exit` decodes. Measured on
    this machine 2026-07-27 across 210 non-zero rows: a SIGKILLed job reads `-9`
    in the column and `"LastExitStatus" = 9`; `com.apple.BiomeAgent` reads `5`
    and `1280`. `abs()` lands both encodings in the same space, so the detail
    this renderer interpolates does not depend on WHICH script looked.

    A column value that is not a number keeps its text rather than becoming a
    fabricated `exit 0` -- an unparsable status is a thing to show, not to round.
    """
    try:
        return f"exit {abs(int(list_status))}"
    except (TypeError, ValueError):
        return f"exit {list_status}"


def launchd_finding(detector_id: str, label: str, detail: str = "") -> dict:
    """The finding dict for one launchd problem: {subject, title, body}.

    The ONLY place either filer renders these. `detail` is a `launchd_exit_detail`
    string and is ignored for `launchd-dark`, which has no exit status.
    """
    if detector_id == "launchd-failing":
        return {
            "subject": label,
            "title": f"launchd job failing: {label} ({detail})",
            "body": (
                f"`{label}` is loaded but its last run exited non-zero (**{detail}**).\n\n"
                "## Action\nRead its `StandardErrorPath`, fix the cause, and confirm a clean "
                "run. If the failure is environmental (auth expiry, server down), say so on "
                "this issue rather than retrying -- `self-healing-retry.md` rule 5 stops "
                "environmental failures on attempt 1."
            ),
        }
    if detector_id == "launchd-dark":
        return {
            "subject": label,
            "title": f"launchd job is dark: {label}",
            "body": (
                f"`{label}` has a plist in `~/Library/LaunchAgents/` but is not loaded, and "
                "it is NOT in the paused ledger -- so nothing recorded a decision to stop "
                "it. An unloaded job cannot report its own death.\n\n"
                "## Action\n"
                f"- Resume: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/{label}.plist`\n"
                f"- Or record the pause: add `{label}` to `~/.config/kipi/launchd-paused.txt`"
            ),
        }
    # Loud, not silent: a caller inventing a launchd detector id would otherwise
    # file an issue with an empty body under a key the other filer also writes.
    raise ValueError(f"no launchd rendering for detector id {detector_id!r}")


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
        out.append(launchd_finding("launchd-dark", label))
    return out


def detect_failing_jobs(_ctx) -> list:
    """Loaded, but the last run exited non-zero."""
    try:
        listing = subprocess.run(["launchctl", "list"], capture_output=True,
                                 text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in listing.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        _pid, status, label = parts[0], parts[1], parts[2]
        if not label.startswith(("com.kipi.", "com.cole.", "com.ask.", "com.assaf.",
                                 "com.claudedaddy.", "com.purespectrum.", "com.personal.")):
            continue
        if status in ("0", "-"):
            continue
        out.append(launchd_finding("launchd-failing", label,
                                   launchd_exit_detail(status)))
    return out


# ---------------------------------------------------------------------------
# The crontab: ONE reader, shared by both cron detectors
# ---------------------------------------------------------------------------


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


class RunContext:
    """Per-run shared state for the detectors. Today: ONE `crontab -l` per run.

    Two detectors read the crontab. `run_detectors` passed None as the context, so
    each one shelled out for itself and a test asserting only that a `cron_text`
    PARAMETER existed was labelled proof that "neither shells out twice" (PR #19
    review, minor 4). The parameter existed; the wiring did not.

    The FAILURE is cached alongside the value and re-raised per caller, so one read
    still produces two independent blind spots. Collapsing them would buy the dedup
    with a silent all-clear for whichever detector ran second -- the exact trade
    `run_detectors` exists to refuse.
    """

    def __init__(self, read_crontab=None):
        self._read_crontab = read_crontab or _crontab_text
        self._crontab = None  # (text, exception), whichever the read produced

    def crontab(self) -> str:
        if self._crontab is None:
            try:
                self._crontab = (self._read_crontab(), None)
            except Exception as exc:  # noqa: BLE001 - replayed to every caller
                self._crontab = (None, exc)
        text, exc = self._crontab
        if exc is not None:
            raise exc
        return text


def _crontab_for(ctx, cron_text):
    """The crontab a detector should read: injected > shared > its own read."""
    if cron_text is not None:
        return cron_text
    return ctx.crontab() if isinstance(ctx, RunContext) else _crontab_text()


def detect_duplicate_schedules(ctx, cron_text=None) -> list:
    """The same script scheduled by BOTH launchd and crontab.

    Found live 2026-07-26: reddit-build-radar runs at 08:00 from
    com.cole.reddit-radar-daily AND from a crontab line. Two schedulers on one
    script means pausing one does nothing, which is how a 'paused' job keeps running.

    The SCRIPT PATH is the finding's content here, and it is not untrusted text in
    the ASK-204 sense: it is matched against a plist this fleet owns, so a path
    that reaches the body is one that already appears in `~/Library/LaunchAgents/`.
    A path that matched nothing is never published.
    """
    cron = _crontab_for(ctx, cron_text)
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


# ---------------------------------------------------------------------------
# Does a crontab line INVOKE `claude`?
#
# This block only ever answers yes/no. Nothing it reads is published; see the
# ASK-204 paragraph in the module docstring. Weakening any of it to simplify the
# output would trade a real detection for nothing, which is the opposite trade.
# ---------------------------------------------------------------------------

CRON_COMMAND_WRAPPERS = {"env", "nohup", "nice", "time", "timeout", "caffeinate",
                         "sudo", "exec", "stdbuf", "npx", "flock", "ssh", "command",
                         "xargs"}

# Shell KEYWORDS that stand in front of a command without being one. `if claude -p
# x ; then ...` scored `if` as the command and answered False (fifth review,
# finding 3). A bare one of these in leading position is always the keyword: an
# argument never reaches here, because `_command_index` returns at the first token
# it does not skip.
SHELL_KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "!"}

# `command -v claude` PRINTS a path; it does not run claude. Widening the matcher
# to reach `command claude` without this would buy a real false positive for a
# false negative — the trade this detector exists to refuse.
_LOOKUP_FLAG_LETTERS = {"command": {"v", "V"}}

# A wrapper option whose VALUE is a separate token. Without this the value was
# scored as command position, so `sudo -u claude /opt/svc/run.sh` -- a service
# account named `claude`, not an invocation -- filed a permanent Linear issue
# (PR #11 fourth review, finding 4). This is the same rule `_shell_c_argument`
# already applies for shells: an option's argument is not a command.
_WRAPPER_VALUE_FLAGS = {
    "sudo": {"-u", "--user", "-g", "--group", "-U", "--other-user", "-C", "--close-from",
             "-D", "--chdir", "-p", "--prompt", "-r", "--role", "-t", "--type",
             "-R", "--chroot"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "npx": {"-p", "--package", "-w", "--workspace"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "caffeinate": {"-t", "-w"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "time": {"-f", "--format", "-o", "--output"},
    "exec": {"-a"},
    "flock": {"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"},
    "ssh": {"-i", "-l", "-p", "-o", "-F", "-b", "-c", "-D", "-E", "-e", "-I", "-J",
            "-L", "-m", "-O", "-Q", "-R", "-S", "-W", "-w"},
    # `xargs -I {} claude -p {}`: without `-I` here the `{}` placeholder was read
    # as the command and `claude` never reached command position. The attached
    # form (`-I{}`) needs nothing — it carries its own value (seventh review,
    # finding 3).
    "xargs": {"-I", "--replace", "-i", "-n", "--max-args", "-P", "--max-procs",
              "-s", "--max-chars", "-L", "-l", "-d", "--delimiter", "-E",
              "-a", "--arg-file"},
}

# Wrappers whose first POSITIONAL operand is not the command: flock takes a lock
# file, ssh takes a destination. Both were missing entirely, so
# `flock -n /tmp/x.lock claude -p` -- the standard way a cron job stops
# overlapping itself -- was a silent false negative (fourth review, finding 5).
# Skipping the operand is what keeps adding them from buying that at the price of
# a lock file or a host named `claude`.
_WRAPPER_OPERANDS = {"flock": 1, "ssh": 1}

# ssh does NOT exec its remote operands the way flock and sudo do. It joins
# everything after the destination with single spaces and hands ONE string to a
# shell on the far side, which lexes it itself. So the remote command has to be
# re-parsed as a command string -- exactly like a `-c` argument -- and reading it
# as tokens in the local segment made the QUOTED form (`ssh mini 'claude -p
# sweep'`, the form you write so the LOCAL shell does not expand it) lex to a
# single token whose basename is `claude -p sweep`, not `claude`. The unquoted
# form was pinned by the suite and the quoted one was a silent false negative
# (PR #19 round-3 review, minor 2). flock stays OUT of this set on purpose: it
# execs its operands directly, so `flock /tmp/x.lock echo 'a; claude -p x'` runs
# no claude and re-lexing it would invent one.
_REMOTE_SHELL_WRAPPERS = {"ssh"}

# A shell in command position does not RUN what follows; it runs the string
# handed to its `-c` flag. `bash -lc 'claude -p ...'` is the shape a cron line
# uses to get a login environment, so the command inside the quotes has to be
# parsed as a command, not scanned as text.
SHELL_COMMANDS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}

# Tokens that END a command and open the next one. Redirections (`<`, `>`, `>>`)
# are deliberately NOT here: they take an argument, they do not start a command.
# `{` / `}` group commands, so a segment opens after them — `{ claude -p x ; }` read
# `{` as the command and answered False (fifth review, finding 3). Brace EXPANSION
# (`cp ~/a/{x,y} ~/b`) and find's `{}` carry no surrounding whitespace, so they lex
# as one token and never look like an operator.
SHELL_OPERATORS = {"&&", "||", ";", "|", "&", "|&", "(", ")", "{", "}"}


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


# A wrapper's own positional argument: `timeout 1800`, `timeout 30m`,
# `timeout 1.5h`. `.isdigit()` alone missed the GNU duration suffix, so
# `timeout 30m claude` lost command-position tracking and slipped through as
# benign (third review, finding 3) — a silent false negative.
_WRAPPER_ARG_RE = re.compile(r"\d+(\.\d+)?[smhd]?")


# A cluster of bundled SHORT options: `-Hu`, `-nu`. Long options (`--user`) have a
# second dash and are matched whole; an attached value (`--user=x`) carries its own
# `=` and never reaches here.
_BUNDLED_SHORT_RE = re.compile(r"-[A-Za-z]+")


def _is_lookup_flag(token: str, wrapper: str) -> bool:
    """The flag turns this wrapper into a LOOKUP, so the segment runs no command."""
    letters = _LOOKUP_FLAG_LETTERS.get(wrapper, ())
    return bool(letters) and bool(_BUNDLED_SHORT_RE.fullmatch(token)) \
        and any(char in letters for char in token[1:])


def _takes_next_token(token: str, wrapper: str) -> bool:
    """The option consumes the NEXT token as its value.

    getopt's own bundling rule, because a whole-token membership test read `-u` and
    missed `-Hu` — and `sudo -Hu svcaccount cmd` is an ordinary idiom, so on a box
    with a `claude` service account it filed a permanent Linear issue asserting a
    scheduler bug that does not exist (fifth review, finding 2).

    Faithful, not just last-char: bundling STOPS at the first option that takes an
    argument, and any characters after it ARE that argument. So `-Hu claude` skips
    `claude` (H takes nothing, u is last), while `-uH claude` does not (H is already
    -u's value, and real sudo runs `claude` as user H). Reading the second shape as
    a flag cluster would buy the false positive back as a false negative.
    """
    value_flags = _WRAPPER_VALUE_FLAGS.get(wrapper, ())
    if token in value_flags:
        return True
    if not _BUNDLED_SHORT_RE.fullmatch(token):
        return False  # a long option, or `-` alone: nothing to unbundle
    letters = token[1:]
    for position, letter in enumerate(letters):
        if f"-{letter}" in value_flags:
            return position == len(letters) - 1  # last char: the value is the next token
    return False


def _command_index(tokens: list) -> int:
    """Index of the real command in a shell segment. See `_command_scan`."""
    return _command_scan(tokens)[0]


def _command_scan(tokens: list) -> tuple:
    """(command index, remote-command index) for a shell segment.

    The command index is the real command past env prefixes and wrappers, or -1
    when the segment holds no command.

    Tracks WHICH wrapper is in effect, because a bare `startswith("-")` skip
    reads a flag and leaves its value exposed: `sudo -u claude run.sh` scored
    `claude` -- the value of `-u` -- as the command (fourth review, finding 4).
    An option's argument belongs to the option, and a wrapper's leading operand
    (flock's lock file, ssh's host) belongs to the wrapper.

    The remote index is where a `_REMOTE_SHELL_WRAPPERS` wrapper's remote command
    STARTS (-1 when there is none). Recorded here rather than derived from the
    command index because a second wrapper resets the tracked one: in `ssh mini
    timeout 30 'claude -p x'` the wrapper in effect at the command is `timeout`,
    yet everything from `timeout` onward is still what ssh hands the far shell.
    """
    skip_value = False
    operands_left = 0
    wrapper = ""
    remote_index = -1
    for index, token in enumerate(tokens):
        if skip_value:
            skip_value = False
            continue  # the VALUE of the option just skipped, never a command
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            continue  # VAR=value prefix
        if token.startswith("-"):
            if _is_lookup_flag(token, wrapper):
                # `command -v claude` resolves a path, it runs nothing. The
                # remote index rides along: over ssh the far shell re-parses the
                # string and reaches the same answer for the same reason.
                return -1, remote_index
            skip_value = _takes_next_token(token, wrapper)
            continue
        if token in SHELL_KEYWORDS:
            continue  # a keyword in front of the command, never the command
        if _WRAPPER_ARG_RE.fullmatch(token):
            continue  # a wrapper's own positional arg, e.g. the 1800 in `timeout 1800`
        name = PurePosixPath(token).name
        if name in CRON_COMMAND_WRAPPERS:
            wrapper = name
            operands_left = _WRAPPER_OPERANDS.get(name, 0)
            continue
        if operands_left:
            operands_left -= 1
            if not operands_left and wrapper in _REMOTE_SHELL_WRAPPERS:
                remote_index = index + 1  # past ssh's destination: the remote command
            continue  # flock's lock file / ssh's destination, not the command
        return index, remote_index
    return -1, remote_index


def _command_token(tokens: list) -> str:
    """The real command in a shell segment, past env prefixes and wrappers."""
    index = _command_index(tokens)
    return tokens[index] if index >= 0 else ""


def _strip_comment(command: str) -> str:
    """Truncate at an sh comment: an UNQUOTED `#` that starts a word.

    Comment handling has to happen BEFORE lexing, on the raw string, because
    quoting is what decides it and posix dequoting erases the evidence: after
    `shlex`, `grep -q '#TODO'`'s argument and a genuine `# comment` are the same
    token, and treating both as comments silenced a real invocation after the
    `&&` (third review, finding 3). sh's own rule is positional — `a#frag` is
    one word, `# rest` is a comment — so the scan tracks quote state and word
    starts, the two things sh actually consults.
    """
    quote = ""
    for index, char in enumerate(command):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or command[index - 1] in " \t;|&()"):
            return command[:index]
    return command


def _lex(command: str):
    """Shell-aware tokens (a list), or None when the string cannot be parsed as sh.

    `punctuation_chars=True` makes `&& || ; | ( )` their own tokens while leaving
    quoted strings intact, which is what lets the operator split in
    `_shell_segments` happen at the TOKEN level. Splitting the raw string on
    `;`/`&&` (the shipped v1) cut inside quoted arguments: `echo "step one;
    claude -p x"` produced a second segment whose first token was `claude`.

    Comments are handled by `_strip_comment` before this runs (`commenters = ""`);
    an unbalanced quote returns None and the CALLER decides what that means —
    returning a whitespace split from here let the caller treat it like real sh
    tokens, which is exactly how a quoted `&&` got re-exposed as an operator
    (third review, finding 5).
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _shell_segments(command: str) -> list:
    """The command's shell segments, each as a token list.

    When the line is not parsable as sh (unbalanced quote), the whole line
    becomes ONE whitespace-split segment. `claude -p 'sweep the repo` is a real
    invocation with a typo and stays caught at line-lead command position; but
    the fallback must never SPLIT on operators, because a `&&` that posix
    parsing had absorbed into a quoted string is not a command boundary —
    re-exposing it invented a command position sh never creates and scored
    `echo 'reminder: && claude -p x` as an invocation (third review, finding 5).
    One segment can only be coarser than sh, never finer.
    """
    command = _strip_comment(command)
    tokens = _lex(command)
    if tokens is None:
        fallback = command.split()
        return [fallback] if fallback else []
    segments, current = [], []
    for token in tokens:
        if token in SHELL_OPERATORS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [s for s in segments if s]


# What a substitution collapses to once its contents have been taken out for
# their own walk. One token, no whitespace, no shell metacharacter, and not a
# name any wrapper or shell answers to -- so it can only ever be an argument.
_SUBST_PLACEHOLDER = "__kipi_subst__"


def _split_substitutions(command: str) -> tuple:
    """(command with every substitution masked, the command strings they run).

    ONE walker for both, because they have to agree. `_substitutions` alone left
    the substitution's TEXT in the string the segment walk lexed, and a
    substitution containing a space breaks the assignment prefix across two
    whitespace tokens: `` VAR=`echo secret` claude -p x `` lexed as
    [`VAR=\\`echo`, `` secret` ``, `claude`, ...], so `_command_index` skipped the
    first as `VAR=value`, scored `` secret` `` as the command, and answered False.
    That is a real invocation -- sh runs `claude -p x` with VAR set -- and it was
    a silent false negative (ASK-204, found by the reproducer this issue's
    acceptance criterion demands).

    Masking rather than deleting: the span becomes ONE argument-shaped token, so
    the assignment stays one token and a substitution in command position
    (`` `cmd` arg ``) cannot collapse into whatever followed it.

    Quote-aware, and that is DETECTION work. Single quotes SUPPRESS substitution
    and double quotes do not, so `echo 'run `claude -p x` now'` is prose and
    `echo "`claude -p x`"` is an invocation. A naive split on backticks would
    score the first — the same trap that made a quoted `&&` look like a command
    boundary (PR #11 third review, finding 5).

    An UNTERMINATED substitution yields nothing and masks nothing. sh would not
    run it either, and guessing where it ends is how a command position gets
    invented.
    """
    out, masked, index, quote, length = [], [], 0, "", len(command)
    while index < length:
        char = command[index]
        if quote == "'":
            quote = "" if char == "'" else quote
            masked.append(char)
            index += 1
            continue
        if char == "\\":
            masked.append(command[index:index + 2])
            index += 2  # escaped next char, in double quotes or unquoted
            continue
        if char == "'" and not quote:
            # `and not quote` is load-bearing: reaching here with quote == '"'
            # means an APOSTROPHE inside a double-quoted span, which sh treats as
            # a literal character. Opening a single-quote span on it inverted the
            # state for the rest of the line, so `echo "don't $(claude -p x)"` --
            # a real invocation -- was missed, and `echo "don't" 'run `claude -p
            # x` now'` -- prose -- was scored as one and would have filed a
            # PERMANENT false-positive issue (PR #19 review, minor 2).
            quote = "'"
        elif char == '"':
            quote = "" if quote == '"' else '"'
        elif char == "`":
            close = _scan_to(command, index + 1, "`")
            if close < 0:
                masked.append(command[index:])
                break
            out.append(command[index + 1:close])
            masked.append(_SUBST_PLACEHOLDER)
            index = close + 1
            continue
        elif char == "$" and command[index + 1:index + 2] == "(":
            close = _scan_to_paren(command, index + 2)
            if close < 0:
                masked.append(command[index:])
                break
            out.append(command[index + 2:close])
            masked.append(_SUBST_PLACEHOLDER)
            index = close + 1
            continue
        masked.append(char)
        index += 1
    return "".join(masked), out


def _substitutions(command: str) -> list:
    """The COMMAND STRINGS a substitution will run: `` `...` `` and `$(...)`.

    Both are command positions the segment walk cannot see, and they were handled
    by accident rather than on purpose: `$(` split only because `punctuation_chars`
    makes `(` its own token and `(` is in SHELL_OPERATORS. Backticks are in neither
    set, so `` OUT=`claude -p x` `` was a silent false negative, and `$(...)` INSIDE
    double quotes was one too — shlex keeps a quoted string whole, so no token ever
    became an operator (seventh review, finding 3).

    QUOTE-AWARE, and that is DETECTION work, not redaction work. ASK-204 lists this
    tracking among what the redaction rewrite deletes; it does not go, because
    single quotes SUPPRESS substitution and double quotes do not. `echo 'run
    `claude -p x` now'` is prose and `echo "`claude -p x`"` is an invocation.
    Dropping the tracking would score the first — a permanent false-positive
    issue — which is the "do not weaken detection to simplify output" line in the
    same issue. What ASK-204 removes is what the finding CARRIES; this decides
    what it DETECTS.

    An UNTERMINATED substitution yields nothing. sh would not run it either, and
    guessing where it ends is how a command position gets invented.
    """
    return _split_substitutions(command)[1]


def _scan_to(text: str, start: int, target: str) -> int:
    """Index of the next unescaped `target`, or -1."""
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == target:
            return index
        index += 1
    return -1


def _scan_to_paren(text: str, start: int) -> int:
    """Index of the `)` closing a `$(` opened before `start`, or -1. Nesting-aware
    so `$(echo $(claude -p x))` yields the whole inner command, not half of it."""
    depth, index = 1, start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if not depth:
                return index
        index += 1
    return -1


def _shell_c_argument(tokens: list, command_index: int) -> str:
    """The string a shell will EXECUTE: the token after its `-c`-bearing flag.

    Only consulted when the command itself is a shell, so `tar -czf` (whose flag
    also contains a `c`) is never read this way.

    Scanning stops at the first OPERAND after the shell: in `bash backup.sh -c
    <arg>` the `-c` belongs to backup.sh's argv, not to bash, and reading it as
    the shell's own flag scored a line that never runs claude (third review,
    finding 2). Only tokens before the shell's first operand are its options.
    """
    for index in range(command_index + 1, len(tokens)):
        token = tokens[index]
        if token.startswith("--"):
            continue  # a long option is still an option, not the first operand
        if not token.startswith("-"):
            return ""  # first operand: the script file; later flags are ITS argv
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
    # Bounded, not shallow. The cap exists to end recursion, not to decide which
    # nesting depths are real: at 2 a genuine `sh -c 'sh -c "sh -c \"claude\""'`
    # was answered False, and a silent false negative is the one failure this
    # detector cannot afford (fourth review, finding 5). Each level costs one
    # lex of a shorter string, so 5 is still bounded work per cron line.
    if _depth > 5:
        return False
    command = _strip_comment(command)
    # Substitutions come OUT before the segment walk lexes, and go back in as one
    # argument-shaped token each. Their contents are walked separately below, at
    # the same depth cap. Leaving them inline let a substitution's internal space
    # split an assignment prefix across two tokens (see _split_substitutions).
    masked, inner_commands = _split_substitutions(command)
    for tokens in _shell_segments(masked):
        command_index, remote_index = _command_scan(tokens)
        command_token = tokens[command_index] if command_index >= 0 else ""
        if _is_claude_token(command_token):
            return True
        if PurePosixPath(command_token).name in SHELL_COMMANDS:
            inner = _shell_c_argument(tokens, command_index)
            if inner and _shells_claude(inner, _depth + 1):
                return True
        # ssh's remote operands are JOINED with spaces and re-lexed by the far
        # shell, so they are a command STRING, not tokens in this segment. Joining
        # the already-lexed tokens is the faithful model: ssh concatenates its
        # argv after the local shell removed the quotes, which is why `ssh mini
        # echo "a; claude -p x"` really does run claude on the far side.
        if remote_index >= 0:
            remote = " ".join(tokens[remote_index:])
            if remote and _shells_claude(remote, _depth + 1):
                return True
    # A line sh REFUSES TO RUN runs nothing -- including whatever sits inside its
    # substitutions. `_shell_segments` already obeys that (an unbalanced quote
    # collapses to one coarse segment and never splits on an operator), and its
    # rule is "one segment can only be coarser than sh, never finer". The walk
    # below is FINER: `_split_substitutions` happily extracts `$(claude -p x)`
    # out of an unterminated double-quoted span and scored it as an invocation,
    # filing a permanent Linear issue for a line /bin/sh answers with a syntax
    # error (PR #19 round-3 review, minor 3).
    if _lex(_strip_comment(masked)) is None:  # the exact test `_shell_segments` makes
        return False
    # A substitution is a command position of its own, and the segment walk above
    # cannot reach one: it saw a placeholder. Same recursion, same depth cap as
    # the `-c` string: what runs inside `$( )` or backticks is a command, not text.
    for inner in inner_commands:
        if _shells_claude(inner, _depth + 1):
            return True
    return False


def offending_cron_lines(cron: str) -> list:
    """1-based line NUMBERS of the crontab lines that invoke `claude`.

    Numbers, not lines. This is the whole of ASK-204: the detector reads the line
    in full (above) and publishes only where it is. A number cannot carry a
    credential, so there is no redaction step to bypass.

    Numbered against the RAW splitlines, including comments and blanks, because
    the operator's editor numbers them that way too. A reference the operator
    cannot follow is not a reference.
    """
    return [number for number, line in enumerate(cron.splitlines(), start=1)
            if _shells_claude(_cron_command(line))]


def detect_cron_shells_claude(ctx, cron_text=None) -> list:
    """A crontab line that invokes `claude`. It cannot work: cron has no keychain.

    Probed 2026-07-23 (`reddit-build-radar/logs/cron-probe/result.txt`):
    `keychain_read_rc=44` and `{"is_error":true,...}`. cron starts from a bare
    environment with no keychain access, so subscription auth fails with an opaque
    error instead of a clean one — the failure reads as a broken prompt, not a
    broken scheduler, which is why it is worth catching at the crontab. launchd
    jobs DO have keychain access; every working `claude -p` job in this fleet is a
    LaunchAgent. Filed as ASK-150.

    ONE rollup finding, never one per line. A crontab line is an unstable string:
    forking a PERMANENT Linear issue per line would fork one per prompt edit too.
    The line numbers live in the body, which `file_findings` REWRITES on every run
    whose content changed — the same reasoning detect_open_spillover documents for
    its count. That update path is what makes the rollup honest: a second
    offending line added a month later lands on the same issue instead of
    disappearing behind an already-known dedup key.

    Raises CrontabUnavailable when the crontab could not be read at all, so a
    blind run is reported as an error rather than as a clean bill of health.
    """
    cron = _crontab_for(ctx, cron_text)
    numbers = offending_cron_lines(cron)
    if not numbers:
        return []
    return [{
        "subject": "cron-shells-claude",
        "title": f"{len(numbers)} crontab line(s) shell `claude` — cron has no keychain access",
        "body": (
            f"**{len(numbers)} crontab line(s) invoke `claude`.** They cannot "
            "authenticate.\n\n"
            "Run `crontab -l | cat -n` and read:\n\n"
            + "\n".join(f"- line {n}" for n in numbers)
            + "\n\nThe lines themselves are deliberately NOT copied here. A crontab "
              "line is operator-authored shell, a Linear issue is permanent, and "
              "redacting arbitrary shell before publishing it was a denylist that "
              "leaked in nine consecutive review rounds (ASK-204). A line number "
              "carries nothing to leak.\n\n"
              "cron runs from a bare environment with no keychain access, so "
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


def detect_stale_runtime_plugins(_ctx) -> list:
    """The RUNNING plugin copy is older than the merged one.

    THE PRODUCTION CALLER for runtime-plugin-freshness.py. Without an entry here
    the checker was reachable only from its own test, so the capability gate
    proved it works on fixtures and nothing ever pointed it at real runtime
    state -- a detector that cannot fire is documentation (codex review of PR
    #105, blocker). This job is the right surface because the failure is a
    property of THIS MACHINE at rest, not of any commit: CI has no
    ~/.claude/plugins to look at, so a CI-only check would be structurally blind.

    REUSES THE CHECKER'S OWN READERS via importlib, the same shape
    `_paused_labels` uses for the watchdog's ledger. Shelling it and parsing its
    stderr would be a SECOND definition of "stale" that can drift from the first;
    importing means the detector and the exit code can never disagree.

    THE BODY DELIBERATELY OMITS THE COMMITS-BEHIND COUNT. `subject` is the dedup
    key and `finding_hash` covers title + body, so any number that moves on every
    merge would rewrite the Linear issue daily -- the cry-wolf failure this file
    already fixed once for the launchd keys. Stale plugin names and dirty file
    names change only when the CONDITION changes, which is the thing worth
    re-filing for.
    """
    import importlib.util

    # A DETECTOR THAT CANNOT RUN SAYS SO. Every `return []` below used to cover
    # the checker being missing or unimportable, which is the silent-disable
    # shape: the job stays green because the thing that would have failed it
    # never loaded, and quiet is indistinguishable from healthy (codex review of
    # PR #105 round 2, major, raised against the ValueError twin of this path).
    # A distinct subject keeps it from colliding with a real staleness finding.
    def _broken(reason: str) -> list:
        return [{
            "subject": "runtime-plugin-freshness-unreadable",
            "title": "the runtime plugin freshness detector could not run",
            "body": (
                f"`detect_stale_runtime_plugins` could not evaluate runtime state: {reason}\n\n"
                "While this is true the fleet has NO check that the running plugins "
                "are the merged ones -- the failure mode that made the Judgment "
                "Compiler unreachable for a day. Absence of a finding here is not "
                "evidence the runtime is fresh.\n\n"
                "## Action\nRun `python3 q-system/.q-system/scripts/runtime-plugin-freshness.py` "
                "by hand and fix what it reports, then confirm this issue stops re-filing."
            ),
        }]

    checker = HERE / "runtime-plugin-freshness.py"
    if not checker.is_file():
        return _broken(f"the checker is missing at {checker}")
    spec = importlib.util.spec_from_file_location("rpf", checker)
    if spec is None or spec.loader is None:
        return _broken(f"python could not build an import spec for {checker}")
    rpf = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(rpf)
    except Exception as exc:
        return _broken(f"importing the checker raised {type(exc).__name__}")

    root = rpf.DEFAULT_PLUGIN_ROOT
    registry = root / "installed_plugins.json"
    marketplace = root / "marketplaces" / "kipi"
    # Same two quiet paths the checker itself treats as SKIP: a box with no
    # plugin registry does not run Claude Code plugins, and absence there is not
    # staleness. Returning [] rather than a finding keeps the two in agreement.
    if not registry.is_file() or not marketplace.is_dir():
        return []
    try:
        live = rpf.marketplace_versions(marketplace)
        installed = rpf.installed_versions(registry, "kipi")
    except ValueError as exc:
        # Malformed input is the checker's exit 2, and it is NOT a staleness
        # claim -- filing "your plugins are stale" off unparseable JSON would be
        # a fabricated finding. But returning [] made unreadable state look
        # exactly like healthy state, which disables the detector silently
        # (codex review round 2, major). Report the inability, not a staleness
        # verdict: separate subject, separate title, no invented severity.
        return _broken(f"the plugin registry or a manifest is unreadable ({exc})")

    stale = sorted(
        f"`{name}` scope={scope} installed **{version}**, marketplace **{live[name]}**"
        for name, scope, version in installed
        if live.get(name) and live[name] != version
    )
    # RETIRED PLUGINS ARE STILL RUNNING CODE (codex review round 4, major). A
    # plugin installed from a marketplace that no longer ships it was skipped by
    # the comprehension above -- `live.get(name)` is None, so the row fell
    # through and produced nothing. The checker at least prints a `note` line;
    # this detector emitted silence, which on the ONE unattended surface means
    # nobody ever learns that a retired plugin is still loaded. That is the same
    # class as the version drift this whole thing exists to catch: the runtime is
    # running code that the merged marketplace does not have.
    retired = sorted(
        f"`{name}` scope={scope} installed **{version}**, no longer in the marketplace"
        for name, scope, version in installed
        if live.get(name) is None
    )
    dirty = sorted(rpf.clone_dirty_tracked(marketplace))
    # COMMIT-LEVEL DRIFT, the thing version parity structurally cannot see
    # (codex review round 6, major). Each installed entry records the commit it
    # was built from; if this plugin's own subtree moved since then, the loaded
    # copy is not the merged one even though both sides report the same version
    # string. Per-plugin scoping is what keeps it exact -- see
    # plugin_commits_since for why a bare sha comparison rebuilds the docs-only
    # false alarm round 3 rejected.
    drifted = []
    try:
        commits = rpf.installed_commits(registry, "kipi")
    except ValueError:
        commits = {}
    for name, sha in sorted(commits.items()):
        n = rpf.plugin_commits_since(marketplace, name, sha)
        if n:
            drifted.append(
                f"`{name}` installed from **{sha[:12]}**, and its own files changed "
                f"in {'a later commit' if n == 1 else 'later commits'} on the clone"
            )

    # CLONE-BEHIND IS A REAL CONDITION AND WAS BEING DROPPED (codex review round
    # 2, major). The checker exits 1 on stale OR dirty OR behind; this detector
    # honoured only the first two, so a plugin commit that changes runtime code
    # WITHOUT bumping a manifest version never fired -- and that is the common
    # shape, since not every merge bumps a version.
    #
    # The reason it was dropped was body churn: `behind` is a COUNT, finding_hash
    # covers the body, and a number that moves on every merge rewrites the Linear
    # issue daily. That argument was right about the NUMBER and wrong to throw out
    # the SIGNAL. The fact is recorded; the count is not.
    # REFRESH THE REMOTE REF FIRST, HERE AND NOT IN THE CHECKER (codex review
    # round 4, major). clone_commits_behind reads the ALREADY-FETCHED
    # origin/main, so if nothing ever fetches, both the clone and its cached
    # remote ref sit at the same old commit and the count is 0 forever: PASS
    # reported indefinitely while merged plugin code never arrives. The
    # docstring calls the number a FLOOR, which is honest, but a floor that is
    # always zero is not a detector.
    #
    # The checker's no-network rule stays intact and is still right for it: it
    # runs interactively and in CI, where a gate that reaches the network fails
    # on a plane and then gets switched off. THIS caller is different -- an
    # unattended daily job on a networked box -- so the fetch belongs at this
    # call site, not inside the shared function.
    #
    # Best-effort by construction: a failure or timeout leaves the cached ref in
    # place and the FLOOR semantics apply exactly as before, so being offline
    # degrades this to the old behaviour instead of breaking the run.
    # A FETCH THAT KEEPS FAILING IS NOT A QUIET DEGRADE (codex review round 5,
    # major). The first cut swallowed every failure, so an expired credential or
    # a removed remote left the cached origin/main frozen and this detector
    # reported nothing forever -- the same PASS-forever hole the fetch was added
    # to close, one layer out. Silence about an inability is the defect class
    # this detector has now been corrected for three times (unreadable registry,
    # missing checker, and here), so the fix is the same one: say it, with the
    # cannot-run subject, instead of returning nothing.
    #
    # A transient blip self-clears: the subject is stable, so it is one issue
    # rather than a page per run, and the next successful fetch stops re-filing.
    fetch_error = ""
    if (marketplace / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(marketplace), "fetch", "--quiet", "origin", "main"],
                capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip().splitlines()
                fetch_error = detail[-1] if detail else f"git fetch exited {proc.returncode}"
        except subprocess.TimeoutExpired:
            fetch_error = "git fetch timed out after 60s"
        except (OSError, subprocess.SubprocessError) as exc:
            fetch_error = f"git fetch raised {type(exc).__name__}"
    if fetch_error:
        return _broken(
            "the marketplace clone's remote could not be refreshed "
            f"({fetch_error}), so 'behind origin/main' is computed from a cached "
            "ref and cannot be trusted")
    behind = rpf.clone_commits_behind(marketplace)
    is_behind = bool(behind)
    if not stale and not retired and not drifted and not dirty and not is_behind:
        return []

    parts = []
    if stale:
        parts.append(
            "## Installed versions behind the marketplace\n"
            + "\n".join(f"- {s}" for s in stale)
        )
    if retired:
        parts.append(
            "## Installed but no longer in the marketplace\n"
            "These are still LOADED at runtime while the merged marketplace no "
            "longer ships them. Either the plugin was retired and the install "
            "should be removed, or it was renamed and the install should follow.\n"
            + "\n".join(f"- {r}" for r in retired)
        )
    if drifted:
        parts.append(
            "## Installed from a commit whose plugin files have since changed\n"
            "Version parity cannot see this: the version string matches on both "
            "sides while the loaded copy predates the plugin's own changes.\n"
            + "\n".join(f"- {d}" for d in drifted)
        )
    if dirty:
        parts.append(
            "## Hand-edits in the marketplace clone\n"
            "These exist in the running runtime and nowhere on main. The next "
            "refresh discards them.\n"
            + "\n".join(f"- `{f}`" for f in dirty[:10])
        )
    if is_behind:
        parts.append(
            "## The marketplace clone is behind `origin/main`\n"
            "Merged plugin commits are not in the running clone. This fires even "
            "when every installed VERSION matches, because a plugin commit can "
            "change runtime code without bumping a manifest version.\n\n"
            "The commit count is deliberately not printed: it would move on every "
            "merge and rewrite this issue daily. Run the checker for the number."
        )
    parts.append(
        "## Action\n"
        "```\nclaude plugin marketplace update kipi\n"
        "claude plugin update <plugin>@kipi --scope <scope>\n```\n"
        "The second is not optional: the marketplace update moves the clone, but "
        "Claude loads the version-keyed cache the registry pins. Recover any "
        "hand-edit above into a PR before refreshing."
    )
    return [{
        "subject": "runtime-plugin-freshness",
        "title": "running kipi plugins are older than the merged ones",
        "body": "\n\n".join(parts),
    }]


DETECTORS = [
    {
        "id": "runtime-plugin-stale",
        "description": "the RUNNING plugin copy is older than the merged one, or hand-edited",
        "detect": detect_stale_runtime_plugins,
        "action": "file_issue",
        "lesson_waived": (
            "Not a recurring defect class with a lesson to cite -- it is a "
            "machine-state drift that reappears whenever an install is left "
            "pinned to an old version. The detector is the durable answer; a "
            "lesson would only restate it."
        ),
    },
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


# The staleness compare CANNOT read the body Linear returns: Linear re-serializes
# markdown on the read path (live evidence, PR #11 third review finding 1: `- `
# bullets come back as `* ` on ASK-148, a body no producer ever wrote `* ` into).
# A raw `!=` against that was stale on every run forever — a daily mutation and a
# daily false "1 updated" Slack ping for an UNCHANGED crontab, and every operator
# edit to the body silently reverted each morning. HTML comments DO survive the
# round-trip verbatim (verified on all 4 live issues), so the renderer's content
# hash rides inside one, and staleness compares hash-to-hash: "did OUR rendering
# change", immune to Linear's serializer and blind to everything it does not own.
_HASH_MARKER_RE = re.compile(r"<!--\s*kipi-hash:\s*([0-9a-f]+)\s*-->")


def finding_hash(finding: dict) -> str:
    """Hash of what the renderer owns: the finding's title and body."""
    return hashlib.sha256(
        f"{finding['title']}\n{finding['body']}".encode()).hexdigest()[:16]


def tracked_hash(description: str) -> str:
    """The kipi-hash a live issue carries, or "" (pre-hash issues read as stale
    once, which is the migration path: one rewrite adds the marker, then settled)."""
    found = _HASH_MARKER_RE.search(description or "")
    return found.group(1) if found else ""


# The end of the region this script owns. Everything below it on a live issue
# belongs to whoever wrote it and is spliced back onto every rewrite.
MANAGED_END = "<!-- kipi-managed-end -->"
_MANAGED_END_RE = re.compile(r"<!--\s*kipi-managed-end\s*-->")

# The last line the v1 renderer emitted, which is where an operator's note starts
# on every issue already on the board. Both filers are matched (this script and
# launchd-health-check.py, ASK-181), and the backticks are optional because Linear
# re-serializes markdown on the read path. The sentinel does not exist yet on
# those issues — this anchor is the migration, used once per issue.
_V1_TRAILER_RE = re.compile(r"Filed by\s+`?(?:fleet-health-daily|launchd-health-check)\.py`?\.")

# A kipi marker sitting on its own line. Stripped from the preserved tail so the
# spliced body carries exactly ONE kipi-key (linear-sync's MARKER_RE parses it
# fleet-wide) and exactly one kipi-hash (`tracked_hash` parses it here).
_KIPI_MARKER_LINE_RE = re.compile(
    r"(?m)^[ \t]*<!--\s*kipi-(?:key|hash|managed-end):?[^>]*-->[ \t]*$\n?")


def operator_tail(description: str) -> str:
    """Whatever a live issue's body holds that this script does not own.

    `_refresh_one` replaced `description` wholesale, so the morning an offending
    crontab line was added or removed, every annotation an operator had written on
    the rollup issue was deleted — silently, with the Slack line reporting it as
    "N updated", which reads as the body being refreshed rather than as operator
    content being replaced (PR #11 seventh review, finding 1). The prior suite
    asserted survival only on the UNCHANGED path, where no mutation is issued at
    all; that check could not fail.

    Blast radius is why the fallbacks are graded rather than strict: every
    fleet-health issue on the board today predates the hash marker, so `body_stale`
    is True for ALL of them on the first post-merge `--apply` run. They lose their
    annotations together or not at all.

    1. the sentinel, on anything this renderer wrote since;
    2. the v1 trailer, on every issue already on the board;
    3. failing both, the WHOLE body is treated as not-ours and preserved.

    Rule 3 buys one duplicated rendering on an unrecognisable body. That is
    recoverable and visible in the issue; deleting operator content is neither.
    """
    text = description or ""
    end = _MANAGED_END_RE.search(text)
    if end:
        tail = text[end.end():]
    else:
        trailer = _V1_TRAILER_RE.search(text)
        tail = text[trailer.end():] if trailer else text
    return _KIPI_MARKER_LINE_RE.sub("", tail).strip()


def issue_description(key: str, finding: dict, tail: str = "",
                      filer: str = "fleet-health-daily.py") -> str:
    """The issue body for a finding. ONE renderer, used by create AND update.

    Two renderers would drift, and the drift would be invisible: the created body
    and the updated body only ever exist on different days.

    The kipi-hash marker is a SEPARATE comment line, never folded into the
    kipi-key marker: linear-sync's MARKER_RE and every other kipi-key consumer
    parse that marker fleet-wide, and changing its shape would break the dedup
    guard that keeps these issues from forking.

    `tail` is operator-owned content carried through a rewrite. It is NOT hashed:
    `finding_hash` covers the finding's title and body only, so an operator's note
    can never make the body read stale and start a daily mutation.
    """
    managed = (f"<!-- kipi-key: {key} -->\n"
               f"<!-- kipi-hash: {finding_hash(finding)} -->\n\n"
               f"{finding['body']}\n\n"
               f"Filed by `{filer}`.\n"
               f"{MANAGED_END}")
    return f"{managed}\n\n{tail}" if tail else managed


# Linear WorkflowState.type values that mean the issue is off the board. Held
# here rather than read off the injected linear module so the reopen decision is
# this file's, testable without a Linear surface that must agree about it.
CLOSED_STATE_TYPES = ("completed", "canceled")


def file_findings(findings: list, apply: bool, filer: str = "fleet-health-daily.py",
                  linear=None) -> dict:
    """Create a Linear issue per finding, deduped by kipi-key; UPDATE it if stale.

    Reuses linear-sync's graphql + remote guard so 'already exists' has exactly one
    definition fleet-wide. Linear objects are permanent, so the guard is refetched
    here rather than trusted from any cache.

    `filer` names the script that produced the finding. It is a parameter rather
    than a constant because this is the fleet's ONE filer: launchd-health-check.py
    files its 09:30/21:30 findings through here too (ASK-181), against these same
    detector keys, so a finding both jobs see stays one issue instead of two.

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

    `skipped_no_key` keeps its name: launchd-health-check.py's own return paths
    and `linear_report_line` read that exact key (ASK-181), and renaming it here
    would make an unreachable-Linear run print `unfiled=0` on the watchdog side.
    """
    result = {"created": 0, "existing": 0, "skipped_no_key": 0, "updated": 0,
              "reopened": 0, "relisted": 0, "errors": 0}
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
        # COUNTED, and counted where the notification gate can see it. The
        # shipped code recorded this in a bucket `should_notify` never read, so
        # a dropped finding produced one stderr line into a file nobody reads
        # and a Slack line that said "Board has them; nothing to do now" -- the
        # exact lie the blind-detector branch exists to prevent (PR #11 fourth
        # review, finding 1).
        result["skipped_no_key"] = len(findings)
        # ASK-204: the exception TYPE and nothing else. The message is arbitrary
        # remote text (a GraphQL error array echoes the request, and this fleet's
        # requests carry an Authorization header), and the destination is a Slack
        # line plus a state file. Same rule as the crontab: publish a reference,
        # never the untrusted string. The full message is already on stderr above,
        # which goes to the run log the operator owns.
        result["unfiled_reason"] = f"{type(exc).__name__}; full text in the run log"
        return result

    ledger = ls.read_ledger()
    known = set(ledger) | set(remote_keys)

    for f in findings:
        key = f["key"]
        try:
            if key not in known:
                result[_create_one(ls, f, apply, team_id, project, filer)] += 1
                continue
            tracked = _tracked_issue(ls, key, remote_keys, ledger)
            if not tracked:
                # Known, and the issue cannot be located anywhere: the ledger
                # names a linear_id Linear no longer has. The shipped behaviour
                # counted it and pinged, every morning, forever -- with no way to
                # clear it and the finding never re-filed, so a real problem sat
                # unfiled behind a stale cache entry (PR #11 review, minor).
                #
                # The clearing path is to FILE IT AGAIN. `read_ledger` is
                # last-wins over an append-only file, so the new record's
                # linear_id replaces the dangling one and the next run resolves
                # the key normally. One `relisted` line, once, instead of a
                # permanent daily ping.
                print(f"  ledger key {key} names an issue Linear cannot find; re-filing",
                      file=sys.stderr)
                _create_one(ls, f, apply, team_id, project, filer)
                result["relisted"] += 1
                continue
            result[_refresh_one(ls, f, apply, tracked, team_id, filer)] += 1
        except Exception as exc:  # noqa: BLE001 - one finding's failure is not the run's
            print(f"  filing {key} FAILED: {exc}", file=sys.stderr)
            result["errors"] += 1
    return result


def _tracked_issue(ls, key: str, remote_keys: dict, ledger: dict) -> dict:
    """The live issue a known key names, or {} when it cannot be located.

    `remote_keys` covers the health PROJECT only. A key in the ledger but not in
    that project is the ordinary result of triage moving the issue, and the
    shipped code answered it with `existing += 1; continue` on every future run:
    the crontab could grow from 1 offending line to 5 with zero writes, zero
    pings, and "nothing to do now" as the only sentence the operator ever saw
    (PR #11 fourth review, finding 2). The ledger already holds the linear_id, so
    the issue is fetched by id rather than given up on for having moved.
    """
    tracked = remote_keys.get(key)
    if tracked:
        return tracked
    linear_id = (ledger.get(key) or {}).get("linear_id")
    if not linear_id:
        return {}
    return ls.fetch_issue(linear_id) or {}


def _create_one(ls, finding: dict, apply: bool, team_id: str, project,
                filer: str) -> str:
    """File ONE new issue. Returns the outcome bucket. Raises on a Linear failure."""
    if not apply:
        return "created"  # would create
    payload = {
        "title": finding["title"][:250],
        "description": issue_description(finding["key"], finding, filer=filer),
        "teamId": team_id,
    }
    if project:
        payload["projectId"] = project["id"]
    data = ls.graphql(ls.ISSUE_CREATE, {"input": payload})
    node = (data.get("issueCreate") or {}).get("issue") or {}
    if not node.get("id"):
        # A create that returned no issue is a FAILURE, not a quiet zero. The
        # shipped code fell off the end of the branch here and counted nothing,
        # which reads downstream as "no findings" rather than "the write did not
        # land".
        raise RuntimeError(f"issueCreate returned no issue for {finding['key']}")
    ls.append_ledger([{
        "key": finding["key"], "kind": "issue", "linear_id": node["id"],
        "identifier": node.get("identifier"), "source": "fleet-health",
    }])
    print(f"  filed {node.get('identifier')}  {finding['title'][:70]}")
    return "created"


def _refresh_one(ls, finding: dict, apply: bool, tracked: dict, team_id: str,
                 filer: str) -> str:
    """Rewrite / reopen ONE tracked issue. Returns the outcome bucket.

    Raises on a Linear failure: the CALLER decides what one finding's failure
    means for the rest of the run. Before this split exactly one network call in
    the whole path was guarded, so a 429 on the first finding propagated out of
    `main()` -- later findings never attempted, the state file left holding
    yesterday's `ran_at`, and no Slack line sent at all (PR #11 fourth review,
    finding 3).
    """
    title = finding["title"][:250]
    # Hash-to-hash, never body-to-body: Linear re-serializes markdown on the read
    # path, so a raw compare was stale forever (see the kipi-hash block above
    # issue_description).
    body_stale = tracked_hash(tracked.get("description")) != finding_hash(finding)
    # A CLOSED rollup issue is the correct end state of the fix: the operator
    # moved the job to a LaunchAgent and closed it. If the finding is back,
    # rewriting a Done issue puts it where nobody looks while the run reports it
    # as handled -- a false all-clear, worse than never surfacing it. State is
    # what carries visibility. Independent of body_stale on purpose: a finding
    # that is STILL TRUE while the board says done is the blind spot whether or
    # not the text moved. An OPEN issue's state is never touched, so an issue the
    # operator moved to In Progress is not dragged back to Todo daily.
    closed = tracked.get("state_type") in CLOSED_STATE_TYPES
    if not body_stale and not closed:
        return "existing"
    if not apply:
        # A dry run reports the action it WOULD take. It cannot know whether a
        # reopen state exists without the network call it is forbidden to make,
        # so "reopened" here is the prediction.
        return "reopened" if closed else "updated"
    # Splice, never replace. The wholesale rewrite deleted every operator
    # annotation the moment the finding's content changed (PR #11 seventh review,
    # finding 1). This script owns the region above `MANAGED_END`; everything
    # below it is carried through untouched.
    update: dict = {
        "title": title,
        "description": issue_description(finding["key"], finding,
                                         operator_tail(tracked.get("description")),
                                         filer=filer),
    }
    reopening = False
    if closed:
        # The issue's OWN team, falling back to the team this lookup started
        # from. A workflow state id belongs to one team, and an issue that left
        # the health project may have left the team with it.
        state_id = ls.reopen_state_id(tracked.get("team_id") or team_id)
        if state_id:
            update["stateId"] = state_id
            reopening = True
        elif not body_stale:
            # No reopenable state and a current body: nothing useful to send.
            # Counting a daily no-op rewrite as progress would be the same false
            # claim one bucket over.
            return "existing"
    data = ls.graphql(ls.ISSUE_UPDATE, {"id": tracked["linear_id"], "input": update})
    # A REFUSED mutation is a failure, not an update. `IssueUpdatePayload.success`
    # is a non-null Boolean; the field exists because it can be false. Firing and
    # never reading the payload printed `updated ISS-1`, counted updated=1, and let
    # the Slack line close with "nothing to do now" while the new offending line
    # never reached the issue (PR #11 fifth review, finding 1).
    if not (data.get("issueUpdate") or {}).get("success"):
        raise RuntimeError(f"issueUpdate refused for {finding['key']}")
    # ONE finding lands in exactly ONE bucket, decided AFTER the mutation input
    # is known: returning "reopened" before resolving the state id announced a
    # reopen that was never sent when no reopenable state existed -- the issue
    # stayed completed while Slack said it was back on the board (PR #11 third
    # review, finding 6).
    verb = "reopened" if reopening else "updated"
    print(f"  {verb} {tracked.get('identifier')}  {title[:70]}")
    return verb


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
    # ONE context for the whole run, so the two crontab readers share a read.
    context = RunContext()
    for d in detectors if detectors is not None else DETECTORS:
        try:
            found = d["detect"](context) or []
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


def outcome_line(outcome: dict) -> str:
    """The filing result as one line that cannot lie by omission.

    Scar (ASK-181 review): this printed `created` and `existing` only. Because
    `file_findings` catches its own network errors and returns
    {created: 0, existing: 0, skipped_no_key: N}, 'Linear was unreachable and N
    findings went nowhere' printed byte-identically to 'the fleet is clean,
    nothing to file'. `unfiled` is what separates empty from broken.

    launchd-health-check.py keeps its OWN copy of this formatter on purpose: it
    has to be able to report that THIS file is missing, which is the rsync
    --delete scar it was built for. Do not consolidate them into a dependency
    that disappears exactly when it is needed.

    `.get` on the newer buckets, not `[]`: launchd-health-check.py's own failure
    paths build a 3-key outcome by hand and pass it here, and a KeyError in the
    reporter would take out the watchdog's report of its own failure."""
    return (f"  filed={outcome['created']} already-tracked={outcome['existing']} "
            f"unfiled={outcome['skipped_no_key']} "
            f"rewritten={outcome.get('updated', 0)} reopened={outcome.get('reopened', 0)} "
            f"relisted={outcome.get('relisted', 0)} errors={outcome.get('errors', 0)}")


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

    A run that could not FILE is as unclean as a run that could not LOOK. The
    shipped gate read created/updated/reopened plus blind detectors and stopped
    there, so Linear being unreachable — every finding dropped — cleared the gate
    as an all-clear (PR #11 fourth review, finding 1).
    """
    if not apply:
        return False
    return bool(outcome.get("created") or outcome.get("updated")
                or outcome.get("reopened") or outcome.get("skipped_no_key")
                or outcome.get("relisted") or outcome.get("errors")
                or blind_detectors(per_detector))


def notify_text(outcome: dict, per_detector: dict) -> str:
    """The ONE Slack line, never one per finding. Pure, so its claims are testable.

    Every way this run could be WRONG about the board goes in front of the
    counts, and any one of them removes the all-clear sentence. Silence and
    "nothing to do now" are the two things a 3am reader cannot distinguish from
    success, so neither is allowed over an unknown.
    """
    counts = (f"{outcome.get('created', 0)} new issue(s) filed, "
              f"{outcome.get('reopened', 0)} reopened, {outcome.get('updated', 0)} updated, "
              f"{outcome.get('existing', 0)} already tracked")
    warnings = []
    blind = blind_detectors(per_detector)
    if blind:
        warnings.append(f"BLIND SPOT — {', '.join(blind)} could not run, so that "
                        "result is UNKNOWN, not clean")
    if outcome.get("skipped_no_key"):
        warnings.append(f"{outcome['skipped_no_key']} finding(s) NOT filed, Linear "
                        f"unreachable ({outcome.get('unfiled_reason', 'no reason recorded')})")
    if outcome.get("errors"):
        warnings.append(f"{outcome['errors']} finding(s) failed to file — Linear "
                        "rejected the write; see the run log")
    if outcome.get("relisted"):
        warnings.append(f"{outcome['relisted']} tracked issue(s) had vanished from Linear "
                        "and were re-filed; the ledger now points at the new issue")
    if warnings:
        return f"fleet health: {'; '.join(warnings)}. Also: {counts}."
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
    print(outcome_line(outcome))

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"ran_at": _now(), "per_detector": per_detector, "outcome": outcome}, indent=2))

    if not args.quiet and should_notify(outcome, per_detector, args.apply) and NOTIFY.exists():
        subprocess.run(["bash", str(NOTIFY), notify_text(outcome, per_detector)],
                       timeout=20, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
