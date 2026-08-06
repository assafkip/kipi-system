#!/usr/bin/env python3
"""Verify that every launchd job's paused/running state matches a DECLARED intent.

The gap this closes (sp-2c7e5819, measured 2026-08-06): nothing anywhere asserted
that the enabled set matches the intended set. `launchd-health-check.py` catches a
job that is FAILING or DARK, and it reads the pause ledger only to SUPPRESS a ping
for a job that is intentionally dark. That makes the ledger a one-way silencer:

    discover_problems() appends only when job_status() is 'failing' or
    'not_loaded'. A label the ledger declares paused, which is actually loaded and
    healthy, returns ('ok', 0) and produces NOTHING.

Reproduced by executing that function, not by reading it: with one paused-ledger
label and job_status stubbed to ('ok', 0), `discover_problems()` returned `[]`.
So "this job should be stopped and is running" was structurally undetectable, and
"this job is running and should be" was indistinguishable from it -- both are
silence. The only reason anyone noticed the podcast jobs' split state was that a
generated feed dirtied a git tree.

This script supplies the missing half: an intended-state manifest diffed against
the launchd override database (`launchctl print-disabled`), reported in BOTH
directions plus a coverage number.

## Why the override DB and not `launchctl list`

They answer different questions and they disagree. `launchctl list` reports what is
bootstrapped right now; `print-disabled` reports the persistent override record
that survives reboots and is what `launchctl disable` writes. Measured 2026-08-06:
`com.cole.pause-resume` is `=> enabled` in the override DB, exits 113 (not loaded)
from `launchctl list`, and has no plist on disk at all. Intent is a statement about
the persistent record, so the persistent record is what it is checked against.

## Where the manifest lives, and why not in this repo

`~/.config/kipi/launchd-intent.json`, in the founder's live env, NOT in the
skeleton -- the same placement as `launchd-watch-prefixes.txt` and the pause
ledger, for the same stated reason: this script propagates fleet-wide via
`kipi update` and must carry no single instance's brand names. The repo ships the
verifier; the machine holds the data.

Usage:
  launchd-intent-verify.py            # check, print, exit 0
  launchd-intent-verify.py --dry      # same, but never writes the state file
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

INTENT_MANIFEST = Path.home() / ".config" / "kipi" / "launchd-intent.json"
STATE_FILE = Path.home() / ".config" / "kipi" / "launchd-intent-state.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"

# The pause ledgers `launchd-health-check.py` already reads. Treated here as an
# IMPLICIT "intent: disabled" for every label they list, so this verifier works on
# day one against the ledger that already exists -- no migration, and no job
# touched. An explicit manifest entry overrides a ledger line, and the
# disagreement is reported rather than silently resolved.
LEGACY_PAUSED_FILES = (
    Path.home() / ".config" / "kipi" / "launchd-paused.txt",
    Path.home() / ".config" / "kipi" / "cole-pause.state",
)

ENABLED = "enabled"
DISABLED = "disabled"

# `launchctl print-disabled` vocabulary. Measured on Darwin 25.3.0 (2026-08-06) as
# `"<label>" => disabled` / `=> enabled`; older macOS prints `=> true` / `=> false`.
# Both are accepted. An UNRECOGNISED token is refused rather than guessed -- see
# parse_print_disabled for why a silent default here is the dangerous branch.
DISABLED_TOKENS = frozenset({"disabled", "true", "1"})
ENABLED_TOKENS = frozenset({"enabled", "false", "0"})

_ENTRY_RE = re.compile(r'"(?P<label>[^"]+)"\s*=>\s*(?P<value>[^\s;,}]+)')

# Findings that reach the founder's phone. `undeclared` and `orphan` are printed
# and counted but never pinged: they are manifest hygiene, and 40 of them exist on
# day one (65 watched plists, 25 declared). Paging on coverage is the alert-fatigue
# mechanism that teaches the founder to ignore this channel.
PINGABLE_KINDS = ("running_but_paused", "paused_but_intended_running")

# Re-ping a still-drifting job every Nth CONSECUTIVE run, counted by this script.
#
# Scar (ASK-283 alert audit, 2026-08-02): the sibling watchdog guards its re-ping
# with FAIL_PING_TTL_SECONDS = 6h while its installed plist runs at 09:30 and
# 21:30 -- 12h apart. The window can never elapse-check to False, so it suppresses
# nothing and reads as protection. A wall-clock window has to be re-checked against
# the schedule every time either one moves. A run COUNTER cannot drift out of sync
# with the schedule, because the schedule is the only thing that increments it.
# At the current 2 runs/day this is one re-ping per week.
REPEAT_EVERY_RUNS = 14


class IntentError(Exception):
    """The verifier could not establish ground truth and must not report 'clean'."""


# --- reading the override database -------------------------------------------

def parse_print_disabled(text):
    """`launchctl print-disabled` output -> {label: 'enabled'|'disabled'}.

    Raises IntentError when the output has the shape of a real answer but nothing
    parsed, or when a value token is unrecognised.

    Why it refuses instead of returning {}: an empty override map means "no label
    has an override", and `effective_state` correctly reads that as everything
    being ENABLED. So a parser that silently fails on a future macOS format change
    would flip every intended-paused job into a `running_but_paused` finding at
    once -- 25 of them on this machine today -- and page the founder about a job
    nobody touched. The failure mode of a silent parse miss here is a false alarm
    storm, which is worse than the outage it would be reporting.
    """
    entries = {}
    unknown = []
    for match in _ENTRY_RE.finditer(text):
        value = match.group("value").strip().lower()
        if value in DISABLED_TOKENS:
            entries[match.group("label")] = DISABLED
        elif value in ENABLED_TOKENS:
            entries[match.group("label")] = ENABLED
        else:
            unknown.append(f'{match.group("label")} => {match.group("value")}')
    if unknown:
        raise IntentError(
            "unrecognised print-disabled value(s): " + ", ".join(sorted(unknown)[:5])
        )
    if not entries and "disabled services" in text:
        raise IntentError("print-disabled produced a services block but no entries parsed")
    return entries


def effective_state(label, overrides):
    """The override DB's answer for one label.

    A label ABSENT from print-disabled is not unknown -- it has no override
    recorded, and launchd runs it. Measured 2026-08-06: 65 watched plists on disk,
    32 labels present in print-disabled, so absence is the common case and
    treating it as 'unknown' would leave two thirds of the fleet unverified.
    """
    return overrides.get(label, ENABLED)


# --- reading declared intent --------------------------------------------------

def load_intent(manifest_text=None, paused_texts=()):
    """Resolve declared intent from the manifest plus the legacy pause ledgers.

    ONE reader for both sources on purpose. Two call-sites each resolving intent
    their own way is how the pause ledger became a suppression list in one place
    and a source of truth in another.

    Returns (intent, conflicts). `conflicts` names every label the manifest and a
    ledger disagree about; the manifest wins (explicit beats implicit) and the
    disagreement is surfaced, never silently resolved.
    """
    ledger = set()
    for text in paused_texts:
        for line in text.splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                ledger.add(entry)

    declared = {}
    if manifest_text:
        try:
            data = json.loads(manifest_text)
        except json.JSONDecodeError as exc:
            raise IntentError(f"launchd-intent.json is not valid JSON: {exc}") from exc
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise IntentError("launchd-intent.json has no 'jobs' list")
        for row in jobs:
            label = (row or {}).get("label")
            intent = (row or {}).get("intent")
            if not label:
                raise IntentError("a launchd-intent.json job row has no 'label'")
            if intent not in (ENABLED, DISABLED):
                raise IntentError(
                    f"{label}: intent must be {ENABLED!r} or {DISABLED!r}, got {intent!r}"
                )
            declared[label] = intent

    conflicts = sorted(
        label for label in ledger
        if declared.get(label) == ENABLED
    )
    intent = {label: DISABLED for label in ledger}
    intent.update(declared)
    return intent, conflicts


# --- the diff -----------------------------------------------------------------

def diff_intent(intent, overrides, installed_labels):
    """(label, kind, detail) for every disagreement between intent and reality.

    kinds:
      running_but_paused          declared disabled, override DB says enabled.
                                  THE DIRECTION NOTHING ELSE SEES -- the sibling
                                  watchdog reports nothing at all for a healthy job.
      paused_but_intended_running declared enabled, override DB says disabled.
      orphan                      declared, but no plist on disk. A manifest line
                                  about a job that no longer exists.
      undeclared                  plist on disk, no intent recorded. Coverage, not
                                  drift; never pinged.
    """
    findings = []
    for label in sorted(intent):
        want = intent[label]
        installed = label in installed_labels
        actual = effective_state(label, overrides)
        # No plist on disk settles it ALONE. An override row is a statement about
        # the override database, never evidence that anything is running -- there
        # is nothing left to run. It is surfaced in the detail, not in the kind.
        #
        # Scar (measured 2026-08-06, found by populating intent from the real
        # 2026-08-01 jobs audit instead of a synthetic manifest): this guard read
        # `not installed and label not in overrides`. The audit retired
        # com.kipi.fractional-cxo.opp-scan by renaming its plist, but launchd kept
        # `"com.kipi.fractional-cxo.opp-scan" => enabled`. The second clause was
        # False, so the label fell through to the drift branch below and paged
        # running_but_paused for a job with no executable. Its sibling
        # bolt-on-discovery, retired the same way but with no leftover row, was
        # classified correctly -- the two differed only by the stale row.
        #
        # Third instance of one class: a signal read on only one side of a branch.
        # 4f6bf61f (ASK-113) nested the pause-ledger read INSIDE the not_loaded
        # arm, whose own scar was 26 false pings for jobs the founder had
        # deliberately stopped. Same shape, same harm: the guard exists, the
        # compound condition stops the path from reaching it.
        if not installed:
            detail = f"declared {want}, no plist and no override"
            if label in overrides:
                detail = (
                    f"declared {want}, no plist; "
                    f"stale override row says {overrides[label]}"
                )
            findings.append((label, "orphan", detail))
            continue
        if want == actual:
            continue
        kind = "running_but_paused" if want == DISABLED else "paused_but_intended_running"
        findings.append((label, kind, f"declared {want}, launchd says {actual}"))
    for label in sorted(installed_labels - set(intent)):
        findings.append((label, "undeclared", "no declared intent"))
    return findings


def coverage(intent, installed_labels):
    """(declared_and_installed, installed). Printed on every run.

    Without this number a manifest covering 25 of 65 jobs reports "no drift" and
    reads exactly like full verification. The count is the difference between
    "nothing is wrong" and "nothing that is checked is wrong".
    """
    return (len(installed_labels & set(intent)), len(installed_labels))


# --- alerting -----------------------------------------------------------------

def ping_decision(findings, state):
    """(due, new_state). Ping the TRANSITION into drift, not the drift.

    A label is due when its kind changed since the last run (a new bad state), or
    when it has now been in that same bad state for a multiple of
    REPEAT_EVERY_RUNS consecutive runs. Each due entry carries its consecutive-run
    count so the message says how long, per founder-notifications.md: repeating an
    unchanged state every cycle is noise, not a ping.
    """
    new_state = {}
    due = []
    for label, kind, detail in findings:
        if kind not in PINGABLE_KINDS:
            continue
        prev = state.get(label) or {}
        runs = prev.get("runs", 0) + 1 if prev.get("kind") == kind else 1
        new_state[label] = {"kind": kind, "runs": runs, "detail": detail}
        if runs == 1 or runs % REPEAT_EVERY_RUNS == 0:
            due.append((label, kind, detail, runs))
    return due, new_state


def ping_message(due):
    """One Slack line for the whole run. One ping per run, never one per finding."""
    parts = []
    for label, kind, detail, runs in due:
        what = ("running but declared paused" if kind == "running_but_paused"
                else "paused but declared running")
        age = "new" if runs == 1 else f"{runs} runs"
        parts.append(f"{label} ({what}, {age})")
    return f"launchd intent drift: {len(due)} job(s) -- " + ", ".join(parts)


# --- Linear rendering ---------------------------------------------------------
# Built here rather than in fleet-health-daily.py's `launchd_finding`: that
# function is an if-chain that RAISES on an unknown detector id, on purpose, so a
# caller cannot file an empty body under a key the other filer also writes. Adding
# a branch there would put this script's rendering inside the file whose own
# absence the sibling watchdog has to be able to report. `file_findings` takes
# plain dicts, so the seam that does not require that coupling is the dict.
LINEAR_DETECTOR = "launchd-intent-drift"

_LINEAR_BODY = {
    "running_but_paused": (
        "`{label}` is declared **disabled** in `~/.config/kipi/launchd-intent.json` "
        "(or the pause ledger) but launchd's override database reports it "
        "**enabled**, so it is running.\n\n"
        "Nothing else in the fleet detects this direction: the launchd watchdog "
        "reports only failing and dark jobs, and a healthy job produces silence.\n\n"
        "## Action\n"
        "- If running is correct, change this label's intent to `enabled` with a reason.\n"
        "- If the pause was intended: `launchctl disable gui/$(id -u)/{label}`"
    ),
    "paused_but_intended_running": (
        "`{label}` is declared **enabled** but launchd's override database reports "
        "it **disabled**, so it has silently stopped running.\n\n"
        "## Action\n"
        "- Resume: `launchctl enable gui/$(id -u)/{label}`\n"
        "- Or record the decision by setting this label's intent to `disabled`."
    ),
}


def linear_findings(findings, finding_key):
    """Finding dicts ready for fleet-health-daily.file_findings, pingable kinds only."""
    out = []
    for label, kind, detail in findings:
        body = _LINEAR_BODY.get(kind)
        if body is None:
            continue
        out.append({
            "subject": label,
            "title": f"launchd intent drift: {label} ({detail})",
            "body": body.format(label=label),
            "key": finding_key(LINEAR_DETECTOR, label),
            "detector": LINEAR_DETECTOR,
        })
    return out


# --- I/O edges ----------------------------------------------------------------

def read_text(path):
    try:
        return path.read_text()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return ""


def installed_labels():
    return {p.stem for p in LAUNCH_AGENTS.glob("*.plist")}


def read_overrides(runner=None):
    """The override DB. `runner` is injected by tests so nothing shells launchctl."""
    if runner is None:
        import subprocess

        def runner():
            import os
            return subprocess.run(
                ["launchctl", "print-disabled", f"gui/{os.getuid()}"],
                capture_output=True, text=True, timeout=20,
            ).stdout
    return parse_print_disabled(runner())


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001 - a missing/corrupt state file is a fresh start
        return {}


def write_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def check(dry_run=False, overrides=None, labels=None):
    """Run the verification. Returns (findings, due, coverage_tuple).

    Raises IntentError when ground truth could not be established -- the caller
    must report that as a broken check, never as a clean one.
    """
    intent, conflicts = load_intent(
        read_text(INTENT_MANIFEST),
        [read_text(p) for p in LEGACY_PAUSED_FILES],
    )
    if overrides is None:
        overrides = read_overrides()
    if labels is None:
        labels = installed_labels()
    findings = diff_intent(intent, overrides, labels)
    due, new_state = ping_decision(findings, load_state())
    if not dry_run:
        write_state(new_state)
    for label in conflicts:
        findings.append((label, "conflict", "manifest says enabled, pause ledger lists it"))
    return findings, due, coverage(intent, labels)


def main(argv):
    dry = any(a in ("--dry", "--dry-run", "-n") for a in argv)
    unrecognized = [a for a in argv if a not in ("--dry", "--dry-run", "-n")]
    if unrecognized:
        print(f"unrecognised flag(s): {' '.join(unrecognized)} -- refusing to run.")
        return 0
    try:
        findings, due, (declared, total) = check(dry_run=dry)
    except IntentError as exc:
        print(f"launchd intent verification COULD NOT RUN: {exc}")
        return 0
    for label, kind, detail in findings:
        print(f"{kind.upper()}: {label} -- {detail}")
    print(f"intent coverage: {declared}/{total} installed jobs declared")
    print(f"would ping: {len(due)}" if dry else f"ping-worthy: {len(due)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
