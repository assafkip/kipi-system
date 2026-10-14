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
from dogfood_gate import (  # noqa: E402
    scan_html, load_fingerprint, EMBEDDED_FALLBACK, is_public_facing_page,
)

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

# finding #2 reproducer: an overflowing rgb()/hsl() value must NOT crash scan_html.
# An unguarded crash exits 1, which the PostToolUse contract treats as a no-op, so the
# page would ship UNGATED (fail-open — the dogfood scar). It must coerce, not raise.
OVERFLOW_RGB = ('<!doctype html><html><head><style>h1{color:rgb(' + ("9" * 400) + ',0,0)}'
                '</style></head><body><h1>hi</h1><form><input><button>go</button></form></body></html>')
OVERFLOW_HSL = ('<!doctype html><html><head><style>body{background:hsl(40,' + ("9" * 200) + '%,'
                + ("9" * 200) + '%)}</style></head><body><h1>hi</h1><form><input><button>go</button></form></body></html>')
for label, page in (("rgb", OVERFLOW_RGB), ("hsl", OVERFLOW_HSL)):
    try:
        result = scan_html(page, load_fingerprint())
        ok("[guard] overflowing %s color does not crash scan_html (no fail-open)" % label, isinstance(result, list))
    except Exception:
        ok("[guard] overflowing %s color does not crash scan_html (no fail-open)" % label, False)

# ── ASK-134: the public-vs-internal path classifier is the DETERMINISTIC half of
# .claude/rules/design-auto-invoke.md ("will someone other than the founder see this?").
# It used to live inline in main() where nothing could test it, so the rule claimed
# ENFORCED while naming no executable. These cases are that rule's reproducer: an
# internal path must be SKIPPED (no design skill, no scan) and a public one SCANNED.
INTERNAL_PATHS = [
    "/repo/q-system/output/daily-schedule-2026-07-31.html",
    "/repo/q-system/marketing/templates/post.html",
    "/repo/sites/eyeball/tests/fixture-page.html",
    "/repo/node_modules/pkg/demo.html",
    "/repo/sites/_harvest/sample.html",
    "/repo/build/index.html",
    "/repo/dist/index.html",
    "/repo/sites/eyeball/debug.html",
    "/repo/q-system/output/morning-log-view.html",
]
PUBLIC_PATHS = [
    "/repo/sites/eyeball/index.html",
    "/repo/sites/index.html",
    "/repo/sites/prd-os/landing.html",
]
NON_HTML = [
    "/repo/sites/eyeball/style.css",
    "/repo/sites/eyeball/app.tsx",
    "/repo/README.md",
    "",
]

for p in INTERNAL_PATHS:
    ok("[scope] internal path is NOT public-facing: %s" % p, is_public_facing_page(p) is False)
for p in PUBLIC_PATHS:
    ok("[scope] public page IS public-facing: %s" % p, is_public_facing_page(p) is True)
for p in NON_HTML:
    ok("[scope] non-.html is out of this gate's scope: %r" % p, is_public_facing_page(p) is False)
# case-insensitive, same as the original main() which lowercased before matching
ok("[scope] uppercase internal path still skipped",
   is_public_facing_page("/repo/Q-System/Output/Schedule.HTML") is False)
ok("[scope] uppercase public page still scanned",
   is_public_facing_page("/repo/sites/eyeball/INDEX.HTML") is True)

# ── ASK-134 regression, Codex major on PR #49: the classifier called the founder-only
# GTM cockpit PUBLIC, so every unattended edit by the com.cole.cockpit job fired a
# blocking false positive. A gate whose first act is refusing legitimate work gets
# switched off, which is the worst direction for this one to fail in.
#
# These are the REAL registered paths, read off disk from the cockpit that
# instance-registry.json points at -- NOT a path shaped to match the fix. A fixture I
# invent tests my assumption; the producer's own path tests the system. The cockpit is
# founder-only by its own bypass check (gtm/cockpit/checks/verify_auth_required.py
# FAILS on an unauthenticated 200), so "internal" here is the cockpit's claim, not mine.
COCKPIT_REAL_PATHS = [
    "/Users/assafkipnis/projects/cole-gtm/gtm/cockpit/index.html",
    "/Users/assafkipnis/projects/cole-gtm/gtm/cockpit/content.html",
]
for p in COCKPIT_REAL_PATHS:
    ok("[scope] registered founder-only GTM cockpit is NOT public-facing: %s" % p,
       is_public_facing_page(p) is False)

# Negative self-test for the fixture above. Without it the two cases could pass because
# some UNRELATED marker happens to match the path, and the assertion would survive the
# "/cockpit/" marker being deleted -- a test that cannot fail. Drop that one marker and
# the real paths must flip back to PUBLIC, which is the exact defect Codex reported.
import dogfood_gate as _dg  # noqa: E402
_saved_markers = _dg.INTERNAL_PATH_MARKERS
try:
    _dg.INTERNAL_PATH_MARKERS = tuple(m for m in _saved_markers if m != "/cockpit/")
    ok("[scope][mutation] removing the /cockpit/ marker makes the real cockpit paths "
       "PUBLIC again, so the cases above are driven by that marker and can fail",
       all(_dg.is_public_facing_page(p) is True for p in COCKPIT_REAL_PATHS))
finally:
    _dg.INTERNAL_PATH_MARKERS = _saved_markers
