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
import threading
import time
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

    def __init__(self, board=None):
        self.created = None
        self.resolved_labels = {}   # id -> name, only for names actually asked for
        self.resolved_projects = {}
        # The Linear side of the world, SHARED across runs when a test passes one
        # in. Linear is the only store that survives a failed ledger append, so a
        # stub with per-run memory could not express the bug being tested.
        self.board = [] if board is None else board

    def graphql(self, query, variables):
        q = " ".join(query.split())
        # Checked before `issueCreate`: the dedup read is a query on `issues(`,
        # and a substring test for "issues" would swallow it.
        if "issues(" in q:
            needle = variables.get("q") or ""
            return {"issues": {"nodes": [
                {"identifier": i["identifier"]} for i in self.board
                if needle and needle in (i.get("description") or "")]}}
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
            ident = f"ASK-99{len(self.board) + 9}"
            self.board.append({"identifier": ident,
                               "description": variables["input"]["description"]})
            return {"issueCreate": {"success": True,
                                    "issue": {"id": "i1", "identifier": ident}}}
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


class InterruptedPromotionTest(unittest.TestCase):
    """A half-finished promotion must not become a second issue (Codex, PR #136).

    The create and the ledger append are two writes to two systems, and only one
    of them can be taken back. When the append failed the row stayed `open`, so
    the next run passed the status check and filed a SECOND permanent issue for
    one finding. The lock added on PR #120 does not reach this: it serializes two
    runs happening AT ONCE, and says nothing about a run that already finished
    halfway and left the ledger telling a lie.

    The append is broken with a read-only ledger file rather than by patching
    the script's own function, so the failure enters through the same door a real
    one would (a read-only checkout, a full disk) and the code under test is the
    shipped code.
    """

    def _setup(self, tmp):
        root = Path(tmp)
        (root / ".prd-os").mkdir(parents=True, exist_ok=True)
        ledger = root / ".prd-os" / "spillover.jsonl"
        ledger.write_text(json.dumps({
            "id": "sp-test01", "status": "open", "severity": "major",
            "source": "ASK-457", "description": "the conveyor is dead"}) + "\n")
        (root / "dor.md").write_text(DOR)
        return root, ledger

    def _run(self, root, stub, project="kipi-system"):
        mod = load_promote()
        mod.linear_module = lambda: stub
        old_argv, old_env = sys.argv, dict(os.environ)
        sys.argv = ["spillover-promote.py", "sp-test01", "--title", "conveyor test",
                    "--dor-file", str(root / "dor.md"), "--repo-root", str(root)]
        os.environ["KIPI_LINEAR_PROJECT"] = project
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = mod.main()
        except Exception as exc:
            # An uncaught crash is one of the shapes this defect takes, so the
            # reproducer has to survive it and go on to the RETRY. Letting it
            # propagate would end the test at the crash and never measure the
            # duplicate, which is the finding.
            rc, _ = 70, err.write(f"UNCAUGHT {type(exc).__name__}: {exc}\n")
        finally:
            sys.argv = old_argv
            os.environ.clear()
            os.environ.update(old_env)
        return rc, err.getvalue()

    def test_a_failed_append_does_not_become_a_duplicate_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, ledger = self._setup(tmp)
            board = []                      # Linear: survives the failed append

            os.chmod(ledger, 0o444)
            rc1, err1 = self._run(root, RecordingLinear(board))
            os.chmod(ledger, 0o644)

            self.assertEqual(len(board), 1,
                             "fixture invalid: run 1 did not create the issue")
            rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["status"], "open",
                             "fixture invalid: the append was not actually blocked")

            # THE FINDING. This is the run that used to file the duplicate, and
            # it is asserted before the message-quality checks below so that a
            # regression fails here rather than on the wording.
            rc2, err2 = self._run(root, RecordingLinear(board))
            self.assertEqual(
                len(board), 1,
                f"{len(board)} Linear issues for one finding: the retry after a "
                "failed append filed a permanent duplicate")
            self.assertEqual(rc2, 0, f"the retry did not repair the ledger: {err2}")
            rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["status"], "promoted")
            self.assertEqual(rows[-1]["linear_ref"], board[0]["identifier"],
                             "the ledger must point at the issue that exists, "
                             "not at one this run invented")

            # And run 1 has to have been recoverable by a human, not a traceback.
            self.assertNotEqual(rc1, 70, f"run 1 crashed instead of refusing: {err1}")
            self.assertNotEqual(rc1, 0, "a promotion whose ledger append failed "
                                        "must not report success")
            self.assertIn(board[0]["identifier"], err1,
                          "the failure must name the issue that now exists, or "
                          "nobody can recover it")

    def test_the_repair_run_does_not_need_the_project_to_resolve(self):
        """The issue is already on the board. A name that fails to resolve must
        not be able to keep the ledger `open` against it forever."""
        with tempfile.TemporaryDirectory() as tmp:
            root, ledger = self._setup(tmp)
            board = [{"identifier": "ASK-777",
                      "description": "Promoted from spillover `sp-test01` (severity: major)"}]
            stub = RecordingLinear(board)
            rc, err = self._run(root, stub, project="no-such-project")
            self.assertEqual(rc, 0, f"the repair path refused: {err}")
            self.assertIsNone(stub.created, "the repair path created an issue")
            rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
            self.assertEqual(rows[-1]["linear_ref"], "ASK-777")


