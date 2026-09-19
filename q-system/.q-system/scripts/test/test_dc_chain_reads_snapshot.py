#!/usr/bin/env python3
"""ASK-1811: the chain reads the snapshot, not the disk.

WHY. ASK-1808 made seal measure a snapshot and compare every file at the end, and left one
window NOT MET: chain_problems() and craft_problems() read the chain records from DISK after
the snapshot was taken. So a record swapped to a good one for the chain check and swapped back
before the final compare was caught by neither read (ASK-1808 finding-10).

These tests open that window exactly, in-process, against the REAL gate at its tracked path
with real producers and real chromium (verify contract 2): the good record goes in after the
real producers ran, and the bad one comes back immediately before the final compare. A watcher
thread cannot hit that window reliably; a hook in the same process can. Temp dirs only.
"""
import contextlib
import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_dc_seal_snapshot as snap  # noqa: E402  (the sealable-round fixture, shared)

REAL_GATE = HERE.parent / "design-chain-gate.py"
BAD_BRIEF = "# Brief\n\nwhatever I felt like, no anchor from the owner file\n"


def load_gate(name):
    spec = importlib.util.spec_from_file_location(name, REAL_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(snap.Base):
    def setUp(self):
        super().setUp()
        self.css.write_text(snap.PASSING_CSS)
        os.environ["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        self.addCleanup(os.environ.pop, "DESIGN_CHAIN_STATE", None)

    def enable(self, **craft):
        import json
        cfgp = self.round.parents[2] / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        cfg["craft"] = {"tier": "craft", **craft}
        cfgp.write_text(json.dumps(cfg))

    def seal_in_process(self, gate):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = gate.seal(self.round)
        return rc, err.getvalue()

    def swap_and_restore(self, gate, rel, good, bad):
        """`good` goes in after the real producers ran, `bad` comes back just before the final
        compare: the chain check is the only read in between."""
        f = self.round / rel
        real_producers, real_compare = gate.producer_problems, gate.files_that_differ

        def producers_then_swap(rd, pages, cfg):
            out = real_producers(rd, pages, cfg)
            f.write_text(good)
            return out

        def restore_then_compare(a, b):
            f.write_text(bad)
            return real_compare(a, gate.round_files(self.round))
        gate.producer_problems = producers_then_swap
        gate.files_that_differ = restore_then_compare


class Controls(Base):
    def test_a_bad_brief_is_refused(self):
        (self.round / "brief.md").write_text(BAD_BRIEF)
        rc, err = self.seal_in_process(load_gate("dcg_c1"))
        self.assertEqual(rc, 2, err)
        self.assertIn("brief.md does not quote verbatim", err)

    def test_an_honest_round_still_seals(self):
        # regression guard: the copied-brief check reads the LIVE siblings; the live round must
        # not be mistaken for a sibling of its own snapshot. require_fresh_brief switches the
        # check on: without it this test could not fail for its reason (review of 40e6cd3d)
        self.enable(require_fresh_brief=True)
        other = self.round.parent / "r0"
        other.mkdir()
        (other / "brief.md").write_text("# an older round's brief\n")
        rc, err = self.seal_in_process(load_gate("dcg_c2"))
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.round / "receipts.json").is_file())


class SwapAndRestoreInsideTheWindow(Base):
    def test_a_bad_brief_swapped_good_for_the_chain_check_only_is_refused(self):
        (self.round / "brief.md").write_text(BAD_BRIEF)
        good = "# Brief\n\n" + snap.OWNER + "\n"
        gate = load_gate("dcg_s1")
        self.swap_and_restore(gate, "brief.md", good, BAD_BRIEF)
        rc, err = self.seal_in_process(gate)
        self.assertEqual(rc, 2, "sealed a round whose brief on disk, before and after, fails the chain\n" + err)
        # the reason is the proof: at chain time the disk held the GOOD brief, so a refusal for
        # the bad one means the chain read the snapshot. (Refused there, seal never reaches the
        # final compare, so the hook that restores the bad brief is not called.)
        self.assertIn("brief.md does not quote verbatim", err)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_short_critique_swapped_long_for_the_chain_check_only_is_refused(self):
        crit = self.round / "critique.md"
        good = crit.read_text()
        bad = "## A\n1. a\n"
        crit.write_text(bad)
        gate = load_gate("dcg_s2")
        self.swap_and_restore(gate, "critique.md", good, bad)
        rc, err = self.seal_in_process(gate)
        self.assertEqual(rc, 2, err)
        self.assertIn("critique.md", err)
        self.assertFalse((self.round / "receipts.json").exists())


