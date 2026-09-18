#!/usr/bin/env python3
"""design-standard-check: measure a rendered page against the POSITIVE standard the
design canon records, and write standard.json for the design chain.

WHY: site-design.md section 6 holds the standard as prose (three type sizes and two
large elements in a view, 45 to 90 characters a line, body 15 to 25 px, one signal
moment). Round 2 of the first screens (2026-09-15) passed every negative check
(tripwire, bio_gate, fit) and broke most of section 6; the founder called it "a block
of words". A standard that lives only in prose is one the builder skims. This turns
the numbers into a measurement the chain cannot proceed without.

Reads the numbers from design-chain.json ("standard"), never from this file, so the
canon owns them. Requires playwright (python) and a served or file URL.

Usage: design-standard-check.py <page.html> [--url URL] [--config design-chain.json]
Writes/updates standard.json next to the page (one entry per page, keyed by name).
exit 0 = pass, 1 = fail (the chain treats fail as open), 2 = could not measure.
"""
from __future__ import annotations

import argparse
import hashlib
import urllib.request
import json
import sys
from pathlib import Path

DEFAULTS = {
    "max_type_sizes": 3, "max_large_elements": 2, "large_px": 40,
    "max_words": 80, "min_body_px": 15, "max_line_chars": 90,
    "signal": "#0066b3", "max_signal_elements": 2,
    "viewports": [[1440, 900], [390, 844]],
}

JS = """
(sig) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const sizes = new Map(); let large = 0, words = 0, minBody = 999, maxLine = 0, sigCount = 0;
  const hex = (c) => { const m = c.match(/\\d+/g); if (!m) return c; return '#' + m.slice(0,3).map(n => (+n).toString(16).padStart(2,'0')).join(''); };
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.bottom <= 0 || r.top >= vh || r.width === 0) continue;
    // Screen-reader-only text is not visible text. The standard visually-hidden pattern
    // is a 1px box with clip, and counting it charged a page 60 words for an accessible
    // description of its diagram (round 2026-09-16c read 143 words for about 80 visible).
    // Penalising accessibility is the one thing a word budget must never do.
    if (r.width <= 1 || r.height <= 1) continue;
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
    if (!own) continue;
    const cs = getComputedStyle(el);
    const fs = Math.round(parseFloat(cs.fontSize));
    sizes.set(fs, (sizes.get(fs) || 0) + 1);
    if (fs >= LARGE) large += 1;
    if (fs < 24) minBody = Math.min(minBody, fs);
    const w = own.split(/\\s+/).filter(Boolean).length; words += w;
    const charsPerLine = r.width / (fs * 0.5);
    if (w > 8) maxLine = Math.max(maxLine, Math.round(Math.min(charsPerLine, own.length)));
    if (hex(cs.color) === sig.toLowerCase()) sigCount += 1;
  }
  // The headline: the first h1 in view (else the largest text in view). Where its words sit
  // is what a reader sees as the page's alignment, so measure the TEXT, not the h1 box:
  // a Range around the h1's contents gives the ink's extent inside a full-width block.
  let hero = null, heroEl = null;
  for (const h of document.querySelectorAll('h1')) {
    const r = h.getBoundingClientRect();
    if (r.bottom > 0 && r.top < vh && r.width > 1) { heroEl = h; break; }
  }
  if (!heroEl) {
    let best = 0;
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.bottom <= 0 || r.top >= vh || r.width <= 1) continue;
      const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (own && fs > best) { best = fs; heroEl = el; }
    }
  }
  if (heroEl) {
    const rg = document.createRange(); rg.selectNodeContents(heroEl);
    const t = rg.getBoundingClientRect();
    hero = { text_align: getComputedStyle(heroEl).textAlign,
             offset_pct: Math.round(Math.abs((t.left + t.right) / 2 - vw / 2) / vw * 1000) / 10,
             pieces: 0, words: 0, lines: 0 };
    // The text a reader sees as one block with the headline: every other piece of 3 or more
    // words from 80px above it to 260px below it, outside fixed or sticky layers and outside
    // header, nav, footer and controls. Lines are rendered height over line height.
    const hr = heroEl.getBoundingClientRect();
    const layered = (e) => { for (let x = e; x && x.nodeType === 1; x = x.parentElement) {
        const c = getComputedStyle(x);
        if (c.position === 'fixed' || c.position === 'sticky') return true;
        // FIGURE: a drawing's own labels are part of the picture, not prose stacked under the
        // headline. The honest boundary: prose wrapped in a figure to dodge this is not caught.
        if (/^(HEADER|NAV|FOOTER|BUTTON|A|DIALOG|FIGURE)$/.test(x.tagName) || x.getAttribute('role') === 'dialog') return true;
      } return false; };
    for (const el of document.body.querySelectorAll('*')) {
      if (heroEl.contains(el) || el.contains(heroEl)) continue;
      const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
      const w = own.split(/\\s+/).filter(Boolean).length;
      if (w < 3) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1 || r.top < hr.top - 80 || r.top > hr.bottom + 260) continue;
      if (layered(el)) continue;
      const c = getComputedStyle(el);
      if (c.visibility === 'hidden' || +c.opacity === 0) continue;
      let lh = parseFloat(c.lineHeight); if (!lh) lh = parseFloat(c.fontSize) * 1.2;
      hero.pieces += 1; hero.words += w; hero.lines += Math.max(1, Math.round(r.height / lh));
    }
  }
  return { type_sizes: [...sizes.keys()].sort((a,b)=>a-b), large_elements: large, words, min_body_px: minBody === 999 ? null : minBody, max_line_chars: maxLine, signal_elements: sigCount, hero };
}
"""


