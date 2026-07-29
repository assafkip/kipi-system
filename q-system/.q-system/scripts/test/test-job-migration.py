#!/usr/bin/env python3
"""Pins job-migration.py -- the single mechanism that migrates the ASK-151 roster
of scheduled jobs onto Linear-tracked execution.

Every assertion here runs against PURE functions fed fabricated facts. Nothing in
this file reads ~/Library/LaunchAgents, shells launchctl, touches the live pause
ledger, or writes the live receipt ledger (fable-discipline: a test must not touch
a live data path -- the blast radius of this migration is the founder's real
scheduled jobs).

The one thing it does read from disk is the roster JSON, because the roster IS the
contract: ASK-151 names 32 jobs and "a partial pass that reports success is the
failure mode".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
QROOT = SCRIPTS.parent.parent
ROSTER = QROOT / ".q-system" / "config" / "job-migration-roster.json"

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def load_module():
    path = SCRIPTS / "job-migration.py"
    if not path.exists():
        print(f"FAIL: {path} does not exist")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("job_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The 32 labels ASK-151 enumerates, transcribed from the issue body. If the roster
# file and this list ever disagree, the roster is wrong: the issue is the contract.
ASK151_JOBS = [
    "com.assaf.competitive-analysis.morning",
    "com.claudedaddy.repo-distribution",
    "com.cole.auto-build",
    "com.cole.cockpit",
    "com.cole.content-brain",
    "com.cole.content-brain-catchup",
    "com.cole.daily-podcast",
    "com.cole.daily-report",
    "com.cole.daily-social",
    "com.cole.daily-x-work",
    "com.cole.delivery-watch",
    "com.cole.fleet-env-health",
    "com.cole.job-liveness",
    "com.cole.podcast-report",
    "com.cole.podcast-weekly-report",
    "com.cole.prospect-feed",
    "com.cole.reddit-autobuild",
    "com.cole.reddit-paste-digest",
    "com.cole.reddit-producer",
    "com.cole.reddit-radar-daily",
    "com.cole.reply-sweep",
    "com.cole.slack-listener",
    "com.cole.substack-producer",
    "com.cole.substack-worker",
    "com.cole.tool-radar-score",
    "com.cole.wip-push",
    "com.kipi.audit-rotate",
    "com.kipi.fleet-health",
    "com.kipi.fractional-cxo.bolt-on-discovery",
    "com.kipi.fractional-cxo.opp-scan",
    "com.personal.story-podcast",
    "com.purespectrum.ti-weekly",
]


def test_roster(mod):
    print("roster is the ASK-151 contract")
    check("roster file exists", ROSTER.exists(), str(ROSTER))
    if not ROSTER.exists():
        return
    data = json.loads(ROSTER.read_text())
    labels = [j["label"] for j in data["jobs"]]
    check("roster holds exactly 32 jobs", len(labels) == 32, f"got {len(labels)}")
    check("roster matches the issue body verbatim",
          labels == ASK151_JOBS,
          f"diff: {sorted(set(labels) ^ set(ASK151_JOBS))}")
    check("roster declares expected_count 32", data.get("expected_count") == 32,
          f"got {data.get('expected_count')}")
    check("loader returns the same labels",
          [j["label"] for j in mod.load_roster(ROSTER)["jobs"]] == ASK151_JOBS)


def test_bar_launchd(mod):
    print("bar 1: launchd, never cron")
    ok, _ = mod.bar_launchd("com.kipi.x", plist_exists=True, cron_text="")
    check("plist present + empty crontab -> pass", ok)
    ok, detail = mod.bar_launchd("com.kipi.x", plist_exists=False, cron_text="")
    check("no plist -> fail", not ok, detail)
    ok, detail = mod.bar_launchd(
        "com.kipi.x", plist_exists=True,
        cron_text="0 7 * * * /bin/bash /x/com.kipi.x/run.sh")
    check("label also scheduled in cron -> fail", not ok, detail)
    ok, _ = mod.bar_launchd("com.kipi.x", plist_exists=True, cron_text=None)
    check("crontab unreadable -> fail, never assumed empty", not ok)


def test_bar_linear(mod):
    print("bar 2: failures reach Linear, not only a log")
    skeleton = ("com.kipi.", "com.cole.", "com.assaf.")
    ok, _ = mod.bar_linear("com.cole.daily-social", skeleton)
    check("watched prefix -> pass", ok)
    ok, detail = mod.bar_linear("com.personal.story-podcast", skeleton)
    check("com.personal. unwatched -> fail (the live gap ASK-151 found)",
          not ok, detail)
    check("missing_prefix names the fix",
          mod.missing_prefix("com.personal.story-podcast", skeleton) == "com.personal.")
    check("missing_prefix is None when already covered",
          mod.missing_prefix("com.cole.daily-social", skeleton) is None)
    ok, _ = mod.bar_linear("com.personal.story-podcast", skeleton + ("com.personal.",))
    check("after the fix prefix is added -> pass", ok)
    check("a bare label is never treated as a prefix",
          mod.missing_prefix("com.personal.story-podcast", ())
          == "com.personal.")


def test_bar_state(mod):
    print("bar 3: live or in the pause ledger, never dark")
    ok, _ = mod.bar_state("com.kipi.a", "ok", paused=False)
    check("loaded and clean -> pass", ok)
    ok, _ = mod.bar_state("com.kipi.a", "failing", paused=False)
    check("loaded but failing -> pass (loaded is recorded; failing is bar 4's job)", ok)
    ok, detail = mod.bar_state("com.cole.a", "not_loaded", paused=True)
    check("not loaded but in the pause ledger -> pass", ok, detail)
    ok, detail = mod.bar_state("com.cole.a", "not_loaded", paused=False)
    check("not loaded and NOT in the ledger -> fail (dark)", not ok, detail)
    ok, detail = mod.bar_state("com.cole.a", "unknown", paused=False)
    check("launchctl unavailable -> fail, never a silent pass", not ok, detail)


def test_bar_verified(mod):
    print("bar 4: verified, with the mode recorded and never laundered")
    ok, mode, _ = mod.bar_verified(None)
    check("no receipt -> fail", not ok)
    check("no receipt -> mode 'none'", mode == "none")
    ok, mode, _ = mod.bar_verified({"mode": "run", "exit_code": 0, "output_head": "x"})
    check("run receipt -> pass, mode run", ok and mode == "run")
    ok, mode, _ = mod.bar_verified({"mode": "run", "exit_code": 3, "output_head": "x"})
    check("run receipt with nonzero exit -> fail", not ok, mode)
    ok, mode, _ = mod.bar_verified({"mode": "run", "exit_code": 0, "output_head": ""})
    check("run receipt with no output and no effect -> fail (exit 0 alone is what "
          "a wrapper over a deleted script also returns)", not ok)
    ok, mode, detail = mod.bar_verified(
        {"mode": "run", "exit_code": 0, "output_head": "",
         "effect": "/Users/x/.claude/audit/audit.log"})
    check("silent exit 0 WITH an observable effect -> pass", ok, detail)
    check("the effect is named in the detail, not just asserted",
          "audit.log" in detail, detail)
    ok, mode, _ = mod.bar_verified(
        {"mode": "scheduler", "exit_code": 0, "output_head": "wrote report"})
    check("scheduler receipt -> pass, mode scheduler", ok and mode == "scheduler")
    ok, mode, _ = mod.bar_verified({"mode": "paused-ledger", "reason": "un-pausing "
                                    "is out of scope for ASK-151"})
    check("paused-ledger receipt -> tracked but NOT run-verified",
          (not ok) and mode == "paused-ledger")


def _row(label, bars=(True, True, True), mode="scheduler", verified=True):
    return {"label": label, "bar_launchd": bars[0], "bar_linear": bars[1],
            "bar_state": bars[2], "verified": verified, "verify_mode": mode,
            "detail": ""}


def test_gate(mod):
    print("gate: a partial pass must never report success")
    rows = [_row(f"com.kipi.j{i}") for i in range(32)]
    code, lines = mod.gate_result(rows, expect=32)
    check("32 tracked jobs -> exit 0", code == 0, "\n".join(lines))
    text = "\n".join(lines)
    check("gate prints the verification-mode breakdown, not a bare count",
          "scheduler" in text and "32" in text, text)

    dark = [_row(f"com.kipi.j{i}") for i in range(31)]
    dark.append(_row("com.cole.dark", bars=(True, True, False)))
    code, lines = mod.gate_result(dark, expect=32)
    check("31 green + 1 dark -> non-zero", code != 0)
    check("the dark job is named in the output",
          "com.cole.dark" in "\n".join(lines))

    short = [_row(f"com.kipi.j{i}") for i in range(31)]
    code, lines = mod.gate_result(short, expect=32)
    check("31 rows against expect=32 -> non-zero (count assertion)", code != 0)
    check("the shortfall is stated", "31" in "\n".join(lines) and "32" in "\n".join(lines))

    unlinked = [_row(f"com.kipi.j{i}") for i in range(31)]
    unlinked.append(_row("com.personal.story-podcast", bars=(True, False, True)))
    code, _ = mod.gate_result(unlinked, expect=32)
    check("a job whose failures reach no Linear issue -> non-zero", code != 0)

    unverified = [_row(f"com.kipi.j{i}") for i in range(31)]
    unverified.append(_row("com.cole.x", mode="none", verified=False))
    code, lines = mod.gate_result(unverified, expect=32)
    check("a job with no receipt at all -> non-zero", code != 0)

    paused = [_row(f"com.kipi.j{i}") for i in range(6)]
    paused += [_row(f"com.cole.p{i}", mode="paused-ledger", verified=False)
               for i in range(26)]
    code, lines = mod.gate_result(paused, expect=32)
    text = "\n".join(lines)
    check("paused-ledger receipts satisfy the gate (un-pausing is out of scope)",
          code == 0, text)
    check("...but the 26 unrun jobs are counted out loud, never folded into green",
          "26" in text and "paused-ledger" in text, text)


def test_effect_detection(mod):
    print("effect detection reads only what the plist declares")
    info = {"StandardOutPath": "/tmp/j.out", "StandardErrorPath": "/tmp/j.err",
            "WorkingDirectory": "/tmp/jwd", "ProgramArguments": ["/bin/true"]}
    paths = [str(p) for p in mod.declared_paths(info)]
    check("all three declared keys are read",
          paths == ["/tmp/j.out", "/tmp/j.err", "/tmp/jwd"], str(paths))
    check("a plist declaring nothing yields no paths (never a guess)",
          mod.declared_paths({"ProgramArguments": ["/bin/true"]}) == [])
    before = {"/a": [1.0, 10], "/b": None}
    check("unchanged -> no effect", mod.describe_effect(before, dict(before)) is None)
    check("a changed mtime is an effect",
          mod.describe_effect(before, {"/a": [2.0, 10], "/b": None}) == "/a")
    check("a path APPEARING is an effect",
          mod.describe_effect(before, {"/a": [1.0, 10], "/b": [3.0, 5]}) == "/b")
    check("a path DISAPPEARING is an effect",
          mod.describe_effect({"/a": [1.0, 10]}, {"/a": None}) == "/a")


def test_run_is_opt_in(mod):
    print("running a job is opt-in per label, never a side effect of an audit")
    check("AUTO_RUN is off", mod.AUTO_RUN is False)
    check("run_receipt refuses a label outside the roster",
          mod.is_runnable("com.not.in.roster", [{"label": "com.kipi.a"}]) is False)
    check("run_receipt accepts a roster label",
          mod.is_runnable("com.kipi.a", [{"label": "com.kipi.a"}]) is True)


def main():
    mod = load_module()
    test_roster(mod)
    test_bar_launchd(mod)
    test_bar_linear(mod)
    test_bar_state(mod)
    test_bar_verified(mod)
    test_gate(mod)
    test_effect_detection(mod)
    test_run_is_opt_in(mod)
    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("PASS: job-migration contract holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
