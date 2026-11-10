#!/usr/bin/env python3
"""Which registered instances lose voice-stop-gate behaviour on the next sync.

ASK-1304, promoted from sp-0b8bec0d (source ASK-1197). `kipi update` rsyncs the
skeleton's q-system/ over every instance, so an instance copy of
voice-stop-gate.py carrying behaviour the skeleton never had is DESTROYED by the
next sync. That happened twice in one afternoon on 2026-09-06 (sp-745f5962,
sp-1ad08728): the instance's pre-commit went red, the restore was undone by the
following sync, and the only check lived in a test that skips wherever the 25
instance clones are absent. CI holds the scanner via synthetic trees; this runner
is what executes it against the real fleet, on a schedule, and fails loudly.

## The AHEAD / BEHIND split is the whole design

A digest mismatch alone is not loss. An instance holding an OLDER skeleton
version is BEHIND and the next sync fixes it, which is the normal state of a
fleet between syncs. Only content the skeleton NEVER SHIPPED is destroyed.
Calling every mismatch red would make this runner red on a healthy fleet, and a
gate red on its own population gets switched off (the same call
`voice-loop-anywhere.md` and `coding-audhd.md` already made).

"SHIPPED" IS THE FAN-OUT BRANCH, NOT EVERY REF IN THE CLONE. The first version
of `_skeleton_ever_had` walked `git log --all`, which is the exact boundary
`kipi-update.sh` was tightened to reject on #151 round 7 -- a blob that only ever
existed on an unmerged branch was never rsynced to any instance, so an instance
holding it is AHEAD. That is not a corner case: the recorded 2026-09-06 loss
says the port was "still on an open PR" (kipi-update.sh:310), and the live clone
measures 1142 refs, 49 gate blobs reachable from `--all` and 8 from origin/main,
so 41 blobs the old walk waved past were never shipped anywhere (PR #339 review
round 3, major).

The ship ref is not restated here. `_fan_out_ref` executes `fleet_ship_ref` out
of `kipi-update.sh`'s own source, so changing the updater's preference moves this
check's answer with it; a copy of that list would agree today and drift the day
the owner changes (lessons/derive-a-value-from-its-owner). When it cannot be
resolved, a mismatching instance is UNANSWERED, never `behind`: "cannot tell"
must not print as the harmless one.

The two citations of that reporter below name it WITHOUT its `.py`, deliberately.
`test_lessons_drift_report.py::test_single_caller_the_plist_template_is_the_only_one_in_the_tree`
is an exact-set git grep for its filename, and it is correct to be that blunt: a
second caller of a scheduled job is exactly what it exists to catch. A docstring
citing prior art is not a caller, and a grep cannot tell the two apart, so the fix
is to stop tripping it rather than to loosen it (the same call
`engineering_route.py` records against the morning-brief slack-notify grep). Do not
"helpfully" restore the extension; that turns this file into a third caller.

## Where it may ACT

This file sits under the fanned-out scripts directory, so all 25 instances carry
it (lessons/a-fan-out-installer-must-refuse-where-its-job-cannot-run.md). Run in
an instance it would compare the fleet against an instance and report the
skeleton as drifted, so it refuses unless the registry's `skeleton` entry IS its
own root. The plist carries `kipi-scope: skeleton-only` for `--all`.

## Alerting

Red files ONE ticket into Sana's Linear triage through slack-notify.sh, on state
CHANGE only, under KIPI_TRIGGER=launchd (which only the plist sets). A ticket
every run while the fleet stays red is how an alert channel gets muted, and a
muted channel is worse than none (founder-notifications.md). Run by hand it
prints and files nothing, so removing the plist provably stops delivery.
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

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
GATE_REL = "q-system/.q-system/scripts/voice-stop-gate.py"
UPDATER_REL = "kipi-update.sh"
# A LOCAL artifact of the last scan, and the docs say only that. It was
# described as "the manifest CI can lo" + "ad"; it is not, and the string is
# broken here so this note cannot re-seed the grep that pins the claim gone.
# q-system/output/*.json is gitignored, this is written only where the clones
# are, and no reader exists outside the suite (PR #339 review round 3, minor).
# The ALERT is the signal that leaves the machine. Kept anyway: it is what a
# reader opens to see the last run without re-scanning 25 clones.
MANIFEST_REL = "q-system/output/voice-gate-propagation.json"
STATE_REL = "q-system/output/.voice-gate-propagation-state.json"
NOTIFY = os.path.join(HERE, "slack-notify.sh")
COULD_NOT_READ = "COULD NOT READ"
NO_INSTANCES = "no instances in the registry"
NO_FAN_OUT_REF = "the fan-out ref kipi-update.sh ships from"
NO_REF_NOTE = ("cannot say ahead or behind: " + NO_FAN_OUT_REF + " did not resolve")
NO_POPULATION = "the row set kipi-update.sh would sync"
NO_POPULATION_NOTE = ("cannot say which rows a sync reaches: " + NO_POPULATION
                      + " did not resolve")
STALE_ROW_NOTE = ("stale registry row: the path does not exist, so kipi update "
                  "skips it and no sync reaches it")
NOT_SYNCED_NOTE = ("declared not skeleton-managed, so no sync reaches it "
                   "(skeleton_managed: false, standalone, or no subtree_prefix)")
UNDECLARED_NOTE = ("UNDECLARED non-propagating: receives no skeleton propagation "
                   "and nothing on record says that is intended, so kipi update "
                   "FAILS on this row")
NOTIFY_TIMEOUT_S = 20
# slack-notify.sh's OWN exit contract, not ours: "3  nothing to file on: no
# Linear API key configured (a setup state)". A setup state read as a send
# FAILURE made every run on a keyless machine exit 2 forever with no ticket
# (PR #339 review round 3, minor). The number is pinned to that contract by
# test_the_setup_exit_code_is_derived_from_slack_notifys_own_contract.
NOTIFY_UNCONFIGURED_RC = 3


class NotifierUnconfigured(Exception):
    """slack-notify.sh has no Linear key. Nothing was filed and that is not a
    failure to retry-diagnose; it is a machine that was never set up."""


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _bash_function(source: str, name: str) -> str:
    """The literal body of one `name() { ... }` from a shell script, sliced at
    the closing brace in column 0. Empty when it is not there in that shape,
    which the caller treats as unresolvable rather than guessing."""
    start = source.find("\n%s() {\n" % name)
    if start < 0:
        return ""
    end = source.find("\n}\n", start + 1)
    return source[start + 1:end + 2] if end > start else ""


def _fan_out_ref(skel_root: str) -> str:
    """The ref `kipi update` would actually ship FROM, answered by executing
    kipi-update.sh's own `fleet_ship_ref` rather than restating its preference
    order here. "" when it cannot be resolved -- no updater, a renamed function,
    a new global it needs -- and the caller must not read "" as `behind`."""
    try:
        with open(os.path.join(skel_root, UPDATER_REL), encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return ""
    body = _bash_function(source, "fleet_ship_ref")
    branch = re.search(r'^SKELETON_BRANCH="([^"]+)"', source, re.M)
    if not body or not branch:
        return ""
    program = (f"SCRIPT_DIR={shlex.quote(skel_root)}\n"
               f"SKELETON_BRANCH={shlex.quote(branch.group(1))}\n"
               f"{body}\nfleet_ship_ref\n")
    try:
        done = subprocess.run(["bash", "-c", program],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def shipped_blobs(skel_root: str, ref: str):
    """Every blob the skeleton ever SHIPPED for GATE_REL, reachable from `ref`.

    Same algorithm as kipi-update.sh::fleet_authored_blob (walk the ship ref for
    that path, read the blob at each commit), hoisted out of the per-instance
    loop: the answer is a property of the skeleton, not of the instance asking.
    None when git could not answer at all, which is not the same as an empty set.
    """
    if not ref:
        return None
    try:
        walk = subprocess.run(["git", "-C", skel_root, "rev-list", ref, "--", GATE_REL],
                              capture_output=True, text=True, timeout=120)
        if walk.returncode != 0:
            return None
        commits = [c for c in walk.stdout.split() if c]
        if not commits:
            return set()
        batch = subprocess.run(["git", "-C", skel_root, "cat-file",
                                "--batch-check=%(objectname) %(objecttype)"],
                               input="".join(f"{c}:{GATE_REL}\n" for c in commits),
                               capture_output=True, text=True, timeout=120)
        if batch.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return {line.split()[0] for line in batch.stdout.splitlines()
            if line.endswith(" blob")}


def _blob_id(skel_root: str, candidate: str) -> str:
    try:
        done = subprocess.run(["git", "-C", skel_root, "hash-object", candidate],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def resolve(root: str) -> bool:
    """Is `root` the checkout the registry calls the skeleton?

    The RAW skeleton value is checked before realpath, because realpath("") is
    the cwd and would pass whenever this ran from its own root (the same hole
    Codex found in the lessons-drift reporter, issue 13).

    It no longer returns the instance rows. Reading `name` and `path` straight
    out of the registry was the PR #726 review's major and minor together: the
    registry is a LEDGER of instances, not the list of directories a sync
    reaches, and those are different sets. `registry_rows` asks the owner.
    """
    root = os.path.realpath(root)
    try:
        with open(os.path.join(root, "instance-registry.json"), encoding="utf-8") as fh:
            registry = json.load(fh)
    except (OSError, ValueError):
        return False
    raw = (registry.get("skeleton") or {}).get("path")
    return isinstance(raw, str) and bool(raw.strip()) and os.path.realpath(raw) == root


def _registry_feed(source: str) -> str:
    """The literal `python3 -c "..."` block kipi-update.sh feeds its own instance
    loop from, sliced out of its source. Empty when it is not in that shape,
    which the caller treats as unresolvable rather than guessing."""
    start = source.find('done < <(python3 -c "')
    if start < 0:
        return ""
    end = source.find('\n")\n', start)
    if end < 0:
        return ""
    return source[start + len("done < <("):end + 2]


def registry_rows(root: str):
    """The instance rows `kipi update` ITSELF would iterate, or None.

    Derived, not restated (lessons/derive-a-value-from-its-owner). Four rules
    decide what a registry row even means -- the default `type`, the
    `subtree_prefix or ''` normalisation, the "only an explicit false counts as
    a declaration" rule, and dropping any row whose `status` starts with
    "merged" -- and all four live in one python block inside kipi-update.sh. A
    copy of them here would agree today and drift the day the owner changes,
    which is the whole shape of the PR #726 review's minor.

    None means the question could not be asked: no updater, a renamed feed, a
    registry the owner itself cannot parse. The caller must not read None as
    "nothing syncs", which is the harmless answer.
    """
    root = os.path.realpath(root)
    try:
        with open(os.path.join(root, UPDATER_REL), encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return None
    feed = _registry_feed(source)
    if not feed:
        return None
    registry = os.path.join(root, "instance-registry.json")
    program = f"REGISTRY={shlex.quote(registry)}\n{feed}\n"
    try:
        done = subprocess.run(["bash", "-c", program],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0]:
            continue
        rows.append({"name": parts[0], "path": parts[1], "prefix": parts[2],
                     "type": parts[3], "declared": parts[4]})
    return rows


def sync_decision(row: dict) -> tuple:
    """(decision, note): would a `kipi update` run rsync the skeleton over this
    row? `syncs` | `stale-row` | `not-synced` | `undeclared`.

    This mirrors kipi-update.sh's own three pre-sync branches, in its order
    (kipi-update.sh:1629 path, :1649 standalone/no-prefix, :1651 declared vs
    :1653 undeclared). The CONDITIONS are the one part of the decision that
    cannot be sliced and executed -- they are inline in a `while` loop, not a
    function like `fleet_ship_ref` -- so they are a divergence check instead:
    `test_the_owners_three_skip_branches_are_still_the_ones_this_reads` parses
    them out of the updater and goes RED when the owner's text moves. Strictly
    worse than deriving, and it fails loudly rather than passing quietly.

    `undeclared` is red on purpose and is NOT a skip for the owner either: the
    updater counts that row as a FAIL, so it is the one row whose fan-out is
    already broken (ASK-117). Handing it the quiet answer would be the defect.
    """
    if not row["path"] or not os.path.isdir(row["path"]):
        return "stale-row", STALE_ROW_NOTE
    if row["type"] == "standalone" or not row["prefix"]:
        if row["declared"] == "declared":
            return "not-synced", NOT_SYNCED_NOTE
        return "undeclared", UNDECLARED_NOTE
    return "syncs", ""


def classify(instance_root: str, skel_root: str, shipped=None) -> tuple:
    """(state, note) for one instance: synced | behind | ahead | could-not-read.

    `shipped` is the set from shipped_blobs(), passed in rather than recomputed:
    it is one answer about the skeleton, not 25 answers about the instances.
    None means the ship ref never resolved, and then a MISMATCH is unanswered --
    the one thing this file may never do is call an unknown instance `behind`.
    """
    skel_gate = os.path.join(skel_root, GATE_REL)
    inst_gate = os.path.join(instance_root or "", GATE_REL)
    if not os.path.isfile(skel_gate):
        return "could-not-read", f"the skeleton has no {GATE_REL}"
    if not instance_root or not os.path.isfile(inst_gate):
        return "could-not-read", f"no {GATE_REL} at {instance_root or '(no path)'}"
    try:
        same = _digest(inst_gate) == _digest(skel_gate)
    except OSError as exc:
        return "could-not-read", str(exc)
    if same:
        return "synced", ""
    if shipped is None:
        return "could-not-read", NO_REF_NOTE
    blob = _blob_id(skel_root, inst_gate)
    if not blob:
        return "could-not-read", f"git could not hash {inst_gate}"
    if blob in shipped:
        return "behind", "an older skeleton version; the next sync fixes it"
    return "ahead", "content the skeleton never shipped; the next sync DESTROYS it"


def scan(root: str) -> dict:
    """The report. Pure enough for a test to read without a subprocess."""
    root = os.path.realpath(root)
    skeleton_ok = resolve(root)
    population = registry_rows(root) if skeleton_ok else None
    rows, excluded_rows = [], []
    shipped = shipped_blobs(root, _fan_out_ref(root)) if skeleton_ok else None
    for row in population or []:
        decision, note = sync_decision(row)
        if decision != "syncs":
            # NOT judged, and NOT dropped. A row no sync reaches cannot lose
            # content to a sync, so it is not the fanout-loss hazard -- but 8 of
            # the live fleet's 22 rows are in this bucket, and a report that
            # stopped mentioning them would read as "22 instances clean".
            excluded_rows.append(dict(row, state=decision, note=note))
            continue
        state, classify_note = classify(row["path"], root, shipped)
        rows.append({"name": row["name"], "path": row["path"],
                     "state": state, "note": classify_note})
    ahead = [r["name"] for r in rows if r["state"] == "ahead"]
    unanswered = [r["name"] for r in rows if r["state"] == "could-not-read"]
    undeclared = [r["name"] for r in excluded_rows if r["state"] == "undeclared"]
    excluded = {}
    for row in excluded_rows:
        if row["state"] != "undeclared":
            excluded.setdefault(row["state"], []).append(row["name"])
    # The population question, like the ship-ref question, has an answer this
    # run may fail to get. "Could not ask which rows a sync reaches" must not
    # print as "no row loses anything": without it every stale row would be
    # silently called stale on a run that never consulted the owner.
    if skeleton_ok and population is None:
        unanswered = [NO_POPULATION] + unanswered
    # The CAUSE leads its own rows. An unresolvable ship ref turns every
    # mismatching instance into an identical `cannot say`, and a title reading
    # "RED UNANSWERED: a, b, c" names the symptom in 25 places and the reason in
    # none. Only when it actually bit something: an all-synced fleet was fully
    # answered, and a sentinel there would be a red with nothing behind it.
    if any(r["note"] == NO_REF_NOTE for r in rows):
        unanswered = [NO_FAN_OUT_REF] + unanswered
    # A registry this run could PARSE but out of which NO row is a sync
    # destination scanned nothing, and nothing has the same bytes as a healthy
    # fleet (lessons/zero-selected-items-is-a-failure-not-a-pass.md). Zero and
    # never-ran must not both print green. It is the SYNCED population that has
    # to be non-empty, not the registry's row count: a registry whose every row
    # is stale answers the question for no instance at all.
    if skeleton_ok and population is not None and not rows:
        unanswered = [NO_INSTANCES]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skeleton": root,
        "skeleton_ok": skeleton_ok,
        "instances": rows,
        "excluded": excluded,
        "excluded_rows": excluded_rows,
        "ahead": ahead,
        "unanswered": unanswered,
        "undeclared": undeclared,
        # THREE ways to be red, and the middle one is the PR #339 review's major:
        # an instance whose gate file could not be read is UNKNOWN, never synced.
        # An instance that is genuinely ahead AND unreadable at 06:30 used to
        # score exit 0 with fingerprint `green`, so the branch this file's own
        # docstring promised was never silently green was exactly the one that
        # was. A root that is not the skeleton is the same defect one level up:
        # it ran somewhere it cannot answer the question, which is not the same
        # answer as "no drift found".
        #
        # What is NOT red, as of the PR #726 review's major: a row no sync
        # reaches. 8 of the live fleet's 22 rows point at directories deleted
        # months ago, so every one of them scored `could-not-read` and this job
        # would have exited 2 at 06:30 daily forever, with launchd-health
        # re-pinging Sana every 6 hours (launchd-health-check.py:47). A gate red
        # on its own population gets switched off, and then it protects nothing.
        # Those rows stay NAMED and COUNTED in the message instead.
        "red": bool(ahead) or bool(unanswered) or bool(undeclared) or not skeleton_ok,
    }


def render(report: dict) -> str:
    """The summary leads, before the per-instance rows.

    `alert-to-linear.py::title_for` flattens this to one line and truncates it,
    so a RED line printed after 25 `name: synced` rows gave Sana a ticket titled
    "X: synced Y: synced..." and never named the instance that is losing
    behaviour (PR #339 review, minor). The NAMES come first inside the summary
    for the same reason: truncation eats the tail.
    """
    day = report["generated_at"][:10]
    lines = [f"voice-stop-gate propagation ({day})"]
    if not report["skeleton_ok"]:
        lines.append(f"skeleton: {COULD_NOT_READ} (the registry's skeleton entry is not "
                     f"this checkout: {report['skeleton']})")
        return "\n".join(lines)
    if report["ahead"]:
        lines.append(f"RED AHEAD: {', '.join(report['ahead'])} -- "
                     "lose behaviour on the next sync")
    if report["unanswered"]:
        lines.append(f"RED UNANSWERED: {', '.join(report['unanswered'])} -- "
                     "not scanned, so not known to be safe")
    if report["undeclared"]:
        lines.append(f"RED UNDECLARED: {', '.join(report['undeclared'])} -- "
                     "receives no skeleton propagation and nothing says that is "
                     "intended, so kipi update fails on it")
    # The rows this check EXCLUDED, counted. They are not red -- no sync reaches
    # them, so no sync destroys anything in them -- and dropping them from the
    # exit code must not drop them from the report too, or the next reader sees
    # "no drift" over a registry a third of which points at nothing.
    for state, label in (("stale-row", "stale registry row"),
                         ("not-synced", "row declared not skeleton-managed")):
        names = report["excluded"].get(state) or []
        if names:
            lines.append(f"{len(names)} {label}{'s' if len(names) != 1 else ''}, "
                         f"excluded (no sync reaches them): {', '.join(names)}")
    for row in report["instances"]:
        if row["state"] == "could-not-read":
            lines.append(f"{row['name']}: {COULD_NOT_READ} ({row['note']})")
        elif row["state"] == "ahead":
            lines.append(f"{row['name']}: AHEAD -- {row['note']}")
        else:
            lines.append(f"{row['name']}: {row['state']}"
                         + (f" ({row['note']})" if row["note"] else ""))
    return "\n".join(lines)


def fingerprint(report: dict) -> str:
    """What counts as a STATE for 'alert once on state change'. The set of ahead
    instances, not the whole report: a new `generated_at` every run would make
    every run a state change, which is the muted-channel failure wearing the
    shape of a fix."""
    if not report["skeleton_ok"]:
        return "skeleton-unreadable"
    parts = []
    if report["ahead"]:
        parts.append("ahead:" + ",".join(sorted(report["ahead"])))
    # the unanswered set belongs to the STATE, not only to the exit code: left
    # out, a newly-unreadable instance either never alerts or alerts on every
    # run, and a channel repeating an unchanged condition stops being read.
    if report["unanswered"]:
        parts.append("unanswered:" + ",".join(sorted(report["unanswered"])))
    if report["undeclared"]:
        parts.append("undeclared:" + ",".join(sorted(report["undeclared"])))
    # The EXCLUDED sets are deliberately not part of the state. They are not
    # red, so they file no ticket, so a change in them has no alert to fire
    # once. A new stale row appearing is registry hygiene, which is
    # kipi-update.sh's own "SKIP: path does not exist" line to report and not
    # this job's; folding it in here would restore the muted channel this
    # round removed, one indirection further out.
    return "|".join(parts) if parts else "green"


def _send(message: str) -> None:
    """Raise when nothing was filed. An absent notifier is a legitimate no-op on
    an unconfigured machine and still is NOT a filing -- returning None there is
    the write-only-integration defect engineering_route.py::send documents."""
    if not os.path.isfile(NOTIFY):
        raise FileNotFoundError(f"no notifier at {NOTIFY}; nothing was filed")
    done = subprocess.run(["bash", NOTIFY, message], check=False,
                          capture_output=True, timeout=NOTIFY_TIMEOUT_S)
    if done.returncode == NOTIFY_UNCONFIGURED_RC:
        raise NotifierUnconfigured(f"slack-notify.sh exited {NOTIFY_UNCONFIGURED_RC}: "
                                   "no Linear API key configured")
    if done.returncode != 0:
        raise RuntimeError(f"slack-notify.sh exited {done.returncode}: "
                           f"{(done.stderr or b'').decode('utf-8', 'replace')[:300]}")


def _remember(root: str, current: str, report: dict) -> str:
    """The single writer of the state file. Advancing the state is what makes the
    next run quiet, so it happens on exactly two paths -- after a filing, and on
    the first quiet run -- and never after a failed filing.

    Returns "" or the error. It does NOT raise, and the reason is a defect the
    manifest fix above found one layer out: the state file and the manifest live
    in the SAME `q-system/output/`, and this writer ran AFTER the alert had
    already filed. So an unwritable output directory did not merely lose the
    local artifact -- it threw a traceback out of a run that had already sent a
    ticket, left the state unadvanced, and made the next run file the identical
    ticket again, forever. That is the muted-channel failure inverted into an
    alert storm, and it is the one founder-notifications.md calls worse.

    Unlike the manifest, a state write that fails IS an exit-2 condition (see
    main): the once-per-state-change promise is broken while it lasts, and that
    is a real break rather than a property of a healthy population.
    """
    state_path = os.path.join(os.path.realpath(root), STATE_REL)
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump({"fingerprint": current, "at": report["generated_at"]}, fh)
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def _write_manifest(root: str, report: dict) -> dict:
    """The LOCAL artifact, written last and never raising.

    It used to be written FIRST and unguarded, so an output directory that
    cannot be written -- a read-only volume, a file where the directory
    belongs, a permission change -- raised out of `run()` and the red fleet
    filed NOTHING (PR #726 review, minor). The convenience artifact was
    ordered ahead of the only signal that leaves the machine.
    """
    try:
        manifest = os.path.join(os.path.realpath(root), MANIFEST_REL)
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
    except OSError as exc:
        return {"written": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"written": True, "error": ""}


def run(root: str, notify=None, trigger=None, write_manifest=True) -> dict:
    report = scan(root)
    message = render(report)
    out = {"report": report, "message": message,
           "alert": {"filed": False, "skipped": True, "error": ""},
           "manifest": {"written": False, "error": "", "skipped": not write_manifest}}

    def finish(result):
        # ONE exit from run(), so the manifest cannot be skipped by whichever
        # early return the alert path took. Every `return` below goes through
        # here; a second writer is how the first-run branch would quietly stop
        # leaving an artifact.
        if write_manifest:
            out["manifest"].update(_write_manifest(root, report))
        return result

    if trigger != "launchd":
        out["alert"]["reason"] = ("not launched by the plist (KIPI_TRIGGER != launchd): "
                                 "printed, filed nothing")
        return finish(out)
    state_path = os.path.join(os.path.realpath(root), STATE_REL)
    try:
        with open(state_path, encoding="utf-8") as fh:
            previous = json.load(fh).get("fingerprint", "")
    except (OSError, ValueError):
        previous = ""
    current = fingerprint(report)
    if current == previous:
        out["alert"]["reason"] = f"no state change since the last run ({current})"
        return finish(out)
    if not previous and not report["red"]:
        # First scheduled run on a healthy fleet: "" -> "green" is a state change
        # by string comparison, and filing "recovered" for a condition that never
        # fired is a ticket somebody closes by hand (PR #339 review, minor).
        # `is_noise()` in alert-to-linear does not match that wording, so it
        # really does become a real ticket. The state is still RECORDED below, so
        # the first genuine red is not muted by this branch.
        _remember(root, current, report)
        out["alert"]["reason"] = f"first run and nothing is red ({current}): state recorded"
        return finish(out)
    out["alert"]["skipped"] = False
    body = message if report["red"] else (
        "voice-stop-gate propagation recovered: no instance is ahead of the skeleton")
    try:
        (notify or _send)(body)
        out["alert"]["filed"] = True
    except NotifierUnconfigured as exc:
        # A machine with no Linear key is a SETUP state, which slack-notify.sh
        # says in its own exit contract. Read as a send failure it made every
        # 06:30 run there exit 2 into a log nobody reads, forever, and file
        # nothing -- on a GREEN fleet too (PR #339 review round 3, minor).
        # Nothing was filed, so the state is still not advanced: the first run
        # after a key exists files the red that was waiting.
        out["alert"]["skipped"] = True
        out["alert"]["reason"] = f"notifier not configured, nothing filed ({exc})"
        return finish(out)
    except Exception as exc:                      # never swallowed: the caller exits 2
        out["alert"]["error"] = f"{type(exc).__name__}: {exc}"
        return finish(out)                        # state NOT advanced: retry next run
    _remember(root, current, report)
    return finish(out)


def main(argv=None, notify=None) -> int:
    """Exit 2 when the fleet is red, when this is not the skeleton, or when the
    plist launched it and the alert did not file. A red fleet whose only alert
    vanished behind exit 0 is read as fine by launchd and the deadman alike."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--no-manifest", action="store_true", help="print only, write nothing")
    a = ap.parse_args(argv)
    trigger = os.environ.get("KIPI_TRIGGER")
    out = run(a.root, notify=notify, trigger=trigger, write_manifest=not a.no_manifest)
    print(out["message"])
    alert = out["alert"]
    if alert["filed"]:
        print("alert: filed to Sana's Linear triage")
    elif alert["error"]:
        print(f"alert: FAILED, {alert['error']}", file=sys.stderr)
    else:
        print("alert: " + alert.get("reason", "not filed"))
    # Said out loud, and NOT folded into the exit code. A local artifact failing
    # is not the fleet losing behaviour, and exiting 2 for it would rebuild the
    # permanently-red shape the PR #726 review's major is about one layer out.
    if out["manifest"]["error"]:
        print(f"manifest: NOT written, {out['manifest']['error']}", file=sys.stderr)
    if alert["error"]:
        return 2
    return 2 if out["report"]["red"] else 0


if __name__ == "__main__":
    sys.exit(main())
