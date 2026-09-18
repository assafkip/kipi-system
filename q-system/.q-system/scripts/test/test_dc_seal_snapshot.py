#!/usr/bin/env python3
"""ASK-1808: seal measures a SNAPSHOT, so what is measured is what is sealed.

EVERY test here drives the PRODUCTION path: the real design-chain-gate.py at its real
location, the real producers beside it, real chromium. No gate copy, no stand-ins. Founder,
2026-09-18: "If the test passes, that's not the answer. The answer is: did the test pass, and
could you then run it on production and it would pass again every time."

Why it exists: dc-03 claimed a producer could no longer measure one set of bytes and sign
another. It was false in two consecutive review rounds. The final one sealed a FAILING page as
COMPLETE with the real gate: swap shared.css to a passing version when seal's server comes up,
swap it back once the verdict is written (A -> X -> A). Every sha matched. My own test for that
class swapped the file and LEFT it swapped, which is the one move an adversary would not make.

The required check runs with DC_REQUIRE_REAL_PRODUCERS=1, so a missing playwright FAILS.
Temp directories only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REAL_GATE = SCRIPTS / "design-chain-gate.py"
OWNER = "> **A business where somebody is paid to be accurate, and being wrong costs money"
FAILING_CSS = "p{font-size:9px}"       # honest verdict: smallest text 9px; min 15
PASSING_CSS = "p{font-size:18px}"
PAGE = ("<html><head><link rel='stylesheet' href='shared.css'></head><body>"
        "<h1>You work more hours than you bill.</h1><p>Somebody retypes it every week.</p>"
        "<a href='#'>Book</a></body></html>")


def require_real_producers(test):
    try:
        import playwright  # noqa: F401
    except ImportError:
        msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
        if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
            test.fail(msg)
        test.skipTest(msg)


class Base(unittest.TestCase):
    def setUp(self):
        require_real_producers(self)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc1808-"))
        inst = self.tmp / "instance"
        (inst / "canonical").mkdir(parents=True)
        (inst / "canonical" / "the-business.md").write_text("# B\n\n" + OWNER + "\n")
        (inst / "design-chain.json").write_text(json.dumps({
            "owners": [{"file": "canonical/the-business.md", "anchors": ["^> \\*\\*A business where somebody is paid"]}],
            "standard": {"min_body_px": 15}}))
        rd = self.round = inst / "site" / "design" / "r1"
        rd.mkdir(parents=True)
        self.page = rd / "Pair-laptop.html"
        self.page.write_text(PAGE)
        self.css = rd / "shared.css"
        (rd / "brief.md").write_text("# Brief\n\n" + OWNER + "\n")
        (rd / "directions.md").write_text("# A\nx\n# B\nx\n# C\nx\n")
        (rd / "critique.md").write_text("".join(f"## {d}\n" + "".join(f"{i}. a\n" for i in range(1, 10)) for d in "ABC"))
        (rd / "proof.md").write_text("Pair-laptop.html: capability proof\n")
        (rd / "checks").mkdir()
        (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir()
        (rd / "gate" / "icp.md").write_text("answers\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("DESIGN_CHAIN_ALLOW", "CLAUDE_PROJECT_DIR")}
        e["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        return e

    def seal(self, during=None):
        """Run the REAL gate. `during(proc)` runs in a thread while seal is alive."""
        proc = subprocess.Popen([sys.executable, str(REAL_GATE), "seal", str(self.round)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env())
        t = None
        if during:
            t = threading.Thread(target=during, args=(proc,), daemon=True)
            t.start()
        out, _ = proc.communicate(timeout=180)
        if t:
            t.join(timeout=10)
        return proc.returncode, out

    def verdict(self):
        p = self.round / "standard.json"
        if not p.is_file():
            return None
        return next((e for e in json.loads(p.read_text()) if e.get("page") == self.page.name), None)


def seal_is_listening(pid):
    r = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True)
    return "LISTEN" in r.stdout


class Controls(Base):
    """Honest runs, so the adversarial results below mean something."""

    def test_the_failing_stylesheet_really_fails(self):
        self.css.write_text(FAILING_CSS)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIs(self.verdict()["pass"], False, out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_the_passing_stylesheet_really_seals(self):
        self.css.write_text(PASSING_CSS)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertIs(self.verdict()["pass"], True)
        self.assertTrue((self.round / "receipts.json").is_file())


class SwapAndRestore(Base):
    """A -> X -> A. The file on disk is A before the seal and A after it. X exists only while
    the browser is looking."""

    def swap_and_restore(self, log):
        def during(proc):
            t0 = time.time()
            while proc.poll() is None and not seal_is_listening(proc.pid):
                time.sleep(0.01)
            self.css.write_text(PASSING_CSS)
            log.append(f"swapped to X at +{time.time() - t0:.2f}s (seal's server is up)")
            while proc.poll() is None and not (self.verdict() or {}).get("sha256"):
                time.sleep(0.01)
            self.css.write_text(FAILING_CSS)
            log.append(f"swapped back to A at +{time.time() - t0:.2f}s (verdict written)")
        return during

    def test_a_failing_round_cannot_be_sealed_by_showing_the_browser_a_passing_stylesheet(self):
        self.css.write_text(FAILING_CSS)
        log = []
        rc, out = self.seal(during=self.swap_and_restore(log))
        report = (f"watcher: {log}\nseal exit: {rc}\nseal said: {out.strip()[-300:]}\n"
                  f"shared.css on disk now == A (9px): {self.css.read_text() == FAILING_CSS}\n"
                  f"verdict: {self.verdict()}\nreceipt written: {(self.round / 'receipts.json').exists()}")
        print("\n--- A -> X -> A against the real gate ---\n" + report, file=sys.stderr)
        self.assertEqual(len(log), 2, f"the watcher never got its window, so nothing was tested\n{report}")
        self.assertEqual(self.css.read_text(), FAILING_CSS)
        self.assertNotEqual(rc, 0, "SEALED a round whose real stylesheet FAILS the standard\n" + report)
        self.assertFalse((self.round / "receipts.json").exists(), report)


class SwapAndLeave(Base):
    def test_an_asset_that_changes_during_the_seal_is_refused_and_named(self):
        self.css.write_text(PASSING_CSS)

        def during(proc):
            while proc.poll() is None and not seal_is_listening(proc.pid):
                time.sleep(0.01)
            self.css.write_text("p{font-size:20px}")
        rc, out = self.seal(during=during)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("shared.css", out)
        self.assertFalse((self.round / "receipts.json").exists())


class VerdictsComeBack(Base):
    def test_the_producers_verdict_lands_in_the_live_round_not_only_in_the_snapshot(self):
        self.css.write_text(PASSING_CSS)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        v = self.verdict()
        self.assertIsNotNone(v, "standard.json did not come back to the round")
        self.assertIn("measurements", v)

    def test_nothing_is_left_behind_in_the_temp_directory(self):
        self.css.write_text(PASSING_CSS)
        before = {p.name for p in Path(tempfile.gettempdir()).glob("dc-seal-*")}
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        after = {p.name for p in Path(tempfile.gettempdir()).glob("dc-seal-*")}
        self.assertEqual(after - before, set(), "a snapshot of the round outlived the seal")


class SwapThePageItself(Base):
    def test_a_failing_page_cannot_be_sealed_by_showing_the_browser_another_page(self):
        long_page = PAGE.replace("<p>", "<p>" + "word " * 200)      # honest verdict: too many words
        self.css.write_text(PASSING_CSS)
        self.page.write_text(long_page)
        log = []

        def during(proc):
            while proc.poll() is None and not seal_is_listening(proc.pid):
                time.sleep(0.01)
            self.page.write_text(PAGE)
            log.append("X")
            while proc.poll() is None and not (self.verdict() or {}).get("sha256"):
                time.sleep(0.01)
            self.page.write_text(long_page)
            log.append("A")
        rc, out = self.seal(during=during)
        self.assertEqual(log, ["X", "A"], "the watcher never got its window\n" + out)
        self.assertNotEqual(rc, 0, out)
        self.assertFalse((self.round / "receipts.json").exists(), out)


class TheSnapshotOnDisk(Base):
    """The residual the receipt names: the same OS user can write into the snapshot directory.
    The browser is served from memory, so that must end in a refusal and never a forged pass."""

    def test_writing_a_passing_stylesheet_into_the_snapshot_does_not_seal_a_failing_round(self):
        self.css.write_text(FAILING_CSS)
        hits = []

        def during(proc):
            while proc.poll() is None:
                for f in Path(tempfile.gettempdir()).glob("dc-seal-*/r1/shared.css"):
                    try:
                        f.write_text(PASSING_CSS)
                        hits.append(str(f))
                    except OSError:
                        pass
                time.sleep(0.005)
        rc, out = self.seal(during=during)
        self.assertTrue(hits, "the snapshot was never found, so nothing was tested")
        self.assertNotEqual(rc, 0, out)
        self.assertFalse((self.round / "receipts.json").exists(), out)

    def test_the_snapshot_directory_is_private_to_the_user(self):
        self.css.write_text(PASSING_CSS)
        modes = []

        def during(proc):
            while proc.poll() is None:
                for d in Path(tempfile.gettempdir()).glob("dc-seal-*"):
                    try:
                        modes.append(d.stat().st_mode & 0o777)
                    except OSError:
                        pass
                time.sleep(0.005)
        rc, out = self.seal(during=during)
        self.assertEqual(rc, 0, out)
        self.assertTrue(modes, "the snapshot was never seen")
        self.assertEqual(set(modes), {0o700})


class TheRealGapProducerIsHandedTheSnapshot(Base):
    """NOT a full gap pass: that needs captured exemplars, which live in an instance and are
    dc-21's fixtures. This proves the wiring on the real path: the real gap producer accepts
    the snapshot as the served round (it refuses when served bytes differ from the directory
    it was handed) and is pointed at the LIVE references directory, not one beside the snapshot."""

    def test_it_gets_past_the_served_bytes_check_and_looks_for_exemplars_beside_the_live_round(self):
        self.css.write_text(PASSING_CSS)
        cfgp = self.round.parents[2] / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        cfgp.write_text(json.dumps(cfg))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertNotIn("served bytes differ", out)
        self.assertIn("usable exemplar capture", out)
        self.assertIn(str((self.round.parent / "references").resolve()), out)
        self.assertFalse((self.round / "receipts.json").exists())


class TheReceipt(Base):
    def test_it_says_what_was_measured_and_names_the_residual(self):
        self.css.write_text(PASSING_CSS)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        rec = json.loads((self.round / "receipts.json").read_text())
        self.assertEqual(rec["__assets__"]["measured"], "snapshot")
        self.assertIn("same OS user", rec["__assets__"]["residual"])
        gate = load_real_gate()
        self.assertEqual(rec["__assets__"]["sha256"], gate.round_asset_digest(self.round))


class TheDigestCoversEveryServedPath(Base):
    def test_a_new_file_anywhere_the_server_serves_moves_the_digest(self):
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        for rel in ("gate/style.css", "checks/extra.js", "notes.md", "deep/er/font.woff2"):
            before = gate.round_asset_digest(self.round)
            f = self.round / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
            self.assertNotEqual(before, gate.round_asset_digest(self.round), f"{rel} is served and not digested")

    def test_everything_the_digest_covers_is_served_and_nothing_else_is(self):
        import urllib.error
        import urllib.request
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        (self.round / "gate" / "style.css").write_text("x")
        files = gate.round_files(self.round)
        with gate.served_round(self.round) as base:
            for rel, data in files.items():
                self.assertEqual(urllib.request.urlopen(f"{base}/{rel}", timeout=5).read(), data, rel)
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{base}/../../design-chain.json", timeout=5)

    def test_a_seal_names_a_new_file_dropped_into_gate_while_it_ran(self):
        self.css.write_text(PASSING_CSS)

        def during(proc):
            while proc.poll() is None and not seal_is_listening(proc.pid):
                time.sleep(0.01)
            (self.round / "gate" / "late.css").write_text("p{font-size:9px}")
        rc, out = self.seal(during=during)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("gate/late.css", out)


class OneSnapshotPerSeal(Base):
    """Both survived the first mutation run (M12, M11), so both are pinned here. In-process,
    because the window they need is between two lines of seal and no watcher can time it."""

    def test_the_producers_measure_the_snapshot_seal_took_not_a_second_one(self):
        # M12: seal kept snapshot S1 for its final comparison while the producers quietly took
        # their own S2. A -> X -> A between the two: S1 = A, S2 = X, live = A at the end.
        # REAL producers and real chromium; only the timing is driven from here.
        gate = load_real_gate()
        self.css.write_text(FAILING_CSS)
        real = gate.producer_problems

        def swapped_around_the_producers(rd, pages, cfg):
            self.css.write_text(PASSING_CSS)
            try:
                return real(rd, pages, cfg)
            finally:
                self.css.write_text(FAILING_CSS)
        gate.producer_problems = swapped_around_the_producers
        os.environ["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        self.addCleanup(os.environ.pop, "DESIGN_CHAIN_STATE", None)
        self.assertEqual(gate.seal(self.round), 2)
        self.assertIs(self.verdict()["pass"], False, "the producers measured bytes seal never held")
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_verdict_must_carry_the_sha_of_the_bytes_held_in_memory(self):
        # M11. A STAND-IN producer, and the only one in this file: the real one refuses when its
        # local page differs from the served bytes, so it can never produce this entry. The
        # gate must not depend on that courtesy.
        import hashlib
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)

        def forged(name, args):
            if name != gate.STANDARD_PRODUCER:
                return 0, ""
            page = Path(args[0])
            page.write_text("<html><body><p>another page</p></body></html>")
            entry = {"page": page.name, "sha256": hashlib.sha256(page.read_bytes()).hexdigest(), "pass": True}
            (page.parent / "standard.json").write_text(json.dumps([entry]))
            return 0, "PASS"
        gate.run_producer = forged
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = gate.seal(self.round)
        self.assertEqual(rc, 2)
        # the REASON, not only the code: a later layer (the live standard.json no longer matches
        # the live page) also refuses, and the first version of this test passed on that alone
        self.assertIn("no fresh verdict for this page", err.getvalue())
        self.assertFalse((self.round / "receipts.json").exists())


def load_real_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dcg_1808", REAL_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    unittest.main()
