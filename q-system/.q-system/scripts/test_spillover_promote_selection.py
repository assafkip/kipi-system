#!/usr/bin/env python3
"""The conveyor test: does what spillover-promote.py FILES get PICKED UP? (ASK-451)

why this shape: spillover-promote.py and linear-worker.sh were each tested alone
and each passed, while the thing they exist to do -- move a confirmed finding
into a queue a machine actually drains -- was broken the whole time. A producer
test that asserts "an issue was created" and a consumer test that asserts "a
correctly-labelled issue is picked" are both green against a payload the
consumer would silently drop. That gap is the entire defect.

So this test refuses to own a copy of either side:

  * `ready()` / `in_this_repo()` are AST-extracted from the SHIPPED
    linear-worker.sh heredoc and executed. Rename or re-scope the predicate and
    the extractor fails loudly instead of testing a stale duplicate.
  * the payload is whatever the SHIPPED spillover-promote.py main() hands to
    issueCreate, captured by stubbing the ONE seam that reaches the network
    (`linear_module`). No live Linear call, and no hand-written payload that
    could agree with my assumption instead of with the code.

The id->name inversion is deliberately strict. `ready()` reads label and project
NAMES; the payload carries UUIDs. If the script ever puts an id in the payload
it did not resolve by name through the stub, the inversion raises rather than
guessing a name -- otherwise this test could manufacture the very selection it
is supposed to be measuring.
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMOTE = HERE / "spillover-promote.py"
WORKER = HERE / "linear-worker.sh"

# Measured from the live board 2026-08-06 (read-only MCP list calls), not
# invented: team ASK carries label `owner:sana` and project `kipi-system`.
# A fixture I make up tests my assumption; these came from the producer.
LABEL_IDS = {"owner:sana": "a90dd212-40ec-4996-975a-9afce63f505d"}
PROJECT_IDS = {"kipi-system": "00bec4fd-cdd1-4d5a-992a-4ae3319c2d0a"}
TEAM_ID = "team-ask-uuid"

# A new Linear issue lands in the team default state. Every state on team ASK
# that a CREATE can produce is Backlog(backlog) or Todo(unstarted), both of
# which ready() accepts; the started/completed/canceled types are only
# reachable by a later transition. Enumerated from list_issue_statuses, so this
# is the measured set and not a guess at "probably backlog".
CREATE_STATE_TYPES = ("backlog", "unstarted")


# --------------------------------------------------------------------------
# Drive the SHIPPED consumer predicates, do not reimplement them.
# --------------------------------------------------------------------------
def worker_predicates(repo_project: str):
    """AST-extract ready()/in_this_repo()/project_of() out of linear-worker.sh."""
    text = WORKER.read_text()
    blocks, cur = [], None
    for line in text.splitlines():
        if cur is None:
            if line.rstrip().endswith("<<'PY'"):
                cur = []
            continue
        if line.strip() == "PY":
            blocks.append("\n".join(cur))
            cur = None
        else:
            cur.append(line)
    hits = [b for b in blocks if "def ready(" in b]
    if len(hits) != 1:
        raise AssertionError(
            f"expected exactly 1 heredoc defining ready() in {WORKER}, found "
            f"{len(hits)}. The consumer moved; this test is measuring nothing.")

    tree = ast.parse(hits[0])
    want = {"project_of", "in_this_repo", "ready"}
    keep = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in want]
    missing = want - {n.name for n in keep}
    if missing:
        raise AssertionError(f"linear-worker.sh no longer defines {missing}")

    ns = {"os": os, "repo_project": repo_project}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(WORKER), "exec"), ns)
    return ns


# --------------------------------------------------------------------------
# Drive the SHIPPED producer, stubbing only the network seam.
# --------------------------------------------------------------------------
class RecordingLinear:
    """Stands in for linear-sync.py. Records every query; serves known names."""

    ISSUE_CREATE = "mutation($input: IssueCreateInput!) { issueCreate(input: $input) }"

    def __init__(self):
        self.created = None
        self.resolved_labels = {}   # id -> name, only for names actually asked for
        self.resolved_projects = {}

    def graphql(self, query, variables):
        q = " ".join(query.split())
        if "teams(" in q and "issueLabels" not in q:
            return {"teams": {"nodes": [{"id": TEAM_ID}]}}
        if "issueLabels" in q:
            name = variables.get("name")
            node = ([{"id": LABEL_IDS[name], "name": name}]
                    if name in LABEL_IDS else [])
            for n in node:
                self.resolved_labels[n["id"]] = n["name"]
            return {"issueLabels": {"nodes": node}}
        if "projects(" in q:
            name = variables.get("name")
            node = ([{"id": PROJECT_IDS[name], "name": name}]
                    if name in PROJECT_IDS else [])
            for n in node:
                self.resolved_projects[n["id"]] = n["name"]
            return {"projects": {"nodes": node}}
        if "issueCreate" in q:
            self.created = variables["input"]
            return {"issueCreate": {"success": True,
                                    "issue": {"id": "i1", "identifier": "ASK-999"}}}
        raise AssertionError(f"stub got an unhandled query: {q[:120]}")


def load_promote():
    spec = importlib.util.spec_from_file_location("spillover_promote", PROMOTE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


DOR = (
    "**Allowed files** -- q-system/.q-system/scripts/spillover-promote.py\n"
    "**Acceptance** -- [ ] the promoted issue is selected by linear-worker.\n"
    "[ ] a failure shows as the worker reporting 0 ready while the issue exists.\n")


def run_promote(tmp, repo_project=None, extra_env=None):
    """Run the real main() against a real ledger; return (rc, stub)."""
    root = Path(tmp)
    (root / ".prd-os").mkdir(parents=True, exist_ok=True)
    (root / ".prd-os" / "spillover.jsonl").write_text(json.dumps({
        "id": "sp-test01", "status": "open", "severity": "major",
        "source": "ASK-451", "description": "the conveyor is dead"}) + "\n")

    mod = load_promote()
    stub = RecordingLinear()
    mod.linear_module = lambda: stub

    dor = root / "dor.md"
    dor.write_text(DOR)

    argv = ["spillover-promote.py", "sp-test01", "--title", "conveyor test",
            "--dor-file", str(dor), "--repo-root", str(root)]
    old_argv, old_env = sys.argv, dict(os.environ)
    sys.argv = argv
    if repo_project is not None:
        os.environ["KIPI_LINEAR_PROJECT"] = repo_project
    else:
        os.environ.pop("KIPI_LINEAR_PROJECT", None)
    os.environ.update(extra_env or {})
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)
    return rc, stub, root


def issue_as_worker_sees_it(stub, state_type="backlog"):
    """Invert the payload's UUIDs back through names the script actually resolved."""
    p = stub.created
    assert p is not None, "spillover-promote.py never called issueCreate"

    labels = []
    for lid in p.get("labelIds", []):
        if lid not in stub.resolved_labels:
            raise AssertionError(
                f"payload carries label id {lid} that was never resolved by name; "
                "refusing to invent a name for it")
        labels.append(stub.resolved_labels[lid])

    pid = p.get("projectId")
    if pid is None:
        project = None
    elif pid not in stub.resolved_projects:
        raise AssertionError(
            f"payload carries project id {pid} that was never resolved by name")
    else:
        project = stub.resolved_projects[pid]

    return {
        "identifier": "ASK-999",
        "title": p.get("title"),
        "description": p.get("description") or "",
        "state": {"name": state_type, "type": state_type},
        "project": ({"name": project} if project else None),
        "labels": {"nodes": [{"name": n} for n in labels]},
    }


