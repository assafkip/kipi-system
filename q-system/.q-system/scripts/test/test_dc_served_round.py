#!/usr/bin/env python3
"""dc-03: `seal` owns the served round, and producers prove they measured the local bytes.

Before this, every producer needed the round served over http and nothing owned the server.
The only serve step was a backgrounded, never-killed http.server on a typed port in the
command doc. A leftover server from an earlier round kept the port, the new bind failed
silently, and design-standard-check.py measured the OLD round over the URL while writing the
sha of the NEW local file: a green verdict bound to bytes nothing measured (PRD finding-3).

Also here, placed in dc-03 by Sana's dispositions of dc-02's review (2026-09-18):
  - design-gap-check.py exits 3 for could-not-measure and keeps 2 for below-the-floor
  - the producer child runs with -s, so a usercustomize.py cannot alter a verdict
  - seal removes the page's prior verdict before the run, so freshness is not an mtime guess

Temp directories only. Stand-ins are selected by running a COPY of the gate beside them.
"""
import ast
import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REAL_GATE = SCRIPTS / "design-chain-gate.py"
REAL_STANDARD = SCRIPTS / "design-standard-check.py"
REAL_GAP = SCRIPTS / "design-gap-check.py"
STUBS = Path(__file__).resolve().parent / "stub_producers"
OWNER = "> **A business where somebody is paid to be accurate, and being wrong costs money"
PAGE = "<html><body><h1>You work more hours than you bill.</h1><a href='#'>Book</a></body></html>"


def clean(extra=None):
    e = {k: v for k, v in os.environ.items() if k not in ("DESIGN_CHAIN_ALLOW", "CLAUDE_PROJECT_DIR")}
    e.update(extra or {})
    return e


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc03-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shutil.copy(REAL_GATE, self.bin / REAL_GATE.name)
        for stub in STUBS.glob("*.py"):
            shutil.copy(stub, self.bin / stub.name)
        self.gate = self.bin / REAL_GATE.name
        self.inst = self.tmp / "instance"
        (self.inst / "canonical").mkdir(parents=True)
        (self.inst / "canonical" / "the-business.md").write_text("# B\n\n" + OWNER + "\n")
        self.cfg = {"owners": [{"file": "canonical/the-business.md",
                                "anchors": ["^> \\*\\*A business where somebody is paid"]}]}
        self.round = self.inst / "site" / "design" / "r1"
        self.round.mkdir(parents=True)
        self.page = self.round / "Pair-laptop.html"
        self.page.write_text(PAGE)
        self.write_cfg()
        rd = self.round
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

    def write_cfg(self):
        (self.inst / "design-chain.json").write_text(json.dumps(self.cfg))

    def seal(self, **env):
        r = subprocess.run([sys.executable, str(self.gate), "seal", str(self.round)], capture_output=True,
                           text=True, env=clean(dict(env, DESIGN_CHAIN_STATE=str(self.tmp / "state"))))
        return r.returncode, r.stdout + r.stderr

    def standard_entry(self):
        return json.loads((self.round / "standard.json").read_text())[0]