ok("[scope][mutation] marker tuple restored after the mutation",
   _dg.INTERNAL_PATH_MARKERS is _saved_markers and "/cockpit/" in _dg.INTERNAL_PATH_MARKERS)

# ── ASK-1906: "report"/"reports" was missing from INTERNAL_PATH_MARKERS, so a
# founder-only report page not already caught by some OTHER marker classified
# PUBLIC and ran the AI-slop block.
#
# The four real paths named in the issue (two under q-consult/output/, one
# under q-system/output/, one under a fourth fleet instance's output/ -- see
# REPORT_PATHS_REAL below for why that instance's real name is genericized
# here) all already sit under an "/output/" directory, and "/output/" was
# already a marker before this fix --
# measured directly: is_public_facing_page() on the real absolute paths already
# returned False pre-fix. So testing those four AS-IS would pass whether or not
# "report" is a marker, and would prove nothing about this fix (the exact "a
# bound can fake your filter" trap). The isolated paths below strip every OTHER
# marker (no /output/, no "dashboard", and no "/q-system/" -- the third real path
# lives under q-system/, which is ITSELF an existing marker, so a naive copy of
# it here would ride "/q-system/" and prove nothing either) so the assertion is
# driven by "report" alone.
REPORT_PATHS_ISOLATED = [
    "/repo/q-consult/ai-builder-reports/dubsado-reliability-recon.html",
    "/repo/q-consult/pipeline-reports/summary.html",
    "/repo/consulting-instance/architecture-report/index.html",
]
for p in REPORT_PATHS_ISOLATED:
    ok("[scope] report page with no other marker present is NOT public-facing: %s" % p,
       is_public_facing_page(p) is False)

# The four real directories named in ASK-1906. The 4th real instance name is a
# client identifier this public repo's client-name-guard blocks from ever being
# committed, so it is genericized here to "q-instance" -- the segment shape
# (output/report-status-dashboard/) is what the case tests, not the fleet
# instance's name. Kept as a named regression guard, not as evidence for the
# "report" marker itself -- see the comment above.
REPORT_PATHS_REAL = [
    "/repo/q-consult/output/ai-builder-reports/dubsado-reliability-recon.html",
    "/repo/q-consult/output/pipeline-reports/summary.html",
    "/repo/q-system/output/architecture-report/index.html",
    "/repo/q-instance/output/report-status-dashboard/index.html",
]
for p in REPORT_PATHS_REAL:
    ok("[scope] real ASK-1906 report path is NOT public-facing: %s" % p,
       is_public_facing_page(p) is False)

# Negative self-test, same shape as the /cockpit/ mutation above: without "report" in
# the markers, the ISOLATED paths (no other marker riding along) must flip PUBLIC.
_saved_markers2 = _dg.INTERNAL_PATH_MARKERS
try:
    _dg.INTERNAL_PATH_MARKERS = tuple(m for m in _saved_markers2 if m != "report")
    ok("[scope][mutation] removing the report marker makes the isolated report paths "
       "PUBLIC again, so the cases above are driven by that marker and can fail",
       all(_dg.is_public_facing_page(p) is True for p in REPORT_PATHS_ISOLATED))
finally:
    _dg.INTERNAL_PATH_MARKERS = _saved_markers2
ok("[scope][mutation] marker tuple restored after the report mutation",
   _dg.INTERNAL_PATH_MARKERS is _saved_markers2 and "report" in _dg.INTERNAL_PATH_MARKERS)

# Acceptance criterion 2: a genuine public page is unaffected by the new marker.
ok("[scope] normal public page is still public-facing after the report marker: "
   "site/pricing/index.html",
   is_public_facing_page("/repo/site/pricing/index.html") is True)

if failures:
    print("test_dogfood_gate FAILED:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
# ── ASK-511: two false positives that blocked five legitimate site edits ──
#
# The gate exit-2'd every edit to askconsulting.io on 2026-08-08. A gate that
# refuses correct work is a gate that gets switched off, so these are its own
# regression tests. Both pages below are DELIBERATELY good.

ANCHOR_CTA = """<!doctype html><html><head><style>
  body { font-family:'Newsreader', Georgia, serif; background:#0b0f14; color:#e8e6e1; }
  .btn { background:#d4a017; color:#0b0f14; }
</style></head><body>
  <h1>The parts of your business that still run on somebody remembering.</h1>
  <p>12 years at LinkedIn, Meta, Google and ElevenLabs.</p>
  <a class="btn" href="/start">Book the assessment</a>
</body></html>"""

for _fp, _tag in ((load_fingerprint(), "live"), (EMBEDDED_FALLBACK, "fallback")):
    _f = labels(scan_html(ANCHOR_CTA, _fp))
    ok("anchor-styled CTA counts as a primary action (%s)" % _tag,
       "No form/input/button" not in _f)
    # The page's only warm near-white is its TEXT colour on a near-black ground.
    # A cream BACKGROUND is the tell; cream text on black is the opposite of one.
    ok("warm text on a dark ground is not a cream background (%s)" % _tag,
       "cream" not in _f.lower())

print("test_dogfood_gate: ASK-511 regressions checked")

if failures:
    print("test_dogfood_gate: %d of %d checks FAILED" % (len(failures), checks))
    for f in failures:
        print("  FAIL  %s" % f)
    raise SystemExit(1)

print("test_dogfood_gate: %d checks passed (live + fallback)" % checks)