def why_not_ready(issue):
    labels = {l["name"] for l in issue["labels"]["nodes"]}
    reasons = []
    if "owner:sana" not in labels:
        reasons.append("missing label owner:sana")
    if (issue.get("project") or {}).get("name") is None:
        reasons.append("project unset (worker: unset project is NOT this repo)")
    if "Definition of Ready" not in issue["description"]:
        reasons.append("no Definition of Ready in description")
    return reasons


class TestPromotedIssueIsSelectable(unittest.TestCase):

    def test_promoted_issue_is_picked_up_by_the_worker(self):
        """The end-to-end claim: what the producer files, the consumer picks."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, stub, _ = run_promote(tmp, repo_project="kipi-system")
            self.assertEqual(rc, 0, "promote did not succeed")
            preds = worker_predicates("kipi-system")
            for st in CREATE_STATE_TYPES:
                issue = issue_as_worker_sees_it(stub, st)
                self.assertTrue(
                    preds["ready"](issue),
                    f"linear-worker.sh would DROP the promoted issue "
                    f"(state={st}): {'; '.join(why_not_ready(issue)) or 'unknown'}")

    def test_issue_for_another_repo_is_not_selected_here(self):
        """A promotion aimed at another repo must not be drained by this checkout."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, stub, _ = run_promote(tmp, repo_project="kipi-system")
            self.assertEqual(rc, 0)
            issue = issue_as_worker_sees_it(stub)
            preds = worker_predicates("some-other-repo")
            self.assertFalse(preds["ready"](issue),
                             "a kipi-system issue was selected by another repo")

    def test_promoting_twice_creates_one_issue(self):
        """Idempotency: the second run must refuse, not file a duplicate."""
        with tempfile.TemporaryDirectory() as tmp:
            rc1, stub1, root = run_promote(tmp, repo_project="kipi-system")
            self.assertEqual(rc1, 0)
            self.assertIsNotNone(stub1.created)

            mod = load_promote()
            stub2 = RecordingLinear()
            mod.linear_module = lambda: stub2
            dor = root / "dor.md"
            old_argv, old_env = sys.argv, dict(os.environ)
            sys.argv = ["spillover-promote.py", "sp-test01", "--title", "again",
                        "--dor-file", str(dor), "--repo-root", str(root)]
            # The project MUST resolve on the second run too. Without this the
            # rerun refused because root.name is a tmpdir that matches no Linear
            # project -- a rc==2 that had nothing to do with idempotency. The
            # M6 mutant (neutering the already-promoted check) SURVIVED against
            # that version: the assertion was green for the wrong reason.
            os.environ["KIPI_LINEAR_PROJECT"] = "kipi-system"
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    rc2 = mod.main()
            finally:
                sys.argv = old_argv
                os.environ.clear()
                os.environ.update(old_env)
            self.assertEqual(rc2, 2, "second promote should refuse")
            self.assertIn("promoted", err.getvalue(),
                          "refusal must be the already-promoted guard, not "
                          f"some other refusal: {err.getvalue()!r}")
            self.assertIsNone(stub2.created,
                              "second promote created a DUPLICATE issue")

    def test_unknown_project_refuses_instead_of_filing_an_invisible_issue(self):
        """The guard that costs one promotion instead of the conveyor."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, stub, root = run_promote(tmp, repo_project="no-such-project")
            self.assertEqual(rc, 2, "unknown project should refuse")
            self.assertIsNone(stub.created,
                              "filed an issue no worker could ever see")
            rows = [json.loads(l) for l in
                    (root / ".prd-os" / "spillover.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["status"], "open",
                             "refused promotion must leave the row open")

    def test_unknown_label_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".prd-os").mkdir(parents=True)
            (root / ".prd-os" / "spillover.jsonl").write_text(json.dumps({
                "id": "sp-test01", "status": "open", "severity": "major",
                "source": "ASK-451", "description": "x"}) + "\n")
            dor = root / "dor.md"
            dor.write_text(DOR)
            mod = load_promote()
            stub = RecordingLinear()
            mod.linear_module = lambda: stub
            # Drives the REAL resolve+refuse path with a name the board lacks.
            mod.REQUIRED_LABELS = ("owner:nobody",)
            old_argv, old_env = sys.argv, dict(os.environ)
            sys.argv = ["spillover-promote.py", "sp-test01", "--title", "t",
                        "--dor-file", str(dor), "--repo-root", str(root)]
            os.environ["KIPI_LINEAR_PROJECT"] = "kipi-system"
            try:
                rc = mod.main()
            finally:
                sys.argv = old_argv
                os.environ.clear()
                os.environ.update(old_env)
            self.assertEqual(rc, 2, "unknown label should refuse")
            self.assertIsNone(stub.created)

    def test_promoting_from_a_worktree_uses_the_shared_ledger(self):
        """The ledger is per-worktree-set, not per-worktree (sp-d3bdbdc9).

        Driven from a REAL `git worktree`, because the whole defect is that
        repo_root and the git-common-dir parent are the same directory in the
        main checkout and only diverge in a worktree. A test run from the main
        checkout passes against the broken code.
        """
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "mainrepo"
            (main / ".prd-os").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(main)], check=True)
            subprocess.run(["git", "-C", str(main), "commit", "-q", "--allow-empty",
                            "-m", "x"], check=True,
                           env={**os.environ, "GIT_AUTHOR_NAME": "t",
                                "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                "GIT_COMMITTER_EMAIL": "t@t"})
            # The REAL prd_runner, so the resolution under test is the shipped
            # rule and not a stand-in that agrees with me.
            dst = main / "plugins" / "prd-os" / "scripts"
            dst.parent.mkdir(parents=True)
            shutil.copytree(HERE.parents[2] / "plugins" / "prd-os" / "scripts", dst)

            (main / ".prd-os" / "spillover.jsonl").write_text(json.dumps({
                "id": "sp-wt01", "status": "open", "severity": "major",
                "source": "ASK-451", "description": "shared ledger"}) + "\n")

            wt = Path(tmp) / "wt"
            r = subprocess.run(["git", "-C", str(main), "worktree", "add", "-q",
                                str(wt), "HEAD"], capture_output=True, text=True)
            # Prove the setup, or a failed worktree add silently relocates this
            # test back into the main checkout, where broken code passes.
            self.assertEqual(r.returncode, 0, f"worktree add failed: {r.stderr}")
            self.assertTrue((wt / ".git").exists(), "no worktree at the target")
            self.assertFalse((wt / ".prd-os" / "spillover.jsonl").exists(),
                             "fixture invalid: the worktree already has a ledger")

            dor = Path(tmp) / "dor.md"
            dor.write_text(DOR)
            mod = load_promote()
            stub = RecordingLinear()
            mod.linear_module = lambda: stub
            old_argv, old_env = sys.argv, dict(os.environ)
            sys.argv = ["spillover-promote.py", "sp-wt01", "--title", "wt",
                        "--dor-file", str(dor), "--repo-root", str(wt)]
            os.environ["KIPI_LINEAR_PROJECT"] = "kipi-system"
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    rc = mod.main()
            finally:
                sys.argv = old_argv
                os.environ.clear()
                os.environ.update(old_env)

            self.assertEqual(rc, 0, f"promote from a worktree failed: {err.getvalue()}")
            self.assertFalse((wt / ".prd-os" / "spillover.jsonl").exists(),
                             "wrote a PRIVATE ledger inside the worktree")
            rows = [json.loads(l) for l in
                    (main / ".prd-os" / "spillover.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["status"], "promoted",
                             "the shared ledger did not receive the promotion")

    def test_ledger_row_says_promoted_not_resolved(self):
        """Promoting is not fixing. A `resolved` here would launder the pile."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, _, root = run_promote(tmp, repo_project="kipi-system")
            self.assertEqual(rc, 0)
            rows = [json.loads(l) for l in
                    (root / ".prd-os" / "spillover.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["status"], "promoted")
            self.assertEqual(rows[-1]["linear_ref"], "ASK-999")


if __name__ == "__main__":
    unittest.main(verbosity=2)
