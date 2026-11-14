"""ASK-4949: import-review takes pr-review-agent.sh's verdict as the standard review.

The fleet's one reviewer posts a verdict comment on the PR and the kipi/reviewer-approved
status on the head it read. `close` only took a receipt from /issue-review, so on chief
PR #433 the receipt was made by hand. import-review does it from the evidence: approve
imports, anything else refuses, and a head that moved refuses.

Every fixture is a virgin repo built by the real prd_split.py (the size-class test's
builder, an S diff so one standard review makes the receipt whole). `gh` is a fake on PATH
that answers from a JSON file, so no test reaches GitHub.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_ask3827_fixtures", DSSE / "test_size_class_depth.py")
_sz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sz)
_issue, _state = _sz._issue, _sz._state

REPO = "owner/name"
PR = 7
APPROVE_BODY = "## Verdict: APPROVE WITH NITS\n\nFindings: 1 (blocker 0, major 0, minor 0, nit 1).\n"
CHANGES_BODY = "## Verdict: REQUEST CHANGES\n\nFindings: 1 (blocker 1, major 0, minor 0, nit 0).\n"

FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
fx = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
a = sys.argv[1:]
if a[:2] == ["pr", "view"]:
    print(json.dumps({"headRefOid": fx["head"]}))
elif a[0] == "api" and "/statuses" in a[1]:
    print(json.dumps(fx["statuses"].get(a[1].split("/commits/")[1].split("/")[0], [])))
elif a[0] == "api" and "/issues/comments/" in a[1]:
    print(json.dumps(fx["comments"][a[1].rsplit("/", 1)[1]]))
else:
    sys.exit("fake gh: unexpected " + " ".join(a))
'''


@pytest.fixture(autouse=True)
def _no_worker_classifier(monkeypatch):
    monkeypatch.delenv("KIPI_SIZE_CLASSIFIER", raising=False)


def _head(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True).stdout.strip()


def _env(tmp_path: Path, fixture: dict) -> dict:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    fx = tmp_path / "gh.json"
    fx.write_text(json.dumps(fixture))
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_FIXTURE": str(fx)}


def _verdict(sha: str, state: str, body: str, *, desc="APPROVE WITH NITS") -> dict:
    url = f"https://github.com/{REPO}/pull/{PR}#issuecomment-555"
    return {"statuses": {sha: [{"context": "kipi/reviewer-approved", "state": state,
                                "target_url": url, "description": desc,
                                "creator": {"login": "reviewer"}}]},
            "comments": {"555": {"user": {"login": "reviewer"}, "body": body,
                                 "issue_url": f"https://api.github.com/repos/{REPO}/issues/{PR}"}}}


def _import(repo: Path, env: dict):
    return _issue(repo, "import-review", "--pr", str(PR), "--repo", REPO, env_extra=env)


def _s_repo(tmp_path):
    return _sz._sized_repo(tmp_path, {"scripts/tool.py": _sz.SMALL_EDIT})


def test_an_approve_on_the_current_head_imports_and_writes_the_receipt(tmp_path):
    repo = _s_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", APPROVE_BODY)}))
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    st = _state(repo)
    assert st["receipts"]["reviewed"], st["receipts"]
    done = st["review_completions"]["standard"]
    assert done["verdict"].startswith("APPROVE WITH NITS (imported from pr-review-agent.sh")
    assert done["imported"]["head"] == sha and done["imported"]["pr"] == PR
    art = Path(out["artifact"])
    assert art.name.endswith("-standard-r1.md")
    assert art.read_bytes() == APPROVE_BODY.encode("utf-8")   # byte for byte


def test_a_request_changes_verdict_refuses_and_claims_no_slot(tmp_path):
    repo = _s_repo(tmp_path)
    sha = _head(repo)
    fx = {"head": sha, **_verdict(sha, "failure", CHANGES_BODY, desc="REQUEST CHANGES")}
    r = _import(repo, _env(tmp_path, fx))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Only an approve imports" in r.stderr
    st = _state(repo)
    assert not st["receipts"].get("reviewed")
    assert st["review_rounds"]["standard"] == 0, "a refused import burned a review slot"


def test_an_approve_body_under_a_failure_status_still_refuses(tmp_path):
    # The status is the gate. A comment that reads approve does not outvote it.
    repo = _s_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "failure", APPROVE_BODY)}))
    assert r.returncode == 2, r.stdout + r.stderr


def test_a_head_that_moved_since_the_review_refuses(tmp_path):
    # The approve sits on the old head; the PR (and this tree) moved on by one commit.
    repo = _s_repo(tmp_path)
    old = _head(repo)
    _sz._commit(repo, {"scripts/tool.py": _sz.SMALL_EDIT + "\n# one more line\n"})
    new = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": new, **_verdict(old, "success", APPROVE_BODY)}))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "head moved since its review" in r.stderr
    assert not _state(repo)["receipts"].get("reviewed")


def test_a_tree_behind_the_pr_head_refuses(tmp_path):
    # The PR head carries an approve, but this tree is not at it: different code.
    repo = _s_repo(tmp_path)
    pr_head = "f" * 40
    r = _import(repo, _env(tmp_path, {"head": pr_head, **_verdict(pr_head, "success", APPROVE_BODY)}))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "this tree is at" in r.stderr
