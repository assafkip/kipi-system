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
- Only STARTED work ages. An unstarted spec is backlog, and every spec of one split shares
  its split time, so judging backlog refuses 76 of 77 kipi-system starts (review of #626,
  round 1). Started = `status: in-progress` in this checkout, or a commit on any local ref
  (remote-tracking refs from the last fetch included) that is not on the base branch and
  changes the spec's `status:` line to in-progress or closed. That second signal is the open
  PR, or the abandoned branch, read from git instead of GitHub. Measured 2026-11-07: 2 of
  77 open kipi-system specs carry one, flipped 77 and 93 days ago and never merged.
- Spillover rows are prd-os's ledger, read at the same root prd_runner writes it.

"Unowned" = no tracker ref: prd_runner's `_spillover_has_tracker_ref`, copied below. NOT the
`owner` field: `spillover add` writes `owner: sana` on every row (RULE-2026-08-24-B), and a
check its own default satisfies is not a check (prd_runner.py, the same trap, 2026-08-24).
NOT the capture ticket `{"state": "filed", ...}` either: that alert makes a row visible, it
is not an issue in a queue somebody works. Review of #626 round 1 measured the first
definition firing on 0 of 260 open majors.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The fold sits beside this file (both kipi-dsse copies are pinned byte-identical), and the
# tests load this module by path, so the directory goes on sys.path the way issue_runner's does.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import ledger_fragments  # noqa: E402

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


def _receipt_rows(ledger: Path) -> list:
    """Every receipt row: receipts.jsonl, then its receipts.d/ fragments, through the one fold.

    WHY NOT `_jsonl` (ASK-3829, merging #626 into #621). Since the fragment switch a close writes
    its receipt as a new file under receipts.d/, so reading receipts.jsonl alone sees no close
    made after the switch: the merged count stops growing, the cycle-time half reports "fewer
    than 5 merged" forever, and a re-close in a fragment never updates its issue's last close.
    Fold order is write order, so "last row per issue wins" below keeps its meaning."""
    rows = []
    for _source, _number, raw in ledger_fragments.iter_lines(ledger):
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


def has_tracker_ref(row: dict) -> bool:
    """A copy of prd_runner._spillover_has_tracker_ref; test_work_item_age.py pins the two."""
    link = row.get("linear")
    return bool((link.strip() if isinstance(link, str) else "")
                or str(row.get("linear_ref") or "").strip())


BASE_REFS = ("refs/remotes/origin/HEAD", "refs/remotes/origin/main", "refs/heads/main",
             "refs/heads/master")


def started_on_refs(repo_root: Path, issues_dir: Path) -> tuple:
    """({spec file stem: seconds since its latest status flip}, base ref) for specs whose
    `status:` line moves to in-progress or closed in a commit no base ref holds.

    (None, why) when git cannot answer. That fails OPEN, with a note: a git hiccup that
    refused every start would wedge the fleet, and the in-checkout signal still applies.
    """
    def git(*argv):
        return subprocess.run(["git", *argv], cwd=str(repo_root), capture_output=True,
                              text=True, timeout=30)
    try:
        base = next((r for r in BASE_REFS
                     if git("rev-parse", "--verify", "-q", r).returncode == 0), None)
        if base is None:
            return None, "no origin/main or main ref"
        rel = issues_dir.resolve().relative_to(Path(repo_root).resolve())
        out = git("log", "--all", "--not", base, "--no-merges",
                  "-G", "^status: (in-progress|closed)", "--format=C %ct", "--name-only",
                  "--", str(rel))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return None, f"git log failed: {exc}"
    if out.returncode != 0:
        return None, f"git log exited {out.returncode}"
    now = datetime.now(timezone.utc).timestamp()
    seen: dict = {}
    when = None
    for line in out.stdout.splitlines():
        if line.startswith("C "):
            when = int(line.split()[1])
        elif line.strip().endswith(".md") and when is not None:
            stem = Path(line.strip()).stem
            seen[stem] = min(seen.get(stem, now - when), now - when)
    return seen, base


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
         issues_dir: Path, now: datetime | None = None) -> tuple[list, list]:
    """(blockers, notes) for starting `issue_id`. `items`: one dict per spec with
    id, stem, prd_id, at (datetime or None), status. A refusal needs a non-empty blockers list."""
    now = now or datetime.now(timezone.utc)
    me = next((it for it in items if it["id"] == issue_id), None)
    if me is None or not me["prd_id"]:
        return [], []
    on_refs, base = started_on_refs(repo_root, issues_dir)
    notes = []
    if on_refs is None:
        notes.append(f"age gate: unmerged-branch signal unavailable ({base}); only "
                     "`status: in-progress` in this checkout marks started work")
        on_refs = {}
    if me["status"] == "in-progress" or me["stem"] in on_refs:
        # Reworking started work lowers the PRD's age; refusing it would make it rot, and it
        # is the very remedy the aging list asks for.
        return [], notes + [f"age gate: {issue_id} is already started, so this is rework, "
                            "not a new start"]
    prd = me["prd_id"]
    blockers = []

    tail, merged = tail_seconds(items, _receipt_rows(receipts_path))
    if tail is None:
        notes.append(f"age gate: cycle-time half skipped, {merged} merged item(s) in this repo and "
                     f"an {TAIL_PERCENTILE}th percentile needs {MIN_MERGED}; the "
                     f"{UNOWNED_DAYS}-day unowned-major half still applies")
    else:
        for it in sorted(items, key=lambda x: x["at"] or now):
            if it["prd_id"] != prd or it["id"] == issue_id or it["status"] == "closed" or it["at"] is None:
                continue
            if it["status"] == "in-progress":
                how = "in progress in this checkout"
            elif it["stem"] in on_refs:
                how = (f"status flipped {on_refs[it['stem']] / DAY_S:.0f} days ago on a ref "
                       f"{base} does not hold")
            else:
                continue  # backlog, not work in progress
            if (now - it["at"]).total_seconds() > tail:
                blockers.append(
                    f"{it['id']} ({how}) split {(now - it['at']).total_seconds() / DAY_S:.1f} "
                    f"days ago, past the repo's {TAIL_PERCENTILE}th percentile of merged cycle time "
                    f"({tail / DAY_S:.1f} days over {merged} merged)")

    sources = {prd, prd[len("linear:"):] if prd.startswith("linear:") else prd}
    sources |= {it["id"] for it in items if it["prd_id"] == prd}
    for row in sorted(_spillover(repo_root), key=lambda r: str(r.get("created_at"))):
        created = _ts(row.get("created_at"))
        if (row.get("source") not in sources or created is None
                or str(row.get("severity") or "").strip().lower() not in MAJOR_SEVERITIES
                or has_tracker_ref(row)):
            continue
        days = (now - created).total_seconds() / DAY_S
        if days >= UNOWNED_DAYS:
            blockers.append(
                f"{row['id']} [{row.get('severity')}] spillover from {row['source']} unowned for "
                f"{days:.0f} days (no tracker ref; promote it to a Linear issue): "
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
