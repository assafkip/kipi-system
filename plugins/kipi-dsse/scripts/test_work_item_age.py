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
           **fields) -> None:
    """File a row through the real `spillover add` (owner: sana, as the producer writes it),
    then append the full-copy row the ledger holds once time passes: backdated, plus any
    field a later writer adds (a promotion's `linear` string, a capture ticket dict)."""
    r = _run(repo, PRDOS / "prd_runner.py", "spillover", "add", "--source", source,
             "--desc", f"probe {sid}", "--id", sid, "--severity", severity, "--no-promote")
    assert r.returncode == 0, r.stderr
    ledger = repo / ".prd-os/spillover.jsonl"
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    last = [x for x in rows if x.get("id") == sid][-1]
    assert last.get("owner") == "sana", last  # the producer's own default, kept as written
    with ledger.open("a") as fh:
        fh.write(json.dumps(dict(last, created_at=_iso(_ago(days_ago)), **fields)) + "\n")


def _git(repo: Path, *argv) -> None:
    r = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, (argv, r.stderr)


def _commit_specs(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A", "-f", ".prd-os/issues", ".prd-os/prds")
    _git(repo, "commit", "-q", "--allow-empty", "-m", msg)


def _flip_on_branch(repo: Path, issue_id: str) -> None:
    """Start `issue_id` the way a worker does: on a branch the base never merges."""
    _commit_specs(repo, "specs on the base branch")
    base = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    _git(repo, "checkout", "-qb", f"sana/{issue_id}")
    path = repo / ".prd-os/issues" / f"{issue_id}.md"
    path.write_text(re.sub(r"(?m)^status:\s*.+$", "status: in-progress", path.read_text(), count=1))
    _commit_specs(repo, f"start {issue_id}")
    _git(repo, "checkout", "-q", base)
    assert "status: open" in path.read_text()


def _five_closed(repo: Path, prd_id: str, ids: list) -> None:
    """Five merged items with cycle times of 1 to 5 days: the 85th percentile is 5 days."""
    for n, i in enumerate(ids, start=1):
        _close(repo, prd_id, i, split_days_ago=30, cycle_days=n)


C5 = ["c1", "c2", "c3", "c4", "c5"]


# --- the DoR check: an 8-day unowned major refuses, naming it ---------------------------------

def test_an_eight_day_unowned_major_spillover_refuses_start_naming_it(tmp_path):
    # The row is exactly what the producer wrote, owner: sana included (review of #626, F1).
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-unowned1", days_ago=8)
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "sp-unowned1" in r.stderr and "unowned" in r.stderr, r.stderr
    assert not (repo / ".claude/state/active-issue.json").exists(), "a refused start wrote state"


def test_a_prd_item_older_than_the_cycle_time_tail_refuses_start_naming_it(tmp_path):
    repo, prd = _prd_repo(tmp_path, C5 + ["old-1", "new-1"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "old-1", _ago(9), status="in-progress")
    _set_spec(repo, "new-1", _ago(9))
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "old-1" in r.stderr and "85th percentile" in r.stderr, r.stderr


def test_work_started_on_an_unmerged_branch_ages_and_refuses_start(tmp_path):
    # The open-PR (or abandoned-branch) case, read from git: the base still says open.
    repo, prd = _prd_repo(tmp_path, C5 + ["old-1", "new-1"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "old-1", _ago(9))
    _set_spec(repo, "new-1", _ago(9))
    _flip_on_branch(repo, "old-1")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "old-1" in r.stderr and "does not hold" in r.stderr, r.stderr


def test_a_healthy_prd_starts(tmp_path):
    repo, prd = _prd_repo(tmp_path, C5 + ["young-1", "new-1"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "young-1", _ago(2), status="in-progress")
    _set_spec(repo, "new-1", _ago(0))
    _spill(repo, prd, "sp-owned1", days_ago=20, linear="ASK-1556")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["loaded"] == "new-1"


# --- the cycle-time half needs 5 merged items; the unowned half does not ------------------

def test_fewer_than_five_merged_items_skips_the_cycle_time_half_in_one_line(tmp_path):
    ids = ["c1", "c2", "c3", "c4"]
    repo, prd = _prd_repo(tmp_path, ids + ["old-1", "new-1"])
    for n, i in enumerate(ids, start=1):
        _close(repo, prd, i, split_days_ago=30, cycle_days=n)
    _set_spec(repo, "old-1", _ago(20), status="in-progress")
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
    _set_spec(repo, "mid-1", _ago(8.5), status="in-progress")
    assert _issue(repo, "load", "new-1").returncode == 0, "8.5 days is inside a 9-day tail"
    _set_spec(repo, "mid-1", _ago(9.5), status="in-progress")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "mid-1" in r.stderr and "9.0 days over 10 merged" in r.stderr, r.stderr


# --- no deadlock: backlog never blocks, and started work can always be reworked -----------

def test_unstarted_siblings_never_block_however_old(tmp_path):
    # One split stamps every spec within seconds (review of #626, F2: 76 of 77 open
    # kipi-system specs have an old open sibling). Backlog is not work in progress.
    repo, prd = _prd_repo(tmp_path, C5 + ["wave-1", "wave-2"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "wave-1", _ago(100) - timedelta(days=3))
    _set_spec(repo, "wave-2", _ago(100))
    r = _issue(repo, "load", "wave-2")
    assert r.returncode == 0, r.stdout + r.stderr


def test_resuming_an_issue_already_in_progress_is_not_a_new_start(tmp_path):
    repo, prd = _prd_repo(tmp_path, C5 + ["old-1", "new-1"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "old-1", _ago(9), status="in-progress")
    _set_spec(repo, "new-1", _ago(9), status="in-progress")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already started" in r.stderr


def test_reworking_an_issue_started_on_a_branch_is_not_a_new_start(tmp_path):
    repo, prd = _prd_repo(tmp_path, C5 + ["old-1", "old-2"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "old-1", _ago(9))
    _set_spec(repo, "old-2", _ago(9))
    _flip_on_branch(repo, "old-1")
    _flip_on_branch(repo, "old-2")
    r = _issue(repo, "load", "old-2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already started" in r.stderr


# --- what "unowned" means: no tracker ref ---------------------------------------------------

def test_the_owner_default_and_a_capture_ticket_do_not_own_a_row(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-captured", days_ago=30,
           linear={"state": "filed", "identifier": "ASK-1555", "exit": 0, "at": _iso(_ago(29))})
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "sp-captured" in r.stderr, r.stderr


def test_a_promotion_or_a_linear_ref_owns_a_row(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-promo", days_ago=30, linear="ASK-1556")
    _spill(repo, prd, "sp-ref", days_ago=30, linear_ref="ASK-1557")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_tracker_ref_copy_agrees_with_prd_runner(tmp_path):
    spec = importlib.util.spec_from_file_location("_prd_runner_ref", PRDOS / "prd_runner.py")
    prd_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prd_runner)
    wspec = importlib.util.spec_from_file_location("_wia_ref", DSSE / "work_item_age.py")
    wia = importlib.util.module_from_spec(wspec)
    wspec.loader.exec_module(wia)
    shapes = [{}, {"owner": "sana"}, {"linear": "ASK-1"}, {"linear": "  "}, {"linear_ref": "ASK-2"},
              {"linear_ref": " "}, {"linear": {"state": "filed", "identifier": "ASK-3"}},
              {"linear": {"state": "failed", "identifier": None}}, {"linear": None}]
    assert [wia.has_tracker_ref(r) for r in shapes] == [
        prd_runner._spillover_has_tracker_ref(r) for r in shapes]


def test_rows_that_are_young_minor_resolved_or_from_another_prd_do_not_refuse(tmp_path):
    repo, prd = _prd_repo(tmp_path, ["new-1"])
    _spill(repo, prd, "sp-young", days_ago=6)
    _spill(repo, prd, "sp-medium", severity="medium", days_ago=30)
    _spill(repo, "prd-someone-else-2026-01-01", "sp-other", days_ago=30)
    _spill(repo, prd, "sp-done", days_ago=30, status="resolved")
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
    _commit_specs(repo, "specs")
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
    wspec = importlib.util.spec_from_file_location("_wia", DSSE / "work_item_age.py")
    wia = importlib.util.module_from_spec(wspec)
    wspec.loader.exec_module(wia)
    assert wia.ledger_root(wt) == prd_runner._ledger_root(wt) == repo.resolve()
    r = _issue(wt, "load", "new-1")
    assert r.returncode == 2 and "sp-main-only" in r.stderr, r.stdout + r.stderr


def test_without_a_base_ref_the_branch_signal_says_so_and_the_checkout_signal_still_holds(tmp_path):
    repo, prd = _prd_repo(tmp_path, C5 + ["old-1", "new-1"])
    _five_closed(repo, prd, C5)
    _git(repo, "branch", "-m", "trunk")
    _set_spec(repo, "old-1", _ago(9), status="in-progress")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 2 and "old-1" in r.stderr, r.stderr
    assert "unmerged-branch signal unavailable (no origin/main or main ref)" in r.stderr, r.stderr


def test_a_squash_merged_siblings_branch_does_not_make_it_started(tmp_path):
    # A squash merge leaves the branch's own commits off the base forever, so the spec stays
    # on an unmerged ref after it closed on the base. Closed on the base is what counts.
    repo, prd = _prd_repo(tmp_path, C5 + ["m-1", "new-1"])
    _five_closed(repo, prd, C5)
    _set_spec(repo, "m-1", _ago(9))
    _commit_specs(repo, "specs on the base branch")
    base = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    _git(repo, "checkout", "-qb", "sana/m-1")
    _set_spec(repo, "m-1", _ago(9), status="closed")
    _commit_specs(repo, "close m-1 on its branch")
    _git(repo, "checkout", "-q", base)
    _close(repo, prd, "m-1", split_days_ago=9, cycle_days=1)
    _commit_specs(repo, "squash merge of sana/m-1")
    r = _issue(repo, "load", "new-1")
    assert r.returncode == 0, r.stdout + r.stderr
