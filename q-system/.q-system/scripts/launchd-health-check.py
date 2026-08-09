#!/usr/bin/env python3
"""Watchdog for the founder's launchd jobs -- surfaces silent job deaths.

Auto-discovers every ~/Library/LaunchAgents/<prefix>*.plist for the OS's base
job families (WATCHED_PREFIXES) plus any instance-local families listed in
EXTRA_PREFIXES_FILE, and Slack-pings (deduped) on TWO silent-death modes:
  1. loaded but its last run exited non-zero (LastExitStatus via `launchctl list`)
  2. installed on disk but NOT loaded into launchd -- so it silently never runs.
     Scar 2026-07-05: com.cole.daily-video was present + scheduled 07:00 but
     unloaded, so it produced no video AND no failure ping (an unloaded job
     cannot ping). Mode 1 alone -- the old com.kipi.*-only check -- was blind to
     both the non-kipi families and the entirely-unloaded case.

Scar: the fractional-cxo income scanners (opp-scan, bolt-on-discovery) exited 127
every day for 6 days (2026-06-24..2026-06-30) after a `kipi update` rsync --delete
wiped their scripts out from under the plists. Nothing surfaced it -- the jobs just
silently stopped hunting income. A prompt cannot watch launchd; this job can. It is
the deterministic backstop that turns a silent 127 into a phone ping within hours.

Every finding also becomes a Linear issue (ASK-181), deduped forever by the SAME
kipi-key fleet-health-daily.py uses for its own launchd checks. A Slack line is
read once and scrolls away; the issue holds state. Slack stays the pointer.

Single notification channel: slack-notify.sh (founder-notifications rule). Silent
no-op if no webhook is configured, so this watchdog never breaks anything.

The watchdog always exits 0 -- it must never become the failing job it reports.

Usage:
  launchd-health-check.py             # check; ping + file Linear issues
  launchd-health-check.py --dry-run   # print findings only; no ping, no issue,
  launchd-health-check.py --dry       #   no state write (--dry / -n are aliases)

Dry mode makes ONE read-only Linear query (the dedup fetch) so its preview of a
permanent, undeletable action is the real number. It writes nothing: no issue, no
state file, no ping. Any flag that is not a dry alias is REFUSED, never run live.
"""
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

SELF_LABEL = "com.kipi.launchd-health"
FAIL_PING_TTL_SECONDS = 6 * 3600  # re-ping a still-failing job at most this often
HERE = Path(__file__).resolve().parent
NOTIFY_SCRIPT = HERE / "slack-notify.sh"
DRY_FLAGS = ("--dry", "--dry-run", "-n")
STATE_FILE = Path.home() / ".config" / "kipi" / "launchd-health-state.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"

# Base launchd job families this OS's own automation uses. A prefix that matches
# nothing on a given machine is a harmless no-op. Instance- or client-specific
# families (client slack syncs, brand jobs) live in EXTRA_PREFIXES_FILE below, NOT
# here -- the skeleton propagates fleet-wide via kipi update and must carry no
# single instance's brand names.
WATCHED_PREFIXES = (
    "com.kipi.",
    "com.cole.",         # daily podcast/video GTM pipeline
    "com.claudedaddy.",  # social posters (Pinterest/X/YouTube/refill/repo)
    "com.ask.",          # ASK AI podcast
    "com.assaf.",        # competitive-analysis morning
)

# Instance-local additions, one prefix per line ('#' starts a comment). Lives in
# the founder's live env (~/.config/kipi/), outside the repo, so client/brand job
# families are watched without being baked into the propagated skeleton. Missing
# file = base set only (harmless no-op).
EXTRA_PREFIXES_FILE = Path.home() / ".config" / "kipi" / "launchd-watch-prefixes.txt"

