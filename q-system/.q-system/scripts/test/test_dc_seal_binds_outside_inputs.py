#!/usr/bin/env python3
"""ASK-1833: seal binds the held outside inputs at the end and refuses escaping paths.

WHY. ASK-1831 made seal read every input outside the round from a held copy. The adversarial
review of f091da79 found what that left open, each reproduced with the real gate:

  1. the held copy was never compared to the live tree at the end, so an input swapped to a
     passing version just BEFORE seal() and restored after the snapshot sealed (X-then-A,
     moved to before the snapshot);
  2. an absolute config path, or enough `..` to reach `/`, joined straight past the held tree
     and read the live file;
  3. after the chain, seal read the config and the declared sources live;
  6. the read tracer saw four APIs and only the chain.

Real gate at its tracked path, real producers, real chromium (verify contract 2). Temp dirs only.
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
from test_dc_chain_reads_snapshot import load_gate  # noqa: E402
from test_dc_seal_holds_outside_inputs import Base, put  # noqa: E402

NEW_WORDING = "> **A business where somebody is paid to be precise, the new wording"


class LiveReadTracer:
    """Records every READ of a file or directory listing under `watch`, through builtins.open,
    io.open, Path.open (read_text and read_bytes go through it), os.scandir and os.listdir."""

    def __init__(self, watch: Path):
        self.watch = os.path.realpath(watch)
        self.reads: list[str] = []
        self.apis: set[str] = set()
        self.on = False

    def _note(self, p, mode="r", api=""):
        if not self.on or p is None or any(c in str(mode) for c in "wax+"):
            return
        if isinstance(p, int):
            return
        rp = os.path.realpath(os.fspath(p))
        if rp == self.watch or rp.startswith(self.watch + os.sep):
            self.reads.append(rp)
            self.apis.add(api)

    @contextlib.contextmanager
    def installed(self):
        real = {"open": builtins.open, "io_open": io.open, "path_open": pathlib.Path.open,
                "scandir": os.scandir, "listdir": os.listdir}
        tr = self

        def t_open(file, mode="r", *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)):
                tr._note(file, mode, "open")
            return real["open"](file, mode, *a, **k)

        def t_path_open(self_, mode="r", *a, **k):
            tr._note(self_, mode, "Path.open")
            return real["path_open"](self_, mode, *a, **k)

        def t_scandir(path="."):
            tr._note(path, api="scandir")
            return real["scandir"](path)

        def t_listdir(path="."):
            tr._note(path, api="listdir")
            return real["listdir"](path)
        builtins.open, io.open, pathlib.Path.open = t_open, t_open, t_path_open
        os.scandir, os.listdir = t_scandir, t_listdir
        try:
            yield self
        finally:
            builtins.open, io.open, pathlib.Path.open = real["open"], real["io_open"], real["path_open"]
            os.scandir, os.listdir = real["scandir"], real["listdir"]


class Binding(Base):
    def owner(self):
        return self.inst / "canonical" / "the-business.md"

    def failing_owner(self):
        """The owner as it stands on disk: new wording the brief does not quote."""
        o = self.owner()
        old = o.read_text()
        new = old.replace(snap.OWNER, NEW_WORDING)
        o.write_text(new)
        return old, new


class AnInputChangedJustBeforeTheSnapshotIsCaughtAtTheEnd(Binding):
    def test_an_owner_swapped_before_seal_and_restored_after_the_snapshot_is_refused(self):
        old, new = self.failing_owner()
        gate = load_gate("dcb_a")
        real_producers = gate.producer_problems

        def restore_then_measure(rd, pages, cfg):
            self.owner().write_text(new)          # the snapshot already holds the passing one
            return real_producers(rd, pages, cfg)
        gate.producer_problems = restore_then_measure
        self.owner().write_text(old)              # passing, only until the snapshot is taken
        rc, err = self.seal_in_process(gate)
        self.assert_refused(rc, err, "changed while this seal")
        self.assertIn("the-business.md", err)

    def test_an_honest_seal_with_every_input_still_seals(self):
        # control: the end compare must not refuse a round whose inputs did not move
        self.enable(require_fresh_brief=True, require_dispositions=True)
        self.config(exemplars_dir="exemplars")
        put(self.round.parent / "r0" / "brief.md", "# r0's own brief\n")()
        put(self.round.parent / "OPEN-DECISIONS.md", "- nothing open\n")()
        put(self.inst / "exemplars" / "Pair-laptop.png", "png")()
        (self.round / "directions.md").write_text("# A\nPair-laptop.png\n# B\nx\n# C\nx\n")
        rc, err = self.seal_in_process(load_gate("dcb_a2"))
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.round / "receipts.json").is_file())


class APathThatEscapesTheHeldTreeIsRefused(Binding):
    def seal_with_owner_path(self, name, owner_path):
        old, new = self.failing_owner()
        cfg = json.loads(self.cfgp.read_text())
        cfg["owners"][0]["file"] = owner_path
        self.cfgp.write_text(json.dumps(cfg))
        gate = load_gate(name)
        self.window(gate, put(self.owner(), old), put(self.owner(), new))
        return self.seal_in_process(gate)

    def test_an_absolute_owner_path(self):
        rc, err = self.seal_with_owner_path("dcb_b1", str(self.owner()))
        self.assert_refused(rc, err, "climbs out of the tree")

    def test_an_owner_path_that_climbs_to_the_root(self):
        rel = "../" * 64 + str(self.owner()).lstrip("/")
        rc, err = self.seal_with_owner_path("dcb_b2", rel)
        self.assert_refused(rc, err, "climbs out of the tree")


class SealReadsTheSourcesAfterTheChainFromHeldBytes(Binding):
    def test_a_declared_source_that_exists_only_inside_the_window_is_refused(self):
        live = self.inst / "site" / "live" / "index.html"
        (self.round / "sources.json").write_text(json.dumps(
            {"sources": {"site/live/index.html": "founder: this round renders it"}}))
        (self.round / "build.sh").write_text("cat ../../live/index.html\n")
        gate = load_gate("dcb_c")
        self.window(gate, put(live, "<p>live</p>"), put(live, None))
        self.assert_refused(*self.seal_in_process(gate), "which does not exist")


class NoLiveReadAfterTheSnapshot(Binding):
    def test_the_tracer_sees_a_planted_read_through_every_api_it_wraps(self):
        # the check that the check can fail: each API, one planted live read
        f = self.round / "brief.md"
        tr = LiveReadTracer(self.inst)
        with tr.installed():
            tr.on = True
            open(f).close()
            io.open(f).close()
            f.open().close()
            f.read_text()
            f.read_bytes()
            list(os.scandir(self.round))
            os.listdir(self.round)
        # read_text and read_bytes reach Path.open, which reaches open: one read, several notes
        self.assertEqual(tr.apis, {"open", "Path.open", "scandir", "listdir"}, tr.reads)

    def test_no_read_of_the_live_instance_from_snapshot_to_the_final_compare(self):
        self.enable(require_fresh_brief=True, require_dispositions=True, require_grounding="teardown.md")
        self.config(exemplars_dir="exemplars")
        put(self.round.parent / "r0" / "brief.md", "# r0's own brief\n")()
        put(self.round.parent / "OPEN-DECISIONS.md", "- pick-colour: open\n")()
        put(self.inst / "exemplars" / "stripe.png", "png")()
        put(self.inst / "teardown.md", "# Teardown\n\nstripe\n")()
        put(self.inst / "design" / "VISION.md", "# Vision\n")()
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "t1", "reference": "stripe"}]}))
        (self.round / "sources.json").write_text(json.dumps({"sources": {"site/live/index.html": "r"}}))
        put(self.inst / "site" / "live" / "index.html", "<p>x</p>")()
        (self.round / "build.sh").write_text("cat ../../live/index.html\n")
        gate = load_gate("dcb_t")
        tr = LiveReadTracer(self.inst)
        real_seal, real_compare = gate._seal_snapshot, gate.files_that_differ

        def traced(*a, **k):
            tr.on = True
            try:
                return real_seal(*a, **k)
            finally:
                tr.on = False

        def compare(a, b):
            tr.on = False                        # the final compare reads live by design
            return real_compare(a, b)
        gate._seal_snapshot, gate.files_that_differ = traced, compare
        with tr.installed():
            rc, err = self.seal_in_process(gate)
        self.assertIn(rc, (0, 2), err)
        self.assertEqual(sorted(set(tr.reads)), [], "the seal read the live instance after the snapshot")


if __name__ == "__main__":
    unittest.main()
