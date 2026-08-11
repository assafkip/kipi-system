#!/usr/bin/env python3
"""The READING end of the founder-notification sink. (ASK-294)

Pairs with: slack-notify.sh (the only writer) and
test/test-notify-receipts-surface.sh (which drives both halves).

WHY THIS FILE EXISTS -- it is a review finding, not a nice-to-have. ASK-294
converted most producers from "page the founder" to `--kind receipt`, which is
recorded to notify-receipts.jsonl and never delivered. slack-notify.sh's own
comment asserted this file read that ledger at SessionStart. It did not exist,
and nothing else in the repo opened the ledger, so three dispatch pages that
mean the Linear loop is DEAD (repo-missing, gh-missing, budget-day) reached no
human AND no machine. page_once compounded it: the sink exits 0 for a receipt,
so the dedupe marker was written and the page counted as delivered.

That is the "quieter, not shorter" failure this whole issue exists to stop.
The founder's requirement was never "fewer pings", it was "they should go to
you or sana" -- ROUTED, not dropped. A sink with no reader is dropped with
extra steps.

WHAT IT SURFACES: every row nothing delivered to a human. That is one predicate
covering three distinct conditions, deliberately:
  * receipts        -- the machine handled it; the agent should still see that
                       it happened overnight.
  * refusals        -- a producer asked for something the enum does not allow.
                       A swallowed alert is the precise failure founder-
                       notifications.md exists to prevent, so it surfaces here.
  * failed delivery -- `delivered:false` on a `decision`. slack-notify.sh exits
                       0 even when curl fails (sp-21815b25), so a dropped page
                       is otherwise invisible to everyone. This reader is the
                       only place it shows up.
Rows that DID reach the phone are skipped: the founder already has them, and
repeating them to the agent is the noise this issue was opened about.

TWO FILES, ONE WRITER EACH. slack-notify.sh appends to the ledger under flock
and owns it exclusively. This reader never writes the ledger -- it keeps its own
byte cursor beside it. Read-state in the ledger rows would make it a second
writer to a file whose whole point is that concurrent dispatchers cannot corrupt
it.

THE CURSOR IS BYTES, AND SHRINKAGE RESETS IT. A rotated or truncated ledger
leaves the offset past EOF; reading from there is silent forever, which is
exactly the bug this file fixes wearing a different hat. `size < offset` means
the file is not the one the cursor described, so it restarts at 0.

Runs on SessionStart. Exit 0 ALWAYS -- a notification reader that can block a
session would be a worse outage than the noise it reports.

HONEST BOUNDARY (what this does NOT do):
  * It does not act. It puts the row in front of the agent; whether the
    condition gets handled is still the agent's call and nothing checks it.
  * It surfaces THIS machine's ledger. Fleet instances write their own.
  * It cannot tell a receipt that was genuinely handled from one that was
    demoted to shut it up. Only review does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Cap the block so an overnight storm cannot bury the rest of the session
# context. The remainder is COUNTED, never silently dropped -- a truncation that
# reads as "that was all of it" is the same lie as having no reader.
MAX_ROWS = 20
MESSAGE_CLIP = 200


def default_ledger() -> str:
    return os.environ.get(
        "KIPI_NOTIFY_RECEIPTS",
        os.path.join(os.path.expanduser("~"), ".config", "kipi", "notify-receipts.jsonl"),
    )


def read_cursor(cursor_path: str, size: int) -> int:
    """Byte offset to resume from. Anything unparseable or past EOF means 0."""
    try:
        with open(cursor_path, encoding="utf-8") as fh:
            offset = int(fh.read().strip())
    except (OSError, ValueError):
        return 0
    if offset < 0 or offset > size:
        return 0  # rotated, truncated, or a cursor from another file
    return offset


def write_cursor(cursor_path: str, offset: int) -> None:
    try:
        os.makedirs(os.path.dirname(cursor_path) or ".", exist_ok=True)
        with open(cursor_path, "w", encoding="utf-8") as fh:
            fh.write("%d\n" % offset)
    except OSError:
        pass  # an unwritable cursor re-surfaces rows; it must never break a session


def unread_rows(ledger: str, cursor_path: str):
    """Return (rows_nobody_delivered, new_offset). Empty on any read problem."""
    try:
        size = os.path.getsize(ledger)
    except OSError:
        return [], None
    offset = read_cursor(cursor_path, size)
    if offset >= size:
        return [], size
    rows = []
    try:
        with open(ledger, encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # one corrupt line must not blind the reader
                if isinstance(row, dict) and not row.get("delivered"):
                    rows.append(row)
            new_offset = fh.tell()
    except OSError:
        return [], None
    return rows, new_offset


def describe(row: dict) -> str:
    kind = row.get("kind") or "?"
    if row.get("refused"):
        tag = "REFUSED"
    elif kind == "decision":
        tag = "UNDELIVERED DECISION"   # curl failed; nobody's phone got this
    else:
        tag = kind.upper()
    klass = row.get("class")
    if klass:
        tag = "%s/%s" % (tag, klass)
    message = str(row.get("message", "")).replace("\n", " ")
    if len(message) > MESSAGE_CLIP:
        message = message[: MESSAGE_CLIP - 1] + "…"
    return "  [%s] %s  %s" % (tag, row.get("ts", "?"), message)


def main() -> int:
    ap = argparse.ArgumentParser(description="Surface undelivered founder-notification rows.")
    ap.add_argument("--ledger", default=None, help="path to notify-receipts.jsonl")
    args = ap.parse_args()

    ledger = args.ledger or default_ledger()
    cursor_path = ledger + ".cursor"

    rows, new_offset = unread_rows(ledger, cursor_path)
    if new_offset is not None:
        write_cursor(cursor_path, new_offset)
    if not rows:
        return 0

    shown, hidden = rows[-MAX_ROWS:], max(0, len(rows) - MAX_ROWS)
    print("MACHINE NOTIFICATIONS SINCE YOUR LAST SESSION (%d)" % len(rows))
    print("=" * 62)
    print("Nothing below reached the founder. It was recorded for you instead.")
    print("A REFUSED row is a producer bug. An UNDELIVERED DECISION means the")
    print("webhook dropped a page that was meant for his phone.")
    print()
    if hidden:
        print("  ... %d older row(s) not shown; full ledger: %s" % (hidden, ledger))
    for row in shown:
        print(describe(row))
    print()
    print("Ledger: %s" % ledger)
    print("=" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- a SessionStart hook never blocks
        print("notify-receipts-surface: skipped (%s)" % exc, file=sys.stderr)
        sys.exit(0)
