#!/usr/bin/env python3
"""Wiring detection in capability-map-gen.py: what counts as "this engine is alive".

WHY (ASK-122): the generator flagged 22 local engines in Alice as UNWIRED. Nearly
all of them had a visible caller on disk -- `regenerate.sh` literally runs
`python3 "$G/fill_sheet.py"`, `brightdata.sh` runs `mcp-client.py`, `pipeline.py`
imports `geo_clues`. The scan simply never opened those files: it walked only
.claude/, plugins/ and q-system/, and Alice's code lives in q-investigate/ and
scripts/. A gate that reports dead-and-alive the same way is not a gate.

Second blind spot, same issue, already scarred once (ASK-230, provenance_vocabulary):
`has_test` compared FILENAMES only, so `tests/test_extract.py` importing `geo_clues`
scored as no-test. An importer is the strongest liveness evidence there is.

The five NEGATIVE cases below are the point of this file. Widening the scan makes
false-LIVE the new failure mode, so a prose-only mention, a true orphan, a
self-referencing docstring, a generated run log, and a dated snapshot must all
still fail to count as wiring. A gate that cannot fail is a rubber stamp.

The generated-log case was not written from imagination: it was found by diffing
old-vs-new output across five real instances before merge, where it had already
flipped a genuinely dead script to LIVE. A negative case earns its place by
having caught something.

Isolation: every fixture is built in a tempdir. Nothing here reads a real repo.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

GEN = Path(__file__).resolve().parent.parent / "capability-map-gen.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Populated per run in main(); an inherited value would mark fixture paths
    # vendored and silently collect zero engines.
    mod._NESTED_REPOS = set()
    return mod


def engine_body(name: str) -> str:
    """A file long enough to clear the generator's 40-line engine floor."""
    head = f'#!/usr/bin/env python3\n"""{name} -- fixture engine."""\n'
    return head + "\n".join(f"# line {i}" for i in range(60))


def build_fixture(root: Path) -> None:
    (root / "q-investigate" / "tools").mkdir(parents=True)
    (root / "q-investigate" / "lib").mkdir(parents=True)
    (root / "q-investigate" / "tests").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)

    # 1. LIVE: only caller is a shell script outside q-system/.
    (root / "q-investigate/tools/engine_shell_called.py").write_text(
        engine_body("engine_shell_called"))
    (root / "q-investigate/tools/run.sh").write_text(
        '#!/bin/bash\nset -euo pipefail\n'
        'python3 "$(dirname "$0")/engine_shell_called.py" --once\n')

    # 2. LIVE: only evidence is a test that IMPORTS it under a different filename.
    (root / "q-investigate/lib/engine_import_tested.py").write_text(
        engine_body("engine_import_tested"))
    (root / "q-investigate/tests/test_unrelated_name.py").write_text(
        "import sys\nsys.path.insert(0, '../lib')\n"
        "import engine_import_tested\n\n"
        "def test_it():\n    assert engine_import_tested\n")

    # 3. LIVE: invoked from a fenced command inside a markdown command/runbook.
    (root / "q-investigate/lib/engine_doc_invoked.py").write_text(
        engine_body("engine_doc_invoked"))
    (root / "docs/runbook.md").write_text(
        "# Runbook\n\nRegenerate the deliverable:\n\n```bash\n"
        "python3 q-investigate/lib/engine_doc_invoked.py\n```\n")

    # 4. NEGATIVE: named in prose only. A findings doc saying a script is broken
    #    is not a caller. This must stay UNWIRED or the widened scan has simply
    #    traded false-dead for false-alive.
    (root / "q-investigate/lib/engine_prose_only.py").write_text(
        engine_body("engine_prose_only"))
    (root / "docs/findings.md").write_text(
        "# Findings\n\nDefect D1: engine_prose_only.py left the template unfilled.\n"
        "Nobody has run engine_prose_only since the migration.\n")

    # 5. NEGATIVE: nothing anywhere mentions it.
    (root / "q-investigate/lib/engine_orphan.py").write_text(
        engine_body("engine_orphan"))

    # 6. NEGATIVE: self-reference in its own docstring is not a caller.
    (root / "q-investigate/lib/engine_self_ref.py").write_text(
        '#!/usr/bin/env python3\n'
        '"""engine_self_ref.py -- run engine_self_ref.py nightly."""\n'
        + "\n".join(f"# line {i}" for i in range(60)))

    # 7. NEGATIVE: named only inside q-system/output/, the generated-artifacts
    #    tree. A codex transcript or run log that ENUMERATES files reads exactly
    #    like a runbook that INVOKES one, so the fixture is a `find`-style
    #    listing -- the real shape that flipped the `_sync_all` script to LIVE in
    #    kipi-investigations. Note both lines below satisfy MD_INVOCATION_RE
    #    ("./" and "python3 "), which is the point: the invocation filter cannot
    #    catch this, only dropping the generated tree can.
    (root / "q-system" / "output").mkdir(parents=True)
    (root / "q-investigate/lib/engine_logged_only.py").write_text(
        engine_body("engine_logged_only"))
    (root / "q-system/output/codex-run-out.txt").write_text(
        "Files considered:\n"
        "./q-investigate/lib/engine_logged_only.py\n"
        "python3 q-investigate/lib/engine_logged_only.py  # transcript echo\n")

    # 8. A dated snapshot of a live engine is not a second engine. Its writer
    #    interpolates the date, so no static scan can ever match its literal name.
    (root / "q-investigate/tools/backups").mkdir(parents=True)
    (root / "q-investigate/tools/backups/engine_shell_called.2026-07-28.py").write_text(
        engine_body("engine_shell_called snapshot"))


class TestWiringDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_generator()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        build_fixture(cls.root)
        cls.by_entry = {
            c["entry"]: c for c in cls.mod.collect_engines(cls.root)
        }

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def status(self, entry: str) -> str:
        self.assertIn(entry, self.by_entry,
                      f"{entry} was not collected at all; got {sorted(self.by_entry)}")
        return self.by_entry[entry]["status"]

    # --- positive: real wiring the old scan could not see -------------------

    def test_shell_caller_outside_qsystem_counts(self):
        self.assertEqual(
            "LIVE", self.status("q-investigate/tools/engine_shell_called.py"),
            "run.sh invokes it by path; that is wiring wherever run.sh lives")

    def test_importing_test_counts_even_with_mismatched_filename(self):
        self.assertEqual(
            "LIVE", self.status("q-investigate/lib/engine_import_tested.py"),
            "test_unrelated_name.py imports the module; filename match is not the test")

    def test_fenced_invocation_in_markdown_counts(self):
        self.assertEqual(
            "LIVE", self.status("q-investigate/lib/engine_doc_invoked.py"),
            "a runbook line that runs the script is a trigger")

    # --- negative: the widened scan must still be able to say dead ----------

    def test_prose_mention_is_not_wiring(self):
        self.assertEqual(
            "UNWIRED", self.status("q-investigate/lib/engine_prose_only.py"),
            "a findings doc naming a script does not make it live")

    def test_orphan_stays_unwired(self):
        self.assertEqual(
            "UNWIRED", self.status("q-investigate/lib/engine_orphan.py"),
            "nothing references it; this is the case the gate exists for")

    def test_self_reference_is_not_wiring(self):
        self.assertEqual(
            "UNWIRED", self.status("q-investigate/lib/engine_self_ref.py"),
            "a script naming itself in its own docstring is not a caller")

    def test_generated_output_is_not_wiring(self):
        self.assertEqual(
            "UNWIRED", self.status("q-investigate/lib/engine_logged_only.py"),
            "q-system/output/ holds codex transcripts and run logs; a log that "
            "lists a script did not run it, and its lines look like invocations")

    def test_dated_snapshot_is_not_an_engine(self):
        self.assertNotIn(
            "q-investigate/tools/backups/engine_shell_called.2026-07-28.py",
            self.by_entry,
            "a dated snapshot is a rollback artifact; flagging it forever leaves "
            "deleting the rollback copy as the only way to clear the gate")

    # --- the evidence has to name the caller, not just assert a verdict -----

    def test_evidence_names_the_referencing_file(self):
        ev = self.by_entry["q-investigate/tools/engine_shell_called.py"]["evidence"]
        self.assertIn("run.sh", ev,
                      f"evidence must point at the caller so the map is auditable: {ev}")


