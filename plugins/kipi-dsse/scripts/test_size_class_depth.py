"""ASK-3827: review depth and verify repeats read the ASK-1749 size class.

The founder's lean-mode ruling (2026-09-18, 09-23, 10-30, 11-04): one review, one fix
round, merge; an adversarial pass only for code that sends mail, touches client data,
loses data or moves money. Before this, `issue_runner.py` gave every issue 2 standard
reviews, 1 adversarial and 5 to 10 verify repeats, whatever the diff was.

The numbers: S gets 1 standard, 0 adversarial, 2 repeats. M gets 1 plus 1. L keeps
2 plus 1 and a minimum of 5 repeats. A repo with no classifier, a diff the classifier
cannot read, or uncommitted code gets L, never S.

Every fixture is a virgin repo built by the real prd_split.py (the builder is loaded by
path from the ASK-1810 test file), with the REAL change-size.py linked in at the path CI
runs it from. The class comes from a committed diff against origin/main, the same way
validate.yml gets it.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
CLASSIFIER = DSSE.parents[2] / "q-system/.q-system/scripts/change-size.py"
_spec = importlib.util.spec_from_file_location(
    "_ask1810_fixtures", DSSE / "test_issue_runner_verifiable_green.py")
_fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fx)
_issue, _state = _fx._issue, _fx._state

TOOL = _fx.TOOL
REAL_TEST = _fx.REAL_TEST
SMALL_EDIT = TOOL + "\n\ndef other():\n    return 7\n"          # 4 changed lines: S
MID_FILE = "".join(f"V{i} = {i}\n" for i in range(30))           # 30 lines: M
BIG_FILE = "".join(f"V{i} = {i}\n" for i in range(160))          # 160 lines: L
FAST_CHECK = "python3 tests/test_tool.py"


def _git(repo: Path, *args: str) -> None:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _sized_repo(tmp_path, change: dict, *, classifier=True, base_ref=True,
                allowed=("scripts/tool.py", "tests/test_tool.py"), check=FAST_CHECK) -> Path:
    """A loaded issue whose branch carries `change` as one commit on top of origin/main."""
    repo = _fx._repo(tmp_path, {"scripts/tool.py": TOOL, "tests/test_tool.py": REAL_TEST,
                                ".gitignore": ".claude/state/\n"}, list(allowed), check)
    if classifier:
        target = repo / "q-system/.q-system/scripts/change-size.py"
        target.parent.mkdir(parents=True)
        target.symlink_to(CLASSIFIER)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    if base_ref:
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _commit(repo, change)
    return repo


def _commit(repo: Path, change: dict) -> None:
    for rel, text in change.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _dry(repo: Path, kind="standard") -> dict:
    r = _issue(repo, "record-review", kind, "--dry")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


# --- the DoR check: S gets 1, 0 and 2 repeats; L keeps 2, 1 and 5 --------------------

def test_an_s_diff_gets_one_standard_review_and_no_adversarial(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    out = _dry(repo)
    assert out["size_class"] == "S", out
    assert out["caps"] == {"standard": 1, "adversarial": 0}, out
    assert _state(repo)["review_rounds"] == {"standard": 0, "adversarial": 0}, "--dry claimed a slot"


def test_an_m_diff_gets_one_standard_and_one_adversarial(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/mid.py": MID_FILE})
    out = _dry(repo)
    assert (out["size_class"], out["caps"]) == ("M", {"standard": 1, "adversarial": 1}), out


def test_an_l_diff_keeps_two_standard_and_one_adversarial(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/big.py": BIG_FILE})
    out = _dry(repo)
    assert (out["size_class"], out["caps"]) == ("L", {"standard": 2, "adversarial": 1}), out


def test_an_s_diff_verifies_with_two_repeats(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["repeats"] == "2 of 2"
    rep = _state(repo)["verified_green"]["repeats"]
    assert (rep["n"], rep["size_class"], rep["repeat_min"]) == (2, "S", 2), rep


def test_an_l_diff_keeps_ten_repeats_and_a_minimum_of_five(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/big.py": BIG_FILE})
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    rep = _state(repo)["verified_green"]["repeats"]
    assert (rep["n"], rep["size_class"], rep["repeat_min"]) == (10, "L", 5), rep


@pytest.mark.parametrize("change,ok", [({"scripts/tool.py": SMALL_EDIT}, True),
                                       ({"scripts/big.py": BIG_FILE}, False)])
def test_the_repeat_minimum_follows_the_class(tmp_path, change, ok):
    # Budget 1s, a 0.2s check: 3 or 4 passes fit. S needs 2 and passes; L needs 5 and is
    # refused. One fixture shape, so only the class differs between the two runs.
    repo = _sized_repo(tmp_path, change, allowed=("README.md",),
                       check="python3 -c \"import time; time.sleep(0.2)\"")
    r = _issue(repo, "verify", env_extra={"KIPI_VERIFY_BUDGET_S": "1"})
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    if not ok:
        assert "at least 5 are needed" in r.stderr


# --- unknown never means small ------------------------------------------------------

def test_a_repo_with_no_classifier_gets_the_strict_numbers(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT}, classifier=False)
    out = _dry(repo)
    assert (out["size_class"], out["caps"]) == ("L", {"standard": 2, "adversarial": 1}), out
    assert "no ASK-1749 classifier" in " ".join(out["reasons"])


def test_a_diff_the_classifier_cannot_read_gets_the_strict_numbers(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT}, base_ref=False)
    out = _dry(repo)
    assert out["size_class"] == "L", out
    assert "could not classify" in " ".join(out["reasons"])


def test_uncommitted_code_gets_the_strict_numbers(tmp_path):
    # The classifier reads committed HEAD, so a large edit not yet committed would read S.
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    (repo / "scripts/big.py").write_text(BIG_FILE)
    out = _dry(repo)
    assert out["size_class"] == "L", out
    assert "uncommitted" in " ".join(out["reasons"]) and "scripts/big.py" in " ".join(out["reasons"])


# --- the receipts follow the class --------------------------------------------------

def _review(repo: Path, kind: str) -> subprocess.CompletedProcess:
    claim = _issue(repo, "record-review", kind)
    if claim.returncode != 0:
        return claim
    art = repo / f"{kind}-review.md"
    art.write_text(f"{kind} reviewer ran, found nothing\n")
    return _issue(repo, "complete-review", kind, "--verdict", "approve", "--evidence-file", str(art))


def test_an_s_issue_is_reviewed_after_the_standard_pass_alone(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    assert _review(repo, "standard").returncode == 0
    assert _state(repo)["receipts"]["reviewed"], "an S issue still waited for an adversarial pass"
    r = _issue(repo, "record-review", "adversarial")
    assert r.returncode == 2 and "0/0" in r.stderr, r.stdout + r.stderr


def _close_ready(repo: Path) -> None:
    assert _issue(repo, "verify").returncode == 0
    assert _review(repo, "standard").returncode == 0
    assert _issue(repo, "triage").returncode == 0
    spec = repo / ".prd-os/issues/probe-1.md"          # close's deliverables lock
    spec.write_text(spec.read_text().replace("- [ ]", "- [x]"))


def test_an_s_issue_closes_on_one_standard_review_and_two_repeats(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    _close_ready(repo)
    r = _issue(repo, "close")
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_s_review_does_not_close_a_change_that_grew_to_l(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    _close_ready(repo)
    _commit(repo, {"scripts/big.py": BIG_FILE})
    assert _issue(repo, "verify").returncode == 0           # re-verified at L: 10 repeats
    r = _issue(repo, "close")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "size class L" in r.stderr and "adversarial" in r.stderr


def test_s_repeats_do_not_close_a_change_that_grew_to_l(tmp_path):
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    _close_ready(repo)
    _commit(repo, {"scripts/big.py": BIG_FILE})
    assert _review(repo, "adversarial").returncode == 0      # reviews whole at L; repeats are not
    r = _issue(repo, "close")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "under the minimum" in r.stderr and "size class L" in r.stderr


def test_a_close_refused_for_uncommitted_code_names_the_file(tmp_path):
    # PR #620 review, major 1: an uncommitted patch made close read L and refuse the S
    # repeats, and the message said "size class L" with no cause, so the agent re-verified
    # instead of committing.
    repo = _sized_repo(tmp_path, {"scripts/tool.py": SMALL_EDIT})
    _close_ready(repo)
    (repo / "scripts/tool.py").write_text(SMALL_EDIT + "\n\ndef patched():\n    return 8\n")
    r = _issue(repo, "close")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "uncommitted change to scripts/tool.py" in r.stderr and "Commit it" in r.stderr, r.stderr
