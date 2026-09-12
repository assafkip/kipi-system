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
fleet between syncs. Only content the skeleton's git history NEVER held is
destroyed. Calling every mismatch red would make this runner red on a healthy
fleet, and a gate red on its own population gets switched off (the same call
`voice-loop-anywhere.md` and `coding-audhd.md` already made). `_skeleton_ever_had`
is the same git-based answer the lessons-drift reporter uses.

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
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
GATE_REL = "q-system/.q-system/scripts/voice-stop-gate.py"
MANIFEST_REL = "q-system/output/voice-gate-propagation.json"
STATE_REL = "q-system/output/.voice-gate-propagation-state.json"
NOTIFY = os.path.join(HERE, "slack-notify.sh")
COULD_NOT_READ = "COULD NOT READ"
NOTIFY_TIMEOUT_S = 20


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _skeleton_ever_had(skel_root: str, candidate: str) -> bool:
    """True when the candidate's content is a version the skeleton's git history
    holds for GATE_REL: the instance is BEHIND, not ahead. False when git cannot
    answer (not a repo, no history), which keeps the conservative reading --
    unknown provenance is treated as drift and gets looked at, never waved past.
    """
    try:
        blob = subprocess.run(["git", "-C", skel_root, "hash-object", candidate],
                              capture_output=True, text=True, timeout=20)
        if blob.returncode != 0:
            return False
        hits = subprocess.run(["git", "-C", skel_root, "log", "--all", "--format=%H",
                               "--find-object=" + blob.stdout.strip(), "--", GATE_REL],
                              capture_output=True, text=True, timeout=120)
        return hits.returncode == 0 and bool(hits.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def resolve(root: str):
    """(skeleton_ok, [(name, path or None)]) from the registry at `root`.

    The RAW skeleton value is checked before realpath, because realpath("") is
    the cwd and would pass whenever this ran from its own root (the same hole
    Codex found in the lessons-drift reporter, issue 13).
    """
    root = os.path.realpath(root)
    try:
        with open(os.path.join(root, "instance-registry.json"), encoding="utf-8") as fh:
            registry = json.load(fh)
    except (OSError, ValueError):
        return False, []
    raw = (registry.get("skeleton") or {}).get("path")
    skeleton_ok = isinstance(raw, str) and bool(raw.strip()) and os.path.realpath(raw) == root
    pairs = [(e.get("name") or "", e.get("path")) for e in registry.get("instances", [])]
    return skeleton_ok, [p for p in pairs if p[0]]


def classify(instance_root: str, skel_root: str) -> tuple:
    """(state, note) for one instance: synced | behind | ahead | could-not-read."""
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
    if _skeleton_ever_had(skel_root, inst_gate):
        return "behind", "an older skeleton version; the next sync fixes it"
    return "ahead", "content the skeleton never had; the next sync DESTROYS it"


def scan(root: str) -> dict:
    """The report. Pure enough for a test to read without a subprocess."""
    root = os.path.realpath(root)
    skeleton_ok, pairs = resolve(root)
    rows = []
    if skeleton_ok:
        for name, path in pairs:
            state, note = classify(path, root)
            rows.append({"name": name, "path": path, "state": state, "note": note})
    ahead = [r["name"] for r in rows if r["state"] == "ahead"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skeleton": root,
        "skeleton_ok": skeleton_ok,
        "instances": rows,
        "ahead": ahead,
        # a root that is not the skeleton is RED: it means this ran somewhere it
        # cannot answer the question, which is not the same as "no drift found".
        "red": bool(ahead) or not skeleton_ok,
    }


def render(report: dict) -> str:
    day = report["generated_at"][:10]
    lines = [f"voice-stop-gate propagation ({day})"]
    if not report["skeleton_ok"]:
        lines.append(f"skeleton: {COULD_NOT_READ} (the registry's skeleton entry is not "
                     f"this checkout: {report['skeleton']})")
        return "\n".join(lines)
    for row in report["instances"]:
        if row["state"] == "could-not-read":
            lines.append(f"{row['name']}: {COULD_NOT_READ} ({row['note']})")
        elif row["state"] == "ahead":
            lines.append(f"{row['name']}: AHEAD -- {row['note']}")
        else:
            lines.append(f"{row['name']}: {row['state']}"
                         + (f" ({row['note']})" if row["note"] else ""))
    if not report["instances"]:
        lines.append("no instances in the registry")
    if report["ahead"]:
        lines.append(f"RED: {len(report['ahead'])} instance(s) lose behaviour on the "
                     f"next sync: {', '.join(report['ahead'])}")
    return "\n".join(lines)


def fingerprint(report: dict) -> str:
    """What counts as a STATE for 'alert once on state change'. The set of ahead
    instances, not the whole report: a new `generated_at` every run would make
    every run a state change, which is the muted-channel failure wearing the
    shape of a fix."""
    if not report["skeleton_ok"]:
        return "skeleton-unreadable"
    return "ahead:" + ",".join(sorted(report["ahead"])) if report["ahead"] else "green"


def _send(message: str) -> None:
    """Raise when nothing was filed. An absent notifier is a legitimate no-op on
    an unconfigured machine and still is NOT a filing -- returning None there is
    the write-only-integration defect engineering_route.py::send documents."""
    if not os.path.isfile(NOTIFY):
        raise FileNotFoundError(f"no notifier at {NOTIFY}; nothing was filed")
    done = subprocess.run(["bash", NOTIFY, message], check=False,
                          capture_output=True, timeout=NOTIFY_TIMEOUT_S)
    if done.returncode != 0:
        raise RuntimeError(f"slack-notify.sh exited {done.returncode}: "
                           f"{(done.stderr or b'').decode('utf-8', 'replace')[:300]}")


def run(root: str, notify=None, trigger=None, write_manifest=True) -> dict:
    report = scan(root)
    message = render(report)
    out = {"report": report, "message": message,
           "alert": {"filed": False, "skipped": True, "error": ""}}
    if write_manifest:
        manifest = os.path.join(os.path.realpath(root), MANIFEST_REL)
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        fh = None
    if trigger != "launchd":
        out["alert"]["reason"] = ("not launched by the plist (KIPI_TRIGGER != launchd): "
                                 "printed, filed nothing")
        return out
    state_path = os.path.join(os.path.realpath(root), STATE_REL)
    try:
        with open(state_path, encoding="utf-8") as fh:
            previous = json.load(fh).get("fingerprint", "")
    except (OSError, ValueError):
        previous = ""
    current = fingerprint(report)
    if current == previous:
        out["alert"]["reason"] = f"no state change since the last run ({current})"
        return out
    out["alert"]["skipped"] = False
    body = message if report["red"] else (
        "voice-stop-gate propagation recovered: no instance is ahead of the skeleton")
    try:
        (notify or _send)(body)
        out["alert"]["filed"] = True
    except Exception as exc:                      # never swallowed: the caller exits 2
        out["alert"]["error"] = f"{type(exc).__name__}: {exc}"
        return out                                # state NOT advanced: retry next run
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump({"fingerprint": current, "at": report["generated_at"]}, fh)
    return out


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
    if alert["error"]:
        return 2
    return 2 if out["report"]["red"] else 0


if __name__ == "__main__":
    sys.exit(main())