class MessagesNameTheLiveRound(Base):
    def test_a_refusal_names_the_round_not_the_snapshot(self):
        (self.round / "directions.md").unlink()
        rc, err = self.seal_in_process(load_gate("dcg_m1"))
        self.assertEqual(rc, 2, err)
        self.assertIn(str(self.round), err)
        self.assertNotIn("dc-seal-", err, "a refusal pointed at the temp snapshot, which is gone")



class ReadsThatLeaveTheRoundResolveLive(Base):
    """Seal checks the chain against the snapshot, whose parent is a temp dir. Every read that
    leaves the round (sibling rounds, the decisions ledger, the round an `implements` names)
    must resolve from the live tree, or it silently checks against nothing."""

    def sibling(self, name, brief):
        d = self.round.parent / name
        d.mkdir()
        (d / "brief.md").write_text(brief)
        return d

    def test_fresh_brief_and_a_founder_question_already_in_the_live_ledger_seal(self):
        # require_dispositions switches on the ledger read (K6 survived without it)
        self.enable(require_fresh_brief=True, require_dispositions=True)
        self.sibling("r0", "# an older round's own brief\n")
        crit = self.round / "critique.md"
        crit.write_text("FOUNDER[pick-colour] which palette?\n" + crit.read_text())
        (self.round.parent / "OPEN-DECISIONS.md").write_text("- pick-colour: open\n")
        rc, err = self.seal_in_process(load_gate("dcg_l1"))
        self.assertEqual(rc, 0, err)

    def test_a_byte_copied_sibling_brief_is_still_caught(self):
        self.enable(require_fresh_brief=True)
        self.sibling("r0", (self.round / "brief.md").read_text())
        rc, err = self.seal_in_process(load_gate("dcg_l2"))
        self.assertEqual(rc, 2, err)
        self.assertIn("byte-identical to r0/brief.md", err)

    def test_the_round_an_implements_names_is_found_beside_the_round(self):
        # Only that it RESOLVES. Whether it counts as sealed is ASK-1831's: a '{}' receipt no
        # longer does, and a round the gate really sealed does
        # (test_dc_seal_holds_outside_inputs.py, TheImplementsSourceMustBeSealedForReal).
        import json
        src = self.sibling("r0", "# the fan-out round's brief\n")
        (src / "directions.md").write_text("# A\nx\n# B\nx\n# C\nx\n")
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"implements": {"round": "r0", "direction": "A", "reason": "founder: build A"}}))
        rc, err = self.seal_in_process(load_gate("dcg_l3"))
        self.assertNotIn("does not exist", err)
        self.assertIn("names round 'r0', which is not sealed", err)

    def test_a_seal_leaves_no_cache_entry_for_its_temp_snapshot(self):
        # a RE-seal: only then is there a receipt in the snapshot to check (K5 survived a first seal)
        import json
        rc, err = self.seal_in_process(load_gate("dcg_l4"))
        self.assertEqual(rc, 0, err)
        rc, err = self.seal_in_process(load_gate("dcg_l5"))
        self.assertEqual(rc, 0, err)
        cache = Path(os.environ["DESIGN_CHAIN_STATE"]) / "round-cache.json"
        keys = json.loads(cache.read_text()).keys() if cache.is_file() else []
        self.assertEqual([k for k in keys if "dc-seal-" in k], [])