class SealServesTheRound(Base):
    def test_the_producer_is_handed_a_loopback_url_that_serves_the_local_bytes(self):
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        url = self.standard_entry()["_fetched_url"]
        # the stand-in fetched this URL and compared its sha to the local file before passing
        self.assertRegex(url or "", r"^http://127\.0\.0\.1:\d+/Pair-laptop\.html$")

    def test_the_server_is_gone_after_a_seal_that_passed(self):
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assert_port_closed(self.standard_entry()["_fetched_url"])

    def test_the_server_is_gone_after_a_seal_that_refused(self):
        rc, out = self.seal(STUB_STANDARD="fail")
        self.assertEqual(rc, 2, out)
        self.assert_port_closed(self.standard_entry()["_fetched_url"])

    def assert_port_closed(self, url):
        port = int(re.search(r":(\d+)/", url).group(1))
        with socket.socket() as s:
            s.settimeout(2)
            self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0, f"a server is still listening on {port}")

    def test_a_page_name_with_a_space_is_served_and_measured(self):
        spaced = self.round / "Clock laptop.html"
        spaced.write_text(PAGE.replace("bill", "count"))
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_the_gap_producer_gets_the_same_served_round(self):
        self.cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        self.write_cfg()
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        gap = json.loads((self.round / "checks" / "gap.json").read_text())
        self.assertRegex(gap["_url_base"], r"^http://127\.0\.0\.1:\d+$")

    def test_no_typed_port_remains_in_the_gate_or_the_producers(self):
        # A REVIEW AID. The first version regexed for a host:port STRING or the literal 8793
        # after stripping '#' comments by hand (which also truncated "#0066b3"). The bind is
        # a TUPLE, ("127.0.0.1", 0), and the reviewer changed the 0 to 8080 with this test
        # green. So it reads the AST: no (host, nonzero int) tuple, no host:digits in any
        # string constant, and an f-string may carry "127.0.0.1:" only inside served_round().
        hosts = {"127.0.0.1", "localhost", "0.0.0.0", ""}
        for f in (REAL_GATE, REAL_STANDARD, REAL_GAP):
            tree = ast.parse(f.read_text())
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                          and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            allowed_fstrings = set()
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and fn.name == "served_round":
                    allowed_fstrings = {id(n) for n in ast.walk(fn) if isinstance(n, ast.JoinedStr)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Tuple) and len(n.elts) == 2:
                    h, p = n.elts
                    if (isinstance(h, ast.Constant) and h.value in hosts
                            and isinstance(p, ast.Constant) and isinstance(p.value, int)):
                        self.assertEqual(p.value, 0, f"{f.name}:{n.lineno} binds a typed port {p.value}")
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                    self.assertNotRegex(n.value, r"(127\.0\.0\.1|localhost):\d{2,5}", f"{f.name}:{n.lineno} types a port")
                if isinstance(n, ast.JoinedStr) and id(n) not in allowed_fstrings:
                    text = "".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
                    self.assertNotRegex(text, r"(127\.0\.0\.1|localhost):$", f"{f.name}:{n.lineno} builds a host:port outside served_round()")


class ServerLifetime(unittest.TestCase):
    """In-process, because the CLI exits right after a seal and takes any daemon thread with it:
    a test that only looks after the process is gone cannot see a server that was never stopped
    (mutant S4 survived the first version)."""

    def test_the_port_is_closed_when_the_context_exits_and_the_process_is_still_alive(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dcg", REAL_GATE)
        dcg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dcg)
        tmp = Path(tempfile.mkdtemp(prefix="dc03-srv-"))
        try:
            (tmp / "a.html").write_text(PAGE)
            with dcg.served_round(tmp) as base:
                port = int(base.rsplit(":", 1)[1])
                with socket.socket() as s:
                    self.assertEqual(s.connect_ex(("127.0.0.1", port)), 0, "not serving inside the context")
            with socket.socket() as s:
                s.settimeout(2)
                self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0, "still listening after the context exited")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_port_is_closed_when_the_body_raises(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dcg2", REAL_GATE)
        dcg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dcg)
        tmp = Path(tempfile.mkdtemp(prefix="dc03-srv-"))
        port = None
        try:
            with self.assertRaises(RuntimeError):
                with dcg.served_round(tmp) as base:
                    port = int(base.rsplit(":", 1)[1])
                    raise RuntimeError("a producer blew up mid-seal")
            with socket.socket() as s:
                s.settimeout(2)
                self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PriorVerdictIsRemoved(Base):
    def test_a_typed_pass_is_gone_after_a_silent_producer(self):
        sha = hashlib.sha256(self.page.read_bytes()).hexdigest()
        (self.round / "standard.json").write_text(json.dumps([{"page": self.page.name, "sha256": sha, "pass": True}]))
        rc, out = self.seal(STUB_STANDARD="silent")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        left = json.loads((self.round / "standard.json").read_text()) if (self.round / "standard.json").is_file() else []
        self.assertEqual([e for e in left if e.get("page") == self.page.name], [],
                         "the verdict typed by hand survived a run that produced nothing")

    def test_another_pages_verdict_is_left_alone(self):
        other = {"page": "Elsewhere.html", "sha256": "x", "pass": True}
        (self.round / "standard.json").write_text(json.dumps([other]))
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertIn(other, json.loads((self.round / "standard.json").read_text()))

    def test_a_typed_gap_is_gone_after_a_silent_gap_producer(self):
        self.cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        self.write_cfg()
        sha = hashlib.sha256(self.page.read_bytes()).hexdigest()
        (self.round / "checks" / "gap.json").write_text(json.dumps({"pages": {self.page.name: {"sha256": sha, "below_floor": []}}}))
        rc, out = self.seal(STUB_GAP="silent")
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.round / "checks" / "gap.json").exists())


