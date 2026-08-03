#!/usr/bin/env python3
"""Re-test every `blocked:capability` block and clear the ones that now pass.

WHY THIS EXISTS (ASK-288)
-------------------------
`blocked:capability` was a one-way door. linear-worker.sh applies it when a
runner is not equipped for an issue whose spec is sound, and the picker then
excludes the issue forever. Nothing re-tested the environment. The Linear
comment ends "once it exists, remove this label and the loop picks the issue
straight back up" -- and the only actor who could do that was a human reading
a comment. Measured 2026-08-01: 10 issues parked, the worker logging one
consolidated count every 15 minutes, and no path back into the pool.

A capability that ARRIVED (a binary installed, a credential exported, a
directory created) left the board exactly as blocked as one that never came.
That is the defect: the state was recoverable in principle and terminal in
practice.

THE SHAPE OF THE FIX
--------------------
A block is only expirable if the run that created it recorded HOW to test it.
linear-worker.sh writes a machine-readable marker into the park comment:

    <!-- capability-probe: bin:codex -->

This script reads that marker back, runs the probe, and on a pass calls
`linear-sync.py unblock` so the picker offers the issue again. No human is the
next actor.

FAIL CLOSED, ALWAYS
-------------------
Un-parking is the unrecoverable direction. Once the label is gone the picker
dispatches the issue and a still-blocked run burns a real attempt; a block left
in place costs one log line. So every ambiguity -- no marker, an unknown kind, a
malformed value, a probe that raises -- leaves the block ALONE and is reported.
Only an affirmative pass clears it.

NO SHELL, EVER
--------------
The marker is agent-authored text read back later by an unattended job. If the
probe kinds were "run this command" then any run that could write a Linear
comment could execute arbitrary code at 3am under the founder's credentials.
The kinds below are a closed allowlist evaluated in-process. `cmd:` is not a
kind and never will be; it lands in the unknown-kind branch like any other
typo.

HONEST BOUNDARY (read this before trusting a green run)
-------------------------------------------------------
These probes test the ENVIRONMENT this script runs in. They do NOT test a
runner's harness. The most common real block -- Claude Code's sensitive-path
guard refusing Edit/Write under `.claude/**` -- is not liftable by
`permissions.allow` and cannot be observed from a plain Python process, so a
`write:` probe against `.claude/` would pass here and un-park an issue Sana
still cannot do. That class has no probe: the park records `none`, this script
reports it as unprobeable, and it stays parked. Reporting an unprobeable block
every run is the correct outcome, not a gap to paper over with a guess.

Usage:
  capability_block_expiry.py [--repo-project NAME] [--apply] [--team ASK]
Dry by default: says what it would clear and mutates nothing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

EXIT_OK = 0
EXIT_USAGE = 1
# Matches linear-worker.sh: 9 means the ENVIRONMENT is down and this run did no
# work. A caller can tell a dead Linear from a bad invocation.
EXIT_INFRA = 9

HERE = pathlib.Path(__file__).resolve().parent
BLOCK_LABEL = "blocked:capability"

# The marker linear-worker.sh writes into the park comment. Non-greedy so a
# comment carrying two markers yields two matches rather than one span across
# both; the LAST one wins (a re-park after a re-scope records a fresh probe and
# the old one must not outvote it).
PROBE_MARKER = re.compile(r"<!--\s*capability-probe:\s*(.*?)\s*-->")

# The literal a park writes when the runner recorded no probe. Distinct from a
# MISSING marker on purpose: "this run considered it and had nothing to test" and
# "this issue was parked before probes existed" are the same outcome here, but
# only the first proves the park path ran the recording step.
PROBE_NONE = "none"


def _load_linear_sync():
    """Import linear-sync.py as a module (its filename is not importable)."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the probe allowlist -----------------------------------------------------
# Each returns (passed, evidence). The evidence string goes onto the Linear issue
# verbatim: "I ran X and got Y" is this repo's bar, and an unblock that says only
# "the probe passed" cannot be checked by the person reading it later.


def probe_path(value: str):
    """The capability is a file or directory that now exists."""
    target = os.path.expanduser(value)
    exists = os.path.exists(target)
    return exists, f"os.path.exists({target!r}) -> {exists}"


def probe_bin(value: str):
    """The capability is a binary on PATH."""
    found = shutil.which(value)
    return bool(found), f"shutil.which({value!r}) -> {found!r}"


