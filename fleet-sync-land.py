#!/usr/bin/env python3
"""Land the fleet updater's skeleton syncs on each instance's origin (ASK-4431).

Why this exists. kipi-update.sh syncs into whatever branch an instance's shared
checkout has checked out and commits there. Nothing pushes that commit. Measured
2026-11-10: the updater reached a client instance every day (its log says
"unlanded sync: 19 updater commit(s) on HEAD are not on origin/main"), but the
checkout sat on branch a feature branch, so origin/main last received a sync on
2026-10-08. 13 of the 14 instances the updater writes had the same gap. The
--refuse-unlanded-sync hatch only refuses; it lands nothing.

The fix does not touch the human's checkout (separate-worktrees ruling,
2026-11-07). For each instance whose origin default branch lags the syncs made
locally, it cuts a worktree from origin/<default>, runs the SAME updater against
that worktree only (KIPI_UPDATE_REGISTRY points the one entry at it), pushes a
dated branch and opens a PR with auto-merge armed.

  check [--alert]   measure made-vs-landed per instance; --alert files one line
                    through slack-notify.sh (Sana's triage) when any lag > threshold
  land [--dry-run]  cut, sync, push, PR for every lagging instance

Exit codes: 0 ok, 1 some instance stale (check) or a landing failed (land).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKEL = Path(__file__).resolve().parent
TAG = "[no-issue: fleet updater"
BRANCH_PREFIX = "kipi/skeleton-sync-"
# 3 days. The updater runs daily and a landing PR needs CI plus a review, so one
# failed day plus one PR day is normal. a client instance went 32 days; this would have
# alerted on day 4.
THRESHOLD_DAYS = 3


def git(path, *args, check=False, timeout=120):
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                       text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {path}: {r.stderr.strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def last_sync_ts(path, ref):
    out = git(path, "log", "-1", "--format=%ct", "--fixed-strings", f"--grep={TAG}", ref)
    return int(out) if out else None


def registry_path():
    return Path(os.environ.get("KIPI_UPDATE_REGISTRY") or SKEL / "instance-registry.json")


def measure(entry, fetch=True):
    """One row per registered instance. status is ok | stale | not-reaching | skip."""
    name, path = entry.get("name"), entry.get("path") or ""
    row = {"name": name, "path": path}
    if entry.get("type") == "standalone" or not entry.get("subtree_prefix"):
        return {**row, "status": "skip", "reason": "not skeleton-managed"}
    if not path or not git(path, "rev-parse", "--git-dir"):
        return {**row, "status": "skip", "reason": "no repo at path"}
    if fetch:
        try:
            git(path, "fetch", "-q", "origin", timeout=60)
        except subprocess.TimeoutExpired:
            pass  # stale remote refs read as an OLDER landing: fails toward the alarm
    default = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if not default:
        return {**row, "status": "skip", "reason": "no origin default branch (nothing to land on)"}
    made, landed = last_sync_ts(path, "HEAD"), last_sync_ts(path, default)
    row.update(default=default, made=made, landed=landed)
    if made is None:
        return {**row, "status": "skip", "reason": "updater never synced this checkout"}
    now = time.time()
    lag = (made - landed) / 86400 if landed else float("inf")
    row["lag_days"] = None if lag == float("inf") else round(lag, 1)
    # Two signals, reported by name, never or-ed into one flag: syncs made but not
    # landed, and the updater not reaching the checkout at all.
    if lag > THRESHOLD_DAYS:
        row["status"] = "stale"
    elif (now - made) / 86400 > THRESHOLD_DAYS:
        row["status"] = "not-reaching"
    else:
        row["status"] = "ok"
    return row


def load_entries(only=""):
    entries = json.loads(registry_path().read_text())["instances"]
    return [e for e in entries if not only or e.get("name") == only]


def notify(line):
    cmd = os.environ.get("KIPI_NOTIFY_CMD") or str(SKEL / "q-system/.q-system/scripts/slack-notify.sh")
    subprocess.run(["bash", cmd, line], timeout=120)


def cmd_check(args):
    rows = [measure(e, fetch=not args.no_fetch) for e in load_entries(args.only)]
    for r in rows:
        detail = r.get("reason") or f"default={r['default']} lag_days={r['lag_days']}"
        print(f"{r['status']:13} {r['name']}: {detail}")
    stale = [r["name"] for r in rows if r["status"] == "stale"]
    absent = [r["name"] for r in rows if r["status"] == "not-reaching"]
    if args.alert:
        # Stable wording so alert-to-linear's fingerprint counts repeats on one ticket.
        if stale:
            notify(f"fleet-sync-divergence: skeleton syncs not landed on origin for >{THRESHOLD_DAYS} days: "
                   f"{', '.join(sorted(stale))}. fleet-sync-land.py land runs from lessons-daily.sh.")
        if absent:
            notify(f"fleet-sync-divergence: updater has not synced these checkouts for >{THRESHOLD_DAYS} days: "
                   f"{', '.join(sorted(absent))}. Read q-system/output/lessons-daily.log.")
    return 1 if stale or absent else 0


def gh(*args):
    exe = os.environ.get("KIPI_GH") or "gh"
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=180)


def github_slug(url):
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url or "")
    return m.group(1) if m else ""


def land_one(row, entry, dry_run, state):
    name, path, default = row["name"], row["path"], row["default"]
    # Raw config, not get-url: get-url expands insteadOf, and the slug is the GitHub name.
    slug = github_slug(git(path, "config", "--get", "remote.origin.url"))
    if not slug:
        return "FAIL", "origin is not a GitHub remote; nothing lands this instance"
    if not dry_run:
        open_prs = gh("pr", "list", "--repo", slug, "--state", "open", "--json", "headRefName",
                      "--jq", f'[.[] | select(.headRefName | startswith("{BRANCH_PREFIX}"))] | length')
        if open_prs.returncode == 0 and open_prs.stdout.strip() not in ("", "0"):
            return "WAIT", "a landing PR is already open; pr-owner and its auto-merge take it"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    wt = state / safe
    if wt.exists():
        git(path, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
    git(path, "worktree", "prune")
    git(path, "worktree", "add", "--detach", str(wt), default, check=True)
    try:
        base = git(wt, "rev-parse", "HEAD")
        reg = json.loads(registry_path().read_text())
        for e in reg["instances"]:
            if e.get("name") == name:
                e["path"] = str(wt)
        reg_file = state / f"registry-{safe}.json"
        reg_file.write_text(json.dumps(reg, indent=2))
        updater = os.environ.get("KIPI_UPDATE_SCRIPT") or str(SKEL / "kipi-update.sh")
        argv = ["bash", updater, "--only", name] + (["--dry-run"] if dry_run else [])
        env = {**os.environ, "KIPI_UPDATE_REGISTRY": str(reg_file)}
        log = state / f"{safe}.log"
        with open(log, "w") as fh:
            rc = subprocess.run(argv, cwd=str(SKEL), env=env, stdout=fh,
                                stderr=subprocess.STDOUT, timeout=3600).returncode
        if rc != 0:
            return "FAIL", f"updater exit {rc} in the landing worktree, log {log}"
        if dry_run:
            return "DRY", f"updater dry run green against worktree off {default}, log {log}"
        head = git(wt, "rev-parse", "HEAD")
        if head == base:
            return "OK", f"sync was a no-op against {default}; nothing to land"
        branch = f"{BRANCH_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"
        git(wt, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", check=True, timeout=300)
        base_branch = default.split("/", 1)[1]
        title = f"chore: land skeleton sync {time.strftime('%Y-%m-%d')} [no-issue: fleet updater skeleton sync]"
        body = ("Lands the fleet updater's skeleton sync on origin. The updater commits into the shared "
                "checkout's current branch, which nothing pushes; fleet-sync-land.py re-runs it in a "
                "worktree cut from origin and opens this PR (ASK-4431).")
        pr = gh("pr", "create", "--repo", slug, "--base", base_branch, "--head", branch,
                "--title", title, "--body", body)
        if pr.returncode != 0:
            return "FAIL", f"pushed {branch} but PR create failed: {pr.stderr.strip()[:200]}"
        url = pr.stdout.strip().splitlines()[-1]
        armed = gh("pr", "merge", url, "--auto", "--squash")
        note = "auto-merge armed" if armed.returncode == 0 else f"auto-merge NOT armed: {armed.stderr.strip()[:120]}"
        return "OK", f"{url} ({note})"
    finally:
        git(path, "worktree", "remove", "--force", str(wt))
        git(path, "worktree", "prune")


def cmd_land(args):
    state = Path(os.environ.get("KIPI_SYNC_LAND_STATE") or Path.home() / ".local/state/kipi/sync-land")
    state.mkdir(parents=True, exist_ok=True)
    failed = 0
    for entry in load_entries(args.only):
        row = measure(entry)
        if row["status"] != "stale" and not args.only:
            continue
        if "default" not in row:
            print(f"SKIP {row['name']}: {row.get('reason')}")
            continue
        try:
            verdict, detail = land_one(row, entry, args.dry_run, state)
        except Exception as exc:  # one instance never stops the rest of the fleet
            verdict, detail = "FAIL", str(exc)[:300]
        failed += verdict == "FAIL"
        print(f"{verdict} {row['name']}: {detail}")
    return 1 if failed else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--alert", action="store_true")
    c.add_argument("--no-fetch", action="store_true")
    c.add_argument("--only", default="")
    l = sub.add_parser("land")
    l.add_argument("--dry-run", action="store_true")
    l.add_argument("--only", default="", help="land this instance even when it is not stale")
    args = p.parse_args(argv)
    return cmd_check(args) if args.cmd == "check" else cmd_land(args)


if __name__ == "__main__":
    sys.exit(main())
