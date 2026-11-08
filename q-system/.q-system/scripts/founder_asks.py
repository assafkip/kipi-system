#!/usr/bin/env python3
"""founder_asks.py: the morning-brief section for decisions only the founder can make.

Founder rulings, 2026-11-07 and 2026-11-08: anything the fleet cannot do itself,
such as spend, access or reach outside the fleet, "is parked with its reason and
listed in the morning status file. It is not a page." This is the reader that
list was missing (PR #662 review, major 3): cap-ladder.py writes the file, this
renders its unresolved entries as a section of /q-morning, and each line carries
the one command that releases the held ticket. This section is the file's one
reader. The brief runs when the founder types /q-morning (its 07:40 schedule was
retired 2026-09-11); nothing reads the file on a schedule.

Registered in morning-brief.py OPTIONAL_SECTIONS. Read-only: the one writer is
cap-ladder.py (status_add, status_resolve).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

STATUS = Path(os.environ.get("CAP_LADDER_STATUS")
              or Path.home() / ".local/state/kipi/morning-status.jsonl")


def collect(now, sources: dict, status: Path | None = None):
    """(rows, error), the registry contract. One row per unresolved ask."""
    path = Path(status or STATUS)
    if not path.exists():
        return [], None          # nothing has ever been asked: an empty section
    try:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except (OSError, ValueError) as exc:
        return [], f"could not read {path}: {exc}"
    out = []
    for r in rows:
        if r.get("resolved"):
            continue
        out.append(f"{r.get('issue')}: {r.get('ask')}. When done: {r.get('resolve') or 'cap-ladder.py --resolve ' + str(r.get('issue'))}")
    return out, None
