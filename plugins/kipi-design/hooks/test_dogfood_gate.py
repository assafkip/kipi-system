#!/usr/bin/env python3
"""
test_dogfood_gate.py — deterministic reproducer for the fingerprint-driven gate.

Pairs with dogfood_gate.py. Proves the RCA fix: a warm-cream / serif / amber page
(NONE of the old garish tells) is now caught, the garish slop is still caught, and
a genuinely human-made page passes. Runs against BOTH the live fingerprint and the
embedded fallback so the gate is proven with and without the eyeball repo on disk.

Run: python3 plugins/kipi-design/hooks/test_dogfood_gate.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dogfood_gate import scan_html, load_fingerprint, EMBEDDED_FALLBACK  # noqa: E402

# the RCA case: tasteful slop. No Inter, no gradient text, no emoji, no "Powered by AI".
WARM_CREAM = """<!doctype html><html><head><style>
  body { font-family:'Instrument Serif', Georgia, serif; background:#faf6f0; color:#2b2622; }
  .accent { color:#f59e0b; }
  .btn { background:#f59e0b; color:#fff; border-radius:14px; }
</style></head><body>
  <h1>Transform your workflow, <span class="accent">effortlessly</span></h1>
  <p>Elevate your team with seamless tools.</p>
  <button class="btn">Get started</button>
</body></html>"""

GARISH = """<!doctype html><html><head><style>
  body { font-family:'Inter', sans-serif; }
  .grad { background:linear-gradient(90deg,#7c3aed,#2563eb); -webkit-background-clip:text; color:transparent; }
</style></head><body>
  <h1>\U0001f680 <span class="grad">Unlock the Future of Synergy</span></h1>
  <p>Seamlessly leverage cutting-edge, AI-powered solutions.</p>
  <button>Get Started</button>
</body></html>"""

# a genuinely human-made page: real foundry serif by name not in the list, ink-on-paper
# neutral palette, specific copy, a real action. Should produce ZERO findings.
CLEAN = """<!doctype html><html><head><style>
  body { font-family:'Canela', serif; background:#111111; color:#ededed; }
  .btn { background:#ededed; color:#111; }
</style></head><body>
  <h1>We score how AI-generated your homepage looks.</h1>
  <p>Paste a URL. We screenshot the first screen and tell you the three things to change.</p>
  <form><input name="url" /><button>Look at it</button></form>
</body></html>"""

# regression guard: a clean page that NAMES every tell inside a comment must still
# pass. The substring checks once flagged the comment text itself (the warm-cream
# fixture got a false "Powered by AI" finding from its own explanatory comment).
COMMENT_BAIT = """<!doctype html><html><head>
  <!-- deliberately avoids Inter, gradient text, emoji icons, warm cream, amber, and "Powered by AI" -->
  <style>body{font-family:'Canela',serif;background:#0e0e0e;color:#eee}</style></head>
  <body><h1>Three fixes for your homepage, in plain language.</h1>
  <form><input name="url"><button>Look</button></form></body></html>"""

failures = []
checks = 0


def ok(name, cond):
    global checks
    checks += 1
    if not cond:
        failures.append(name)


def labels(findings):
    return " ; ".join(f["label"] for f in findings)


def run(fp, tag):
    cream = scan_html(WARM_CREAM, fp)
    cl = labels(cream).lower()
    ok("[%s] warm-cream is caught at all" % tag, len(cream) > 0)
    ok("[%s] warm-cream: cream paper caught" % tag, "warm cream" in cl)
    ok("[%s] warm-cream: amber accent caught" % tag, "amber" in cl)
    ok("[%s] warm-cream: serif default caught" % tag, "instrument serif" in cl)
    ok("[%s] warm-cream: NOT via gradient/emoji/badge (proves it's the new detectors)" % tag,
       "gradient" not in cl and "emoji" not in cl and "powered by ai" not in cl)

    garish = scan_html(GARISH, fp)
    gl = labels(garish).lower()
    ok("[%s] garish still caught" % tag, len(garish) >= 3)
    ok("[%s] garish: inter font" % tag, "inter" in gl)
    ok("[%s] garish: gradient text" % tag, "gradient" in gl)
    ok("[%s] garish: emoji" % tag, "emoji" in gl)

    clean = scan_html(CLEAN, fp)
    ok("[%s] genuinely human page passes (0 findings)" % tag, len(clean) == 0)

    bait = scan_html(COMMENT_BAIT, fp)
    ok("[%s] naming tells in a comment does NOT flag (false-positive guard)" % tag, len(bait) == 0)


run(load_fingerprint(), "live")
run(EMBEDDED_FALLBACK, "fallback")

if failures:
    print("test_dogfood_gate FAILED:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("test_dogfood_gate: %d checks passed (live + fallback)" % checks)