# Labels that are not_loaded ON PURPOSE. A deliberately paused job is not a
# failure, and pinging about one is the alert-fatigue mechanism that teaches the
# founder to ignore this channel entirely.
#
# Scar 2026-07-26: 26 com.cole.* jobs were paused by commenting `com.cole.` out
# of EXTRA_PREFIXES_FILE. That could never work -- load_watched_prefixes() only
# ADDS from that file, so a commented line cannot remove a prefix hardcoded in
# WATCHED_PREFIXES. The pause was real, the silence was not, and one manual run
# fired 26 false pings. Suppression needs its own ledger, not a comment.
#
# Paused labels are still PRINTED (visible, not forgotten) and never pinged.
PAUSED_LABEL_FILES = (
    Path.home() / ".config" / "kipi" / "launchd-paused.txt",
    Path.home() / ".config" / "kipi" / "cole-pause.state",  # the live pause ledger
)


def load_paused_labels():
    """Exact labels (not prefixes) that are intentionally stopped."""
    paused = set()
    for path in PAUSED_LABEL_FILES:
        try:
            lines = path.read_text().splitlines()
        except (FileNotFoundError, NotADirectoryError):
            continue
        for line in lines:
            entry = line.split("#", 1)[0].strip()
            if entry:
                paused.add(entry)
    return paused


def load_watched_prefixes():
    """Base families plus any instance-local additions from EXTRA_PREFIXES_FILE."""
    prefixes = list(WATCHED_PREFIXES)
    try:
        lines = EXTRA_PREFIXES_FILE.read_text().splitlines()
    except FileNotFoundError:
        return tuple(prefixes)
    for line in lines:
        entry = line.split("#", 1)[0].strip()
        if entry and entry not in prefixes:
            prefixes.append(entry)
    return tuple(prefixes)


def normalize_exit(raw):
    """launchctl reports LastExitStatus as a raw wait(2) status. Decode to the
    human exit code: exit 3 arrives as 3<<8 = 768; a signal kill as 128+signal.
    A small value (<256) is already a clean code, so pass it through."""
    if raw == 0 or 0 < raw < 256:
        return raw
    exit_code = (raw >> 8) & 0xFF
    if exit_code:
        return exit_code
    signal_num = raw & 0x7F
    return 128 + signal_num if signal_num else raw


def classify_status(returncode, stdout):
    """Pure classifier for a `launchctl list <label>` result (returncode, stdout):
      ('failing', code)     loaded, last run exited non-zero
      ('not_loaded', None)  plist on disk but not bootstrapped -> never runs
      ('ok', 0)             loaded, last run clean (or a benign KeepAlive restart)
    Split out from job_status so the SIGTERM/live-PID logic below is unit-testable
    without shelling launchctl.

    Benign-restart carve-out (scar 2026-07-18): a KeepAlive job restarts on exit,
    and launchd records the PREVIOUS run's SIGTERM as LastExitStatus while a fresh
    process (a live PID) is already running. `com.cole.linkedin-session` logged
    LastExitStatus=15 with a live PID every cycle and the watchdog paged "exit 15"
    falsely. A SIGTERM (graceful stop, raw wait-status 15) WITH a live PID is that
    relaunch, not a death -> ok. Kept narrow to SIGTERM: a crash-loop
    (SIGKILL/SIGSEGV while KeepAlive relaunches) still pages, and a real exit(15)
    (raw wait-status 15<<8 = 3840, not 15) still pages."""
    if returncode != 0:
        return ("not_loaded", None)
    match = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', stdout)
    raw = int(match.group(1)) if match else 0
    code = normalize_exit(raw)
    if code == 0:
        return ("ok", 0)
    has_live_pid = re.search(r'"PID"\s*=\s*\d+', stdout) is not None
    terminated_by_sigterm = raw == 15  # raw wait-status 15 = killed by SIGTERM
    if has_live_pid and terminated_by_sigterm:
        return ("ok", 0)
    return ("failing", code)


def job_status(label):
    """Classify a launchd label by shelling `launchctl list <label>`:
      ('unknown', None)     launchctl unavailable -- do not alert
      otherwise -> classify_status(returncode, stdout)
    `launchctl list <label>` exits non-zero when the label is not loaded, which
    is how a silently-unloaded job (present plist, absent from launchd) is caught."""
    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return ("unknown", None)
    return classify_status(result.returncode, result.stdout)


