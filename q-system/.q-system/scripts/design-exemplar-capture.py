#!/usr/bin/env python3
"""Capture and MEASURE exemplar pages the founder names, so a design round is grounded in
real pages instead of the builder's prior.

WHY (founder, 2026-09-15): after two rounds he rejected as generic, "I want a part of the
process is for you to take the websites that I give you as exemplars, but also beyond what
you're currently extracting, create a design narrative of what are the style elements that
define this group? What is what are the similarities with regards to the design elements
and usage of the tools in the design. And you should do that every time I put in more
exemplars."

So this is a script and not a habit. It captures every exemplar in `exemplars.json`, writes
one measurement record per site, and rewrites `MEASUREMENTS.md`. The NARRATIVE is the human
half and lives in `NARRATIVE.md`; `design-chain-gate.py` requires every captured exemplar
to appear there, so adding a site and not re-reading the group is a blocked state rather
than a forgotten one.

What it measures, above the fold at two viewports: type families and the full size ramp,
weights, the display line's size and measure, every background and text colour, accents,
gradient use, radii, shadows, the space scale, imagery by kind (img / svg / video / canvas
/ background-image), motion, the content measure, and the button and nav shapes. These are
the axes a group's shared DNA actually shows up on.

Usage:
  design-exemplar-capture.py <references-dir> [--add URL ...] [--only URL] [--no-shot]

`exemplars.json` in that directory is the roster and is append-only through --add, so a
site the founder named once is never silently dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

VIEWPORTS = [("laptop", 1440, 900), ("phone", 390, 844)]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PROBE = r"""
() => {
  const vh = innerHeight, vw = innerWidth;
  const inFold = e => { const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.top < vh && r.bottom > 0; };
  // querySelectorAll does NOT pierce shadow roots, so a site that renders its hero inside
  // a web component is invisible to the probe. Measured 2026-09-15: figma.com reported 0
  // images and 0% visual area in the fold while its own screenshot shows three large
  // artwork panels. The page carries 87 <img> elements and 11 shadow hosts; every one of
  // those images sits inside a shadow root. The probe was not describing figma, it was
  // describing its own blindness, and a floor derived from that number would have been
  // derived from a measurement error.
  const deepAll = (root, out) => {
    for (const e of root.querySelectorAll('*')) {
      out.push(e);
      if (e.shadowRoot) deepAll(e.shadowRoot, out);
    }
    return out;
  };
  const all = deepAll(document.body, []);
  const fold = all.filter(inFold);

  const fam = new Map(), sizes = new Map(), weights = new Map();
  const textColors = new Map(), bgColors = new Map();
  const radii = new Map(), shadows = [], gradients = [];
  let display = null;

  const own = e => [...e.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent).join(' ').trim();

  for (const e of fold) {
    const c = getComputedStyle(e), t = own(e);
    if (t) {
      const f = c.fontFamily.split(',')[0].replace(/["']/g, '').trim();
      const s = Math.round(parseFloat(c.fontSize));
      fam.set(f, (fam.get(f) || 0) + 1);
      sizes.set(s, (sizes.get(s) || 0) + 1);
      weights.set(c.fontWeight, (weights.get(c.fontWeight) || 0) + 1);
      textColors.set(c.color, (textColors.get(c.color) || 0) + 1);
      const r = e.getBoundingClientRect();
      if (!display || s > display.px) {
        // the whole visible line, not this element's own text nodes: a headline with a
        // tone-shifted span or an inline highlight pill splits into several nodes, and a
        // reader sees one sentence. Measured 2026-09-16: a five-word display line read as
        // two because the span carried the rest.
        // The display LINE is the run of text set at the display size, which is neither
        // this element's own text nodes (a tone-shifted span splits the line: a five-word
        // headline read as two) nor the whole heading element (stripe's h1 carries its
        // subhead: six words read as twenty-two). Collect every text node inside the host
        // whose computed size matches, and nothing smaller.
        const host = e.closest('h1,h2,h3,[role=heading]') || e;
        let whole = '';
        const sameSize = n => {
          const owner = n.nodeType === 3 ? n.parentElement : n;
          return owner && Math.round(parseFloat(getComputedStyle(owner).fontSize)) === s;
        };
        const walk = n => {
          for (const k of n.childNodes) {
            if (k.nodeType === 3) { if (sameSize(k)) whole += ' ' + k.textContent; }
            else if (k.nodeType === 1) walk(k);
          }
        };
        walk(host);
        whole = (whole.trim() || t).replace(/\s+/g, ' ').trim();
        display = {
          px: s, family: f, weight: c.fontWeight,
          tracking: c.letterSpacing, leading: c.lineHeight,
          width_px: Math.round(r.width), width_pct: Math.round(100 * r.width / vw),
          words: whole.split(/\s+/).filter(Boolean).length, text: whole.slice(0, 90)
        };
      }
    }
    if (c.backgroundColor !== 'rgba(0, 0, 0, 0)')
      bgColors.set(c.backgroundColor, (bgColors.get(c.backgroundColor) || 0) + 1);
    if (c.backgroundImage && c.backgroundImage.includes('gradient'))
      gradients.push(c.backgroundImage.slice(0, 70));
    const rad = parseFloat(c.borderRadius);
    if (rad > 0) radii.set(Math.round(rad), (radii.get(Math.round(rad)) || 0) + 1);
    if (c.boxShadow !== 'none') shadows.push(c.boxShadow.slice(0, 60));
  }

  const top = (m, n) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, n)
      .map(([k, v]) => ({ value: k, count: v }));

  // Every element a visitor can actually act on. The first version counted BUTTON plus
  // an A whose CLASS NAME happened to contain btn/button/cta, which misses an ordinary
  // navigation link entirely: a real header nav scored 0. Found 2026-09-15 building round
  // g, where a page with a six-item header measured 2 controls. An instrument that counts
  // a class name rather than the thing is measuring naming convention.
  const btns = fold.filter(e =>
      e.tagName === 'BUTTON' || e.tagName === 'SELECT' ||
      (e.tagName === 'INPUT' && e.type !== 'hidden') ||
      (e.tagName === 'A' && e.hasAttribute('href')) ||
      e.getAttribute('role') === 'button' ||
      (e.hasAttribute('tabindex') && e.getAttribute('tabindex') !== '-1'));
  const buttons = btns.slice(0, 5).map(e => { const c = getComputedStyle(e);
    return { text: (e.innerText || '').trim().slice(0, 28), radius: c.borderRadius,
             bg: c.backgroundColor, color: c.color, padding: c.padding,
             font_px: Math.round(parseFloat(c.fontSize)), weight: c.fontWeight }; });

  const imgs = fold.filter(e => e.tagName === 'IMG');
  const bgImgs = fold.filter(e => { const b = getComputedStyle(e).backgroundImage;
    return b !== 'none' && !b.includes('gradient'); });

  // HOW MUCH OF THE FOLD IS A VISUAL OBJECT, by area rather than by count.
  // Counting elements is gameable and was gamed: a round met an svg floor of 5 with a
  // logo, three bars and an arrow, while every exemplar's fold is dominated by a large
  // visual (a chromatic ribbon, a gradient field, a product screen, artwork panels, a
  // full-bleed photograph). Area is the property that separates them; count is not.
  const visualTags = new Set(['IMG', 'SVG', 'VIDEO', 'CANVAS', 'PICTURE']);
  const visuals = fold.filter(e => visualTags.has(e.tagName.toUpperCase()) ||
      (getComputedStyle(e).backgroundImage || 'none') !== 'none');
  const clipped = e => { const r = e.getBoundingClientRect();
    const w = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
    const h = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    return w * h; };
  // an element nested inside another visual would be counted twice, so only count a
  // visual whose nearest visual ancestor is not itself in the set
  const outermost = visuals.filter(e => !visuals.some(o => o !== e && o.contains(e)));
  const areas = outermost.map(clipped);
  const foldArea = vw * vh;
  const largest = areas.length ? Math.max(...areas) : 0;
  const covered = areas.reduce((a, b) => a + b, 0);

  // widest block of running text = the content measure the page actually uses
  let measure = 0;
  for (const e of fold) { const t = own(e);
    if (t.split(/\s+/).length > 12) measure = Math.max(measure,
      Math.round(e.getBoundingClientRect().width)); }

  return {
    viewport: vw + 'x' + vh,
    type: { families: top(fam, 4), size_ramp: [...sizes.keys()].sort((a, b) => a - b),
            weights: top(weights, 4), display },
    color: { backgrounds: top(bgColors, 6), text: top(textColors, 5),
             gradient_count: gradients.length, gradient_samples: [...new Set(gradients)].slice(0, 2) },
    shape: { radii: top(radii, 5), shadow_count: shadows.length,
             shadow_samples: [...new Set(shadows)].slice(0, 2) },
    imagery: { img: imgs.length, svg: fold.filter(e => e.tagName === 'svg').length,
               video: fold.filter(e => e.tagName === 'VIDEO').length,
               canvas: fold.filter(e => e.tagName === 'CANVAS').length,
               background_images: bgImgs.length,
               largest_visual_pct: Math.round(100 * largest / foldArea),
               visual_area_pct: Math.min(100, Math.round(100 * covered / foldArea)),
               img_src_sample: imgs.slice(0, 3).map(e => (e.currentSrc || e.src || '').slice(-60)) },
    motion: { animated: fold.filter(e => getComputedStyle(e).animationName !== 'none').length,
              transitioned: fold.filter(e => { const c = getComputedStyle(e);
                return c.transitionDuration !== '0s' && c.transitionProperty !== 'none'; }).length },
    layout: { content_measure_px: measure, buttons_in_fold: btns.length, buttons },
  };
}
"""


def capture(url: str, out_dir: Path, shoot: bool) -> dict:
    from playwright.sync_api import sync_playwright
    rec: dict = {"url": url, "captured": date.today().isoformat(), "viewports": {}}
    slug = re.sub(r"[^a-z0-9]+", "-", url.split("//")[-1].split("/")[0].lower()).strip("-")
    rec["slug"] = slug
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA)
        for name, w, h in VIEWPORTS:
            pg = ctx.new_page()
            pg.set_viewport_size({"width": w, "height": h})
            try:
                pg.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    rec["viewports"][name] = {"error": str(e)[:160]}
                    pg.close()
                    continue
            pg.wait_for_timeout(1800)
            try:
                rec["viewports"][name] = pg.evaluate(PROBE)
            except Exception as e:
                rec["viewports"][name] = {"error": str(e)[:160]}
            if shoot:
                try:
                    pg.screenshot(path=str(out_dir / f"{slug}-{name}.png"))
                except Exception:
                    pass
            pg.close()
        b.close()
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("refs")
    ap.add_argument("--add", nargs="*", default=[])
    ap.add_argument("--only")
    ap.add_argument("--no-shot", action="store_true")
    a = ap.parse_args()

    refs = Path(a.refs).resolve()
    refs.mkdir(parents=True, exist_ok=True)
    roster = refs / "exemplars.json"
    data = json.loads(roster.read_text()) if roster.is_file() else {"exemplars": []}

    known = {e["url"] for e in data["exemplars"]}
    for raw in a.add:
        url = raw if raw.startswith("http") else "https://" + raw.lstrip("/")
        if url not in known:
            data["exemplars"].append({"url": url, "added": date.today().isoformat()})
            known.add(url)
    roster.write_text(json.dumps(data, indent=2) + "\n")

    targets = [e for e in data["exemplars"] if not a.only or a.only in e["url"]]
    if not targets:
        print("no exemplars to capture", file=sys.stderr)
        return 2

    records = []
    for e in targets:
        print("capturing", e["url"], flush=True)
        rec = capture(e["url"], refs, not a.no_shot)
        (refs / f"{rec['slug']}.json").write_text(json.dumps(rec, indent=2) + "\n")
        records.append(rec)

    # MEASUREMENTS.md is regenerated, never hand-edited: it is the measured half.
    lines = [f"<!-- generated by design-exemplar-capture.py on {date.today().isoformat()};",
             "     do not hand-edit. The NARRATIVE is the human half, in NARRATIVE.md. -->",
             "# Exemplar measurements", "",
             f"{len(records)} page(s), captured in a real browser at 1440x900 and 390x844.",
             "Every number below came out of the probe; nothing here is recalled.", ""]
    for r in records:
        lap = r["viewports"].get("laptop", {})
        lines.append(f"## {r['url']}")
        if "error" in lap or not lap:
            lines += [f"CAPTURE FAILED: {lap.get('error', 'no data')}", ""]
            continue
        t, c, s, im, mo, ly = (lap["type"], lap["color"], lap["shape"],
                               lap["imagery"], lap["motion"], lap["layout"])
        d = t["display"] or {}
        lines += [
            f"- type: {', '.join(f['value'] for f in t['families'])}",
            f"- size ramp: {t['size_ramp']}",
            f"- display: {d.get('px')}px {d.get('weight')} across {d.get('width_pct')}% of the "
            f"viewport, {d.get('words')} words, tracking {d.get('tracking')}, leading {d.get('leading')}",
            f"- display text: {d.get('text', '')!r}",
            f"- backgrounds: {[b['value'] for b in c['backgrounds']]}",
            f"- gradients in fold: {c['gradient_count']}",
            f"- radii: {[x['value'] for x in s['radii']]}   shadows: {s['shadow_count']}",
            f"- fold given to visuals: largest object {im.get('largest_visual_pct', 0)}%% of the fold, "
            f"all visuals {im.get('visual_area_pct', 0)}%% "
            f"(counting elements is gameable; area is what separates these folds)",
            f"- imagery: img {im['img']}, svg {im['svg']}, video {im['video']}, "
            f"canvas {im['canvas']}, background-images {im['background_images']}",
            f"- motion: {mo['animated']} animated, {mo['transitioned']} transitioned",
            f"- content measure: {ly['content_measure_px']}px, {ly['buttons_in_fold']} buttons in fold",
        ]
        for btn in ly["buttons"][:2]:
            lines.append(f"  - button {btn['text']!r}: radius {btn['radius']}, "
                         f"{btn['font_px']}px {btn['weight']}, bg {btn['bg']}")
        lines.append("")
    (refs / "MEASUREMENTS.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {refs/'MEASUREMENTS.md'} ({len(records)} page(s))")
    print("NEXT: rewrite NARRATIVE.md for the WHOLE set. Adding a page and not re-reading")
    print("the group is what the gate blocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