def probe_env(value: str):
    """The capability is a credential or setting present in the environment."""
    # Reports SET/UNSET and the length, never the value. This string is posted to
    # Linear, and a probe that proves a token exists by printing it is a leak.
    raw = os.environ.get(value) or ""
    present = bool(raw.strip())
    return present, f"os.environ[{value!r}] -> {'set' if present else 'unset'} (len {len(raw)})"


def probe_write(value: str):
    """The capability is write access to a directory.

    Tests by create-and-remove rather than os.access: os.access answers from the
    permission bits, which is the wrong answer on a read-only mount, inside a
    container, or under any guard that intercepts the write itself. The bits are
    not the capability; writing is.
    """
    target = os.path.expanduser(value)
    directory = target if os.path.isdir(target) else os.path.dirname(target) or "."
    stamp = os.path.join(directory, f".capability-probe-{os.getpid()}")
    if os.path.exists(stamp):
        # Never overwrite. A probe that clobbers a file to prove it can write is
        # a probe that destroys data on a name collision.
        return False, f"refused: probe file {stamp} already exists"
    try:
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write("probe")
        os.unlink(stamp)
    except OSError as exc:
        return False, f"write to {directory} -> {type(exc).__name__}: {exc}"
    return True, f"write to {directory} -> created and removed {os.path.basename(stamp)}"


PROBES = {
    "path": probe_path,
    "bin": probe_bin,
    "env": probe_env,
    "write": probe_write,
}


def run_probe(spec: str):
    """Evaluate one recorded probe. Returns (status, evidence).

    status is one of: pass, fail, unprobeable, unknown. Only `pass` may unblock.
    """
    spec = (spec or "").strip()
    if not spec or spec.lower() == PROBE_NONE:
        return "unprobeable", "no probe was recorded when this block was parked"
    if ":" not in spec:
        return "unknown", f"malformed probe {spec!r}: expected <kind>:<value>"
    kind, _, value = spec.partition(":")
    kind, value = kind.strip().lower(), value.strip()
    fn = PROBES.get(kind)
    if fn is None:
        return "unknown", (f"unknown probe kind {kind!r} (known: "
                           f"{', '.join(sorted(PROBES))}) -- not executed")
    if not value:
        return "unknown", f"probe {kind!r} carries no value"
    try:
        passed, evidence = fn(value)
    except Exception as exc:  # noqa: BLE1 -- fail closed on ANY probe defect
        return "fail", f"probe {spec!r} raised {type(exc).__name__}: {exc}"
    return ("pass" if passed else "fail"), evidence


# --- Linear reads ------------------------------------------------------------

BLOCKED_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""

TEAM_ID_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'