class ConcurrentPromotionTest(unittest.TestCase):
    """One finding may become ONE issue, even when two runs promote it at once.

    Codex major on PR #120: the open-state read, the issueCreate and the ledger
    append were three separate steps with nothing serializing them. The ratchet
    makes that concurrency ordinary rather than exotic -- it fires PostToolUse in
    every agent session, and after the git-common-dir fix every worktree in the
    set shares ONE ledger. Two agents editing the same file both see `open` and
    both file. A duplicate Linear issue is permanent: nothing in the conveyor
    de-duplicates, and the worker would dispatch two runs at the same fix.

    The race is made deterministic rather than raced for. Both threads are held
    at a barrier until each has passed the status check, then the create is slow
    enough that the second is inside the window while the first is still in it.
    Unlocked that yields two creates every run; there is no timing in which it
    yields one.
    """

    def _run_two(self, tmp, break_prd_runner=False):
        root = Path(tmp)
        (root / ".prd-os").mkdir(parents=True, exist_ok=True)
        (root / ".prd-os" / "spillover.jsonl").write_text(json.dumps({
            "id": "sp-test01", "status": "open", "severity": "major",
            "source": "ASK-451", "description": "the conveyor is dead"}) + "\n")
        dor = root / "dor.md"
        dor.write_text(DOR)

        creates = []
        creates_lock = threading.Lock()
        start = threading.Barrier(2)

        class SlowLinear(RecordingLinear):
            """Widens the create window; the barrier decides the interleaving."""

            def graphql(self, query, variables):
                if "issueCreate" in " ".join(query.split()):
                    time.sleep(0.4)
                    with creates_lock:
                        creates.append(variables["input"]["title"])
                        n = len(creates)
                    return {"issueCreate": {
                        "success": True,
                        "issue": {"id": f"i{n}", "identifier": f"ASK-99{n}"}}}
                return super().graphql(query, variables)

        mod = load_promote()
        mod.linear_module = lambda: SlowLinear()
        if break_prd_runner:
            # The plugin is not importable: not checked out, a syntax error, a
            # missing dependency. `prd_runner()` swallows all of those and
            # returns None, which is exactly what this stands in for.
            mod.prd_runner = lambda repo_root: None

        sys.argv = ["spillover-promote.py", "sp-test01", "--title", "conveyor test",
                    "--dor-file", str(dor), "--repo-root", str(root)]
        os.environ["KIPI_LINEAR_PROJECT"] = "kipi-system"

        rcs = {}

        def promote(tag):
            # Both threads clear the status check before either can create.
            # Without that barrier this would be a coin flip on scheduler luck,
            # and a reproducer that only sometimes reproduces is not one.
            start.wait(timeout=10)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rcs[tag] = mod.main()

        threads = [threading.Thread(target=promote, args=(i,)) for i in range(2)]
        old_argv, old_env = sys.argv, dict(os.environ)
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
                self.assertFalse(t.is_alive(), "a promotion never finished (deadlock?)")
        finally:
            sys.argv = old_argv
            os.environ.clear()
            os.environ.update(old_env)
        return creates, rcs, root

    def test_two_concurrent_promotions_create_one_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            creates, rcs, root = self._run_two(tmp)
            self.assertEqual(len(creates), 1,
                             f"{len(creates)} Linear issues for one finding: the "
                             "check/create/append is not serialized")
            self.assertEqual(sorted(rcs.values()), [0, 2],
                             "the loser must REFUSE (exit 2), not report success")

    def test_the_loser_appends_no_second_promoted_row(self):
        """A second `promoted` row would make the ledger claim two promotions."""
        with tempfile.TemporaryDirectory() as tmp:
            _, _, root = self._run_two(tmp)
            rows = [json.loads(l) for l in
                    (root / ".prd-os" / "spillover.jsonl").read_text().splitlines()
                    if l.strip()]
            promoted = [r for r in rows if r.get("status") == "promoted"]
            self.assertEqual(len(promoted), 1,
                             f"{len(promoted)} promoted rows for one finding")