class OneRoundOneConfig(Base):
    """ASK-1811 review round 1 (40e6cd3d), Sana's triage 2026-09-19."""

    def test_the_round_lookup_never_climbs_above_the_snapshot(self):
        # finding-1: with no brief.md, round_dir_for walked from the snapshot up into $TMPDIR,
        # and a complete fake round sitting there was what the chain checked
        import shutil
        import tempfile
        fake = Path(tempfile.mkdtemp(prefix="dc1811-fake-"))
        self.addCleanup(shutil.rmtree, fake, True)
        for rel in ("brief.md", "directions.md", "critique.md", "proof.md", "checks/bio_gate.txt", "gate/icp.md"):
            src, dst = self.round / rel, fake / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        # a COMPLETE fake round: without a passing standard entry for the page the chain refuses
        # the fake for that instead, and the test passes for the wrong reason (first version did)
        import hashlib
        import json
        (fake / "standard.json").write_text(json.dumps([{
            "page": self.page.name, "sha256": hashlib.sha256(self.page.read_bytes()).hexdigest(),
            "pass": True, "measurements": [], "failures": {}}]))
        (self.round / "brief.md").unlink()
        old = tempfile.tempdir
        tempfile.tempdir = str(fake)
        self.addCleanup(setattr, tempfile, "tempdir", old)
        rc, err = self.seal_in_process(load_gate("dcg_o1"))
        self.assertEqual(rc, 2, err)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_relative_round_path_does_not_seal_against_the_producer_defaults(self):
        # finding-2: the producers got no config (defaults, 15px) while the chain found one
        self.css.write_text("p,a{font-size:16px}")            # fails the canon's 17, passes 15
        old = os.getcwd()
        os.chdir(self.round.parent)
        self.addCleanup(os.chdir, old)
        gate = load_gate("dcg_o2")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = gate.seal(Path("r1"))
        self.assertEqual(rc, 2, err.getvalue())
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_symlinked_round_is_checked_against_the_config_its_typed_path_finds(self):
        # finding-3: the chain walked the RESOLVED ancestors (a permissive config) while the
        # producers and the passive gate walk the typed ones (a strict config)
        import json
        import shutil
        strict = self.tmp / "strict"
        strict.mkdir()
        inst_cfg = self.round.parents[2] / "design-chain.json"
        shutil.copy(inst_cfg, strict / "design-chain.json")
        shutil.copytree(self.round.parents[2] / "canonical", strict / "canonical")
        cfg = json.loads(inst_cfg.read_text())
        cfg["owners"] = []
        inst_cfg.write_text(json.dumps(cfg))
        (strict / "r1").symlink_to(self.round)
        (self.round / "brief.md").write_text(BAD_BRIEF)
        gate = load_gate("dcg_o3")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = gate.seal(strict / "r1")
        self.assertEqual(rc, 2, err.getvalue())
        self.assertIn("brief.md does not quote verbatim", err.getvalue())


class ACorrectedPageMeetsTheFullBarAtSeal(Base):
    def test_seal_holds_a_corrected_page_to_the_chain_and_the_passive_gate_still_exempts_it(self):
        # finding-7, kept on purpose (Sana): a seal writes a receipt, a receipt says the chain was
        # measured; the correction exemption is the passive gate's alone
        import subprocess
        repo = self.tmp
        for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"], ["config", "user.name", "t"],
                    ["add", "-A"], ["commit", "-qm", "round"]):
            subprocess.run(["git", "-C", str(repo), *cmd], capture_output=True, check=True)
        gate = load_gate("dcg_p4")
        self.page.write_text(snap.PAGE.replace("every week", "every single week"))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.correct(self.page, "wording"), 0)
        (self.round / "critique.md").write_text("## A\n1. a\n")
        rc, err = self.seal_in_process(gate)
        self.assertEqual(rc, 2, err)
        self.assertIn("critique.md", err)
        self.assertEqual(gate.chain_problems(self.page), [])

if __name__ == "__main__":
    unittest.main()
