"""Model routing is data the code reads (ASK-4013).

Founder, 2026-11-08, verbatim: "I want you to evaluate what kind of tickets can go
to sonnet and what kind of tickets can stay on Opus and make that a rule in code".
His concern, verbatim: "it's probably not going to create as good as code solutions
for open PRS and tickets".

Why this shape: before ASK-4013 the model was a literal in three call sites
(linear-worker.sh SECOND_RUNNER_FALLBACK, pr-review-agent.sh CLAUDE_MODEL,
linear-alert-triage.py TRIAGE_MODEL), the worker's main run named none and took
whatever ANTHROPIC_MODEL its parent exported (claude-opus-5 under dispatch, the
settings default "opus" alias by hand), and the reviewer's real model came from a
plist env var. Four places, three mechanisms, no evidence attached to any of them.
Now one table (q-system/.q-system/model-routing.json) says which job class runs on
which model and carries the evidence per row, and model_route.py is the only
reader. This test fails when a governed call site names a model directly again.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
SCRIPTS = QS / "scripts"
TABLE = QS / "model-routing.json"
sys.path.insert(0, str(SCRIPTS))
import model_route  # noqa: E402

# The call sites the table governs. Each must read model_route.py and name no model.
GOVERNED = ("linear-worker.sh", "pr-review-agent.sh", "linear-alert-triage.py")
MODEL_ID = re.compile(r"claude-(?:opus|sonnet|haiku|fable)-\d")


def literal_sites(path_name: str, text: str) -> list:
    """Code lines (whole-line comments skipped) that name a model id."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if MODEL_ID.search(s):
            hits.append(f"{path_name}:{n}: {s[:120]}")
    if path_name.endswith(".py"):
        # docstrings may cite a model in prose; only string constants that are code count
        import ast
        tree = ast.parse(text)
        docs = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant):
                docs.add(body[0].value.lineno)
        code = {node.lineno for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and MODEL_ID.search(node.value) and node.lineno not in docs}
        hits = [h for h in hits if int(h.split(":")[1]) in code]
    return hits