class GapExitCodes(Base):
    def setUp(self):
        super().setUp()
        self.cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        self.write_cfg()

    def test_exit_2_is_labelled_below_the_floor_and_only_that(self):
        rc, out = self.seal(STUB_GAP="below")
        self.assertEqual(rc, 2, out)
        self.assertIn("below the exemplar floor", out)
        self.assertNotIn("could not measure", out)

    def test_exit_3_is_labelled_could_not_measure_and_only_that(self):
        rc, out = self.seal(STUB_GAP="cannot")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        self.assertNotIn("below the exemplar floor", out)

    def test_the_REAL_gap_producer_exits_3_with_no_exemplar_captures(self):
        # The round is really SERVED here. The first version pointed at a dead port, so the
        # served-bytes check answered first and --refs was never read: right code, wrong branch.
        with _Serve(self.round) as base:
            r = subprocess.run([sys.executable, str(REAL_GAP), str(self.round), "--url-base", base,
                                "--refs", str(self.tmp / "no-refs")], capture_output=True, text=True, env=clean())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("usable exemplar capture", r.stdout + r.stderr)

    def test_a_usage_error_is_could_not_measure_not_below_the_floor(self):
        # argparse exits 2 by default, and 2 now means "below the exemplar floor"
        for argv in (["--nope"], [], [str(self.round), "--url-base"]):
            r = subprocess.run([sys.executable, str(REAL_GAP), *argv], capture_output=True, text=True, env=clean())
            self.assertEqual(r.returncode, 3, f"{argv}: {r.stdout + r.stderr}")

    def test_the_REAL_gap_producer_exits_3_with_no_url_base(self):
        r = subprocess.run([sys.executable, str(REAL_GAP), str(self.round)], capture_output=True, text=True, env=clean())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)


class _Serve:
    """The round, really served, for tests that must get PAST the served-bytes check."""

    def __init__(self, directory, after_get=None):
        self.directory, self.after_get = str(directory), after_get

    def __enter__(self):
        outer = self

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=outer.directory, **k)

            def do_GET(self):
                super().do_GET()
                if outer.after_get:
                    outer.after_get(self.path)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


class _Decoy:
    """A server handing out DIFFERENT bytes under the same page name: the leftover round."""

    def __enter__(self):
        body = b"<html><body><h1>The OLD round</h1></body></html>"

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()


class RealProducersRefuseADecoy(Base):
    """The check comes before any browser, so these run without playwright."""

    def test_the_REAL_standard_producer_refuses_bytes_it_was_not_handed(self):
        with _Decoy() as base:
            r = subprocess.run([sys.executable, str(REAL_STANDARD), str(self.page), "--url", f"{base}/{self.page.name}"],
                               capture_output=True, text=True, env=clean())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("served bytes differ", r.stdout + r.stderr)
        self.assertFalse((self.round / "standard.json").exists(), "a verdict was written for bytes nothing measured")

    def test_the_REAL_gap_producer_refuses_a_decoy(self):
        refs = self.tmp / "refs"
        refs.mkdir()
        with _Decoy() as base:
            r = subprocess.run([sys.executable, str(REAL_GAP), str(self.round), "--url-base", base, "--refs", str(refs),
                                "--write"], capture_output=True, text=True, env=clean())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        # the MESSAGE, not only the code: an empty refs dir also exits 3, and the first version
        # of this test passed on that while the served-bytes check was switched off (mutant S9)
        self.assertIn("served bytes differ", r.stdout + r.stderr)
        self.assertFalse((self.round / "checks" / "gap.json").exists())


