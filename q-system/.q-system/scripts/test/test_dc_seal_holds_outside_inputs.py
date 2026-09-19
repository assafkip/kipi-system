#!/usr/bin/env python3
"""ASK-1831: seal reads the inputs outside the round from held bytes, not the live tree.

WHY. ASK-1811 made the chain read every ROUND file from the snapshot. Everything it reads
OUTSIDE the round (the config, owner files, the OPEN-DECISIONS ledger, the round an
`implements` names, sibling briefs, exemplars, the vision file, the grounding file, the
references the gap producer measures against) was still read live inside the seal window. An
input swapped in once the snapshot is taken and restored before the final compare sealed a
round that fails on disk before and after (adversarial review of 40e6cd3d, findings 4-6,
each reproduced). A before/after compare lets X-then-back-to-A through (the ASK-1808 scar),
so the chain has to READ held bytes.

The window is opened in-process against the REAL gate at its tracked path, real producers,
real chromium (verify contract 2): the swap goes in when the producers start (the snapshot is
already taken) and comes back immediately before the final compare. Temp dirs only.
"""
import builtins
import contextlib
import io
import json
import os
import pathlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_dc_seal_snapshot as snap  # noqa: E402  (the sealable-round fixture, shared)
from test_dc_chain_reads_snapshot import BAD_BRIEF, load_gate  # noqa: E402


