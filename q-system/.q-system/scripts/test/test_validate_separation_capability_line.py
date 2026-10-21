#!/usr/bin/env python3
"""Unit tests for validate-separation.py reporting helpers.

Shared file (ASK-1903 / sp-21755bd0 and sp-5d59eb4f both land here) so two
narrow fixes to one validator do not open two test files with the same import
boilerplate.

ASK-1903: Gate 1.2b read "memory-lint printed no `structural:` line" as the
single signal for "the linter is broken". memory-lint exits 0 and prints
"no memory directory at <path> (nothing to sweep)" when the auto-memory corpus
is absent -- the ordinary state of a fresh checkout or a git worktree -- so a
healthy run was reported as a broken linter.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT / "validate-separation.py"


def load_validator():
    """Import validate-separation.py by path (the filename is not importable)."""
    spec = importlib.util.spec_from_file_location("kipi_validate_separation", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VS = load_validator()

# The real absent-corpus stdout, produced by running memory-lint.py against a
# path that does not exist. Not invented: a fixture that does not come from the
# producer tests the author's assumption about the producer.
ABSENT_STDOUT = "memory-lint: no memory directory at %s (nothing to sweep)\n"
CLEAN_STDOUT = "memory-lint: 12 memory file(s) in %s\n\nstructural: 0   advisory: 3\n"
DIRTY_STDOUT = "memory-lint: 12 memory file(s) in %s\n\nstructural: 2   advisory: 3\n"


class MemoryLintClassification(unittest.TestCase):
    def test_absent_corpus_is_a_skip_naming_the_directory(self):
        """ASK-1903: a checkout with no auto-memory dir is healthy, not broken."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "memory")
            kind, message = VS.classify_memory_lint(missing, 0, ABSENT_STDOUT % missing)
        self.assertEqual(kind, "skip")
        self.assertIn(missing, message)
        self.assertNotIn("no summary", message)

    def test_present_corpus_with_no_summary_still_warns(self):
        """The mutant killer for the decision point above.

        A fix that returned "skip" whenever the summary is missing would pass
        the absent-corpus test and silence the real crash this gate exists for.
        The directory EXISTS here, so the missing summary is an anomaly.
        """
        with tempfile.TemporaryDirectory() as tmp:
            kind, message = VS.classify_memory_lint(tmp, 0, "Traceback (most recent call last):\n")
        self.assertEqual(kind, "broken")
        self.assertIn("no summary", message)

    def test_nonzero_exit_with_no_summary_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "memory")
            kind, message = VS.classify_memory_lint(missing, 2, "memory-lint: --today 'x' is not YYYY-MM-DD\n")
        self.assertEqual(kind, "broken")
        self.assertIn("exit 2", message)

    def test_silent_producer_on_an_absent_corpus_warns(self):
        """ASK-1903 round 3: absence is only a PASS when the producer said so.

        Round 2 read absence off `os.path.isdir` alone, so a memory-lint that
        crashed before printing anything and still exited 0 reported PASS. That
        branch is the one every checkout without a corpus takes, so the gate's
        crash detection was off in exactly the population it targets.
        """
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "memory")
            kind, message = VS.classify_memory_lint(missing, 0, "")
        self.assertEqual(kind, "broken")
        self.assertIn("absence line", message)

    def test_unrelated_stdout_on_an_absent_corpus_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "memory")
            kind, _ = VS.classify_memory_lint(missing, 0, "ImportError swallowed\n")
        self.assertEqual(kind, "broken")

    def test_absence_line_about_a_different_corpus_warns(self):
        """The producer must report absence of the path the gate handed it.

        An absence line naming some other directory means the subprocess swept a
        corpus the gate is not reporting on, which is the two-derivations defect
        this issue exists for.
        """
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "memory")
            other = os.path.join(tmp, "somewhere-else", "memory")
            kind, _ = VS.classify_memory_lint(missing, 0, ABSENT_STDOUT % other)
        self.assertEqual(kind, "broken")

    def test_unknown_corpus_path_with_no_summary_warns(self):
        """corpus=None means the derivation failed; do not call that healthy."""
        kind, _ = VS.classify_memory_lint(None, 0, ABSENT_STDOUT % "somewhere")
        self.assertEqual(kind, "broken")

    def test_clean_summary_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            kind, message = VS.classify_memory_lint(tmp, 0, CLEAN_STDOUT % tmp)
        self.assertEqual(kind, "clean")
        self.assertIn("structural: 0", message)

    def test_structural_findings_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            kind, message = VS.classify_memory_lint(tmp, 0, DIRTY_STDOUT % tmp)
        self.assertEqual(kind, "findings")
        self.assertIn("structural: 2", message)


class MemoryCorpusDerivation(unittest.TestCase):
    def test_corpus_path_comes_from_memory_lint_itself(self):
        """One derivation of one path, and the validator is not one of its owners.

        Round 1 of this test restated the slug as `SCRIPT_DIR.replace("/", "-")`
        directly below a docstring saying it refuses to restate it -- which is
        why it stayed green while naming a directory Claude Code never creates
        (PR #458 review, minor). The expectation now comes from
        `memory_conventions`, the single owner, and what is asserted here is the
        BINDING: the validator reports whatever that owner says, and the answer
        carries the project path rather than some default.
        """
        derived = VS.memory_corpus_dir()
        self.assertIsNotNone(derived, "validator could not load memory-lint's derivation")

        sys.path.insert(0, str(REPO_ROOT / "q-system" / ".q-system" / "scripts"))
        import memory_conventions

        self.assertEqual(
            os.path.normpath(derived),
            os.path.normpath(str(memory_conventions.claude_project_memory_dir(str(VS.SCRIPT_DIR)))),
        )
        # A derivation that returned an empty slug, or ignored the project path
        # and answered for the cwd, would satisfy the equality above only
        # because both sides would be wrong together. `project_state_root` and
        # not SCRIPT_DIR: in a linked worktree the corpus is keyed on the main
        # worktree, which is round 3's whole finding.
        state_root = memory_conventions.project_state_root(str(VS.SCRIPT_DIR))
        self.assertIn(memory_conventions.claude_project_slug(state_root), derived)

    def test_the_slug_is_a_literal_contract_not_a_recomputation(self):
        """Round 2's version of the test above compared the owner with itself.

        Every assertion in it called `claude_project_slug`, so a mutant that
        lower-cased the answer -- naming a directory the producer never writes,
        since real corpora include `-Users-x-projects-Some-Mixed-Case` -- passed
        it 2 of 2. These expectations are literals, so they can disagree with the
        owner.
        """
        sys.path.insert(0, str(REPO_ROOT / "q-system" / ".q-system" / "scripts"))
        import memory_conventions

        self.assertEqual(
            memory_conventions.claude_project_slug("/Users/x/Projects/Demo_App"),
            "-Users-x-Projects-Demo-App",
        )
        self.assertEqual(
            memory_conventions.claude_project_slug("/Users/x/.config/wt/a-1"),
            "-Users-x--config-wt-a-1",
        )

    def test_derivation_does_not_leak_the_pinned_env(self):
        prior = os.environ.get("CLAUDE_PROJECT_DIR")
        VS.memory_corpus_dir()
        self.assertEqual(os.environ.get("CLAUDE_PROJECT_DIR"), prior)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
