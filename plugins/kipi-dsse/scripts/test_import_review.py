"""ASK-4949: issue_runner import-review takes pr-review-agent.sh's verdict as the standard review.

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
# The reviewer's own record: an echoed template block first, its verdict block last.
LOCAL_REVIEW_DEFAULT = ("prompt echo:\nFINDINGS:\nmajor|echoed template|z.py:1\nEND FINDINGS\n\n"
                        "review...\nFINDINGS:\nnit|name the constant|scripts/tool.py:4\n"
                        "END FINDINGS\n")

FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
fx = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
a = sys.argv[1:]
if a[:2] == ["pr", "view"]:
    print(json.dumps({"headRefOid": fx["head"]}))
elif a[0] == "api" and "/statuses" in a[1]:
    print(json.dumps(fx["statuses"].get(a[1].split("/commits/")[1].split("/")[0], [])))
elif a[0] == "api" and a[1].split("?")[0].endswith("/comments"):
    # every comment on the PR, one JSON object per line, as `--paginate --jq '.[]'` prints
    rows = fx.get("pr_comments") or [dict(c, id=int(k)) for k, c in fx["comments"].items()]
    for c in rows:
        print(json.dumps(c))
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


def _env(tmp_path: Path, fixture: dict, local_review: "str | None" = LOCAL_REVIEW_DEFAULT) -> dict:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    fx = tmp_path / "gh.json"
    fx.write_text(json.dumps(fixture))
    # The reviewer's local records, never the live ~/.config/kipi/pr-reviews. A counts-only
    # body (public repo) reads its rows from here (PR #819 round 1).
    reviews = tmp_path / "pr-reviews"
    if local_review is not None:
        reviews.mkdir(exist_ok=True)
        (reviews / f"{REPO.replace('/', '_')}__pr-{PR}-20261114-000000.md").write_text(local_review)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_FIXTURE": str(fx),
            "KIPI_PR_REVIEWS_DIR": str(reviews)}


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
    assert json.loads(r.stdout)["imported"] == ["standard"]   # S needs no adversarial kind
    st = _state(repo)
    assert st["receipts"]["reviewed"], st["receipts"]
    done = st["review_completions"]["standard"]
    assert done["verdict"].startswith("APPROVE WITH NITS (imported from pr-review-agent.sh")
    assert done["imported"]["head"] == sha and done["imported"]["pr"] == PR
    art = Path(done["artifact_path"])
    assert art.name.endswith("-standard-r1.md")
    assert art.read_bytes() == APPROVE_BODY.encode("utf-8")   # byte for byte


def _l_repo(tmp_path):
    return _sz._sized_repo(tmp_path, {"scripts/big.py": _sz.BIG_FILE})


def test_an_l_diff_with_one_imported_approve_gets_the_reviewed_receipt(tmp_path):
    # Founder ruling 2026-11-14: one review per issue through pr-review-agent.sh, which
    # records as claude-adversarial, so one approve fills both kinds L requires.
    repo = _l_repo(tmp_path)
    assert json.loads(_issue(repo, "record-review", "standard", "--dry").stdout)["size_class"] == "L"
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", APPROVE_BODY)}))
    assert r.returncode == 0, r.stdout + r.stderr
    st = _state(repo)
    assert st["receipts"]["reviewed"], st["receipts"]
    for kind in ("standard", "adversarial"):
        done = st["review_completions"][kind]
        assert "founder ruling 2026-11-14" in done["verdict"], done
        assert f"counts as the {kind} review" in done["verdict"], done
        assert Path(done["artifact_path"]).read_bytes() == APPROVE_BODY.encode("utf-8")


def test_an_l_diff_with_nothing_imported_still_refuses_the_receipt(tmp_path):
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    fx = {"head": sha, **_verdict(sha, "failure", CHANGES_BODY, desc="REQUEST CHANGES")}
    assert _import(repo, _env(tmp_path, fx)).returncode == 2
    # And the old path alone, one standard completion, still leaves the receipt unset.
    assert _issue(repo, "record-review", "standard").returncode == 0
    art = repo / "std.md"
    art.write_text("standard reviewer ran, found nothing\n")
    r = _issue(repo, "complete-review", "standard", "--verdict", "approve",
               "--evidence-file", str(art))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["awaiting"] == ["adversarial"]
    assert not _state(repo)["receipts"].get("reviewed")


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


# --- PR #815 round 1 (pr-review-agent.sh, REQUEST CHANGES) -------------------------------


def test_an_l_issue_with_a_stale_adversarial_claim_refuses_whole_and_burns_nothing(tmp_path):
    # Finding 1 (major): /issue-review claims the adversarial slot before codex runs, so
    # "class L, codex out" leaves adversarial 1/1 claimed. The import claimed and sealed
    # standard, then refused on adversarial: a refusal that burned a slot, and two retries
    # made the issue unclosable.
    repo = _l_repo(tmp_path)
    assert _issue(repo, "record-review", "adversarial").returncode == 0
    sha = _head(repo)
    env = _env(tmp_path, {"head": sha, **_verdict(sha, "success", APPROVE_BODY)})
    for _ in range(3):   # the operator's obvious next move is to retry
        r = _import(repo, env)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "adversarial: 1/1" in r.stderr, r.stderr
        assert r.stdout == ""
    st = _state(repo)
    assert st["review_rounds"]["standard"] == 0, "a refused import burned a review slot"
    assert not st.get("review_completions", {}).get("standard"), st.get("review_completions")
    assert not list((repo / ".prd-os/reviews").glob("*-standard-r*.md"))


def test_no_gh_on_path_is_a_one_line_refusal_not_a_traceback(tmp_path):
    # Finding 3 (minor): FileNotFoundError escaped the except tuple as rc=1 and a traceback.
    import shutil
    repo = _s_repo(tmp_path)
    bindir = tmp_path / "nogh"
    bindir.mkdir()
    for tool in ("git", "python3"):
        (bindir / tool).symlink_to(shutil.which(tool))
    r = _issue(repo, "import-review", "--pr", str(PR), "--repo", REPO,
               env_extra={"PATH": str(bindir)})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stderr and r.stderr.startswith("refusing import:"), r.stderr
    assert _state(repo)["review_rounds"]["standard"] == 0


@pytest.mark.parametrize("body", [
    "Verdict: APPROVE WITH NITS. Findings: 1. Review withheld: this repository is public.\n",
    "DEGRADED (Opus fallback, not an independent second opinion). Verdict: APPROVE. "
    "Findings: 0. Review withheld: this repository is public.\n",
])
def test_the_public_repo_floor_body_imports(tmp_path, body):
    # Finding 4 (minor): pr-verdict-lib.sh review_public_counts_line has no '## Verdict:'
    # heading, so a real approve under a success status refused.
    repo = _s_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", body)}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert _state(repo)["receipts"]["reviewed"]


def test_a_floor_body_with_a_non_approve_verdict_still_refuses(tmp_path):
    # Negative self-test for the floor pattern: it must not widen to any 'Verdict:' line.
    repo = _s_repo(tmp_path)
    sha = _head(repo)
    body = "Verdict: REQUEST CHANGES. Findings: 2. Review withheld: this repository is public.\n"
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", body)}))
    assert r.returncode == 2, r.stdout + r.stderr


def test_the_status_description_is_sealed_with_the_import(tmp_path):
    # Finding 5 (minor): 'delta <base>..<sha>' and DEGRADED live only in the status
    # description; dropping it sealed a delta approve as a full review with no trace.
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    desc = "delta 5b2c1894..7d415788: APPROVE WITH NITS"
    r = _import(repo, _env(tmp_path, {"head": sha,
                                      **_verdict(sha, "success", APPROVE_BODY, desc=desc)}))
    assert r.returncode == 0, r.stdout + r.stderr
    for kind in ("standard", "adversarial"):
        assert _state(repo)["review_completions"][kind]["imported"]["status_description"] == desc


# --- ASK-5005: the import carries every round's findings into the issue ledger ---------
#
# Chief PR #432: rounds 1 and 2 had 9 findings, one major. import-review sealed the approve
# and wrote no ledger rows, so `issue_findings.py list --only-pending` was empty and triage
# passed with nothing to check.

ROUND1 = ("## Verdict: REQUEST CHANGES\n\nReviewer engine: `claude`.\n\n```\nFINDINGS:\n"
          "major|the cap resets on restart|scripts/tool.py:12\n"
          "minor|a comment claims what the code does not|other/x.py:3|nonblocking\n"
          "END FINDINGS\n```\n\n--- reviewer output ---\n\nFINDINGS:\nminor|echoed template|a.py:1\n"
          "END FINDINGS\n")
ROUND2 = ("## Verdict: APPROVE WITH NITS\n\nReviewer engine: `claude`.\n\n```\nFINDINGS:\n"
          "nit|name the constant|tests/test_tool.py:4\n"
          "major|the cap resets on restart|scripts/tool.py:12\n"
          "END FINDINGS\n```\n")
STRANGER = ("## Verdict: REQUEST CHANGES\n\n```\nFINDINGS:\nblocker|not ours|scripts/tool.py:1\n"
            "END FINDINGS\n```\n")


def _rounds_fixture(sha: str) -> dict:
    fx = {"head": sha, **_verdict(sha, "success", ROUND2)}
    issue_url = f"https://api.github.com/repos/{REPO}/issues/{PR}"
    fx["pr_comments"] = [
        {"id": 400, "user": {"login": "reviewer"}, "body": ROUND1, "issue_url": issue_url},
        {"id": 450, "user": {"login": "someone-else"}, "body": STRANGER, "issue_url": issue_url},
        {"id": 555, "user": {"login": "reviewer"}, "body": ROUND2, "issue_url": issue_url},
        {"id": 600, "user": {"login": "reviewer"}, "body": STRANGER, "issue_url": issue_url},
    ]
    return fx


def _ledger(repo: Path) -> list:
    issue_id = _state(repo)["issue_id"]
    r = subprocess.run([sys.executable, str(DSSE / "issue_findings.py"), "list", issue_id],
                       cwd=repo, capture_output=True, text=True,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_every_imported_rounds_findings_reach_the_ledger(tmp_path):
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, _rounds_fixture(sha)))
    assert r.returncode == 0, r.stdout + r.stderr
    rows = _ledger(repo)
    # Round 1's two rows and round 2's nit. The major round 2 repeats is one row. The
    # stranger's blocker, the reviewer's comment after the approving one, and the echoed
    # block after the canonical one are not rows.
    assert sorted((x["severity"], x["affected_path"]) for x in rows) == [
        ("major", "scripts/tool.py"), ("minor", "other/x.py"), ("nit", "tests/test_tool.py")], rows
    for x in rows:
        assert x["disposition"] == "pending" and x["source"] == "claude-adversarial", x
        assert x["id"].startswith("finding-") and x["created_at"], x
    by_path = {x["affected_path"]: x for x in rows}
    assert by_path["other/x.py"]["out_of_scope"] is True
    assert by_path["scripts/tool.py"]["out_of_scope"] is False
    assert "scripts/tool.py:12" in by_path["scripts/tool.py"]["body"]
    assert "nonblocking" in by_path["other/x.py"]["body"]
    assert json.loads(r.stdout)["findings_added"] == 3
    # triage now has real rows: in-scope pending findings refuse the receipt
    t = _issue(repo, "triage")
    assert t.returncode != 0, t.stdout + t.stderr


def test_a_second_import_adds_no_duplicate_rows(tmp_path):
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    env = _env(tmp_path, _rounds_fixture(sha))
    assert _import(repo, env).returncode == 0
    r = _import(repo, env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_ledger(repo)) == 3
    out = json.loads(r.stdout)
    assert out["imported"] == [] and out["findings_added"] == 0, out


def test_a_refused_import_writes_no_findings(tmp_path):
    repo = _l_repo(tmp_path)
    assert _issue(repo, "record-review", "adversarial").returncode == 0   # abandoned slot
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, _rounds_fixture(sha)))
    assert r.returncode == 2, r.stdout + r.stderr
    assert _ledger(repo) == []


# --- ASK-4990 and PR 815 round 2 minor: a completed kind is skipped, never re-claimed ---

def test_on_m_a_completed_standard_is_kept_and_the_import_fills_adversarial(tmp_path):
    repo = _sz._sized_repo(tmp_path, {"scripts/mid.py": _sz.MID_FILE})
    assert json.loads(_issue(repo, "record-review", "standard", "--dry").stdout)["size_class"] == "M"
    assert _issue(repo, "record-review", "standard").returncode == 0
    art = repo / "std.md"
    art.write_text("standard reviewer ran\n")
    assert _issue(repo, "complete-review", "standard", "--verdict", "APPROVE",
                  "--evidence-file", str(art)).returncode == 0
    before = dict(_state(repo)["review_completions"]["standard"])
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", APPROVE_BODY)}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["imported"] == ["adversarial"]
    st = _state(repo)
    assert st["receipts"]["reviewed"], st["receipts"]
    assert st["review_rounds"] == {"standard": 1, "adversarial": 1}, st["review_rounds"]
    assert st["review_completions"]["standard"] == before   # the real review is untouched


# --- PR #819 round 1 -------------------------------------------------------------------

PUBLIC_BODY = ("## Verdict: APPROVE WITH NITS\n\nFindings: 2 (blocker 0, major 1, minor 1, nit 0). "
               "Reviewer engine: `claude`.\n\nThis repository is public, so the review text, the "
               "finding details and the diff are not posted here.\n")


def test_a_public_counts_only_round_reads_its_rows_from_the_local_review_record(tmp_path):
    # Major: the public-repo comment states findings but carries no block. The import sealed
    # with findings_added 0 and triage passed: ASK-5005 again, on kipi-system itself.
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", PUBLIC_BODY)}))
    assert r.returncode == 0, r.stdout + r.stderr
    rows = _ledger(repo)
    # the verdict block (last), not the echoed template before it
    assert [(x["severity"], x["affected_path"]) for x in rows] == [("nit", "scripts/tool.py")], rows


def test_a_public_round_with_no_local_record_refuses_and_claims_nothing(tmp_path):
    repo = _l_repo(tmp_path)
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", PUBLIC_BODY)},
                           local_review=None))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "state findings but carry no FINDINGS block" in r.stderr, r.stderr
    st = _state(repo)
    assert st["review_rounds"]["standard"] == 0 and not st["receipts"].get("reviewed")
    assert _ledger(repo) == []


def test_a_completed_request_changes_is_not_skipped(tmp_path):
    # Minor: a completed REQUEST CHANGES was skipped and the import sealed `reviewed` with no
    # override. It stays in the precheck and refuses at its cap, as before the PR. M, so
    # standard's cap is 1 (on L a second standard round is a legitimate new round).
    repo = _sz._sized_repo(tmp_path, {"scripts/mid.py": _sz.MID_FILE})
    assert _issue(repo, "record-review", "standard").returncode == 0
    art = repo / "std.md"
    art.write_text("standard reviewer found a blocker\n")
    assert _issue(repo, "complete-review", "standard", "--verdict",
                  "REQUEST CHANGES (blocker)", "--evidence-file", str(art)).returncode == 0
    sha = _head(repo)
    r = _import(repo, _env(tmp_path, {"head": sha, **_verdict(sha, "success", APPROVE_BODY)}))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "review cap reached for standard" in r.stderr, r.stderr
    assert not _state(repo)["receipts"].get("reviewed")