def _load_gate(name):
    spec = importlib.util.spec_from_file_location(name, REAL_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OneReadOfTheBytes(Base):
    """Adversarial review of 4998d7b7, reproduced with real chromium: the producer hashed the
    page AFTER measuring it, so a file swapped while the browser was mid-measure came back
    PASS, signed with the sha of bytes nothing had measured."""

    def test_the_REAL_producer_refuses_a_page_that_changed_while_it_was_measured(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the measure-then-hash window was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        gets = []

        def swap_on_the_browsers_get(path):
            gets.append(path)
            if len(gets) == 2:          # 1st GET is the producer's own byte check, 2nd is the browser
                self.page.write_text("<html><body>" + "<p style='font-size:9px'>slop</p>" * 40 + "</body></html>")
        with _Serve(self.round, after_get=swap_on_the_browsers_get) as base:
            r = subprocess.run([sys.executable, str(REAL_STANDARD), str(self.page), "--url", f"{base}/{self.page.name}"],
                               capture_output=True, text=True, env=clean())
        self.assertGreaterEqual(len(gets), 2, "the browser never fetched the page, so the window was not exercised")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("changed while it was being measured", r.stdout + r.stderr)
        self.assertFalse((self.round / "standard.json").exists(), "a verdict was signed over bytes nothing measured")

    def test_seal_rechecks_the_bytes_immediately_before_it_writes_the_receipt(self):
        dcg = _load_gate("dcg_recheck")
        dcg.producer_problems = lambda rd, pages, cfg: []

        def chain_then_swap(page, honor_seal=True):
            page.write_text(PAGE.replace("bill", "invoice"))     # the window after the last check
            return []
        dcg.chain_problems = chain_then_swap
        rc = dcg.seal(self.round)
        self.assertEqual(rc, 2)
        self.assertFalse((self.round / "receipts.json").exists())


class AssetDigest(Base):
    """Adversarial review of 4998d7b7: the byte proof covered the HTML only. Measure with one
    shared.css, swap it, and every sha still matched while an honest re-measure FAILED. Sana:
    seal computes ONE digest over every file in the round except the chain's own records and
    writes it into the receipt; dc-10 makes the passive gate recompute it."""

    def setUp(self):
        super().setUp()
        (self.round / "shared.css").write_text("p{font-size:18px}")

    def test_the_receipt_records_a_digest_that_moves_when_an_asset_changes(self):
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        recorded = json.loads((self.round / "receipts.json").read_text())["__assets__"]["sha256"]
        dcg = _load_gate("dcg_digest")
        self.assertEqual(recorded, dcg.round_asset_digest(self.round))
        (self.round / "shared.css").write_text("p{font-size:9px}")
        self.assertNotEqual(recorded, dcg.round_asset_digest(self.round))

    def test_the_chains_own_records_do_not_move_the_digest(self):
        # By NAME, at the round's top level and in checks/ and gate/, only the files the chain
        # itself writes. Nothing is skipped because of the directory it sits in.
        dcg = _load_gate("dcg_digest2")
        before = dcg.round_asset_digest(self.round)
        (self.round / "critique.md").write_text("rewritten" + chr(10))
        (self.round / "standard.json").write_text("[]")
        (self.round / "checks" / "gap.json").write_text("{}")
        (self.round / "checks" / "impeccable.txt").write_text("x")
        (self.round / "gate" / "reader-runs.jsonl").write_text("{}")
        self.assertEqual(before, dcg.round_asset_digest(self.round))

    def test_an_asset_parked_in_gate_or_checks_moves_the_digest(self):
        # Final review of c3607e0d, reproduced with the real gate: the server serves gate/ and
        # checks/, the page loaded gate/style.css, and the digest skipped the whole directory,
        # so the stylesheet could be swapped AFTER the seal with every sha still matching.
        dcg = _load_gate("dcg_digest5")
        for rel in ("gate/style.css", "checks/app.js", "notes.md", "gate/readme.md"):
            before = dcg.round_asset_digest(self.round)
            (self.round / rel).write_text("/* anything a page can load */")
            self.assertNotEqual(before, dcg.round_asset_digest(self.round), f"{rel} is served and not digested")

    def test_an_unreadable_file_in_the_round_is_a_refusal_not_a_traceback(self):
        logo = self.round / "logo.png"
        logo.write_bytes(b"png")
        logo.chmod(0)
        try:
            rc, out = self.seal()
        finally:
            logo.chmod(0o644)
        self.assertEqual(rc, 2, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("could not measure", out)

    def test_an_asset_swapped_after_measuring_and_before_the_receipt_is_refused(self):
        dcg = _load_gate("dcg_digest3")

        def measured_then_swapped(rd, pages, cfg):
            (rd / "shared.css").write_text("p{font-size:9px}")
            return []
        dcg.producer_problems = measured_then_swapped
        dcg.chain_problems = lambda page, honor_seal=True: []
        self.assertEqual(dcg.seal(self.round), 2)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_renamed_asset_moves_the_digest(self):
        dcg = _load_gate("dcg_digest4")
        before = dcg.round_asset_digest(self.round)
        (self.round / "shared.css").rename(self.round / "other.css")
        self.assertNotEqual(before, dcg.round_asset_digest(self.round))


class SealRefusesCleanly(Base):
    def test_a_bind_failure_is_could_not_measure_not_a_traceback(self):
        dcg = _load_gate("dcg_bind")

        def refuse(*a, **k):
            raise OSError("Address family not supported")
        dcg.http.server.ThreadingHTTPServer = refuse
        try:
            bad = dcg.producer_problems(self.round, [self.page], {})
        finally:
            importlib.reload(http.server)
        self.assertTrue(bad)
        self.assertIn("could not measure", bad[0][1][0])

    def test_an_unwritable_standard_json_is_a_refusal_not_a_traceback(self):
        std = self.round / "standard.json"
        std.write_text(json.dumps([{"page": self.page.name, "sha256": "x", "pass": True}]))
        std.chmod(0o444)
        try:
            rc, out = self.seal()
        finally:
            std.chmod(0o644)
        self.assertEqual(rc, 2, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("could not measure", out)


class ServerServesOnlyTheRound(unittest.TestCase):
    def test_no_directory_listing_and_nothing_outside_the_round(self):
        import urllib.error
        import urllib.request
        dcg = _load_gate("dcg_scope")
        tmp = Path(tempfile.mkdtemp(prefix="dc03-scope-"))
        try:
            rd = tmp / "round"
            rd.mkdir()
            (rd / "a.html").write_text(PAGE)
            (rd / "sub").mkdir()
            (tmp / "secret.txt").write_text("outside the round")
            (rd / "out").symlink_to(tmp)
            with dcg.served_round(rd) as base:
                self.assertEqual(urllib.request.urlopen(f"{base}/a.html", timeout=5).status, 200)
                for path in ("/", "/sub/", "/out/secret.txt"):
                    with self.assertRaises(urllib.error.HTTPError, msg=path) as ctx:
                        urllib.request.urlopen(base + path, timeout=5)
                    self.assertEqual(ctx.exception.code, 404, path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ChildIgnoresTheUserSite(Base):
    def test_a_usercustomize_cannot_alter_a_verdict(self):
        # -E ignores PYTHONUSERBASE but leaves the DEFAULT user site on, and usercustomize.py
        # there is imported at interpreter startup (measured by Sana, 2026-09-18). This plants
        # one that writes a passing verdict and exits 0 before the producer can judge.
        home = self.tmp / "home"
        home.mkdir()
        probe = subprocess.run([sys.executable, "-E", "-c", "import site; print(site.getusersitepackages())"],
                               capture_output=True, text=True, env=clean({"HOME": str(home)}))
        usersite = Path(probe.stdout.strip())
        self.assertTrue(str(usersite).startswith(str(home)), f"cannot plant a user site under a temp HOME: {usersite}")
        usersite.mkdir(parents=True)
        (usersite / "usercustomize.py").write_text(
            "import hashlib, json, os, sys\n"
            "from pathlib import Path\n"
            "if sys.argv and sys.argv[0].endswith('design-standard-check.py'):\n"
            "    p = Path(sys.argv[1])\n"
            "    (p.parent / 'standard.json').write_text(json.dumps([{'page': p.name, 'pass': True,\n"
            "        'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), '_hijacked': True}]))\n"
            "    os._exit(0)\n")
        rc, out = self.seal(STUB_STANDARD="fail", HOME=str(home))
        self.assertEqual(rc, 2, out)
        self.assertIn("FAILS the standard", out, "a usercustomize.py in the user site decided the verdict")
        self.assertNotIn("_hijacked", (self.round / "standard.json").read_text())

    def test_a_missing_module_names_the_flags_that_hide_it(self):
        rc, out = self.seal(STUB_STANDARD="nomodule")
        self.assertEqual(rc, 2, out)
        # NOT assertIn("-s"): that is a substring of "design-standard-check.py", which every
        # refusal names, so the first version stayed green with the whole hint deleted.
        self.assertIn("pip install --user", out)
        self.assertIn("-E -s", out)


if __name__ == "__main__":
    unittest.main()
