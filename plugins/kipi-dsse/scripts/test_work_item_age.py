"""ASK-3826 (age half): `issue_runner.py load` refuses a new issue while its PRD's oldest work ages.

RCA 2026-11-06 root cause #5: work in progress had no ceiling and no age signal, so new
issues started every day while older items from the same PRD conflicted with main and were
abandoned (chief: three majors unowned for 12 days while the next issues started). `load` is
the verb /issue-start runs, so the refusal sits there.

Every fixture is a virgin git repo whose specs are rendered by the real prd_split.py from a
real PRD; only the split timestamps, statuses and ledgers are then set to the ages a case
needs, the same way time would have set them.
"""
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

DSSE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "_ask1810_fixtures", DSSE / "test_issue_runner_verifiable_green.py")
_fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fx)
_run, _issue, PRDOS = _fx._run, _fx._issue, _fx.PRDOS

MARKER_AT = re.compile(r"(<!-- generated-by: prd_split\.py prd=\S+ finding=\S+ at=)(\S+)( -->)")
DAY = 86400


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _prd_repo(tmp_path: Path, ids: list) -> tuple:
    """A virgin repo with one approved PRD split into one open spec per id. Returns (repo, prd_id)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# t\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, capture_output=True)
    assert _run(repo, PRDOS / "prd_os_init.py").returncode == 0
    created = _run(repo, PRDOS / "prd_runner.py", "new", "probe", "--title", "T")
    assert created.returncode == 0, created.stderr
    prd_id = json.loads(created.stdout)["created"]
    spec = repo / ".prd-os/prds" / f"{prd_id}.md"
    manifest = json.dumps([{"id": i, "title": f"Probe {i}", "allowed_files": ["README.md"],
                            "required_checks": ["true"], "acceptance": "a",
                            "finding_id": f"finding-{n}",
                            "bypass_check": "python3 -c \"print('no bypass')\""}
                           for n, i in enumerate(ids, start=1)])
    body = spec.read_text()
    at = body.index("\n## Issues") + len("\n## Issues")
    spec.write_text(body[:at] + "\n\n```json\n" + manifest + "\n```\n" + body[at:])
    assert _run(repo, PRDOS / "prd_runner.py", "advance", "draft").returncode == 0
    add = _run(repo, PRDOS / "findings_writer.py", "add", prd_id, "--source", "claude-review",
               stdin=json.dumps([{"severity": "major", "body": f"probe {i}"} for i in ids]))
    assert add.returncode == 0, add.stderr
    for n in range(1, len(ids) + 1):
        assert _run(repo, PRDOS / "findings_writer.py", "set-disposition", prd_id, f"finding-{n}",
                    "accepted", "--reason-code", "valid-fix-now", "--actor", "t").returncode == 0
    for step in ("in-review", "approved"):
        assert _run(repo, PRDOS / "prd_runner.py", "advance", step).returncode == 0
    split = _run(repo, PRDOS / "prd_split.py")
    assert split.returncode == 0, split.stderr
    assert _run(repo, PRDOS / "prd_runner.py", "clear").returncode == 0
    for i in ids:
        assert (repo / ".prd-os/issues" / f"{i}.md").is_file(), i
    return repo, prd_id


def _set_spec(repo: Path, issue_id: str, split_at: datetime, status: str | None = None) -> None:
    path = repo / ".prd-os/issues" / f"{issue_id}.md"
    text, n = MARKER_AT.subn(lambda m: m.group(1) + _iso(split_at) + m.group(3), path.read_text())
    assert n == 1, f"{issue_id}: marker not found exactly once"
    if status:
        text = re.sub(r"(?m)^status:\s*.+$", f"status: {status}", text, count=1)
    path.write_text(text)


def _close(repo: Path, prd_id: str, issue_id: str, split_days_ago: float, cycle_days: float) -> None:
    """Close an issue the way `close` leaves it: status closed plus one close receipt row."""
    split_at = _ago(split_days_ago)
    _set_spec(repo, issue_id, split_at, status="closed")
    row = {"issue_id": issue_id, "prd_id": prd_id, "finding_id": "finding-1",
           "closed_at": _iso(split_at + timedelta(days=cycle_days)), "verified_at": None,
           "reviewed_at": None, "findings_triaged_at": None, "commit_sha": "0" * 40}
    with (repo / ".prd-os/receipts.jsonl").open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _spill(repo: Path, source: str, sid: str, severity: str = "major", days_ago: float = 8,
           owner: str | None = None, linear=None) -> None:
    """File a row through the real `spillover add`, then append the full-copy row the ledger
    would hold for an older row: backdated, and with the owner and link the case needs.
    Rows written before RULE-2026-08-24-B carry no owner field (585 of 998 open rows in the
    kipi-system ledger on 2026-11-07)."""
    r = _run(repo, PRDOS / "prd_runner.py", "spillover", "add", "--source", source,
             "--desc", f"probe {sid}", "--id", sid, "--severity", severity, "--no-promote")
    assert r.returncode == 0, r.stderr
    ledger = repo / ".prd-os/spillover.jsonl"
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    last = [x for x in rows if x.get("id") == sid][-1]
    row = dict(last, created_at=_iso(_ago(days_ago)))
    row.pop("owner", None)
    if owner is not None:
        row["owner"] = owner
    if linear is not None:
        row["linear"] = linear
    with ledger.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def _five_closed(repo: Path, prd_id: str, ids: list) -> None:
    """Five merged items with cycle times of 1 to 5 days: the 85th percentile is 5 days."""
    for n, i in enumerate(ids, start=1):
        _close(repo, prd_id, i, split_days_ago=30, cycle_days=n)


# --- the DoR check: an 8-day unowned major refuses, naming it ---------------------------------

def test_an_eight_day_unowned_major_spillover_refuses_start_naming_it(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-unowned1", days_ago=8)
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "sp-unowned1" in r.stderr and "unowned" in r.stderr, r.stderr
    assert not (repo / ".claude/state/active-issue.json").exists(), "a refused start wrote state"


def test_a_prd_item_older_than_the_cycle_time_tail_refuses_start_naming_it(tmp_path):
    ids = ["c1", "c2", "c3", "c4", "c5"]
    repo, prd = _prd_repo(tmp_path, ids + ["old-1", "new-1"])
    _five_closed(repo, prd, ids)
    _set_spec(repo, "old-1", _ago(9))
    _set_spec(repo, "new-1", _ago(0))
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "old-1" in r.stderr and "85th percentile" in r.stderr, r.stderr


def test_a_healthy_prd_starts(tmp_path):
    ids = ["c1", "c2", "c3", "c4", "c5"]
    repo, prd = _prd_repo(tmp_path, ids + ["young-1", "new-1"])
    _five_closed(repo, prd, ids)
    _set_spec(repo, "young-1", _ago(2))
    _set_spec(repo, "new-1", _ago(0))
    _spill(repo, prd, "sp-owned1", days_ago=20, owner="sana")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["loaded"] == "new-1"


# --- the cycle-time half needs 5 merged items; the unowned half does not ------------------

def test_fewer_than_five_merged_items_skips_the_cycle_time_half_in_one_line(tmp_path):
    ids = ["c1", "c2", "c3", "c4"]
    repo, prd = _prd_repo(tmp_path, ids + ["old-1", "new-1"])
    for n, i in enumerate(ids, start=1):
        _close(repo, prd, i, split_days_ago=30, cycle_days=n)
    _set_spec(repo, "old-1", _ago(20))
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
    [line] = [x for x in r.stderr.splitlines() if x.startswith("age gate:")]
    assert "4 merged" in line and "needs 5" in line and "unowned-major half still applies" in line


def test_fewer_than_five_merged_items_still_refuses_an_unowned_major(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["c1", "new-1"])
    _close(repo, prd, "c1", split_days_ago=30, cycle_days=1)
    _spill(repo, prd, "sp-floor1", severity="blocker", days_ago=10)
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "sp-floor1" in r.stderr, r.stderr


# --- the percentile is the 85th by nearest rank, not the max or the median ----------------

def test_the_tail_is_the_85th_percentile_of_merged_cycle_time(tmp_path):
    # Ten merged items, 1 to 10 days: nearest-rank p85 is 9 days (max 10, median 5.5).
    ids = [f"c{n}" for n in range(1, 11)]
    repo, prd = _prd_repo(tmp_path, ids + ["mid-1", "new-1"])
    for n, i in enumerate(ids, start=1):
        _close(repo, prd, i, split_days_ago=40, cycle_days=n)
    _set_spec(repo, "mid-1", _ago(8.5))
    assert _issue(repo, "load", "new-1").returncode == 0, "8.5 days is inside a 9-day tail"
    _set_spec(repo, "mid-1", _ago(9.5))
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "mid-1" in r.stderr and "9.0 days over 10 merged" in r.stderr, r.stderr


# --- no deadlock: the oldest work itself can always start ---------------------------------

def test_aging_specs_from_one_split_wave_do_not_block_each_other(tmp_path):
    ids = ["c1", "c2", "c3", "c4", "c5"]
    repo, prd = _prd_repo(tmp_path, ids + ["wave-1", "wave-2"])
    _five_closed(repo, prd, ids)
    _set_spec(repo, "wave-1", _ago(20) - timedelta(seconds=2))
    _set_spec(repo, "wave-2", _ago(20))
    r = _issue(repo, "load", "wave-2")
    assert r.returncode == 0, r.stdout + r.stderr


def test_resuming_an_issue_already_in_progress_is_not_a_new_start(tmp_path):
    ids = ["c1", "c2", "c3", "c4", "c5"]
    repo, prd = _prd_repo(tmp_path, ids + ["old-1", "new-1"])
    _five_closed(repo, prd, ids)
    _set_spec(repo, "old-1", _ago(9))
    _set_spec(repo, "new-1", _ago(0), status="in-progress")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already in progress" in r.stderr


# --- what "unowned" means --------------------------------------------------------------

def test_an_owner_field_or_a_linked_linear_issue_owns_a_row(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-own", days_ago=30, owner="sana")
    _spill(repo, prd, "sp-cap", days_ago=30,
           linear={"state": "filed", "identifier": "ASK-1555", "exit": 0, "at": _iso(_ago(29))})
    _spill(repo, prd, "sp-promo", days_ago=30, linear="ASK-1556")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_failed_capture_ticket_is_not_a_link(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-failed", days_ago=9,
           linear={"state": "failed", "identifier": None, "exit": 1, "at": _iso(_ago(9))})
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "sp-failed" in r.stderr, r.stderr


def test_rows_that_are_young_minor_resolved_or_from_another_prd_do_not_refuse(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-young", days_ago=6)
    _spill(repo, prd, "sp-medium", severity="medium", days_ago=30)
    _spill(repo, "prd-someone-else-2026-01-01", "sp-other", days_ago=30)
    _spill(repo, prd, "sp-done", days_ago=30)
    ledger = repo / ".prd-os/spillover.jsonl"
    done = [json.loads(x) for x in ledger.read_text().splitlines() if '"sp-done"' in x][-1]
    with ledger.open("a") as fh:
        fh.write(json.dumps(dict(done, status="resolved")) + "\n")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_row_filed_by_a_sibling_issue_counts_as_the_prds(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["done-1", "new-1"])
    _spill(repo, "done-1", "sp-sib", days_ago=8)
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "sp-sib" in r.stderr, r.stderr


# --- the one override: explicit, with a reason, logged ----------------------------------

def test_the_override_needs_a_reason_and_writes_a_row(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-obsolete", days_ago=8)
    assert _issue(repo, "load", "new-1", "--age-override", "  ").returncode == 2
    ledger = repo / ".prd-os/gate-bypasses.jsonl"
    assert not ledger.exists()
    r = _issue(repo, "load", "new-1", "--age-override", "sp-obsolete superseded by ASK-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OVERRIDDEN" in r.stderr and "sp-obsolete" in r.stderr
    [row] = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert row["flag"] == "--age-override" and row["issue_id"] == "new-1"
    assert row["reason"] == "sp-obsolete superseded by ASK-1" and row["blockers"] == ["sp-obsolete"]


# --- load path: a worktree reads the ledger prd_runner writes, at the main checkout -------

def test_a_worktree_start_reads_the_main_checkouts_ledger(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    subprocess.run(["git", "add", "-A", "-f", ".prd-os/issues", ".prd-os/prds"], cwd=repo,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "specs"], cwd=repo, capture_output=True)
    wt = tmp_path / "wt"
    made = subprocess.run(["git", "worktree", "add", "-q", str(wt)], cwd=repo,
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    assert _run(wt, PRDOS / "prd_os_init.py").returncode == 0
    _spill(repo, prd, "sp-main-only", days_ago=8)
    assert not (wt / ".prd-os/spillover.jsonl").exists()
    spec = importlib.util.spec_from_file_location("_prd_runner_for_parity", PRDOS / "prd_runner.py")
    prd_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prd_runner)
    sys_path_wia = importlib.util.spec_from_file_location("_wia", DSSE / "work_item_age.py")
    wia = importlib.util.module_from_spec(sys_path_wia)
    sys_path_wia.loader.exec_module(wia)
    assert wia.ledger_root(wt) == prd_runner._ledger_root(wt) == repo.resolve()
    r = _issue(wt, "load", "new-1")
    assert r.returncode == 2 and "sp-main-only" in r.stderr, r.stdout + r.stderr