def blocked_issues(ls, team_key: str, repo_project: str | None):
    """Every parked issue this checkout owns."""
    team = ls.graphql(TEAM_ID_QUERY, {"k": team_key})["teams"]["nodes"]
    if not team:
        raise ls.LinearAPIError(f"no team with key {team_key}")
    tid = team[0]["id"]
    issues, after = [], None
    while True:
        page = ls.graphql(BLOCKED_QUERY, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    out = []
    for i in issues:
        labels = {n["name"] for n in (i.get("labels") or {}).get("nodes", [])}
        if BLOCK_LABEL not in labels:
            continue
        # SCOPED TO THIS CHECKOUT, same rule the picker uses. Unblocking an
        # issue this repo cannot check out does not restart it, it just moves
        # the stall to a queue nobody is draining. An unset project is NOT this
        # repo (the picker's in_this_repo comment carries the same reasoning).
        if repo_project and (i.get("project") or {}).get("name") != repo_project:
            continue
        out.append(i)
    return out


def recorded_probe(ls, identifier: str) -> str | None:
    """The probe from the LAST park comment, or None if none was ever written.

    Sorted explicitly by createdAt: linear-sync.cmd_comments carries a comment
    about Linear returning this connection newest-first, and a re-park writes a
    fresh probe that must outvote the one before it.
    """
    issue = ls.graphql(ls.ISSUE_COMMENTS, {"id": identifier}).get("issue")
    if not issue:
        return None
    nodes = (issue.get("comments") or {}).get("nodes") or []
    nodes.sort(key=lambda n: n.get("createdAt") or "")
    found = None
    for node in nodes:
        for match in PROBE_MARKER.findall(node.get("body") or ""):
            found = match
    return found


# --- Linear writes -----------------------------------------------------------
# Both go through linear-sync.py rather than a second copy of the mutations.
# That file is the one writer of Linear state in this fleet; a hand-rolled
# labelIds update here would be a second read-modify-write to keep in step with
# it, which is the drift sp-53b02cc4 already records for the attempts ledger.


def _sync(*args) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(HERE / "linear-sync.py"), *args],
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def clear_block(identifier: str, probe: str, evidence: str) -> tuple[bool, str]:
    ok, detail = _sync("unblock", identifier, BLOCK_LABEL)
    if not ok:
        return False, detail
    # The comment is how a reader learns why the issue reappeared. Posted only
    # on a state CHANGE -- a re-test that changes nothing must not write a
    # comment, or a 15-minute loop becomes a comment every 15 minutes on an
    # object whose comments cannot be deleted.
    note = (
        f"**The capability arrived. Un-parked automatically.** `{BLOCK_LABEL}` removed; "
        f"the picker offers this issue again on the next run.\n\n"
        f"Recorded probe: `{probe}`\n\n"
        f"**Next:** normal dispatch. No founder action, no capability grant pending. "
        f"If the block is still real, the run will park it again with a fresh probe."
    )
    _sync("progress", identifier, note, "--agent", "capability-expiry",
          "--evidence", f"{probe} -> {evidence}")
    return True, detail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-project", default=os.environ.get("REPO_PROJECT") or None,
                    help="only re-test blocks in this Linear project (default $REPO_PROJECT)")
    ap.add_argument("--team", default="ASK", help="Linear team key (default ASK)")
    ap.add_argument("--apply", action="store_true",
                    help="actually clear the blocks that pass; dry without it")
    args = ap.parse_args(argv)

    ls = _load_linear_sync()
    try:
        parked = blocked_issues(ls, args.team, args.repo_project)
    except ls.LinearAPIError as exc:
        print(f"INFRA: linear unreachable ({exc}). No block was re-tested.", file=sys.stderr)
        return EXIT_INFRA
    except Exception as exc:  # noqa: BLE1
        print(f"BLOCK: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    counts = {"pass": 0, "fail": 0, "unprobeable": 0, "unknown": 0, "cleared": 0}
    if not parked:
        print(f"capability-expiry: no issue parked at {BLOCK_LABEL}"
              + (f" in {args.repo_project}" if args.repo_project else ""))
        return EXIT_OK

    for issue in parked:
        ident = issue["identifier"]
        try:
            probe = recorded_probe(ls, ident)
        except ls.LinearAPIError as exc:
            # One unreadable thread does not stop the sweep: the other blocks
            # are still worth re-testing, and a whole run lost to one bad read
            # is a loop that stops recovering for a reason nobody sees.
            print(f"capability-expiry: {ident} comments unreadable ({exc}) -- left parked")
            counts["fail"] += 1
            continue
        status, evidence = run_probe(probe if probe is not None else PROBE_NONE)
        counts[status] = counts.get(status, 0) + 1

        if status != "pass":
            reason = {"unprobeable": "no recorded probe -- stays parked, nothing to re-test",
                      "unknown": "probe not runnable -- stays parked (fail closed)",
                      "fail": "still blocked"}[status]
            print(f"capability-expiry: {ident} {reason} [{evidence}]")
            continue

        if not args.apply:
            print(f"capability-expiry: {ident} WOULD BE CLEARED "
                  f"(probe `{probe}` passed: {evidence}) -- dry, use --apply")
            continue
        cleared, detail = clear_block(ident, probe, evidence)
        if cleared:
            counts["cleared"] += 1
            print(f"capability-expiry: {ident} CLEARED -- probe `{probe}` passed ({evidence})")
        else:
            # Same reasoning as the worker's failed-label branch: if the write
            # did not land, the issue is still parked and saying "cleared" would
            # report a recovery that did not happen.
            print(f"capability-expiry: {ident} probe passed but the unblock did NOT "
                  f"apply ({detail}) -- still parked")

    print("capability-expiry: " + json.dumps({
        "parked": len(parked),
        "cleared": counts["cleared"],
        "still_blocked": counts["fail"],
        "unprobeable": counts["unprobeable"],
        "unrunnable_probe": counts["unknown"],
        "applied": bool(args.apply),
    }))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