class Base(snap.Base):
    def setUp(self):
        super().setUp()
        self.css.write_text(snap.PASSING_CSS)
        os.environ["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        self.addCleanup(os.environ.pop, "DESIGN_CHAIN_STATE", None)
        self.inst = self.round.parents[2]
        self.cfgp = self.inst / "design-chain.json"

    def config(self, **top):
        cfg = json.loads(self.cfgp.read_text())
        cfg.update(top)
        self.cfgp.write_text(json.dumps(cfg))

    def enable(self, **craft):
        self.config(craft={"tier": "craft", **craft})

    def seal_in_process(self, gate, rd=None):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = gate.seal(rd or self.round)
        return rc, err.getvalue()

    def window(self, gate, swap_in, restore):
        """`swap_in` runs when the producers start (after the snapshot), `restore` immediately
        before the final compare: everything seal reads in between is inside the window."""
        real_producers, real_compare = gate.producer_problems, gate.files_that_differ

        def producers(rd, pages, cfg):
            swap_in()
            return real_producers(rd, pages, cfg)

        def compare(a, b):
            restore()
            return real_compare(a, gate.round_files(self.round))
        gate.producer_problems, gate.files_that_differ = producers, compare

    def assert_refused(self, rc, err, reason):
        self.assertEqual(rc, 2, "sealed a round that fails on disk before and after the seal\n" + err)
        self.assertIn(reason, err)
        self.assertFalse((self.round / "receipts.json").exists())


def put(path: Path, text):
    def go():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    return go


class AnInputSwappedOnlyInsideTheWindowIsNotWhatSealReads(Base):
    def test_1_the_config(self):
        (self.round / "brief.md").write_text(BAD_BRIEF)
        strict = self.cfgp.read_text()
        loose = json.loads(strict)
        loose["owners"] = []
        gate = load_gate("dco_1")
        self.window(gate, put(self.cfgp, json.dumps(loose)), put(self.cfgp, strict))
        self.assert_refused(*self.seal_in_process(gate), "brief.md does not quote verbatim")

    def test_2_an_owner_file(self):
        owner = self.inst / "canonical" / "the-business.md"
        old = owner.read_text()
        new = old.replace(snap.OWNER, "> **A business where somebody is paid to be precise, the new wording")
        owner.write_text(new)                       # the brief quotes the OLD wording
        gate = load_gate("dco_2")
        self.window(gate, put(owner, old), put(owner, new))
        self.assert_refused(*self.seal_in_process(gate), "brief.md does not quote verbatim")

    def test_3_the_open_decisions_ledger(self):
        self.enable(require_dispositions=True)
        crit = self.round / "critique.md"
        crit.write_text("FOUNDER[pick-colour] which palette?\n" + crit.read_text())
        ledger = self.round.parent / "OPEN-DECISIONS.md"
        gate = load_gate("dco_3")
        self.window(gate, put(ledger, "- pick-colour: open\n"), put(ledger, None))
        self.assert_refused(*self.seal_in_process(gate), "pick-colour")

    def test_4_the_implements_source(self):
        src = self.round.parent / "r0"
        src.mkdir()
        (src / "brief.md").write_text("# the fan-out round's brief\n")
        (src / "directions.md").write_text("# A\nx\n# B\nx\n# C\nx\n")
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"implements": {"round": "r0", "direction": "A", "reason": "founder: build A"}}))
        gate = load_gate("dco_4")
        self.window(gate, put(src / "receipts.json", "{}\n"), put(src / "receipts.json", None))
        self.assert_refused(*self.seal_in_process(gate), "not sealed")

    def test_5_a_sibling_brief(self):
        self.enable(require_fresh_brief=True)
        sib = self.round.parent / "r0" / "brief.md"
        copied = (self.round / "brief.md").read_text()
        put(sib, copied)()
        gate = load_gate("dco_5")
        self.window(gate, put(sib, "# r0's own brief\n"), put(sib, copied))
        self.assert_refused(*self.seal_in_process(gate), "byte-identical to r0/brief.md")

    def test_6_the_exemplars(self):
        self.config(exemplars_dir="exemplars")
        ex = self.inst / "exemplars" / "stripe.png"
        put(ex, "png")()
        gate = load_gate("dco_6")
        self.window(gate, put(ex, None), put(ex, "png"))
        self.assert_refused(*self.seal_in_process(gate), "cites none of the exemplars")

    def test_7_the_vision_file(self):
        vf = self.inst / "design" / "VISION.md"
        put(vf, "# Vision\n\nno founder words here\n")()
        gate = load_gate("dco_7")
        self.window(gate, put(vf, None), put(vf, "# Vision\n\nno founder words here\n"))
        self.assert_refused(*self.seal_in_process(gate), "founder block(s)")

    def test_8_the_grounding_file(self):
        self.enable(require_grounding="teardown.md")
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "t1", "reference": "stripe"}]}))
        td = self.inst / "teardown.md"
        put(td, "# Teardown\n\nnothing torn down yet\n")()
        gate = load_gate("dco_8")
        self.window(gate, put(td, "# Teardown\n\nstripe: the ledger rows\n"),
                    put(td, "# Teardown\n\nnothing torn down yet\n"))
        self.assert_refused(*self.seal_in_process(gate), "which is not in teardown.md")

    def test_9_the_producers_get_the_held_references_and_config(self):
        # No rc=0 exists to flip here: a gap PASS needs real exemplar captures, which are dc-21's
        # fixtures. What is measurable is the bytes each producer is handed at the moment it runs:
        # the references and the config as they were when the snapshot was taken, never the
        # window's.
        self.enable(require_gap_check=True)
        ref = self.round.parent / "references" / "a.json"
        put(ref, '{"disk": 1}')()
        disk_cfg = self.cfgp.read_text()
        window_cfg = json.dumps({**json.loads(disk_cfg), "_window": 1})
        gate = load_gate("dco_9")

        def swap():
            put(ref, '{"window": 1}')()
            put(self.cfgp, window_cfg)()

        def restore():
            put(ref, '{"disk": 1}')()
            put(self.cfgp, disk_cfg)()
        self.window(gate, swap, restore)
        seen = []
        real_run = gate.run_producer

        # *rest: dc-05 gave run_producer a timeout and a stage name, and a spy taking only
        # (producer, args) made every seal here a TypeError, red and unseen since (ASK-1841)
        def spy(producer, args, *rest):
            for flag in ("--refs", "--config"):
                if flag in args:
                    p = Path(args[args.index(flag) + 1])
                    body = (p / "a.json").read_text() if p.is_dir() else p.read_text()
                    seen.append((flag, body))
            return real_run(producer, args, *rest)
        gate.run_producer = spy
        rc, err = self.seal_in_process(gate)
        self.assertEqual(rc, 2, err)
        self.assertIn(("--refs", '{"disk": 1}'), seen, err)
        self.assertIn(("--config", disk_cfg), seen, err)
        self.assertNotIn(("--config", window_cfg), seen, err)


class TheImplementsSourceMustBeSealedForReal(Base):
    def test_an_empty_receipt_is_not_a_seal(self):
        src = self.round.parent / "r0"
        src.mkdir()
        (src / "directions.md").write_text("# A\nx\n# B\nx\n# C\nx\n")
        (src / "receipts.json").write_text("{}\n")
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"implements": {"round": "r0", "direction": "A", "reason": "founder: build A"}}))
        self.assert_refused(*self.seal_in_process(load_gate("dco_r1")), "not sealed")

    def test_a_round_the_gate_really_sealed_is_one_a_round_may_implement(self):
        # the control: without it the refusal above could be "implements always refuses"
        src = self.round.parent / "r0"
        src.mkdir()
        for f in self.round.rglob("*"):
            if f.is_file():
                dest = src / f.relative_to(self.round)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f.read_bytes())
        (src / "brief.md").write_text((self.round / "brief.md").read_text() + "\nthe fan-out\n")
        gate = load_gate("dco_r2")
        rc, err = self.seal_in_process(gate, src)
        self.assertEqual(rc, 0, err)
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"implements": {"round": "r0", "direction": "A", "reason": "founder: build A"}}))
        rc, err = self.seal_in_process(load_gate("dco_r3"))
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.round / "receipts.json").is_file())