class TestMutantKills(unittest.TestCase):
    """Kill-tests for mutants that SURVIVED the 9-case suite (Fable mutation table).

    Reverting either 73a8870 fix left every test green: the witness ranking and
    the engine-side generated exclusion shipped with zero coverage. A fix nothing
    pins is a fix that silently un-ships on the next edit. These assert the unit
    behaviour directly so no fixture wiring can mask them.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_generator()

    # --- MD_INVOCATION_RE: prose must not read as invocation (Fable B1) -------

    def test_prose_does_not_match_invocation_re(self):
        for line in [
            "The source of the bug is engine_x.py",
            "run-sweep.sh used to call engine_x.py",
            "this old python script engine_x.py is dead",
            "see ../notes for why engine_x.py was dropped",
            "we removed the bash wrapper around engine_x.py",
        ]:
            self.assertIsNone(
                self.mod.MD_INVOCATION_RE.search(line),
                f"prose asserting a script is dead must not mark it live: {line!r}")

    def test_real_invocations_still_match(self):
        for line in [
            "python3 engine_x.py --once",
            "  ./engine_x.py",
            "bash scripts/run.sh",
            "cat x | python3 tools/y.py",
            "$(python3 gen.py)",
            "sh ./deploy.sh",
        ]:
            self.assertIsNotNone(
                self.mod.MD_INVOCATION_RE.search(line),
                f"a real invocation must still count as wiring: {line!r}")

    # --- witness ranking: .claude/ and .q-system/ are NOT scratch (Fable A1) --

    def test_witness_prefers_real_caller_over_review_scratch(self):
        real = Path("q-system/.q-system/scripts/linear-worker.sh")
        scratch = Path(".pr36rev/tree/q-system/.q-system/scripts/linear-worker.sh")
        self.assertEqual(
            real, sorted([scratch, real], key=self.mod._witness_rank)[0],
            "a review tree copy must never out-cite the real caller")

    def test_dotted_wiring_dirs_are_not_treated_as_scratch(self):
        for real in (Path(".claude/settings.json"),
                     Path("q-system/.q-system/scripts/x.sh")):
            plain = Path("docs/some/deep/nested/note.md")
            self.assertEqual(
                real, sorted([plain, real], key=self.mod._witness_rank)[0],
                f"{real} is primary wiring in this fleet, not hidden scratch")

    # --- the exclusion predicate is used for ALL THREE questions -------------

    def test_excluded_tree_covers_generated_and_scratch(self):
        root = Path("/repo")
        for rel in ("q-system/output/log.txt", ".pr36rev/all-dors.json",
                    ".pr42rev-r2/tree/q-system/x.py", ".prd-os/spillover.jsonl",
                    ".claude/worktrees/w/q-system/x.py"):
            self.assertTrue(self.mod.is_excluded_tree(root / rel, root),
                            f"{rel} is generated or review scratch")

    def test_excluded_tree_does_not_swallow_real_wiring(self):
        root = Path("/repo")
        for rel in (".claude/settings.json", "q-system/.q-system/scripts/x.sh",
                    "plugins/prd-os/hooks.json", "scripts/daily-sweep/run.sh"):
            self.assertFalse(self.mod.is_excluded_tree(root / rel, root),
                             f"{rel} is real wiring and must stay on the surface")

    def test_scratch_tree_test_file_does_not_grant_has_test(self):
        """The has_test walk is a FOURTH consumer of is_excluded_tree.

        Missed when the predicate was introduced, so a test filename inside a
        review tree still marked a dead engine LIVE -- the same one-sided
        exclusion the predicate exists to prevent, surviving inside its own fix.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "lib").mkdir(parents=True)
            (root / ".pr36rev" / "tree" / "tests").mkdir(parents=True)
            (root / "lib/engine_only_scratch_test.py").write_text(
                engine_body("engine_only_scratch_test"))
            (root / ".pr36rev/tree/tests/test_engine_only_scratch_test.py").write_text(
                "def test_x():\n    assert True\n")
            caps = {c["entry"]: c for c in self.mod.collect_engines(root)}
            self.assertEqual(
                "UNWIRED", caps["lib/engine_only_scratch_test.py"]["status"],
                "a test file inside a review tree is not coverage of real code")

    def test_generated_prefix_is_anchored_not_substring(self):
        root = Path("/repo")
        self.assertFalse(
            self.mod.is_excluded_tree(root / "q-investigate/output/gen.py", root),
            "a case-level output/ dir is not q-system/output/; un-anchoring this "
            "darkens Alice's fill_sheet.py, which is LIVE and in ASK-122's table")


if __name__ == "__main__":
    unittest.main(verbosity=2)
