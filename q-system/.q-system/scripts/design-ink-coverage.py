#!/usr/bin/env python3
"""How much of a fold is NOT background, measured from the screenshot rather than the DOM.

Why a second instrument exists at all. The property that separates the founder's exemplar
folds from ours is how much of the screen is given to something other than plain background:
a chromatic ribbon, a gradient field, a product screen, artwork panels, a photograph. Three
DOM-based attempts at that number failed, and the failures are the argument for this file:

  1. COUNT of visual elements. Gameable, and gamed: a round met an svg floor of 5 with a
     logo, three bars and an arrow.
  2. AREA of visual elements. figma.com read 0% while its own screenshot shows three large
     artwork panels.
  3. AREA, walking shadow roots. figma still read 0%, and calendly moved from 85% to 28%
     on the same page because changing the traversal changed which elements counted as
     outermost. An instrument whose answer moves 3x when you change how you walk the tree
     is not measuring the page.

The assumption underneath all three was that a DOM probe can see "visual" across arbitrary
sites. It cannot: sites paint with images, inline SVG, canvas, CSS gradients, masks, web
components and video, and a probe has to enumerate all of that correctly on every site.

A screenshot has no such problem. Whatever the page did to put colour on the screen, the
colour is on the screen. So this measures pixels: the share of the fold that differs from
the page's own dominant background colour. It is deliberately naive, it is stable, and it
does not care how anything was rendered.

Needs Pillow. Exit 0 always: this reports, it does not gate. The gating decision lives in
design-gap-check.py once the numbers are trusted.

Usage: design-ink-coverage.py <png> [<png> ...]
       design-ink-coverage.py --selftest
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


def measure(path: Path, tol: int = 18) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # a screenshot at device-scale-factor 2 is twice the CSS size; sampling keeps this cheap
    step = max(1, min(w, h) // 400)
    px = [im.getpixel((x, y)) for y in range(0, h, step) for x in range(0, w, step)]
    if not px:
        return {}
    bg, bg_n = Counter(px).most_common(1)[0]
    near = sum(1 for p in px if all(abs(a - b) <= tol for a, b in zip(p, bg)))
    ink = len(px) - near
    # "chroma" is the share that is not merely dark-on-light text: pixels with real colour
    chroma = sum(1 for p in px if (max(p) - min(p)) > 26)
    return {
        "background": "#%02x%02x%02x" % bg,
        "background_share_pct": round(100 * bg_n / len(px)),
        "non_background_pct": round(100 * ink / len(px)),
        "chromatic_pct": round(100 * chroma / len(px)),
        "sampled": len(px),
    }


def selftest() -> int:
    from PIL import Image
    import tempfile
    d = Path(tempfile.mkdtemp())
    plain = Image.new("RGB", (400, 300), (246, 246, 246))
    plain.save(d / "plain.png")
    half = Image.new("RGB", (400, 300), (246, 246, 246))
    for y in range(300):
        for x in range(200, 400):
            half.putpixel((x, y), (83, 58, 253))
    half.save(d / "half.png")

    a, b = measure(d / "plain.png"), measure(d / "half.png")
    assert a["non_background_pct"] == 0, a
    assert a["chromatic_pct"] == 0, a
    assert 45 <= b["non_background_pct"] <= 55, b
    assert 45 <= b["chromatic_pct"] <= 55, b
    assert b["background"] == "#f6f6f6", b
    print("selftest: a plain sheet reads 0% non-background and 0% chromatic, a half-covered "
          "sheet reads about 50% of both, and the dominant colour is identified")
    return 0


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--selftest" in args:
        return selftest()
    if not args:
        print(__doc__.strip().splitlines()[-2], file=sys.stderr)
        return 2
    print(f"{'screenshot':34} {'background':>11} {'not bg':>8} {'colour':>8}")
    for a in args:
        p = Path(a)
        m = measure(p)
        if not m:
            print(f"{p.name:34}  could not read")
            continue
        print(f"{p.name:34} {m['background']:>11} {m['non_background_pct']:>7}% "
              f"{m['chromatic_pct']:>7}%")
    print("""
non bg = share of the fold that is not the page's own dominant colour
colour = share carrying real chroma, so dark text on light paper does not count as colour

Naive on purpose and it does not care HOW the page painted: images, inline svg, canvas,
gradients, masks, web components and video all land as pixels. It says nothing about
whether what is on the screen is any good.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
