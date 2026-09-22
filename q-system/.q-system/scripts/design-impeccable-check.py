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
Exit 3 = at least one page raised an anti-pattern that STANDS. A finding stops counting only
         when this script refutes it by pixel measurement (low-contrast via analytic-gradient)
         or a canon entry answers it (CANON_RULES only); see the block above main().
It used to exit 0 whenever the control fired: `worst` was computed over the pages and never
used, so a flagged page sealed on a receipt that said so (dc-04). --url-base has no default: a
fixed port measured whatever round a leftover server was serving (dc-03 finding-4).
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
    """One detector call, from an EMPTY directory and with --no-config. The detector reads
    .impeccable/config.json (ignoreRules, ignoreValues, designSystem) from its cwd, so the
    caller's directory decided which rules ran: a config there switched gradient-text off and
    a slop page sealed (adversarial review of d0492b36, finding-3). Both halves, each pinned
    by its own test."""
    try:
        with tempfile.TemporaryDirectory(prefix="impeccable-cwd-") as empty:
            r = subprocess.run(["node", str(detector), target, "--no-config"], cwd=empty,
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
HTML_SUFFIXES = {".html", ".htm"}


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


# ---------------------------------------------------------------------------------------------
# THE ONLY TWO WAYS A FINDING STOPS COUNTING (round 2026-09-21, ASK-1743). Both are decided
# here, by this script, on every run. Neither reads anything the round's author writes, so
# neither is a place to type "accepted". The gate's history is a run of bypasses found in
# exactly that shape (a caller-dir config switched gradient-text off, "ran" in the receipt
# sealed), so the narrowness is in the code, not in a promise:
#
# 1. REFUTED BY MEASUREMENT. The browser engine scores text on a CSS gradient against the
#    gradient's worst STOP, wherever that stop sits. A panel that fades in from the page colour
#    and holds dark behind the words scored white-on-white, 1.0:1, on all six pages of round
#    2026-09-21, while a pixel read of the same render measured 4.71:1 and up. Only a finding
#    whose method is exactly `analytic-gradient` is re-measured. The re-measure renders the
#    page with its text made transparent and reads the pixels inside the element's box, at the
#    detector's viewport and both standard ones, and refutes only when the WORST pixel clears
#    the detector's own threshold at every viewport. It runs its own two-sided control first
#    (one text that must fail, one that must pass); a refuter that cannot tell them apart
#    makes the run exit 2, never 0.
#
# 2. DECIDED BY CANON. A rule that is a taste call, never a defect, can be answered by a
#    canon decision, through design-chain.json `impeccable.canon`. Only rules in CANON_RULES
#    qualify; each entry names the EXACT finding text (so a different single font still
#    flags), an owner file the config already lists (so the seal holds and binds it), and a
#    `decision`: LITERAL text that must appear on one line of that owner AND must itself read
#    as the decision (a dated AGREED/DECIDED or RULE-id marker, the rule's subject word, and
#    the very value the finding names). It was a caller-supplied regex until review of PR #403:
#    `^#` matched a heading in a file with no typeface decision and the finding sealed. The
#    text stops matching, the finding stands. Contrast, gradient text and the AI palette are
#    defects and can never be here.
# ---------------------------------------------------------------------------------------------
REFUTABLE_METHOD = "analytic-gradient"
# rule -> (the finding's fixed prefix, whose remainder is the VALUE the decision must name;
#          words one of which the decision must contain, so it is about this rule's subject)
CANON_RULES = {"single-font": ("only font used is ", ("typeface", "font"))}
DECISION_MARKER = re.compile(r"\b(?:AGREED|DECIDED) \d{4}-\d{2}-\d{2}\b|\bRULE-\d{4}-\d{2}-\d{2}-[A-Z]\b")
FINDING_LINE = re.compile(r"^\s*\[([a-z0-9-]+)\]\s+(.*\S)\s*$")
CONTRAST_DETAIL = re.compile(
    r'^browser contrast [\d.]+:1 median [\d.]+:1 \(need ([\d.]+):1\) via ([a-z, -]+?) "(.*)"$')
# the detector's default viewport (detect-url.mjs) plus the two the standard check renders at
REFUTE_VIEWPORTS = ((1280, 800), (1440, 900), (390, 844))

# Two texts on one gradient panel: the one at the light end MUST read as failing and the one
# at the dark end MUST read as passing. A refuter that passes everything, or fails everything,
# trips one of the two.
REFUTER_CONTROL_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>refuter control</title>
<style>body{margin:0;background:#fcfbf8;font:18px/1.4 sans-serif}
.p{position:relative;height:600px;margin:40px;
background:linear-gradient(to bottom,#1b3d66 0%,#1b3d66 45%,#fcfbf8 100%);background-color:#1b3d66}
.p span{position:absolute;left:24px;color:#ffffff}
.dark{top:40px}.light{bottom:12px}</style></head><body>
<div class="p"><span class="dark">refuter control reads on dark</span>
<span class="light">refuter control reads on light</span></div></body></html>
"""
REFUTER_CONTROL_PASS = "refuter control reads on dark"
REFUTER_CONTROL_FAIL = "refuter control reads on light"

_PROBE = r"""(want) => {
  const norm = s => s.trim().replace(/\s+/g, ' ').slice(0, 80);
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const direct = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent || '').join('');
    if (norm(direct) !== want) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    // a photo or icon inside the line is content, not what the words sit on (round 2026-09-21:
    // the author photo in the signature read as a 1.48:1 background); only REPLACED content is
    // skipped, a child's own background still counts
    const skip = [...el.querySelectorAll('img,svg,video,canvas,picture,iframe')].map(k => {
      const b = k.getBoundingClientRect();
      return [b.left + scrollX - 1, b.top + scrollY - 1, b.right + scrollX + 1, b.bottom + scrollY + 1]; });
    out.push({x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height,
              color: getComputedStyle(el).color, skip});
  }
  return out;
}"""
# text and anything painted in currentColor go transparent, so only what is BEHIND is read
_HIDE_TEXT = ("*{color:transparent!important;-webkit-text-fill-color:transparent!important;"
              "text-shadow:none!important;caret-color:transparent!important}")
_SETTLE = """() => Promise.race([
  Promise.all([document.fonts.ready, ...document.getAnimations().map(a => a.finished.catch(() => 0))]),
  new Promise(r => setTimeout(r, 5000))])"""


def _lum(rgb) -> float:
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def pixel_contrast(url: str, text: str) -> tuple[list[tuple[str, float, int]], str | None]:
    """The worst pixel contrast behind every element whose direct text is `text`, per viewport.
    Returns ([(viewport, worst ratio, elements measured)], None) or ([], why it could not)."""
    try:
        import io
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return [], f"the pixel re-measure needs playwright and Pillow ({e})"
    rows = []
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            try:
                for w, h in REFUTE_VIEWPORTS:
                    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
                    pg.goto(url, wait_until="load", timeout=30000)
                    pg.evaluate(_SETTLE)
                    boxes = pg.evaluate(_PROBE, text)
                    pg.add_style_tag(content=_HIDE_TEXT)
                    pg.wait_for_timeout(150)
                    shot = Image.open(io.BytesIO(pg.screenshot(full_page=True))).convert("RGB")
                    pg.close()
                    worst, n = None, 0
                    for bx in boxes:
                        m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", bx["color"])
                        if not m or (m.group(4) is not None and float(m.group(4)) < 0.99):
                            return [], f"text colour {bx['color']!r} is not opaque rgb; cannot re-measure"
                        fg = tuple(float(m.group(i)) for i in (1, 2, 3))
                        x0, y0 = int(bx["x"]) + 1, int(bx["y"]) + 1
                        x1 = min(shot.width, int(bx["x"] + bx["w"]) - 1)
                        y1 = min(shot.height, int(bx["y"] + bx["h"]) - 1)
                        inside = lambda x, y: any(k[0] <= x <= k[2] and k[1] <= y <= k[3] for k in bx["skip"])
                        px = [shot.getpixel((x, y)) for x in range(max(0, x0), x1, 2)
                              for y in range(max(0, y0), y1, 2) if not inside(x, y)]
                        if not px:
                            continue
                        n += 1
                        r = min(_ratio(fg, p) for p in px)
                        worst = r if worst is None else min(worst, r)
                    rows.append((f"{w}x{h}", worst if worst is not None else 0.0, n))
            finally:
                b.close()
    except Exception as e:                      # a browser that will not start is could-not-measure
        return [], f"the pixel re-measure crashed: {type(e).__name__}: {e}"
    return rows, None


def refuted(rows, need: float) -> bool:
    """Refuted only when EVERY viewport found the element and its worst pixel clears `need`."""
    return bool(rows) and all(n >= 1 and worst >= need for _, worst, n in rows)


def refuter_control() -> str | None:
    """None when the re-measure tells a failing text from a passing one, else why not."""
    with control_server(REFUTER_CONTROL_HTML) as url:
        ok_rows, why = pixel_contrast(url, REFUTER_CONTROL_PASS)
        if why:
            return why
        bad_rows, why = pixel_contrast(url, REFUTER_CONTROL_FAIL)
        if why:
            return why
    if not refuted(ok_rows, 4.5):
        return f"its control text on the dark end did not pass ({ok_rows})"
    if refuted(bad_rows, 4.5):
        return f"its control text on the light end did not fail ({bad_rows})"
    return None


def parse_findings(output: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in map(FINDING_LINE.match, output.splitlines()) if m]


def canon_entries(cfg_path: Path | None) -> tuple[list[dict], list[str], str | None]:
    """(honoured entries, entries NOT honoured with why, a config error that refuses the run).
    Owner files resolve against the config's directory, the same base the gate's owners use."""
    if cfg_path is None:
        return [], [], None
    try:
        cfg = json.loads(cfg_path.read_text())
    except (OSError, ValueError) as e:
        return [], [], f"cannot read --config {cfg_path}: {e}"
    block = cfg.get("impeccable")
    if block is None:
        return [], [], None
    entries = block.get("canon") if isinstance(block, dict) else None
    if not isinstance(entries, list):
        return [], [], "design-chain.json impeccable.canon must be a list"
    owners = {o.get("file") for o in cfg.get("owners", []) if isinstance(o, dict)}
    ok, not_ok = [], []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e[k].strip()
                                             for k in ("rule", "finding", "owner", "decision")):
            return [], [], f"impeccable.canon[{i}] needs rule, finding, owner and decision, each a string"
        if "anchor" in e:
            return [], [], (f"impeccable.canon[{i}] carries 'anchor'; a regex proved nothing (PR #403 "
                            f"review), so the entry names its canon line as literal 'decision' text")
        if e["rule"] not in CANON_RULES:
            return [], [], (f"impeccable.canon[{i}] names rule {e['rule']!r}; only {sorted(CANON_RULES)} "
                            f"are taste calls a canon decision can answer")
        if e["owner"] not in owners:
            return [], [], (f"impeccable.canon[{i}] owner {e['owner']!r} is not one of the config's "
                            f"owners, so the seal would not hold it")
        prefix, subject = CANON_RULES[e["rule"]]
        value = e["finding"][len(prefix):].strip().lower() if e["finding"].startswith(prefix) else ""
        dec = e["decision"].strip()
        low = dec.lower()
        why = ("its finding does not have the rule's shape" if not value else
               "its decision has no dated AGREED/DECIDED or RULE-id marker" if not DECISION_MARKER.search(dec) else
               f"its decision names none of {list(subject)}" if not any(w in low for w in subject) else
               f"its decision does not name {value!r}, the value the finding reports" if value not in low else None)
        if why:
            return [], [], f"impeccable.canon[{i}]: {why}"
        try:
            src = (cfg_path.parent / e["owner"]).read_text()
        except OSError as err:
            not_ok.append(f"canon[{i}] {e['rule']}: owner unreadable ({err})")
            continue
        line_no = next((n for n, ln in enumerate(src.splitlines(), 1) if dec in ln), None)
        if line_no is None:
            not_ok.append(f"canon[{i}] {e['rule']}: its decision text is no longer in {e['owner']}")
            continue
        ok.append({**e, "line": line_no, "quote": src.splitlines()[line_no - 1].strip()[:160]})
    return ok, not_ok, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round")
    ap.add_argument("--url-base", required=True,
                    help="the served round; no default, so a leftover server is never measured")
    ap.add_argument("--detector")
    ap.add_argument("--control")
    ap.add_argument("--page", action="append", default=[],
                    help="a page to scan, by name; seal passes every page it seals")
    ap.add_argument("--config", help="design-chain.json (the seal passes its HELD copy); read only for "
                                     "impeccable.canon")
    a = ap.parse_args()
    canon_ok, canon_not, canon_err = canon_entries(Path(a.config) if a.config else None)
    if canon_err:
        print(f"could not measure: {canon_err}", file=sys.stderr)
        return 2

    rd = Path(a.round).resolve()
    # The pages are the ones the CALLER seals, not a glob of our own: this scanned *.html and
    # seal seals .htm (and more), so a slop Offer.htm beside a clean Home sealed "pages flagged:
    # none" (adversarial review of d0492b36, finding-2). A page we cannot scan as HTML refuses,
    # and an HTML page in the round we were not handed refuses: never a silent skip.
    html = {p.name for p in rd.iterdir() if p.is_file() and p.suffix.lower() in HTML_SUFFIXES}
    names = a.page or sorted(html)
    cannot = [n for n in names if Path(n).suffix.lower() not in HTML_SUFFIXES]
    if cannot:
        print(f"could not measure: cannot scan {', '.join(cannot)} as HTML; the detector reads "
              f"rendered HTML only", file=sys.stderr)
        return 2
    unlisted = sorted(html - set(names))
    if unlisted:
        print(f"could not measure: {unlisted} are pages in the round this run was not given",
              file=sys.stderr)
        return 2
    pages = [rd / n for n in names]
    missing = [p.name for p in pages if not p.is_file()]
    if not pages or missing:
        print(f"no pages to scan in {rd}" + (f": {missing} do not exist" if missing else ""), file=sys.stderr)
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
    control = Path(a.control).expanduser().read_text() if a.control else CONTROL_HTML
    with control_server(control) as ctrl_target:
        crc, cout = run_detector(detector, ctrl_target)
        if "unavailable" in engine_of(cout, ctrl_target):
            with tempfile.TemporaryDirectory(prefix="impeccable-control-") as fb:
                fallback = Path(fb) / ".impeccable-control.html"
                fallback.write_text(control)
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
    flagged, broken, raised = [], [], []
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
            raised.append((p.name, url if browser_ok else None, out))
        elif rc != 0:
            broken.append(f"{p.name} (detector exit {rc})")
    w("")

    # --- what each raised finding comes to. A finding this cannot parse STANDS: fail closed.
    w("=== DISPOSITIONS (decided by this script; see REFUTABLE_METHOD and CANON_RULES) ===")
    for line in canon_not:
        w(f"canon entry NOT honoured, its findings stand: {line}")
    control_why = "not needed"
    n_refuted = n_canon = 0
    for name, url, out in raised:
        found = parse_findings(out)
        standing = [] if found else [("unparsed", "the detector exited 'found' and no finding line parsed")]
        for rule, detail in found:
            m = CONTRAST_DETAIL.match(detail) if rule == "low-contrast" else None
            if m and m.group(2) == REFUTABLE_METHOD and url:
                if control_why == "not needed":
                    control_why = refuter_control()
                    w(f"pixel re-measure control: {'FIRED both ways' if control_why is None else 'BROKEN: ' + control_why}")
                if control_why is not None:
                    print(f"could not measure: the pixel re-measure {control_why}", file=sys.stderr)
                    return 2
                need = float(m.group(1))
                rows, why = pixel_contrast(url, m.group(3))
                shown = ", ".join(f"{vp} {r:.2f}:1 over {n} element(s)" for vp, r, n in rows) or why
                if not why and refuted(rows, need):
                    n_refuted += 1
                    w(f"{name}: REFUTED [{rule}] \"{m.group(3)}\": worst pixel {shown} (need {need}:1)")
                    continue
                standing.append((rule, f"{detail} | pixel re-measure did not refute: {shown}"))
                continue
            hit = next((c for c in canon_ok if c["rule"] == rule and c["finding"] == detail), None)
            if hit:
                n_canon += 1
                w(f"{name}: CANON [{rule}] {detail}: {hit['owner']}:{hit['line']} \"{hit['quote']}\"")
                continue
            standing.append((rule, detail))
        for rule, detail in standing:
            w(f"{name}: STANDS [{rule}] {detail}")
        if standing:
            flagged.append(name)
    w(f"refuted by measurement: {n_refuted}; decided by canon: {n_canon}")
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
