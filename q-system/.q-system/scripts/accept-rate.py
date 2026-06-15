#!/usr/bin/env python3
"""accept-rate.py - prd-os disposition / receipt-coverage metric.

The loop-engineering article's KPI is "cost per accepted change." Tokens are
effectively unmetered on this fleet, so cost is the wrong denominator. The
constraint that actually binds is review burden: when the gate (Codex review)
raises a real objection, does it get FIXED, or waved through (deferred) / claimed
fixed without a receipt to prove it.

For every PRD in `.prd-os/findings/*.jsonl` this reports:
  - disposition mix (accepted / deferred / rejected / optional / pending)
  - deferred-major rate    -> "the gate objected and we waved it"
  - accepted-without-receipt -> "we said we'd fix it; no receipt it happened"

A finding counts as receipted when (prd_id, finding_id) appears in
`.prd-os/receipts.jsonl`. That file is the closeout trail the issue runner writes.

Scar (2026-06-15): built because the build-craft PRD sat in-review with 8 accepted
findings and zero receipts - the exact "done was a sentence, not a receipt" gap
this fleet ships against. A metric that can't see that gap is decoration. So the
accepted-without-receipt count is a first-class signal, not a footnote.

Read-only. No mutation of any shared resource, so no single-writer chokepoint
applies. `--selftest` builds its fixtures in a tempdir and never reads the live
`.prd-os/`, per the test-isolation rule the fable-discipline hook enforces.

Usage:
  accept-rate.py                 # report against the live .prd-os/ , exit 0
  accept-rate.py --gate          # exit 2 if any PRD trips an alert (for hooks)
  accept-rate.py --prd-os-dir D  # point at an alternate .prd-os/ (tests use this)
  accept-rate.py --selftest      # positive + negative self-test, exit 0 pass / 1 fail
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# Tunable. A deferred-major rate at or above this trips the soft alert. Not a
# magic truth - calibrate against the first weeks of real output. The hard alert
# (accepted-without-receipt) has no threshold: any such finding is a claimed fix
# with no proof, which is the failure mode this tool exists to surface.
DEFERRED_MAJOR_RATE_ALERT = 1.0 / 3.0


def _repo_root_default() -> str:
    # This file lives at <repo>/q-system/.q-system/scripts/accept-rate.py .
    # The prd-os data lives at <repo>/.prd-os/ , i.e. three levels up from here.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def load_findings(prd_os_dir: str) -> tuple[dict[str, list[dict]], list[str]]:
    """Return {prd_id: [finding, ...]} and a list of parse-error descriptions.

    Parse errors are returned, not swallowed: an unreadable findings line is a
    hole in the trail and the whole point of this fleet is that holes are
    findable, not silent.
    """
    findings: dict[str, list[dict]] = {}
    errors: list[str] = []
    findings_dir = os.path.join(prd_os_dir, "findings")
    if not os.path.isdir(findings_dir):
        return findings, errors
    for name in sorted(os.listdir(findings_dir)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(findings_dir, name)
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{name}:{lineno}: {exc}")
                    continue
                if not isinstance(obj, dict):
                    # Valid JSON but not an object (e.g. [] or "x") is still a hole
                    # in the trail, not a crash. Codex review finding, 2026-06-15.
                    errors.append(f"{name}:{lineno}: expected a JSON object, got {type(obj).__name__}")
                    continue
                prd_id = obj.get("prd_id") or name[: -len("-findings.jsonl")]
                findings.setdefault(prd_id, []).append(obj)
    return findings, errors


def load_receipts(prd_os_dir: str) -> set[tuple[str, str]]:
    """Return {(prd_id, finding_id), ...} for every closed-out finding."""
    closed: set[tuple[str, str]] = set()
    path = os.path.join(prd_os_dir, "receipts.jsonl")
    if not os.path.isfile(path):
        return closed
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # A malformed receipt means we cannot prove that closeout, so the
                # finding stays counted as unreceipted. Skipping is the safe side.
                continue
            prd_id = obj.get("prd_id")
            finding_id = obj.get("finding_id")
            if prd_id and finding_id:
                closed.add((prd_id, finding_id))
    return closed


def stats_for_prd(prd_id: str, items: list[dict], closed: set[tuple[str, str]]) -> dict:
    total = len(items)
    dispositions: dict[str, int] = {}
    deferred_major = 0
    accepted = 0
    accepted_without_receipt = 0
    for f in items:
        disp = (f.get("disposition") or "pending").lower()
        sev = (f.get("severity") or "unknown").lower()
        dispositions[disp] = dispositions.get(disp, 0) + 1
        if disp == "deferred" and sev == "major":
            deferred_major += 1
        if disp == "accepted":
            accepted += 1
            if (prd_id, f.get("id")) not in closed:
                accepted_without_receipt += 1
    # Degenerate case: a PRD with zero findings has no rate. Guard the divide and
    # report a rate of 0.0 rather than crashing or implying a problem.
    deferred_major_rate = (deferred_major / total) if total else 0.0
    alert = accepted_without_receipt > 0 or deferred_major_rate >= DEFERRED_MAJOR_RATE_ALERT
    return {
        "prd_id": prd_id,
        "total": total,
        "dispositions": dispositions,
        "accepted": accepted,
        "accepted_without_receipt": accepted_without_receipt,
        "deferred_major": deferred_major,
        "deferred_major_rate": deferred_major_rate,
        "alert": alert,
    }


def build_report(prd_os_dir: str) -> tuple[list[dict], list[str]]:
    findings, errors = load_findings(prd_os_dir)
    closed = load_receipts(prd_os_dir)
    rows = [stats_for_prd(pid, items, closed) for pid, items in sorted(findings.items())]
    return rows, errors


def print_report(rows: list[dict], errors: list[str]) -> None:
    if not rows:
        print("No PRD findings found. Nothing to measure.")
    for r in rows:
        flag = "ALERT" if r["alert"] else "ok"
        print(f"[{flag}] {r['prd_id']}")
        print(f"    findings: {r['total']}  dispositions: {r['dispositions']}")
        print(
            f"    accepted: {r['accepted']}  "
            f"accepted-without-receipt: {r['accepted_without_receipt']}"
        )
        print(
            f"    deferred-major: {r['deferred_major']}  "
            f"rate: {r['deferred_major_rate']:.2f} "
            f"(alert at {DEFERRED_MAJOR_RATE_ALERT:.2f})"
        )
    if errors:
        print("\nParse errors (holes in the trail):")
        for e in errors:
            print(f"    {e}")


def _write_jsonl(path: str, objs: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for o in objs:
            fh.write(json.dumps(o) + "\n")


def selftest() -> int:
    """Positive + negative self-test.

    A passing check unseen-to-fail is not a check (fable-discipline rule 2): so we
    assert both that a clean PRD does NOT alert and that a dirty one DOES, and that
    flipping the single offending field clears the alert.

    Scar (codex-review finding-1, 2026-06-15): the core logic test runs entirely in
    memory through `stats_for_prd`, so it passes even in a read-only sandbox with no
    writable temp dir - the exact environment the prd-os Codex gate runs in. A
    check the gate itself cannot execute is a weak check. The file round-trip is a
    second, best-effort test that confirms the disk-load path agrees with the pure
    path; it is skipped (not failed) when no temp dir is available.
    """
    failures: list[str] = []

    # --- Core logic, in memory, no filesystem. stats_for_prd IS the logic. ---
    clean = stats_for_prd(
        "prd-clean",
        [{"id": "finding-1", "disposition": "accepted", "severity": "major"}],
        {("prd-clean", "finding-1")},  # accepted AND receipted
    )
    if clean["alert"]:
        failures.append("clean PRD should NOT alert but did")

    dirty_items = [
        {"id": "finding-1", "disposition": "accepted", "severity": "major"},
        {"id": "finding-2", "disposition": "deferred", "severity": "major"},
    ]
    dirty = stats_for_prd("prd-dirty", dirty_items, set())  # no receipts at all
    if not dirty["alert"]:
        failures.append("dirty PRD SHOULD alert but did not")
    if dirty["accepted_without_receipt"] != 1:
        failures.append("dirty accepted-without-receipt should be 1")

    # Negative self-test: add the missing receipt and prove the signal drops to 0.
    # This is what makes the green meaningful - the count tracks the input, not a
    # constant.
    dirty_fixed = stats_for_prd("prd-dirty", dirty_items, {("prd-dirty", "finding-1")})
    if dirty_fixed["accepted_without_receipt"] != 0:
        failures.append("adding the receipt should zero accepted-without-receipt")
    # The deferred major still stands, so it still alerts. A receipt does not
    # un-defer a waved major.
    if not dirty_fixed["alert"]:
        failures.append("dirty PRD should still alert on deferred-major")

    # --- File round-trip, best-effort. Confirms load_findings/load_receipts agree
    #     with the pure path. Skipped, not failed, when no temp dir exists. ---
    try:
        tmp = tempfile.TemporaryDirectory()
    except (FileNotFoundError, OSError) as exc:
        print(f"integration test skipped: no writable temp dir ({exc})")
    else:
        with tmp as d:
            os.makedirs(os.path.join(d, "findings"))
            _write_jsonl(
                os.path.join(d, "findings", "prd-dirty-findings.jsonl"),
                [{"prd_id": "prd-dirty", **it} for it in dirty_items],
            )
            _write_jsonl(
                os.path.join(d, "receipts.jsonl"),
                [{"prd_id": "prd-dirty", "finding_id": "finding-1",
                  "issue_id": "iss", "closed_at": "2026-06-15T00:00:00Z"}],
            )
            rows, errors = build_report(d)
            row = {r["prd_id"]: r for r in rows}.get("prd-dirty")
            if errors:
                failures.append(f"integration: unexpected parse errors {errors}")
            if row is None or row["accepted_without_receipt"] != 0:
                failures.append("integration: file load disagrees with pure path")

    if failures:
        print("SELFTEST FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELFTEST PASS: clean ok, dirty alerts, signal tracks the input.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="prd-os disposition / receipt metric")
    ap.add_argument("--prd-os-dir", default=None,
                    help="path to a .prd-os directory (defaults to repo root)")
    ap.add_argument("--gate", action="store_true",
                    help="exit 2 if any PRD trips an alert (for hook wiring)")
    ap.add_argument("--selftest", action="store_true",
                    help="run positive+negative self-test, never touches live data")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    prd_os_dir = args.prd_os_dir or os.path.join(_repo_root_default(), ".prd-os")
    rows, errors = build_report(prd_os_dir)
    print_report(rows, errors)

    if args.gate and any(r["alert"] for r in rows):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