class LockUnavailableTest(ConcurrentPromotionTest):
    """The serialization must not depend on the plugin being importable (ASK-457).

    Codex major, PR #136: the lock is IMPORTED from prd_runner, and when that
    import came back None the promotion proceeded UNLOCKED with a warning. The
    warning is printed to a stderr nobody blocks on, and the duplicate Linear
    issue it permits is permanent.

    That degrade was inherited from `_spillover_lock`, where it is correct and
    for a different reason: a read-only DIRECTORY cannot hold a lock file at
    all, so refusing would turn a working resolve into a traceback. A missing
    MODULE is not that. The directory is writable, `flock` is in the standard
    library, and the lock path is derived by this script already -- so there is
    nothing to degrade FROM. Degrading here traded a permanent duplicate for an
    import that could simply have been done without.

    Same barrier, same slow create as the parent class. The only change is that
    prd_runner is unavailable, which is the condition under test.
    """

    def test_two_concurrent_promotions_create_one_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            creates, rcs, _ = self._run_two(tmp, break_prd_runner=True)
            self.assertEqual(len(creates), 1,
                             f"{len(creates)} Linear issues for one finding: with "
                             "prd_runner unavailable the promotion ran unlocked")
            self.assertEqual(sorted(rcs.values()), [0, 2],
                             "the loser must REFUSE (exit 2), not report success")

    def test_the_loser_appends_no_second_promoted_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, root = self._run_two(tmp, break_prd_runner=True)
            rows = [json.loads(l) for l in
                    (root / ".prd-os" / "spillover.jsonl").read_text().splitlines()
                    if l.strip()]
            promoted = [r for r in rows if r.get("status") == "promoted"]
            self.assertEqual(len(promoted), 1,
                             f"{len(promoted)} promoted rows for one finding")

    def test_it_locks_the_same_file_prd_runner_would_have(self):
        """A private second lock path would serialize promotions against each
        other and against NOTHING else -- a concurrent `resolve` or `reclassify`
        takes `spillover.jsonl.lock`, so the fallback has to take that one too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".prd-os").mkdir(parents=True)
            mod = load_promote()
            mod.prd_runner = lambda repo_root: None
            with mod.ledger_lock(root):
                pass
            self.assertTrue((root / ".prd-os" / "spillover.jsonl.lock").exists(),
                            "the fallback did not lock the shared ledger lock file")


class ReadOnlyLockTest(unittest.TestCase):
    """A lock that CANNOT be taken still degrades, loudly (ASK-457).

    The read-only sandbox case is real and every Codex round this session ran in
    one. Refusing to promote there would trade a recoverable race for a stopped
    conveyor, which is the trade `_spillover_lock` already refused to make.
    """

    def test_an_unwritable_directory_warns_and_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".prd-os").mkdir(parents=True)
            mod = load_promote()
            mod.prd_runner = lambda repo_root: None
            os.chmod(root / ".prd-os", 0o500)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stderr(buf):
                    with mod.ledger_lock(root):
                        ran = True
            finally:
                os.chmod(root / ".prd-os", 0o700)
            self.assertTrue(ran, "an unlockable directory must not stop a promotion")
            self.assertIn("UNLOCKED", buf.getvalue(),
                          "an unlocked promotion has to say so out loud")


if __name__ == "__main__":
    unittest.main(verbosity=2)