class Classify(unittest.TestCase):
    """Cases are real tickets; the comment names the PR the file list came from."""

    def cls(self, files, repo="kipi-system", text=""):
        return model_route.classify(repo=repo, files=files, text=text)

    def test_dispatcher_worker_reviewer_paths(self):
        self.assertEqual(self.cls(["q-system/.q-system/scripts/linear-worker.sh"]), "dispatcher-worker")
        self.assertEqual(self.cls(["kipi-dispatch.sh", "q-system/.q-system/scripts/test/test-x.sh"]), "dispatcher-worker")
        self.assertEqual(self.cls(["q-system/.q-system/scripts/pr-review-agent.sh"]), "dispatcher-worker")

    def test_guards_and_hooks_outrank_everything(self):
        self.assertEqual(self.cls(["q-system/hooks/destructive-op-deny.sh"]), "guards-hooks")
        self.assertEqual(self.cls([".claude/settings.json"]), "guards-hooks")
        self.assertEqual(self.cls(["q-system/.q-system/scripts/merge-bypass-gate.py"]), "guards-hooks")
        # a client repo touching a hook is still a guard change first
        self.assertEqual(self.cls(["q-system/hooks/x.sh"], repo="client-path"), "guards-hooks")

    def test_every_wired_hook_is_a_guard_change(self):
        # PR #664 round 1, major: a name matcher missed 38 of the 50 hook scripts
        # .claude/settings.json wires (*-lint.py, *-check.py, *-door.py). The
        # reviewer's reproducer, against the repo's own config.
        txt = (QS.parents[1] / ".claude" / "settings.json").read_text()
        wired = sorted(set(re.findall(r"q-system/\.q-system/[A-Za-z0-9_./-]+\.(?:py|sh)", txt)))
        self.assertGreater(len(wired), 20)
        miss = [p for p in wired if self.cls([p]) != "guards-hooks"]
        self.assertEqual(miss, [])

    def test_a_newly_wired_hook_is_picked_up_from_the_config(self):
        # negative self-test: the same file is single-code-file until a config runs it
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/q-system/x/plain-name.py"'}]}]}}))
            (root / "plugins" / "p" / "hooks").mkdir(parents=True)
            (root / "plugins" / "p" / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/also-plain.py"'}]}]}}))
            hooks = model_route.wired_hooks(root)
            self.assertEqual(hooks, {"q-system/x/plain-name.py", "plugins/p/scripts/also-plain.py"})
            self.assertEqual(model_route.classify(files=["q-system/x/plain-name.py"], hooks=hooks), "guards-hooks")
            self.assertEqual(model_route.classify(files=["plugins/p/scripts/also-plain.py"], hooks=hooks), "guards-hooks")
            self.assertEqual(model_route.classify(files=["q-system/x/plain-name.py"], hooks=set()), "single-code-file")

    def test_concurrency_from_the_ticket_text(self):
        self.assertEqual(self.cls(["q-system/.q-system/scripts/board_rows.py"],
                                  text="the ledger write races a second worker; take a flock"),
                         "concurrency-locks")
        # name tokens are anchored: "claim" inside a longer word is not a lock
        self.assertNotEqual(model_route.classify(files=["a/reclaimer.py"], hooks=set()), "concurrency-locks")

    def test_client_repo(self):
        # ASK-767, a client engagement's PR: a test-only change, still client work first
        self.assertEqual(self.cls(["tests/test_open_loops_skip.py"], repo="client-path"), "client-repo")
        # the CLI derives client-path from the checkout, never from a named slug
        with tempfile.NamedTemporaryFile("w", suffix=".files", delete=False) as fh:
            fh.write("src/collector.py\n")
        out = subprocess.run([sys.executable, str(SCRIPTS / "model_route.py"), "pick", "--job", "review",
                              "--files-from", fh.name, "--tree",
                              "/Users/x/projects/consulting/projects/example_instance"],
                             capture_output=True, text=True)
        Path(fh.name).unlink()
        self.assertIn("class=client-repo", out.stderr)

    def test_code_size_classes(self):
        # ASK-2388, kipi-system PR #500: one script plus its test
        self.assertEqual(self.cls(["q-system/.q-system/scripts/change-size.py",
                                   "q-system/.q-system/tests/test_change_size.py"]), "single-code-file")
        self.assertEqual(self.cls(["a/x.py", "b/y.sh"]), "multi-code-file")

    def test_non_code_classes(self):
        self.assertEqual(self.cls(["q-system/.q-system/tests/test_open_loops.py"]), "test-only")
        self.assertEqual(self.cls(["q-system/.q-system/heartbeat-jobs.json"]), "config-data")
        self.assertEqual(self.cls(["docs/autonomous-systems.md"]), "docs-text")

    def test_no_file_list_is_unknown(self):
        self.assertEqual(self.cls([]), "unknown")

    def test_dor_file_list_is_parsed(self):
        dor = ("## Definition of Ready\n\n* **Outcome:** x\n"
               "* **Files:** `q-system/.q-system/scripts/open-loops.py` (read-only), "
               "and `q-system/.q-system/tests/test_open_loops.py`.\n* **Check:** y\n")
        self.assertEqual(model_route.dor_files(dor), ["q-system/.q-system/scripts/open-loops.py",
                                                      "q-system/.q-system/tests/test_open_loops.py"])
        self.assertEqual(model_route.dor_files("no files line here"), [])

    def test_bare_field_dor_never_reads_not_doing(self):
        # PR #664 round 1, minor: the reviewer's shape. A bare **Files:** field with
        # no bullet; the first parser read on into **Not doing:** and routed by a
        # path the ticket is told not to touch.
        dor = ("## Definition of Ready\n\n**Outcome:** stop the open-loops writer from racing\n\n"
               "**Files:** `q-system/.q-system/scripts/open-loops.py`\n"
               "**Not doing:** `q-system/hooks/destructive-op-deny.sh`\n"
               "**Check:** `python3 q-system/.q-system/tests/test_open_loops.py`\n")
        self.assertEqual(model_route.dor_files(dor), ["q-system/.q-system/scripts/open-loops.py"])


class Table(unittest.TestCase):
    def setUp(self):
        self.t = json.loads(TABLE.read_text())

    def test_every_routed_row_has_a_model_and_evidence(self):
        for job, spec in self.t["jobs"].items():
            rows = spec.get("classes", {"*": spec})
            for cls, row in rows.items():
                self.assertIn(row.get("model"), self.t["known_models"], f"{job}/{cls}")
                self.assertTrue((row.get("evidence") or "").strip(), f"{job}/{cls} has no evidence")

    def test_code_jobs_cover_every_class(self):
        names = [c["name"] for c in self.t["classes"]] + ["unknown"]
        for job in ("worker", "review"):
            self.assertEqual(sorted(self.t["jobs"][job]["classes"]), sorted(names), job)

    def test_default_is_opus(self):
        self.assertIn("opus", self.t["default"])

    def test_risky_classes_stay_on_opus(self):
        for job in ("worker", "review"):
            for cls in ("guards-hooks", "dispatcher-worker", "concurrency-locks", "unknown"):
                self.assertIn("opus", self.t["jobs"][job]["classes"][cls]["model"], f"{job}/{cls}")

    def test_rows_are_the_opus_base_and_sonnet_comes_only_from_evidence(self):
        # PR #664 round 2, minor: a one-key edit could route a class to Sonnet on
        # 2 samples with CI green. Since ASK-4038 the rows stay the Opus base and a
        # Sonnet answer can only come from decide() over measured evidence.
        for job, spec in self.t["jobs"].items():
            rows = spec.get("classes", {"*": spec})
            for cls, row in rows.items():
                self.assertIn("opus", row["model"], f"{job}/{cls}: a row names Sonnet; let the evidence move it")
        ev = model_route._evidence()
        self.assertIsNotNone(ev, "model-eval-evidence.json must exist and parse")
        for job, spec in self.t["jobs"].items():
            for cls in (spec.get("classes") or {"*": None}):
                picked = model_route.pick(job, cls)
                sonnet, why = model_route.decide(job, cls, self.t, ev)
                if "sonnet" in picked:
                    self.assertEqual(picked, sonnet, f"{job}/{cls} on Sonnet without the rule: {why}")

    def test_decide_moves_a_row_only_over_the_bar(self):
        # negative self-test both ways: evidence just over each bar moves the row,
        # just under it does not, and a risk class never moves
        t = self.t
        r = t["sonnet_rule"]
        good_review = {"review": {"model": r["sonnet_model"], "per_class": {"docs-text": {
            "opus_majors": r["review"]["min_majors"], "caught": r["review"]["min_majors"], "sonnet_approved_those": 0}}}}
        self.assertEqual(model_route.decide("review", "docs-text", t, good_review)[0], r["sonnet_model"])
        low = json.loads(json.dumps(good_review))
        low["review"]["per_class"]["docs-text"]["caught"] = int(r["review"]["min_majors"] * r["review"]["min_recall"]) - 1
        self.assertIsNone(model_route.decide("review", "docs-text", t, low)[0])
        let_through = json.loads(json.dumps(good_review))
        let_through["review"]["per_class"]["docs-text"]["sonnet_approved_those"] = 1
        self.assertIsNone(model_route.decide("review", "docs-text", t, let_through)[0])
        self.assertIsNone(model_route.decide("review", "guards-hooks", t,
                                             {"review": {"model": "x", "per_class": {"guards-hooks": {"opus_majors": 99, "caught": 99}}}})[0])
        arm = {"runs": 3, "committed": 3, "tests_pass": 3, "tests_fail": 0, "r1_approve": 2, "gating": 1}
        good_worker = {"worker": {"models": {"sonnet": r["sonnet_model"]}, "per_class": {"test-only": {"sonnet": dict(arm), "opus": dict(arm)}}}}
        self.assertEqual(model_route.decide("worker", "test-only", t, good_worker)[0], r["sonnet_model"])
        worse = json.loads(json.dumps(good_worker))
        worse["worker"]["per_class"]["test-only"]["sonnet"]["gating"] = 2
        self.assertIsNone(model_route.decide("worker", "test-only", t, worse)[0])
        n = r["decision"]["min_n"]
        self.assertEqual(model_route.decide("alert-triage", "*", t, {"jobs": {"alert-triage": {"kind": "decision", "n": n, "same": n}}})[0],
                         r["sonnet_model"])
        self.assertIsNone(model_route.decide("alert-triage", "*", t, {"jobs": {"alert-triage": {"kind": "decision", "n": n, "same": n - 1}}})[0])
        content = {"jobs": {"lesson-distill": {"kind": "content", "n": 30, "judged": 20, "sonnet_better": 6, "equal": 4,
                                               "sonnet_gate": 30, "opus_gate": 29}}}
        self.assertEqual(model_route.decide("lesson-distill", "*", t, content)[0], r["sonnet_model"])
        content["jobs"]["lesson-distill"]["equal"] = 2
        self.assertIsNone(model_route.decide("lesson-distill", "*", t, content)[0])

    def test_the_measured_evidence_routes_today(self):
        # what the 2026-11-08 eval measured, read through the same code path
        ev = model_route._evidence()
        why = model_route.decide("lesson-distill", "*", self.t, ev)[1]
        self.assertIn("38%", why)
        self.assertIsNone(model_route.decide("review", "multi-code-file", self.t, ev)[0])

    def test_a_hook_wired_only_in_the_settings_template_is_a_guard(self):
        # PR #664 round 2, minor: miyo-session-pull.py is wired only in
        # settings-template.json, which is what instances install.
        hooks = model_route.wired_hooks(QS.parents[1])
        self.assertIn("q-system/.q-system/scripts/miyo-session-pull.py", hooks)

    def test_unreadable_table_floor_is_the_table_default(self):
        # the floor is the only literal outside the table; it must not drift from it
        self.assertEqual(model_route.FLOOR, self.t["default"])


class Pick(unittest.TestCase):
    def test_known_job_and_class(self):
        t = json.loads(TABLE.read_text())
        self.assertEqual(model_route.pick("worker", "dispatcher-worker"),
                         t["jobs"]["worker"]["classes"]["dispatcher-worker"]["model"])

    def test_unknown_job_or_class_falls_to_default(self):
        t = json.loads(TABLE.read_text())
        self.assertEqual(model_route.pick("no-such-job"), t["default"])
        self.assertEqual(model_route.pick("worker", "no-such-class"),
                         t["jobs"]["worker"]["classes"]["unknown"]["model"])

    def test_unreadable_table_fails_toward_opus(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "model-routing.json"
            bad.write_text("{not json")
            self.assertIn("opus", model_route.pick("worker", "docs-text", table_path=bad))


class CallSites(unittest.TestCase):
    def test_governed_sites_name_no_model(self):
        hits = []
        for name in GOVERNED:
            hits += literal_sites(name, (SCRIPTS / name).read_text())
        self.assertEqual(hits, [], "a governed call site names a model; read it from model_route.py")

    def test_governed_sites_read_the_table(self):
        for name in GOVERNED:
            self.assertTrue("model_route" in (SCRIPTS / name).read_text(), f"{name} does not read model_route")

    def test_worker_main_run_passes_a_model(self):
        text = (SCRIPTS / "linear-worker.sh").read_text()
        main = [l for l in text.splitlines() if 'claude -p \\"\\$1\\"' in l and not l.strip().startswith("#")]
        self.assertEqual(len(main), 1, "expected exactly one main-run claude -p line")
        self.assertIn("--model", main[0])

    def test_the_retired_reviewer_env_is_read_and_set_nowhere(self):
        # The 2026-09-28 Sonnet reviewer lived in this env var, set in the dispatch plist
        # and copied into the hosted workflow. A var that still overrode the table would
        # make the table decoration. The installed plist may still export it: inert.
        root = QS.parents[1]
        for rel in ("q-system/.q-system/scripts/pr-review-agent.sh",
                    "q-system/.q-system/scripts/com.kipi.dispatch.plist",
                    ".github/workflows/reviewer-hosted.yml"):
            code = [l for l in (root / rel).read_text().splitlines()
                    if "KIPI_REVIEW_CLAUDE_MODEL" in l and not l.strip().startswith(("#", "<!--"))]
            self.assertEqual(code, [], rel)

    def test_negative_self_test_the_lint_catches_a_literal(self):
        # A lint that cannot fail is not a lint: plant each shape it must catch.
        self.assertTrue(literal_sites("x.sh", 'M="${X:-claude-opus-5}"\n'))
        self.assertTrue(literal_sites("x.sh", "claude -p --model claude-sonnet-5-5 hi\n"))
        self.assertTrue(literal_sites("x.py", 'TRIAGE_MODEL = "claude-opus-5"\n'))
        self.assertFalse(literal_sites("x.sh", "# claude-opus-5 was the old pin\n"))
        self.assertFalse(literal_sites("x.py", '"""docstring naming claude-opus-5"""\nX = 1\n'))


def names_its_model(path_name: str, text: str) -> list:
    """Why a call-site file is NOT on the CLI default, or [] when nothing pins it.

    A model is named by `--model` in code, by the routing table, by a lean_call
    `job=`, or by an ANTHROPIC_MODEL pin the file sets itself. Measured
    2026-11-08: the lean jobs (DoR drafter, fleet triage, lesson distill) named
    none, and with no settings loaded the CLI picked claude-opus-5-5 for them."""
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    if path_name.endswith(".py"):
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        strings = " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        kwargs = {k.arg for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords}
        code = strings + " " + " ".join(sorted(k for k in kwargs if k))
    why = [w for w, hit in (("--model", "--model" in code), ("model_route", "model_route" in code),
                            ("job=", "job" in code.split()), ("ANTHROPIC_MODEL", "ANTHROPIC_MODEL" in code)) if hit]
    return why


class EveryCallNamesAModel(unittest.TestCase):
    """Coordinator, 2026-11-08: a fleet `claude -p` with no --model runs on the CLI
    default. The literal lint above catches a direct id; this catches the missing one."""

    def test_every_claude_p_call_site_names_its_model(self):
        root = QS.parents[1]
        sys.path.insert(0, str(root / "plugins" / "kipi-core"))
        from voiceloop import call_sites as cs
        sites = sorted(cs.call_sites(root))
        self.assertGreater(len(sites), 10, "the detector found no population; a silent scan is not coverage")
        bare = [rel for rel in sites if not names_its_model(rel, (root / rel).read_text(errors="replace"))]
        self.assertEqual(bare, [], "these claude -p call sites run on the CLI default")

    def test_every_lean_call_names_a_job(self):
        # lean_call is the chokepoint for background calls; each caller names its row
        import ast
        bare = []
        for py in sorted(SCRIPTS.glob("*.py")):
            if py.name == "lean_call.py":
                continue
            tree = ast.parse(py.read_text())
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "lean_call"
                        and not any(k.arg == "job" for k in n.keywords)):
                    bare.append(f"{py.name}:{n.lineno}")
        self.assertEqual(bare, [])

    def test_lean_call_job_adds_the_rows_model(self):
        import lean_call
        seen = {}

        def fake(argv, **kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "", "")
        orig = lean_call.subprocess.run
        lean_call.subprocess.run = fake
        try:
            lean_call.run(["claude", "-p", "hi"], job="dor-drafting", capture_output=True, text=True)
        finally:
            lean_call.subprocess.run = orig
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], model_route.pick("dor-drafting"))
        for job in ("dor-drafting", "fleet-triage", "lesson-distill", "lesson-verify", "on-demand"):
            self.assertIn(job, json.loads(TABLE.read_text())["jobs"], job)

    def test_negative_self_test_a_bare_call_is_caught(self):
        self.assertEqual(names_its_model("x.py", 'import subprocess\nsubprocess.run(["claude", "-p", "hi"])\n'), [])
        self.assertEqual(names_its_model("x.sh", 'claude -p "hi"\n# --model claude-x only in a comment\n'), [])
        self.assertTrue(names_its_model("x.py", 'lean_call.run(["claude", "-p", "x"], job="fleet-triage")\n'))
        self.assertTrue(names_its_model("x.sh", 'claude -p "$1" --model "$M"\n'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
