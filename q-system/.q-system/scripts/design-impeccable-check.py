#!/usr/bin/env python3
"""Run the impeccable anti-pattern detector over a design-chain round and write the
receipt the gate requires at `checks/impeccable.txt`.

WHY THIS IS A SCRIPT AND NOT A LINE IN A COMMAND DOC (founder's standing rule): a step
an agent is told to run is a step an agent forgets. `design-chain-gate.py` requires the
receipt file; this produces it, with the two things that make the receipt mean anything.

1. A KNOWN-SLOP CONTROL runs in the same invocation. Measured 2026-09-15: the first
   control chosen for this round sat under a `/output/` path, which the kipi-design
   tripwire treats as internal, so it returned exit 0 and a SKIP read as a PASS
   (ASK-1746). A clean report whose control never fired is decoration.
2. THE DETECTOR'S OWN BLIND SPOT IS PRINTED, not swallowed. impeccable has two engines:
   static HTML parsing, and a real browser via URL that resolves computed styles. The
   browser engine needs puppeteer, which was installed nowhere in this fleet until
   2026-09-15 -- so every impeccable claim made here before that date, including
   `site-design.md` section 8's, was static-mode only. Worse, the detector exits 0 when
   puppeteer is missing, so that gap is invisible to any caller reading exit codes. This
   script asks for URL mode first and records in the receipt exactly which engine
   actually ran, so the same gap cannot reopen silently if the dependency goes away.

   The control goes through that SAME engine. Running it statically while the pages get
   the browser proves only the static parser and leaves the browser's zeros unproven.
   Measured the hour puppeteer landed: through the browser the control raised
   `ai-color-palette`, which the static parse had missed on the identical file.

WHAT THIS DOES NOT DO: certify a page. impeccable is a defect-ABSENCE detector, the same
class as the tripwire and the standard check. Zero findings means "no known anti-pattern
was detected", never "this is good" -- see
q-system/lessons/a-defect-absence-gate-is-a-floor-not-a-finish-line.md. The craft
manifest is the half that asks whether the work was actually done.

Usage:
  design-impeccable-check.py <round-dir> [--url-base http://127.0.0.1:8793]
                                        [--detector <path to detect-antipatterns.mjs>]
                                        [--control <path to a known-slop html>]
Exit 0 = receipt written, the control fired, and every page is clean.
Exit 1 = the control did not fire, so the page results are unproven.
Exit 2 = could not run: no detector, no node, a detector that crashed on a page, or a served
         page whose bytes are not the local file.
Exit 3 = at least one page raised an anti-pattern.
It used to exit 0 whenever the control fired: `worst` was computed over the pages and never
used, so a flagged page sealed on a receipt that said so (dc-04). --url-base has no default: a
fixed port measured whatever round a leftover server was serving (dc-03 finding-4).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import contextlib
import hashlib
import http.server
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

DETECTOR_CANDIDATES = (
    "~/projects/cole-gtm/.agents/skills/impeccable/scripts/detector/detect-antipatterns.mjs",
)
# A page that must trip the detector. Kept here rather than in a fixture file so the
# control cannot drift away from the thing it controls for.
CONTROL_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Control</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap">
<style>body{font-family:Inter,sans-serif;background:#0b0b17;color:#fff}
h1{background:linear-gradient(90deg,#7c3aed,#4f46e5);-webkit-background-clip:text;
-webkit-text-fill-color:transparent;font-size:64px}</style></head><body>
<h1>Unlock the power of AI for your business</h1>
<p>Transform your workflow with our cutting-edge, next-generation platform.</p>
</body></html>
"""


