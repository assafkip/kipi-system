#!/usr/bin/env python3
"""Spillover -> Linear: file each new ledger row once, and say so when one is not.

ASK-1552. Founder, 2026-09-12, verbatim: "Backlog where? In linear or is it
going to disappear" and then "You told me you saved this exact thing to memory
many times. Is not true." Measured by script that day: `.prd-os/spillover.jsonl`
is untracked in git in chief, consulting and kipi-system, and nothing carried it
to Linear. A finding that lives only in an untracked file on one laptop is not
captured, it is parked where Sana's queue cannot see it.

TWO JOBS, ONE DEFINITION.

1. The capture-time filer. `prd_runner.py spillover add`, findings_writer's
   deferred auto-create and kipi-dsse's issue_findings deferred auto-create all
   import THIS file for `file_record()`, so there is one definition of "what a
   spillover row's Linear message says" and "how the filer's answer is read".
   Each caller keeps writing the ledger through its own existing append; this
   file never writes a ledger on their behalf.

2. The daily check (`main`). Reads the ledger(s) it is pointed at, retries the
   Linear link for open rows created on or after CREATED_AT_CUTOFF that have
   none, bounded per run, and files ONE summary alert (fingerprint-deduped by
   alert-to-linear) when rows stay unlinked. The link it records goes through
   prd_runner's `_spillover_record_link`, the ledger's existing locked write
   path, never a second writer.

WHAT IT DELIBERATELY DOES NOT DO. Rows created before CREATED_AT_CUTOFF are the
pre-existing backlog (open rows measured 2026-09-12: kipi-system 1,318, consulting 529, chief 3).
Bulk-filing them, and whether minors should be filed at all, are founder
decisions still pending, so the check skips them and prints their count on its
own line instead of folding it into the numbers it acts on.

EXIT CONTRACT (launchd-health reads LastExitStatus, so a non-zero here pages):
  0  every new open row is linked, or the summary alert about the rest landed
  1  the check could not do its job: a ledger or prd_runner could not be read,
     or rows stayed unlinked AND the summary alert failed. A job that cannot
     alert must not exit 0, or it goes quiet exactly when it matters.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILER = HERE / "alert-to-linear.py"

# Rows created before this instant are the pre-existing backlog: counted and
# printed, never filed by this check. Set to the moment the capture-time filer
# was written (date -u, 2026-09-13T01:30:20Z), so every row captured from then
# on is either filed at capture or retried here.
CREATED_AT_CUTOFF = "2026-09-13T01:30:00Z"

# Retries per run, across every ledger. A bound, so a Linear outage or a long
# un-synced instance cannot turn one run into a flood of tickets.
DEFAULT_RETRY_LIMIT = 20

FILER_TIMEOUT_SECONDS = 120

# States that mean "this row has a Linear issue". `captured` is the
# KIPI_ALERT_CAPTURE hatch: the filer accepted the message into the capture
# file, which is the only delivery a test run is allowed to make.
LINKED_STATES = ("filed", "captured")

_IDENT = re.compile(r"\b(?:filed|repeat #\d+ on) ([A-Z][A-Z0-9]*-\d+)\b")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(value) -> datetime | None:
    """Parse a created_at as an INSTANT. Strings from different writers compare
    wrong as strings (a `+00:00` row sorts differently from a `Z` row)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


CUTOFF = _instant(CREATED_AT_CUTOFF)


def is_new(rec: dict) -> bool:
    """On or after the cutoff. A missing or unparseable created_at is counted
    as pre-existing: the safe side of "do not flood Linear"."""
    created = _instant(rec.get("created_at"))
    return created is not None and created >= CUTOFF


def is_linked(rec: dict) -> bool:
    link = rec.get("linear")
    return isinstance(link, dict) and link.get("state") in LINKED_STATES


def _row_key(sid: str) -> str:
    """A per-row word that survives alert-to-linear's fingerprint.

    why: that fingerprint strips paths, digits and hex before hashing, so it can
    collapse a flood of one alert into one ticket. A spillover id is `sp-` plus
    hex, which it strips, so two rows whose descriptions differ only by a path
    would land on ONE ticket. Mapping a hash of the id onto the letters g..v
    (none of them hex) gives a token it keeps: distinct rows get distinct
    tickets, and re-filing the SAME row still dedups onto its own ticket.
    """
    digest = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:12]
    return "".join(chr(ord("g") + int(c, 16)) for c in digest)


def message_for(rec: dict) -> str:
    """The alert text. Title is its first 110 chars, so the id leads."""
    sid = str(rec.get("id") or "?")
    desc = " ".join(str(rec.get("description") or "").split())[:600]
    return (f"spillover {sid} ({rec.get('severity') or 'minor'}) from "
            f"{rec.get('source') or '?'}: {desc} | owner {rec.get('owner') or 'sana'}"
            f" | resolve with prd_runner spillover resolve {sid} | key {_row_key(sid)}")


def parse_filer_output(code, stdout: str, stderr: str) -> dict:
    """Turn alert-to-linear's answer into the row's `linear` link."""
    link = {"exit": code, "at": _now_iso(), "identifier": None}
    match = _IDENT.search(stdout or "")
    if code == 0 and match:
        link.update(state="filed", identifier=match.group(1))
    elif code == 0 and "CAPTURED to" in (stderr or ""):
        link["state"] = "captured"
    else:
        # Includes exit 0 with no identifier (a noise suppression): the row has
        # no issue, so it stays unlinked and the daily check retries it.
        link["state"] = "failed"
        link["detail"] = ((stderr or "") + (stdout or "")).strip()[-300:]
    return link


