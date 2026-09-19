#!/usr/bin/env python3
"""ASK-1836 (dc-06b): the reader gate serves the round itself, so what readers see is the bytes hashed.

WHY. design-reader-gate.py fetched the page once with urllib to check its bytes, then Chromium
fetched it again for the screenshot. A server the builder controlled returned the GOOD page to
urllib and a red one to Chromium: rc 0, html_sha256 == GOOD, a red screenshot (adversarial review
of c911e33f, finding-1). Subresources were never hashed and --url-base could be any host. Now the
script reads the round into memory once and serves only those bytes on a loopback port the OS
picks, and every row records exactly which files the browser was given.

The REAL script at its tracked path, real playwright, injected runner (no model call).
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "design-reader-gate.py"
GREEN_PAGE = ("<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
              "</head><body><h1>Two records that should agree</h1><p>Retyping costs hours.</p></body></html>")
GREEN_CSS = "html,body{background:#00ff00;margin:0;min-height:100vh}"
RED_CSS = "html,body{background:#ff0000;margin:0;min-height:100vh}"
ANSWERS = {str(i): a for i, a in enumerate(
    ["yes", "fixes", "fewer errors", "example", "a week", "ops", "STAY", "nothing", "unknown"], 1)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Held(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc06b-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "Home-laptop.html").write_text(GREEN_PAGE)
        (self.rd / "shared.css").write_text(GREEN_CSS)
        (self.inst / "persona.md").write_text("You run a small tax practice.\n")
        (self.inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc06b", "owners": [], "readers": {"persona_file": "persona.md", "n": 1}}))
        self.answers = self.tmp / "answers.json"
        self.answers.write_text(json.dumps(ANSWERS))
        self.keep = self.tmp / "screens"

    def args(self, *extra):
        return [str(self.rd), "--config", str(self.inst / "design-chain.json"), "--runner", "injected",
                "--answers", str(self.answers), "--keep-screens", str(self.keep), *extra]

    def run_in_process(self, mod, *extra):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = mod.main(self.args(*extra))
            except SystemExit as e:
                rc = e.code
        return rc, err.getvalue()

    def rows(self):
        return [json.loads(l) for l in (self.rd / "gate" / "reader-runs.jsonl").read_text().splitlines()]

    def pixel(self):
        from PIL import Image
        png = next(self.keep.glob("*.png"))
        return Image.open(png).convert("RGB").getpixel((5, 5))


class ServesItself(Held):
    def test_a_stylesheet_changed_on_disk_after_the_read_changes_nothing_readers_see(self):
        mod = load_script("drg_a")
        real_shoot = mod.shoot

        def swap_then_shoot(*a, **k):
            (self.rd / "shared.css").write_text(RED_CSS)     # after the round was read
            return real_shoot(*a, **k)
        mod.shoot = swap_then_shoot
        rc, err = self.run_in_process(mod)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.pixel()[:3], (0, 255, 0), "readers were shown the stylesheet on disk, not the one read")
        r = self.rows()[0]
        self.assertEqual(r["served"]["shared.css"], sha(GREEN_CSS.encode()))

    def test_rows_name_every_file_the_browser_was_given_and_their_digest(self):
        rc, err = self.run_in_process(load_script("drg_b"))
        self.assertEqual(rc, 0, err)
        r = self.rows()[0]
        self.assertEqual(r["served"], {"Home-laptop.html": sha(GREEN_PAGE.encode()),
                                       "shared.css": sha(GREEN_CSS.encode())})
        self.assertEqual(r["round_digest"], sha(json.dumps(r["served"], sort_keys=True).encode()))
        self.assertEqual(r["html_sha256"], sha(GREEN_PAGE.encode()))

    def test_a_page_asking_for_a_file_the_round_lacks_refuses(self):
        (self.rd / "Home-laptop.html").write_text(GREEN_PAGE.replace("shared.css", "missing.css"))
        rc, err = self.run_in_process(load_script("drg_c"))
        self.assertEqual(rc, 2, err)
        self.assertIn("missing.css", err)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_there_is_no_url_to_point_it_at(self):
        # the user-agent-switching server needed a URL; the option is gone
        rc, err = self.run_in_process(load_script("drg_d"), "--url-base", "http://127.0.0.1:1")
        self.assertEqual(rc, 2, err)
        self.assertIn("unrecognized arguments: --url-base", err)

    def test_a_symlink_out_of_the_round_is_not_served(self):
        outside = self.tmp / "secret.css"
        outside.write_text(RED_CSS)
        (self.rd / "shared.css").unlink()
        (self.rd / "shared.css").symlink_to(outside)
        rc, err = self.run_in_process(load_script("drg_e"))
        self.assertEqual(rc, 2, err)
        self.assertIn("shared.css", err)


class WhatTheBrowserWasGivenPerRender(Held):
    """Standard review of c38d2bf9: images were served as application/octet-stream, which chromium
    will not render; and `served` was recorded per page, so a row named files only the other
    viewport fetched."""

    def png(self, rgb):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), rgb).save(buf, format="PNG")
        return buf.getvalue()

    def test_an_image_in_the_round_is_rendered(self):
        (self.rd / "dot.png").write_bytes(self.png((0, 255, 0)))
        (self.rd / "Home-laptop.html").write_text(
            "<!doctype html><html><body style='margin:0'><img src='dot.png' "
            "style='width:100vw;height:100vh;display:block'></body></html>")
        rc, err = self.run_in_process(load_script("drg_g"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.pixel()[:3], (0, 255, 0), "the round's image did not render")

    def test_each_row_names_only_what_its_own_viewport_fetched(self):
        (self.rd / "wide.png").write_bytes(self.png((0, 0, 255)))
        (self.rd / "narrow.png").write_bytes(self.png((255, 0, 255)))
        (self.rd / "Home-laptop.html").write_text(
            "<!doctype html><html><head><style>body{margin:0;height:100vh;background:url(wide.png)}"
            "@media (max-width:600px){body{background:url(narrow.png)}}</style></head><body></body></html>")
        cfg = json.loads((self.inst / "design-chain.json").read_text())
        cfg["readers"]["viewports"] = [[1440, 900], [390, 844]]
        (self.inst / "design-chain.json").write_text(json.dumps(cfg))
        rc, err = self.run_in_process(load_script("drg_h"))
        self.assertEqual(rc, 0, err)
        by_vp = {tuple(r["viewport"]): r for r in self.rows()}
        self.assertIn("wide.png", by_vp[(1440, 900)]["served"])
        self.assertNotIn("narrow.png", by_vp[(1440, 900)]["served"])
        self.assertIn("narrow.png", by_vp[(390, 844)]["served"])
        self.assertNotIn("wide.png", by_vp[(390, 844)]["served"])
        self.assertNotEqual(by_vp[(1440, 900)]["round_digest"], by_vp[(390, 844)]["round_digest"])


class NothingOutsideTheRoundReachesTheScreenshot(Held):
    """Adversarial review of c38d2bf9: Chromium had no request routing, so an iframe, an @import or a
    late stylesheet from another origin rendered in the screenshot without reaching the held server;
    the row's served map and round_digest described a page the readers did not see."""

    def foreign(self):
        import http.server
        import threading

        class Red(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = (b"html,body{background:#ff0000}" if self.path.endswith(".css")
                        else b"<html><body style='background:#ff0000;margin:0;height:100vh'></body></html>")
                self.send_response(200)
                self.send_header("Content-Type", "text/css" if self.path.endswith(".css") else "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Red)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def refused_with(self, page_html):
        host = self.foreign()
        (self.rd / "Home-laptop.html").write_text(page_html.replace("HOST", host))
        rc, err = self.run_in_process(load_script("drg_f"))
        self.assertEqual(rc, 2, err)
        self.assertIn("outside the round", err)
        self.assertIn(host.split("//", 1)[1], err)       # host:port, whatever the scheme (http or ws)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_an_iframe_to_another_origin_refuses(self):
        self.refused_with("<!doctype html><html><body style='margin:0'>"
                          "<iframe src='HOST/x' style='border:0;width:100vw;height:100vh'></iframe></body></html>")

    def test_an_import_from_another_origin_refuses(self):
        self.refused_with("<!doctype html><html><head><style>@import url(HOST/late.css);</style></head>"
                          "<body><h1>Two records</h1></body></html>")

    def test_a_websocket_to_another_origin_refuses(self):
        # page.route does not see WebSockets; they are routed on their own (Sana)
        self.refused_with("<!doctype html><html><head><script>new WebSocket('HOST'.replace('http','ws')"
                          "+'/live')</script></head><body><h1>Two records</h1></body></html>")

    def test_a_stylesheet_added_late_from_another_origin_refuses(self):
        self.refused_with("<!doctype html><html><head><script>setTimeout(function(){var l=document."
                          "createElement('link');l.rel='stylesheet';l.href='HOST/late2.css';document.head."
                          "appendChild(l)},100)</script></head><body><h1>Two records</h1></body></html>")


if __name__ == "__main__":
    unittest.main()