def measure(url: str, cfg: dict) -> list[dict]:
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h in cfg["viewports"]:
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(url, wait_until="networkidle")
            pg.wait_for_timeout(300)
            m = pg.evaluate(JS.replace("LARGE", str(cfg["large_px"])), cfg["signal"])
            m["viewport"] = f"{w}x{h}"
            pg.close()
            out.append(m)
        b.close()
    return out


def judge(m: dict, cfg: dict) -> list[str]:
    f = []
    # the number of DISTINCT sizes; the two allowed large elements may add sizes of their own
    small = [s for s in m["type_sizes"] if s < cfg["large_px"]]
    if len(small) > cfg["max_type_sizes"]:
        f.append(f"{len(small)} text sizes under {cfg['large_px']}px ({small}); max {cfg['max_type_sizes']}")
    if m["large_elements"] > cfg["max_large_elements"]:
        f.append(f"{m['large_elements']} large elements; max {cfg['max_large_elements']}")
    if m["words"] > cfg["max_words"]:
        f.append(f"{m['words']} words in view; max {cfg['max_words']}")
    if m["min_body_px"] is not None and m["min_body_px"] < cfg["min_body_px"]:
        f.append(f"smallest text {m['min_body_px']}px; min {cfg['min_body_px']}")
    if m["max_line_chars"] > cfg["max_line_chars"]:
        f.append(f"longest line about {m['max_line_chars']} chars; max {cfg['max_line_chars']}")
    if m["signal_elements"] > cfg["max_signal_elements"]:
        f.append(f"signal colour on {m['signal_elements']} elements; max {cfg['max_signal_elements']}")
    # Hero alignment, when the canon asks for one. Founder, 2026-09-15: left-aligned
    # everything reads as slop. That note lived only in a critique and the headline was
    # back on the left a day later (round 2026-09-16d: "the text is again on lined on the
    # left"). Two conditions, because either alone is fooled: text-align:center inside a
    # left-hand column is still a left-hand headline, and a centred box can hold
    # left-aligned lines.
    want = cfg.get("hero_align")
    if want == "center":
        h = m.get("hero")
        tol = cfg.get("hero_center_tolerance_pct", 5)
        if not h:
            f.append("no headline in view to check alignment against; hero_align is center")
        elif h["text_align"] not in ("center", "-webkit-center") or h["offset_pct"] > tol:
            f.append(f"headline is not centred (text-align {h['text_align']}, its text sits "
                     f"{h['offset_pct']}% of the viewport off centre; max {tol}%); "
                     f"hero_align is center")
    # The block around the headline. Founder 2026-09-16: "the text kind of bunches up in the
    # middle, wrapped, and it looks like a block of text. It's not about the length, it's
    # about what it looks like." Measured on the five exemplars the same day
    # (site/design/2026-09-16g/checks/hero-text-laptop.txt): the most any of them puts
    # around the headline is calendly's 2 pieces, 18 words, 3 lines; round 16e had 4, 43, 6.
    # Words alone would miss it (he said it is not the length), so pieces and wrapped lines
    # are held too.
    h = m.get("hero") or {}
    caps = [("pieces", "max_hero_pieces", "separate pieces of text"),
            ("words", "max_hero_words", "words"), ("lines", "max_hero_lines", "wrapped lines")]
    over = [f"{h.get(k, 0)} {label} (max {cfg[c]})" for k, c, label in caps
            if c in cfg and h and h.get(k, 0) > cfg[c]]
    if over:
        f.append("the text around the headline reads as a block: " + ", ".join(over))
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("--url")
    ap.add_argument("--config")
    a = ap.parse_args()
    page = Path(a.page).resolve()
    cfg = dict(DEFAULTS)
    cpath = Path(a.config) if a.config else None
    if not cpath:
        for d in [page.parent] + list(page.parents):
            if (d / "design-chain.json").is_file():
                cpath = d / "design-chain.json"
                break
    if cpath and cpath.is_file():
        cfg.update(json.loads(cpath.read_text()).get("standard", {}))
    url = a.url or page.as_uri()
    # ONE read of the bytes, BEFORE the browser, and its sha is the only one the entry may
    # carry. This used to hash page.read_bytes() AFTER measure(): a file swapped while the
    # browser was mid-measure came back PASS, signed with the sha of bytes nothing had measured
    # (adversarial review of 4998d7b7, reproduced with real chromium).
    measured_sha = hashlib.sha256(page.read_bytes()).hexdigest()
    if a.url:
        # dc-03: prove the bytes about to be measured are the bytes about to be hashed. A stale
        # server on the same port served the OLD round while this wrote the NEW file's sha.
        try:
            served = hashlib.sha256(urllib.request.urlopen(a.url, timeout=20).read()).hexdigest()
        except OSError as e:
            print(f"could not measure: {a.url} is not being served: {e}", file=sys.stderr)
            return 2
        if served != measured_sha:
            print(f"could not measure: served bytes differ from {page.name}. {a.url} is handing out "
                  f"another page, so a verdict here would be about the wrong bytes.", file=sys.stderr)
            return 2
    try:
        ms = measure(url, cfg)
    except Exception as e:  # playwright missing, page unreachable
        print(f"could not measure: {e}", file=sys.stderr)
        return 2
    if hashlib.sha256(page.read_bytes()).hexdigest() != measured_sha:
        print(f"could not measure: {page.name} changed while it was being measured, so no verdict "
              f"can be signed for either version. Measure again.", file=sys.stderr)
        return 2
    fails = {m["viewport"]: judge(m, cfg) for m in ms}
    ok = not any(fails.values())
    entry = {"page": page.name, "sha256": measured_sha,
             "pass": ok, "measurements": ms, "failures": fails, "config": cfg}
    std_path = page.parent / "standard.json"
    entries = []
    if std_path.is_file():
        try:
            prev = json.loads(std_path.read_text())
            entries = prev if isinstance(prev, list) else [prev]
        except ValueError:
            entries = []
    entries = [e for e in entries if e.get("page") != page.name] + [entry]
    std_path.write_text(json.dumps(entries, indent=2) + "\n")
    print(f"{page.name}: {'PASS' if ok else 'FAIL'}")
    for vp, fl in fails.items():
        for x in fl:
            print(f"  {vp}: {x}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
