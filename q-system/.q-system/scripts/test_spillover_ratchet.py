#!/usr/bin/env python3
"""Tests for spillover-ratchet.py (ASK-343).

Two properties decide whether this hook is worth having at all:

  1. It must EXIT 2. The hook contract is exit 2 = stderr fed to Claude,
     exit 0 = pass. The first version of this file exited 0, so it wrote to a
     stderr nobody read -- inert on arrival, the same defect the ledger had.
  2. It must not cry wolf. A ratchet that fires on README.md gets switched off,
     and a switched-off gate protects nothing.

Temp ledgers only, never the live one.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "spillover-ratchet.py"
spec = importlib.util.spec_from_file_location("sr", SCRIPT)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

ROWS = [
    {"id": "sp-aaa", "status": "open", "severity": "minor", "source": "s",
     "description": "capability-gate.py reports a timeout as RED"},
    {"id": "sp-bbb", "status": "open", "severity": "major", "source": "s",
     "description": "capability-gate.py has a second, blocking problem"},
    {"id": "sp-ccc", "status": "resolved", "severity": "minor", "source": "s",
     "description": "capability-gate.py had a third, already handled"},
    {"id": "sp-ddd", "status": "open", "severity": "minor", "source": "s",
     "description": "see the README for the full context of this unrelated note"},
]


class MatchTest(unittest.TestCase):
    def rows(self):
        return [r for r in ROWS
                if r["status"] == "open" and r["severity"] == "minor"]

    def test_matches_the_named_file(self):
        hits = sr.findings_for("q-system/.q-system/scripts/capability-gate.py", self.rows())
        self.assertEqual([h["id"] for h in hits], ["sp-aaa"])

    def test_matches_on_basename_not_full_path(self):
        """A finding written from another checkout names the file, not your path."""
        hits = sr.findings_for("/somewhere/else/entirely/capability-gate.py", self.rows())
        self.assertEqual([h["id"] for h in hits], ["sp-aaa"])

    def test_generic_stem_does_not_cry_wolf(self):
        """README appears in unrelated prose everywhere. Firing on it is how a
        ratchet gets switched off."""
        self.assertEqual(sr.findings_for("README.md", self.rows()), [])

    def test_partial_name_does_not_match(self):
        """gate.py must not match capability-gate.py."""
        self.assertEqual(sr.findings_for("gate.py", self.rows()), [])

    def test_blocking_severities_are_not_delivered_here(self):
        """major/blocker go through `gates run`, not the ratchet. Delivering them
        twice trains people to dismiss both."""
        rows = sr.ledger_rows(Path("/nonexistent"))
        self.assertEqual(rows, [])
        self.assertNotIn("sp-bbb", [h["id"] for h in
                                    sr.findings_for("capability-gate.py", self.rows())])

    def test_resolved_findings_are_not_delivered(self):
        self.assertNotIn("sp-ccc", [h["id"] for h in
                                    sr.findings_for("capability-gate.py", self.rows())])


class ExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".prd-os").mkdir(parents=True)
        (self.root / ".prd-os" / "spillover.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ROWS))
        (self.root / "capability-gate.py").write_text("# x\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.home.cleanup()

    def run_hook(self, target, day="d1"):
        env = dict(os.environ, HOME=self.home.name, KIPI_RATCHET_DATE=day)
        return subprocess.run([sys.executable, str(SCRIPT), str(target)],
                              capture_output=True, text=True, env=env, cwd=self.root)

    # --- THE PROPERTY THAT MAKES IT NOT INERT ------------------------------
    def test_exits_2_so_the_agent_actually_sees_it(self):
        r = self.run_hook(self.root / "capability-gate.py")
        self.assertEqual(r.returncode, 2,
                         "exit 0 means stderr is discarded and the hook is inert")
        self.assertIn("sp-aaa", r.stderr)

    def test_asks_for_triage_not_a_fix(self):
        """Fixing an adjacent bug mid-task is scope creep, which the repo rules
        forbid. The ask has to be 'is this still true'."""
        r = self.run_hook(self.root / "capability-gate.py")
        self.assertIn("DO NOT fix", r.stderr)
        self.assertIn("STILL TRUE", r.stderr)

    def test_fires_once_per_file_per_day(self):
        first = self.run_hook(self.root / "capability-gate.py", day="d1")
        second = self.run_hook(self.root / "capability-gate.py", day="d1")
        self.assertEqual(first.returncode, 2)
        self.assertEqual(second.returncode, 0, "a second edit must not re-interrupt")

    def test_a_new_day_re_asks(self):
        self.run_hook(self.root / "capability-gate.py", day="d1")
        third = self.run_hook(self.root / "capability-gate.py", day="d2")
        self.assertEqual(third.returncode, 2, "a deferred note should come back")

    def test_file_with_no_notes_is_silent(self):
        (self.root / "quiet_file.py").write_text("# x\n")
        r = self.run_hook(self.root / "quiet_file.py")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "")

    # --- THE PROPERTY THAT MAKES IT NOT INERT, PART 2 (ASK-457) ------------
    def test_fires_through_the_stdin_payload_the_hook_actually_uses(self):
        """argv is the MANUAL path. PostToolUse feeds JSON on stdin, and that is
        the only path the wired hook ever takes -- so testing argv alone would
        have left the shipped invocation untested."""
        env = dict(os.environ, HOME=self.home.name, KIPI_RATCHET_DATE="dstdin")
        payload = json.dumps({"tool_name": "Edit", "tool_input": {
            "file_path": str(self.root / "capability-gate.py")}})
        r = subprocess.run([sys.executable, str(SCRIPT)], input=payload,
                           capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(r.returncode, 2, "the wired hook path must reach exit 2")
        self.assertIn("sp-aaa", r.stderr)

    def test_promoter_is_named_by_a_path_that_exists(self):
        """An address the reader cannot dial is not an address. The promoter is
        not on PATH, so a bare basename leaves the agent guessing from whatever
        worktree it is in."""
        r = self.run_hook(self.root / "capability-gate.py", day="dpath")
        self.assertIn(str(SCRIPT.parent / "spillover-promote.py"), r.stderr)


class BareWordTest(unittest.TestCase):
    """A bare dictionary word is a word, not a filename (ASK-457).

    Measured against the live ledger before wiring: `kipi` matched 148 findings,
    every sampled one a false positive. A ratchet that dumps 148 notes when you
    edit the main CLI is a ratchet someone switches off, and an off gate protects
    nothing -- the same reasoning as the README guard above, one hole over.
    """
    ROWS = [
        {"id": "sp-bare", "status": "open", "severity": "minor", "source": "s",
         "description": "kipi update rsyncs into main from the repo config at HEAD"},
        {"id": "sp-real", "status": "open", "severity": "minor", "source": "s",
         "description": "linear-worker.sh ready() refuses an unlabelled issue"},
        {"id": "sp-dot", "status": "open", "severity": "minor", "source": "s",
         "description": ".gitignore excludes *.jsonl so the ledger never travels"},
    ]

    def test_bare_words_do_not_fire(self):
        for word in ("kipi", "main", "repo", "config", "HEAD", "claude"):
            with self.subTest(word=word):
                self.assertEqual(sr.findings_for(word, self.ROWS), [],
                                 f"{word!r} is a word, not a filename")

    def test_a_separator_still_makes_it_a_name(self):
        hits = sr.findings_for("linear-worker.sh", self.ROWS)
        self.assertEqual([h["id"] for h in hits], ["sp-real"])

    def test_a_dotfile_is_still_a_name(self):
        """`.gitignore` has no extension and no separator, but the leading dot
        marks it as a filename. Suppressing it would be the fix overshooting."""
        hits = sr.findings_for(".gitignore", self.ROWS)
        self.assertEqual([h["id"] for h in hits], ["sp-dot"])


class PathedMentionTest(unittest.TestCase):
    """A real description cites a PATH, not a bare basename (Codex minor, ASK-457).

    `spillover add --desc` is written by an agent that has the path in hand, so
    that is what lands in the ledger. The basename branch excluded a preceding
    `/` and the stem branch only ran for stems carrying a separator, so a finding
    about an ordinary-stem file -- `hooks.json`, `config.json`, `settings.json` --
    fell between the two and could never fire. The conveyor's first stage was
    silently absent for a whole class of file.

    The two directions are tested together on purpose: dropping the `/`
    restriction alone fixes the miss and creates a worse bug, because a repo is
    full of same-named files in different directories.
    """
    ROWS = [
        {"id": "sp-here", "status": "open", "severity": "minor", "source": "s",
         "description": "plugins/prd-os/hooks/hooks.json wires the lint but the "
                        "script it names is absent"},
        {"id": "sp-elsewhere", "status": "open", "severity": "minor", "source": "s",
         "description": ".claude/hooks/hooks.json has a different, unrelated gap"},
        {"id": "sp-deep", "status": "open", "severity": "minor", "source": "s",
         "description": "q-system/.q-system/config.json still pins the old tier"},
    ]

    def test_an_ordinary_stem_fires_on_a_pathed_mention(self):
        hits = sr.findings_for("plugins/prd-os/hooks/hooks.json", self.ROWS)
        self.assertEqual([h["id"] for h in hits], ["sp-here"],
                         "a note citing this file's path did not reach the file")

    def test_a_pathed_mention_of_another_directory_does_not_fire(self):
        """Same basename, different directory, different file. Firing here is
        the cry-wolf failure the `/` restriction was over-solving."""
        hits = sr.findings_for("plugins/prd-os/hooks/hooks.json",
                               [self.ROWS[1]])
        self.assertEqual(hits, [], "a note about .claude/hooks/hooks.json fired "
                                   "on plugins/prd-os/hooks/hooks.json")

    def test_a_ledger_path_matches_the_worktree_path_it_is_edited_through(self):
        """The description is written from one checkout and read from another,
        so the comparison has to be a suffix, not equality."""
        hits = sr.findings_for(
            "/Users/x/.config/kipi/worktrees/ask-457/q-system/.q-system/config.json",
            self.ROWS)
        self.assertEqual([h["id"] for h in hits], ["sp-deep"])

    def test_a_bare_basename_still_fires_anywhere(self):
        """The old behaviour, unchanged: a finding from another checkout that
        names only the file still reaches whatever path you edit it through."""
        rows = [{"id": "sp-bare", "status": "open", "severity": "minor",
                 "source": "s", "description": "settings.json wires the hook"}]
        hits = sr.findings_for("/anywhere/at/all/settings.json", rows)
        self.assertEqual([h["id"] for h in hits], ["sp-bare"])


class AckKeyTest(unittest.TestCase):
    """The daily acknowledgement is per FILE, not per basename (Codex minor, ASK-457).

    The suppression key was `<date>-<basename>`, so acknowledging
    `plugins/prd-os/hooks/hooks.json` also silenced `.claude/hooks/hooks.json`
    for the rest of the day. That is a silent absence, and the pathed-mention
    fix made it reachable: findings can now address a specific same-named file,
    and this key threw that distinction away one step later.

    Same-named files in different directories are the ordinary case here
    (`hooks.json`, `settings.json`, `README.md`), so this is not exotic.
    """

    ROWS = [
        {"id": "sp-plug", "status": "open", "severity": "minor", "source": "s",
         "description": "plugins/prd-os/hooks/hooks.json wires a script that is absent"},
        {"id": "sp-claude", "status": "open", "severity": "minor", "source": "s",
         "description": ".claude/hooks/hooks.json has a different, unrelated gap"},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".prd-os").mkdir(parents=True)
        (self.root / ".prd-os" / "spillover.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in self.ROWS))
        for rel in ("plugins/prd-os/hooks", ".claude/hooks"):
            (self.root / rel).mkdir(parents=True)
            (self.root / rel / "hooks.json").write_text("{}\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.home.cleanup()

    def run_hook(self, rel, day="d1"):
        env = dict(os.environ, HOME=self.home.name, KIPI_RATCHET_DATE=day)
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root / rel)],
                              capture_output=True, text=True, env=env, cwd=self.root)

    def test_a_same_named_file_elsewhere_still_fires_the_same_day(self):
        first = self.run_hook("plugins/prd-os/hooks/hooks.json")
        self.assertEqual(first.returncode, 2)
        self.assertIn("sp-plug", first.stderr)
        second = self.run_hook(".claude/hooks/hooks.json")
        self.assertEqual(second.returncode, 2,
                         "acknowledging one hooks.json silenced a DIFFERENT "
                         "hooks.json: the ack key is keyed on the basename")
        self.assertIn("sp-claude", second.stderr)

    def test_the_same_file_twice_is_still_suppressed(self):
        """The property the key exists for, unchanged: one file, one interruption."""
        self.assertEqual(self.run_hook("plugins/prd-os/hooks/hooks.json").returncode, 2)
        self.assertEqual(self.run_hook("plugins/prd-os/hooks/hooks.json").returncode, 0)

    def test_the_same_file_through_two_paths_is_one_acknowledgement(self):
        """One file reached by two spellings is one acknowledgement. Keying on
        the raw argument would re-interrupt on every route to the same file.

        The detour is `.claude/..`, chosen so the four trailing components the
        finding cites survive it -- a `..` inside the cited part would make
        `findings_for` miss and the hook would exit 0 before ever reaching the
        ack key, which is a test passing for the wrong reason. Caught by mutation
        (M4 survived against the first version of this test)."""
        first = self.run_hook("plugins/prd-os/hooks/hooks.json")
        self.assertEqual(first.returncode, 2)
        detour = ".claude/../plugins/prd-os/hooks/hooks.json"
        self.assertEqual(
            [h["id"] for h in sr.findings_for(str(self.root / detour), self.ROWS)],
            ["sp-plug"],
            "the detour spelling stopped matching, so this test would pass "
            "without the ack key being consulted at all")
        self.assertEqual(self.run_hook(detour).returncode, 0,
                         "the same file spelled differently re-interrupted")


class WorktreeLedgerTest(unittest.TestCase):
    """The ledger lives in ONE place for the whole worktree set (ASK-457).

    Measured before wiring: run from a worktree, the ratchet saw 0 rows on a file
    carrying 57 real notes, because `*.jsonl` is gitignored and so each worktree
    has its own (absent) copy. Agents work in worktrees. Arming the hook without
    this would have armed it precisely where it can never fire.
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = tempfile.TemporaryDirectory()
        self.main = Path(self.tmp.name) / "checkout"
        self.main.mkdir()
        run = lambda *a: subprocess.run(list(a), cwd=self.main,
                                        capture_output=True, text=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (self.main / "capability-gate.py").write_text("# x\n")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "init")
        # The ledger exists ONLY in the main checkout, exactly as in real life.
        (self.main / ".prd-os").mkdir()
        (self.main / ".prd-os" / "spillover.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ROWS))
        self.wt = Path(self.tmp.name) / "wt"
        add = run("git", "worktree", "add", "-q", "-b", "side", str(self.wt))
        # A failed `git worktree add` would leave cwd falling back to the MAIN
        # checkout, where the ledger is present and the test passes from code
        # without the fix. Assert the setup landed before trusting the result.
        self.assertEqual(add.returncode, 0, f"worktree setup failed: {add.stderr}")
        self.assertTrue((self.wt / "capability-gate.py").is_file())
        self.assertFalse((self.wt / ".prd-os" / "spillover.jsonl").exists(),
                         "the worktree must NOT have its own ledger copy")

    def tearDown(self):
        subprocess.run(["git", "worktree", "remove", "--force", str(self.wt)],
                       cwd=self.main, capture_output=True)
        self.tmp.cleanup()
        self.home.cleanup()

    def test_a_worktree_edit_still_sees_the_shared_ledger(self):
        env = dict(os.environ, HOME=self.home.name, KIPI_RATCHET_DATE="dwt")
        target = self.wt / "capability-gate.py"
        r = subprocess.run([sys.executable, str(SCRIPT), str(target)],
                           capture_output=True, text=True, env=env, cwd=self.wt)
        self.assertEqual(
            r.returncode, 2,
            f"inert in the worktree the work happens in (ran in {self.wt}): {r.stderr!r}")
        self.assertIn("sp-aaa", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
