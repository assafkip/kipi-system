"""Work-item age gate for `issue_runner.py load` (ASK-3826, the age half).

`load` (what /issue-start runs) refuses a new issue while its PRD's oldest work ages:
  1. an open issue of the same PRD is past the repo's 85th percentile of merged cycle time, or
  2. a major or blocker spillover row from the same PRD has been unowned for 7 days.
It prints the aging list instead of starting. RCA 2026-11-06 root cause #5: nothing read
work-item age, so new issues started every day while older items from the same PRD
conflicted with main and were abandoned (chief: three majors unowned 12 days while the next
issues started). Vacanti: work-item age is the one flow metric that gets worse by doing nothing.

Where the numbers come from (all local; `load` makes no network call):
- Cycle time is a closed spec's split time (its prd_split marker `at=`) to its LAST close
  receipt `closed_at` in the receipts ledger. A spec closed in this checkout is a merged one:
  the close row and the `status: closed` flip ship inside the issue's PR. Age is split time
  to now, so both are read with the same instrument.
- The percentile is over every closed spec in the repo, not one PRD. Measured 2026-11-07 in
  kipi-system: 200 merged items repo-wide; per PRD, all 77 open specs belonged to PRDs with
  fewer than 5 closes, so a per-PRD tail would have judged nothing.
- An open PR is covered without GitHub: its issue's spec is not closed on main until it merges.
- Spillover rows are prd-os's ledger, read at the same root prd_runner writes it.

"Unowned" = no `owner` field AND no linked Linear issue. Rows filed since RULE-2026-08-24-B
carry `owner: sana`; 585 of 998 open kipi-system rows predate it and carry none. A link is
the capture ticket `{"state": "filed"|"captured", "identifier": ...}` or a promotion's string.
Whether that Linear issue is still open is NOT checked: that needs the network.
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

TAIL_PERCENTILE = 85
MIN_MERGED = 5
UNOWNED_DAYS = 7
MAJOR_SEVERITIES = ("major", "blocker")
OVERRIDE_FLAG = "--age-override"
DAY_S = 86400.0


def _ts(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def ledger_root(repo_root: Path) -> Path:
    """The main checkout every worktree shares; a copy of prd_runner._ledger_root.

    Copied, not imported: the installed plugin cache holds kipi-dsse without prd-os beside
    it, so an import works in the repo and silently falls back in the copy that runs (the
    `_closed_finding_class` shape). test_work_item_age.py pins the two to one answer.
    Scar sp-bc42f1d3: the ledger is gitignored, so a per-worktree read saw 0 of the 71 open
    findings that lived in the main checkout's copy.
    """
    root = repo_root
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(repo_root),
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = Path(repo_root) / common
            parent = common.resolve().parent
            if (parent / ".git").exists():
                root = parent
    except Exception:  # noqa: BLE001 -- same fallback as prd_runner: degraded, never raised
        pass
    return root


def _jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    rows = []
    for raw in path.read_text().splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _spillover(repo_root: Path) -> list:
    """Open rows, last write per id wins (the ledger's own read rule)."""
    items: dict = {}
    for rec in _jsonl(ledger_root(repo_root) / ".prd-os" / "spillover.jsonl"):
        if rec.get("id"):
            items[rec["id"]] = rec
    return [r for r in items.values() if r.get("status") == "open"]


def _linked(row: dict) -> bool:
    link = row.get("linear")
    if isinstance(link, dict):
        return link.get("state") in ("filed", "captured") and bool(str(link.get("identifier") or "").strip())
    return isinstance(link, str) and bool(link.strip())


def tail_seconds(items: list, receipts: list) -> tuple[float | None, int]:
    """(85th percentile of merged cycle time in seconds or None, merged count). Nearest rank."""
    last_close: dict = {}
    for row in receipts:
        closed = _ts(row.get("closed_at"))
        if closed is not None and row.get("issue_id"):
            last_close[row["issue_id"]] = closed
    cycles = []
    for it in items:
        if it["status"] != "closed" or it["at"] is None or it["id"] not in last_close:
            continue
        seconds = (last_close[it["id"]] - it["at"]).total_seconds()
        if seconds > 0:  # hand-written `prd-manual` markers carry times after the close
            cycles.append(seconds)
    if len(cycles) < MIN_MERGED:
        return None, len(cycles)
    cycles.sort()
    return cycles[math.ceil(TAIL_PERCENTILE / 100 * len(cycles)) - 1], len(cycles)


def gate(repo_root: Path, receipts_path: Path, items: list, issue_id: str,
         now: datetime | None = None) -> tuple[list, list]:
    """(blockers, notes) for starting `issue_id`. `items`: one dict per spec with
    id, prd_id, at (datetime or None), status. A refusal needs a non-empty blockers list."""
    now = now or datetime.now(timezone.utc)
    me = next((it for it in items if it["id"] == issue_id), None)
    if me is None or not me["prd_id"]:
        return [], []
    if me["status"] == "in-progress":
        # Resuming work already started lowers the PRD's age; refusing it would make it rot.
        return [], [f"age gate: {issue_id} is already in progress, so this is not a new start"]
    prd = me["prd_id"]
    blockers, notes = [], []

    tail, merged = tail_seconds(items, _jsonl(receipts_path))
    if tail is None:
        notes.append(f"age gate: cycle-time half skipped, {merged} merged item(s) in this repo and "
                     f"an {TAIL_PERCENTILE}th percentile needs {MIN_MERGED}; the "
                     f"{UNOWNED_DAYS}-day unowned-major half still applies")
    else:
        my_at = me["at"] or now
        for it in sorted(items, key=lambda x: x["at"] or now):
            if it["prd_id"] != prd or it["id"] == issue_id or it["status"] == "closed" or it["at"] is None:
                continue
            # Past the tail AND split more than one tail before this issue. Specs split within
            # one tail of each other are one wave (prd_split stamps each spec separately, a
            # second or two apart), so starting any of them is working the oldest work. Without
            # this every aging sibling blocks every other one and the PRD can never move.
            if (now - it["at"]).total_seconds() > tail and (my_at - it["at"]).total_seconds() > tail:
                blockers.append(
                    f"{it['id']} ({it['status']}) split {(now - it['at']).total_seconds() / DAY_S:.1f} "
                    f"days ago, past the repo's {TAIL_PERCENTILE}th percentile of merged cycle time "
                    f"({tail / DAY_S:.1f} days over {merged} merged)")

    sources = {prd, prd[len("linear:"):] if prd.startswith("linear:") else prd}
    sources |= {it["id"] for it in items if it["prd_id"] == prd}
    for row in sorted(_spillover(repo_root), key=lambda r: str(r.get("created_at"))):
        created = _ts(row.get("created_at"))
        if (row.get("source") not in sources or created is None
                or str(row.get("severity") or "").strip().lower() not in MAJOR_SEVERITIES
                or str(row.get("owner") or "").strip() or _linked(row)):
            continue
        days = (now - created).total_seconds() / DAY_S
        if days >= UNOWNED_DAYS:
            blockers.append(
                f"{row['id']} [{row.get('severity')}] spillover from {row['source']} unowned for "
                f"{days:.0f} days (no owner, no linked Linear issue): "
                f"{str(row.get('description') or '')[:100]}")
    return blockers, notes


def record_override(repo_root: Path, issue_id: str, reason: str, blockers: list, at: str) -> Path:
    """One row per override, in the shared bypass ledger at the main checkout.

    Written at the ledger root, not the worktree: gate-bypasses.jsonl is gitignored, so a row
    in a worktree would vanish with it (the sp-bc42f1d3 shape). Raises on a write failure:
    an override that cannot be logged is a silent bypass, and that is refused.
    """
    ledger = ledger_root(repo_root) / ".prd-os" / "gate-bypasses.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"flag": OVERRIDE_FLAG, "issue_id": issue_id, "reason": reason,
                             "blockers": [b.split(" ", 1)[0] for b in blockers], "at": at},
                            sort_keys=True) + "\n")
    return ledger
