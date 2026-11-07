"""DSSE close refuses a checked Live deliverable with no live record (ASK-3830).

Scar, measured 2026-11-06: 15 of the 23 closed chief gp-* specs closed with a
checked "Live:" deliverable whose own text said PENDING ("PENDING deploy",
"PENDING after deploy"). The checkbox counter (`_count_checked_deliverables`)
counted the box, the issue closed, and none of the 15 got its record afterwards.
A checked box is a claim; a Live box is a claim about the RUNNING system, so it
closes only with a receipt of that system's record: the spec's `live_receipt:`
field names a file made by `runtime_receipt.py capture`, the same receipt #610
added for runtime-control fixes.

Red on the pre-fix runner: every refusal below exits 0 there.
Fixtures come from producers: the repo is built by prd_split + issue_runner.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

DSSE = Path(__file__).resolve().parent
sys.path.insert(0, str(DSSE))
from test_computed_receipts import (  # noqa: E402
    _issue, _make_repo, _review_artifact, _run)

SPEC = ".prd-os/issues/probe-1.md"
LIVE_PENDING = "- [x] Live: one verdict row from a real run. PENDING deploy"


def _record_path(tmp_path: Path) -> Path:
    """Where the running system writes its record: OUTSIDE the repo
    (the repo is tmp_path/repo)."""
    return tmp_path / "live" / "verdicts.jsonl"


def _shipped(tmp_path: Path) -> str:
    """A checked Live box that names its record, as chief's gp-* specs do."""
    return f"- [x] Live: one verdict row from a real run, in {_record_path(tmp_path)}."


def _ready(tmp_path: Path, deliverable: str) -> Path:
    """A probe issue with every other close gate passed, and its one locked
    deliverable replaced by `deliverable` (the count stays 1)."""
    repo = _make_repo(tmp_path, check="python3 -c \"print('ok')\"")
    assert _issue(repo, "verify").returncode == 0
    assert _issue(repo, "triage").returncode == 0
    for kind in ("standard", "adversarial"):
        assert _issue(repo, "record-review", kind).returncode == 0
        assert _issue(repo, "complete-review", kind, "--verdict", "approve",
                      "--evidence-file", _review_artifact(repo, kind)).returncode == 0
    spec = repo / SPEC
    text = spec.read_text()
    assert "- [ ] Probe" in text, text
    spec.write_text(text.replace("- [ ] Probe", deliverable, 1))
    return repo


def _set_live_receipt(repo: Path, value: str) -> None:
    spec = repo / SPEC
    text = spec.read_text()
    if re.search(r"(?m)^live_receipt:", text):
        text = re.sub(r"(?m)^live_receipt:.*$", f"live_receipt: {value}", text, count=1)
    else:
        end = text.index("\n---", 3)
        text = text[:end] + f"\nlive_receipt: {value}" + text[end:]
    spec.write_text(text)


def _record(tmp_path: Path) -> Path:
    rec = _record_path(tmp_path)
    rec.parent.mkdir(exist_ok=True)
    rec.write_text('{"verdict": "allow", "bot": "dev"}\n')
    return rec


def _capture(repo: Path, out: Path, *cmd: str):
    cap = _run(repo, DSSE / "runtime_receipt.py", "capture", "--out", str(out), "--", *cmd)
    assert cap.returncode == 0, cap.stderr
    return out


def _rows(repo: Path) -> list:
    f = repo / ".prd-os/receipts.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


# --- the DoR check -----------------------------------------------------------

def test_a_checked_pending_live_deliverable_without_a_receipt_does_not_close(tmp_path):
    repo = _ready(tmp_path, LIVE_PENDING)
    proc = _issue(repo, "close")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "PENDING" in proc.stderr and "Live" in proc.stderr, proc.stderr
    assert _rows(repo) == []
    assert "status: closed" not in (repo / SPEC).read_text()


def test_a_checked_live_deliverable_without_a_live_receipt_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    proc = _issue(repo, "close")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "live_receipt" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_pending_fails_even_with_a_live_receipt(tmp_path):
    """A checked box that says PENDING contradicts itself: drop the word or
    uncheck the box. A receipt does not settle which one is true."""
    repo = _ready(tmp_path, LIVE_PENDING)
    rec = _record(tmp_path)
    out = _capture(repo, tmp_path / "live.json", "tail", "-1", str(rec))
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "PENDING" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_lowercase_pending_also_fails(tmp_path):
    repo = _ready(tmp_path, "- [x] Live: first voice note answered, pending deploy, then his tap")
    assert _issue(repo, "close").returncode == 2


# --- the receipt itself --------------------------------------------------------