def file_record(rec: dict, repo_root) -> dict:
    """File one row through alert-to-linear.py. Never raises: a filer failure
    becomes a `failed` link the daily check retries, never a lost row."""
    if not FILER.is_file():
        return {"state": "failed", "exit": None, "identifier": None,
                "at": _now_iso(), "detail": f"no filer at {FILER}"}
    env = dict(os.environ)
    # Route the ticket to the ledger's own repo's Linear project.
    env.setdefault("KIPI_ALERT_REPO_PATH", str(repo_root))
    try:
        res = subprocess.run([sys.executable, str(FILER), message_for(rec)],
                             capture_output=True, text=True, env=env,
                             timeout=FILER_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001
        return {"state": "failed", "exit": None, "identifier": None,
                "at": _now_iso(), "detail": repr(exc)[:300]}
    return parse_filer_output(res.returncode, res.stdout, res.stderr)


# --------------------------------------------------------------------------
# The daily check
# --------------------------------------------------------------------------

def _load_runner():
    """prd_runner from this checkout: its lock + append are the ledger's one
    write path, and its reader is the one definition of last-write-wins."""
    scripts = HERE.parents[2] / "plugins" / "prd-os" / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("prd_runner_slc", scripts / "prd_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo_root_of(target: str) -> Path:
    p = Path(target).expanduser().resolve()
    if p.is_file() and p.name.endswith(".jsonl"):
        return p.parent.parent
    return p


def _summary_message(per_ledger: list, limit: int) -> str:
    counts = ", ".join(f"{name} {n}" for name, n in per_ledger)
    return ("spillover-linear-check: open spillover rows captured after the "
            "capture-filing cutoff still have no Linear issue after this run's "
            f"retries. Unlinked per ledger: {counts}. Each run retries up to {limit}. "
            "Rows from before the cutoff are the pre-existing backlog and are not "
            "counted here.")


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("targets", nargs="+", help="repo roots or spillover.jsonl paths")
    ap.add_argument("--limit", type=int, default=DEFAULT_RETRY_LIMIT,
                    help="max rows to retry per run, across all ledgers")
    ap.add_argument("--dry-run", action="store_true", help="count only; file nothing")
    args = ap.parse_args(argv)

    try:
        runner = _load_runner()
    except Exception as exc:  # noqa: BLE001
        print(f"spillover-linear-check: cannot load prd_runner ({exc!r})", file=sys.stderr)
        return 1

    budget = max(args.limit, 0)
    failed_read = False
    totals = {"open": 0, "backlog": 0, "filed": 0, "still": 0}
    per_ledger = []
    for target in args.targets:
        root = _repo_root_of(target)
        name = root.name
        if not root.is_dir():
            print(f"spillover-linear-check {name}: no repo at {root} (skipped)")
            continue
        cfg = types.SimpleNamespace(repo_root=root)
        try:
            items = runner._read_spillover(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"spillover-linear-check {name}: cannot read ledger ({exc!r})",
                  file=sys.stderr)
            failed_read = True
            continue
        open_rows = [r for r in items.values() if r.get("status") == "open"]
        backlog = [r for r in open_rows if not is_new(r) and not is_linked(r)]
        new_rows = [r for r in open_rows if is_new(r)]
        already = [r for r in new_rows if is_linked(r)]
        todo = sorted((r for r in new_rows if not is_linked(r)),
                      key=lambda r: _instant(r.get("created_at")))
        filed_now = failed_now = 0
        for rec in todo:
            if args.dry_run or budget <= 0:
                break
            budget -= 1
            link = file_record(rec, root)
            runner._spillover_record_link(cfg, rec["id"], link)
            if link.get("state") in LINKED_STATES:
                filed_now += 1
            else:
                failed_now += 1
        still = len(todo) - filed_now
        per_ledger.append((name, still))
        totals["open"] += len(open_rows)
        totals["backlog"] += len(backlog)
        totals["filed"] += filed_now
        totals["still"] += still
        print(f"spillover-linear-check {name}: open={len(open_rows)} "
              f"pre_cutoff_unlinked={len(backlog)} new_open={len(new_rows)} "
              f"already_linked={len(already)} filed_now={filed_now} "
              f"failed_now={failed_now} still_unlinked={still}")

    print(f"spillover-linear-check TOTAL: open={totals['open']} "
          f"filed_now={totals['filed']} still_unlinked={totals['still']}")
    print(f"pre-existing unlinked backlog (created before {CREATED_AT_CUTOFF}, "
          f"not filed by this check): {totals['backlog']}")

    rc = 1 if failed_read else 0
    if totals["still"] and not args.dry_run:
        msg = _summary_message(per_ledger, args.limit)
        try:
            res = subprocess.run([sys.executable, str(FILER), msg], capture_output=True,
                                 text=True, timeout=FILER_TIMEOUT_SECONDS)
            code, out = res.returncode, (res.stdout + res.stderr).strip()
        except Exception as exc:  # noqa: BLE001
            code, out = 1, repr(exc)
        print(f"summary alert: exit {code}: {out[-300:]}")
        if code != 0:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