def find_detector(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    for c in DETECTOR_CANDIDATES:
        p = Path(c).expanduser()
        if p.is_file():
            return p
    return None


def run_detector(detector: Path, target: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["node", str(detector), target],
                           capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return 2, "node is not on PATH"
    except subprocess.TimeoutExpired:
        return 2, f"timed out after 300s on {target}"
    return r.returncode, (r.stdout + r.stderr).strip()


# The detector's own contract (cli/main.mjs): exit 2 when it found anything, 0 when it found
# nothing. Anything else is a crash. The control used to be read off the TEXT ("anti-patterns
# found" and not " 0 anti-patterns"), which read "0 anti-patterns found." at the start of the
# output as a control that fired (dc-04 test, red on the old script).
DETECTOR_FOUND = 2


@contextlib.contextmanager
def control_server(html: str):
    """The negative control on a loopback port of its own, so it goes through the same URL
    engine as the pages without being written into the round: under seal the round is served
    from memory, and a control written beside the pages would be a 404 there (dc-04)."""
    d = Path(tempfile.mkdtemp(prefix="impeccable-control-"))
    (d / ".impeccable-control.html").write_text(html)
    handler = lambda *a, **k: _Quiet(*a, directory=str(d), **k)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/.impeccable-control.html"
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(d, ignore_errors=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def served_bytes_differ(url: str, local: Path) -> str | None:
    """None when the URL serves exactly the local file's bytes, else why not. A verdict about
    a page the browser was not given is not a verdict about that page (the dc-03 rule)."""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            got = r.read()
    except OSError as e:
        return f"could not fetch {url}: {e}"
    if hashlib.sha256(got).digest() != hashlib.sha256(local.read_bytes()).digest():
        return f"served bytes differ from {local.name} at {url}"
    return None


def engine_of(output: str, target: str) -> str:
    """Which engine actually ran. The detector does not say, and it exits 0 when the
    browser engine is unavailable, so this is read off the error text rather than
    assumed."""
    if "puppeteer is required" in output:
        return "NONE (browser engine unavailable: puppeteer not installed)"
    return "browser (URL, computed styles resolved)" if target.startswith("http") else "static HTML parse"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round")
    ap.add_argument("--url-base", required=True,
                    help="the served round; no default, so a leftover server is never measured")
    ap.add_argument("--detector")
    ap.add_argument("--control")
    a = ap.parse_args()

    rd = Path(a.round).resolve()
    pages = sorted(p for p in rd.glob("*.html"))
    if not pages:
        print(f"no .html pages in {rd}", file=sys.stderr)
        return 2
    detector = find_detector(a.detector)
    if not detector:
        print("impeccable detector not found; pass --detector <path to "
              "detect-antipatterns.mjs>", file=sys.stderr)
        return 2

    lines: list[str] = []
    w = lines.append
    w("impeccable anti-pattern detector over this design-chain round.")
    w(f"detector: {detector}")
    w("This is a defect-ABSENCE check. Zero findings means no known anti-pattern was")
    w("detected. It never means the page is good; see the craft manifest for the half")
    w("that asks whether the work was actually done.")
    w("")

    # --- the control, first, so a dead detector cannot look like a clean report
    w("=== NEGATIVE CONTROL (a deliberately slop page; these results are only worth")
    w("    reading because this one trips) ===")
    # The control must go through the SAME engine as the pages. Running it statically
    # while the pages get the browser engine proves the static parser works and leaves
    # the browser engine's zeros unproven -- a control that cannot fail for the engine
    # you care about is decoration (2026-09-15, caught the first time puppeteer was
    # present). URL first, falling back only if the browser engine is unavailable.
    html = Path(a.control).expanduser().read_text() if a.control else CONTROL_HTML
    with control_server(html) as ctrl_target:
        crc, cout = run_detector(detector, ctrl_target)
        if "unavailable" in engine_of(cout, ctrl_target):
            fallback = Path(tempfile.mkdtemp(prefix="impeccable-control-")) / ".impeccable-control.html"
            fallback.write_text(html)
            crc, cout = run_detector(detector, str(fallback))
            ctrl_target = str(fallback)
    ctrl_fired = crc == DETECTOR_FOUND
    w(f"control: {ctrl_target}")
    w(f"engine: {engine_of(cout, ctrl_target)}")
    for ln in cout.splitlines():
        w("    " + ln)
    w(f"control fired: {'YES' if ctrl_fired else 'NO -- treat every page result below as UNPROVEN'}")
    w("")

    # --- the pages, browser engine asked for first
    w("=== THE PAGES ===")
    browser_ok = None
    flagged, broken = [], []
    for p in pages:
        url = f"{a.url_base.rstrip('/')}/{p.name}"
        why = served_bytes_differ(url, p)
        if why:
            print(f"could not measure: {why}", file=sys.stderr)
            return 2
        rc, out = run_detector(detector, url)
        eng = engine_of(out, url)
        if browser_ok is None:
            browser_ok = "unavailable" not in eng
        if not browser_ok:
            rc, out = run_detector(detector, str(p))
            eng = engine_of(out, str(p))
        w(f"--- {p.name}")
        w(f"    engine: {eng}")
        for ln in (out or "(no output)").splitlines():
            w("    " + ln)
        if rc == DETECTOR_FOUND:
            flagged.append(p.name)
        elif rc != 0:
            broken.append(f"{p.name} (detector exit {rc})")
    w("")

    w("=== WHAT THIS RUN COULD NOT SEE ===")
    if browser_ok:
        w("Nothing known: the browser engine ran, so computed styles were resolved.")
    else:
        w("The browser engine did NOT run: puppeteer is not installed, and the detector")
        w("exits 0 in that state rather than failing, so a caller reading exit codes")
        w("would not know. Everything above is a STATIC parse. It cannot see computed")
        w("colour (so no WCAG contrast from resolved values), anything a stylesheet or")
        w("script applies at runtime, or the type-hierarchy ratio as rendered. To close")
        w("it: npm install puppeteer beside the detector. Founder decision, because it")
        w("pulls a Chromium download.")
    w("")
    w(f"pages flagged: {flagged or 'none'}")
    w(f"control fired: {'YES' if ctrl_fired else 'NO'}")

    out_path = rd / "checks" / "impeccable.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}")
    print(f"control fired: {ctrl_fired}; browser engine: {bool(browser_ok)}; flagged: {flagged}")
    if broken:
        print(f"could not measure: the detector crashed on {broken}", file=sys.stderr)
        return 2
    if not ctrl_fired:
        return 1
    return 3 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
