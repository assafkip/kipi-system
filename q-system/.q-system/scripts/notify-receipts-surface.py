#!/usr/bin/env python3
"""Surface undelivered notify receipts at SessionStart. The ledger's only reader.

WHY THIS EXISTS (PR #72 review, MAJOR)

`slack-notify.sh:214` has stated for weeks that "notify-receipts-surface.py reads
it at SessionStart". That file did not exist, on any branch, and nothing else
opened `notify-receipts.jsonl` -- verified with `find` across the whole repo and
`git log --all --diff-filter=A`. So `--kind receipt` was a write-only sink.

That is not a cosmetic gap. `--kind receipt` means "the machine handled this,
recorded not delivered", and three pages converted to it are not handled by any
machine: `repo not found ... the Linear loop is DEAD`, `cannot compute its spend
budget window`, and `gh CLI is not on PATH ... the loop is stalled`. Each names a
condition that stops the loop completely, and each was being written to a file no
human and no process read. The alert channel was not quieted, it was severed.

This is the same defect as the one the whole ASK-310 line is about, inverted: not
"the loop hands work to a human", but "the loop stops telling anyone at all". A
receipt is only legitimately silent if something reads it.

WHAT IT SHOWS, AND WHAT IT DELIBERATELY DOES NOT

It prints receipts since the last time it ran, newest first, and nothing else.
Specifically it does NOT re-print the whole ledger every session: the file is
append-only and unbounded, and a surface that grows without limit is one the
operator learns to scroll past -- the same cry-wolf failure `page_once` exists to
prevent on the delivery side.

Delivered rows are skipped. Those already reached Slack; repeating them here is
the duplicate the operator would learn to ignore.

Exit 0 ALWAYS. A SessionStart hook that can fail is a hook that can wedge a
session, and a missing or malformed ledger is not an error -- it is an empty one.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

LEDGER = os.environ.get(
    "KIPI_NOTIFY_RECEIPTS", os.path.expanduser("~/.config/kipi/notify-receipts.jsonl"))
# Its own file, not the ledger, so replaying the surface never rewrites history.
STATE = os.environ.get(
    "KIPI_NOTIFY_SURFACE_STATE",
    os.path.expanduser("~/.config/kipi/notify-receipts-surface.json"))
MAX_SHOWN = 12


# The writer's timestamp key is `ts`, NOT `at`. The first cut of this reader used
# `at`, and because every synthetic fixture in its test also used `at`, the suite
# went green while the live ledger rendered every timestamp blank and the
# watermark never advanced -- the surface re-printed all 11 rows on every run. A
# fixture that invents its own schema tests the fixture.
TS_KEY = "ts"


def rows(path: str) -> list:
    """Every parsable row. A corrupt line is skipped, never fatal: one bad write
    must not blind the operator to the good rows around it."""
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        return []
    return out


def read_watermark() -> str:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh).get("last_seen_at") or ""
    except Exception:  # noqa: BLE001 - a missing/corrupt watermark means "show recent"
        return ""


def write_watermark(value: str) -> None:
    """Best effort. Failing to persist means one repeat next session, which is a
    far better failure than a crash in a SessionStart hook."""
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump({"last_seen_at": value}, fh)
    except OSError:
        pass


def undelivered_since(all_rows: list, watermark: str) -> list:
    fresh = []
    for r in all_rows:
        if r.get("delivered"):
            continue
        # The writer already stamps a per-row `read` flag. Honour it rather than
        # inventing a parallel notion of seen -- two sources of truth for the
        # same fact is how a surface starts disagreeing with its ledger.
        if r.get("read") in (True, "True"):
            continue
        at = r.get("ts") or ""
        if watermark and at and at <= watermark:
            continue
        fresh.append(r)
    return fresh


def render(fresh: list, total_new: int) -> str:
    lines = [f"# Notify receipts ({total_new} new, handled by the machine, not delivered)",
             "# These are conditions the loop recorded rather than paged about."]
    for r in fresh:
        at = (r.get("ts") or "")[:16].replace("T", " ")
        label = r.get("label") or "-"
        msg = (r.get("message") or "").strip().replace("\n", " ")
        lines.append(f"- [{at}] {label}: {msg[:150]}")
    if total_new > len(fresh):
        lines.append(f"- ...and {total_new - len(fresh)} more in {LEDGER}")
    return "\n".join(lines)


def main() -> int:
    all_rows = rows(LEDGER)
    if not all_rows:
        return 0
    watermark = read_watermark()
    fresh = undelivered_since(all_rows, watermark)
    newest = max((r.get("ts") or "") for r in all_rows)
    if not fresh:
        write_watermark(newest)
        return 0
    fresh.sort(key=lambda r: r.get("ts") or "", reverse=True)
    print(render(fresh[:MAX_SHOWN], len(fresh)))
    write_watermark(newest)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # See the module docstring: a SessionStart hook may not wedge a session.
        print(f"# notify-receipts-surface: skipped ({str(exc)[:80]})", file=sys.stderr)
        sys.exit(0)