class NoPageSkipsTheChainAtSeal(Base):
    """Adversarial review of f091da79, findings 4 and 5 (Sana's triage: fixed here)."""

    def test_a_round_that_declares_its_own_page_a_source_is_still_checked(self):
        # finding-4, NEW in f091da79: the held config let sourced_page() work during a seal, so
        # a hand-written __sources__ receipt skipped the brief, the critique and gate/. Only on a
        # resolved temp dir; on macOS the /var symlink refused it by accident, so pin one here.
        import hashlib
        import shutil
        import tempfile
        (self.round / "brief.md").write_text(BAD_BRIEF)
        (self.round / "critique.md").unlink()
        shutil.rmtree(self.round / "gate")
        rel = "site/design/r1/Pair-laptop.html"
        (self.round / "sources.json").write_text(json.dumps({"sources": {rel: "founder: me"}}))
        (self.round / "proof.md").write_text("proof of r1/Pair-laptop.html\n")
        (self.round / "receipts.json").write_text(json.dumps(
            {"__sources__": {rel: hashlib.sha256(self.page.read_bytes()).hexdigest()}}))
        old = tempfile.tempdir
        tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
        self.addCleanup(setattr, tempfile, "tempdir", old)
        rc, err = self.seal_in_process(load_gate("dco_f4"))
        self.assertEqual(rc, 2, err)
        self.assertIn("brief.md does not quote verbatim", err)

    def test_a_round_path_containing_receipt_does_not_hide_a_problem_on_reseal(self):
        # finding-5: the re-seal filter dropped every problem whose text held "receipt"
        import shutil
        shutil.rmtree(self.round / "gate")
        (self.round / "receipts.json").write_text("{}\n")
        new = self.tmp / "receipt-instance"
        self.inst.rename(new)
        self.round = new / "site" / "design" / "r1"
        rc, err = self.seal_in_process(load_gate("dco_f5"))
        self.assertEqual(rc, 2, err)
        self.assertIn("gate/", err)


class NoReadInsideTheSealLeavesTheHeldTree(Base):
    """The class check. Nine tests above name nine inputs; this one names none, so an input
    nobody has thought of yet is caught when a read reaches it."""

    def test_every_read_the_chain_makes_during_a_seal_is_inside_the_held_tree(self):
        self.enable(require_fresh_brief=True, require_dispositions=True, require_grounding="teardown.md")
        self.config(exemplars_dir="exemplars")
        put(self.round.parent / "r0" / "brief.md", "# r0's own brief\n")()
        put(self.round.parent / "OPEN-DECISIONS.md", "- pick-colour: open\n")()
        put(self.inst / "exemplars" / "stripe.png", "png")()
        put(self.inst / "teardown.md", "# Teardown\n\nstripe\n")()
        put(self.inst / "design" / "VISION.md", "# Vision\n")()
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "t1", "reference": "stripe"}]}))
        gate = load_gate("dco_t1")
        reads: list[str] = []
        roots: list[str] = []
        real = {"open": builtins.open, "read_text": pathlib.Path.read_text,
                "read_bytes": pathlib.Path.read_bytes, "iterdir": pathlib.Path.iterdir}

        def note(p):
            reads.append(os.path.realpath(os.fspath(p)))

        def t_open(file, *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)):
                note(file)
            return real["open"](file, *a, **k)

        def t_read_text(self_, *a, **k):
            note(self_)
            return real["read_text"](self_, *a, **k)

        def t_read_bytes(self_, *a, **k):
            note(self_)
            return real["read_bytes"](self_, *a, **k)

        def t_iterdir(self_, *a, **k):
            note(self_)
            return real["iterdir"](self_, *a, **k)
        real_chain = gate.chain_problems

        def traced_chain(page, honor_seal=True):
            for held in gate._SNAPSHOTS.values():
                roots.append(os.path.realpath(getattr(held, "root", held.dir)))
            builtins.open, pathlib.Path.read_text = t_open, t_read_text
            pathlib.Path.read_bytes, pathlib.Path.iterdir = t_read_bytes, t_iterdir
            try:
                return real_chain(page, honor_seal)
            finally:
                builtins.open, pathlib.Path.read_text = real["open"], real["read_text"]
                pathlib.Path.read_bytes, pathlib.Path.iterdir = real["read_bytes"], real["iterdir"]
        gate.chain_problems = traced_chain
        rc, err = self.seal_in_process(gate)
        self.assertTrue(roots, "the chain never ran inside a seal: " + err)
        self.assertTrue(reads, "the tracer saw no reads at all, so it traced nothing")
        outside = sorted({r for r in reads if not any(r == x or r.startswith(x + os.sep) for x in roots)})
        self.assertEqual(outside, [], "reads that left the held tree during a seal")


if __name__ == "__main__":
    unittest.main()