def discover_problems():
    """List (label, kind, detail) for every watched job that is failing or
    installed-but-unloaded. Watched = any watched-prefix plist, minus self."""
    problems = []
    seen = set()
    paused = load_paused_labels()
    for prefix in load_watched_prefixes():
        for plist in sorted(LAUNCH_AGENTS.glob(f"{prefix}*.plist")):
            label = plist.stem
            if label == SELF_LABEL or label in seen:
                continue
            seen.add(label)
            kind, code = job_status(label)
            if kind == "failing":
                problems.append((label, "failing", f"exit {code}"))
            elif kind == "not_loaded":
                if label in paused:
                    # Intentional. Reported so it stays visible, never pinged.
                    problems.append((label, "paused", "paused on purpose"))
                else:
                    problems.append((label, "not_loaded", "installed but not running"))
    return problems


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def write_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


_NOTIFY_CHANNEL = None


def notify_channel_configured():
    """True when a page could actually leave this machine.

    Borrowed, not re-derived: `fable-escalate.py` already owns the Python read of
    slack-notify.sh's webhook resolution order ($KIPI_SLACK_WEBHOOK, then
    ~/.config/kipi/slack-webhook), and a second copy here is the drift
    `fleet-homogeneity` exists to stop. Loaded through the same lazy-importlib
    shape as `_fleet_health` / `_intent_module`, so its absence cannot stop the
    watchdog.

    A load failure answers False -- "delivery unknown". The caller reads that as
    NOT delivered, which costs a repeated ping and never costs a missed one. That
    is the same trade `check()` in launchd-intent-verify.py already made: a
    duplicate is the failure this system is allowed to have.
    """
    global _NOTIFY_CHANNEL
    if _NOTIFY_CHANNEL is None:
        import importlib.util

        try:
            spec = importlib.util.spec_from_file_location(
                "fe", HERE / "fable-escalate.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _NOTIFY_CHANNEL = module.notify_channel_configured
        except Exception:  # noqa: BLE001
            _NOTIFY_CHANNEL = lambda: False  # noqa: E731
    return _NOTIFY_CHANNEL()


_NOTIFY_SENDER = False


def _notify_sender():
    """fable-escalate.py's `notify_send`, or None when it cannot be loaded.

    Same lazy-importlib borrow as `notify_channel_configured` above, and for the
    same reason: that module is the single Python reader of slack-notify.sh's
    delivery verdict, and a second copy here is the drift `fleet-homogeneity`
    exists to stop. None means "delivery unknowable", which the caller reads as
    NOT delivered.
    """
    global _NOTIFY_SENDER
    if _NOTIFY_SENDER is False:
        import importlib.util

        try:
            spec = importlib.util.spec_from_file_location(
                "fe_send", HERE / "fable-escalate.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _NOTIFY_SENDER = module.notify_send
        except Exception:  # noqa: BLE001
            _NOTIFY_SENDER = None
    return _NOTIFY_SENDER


def send_ping(message):
    """Attempt the page. Returns True only when it could actually have LEFT.

    Scar (PR #134 review, major): this returned None on every path, and
    `run_intent_check` recorded the run as seen regardless. slack-notify.sh is a
    silent no-op that STILL EXITS 0 when no webhook resolves -- its own header
    says so -- so neither its exit code nor "the subprocess started" distinguishes
    a delivered page from a swallowed one. Measured on the shipped code with no
    webhook and a dead filer: 0 findings reached Linear, the message was never
    sent, the run was committed anyway, and the following 12 runs were silent.

    Scar (PR #134 review round 5, same class one layer down, reproduced before
    fixing): the fix above still ended in `return proc.returncode == 0`, and
    slack-notify.sh exits 0 after a curl that never reached Slack -- its last line
    is `curl ... || true`. Measured with the webhook pointing at a refused port:
    curl failed, this returned True, run_intent_check committed the run, and the
    next 13 scheduled runs were silent. A configured channel says a page COULD
    leave the machine; it never said this one did.

    The POST outcome exists in exactly one place -- inside slack-notify.sh -- so
    it is now REPORTED from there (KIPI_NOTIFY_VERDICT_FILE) and read by one
    shared function rather than re-inferred here. Borrowed through the same lazy
    importlib shape as `notify_channel_configured`, and a load failure answers
    False: delivery unknown reads as not delivered, which costs a duplicate ping
    and never a missed one.

    HONEST BOUNDARY: True means Slack accepted the POST, not that a human saw it.
    slack-notify.sh's fixture guard refuses to page on a loopback
    KIPI_LINEAR_API_URL -- that now reports `refused-fixture`, so it reads as NOT
    delivered here instead of as a page. Tests stub send_ping regardless (finding
    2 of the round-2 review); production has no loopback Linear URL.
    """
    if not NOTIFY_SCRIPT.exists():
        return False
    if not notify_channel_configured():
        return False
    send = _notify_sender()
    if send is None:
        return False
    try:
        return bool(send(message, notify=str(NOTIFY_SCRIPT))["delivered"])
    except Exception:  # noqa: BLE001
        return False


def is_dry_run(args):
    """True when a dry alias was typed. Answers only that; see parse_mode."""
    return any(arg in DRY_FLAGS for arg in args)


def parse_mode(args):
    """('live'|'dry'|'refuse', unrecognized_flags).

    Scar (ASK-181): dry mode used to be `"--dry" in sys.argv`, an exact string
    match. `--dry-run` -- the flag this job's own migration checklist tells the
    verifier to type -- did not match, so a read-only check silently took the LIVE
    path and pinged the founder's phone.

    Widening the accept-list fixed that one typo and left the shape intact: every
    OTHER near-miss (`--dry-run=1`, `--dryrun`, `--dry_run`, `-dry`) still armed
    the live path. So an unrecognized flag now REFUSES the run instead of guessing.
    An unknown flag alongside a valid dry one also refuses -- if part of the
    command line is unparsed, the operator's intent is unknown, and the safe
    reading of an unknown intent is 'do nothing'.

    launchd invokes this script with no arguments, so refusing cannot stop the
    scheduled run; it only stops a hand-typed command from doing more than the
    operator asked."""
    unrecognized = [arg for arg in args if arg not in DRY_FLAGS]
    if unrecognized:
        return ("refuse", unrecognized)
    return ("dry" if is_dry_run(args) else "live", [])


# --- findings reach Linear, not only Slack -----------------------------------
# Bar 2 of the job-migration contract (ASK-181). The detector ids below are
# fleet-health-daily.py's, not new ones: that job runs the same two checks at
# 08:15 and files against those keys. Sharing the key means a job both of them see
# is ONE permanent issue; a private namespace here would file a second one every
# time, and Linear issues are not deleted in this fleet.
LINEAR_DETECTOR_BY_KIND = {
    "failing": "launchd-failing",
    "not_loaded": "launchd-dark",
    # "paused" is deliberate, recorded in the pause ledger, and never filed.
}

_FLEET_HEALTH = None


def _fleet_health():
    """Lazily load fleet-health-daily.py -- the one place that defines a finding's
    Linear key and how it gets filed. Loaded on demand so a healthy run (the
    common case) pays nothing, and so an import error cannot stop the watchdog."""
    global _FLEET_HEALTH
    if _FLEET_HEALTH is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("fh", HERE / "fleet-health-daily.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _FLEET_HEALTH = module
    return _FLEET_HEALTH


def linear_findings(problems):
    """Turn watchdog problems into fleet-health finding dicts, ready to file."""
    fleet_health = _fleet_health()
    findings = []
    for label, kind, detail in problems:
        detector = LINEAR_DETECTOR_BY_KIND.get(kind)
        if detector is None:
            continue
        # fleet-health-daily.py RENDERS these, it does not just name their key.
        # Both scripts file against one kipi-key and `finding_hash` covers title
        # and body, so a second rendering here made every alternating run see a
        # stale hash: a Linear rewrite and a "1 updated" Slack line twice a day on
        # an unchanged fleet (PR #19 round-3 review, major). Rendering is safe to
        # delegate for the same reason the key is: this path only runs when
        # fleet-health-daily.py loaded, and `file_linear_findings` already reports
        # its ABSENCE as owed-but-unfiled rather than letting it raise.
        finding = fleet_health.launchd_finding(detector, label, detail)
        finding["key"] = fleet_health.finding_key(detector, label)
        finding["detector"] = detector
        findings.append(finding)
    return findings


def file_linear_findings(problems, apply=True):
    """File the findings as deduped Linear issues. Never raises.

    A watchdog that dies because Linear is unreachable stops watching launchd --
    which is precisely the silent death it exists to catch. A filing failure is
    counted and printed, never propagated.

    With apply=False nothing is created; the same filer still runs its dedup so a
    dry preview reports the real number instead of a second, looser estimate.

    Every return path sets `skipped_no_key` to the number of problems that were
    OWED an issue and did not get one. Counting the findings we managed to build
    would report 0 for the one failure that matters most -- fleet-health-daily.py
    missing entirely, which is the `kipi update` rsync --delete scar this watchdog
    exists for."""
    owed = sum(1 for _, kind, _ in problems if kind in LINEAR_DETECTOR_BY_KIND)
    try:
        findings = linear_findings(problems)
    except Exception as exc:  # noqa: BLE001
        print(f"linear findings could not be built: {exc}", file=sys.stderr)
        return {"created": 0, "existing": 0, "skipped_no_key": owed, "owed": owed}
    if not findings:
        return {"created": 0, "existing": 0, "skipped_no_key": 0, "owed": 0}
    try:
        outcome = _fleet_health().file_findings(
            findings, apply=apply, filer="launchd-health-check.py")
    except Exception as exc:  # noqa: BLE001
        print(f"linear filing skipped: {exc}", file=sys.stderr)
        return {"created": 0, "existing": 0, "skipped_no_key": len(findings),
                "owed": len(findings)}
    # The DENOMINATOR travels with the outcome. `file_findings` reports which
    # findings landed; only this side knows how many were owed an issue, and
    # without that number the reporter below can only trust the failure buckets
    # it happens to know the names of.
    outcome["owed"] = len(findings)
    return outcome


# Buckets that mean "the board HAS this finding". Everything owed and not in one
# of these counts as unfiled. An ALLOWLIST on purpose (PR #19 review, major):
# `file_findings` grows buckets -- ASK-204 added `updated`, `reopened`, `relisted`
# and `errors` -- and a reporter that names FAILURE buckets goes silently dark the
# first time a new one lands upstream. That is exactly how a refused Linear write
# came to print byte-for-byte like a clean run here. A new bucket now has to be
# declared landed before it stops being counted as unfiled.
LANDED_BUCKETS = ("created", "existing", "updated", "reopened", "relisted")


def unfiled_count(outcome):
    """How many findings were OWED an issue and did not get one.

    Falls back to `skipped_no_key` when the outcome carries no `owed` -- an
    outcome built by hand or by an older copy of this pair mid-`kipi update`
    degrades to the pre-fix number rather than to a wrong one.
    """
    fallback = outcome.get("skipped_no_key", 0)
    if "owed" not in outcome:
        return fallback
    landed = sum(outcome.get(bucket, 0) for bucket in LANDED_BUCKETS)
    return max(outcome["owed"] - landed, fallback)


def linear_report_line(outcome, dry_run):
    """The filing result as one line that cannot lie by omission.

    Scar (ASK-181 review): the old line printed `created` and `existing` only.
    `file_findings` catches its own network errors and returns
    {created: 0, existing: 0, skipped_no_key: N}, so 'Linear is unreachable and N
    findings went nowhere' printed byte-identically to 'the fleet is clean, nothing
    to file'. Every instance without a Linear API key takes that branch, and this
    script ships fleet-wide. `unfiled` is what separates empty from broken.

    Second scar (PR #19 review): `unfiled` read ONE bucket by name. When ASK-204
    taught `file_findings` to catch a per-finding write failure and return it as
    `errors` instead of raising, this line went silent on the exact failure the
    first scar was about. It now reads owed-minus-landed (`unfiled_count`), so the
    number cannot be defeated by a bucket added upstream.

    This stays a SEPARATE formatter from fleet-health-daily's `outcome_line`: this
    script has to be able to report that fleet-health-daily.py is missing, which is
    the rsync --delete scar it was built for. It cannot import its own reporter
    from the file whose absence it reports. Both are pinned by tests."""
    verb = "would-file" if dry_run else "filed"
    prefix = "[dry] " if dry_run else ""
    return (f"{prefix}linear: {verb}={outcome['created']} "
            f"already-tracked={outcome['existing']} unfiled={unfiled_count(outcome)}")


_INTENT = None


def _intent_module():
    """Lazily load launchd-intent-verify.py (sp-2c7e5819). Same importlib shape as
    _fleet_health: loaded on demand, and its absence cannot stop the watchdog."""
    global _INTENT
    if _INTENT is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "iv", HERE / "launchd-intent-verify.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _INTENT = module
    return _INTENT


def run_intent_check(dry_run):
    """Verify declared intent against launchd's override DB; print, ping, file.

    Never raises. A watchdog that dies because the intent manifest is malformed
    stops watching launchd, which is the silent death it exists to catch -- the
    same contract `file_linear_findings` keeps for Linear.

    The result is REPORTED even when it could not run. An intent verifier that
    fails to parse `launchctl print-disabled` and prints nothing is
    indistinguishable from one that found no drift, and the second reading is the
    one a reader defaults to (the `unfiled=` scar on `linear_report_line`, ASK-181).
    """
    try:
        intent = _intent_module()
    except Exception as exc:  # noqa: BLE001
        print(f"intent verification unavailable: {exc}", file=sys.stderr)
        return
    try:
        findings, due, (declared, total), commit = intent.check(dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"intent verification COULD NOT RUN: {exc}", file=sys.stderr)
        return

    for label, kind, detail in findings:
        print(f"INTENT-{kind.upper()}: {label} -- {detail}")
    print(f"intent coverage: {declared}/{total} installed jobs declared")

    # `commit` records the consecutive-run counts and is deliberately called
    # AFTER delivery on every path that has one. Recording first meant a crash
    # between the write and send_ping suppressed an alert that was never sent
    # (see check()'s docstring). Nothing to deliver commits immediately: the
    # counts still have to advance for a job that stopped drifting.
    if not due:
        commit()
        return
    if dry_run:
        print(f"[dry] would ping intent drift for {len(due)} job(s)")
        commit()  # a no-op in dry mode; called so the paths stay symmetrical
        return

    drift = [(label, kind, detail) for label, kind, detail, _ in due]
    try:
        outcome = _fleet_health().file_findings(
            intent.linear_findings(drift, _fleet_health().finding_key),
            apply=True, filer="launchd-intent-verify.py")
        unfiled = max(len(drift) - sum(outcome.get(b, 0) for b in LANDED_BUCKETS), 0)
    except Exception as exc:  # noqa: BLE001
        print(f"intent findings NOT filed to Linear: {exc}", file=sys.stderr)
        unfiled = len(drift)

    message = intent.ping_message(due)
    if unfiled:
        message += f" [NOT filed to Linear: {unfiled}]"
    landed = max(len(drift) - unfiled, 0)
    delivered = send_ping(message)

    # Deliver-then-record is only half the contract. The other half is that
    # "delivered" has to be TRUE. Scar (PR #134 review, major): commit() ran
    # unconditionally, so a run where Linear filed nothing AND no webhook was
    # configured still advanced the consecutive-run counts. Measured on the
    # shipped code: runs=1 persisted with nothing sent, and runs 2 through 13
    # were silent -- the next page came only at run 14, because ping_decision
    # re-alerts at 1 and at multiples of REPEAT_EVERY_RUNS and at nothing else.
    # A phantom receipt for an undelivered alert is the exact failure this whole
    # verifier exists to catch, one layer up.
    #
    # The refusal itself now lives in check()'s commit(), the single writer of
    # the state file (PR #134 round 4: the same class came back through main(),
    # which had its own copy of the ordering rule and got it wrong). What this
    # caller owns is the part the writer cannot see -- WHICH channel failed --
    # so it reports that and hands the writer a truthful verdict.
    if not (landed or delivered):
        print(f"intent alert NOT delivered (linear=0, slack=not delivered) -- "
              f"run counts NOT recorded, the next run re-alerts "
              f"{len(drift)} job(s)", file=sys.stderr)
    commit(delivered=bool(landed or delivered))


def problems_to_ping(problems, state, now):
    """Problems whose kind changed since the last ping, or whose last ping is
    older than the TTL (dedupe spam, but re-ping when failing -> not_loaded)."""
    due = []
    for label, kind, detail in problems:
        # A deliberately paused job is never a ping. It is still returned by
        # discover_problems so it prints and stays visible; it just does not
        # reach the founder's phone. Silencing it here rather than dropping it
        # earlier keeps "paused" auditable instead of invisible.
        if kind == "paused":
            continue
        prev = state.get(label, {})
        kind_changed = prev.get("kind") != kind
        last_pinged = prev.get("pinged_at", 0)
        if kind_changed or now - last_pinged >= FAIL_PING_TTL_SECONDS:
            due.append((label, kind, detail))
    return due


def run(dry_run):
    # BEFORE the early return below, not after. `problems` is empty exactly when
    # every watched job is loaded and healthy -- which is the state a job running
    # against an explicit pause decision produces. Wiring the intent check after
    # the `if not problems: return` would make it dead on the only fleet state it
    # exists to judge.
    run_intent_check(dry_run)

    problems = discover_problems()

    if not problems:
        if dry_run:
            print("all watched launchd jobs healthy (loaded, exit 0)")
        elif STATE_FILE.exists():
            write_state({})  # everything recovered; clear ping history
        return

    for label, kind, detail in problems:
        print(f"{kind.upper()}: {label} -- {detail}")

    state = load_state()
    now = int(time.time())
    due = problems_to_ping(problems, state, now)

    # ONE filer for both modes. Dry used to count the findings it built while live
    # counted what survived dedup, so the dry preview of a permanent action
    # over-reported (review finding 2). Two readers of one input is the defect.
    filed = file_linear_findings(problems, apply=not dry_run)
    print(linear_report_line(filed, dry_run))

    if dry_run:
        print(f"[dry] would ping {len(due)} job(s)")
        return

    if due:
        parts = [
            f"{label} (installed but NOT running)" if kind == "not_loaded"
            else f"{label} ({detail})"
            for label, kind, detail in due
        ]
        message = f"launchd watchdog: {len(due)} job issue(s) -- " + ", ".join(parts)
        if unfiled_count(filed):
            # Slack is the only channel the founder actually reads. Fixing the
            # stdout counter alone would leave this ping saying "here are the
            # problems" while the issues meant to hold them never reached the
            # board. No NEW ping: the one that was already firing carries it.
            message += f" [NOT filed to Linear: {unfiled_count(filed)}]"
        send_ping(message)
        for label, kind, detail in due:
            state[label] = {"pinged_at": now, "kind": kind, "detail": detail}

    problem_labels = {label for label, _, _ in problems}
    for label in [k for k in state if k not in problem_labels]:
        state.pop(label)  # recovered since last run

    write_state(state)


def main(argv):
    """Always returns 0 -- a watchdog must never report itself as the failing job.

    Scar (ASK-181 review): this used to be `try: run(...) finally: sys.exit(0)`.
    `sys.exit` in the finally supersedes a propagating exception, so an unhandled
    crash printed NOTHING and launchd recorded SUCCESS. Exiting 0 is the contract;
    exiting 0 SILENTLY is the watchdog dying the same silent death it exists to
    catch. Catch, print the traceback, then exit 0."""
    mode, unrecognized = parse_mode(argv)
    if mode == "refuse":
        print(f"unrecognized flag(s): {' '.join(unrecognized)} -- refusing to run. "
              f"Dry: {' / '.join(DRY_FLAGS)}. Live: no flags at all.", file=sys.stderr)
        return 0
    try:
        run(mode == "dry")
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