def test_a_live_receipt_reading_the_running_record_closes_and_lands_on_the_row(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    rec = _record(tmp_path)
    out = _capture(repo, tmp_path / "live.json", "tail", "-1", str(rec))
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr
    (row,) = _rows(repo)
    assert row["live_receipt"]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert row["live_receipt"]["claim_terms"] == ["live"]


def test_a_repo_relative_live_receipt_path_resolves_against_the_repo(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    rec = _record(tmp_path)
    (repo / ".prd-os/live").mkdir()
    _capture(repo, repo / ".prd-os/live/probe-1.json", "tail", "-1", str(rec))
    _set_live_receipt(repo, ".prd-os/live/probe-1.json")
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr


def test_a_live_receipt_that_only_reads_repo_source_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    out = _capture(repo, tmp_path / "src.json", "cat", "README.md")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "only reads source" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_a_live_receipt_that_names_nothing_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    out = _capture(repo, tmp_path / "date.json", "date")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "names no record" in proc.stderr, proc.stderr


def test_a_missing_live_receipt_file_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    _set_live_receipt(repo, str(tmp_path / "nope.json"))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "not found" in proc.stderr, proc.stderr


def test_a_live_receipt_from_before_the_issue_loaded_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    rec = _record(tmp_path)
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"command": f"tail -1 {rec}", "output": "row",
                               "exit_code": 0, "ran_at": "2020-01-01T00:00:00Z"}))
    _set_live_receipt(repo, str(old))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "before this item existed" in proc.stderr, proc.stderr


def test_a_live_receipt_already_on_another_issue_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    rec = _record(tmp_path)
    out = _capture(repo, tmp_path / "reused.json", "tail", "-1", str(rec))
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    with (repo / ".prd-os/receipts.jsonl").open("a") as fh:
        fh.write(json.dumps({"issue_id": "other-1", "live_receipt": {"sha256": sha}}) + "\n")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "already used to close other-1" in proc.stderr, proc.stderr


# --- PR #618 review round 1, major 1: the record is the one the spec names ----

def test_a_green_test_is_not_a_live_receipt(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    (repo / "test_probe_green.py").write_text("def test_ok():\n    assert True\n")
    out = _capture(repo, tmp_path / "g.json", sys.executable, "-m", "pytest", "-q",
                   "-p", "no:cacheprovider", "test_probe_green.py")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "runs a test" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_a_selftest_is_not_a_live_receipt(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    (repo / "prove.sh").write_text("echo selftest ok\n")
    out = _capture(repo, tmp_path / "s.json", "bash", "prove.sh", "--selftest")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "runs a test" in proc.stderr, proc.stderr


def test_the_issues_own_required_check_is_not_a_live_receipt(tmp_path):
    """The fixture's required check is python3 -c "print('ok')"."""
    repo = _ready(tmp_path, _shipped(tmp_path))
    out = _capture(repo, tmp_path / "rc.json", "bash", "-c", "python3 -c \"print('ok')\"")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "required check" in proc.stderr, proc.stderr


def test_a_read_of_a_record_the_live_box_does_not_name_does_not_close(tmp_path):
    repo = _ready(tmp_path, _shipped(tmp_path))
    other = tmp_path / "unrelated.log"
    other.write_text("anything\n")
    out = _capture(repo, tmp_path / "u.json", "tail", "-1", str(other))
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "Live deliverable names" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_a_record_under_a_directory_the_live_box_names_closes(tmp_path):
    rec = _record_path(tmp_path)
    repo = _ready(tmp_path, f"- [x] Live: the probe receipt in {rec.parent}/ from one real run.")
    _record(tmp_path)
    out = _capture(repo, tmp_path / "d.json", "tail", "-1", str(rec))
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr


def test_a_command_the_live_box_names_in_backticks_closes(tmp_path):
    """A status line has no file; the Live box names the command instead."""
    repo = _ready(tmp_path, "- [x] Live: the host status line from `uname -a`.")
    out = _capture(repo, tmp_path / "b.json", "uname", "-a")
    _set_live_receipt(repo, str(out))
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr


def test_a_shallow_named_path_binds_nothing():
    import runtime_receipt as rr
    assert rr._live_named_paths("Live: a row somewhere in ~/.config/ or /etc") == []
    named = rr._live_named_paths("Live: the row in ~/.config/chief/out.jsonl.")
    assert [p.name for p in named] == ["out.jsonl"], named


# --- controls ---------------------------------------------------------------

def test_an_issue_with_no_live_deliverable_closes_without_one(tmp_path):
    repo = _ready(tmp_path, "- [x] Probe")
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr
    assert "live_receipt" not in _rows(repo)[0]


def test_an_unchecked_live_deliverable_is_left_to_the_deliverables_lock(tmp_path):
    """Unchecked means not claimed; the count lock already refuses it."""
    repo = _ready(tmp_path, "- [ ] Live: one verdict row. PENDING deploy")
    proc = _issue(repo, "close")
    assert proc.returncode == 2 and "deliverables lock" in proc.stderr, proc.stderr


def test_a_live_word_that_is_not_the_deliverable_label_is_not_live(tmp_path):
    repo = _ready(tmp_path, "- [x] the live view renders, pending rows hidden")
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr
