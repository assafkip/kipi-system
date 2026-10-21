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
CANON_MIN_BODY_PX = 17                 # NOT the producer's DEFAULTS value (15): a dropped --config must show
FAILING_CSS = "p{font-size:9px}"       # honest verdict: smallest text 9px; min 17
PASSING_CSS = "p,a{font-size:18px}"     # the link too: at the browser's 16px it fails the canon's 17
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
            "standard": {"min_body_px": CANON_MIN_BODY_PX}}))
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

    def record_brief_reads(self):
        """brief-reads.json as the gate's hook writes it (dc-16): a session transcript that Read every
        owner the config names, handed to the REAL recorder. Needed wherever require_fresh_brief is on."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("snap_recorder", REAL_GATE)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        cfgp = self.round.parents[2] / "design-chain.json"
        owners = [o["file"] for o in json.loads(cfgp.read_text())["owners"]]
        t = self.tmp / "brief-session.jsonl"
        t.write_text("".join(json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": str(cfgp.parent / o)}}]}}) + "\n"
            for o in owners))
        gate.record_brief_reads(self.round, str(t), "s-fixture")

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


def wait_for_the_server(proc, limit=60.0):
    """WHY the wait ended: 'listening', 'exited' or 'timeout'. The first version swapped the file
    after the loop whatever had ended it, so with lsof missing or slow the swap landed after seal
    had gone and the test stayed green without attacking anything (standard review of 4ab043d7).
    Looked up through the module, so a test can prove this check is able to fail."""
    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            return "exited"
        if sys.modules[__name__].seal_is_listening(proc.pid):
            return "listening"
        time.sleep(0.01)
    return "timeout"


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

    def test_the_producer_is_handed_the_rounds_own_canon_not_its_defaults(self):
        # Mutant M-H (adversarial review of 4ab043d7): drop the --config seal hands the producer
        # and every test stayed green, because the fixture's 15 WAS the producer's default. The
        # snapshot has no design-chain.json above it, so without --config the canon is ignored.
        self.css.write_text("p,a{font-size:16px}")          # passes a floor of 15, fails the canon's 17
        rc, out = self.seal()
        self.assertEqual(self.verdict()["config"]["min_body_px"], CANON_MIN_BODY_PX, out)
        self.assertEqual(rc, 2, out)
        self.assertIs(self.verdict()["pass"], False)


class SwapAndRestore(Base):
    """A -> X -> A. The file on disk is A before the seal and A after it. X exists only while
    the browser is looking."""

    def swap_and_restore(self, log):
        def during(proc):
            t0 = time.time()
            why = wait_for_the_server(proc)
            log.append(why)
            if why != "listening":
                return
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
        self.assertEqual(log[0], "listening", f"the watcher never saw seal's server, so nothing was attacked\n{report}")
        self.assertEqual(len(log), 3, report)
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
        # the snapshot (18px) measured PASS; the round on disk is no longer those bytes
        self.assertIsNone(self.verdict(), "a refused seal left a pass:true verdict in the live round")


class VerdictsComeBack(Base):
    def test_the_producers_verdict_lands_in_the_live_round_not_only_in_the_snapshot(self):
        self.css.write_text(PASSING_CSS)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        v = self.verdict()
        self.assertIsNotNone(v, "standard.json did not come back to the round")
        self.assertIn("measurements", v)

    def test_nothing_is_left_behind_after_a_seal_that_exits_on_its_own(self):
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
            log.append(wait_for_the_server(proc))
            if log[0] != "listening":
                return
            self.page.write_text(PAGE)
            log.append("X")
            while proc.poll() is None and not (self.verdict() or {}).get("sha256"):
                time.sleep(0.01)
            self.page.write_text(long_page)
            log.append("A")
        rc, out = self.seal(during=during)
        self.assertEqual(log, ["listening", "X", "A"], "the watcher never saw seal's server\n" + out)
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
                # the held tree mirrors each file at its own absolute path (ASK-1831), so the round
                # sits deep under the snapshot root
                for f in Path(tempfile.gettempdir()).glob("dc-seal-*/**/r1/shared.css"):
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
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base}/../../design-chain.json", timeout=5)
            ctx.exception.close()

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

        def forged(name, args, *rest):
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


class WhatThePageAskedForAndDidNotGet(Base):
    """A 404 stylesheet leaves the browser's 16px default, which passed a 15px floor: the round
    sealed with its real stylesheet at 9px, no race needed (adversarial review of 4ab043d7).
    Each test asserts the REASON, because the canon here (17) also fails a 16px page."""

    def refused_for(self, name):
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("does not serve it", out)
        self.assertIn(name, out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_stylesheet_symlinked_outside_the_round(self):
        (self.round.parent / "shared.css").write_text(FAILING_CSS)
        self.css.symlink_to(self.round.parent / "shared.css")
        self.refused_for("shared.css")

    def test_a_stylesheet_with_a_non_ascii_name_is_served_under_its_own_name(self):
        # no charset on the page made chromium ask for a mojibake name. With the charset the
        # real file is found, measured at 9px, and the refusal is the HONEST one.
        (self.round / "h\u00e9r\u00f3.css").write_text(FAILING_CSS)
        self.page.write_text(PAGE.replace("shared.css", "h\u00e9r\u00f3.css"), encoding="utf-8")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertNotIn("does not serve it", out)
        self.assertIn("smallest text 9px", out)

    def test_a_link_whose_case_differs_from_the_file(self):
        # the pre-commit disk server found shared.css for /Shared.CSS through APFS; a static
        # host on Linux does not. Case is not folded: the refusal is the honest answer.
        self.css.write_text(FAILING_CSS)
        self.page.write_text(PAGE.replace("shared.css", "Shared.CSS"))
        self.refused_for("Shared.CSS")

    def test_what_a_browser_asks_for_unprompted_is_not_held_against_the_round(self):
        gate = load_real_gate()
        import urllib.error
        import urllib.request
        self.css.write_text(PASSING_CSS)
        missed = []
        with gate.served_round(self.round, None, missed) as base:
            for path in ("/favicon.ico", "/robots.txt", "/nope.css"):
                try:
                    urllib.request.urlopen(base + path, timeout=5)
                except urllib.error.HTTPError as e:
                    e.close()
        self.assertEqual(sorted(missed), ["favicon.ico", "nope.css", "robots.txt"])
        self.assertEqual([m for m in missed if m not in gate.BROWSER_ASKS_UNPROMPTED], ["nope.css"])
        rc, out = self.seal()                  # chromium asks for /favicon.ico on its own
        self.assertEqual(rc, 0, out)


class ChainRecordsAreComparedToo(Base):
    def test_a_chain_record_changed_under_a_running_seal_and_left_changed_is_refused(self):
        # directions.md on purpose: no chain check reads its wording, so only the compare can see it
        self.css.write_text(PASSING_CSS)
        why = []

        def during(proc):
            why.append(wait_for_the_server(proc))
            if why[0] == "listening":
                with (self.round / "directions.md").open("a") as f:
                    f.write("a line added while the seal ran, no new heading\n")
        rc, out = self.seal(during=during)
        self.assertEqual(why, ["listening"], out)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("directions.md", out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_wireframe_declaration_that_exists_only_during_the_seal_does_not_skip_the_gap_producer(self):
        self.css.write_text(PASSING_CSS)
        cfgp = self.round.parents[2] / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        cfgp.write_text(json.dumps(cfg))
        manifest = self.round / "craft-manifest.json"
        why = []

        def during(proc):
            why.append(wait_for_the_server(proc))
            if why[0] != "listening":
                return
            manifest.write_text(json.dumps({"tier": "wireframe", "reason": "only while seal looks"}))
            proc.wait()
            manifest.unlink()
        rc, out = self.seal(during=during)
        self.assertEqual(why, ["listening"], out)
        self.assertNotEqual(rc, 0, out)
        # the REASON: the compare also refuses (the manifest was still there at the end), so the
        # exit code alone cannot tell whether the gap producer was skipped
        self.assertIn("design-gap-check.py", out)
        self.assertFalse(manifest.exists())


class ASealThatIsKilled(Base):
    def test_sigterm_and_sighup_leave_no_snapshot_behind(self):
        import signal
        self.css.write_text(PASSING_CSS)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            before = {p.name for p in Path(tempfile.gettempdir()).glob("dc-seal-*")}
            why = []

            def during(proc):
                why.append(wait_for_the_server(proc))
                if why[0] == "listening":
                    proc.send_signal(sig)
            rc, out = self.seal(during=during)
            self.assertEqual(why, ["listening"], out)
            self.assertNotEqual(rc, 0, out)
            left = {p.name for p in Path(tempfile.gettempdir()).glob("dc-seal-*")} - before
            self.assertEqual(left, set(), f"{sig.name} left a copy of the round in the temp dir")
            self.assertFalse((self.round / "receipts.json").exists())


class TheWatcherCheckCanFail(Base):
    def test_a_run_that_never_sees_the_server_is_reported_as_such(self):
        # Sana: "with seal_is_listening stubbed to always return False, the test goes red."
        me = sys.modules[__name__]
        real = me.seal_is_listening
        me.seal_is_listening = lambda pid: False
        self.addCleanup(setattr, me, "seal_is_listening", real)
        self.css.write_text(PASSING_CSS)
        why = []
        self.seal(during=lambda proc: why.append(wait_for_the_server(proc)))
        self.assertEqual(why, ["exited"])


class CleanRefusals(Base):
    def run_seal(self, gate):
        import contextlib
        import io
        os.environ["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        self.addCleanup(os.environ.pop, "DESIGN_CHAIN_STATE", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = gate.seal(self.round)
        return rc, err.getvalue()

    def test_a_page_that_vanishes_before_the_snapshot_is_a_refusal_not_a_traceback(self):
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        real = gate.round_files

        def without_the_page(rd):
            files = real(rd)
            files.pop(self.page.name, None)
            return files
        gate.round_files = without_the_page
        rc, err = self.run_seal(gate)
        self.assertEqual(rc, 2)
        self.assertIn("vanished", err)

    def test_a_second_seal_of_the_same_round_in_one_process_is_refused(self):
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        with gate.snapshot_round(self.round):
            rc, err = self.run_seal(gate)
        self.assertEqual(rc, 2)
        self.assertIn("already running", err)

    def test_a_stale_verdict_does_not_stand_in_for_a_producer_that_wrote_nothing(self):
        # Mutant M-V. A STAND-IN producer (the second and last in this file): the real one
        # always writes an entry when it exits 0, so only a silent one reaches this.
        import hashlib
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        (self.round / "standard.json").write_text(json.dumps([{
            "page": self.page.name, "sha256": hashlib.sha256(self.page.read_bytes()).hexdigest(), "pass": True}]))
        gate.run_producer = lambda name, args, *rest: (0, "")     # timeout, stage (dc-05)
        rc, err = self.run_seal(gate)
        self.assertEqual(rc, 2)
        self.assertIn("no fresh verdict for this page", err)
        self.assertIsNone(self.verdict(), "the typed pass:true survived a seal that refused")

    def test_a_gap_receipt_this_run_did_not_write_is_removed_from_the_round(self):
        # Mutant M-S. Real producers: with no exemplar captures the real gap producer cannot
        # measure and writes nothing, so the stale receipt must go.
        self.css.write_text(PASSING_CSS)
        cfgp = self.round.parents[2] / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        cfgp.write_text(json.dumps(cfg))
        stale = self.round / "checks" / "gap.json"
        stale.write_text(json.dumps({"pages": {self.page.name: {"below_floor": []}}}))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertFalse(stale.exists(), "a gap receipt from an earlier run outlived a run that wrote none")


class NothingOutsideTheRoundIsServed(Base):
    def test_symlinks_out_loops_broken_links_and_encoded_slashes(self):
        import urllib.error
        import urllib.request
        gate = load_real_gate()
        self.css.write_text(PASSING_CSS)
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.css").write_text("secret")
        (self.round / "out.css").symlink_to(outside / "secret.css")
        (self.round / "outdir").symlink_to(outside)
        (self.round / "loop").symlink_to(self.round / "loop")
        (self.round / "broken.css").symlink_to(self.round / "nothing-here.css")
        files = gate.round_files(self.round)
        for rel in ("out.css", "outdir/secret.css", "loop", "broken.css"):
            self.assertNotIn(rel, files)
        with gate.served_round(self.round) as base:
            for path in ("/out.css", "/outdir/secret.css", "/loop", "/broken.css",
                         "/..%2f..%2fdesign-chain.json", "/%2e%2e/%2e%2e/design-chain.json"):
                with self.assertRaises(urllib.error.HTTPError, msg=path) as ctx:
                    urllib.request.urlopen(base + path, timeout=5)
                self.assertEqual(ctx.exception.code, 404, path)
                ctx.exception.close()


def load_real_gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dcg_1808", REAL_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    unittest.main()
