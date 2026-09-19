#!/usr/bin/env python3
"""Measure a built page AGAINST the captured exemplars. Distance, not absence.

The gap this closes, RCA rca-design-chain-passes-bland-2026-09-15.md: every other
mechanical check in the design chain is a defect-ABSENCE detector, and a bland page has no
defects. A deliberately bland control page passed design-standard-check.py, the
dogfood_gate tripwire AND the impeccable browser detector, all three, in one run whose own
control fired. Seven rounds drifted the same way while every gate stayed green.

What was missing is not another detector. It is a DISTANCE to a target, where the target is
the founder's own exemplars, measured rather than described. The numbers already existed in
references/*.json and no executable read them.

THE FLOORS ARE DERIVED, NEVER HAND-WRITTEN. Each floor is the MINIMUM any exemplar in the
set reaches on that axis: "at least as much as the least of your own examples." That makes
the bar move when the roster moves, and it makes it impossible to set the bar by taste. It
is also deliberately the weakest defensible target: matching the median would be a demand
to equal the best of the group on every axis at once.

NOT EVERY AXIS IS FLOORED, and the reasons are per axis in AXES below. Flooring an axis the
canon argues against would make this script fight site-design.md, which is the exact
failure that produced the RCA: design-chain.json's `standard` capped type sizes at 3 while
the measured group runs 4 to 7, so passing the floor GUARANTEED being sparser than every
exemplar. A gate that contradicts the canon wins silently, so this one only floors axes
where the canon and the measurement agree.

Exit 0 = every floored axis is met. Exit 2 = at least one is BELOW the floor. Exit 3 = COULD NOT
MEASURE (too few exemplar captures, no pages, no served round, served bytes differ, no browser).
There is no exit code meaning "this page is good", for the same reason
check_technique_parity.py has none: a floor is not a finish line.

Usage:
  design-gap-check.py <round-dir> --url-base <served round> [--refs DIR] [--write]
  design-gap-check.py --selftest
"""
from __future__ import annotations

import argparse
import urllib.parse
import urllib.request
import hashlib
import json
import statistics
import sys
from pathlib import Path

FORBIDDEN_VERDICTS = ("PASS", "DONE", "GOOD", "SHIPPED", "APPROVED")
RECEIPT = "gap.json"
# A floor that is NOT derived carries its number here, in the open, so a reader can
# tell a measured bar from a chosen one at a glance.
PRESENCE_FLOOR = {"controls": 5}
# Axes where being ABOVE the group is the defect, not only being below. The ceiling is
# derived the same way the floor is: the most any exemplar does.
RANGE_AXES: set[str] = set()   # display_words left it 2026-09-16, see its reason


def _n(d, *path, default=0):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if isinstance(cur, (int, float)) else default


# (key, label, extractor, floored, why)
AXES = [
    ("background_colours", "distinct background colours",
     lambda d: len(_l(d, "color", "backgrounds")), True,
     "NARRATIVE.md section 3, measured and then ignored by the build: 'Depth comes from "
     "colour fields and layering, not from drop shadows.' The canon and the group agree, "
     "and the round that triggered the RCA had zero."),
    ("responds_per_control", "transitions per interactive control",
     lambda d: round(_n(d, "motion", "transitioned") / max(_n(d, "layout", "buttons_in_fold"), 1), 2),
     True,
     "NARRATIVE.md section 5: the group barely animates and responds richly to the pointer. "
     "The property is that CONTROLS RESPOND, and it holds tightly across the set: figma "
     "0.95, notion 1.12, squarespace 1.15, calendly 1.58, stripe 5.15 transitions per "
     "control. A ratio transfers to a site of any size; an absolute count is a measure of "
     "how big somebody's navigation is."),
    ("transitioned", "elements that respond to the pointer",
     lambda d: _n(d, "motion", "transitioned"), False,
     "NOT FLOORED, and this floor was REMOVED AFTER IT FAILED A PAGE, which is the "
     "suspicious direction to move a bar, so the argument is here in full. It was floored "
     "at 18, the least any exemplar reaches. Round 2026-09-15g measured 12 with a full "
     "header nav, a three-row artifact that responds and two buttons. Looking at the set "
     "next to the control count showed what the number actually tracks: transitions run "
     "0.95 to 5.15 PER CONTROL across all five, so 18 was measuring the size of a product "
     "company's navigation and not whether anything responds. The property is kept as the "
     "ratio axis above, where round g measures 1.71 and sits above three of the five. The "
     "founder can overrule this by setting floored back to True."),
    ("svg", "svg elements in the fold",
     lambda d: _n(d, "imagery", "svg"), False,
     "UNFLOORED 2026-09-16, and it is a RETIREMENT rather than a loosening. It was floored "
     "at 5 as a stand-in for 'the fold carries real visual work'. It never measured that: "
     "round g satisfied it with a logo, three bars and an arrow, and round 2026-09-16 draws "
     "its record in CSS and scores 1 while carrying MORE visual weight, not less. A count "
     "of elements was always a proxy. The property it stood for is now measured directly by "
     "ink_non_background and ink_chromatic, from the screenshot, where it cannot be gamed by "
     "splitting one drawing into five tags or beaten by drawing without tags. Kept and "
     "reported because the number is worth reading, never as a bar."),
    ("radii", "distinct corner radii",
     lambda d: len(_l(d, "shape", "radii")), True,
     "NARRATIVE.md section 6: the group has two radius tiers, small for controls and fully "
     "round for chips, with no 12px middle. Two tiers needs two radii."),
    ("controls", "interactive controls in the fold",
     lambda d: _n(d, "layout", "buttons_in_fold"), "presence",
     "FLOORED ON PRESENCE, NOT ON THE DERIVED COUNT, and this was also loosened after it "
     "failed a page. The derived fact that transfers is that 5 of 5 exemplars carry "
     "NAVIGATION in the fold; round f carried one button, no nav, no logo and no footer, "
     "and read as a slide. The derived COUNT does not transfer: the exemplars run 19 to "
     "127 controls because they are product companies with menus, and a two-person "
     "consulting page with 19 controls in its first screen would contradict "
     "RULE-2026-09-15-H directly, which says the visitor must understand the offer at once "
     "and not play with the page. So the floor is PRESENCE_FLOOR below, the smallest "
     "number that constitutes a navigation plus an action, and it is a judgement stated "
     "out loud rather than a number derived from a set that does not apply."),
    ("type_sizes", "type sizes in the fold",
     lambda d: len(_l(d, "type", "size_ramp")), True,
     "design-chain.json `standard` capped this at 3 while the group runs 4 to 7. That "
     "contradiction is the RCA's most actionable cause. The cap is regenerated from these "
     "same captures by design-standard-from-exemplars.py so the two agree."),
    ("display_words", "words in the display line",
     lambda d: _n(d, "type", "display", "words"), False,
     "UNFLOORED 2026-09-16 ON A CORRECTED MEASUREMENT, and the correction is the point. "
     "This axis was floored as a 3-to-6 range on the claim that round g's 16-word display "
     "line was three times the longest in the group. That claim was FALSE. The probe "
     "counted only the first text node of each headline. Counting the whole run of text set "
     "at the display size shows stripe at 22 words: its dark sentence and the blue-grey "
     "continuation are both 48px, split by colour, not by size. The group therefore runs 3 "
     "to 22, and a range that wide disciplines nothing, so it is reported and not enforced. "
     "What stripe proves is that a long display line can work WHEN it sits against a large "
     "coloured surface (its ribbon takes 74% of the fold). Round g did not fail on word "
     "count; it failed on ink_chromatic, at 0 against a floor of 3, and that axis caught it."),
    ("largest_visual_pct", "share of the fold given to its largest visual object",
     lambda d: _n(d, "imagery", "largest_visual_pct"), False,
     "MEASURED, NOT FLOORED, AND SUPERSEDED. This was the third attempt at the property "
     "and all three failed: a COUNT of visual elements was gamed by a logo and three "
     "bars; this AREA version read figma at 0% against its own screenshot; and walking "
     "shadow roots left figma at 0% while moving calendly from 85% to 28% on an "
     "unchanged page. An instrument whose answer moves 3x when you change how you walk "
     "the tree is not measuring the page. The property now lives in ink_non_background "
     "and ink_chromatic, measured from the screenshot, where it is stable and does not "
     "care how the page painted. Kept and reported because the DOM numbers are still "
     "worth reading next to the pixel ones, never as a bar."),
    ("visual_area_pct", "share of the fold covered by visuals in total",
     lambda d: _n(d, "imagery", "visual_area_pct"), False,
     "MEASURED, NOT FLOORED, same instrument fault as largest_visual_pct. Reads calendly "
     "100%, squarespace 100%, stripe 100%, notion 66%, figma 0%."),
    ("ink_non_background", "share of the fold that is not the page's own background",
     lambda d: _n(d, "ink", "non_background_pct"), True,
     "MEASURED FROM THE SCREENSHOT, not the DOM, after three DOM attempts failed (see "
     "ink_for). Across the set: squarespace 89, calendly 72, figma 37, stripe 31, notion "
     "10. Our grey rounds read 4 to 6. This is the axis that says a fold is mostly empty "
     "paper, and it is the honest replacement for the svg COUNT floor that a logo and three "
     "bars satisfied."),
    ("ink_chromatic", "share of the fold carrying real colour",
     lambda d: _n(d, "ink", "chromatic_pct"), True,
     "Dark text on light paper is not colour, so this counts only pixels with real chroma. "
     "Across the set: calendly 67, squarespace 48, stripe 29, figma 16, notion 3. Round f "
     "and round g's grey variant both read ZERO, which is the number behind the founder's "
     "word for them. NARRATIVE.md section 3 said it first and the build ignored it: 'Depth "
     "comes from colour fields and layering.'"),
    ("images", "images in the fold",
     lambda d: _n(d, "imagery", "img"), False,
     "NOT FLOORED. design-dna.md section 4 bans stock imagery and allows only real records "
     "recreated and anonymized. squarespace's 20 images are its product; demanding a count "
     "here would push the build toward exactly the stock filler the canon forbids."),
    ("shadows", "shadows",
     lambda d: _n(d, "shape", "shadow_count"), False,
     "NOT FLOORED. NARRATIVE.md section 3 measured the group as essentially flat and "
     "site-design.md section 7 treats shadow-heavy depth as a tell. Flooring this would "
     "fight the canon."),
    ("gradients", "gradients",
     lambda d: _n(d, "color", "gradient_count"), False,
     "NOT FLOORED. site-design.md section 7 bans gradient-on-type and the palette question "
     "is an open founder decision in OPEN-DECISIONS.md."),
    ("video", "video elements",
     lambda d: _n(d, "imagery", "video"), False,
     "NOT FLOORED. Three of five exemplars have zero, so the set does not support a floor."),
    ("display_px", "display size in px",
     lambda d: _n(d, "type", "display", "px"), False,
     "NOT FLOORED here because design-chain.json `standard` already governs large elements "
     "and a round may legitimately carry no display line at all (round 2026-09-15f's "
     "Exhibit direction, founder-directed: 'Why do we have to have the heading at all')."),
]


def _l(d, *path):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(k)
    return cur if isinstance(cur, list) else []


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ink_for(png: Path) -> dict:
    """The pixel measurement for one screenshot, or {} when there is none.

    Why pixels and not the DOM. Three DOM attempts at "how much of the fold is visual"
    failed: a COUNT of visual elements was gamed by a logo and three bars; an AREA of
    visual elements read figma.com at 0% against its own screenshot; and walking shadow
    roots left figma at 0% while moving calendly from 85% to 28% on an unchanged page. An
    instrument whose answer moves 3x when you change how you walk the tree is not measuring
    the page. Sites paint with images, inline svg, canvas, gradients, masks, web components
    and video, and a probe must enumerate all of it correctly on every site. A screenshot
    does not have that problem: whatever the page did, the colour is on the screen.
    """
    if not png.is_file():
        return {}
    try:
        ink = _load_sibling("design-ink-coverage")
        return ink.measure(png)
    except Exception:
        return {}


def _load_sibling(mod: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        mod.replace("-", "_"), Path(__file__).resolve().parent / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_exemplars(refs: Path) -> dict:
    """Every captured exemplar's laptop fold. A capture that failed is excluded BY NAME in
    the narrative, not silently here, so a bot-walled site cannot quietly lower the bar."""
    out = {}
    for f in sorted(refs.glob("*.json")):
        if f.name == "exemplars.json":
            continue
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        vps = d.get("viewports", {}) if isinstance(d, dict) else {}
        wide = vps.get("laptop") or next(
            (v for v in vps.values() if str(v.get("viewport", "")).startswith("1440")), None)
        if not wide:
            continue
        wide = dict(wide)
        wide["ink"] = ink_for(f.with_name(f.stem + "-laptop.png"))
        out[f.stem] = wide
    return out


def usable(ex: dict) -> tuple[dict, list[str]]:
    """Split the captures into the ones that describe a DESIGN and the ones that describe
    an error page, and hand back the rejects BY NAME.

    This exists because of a live miss, not a hypothetical. canva.com returned its bot-wall
    page ("We'll have you designing again soon", one SVG, zero buttons). NARRATIVE.md
    section 1 says so in writing and excludes it from every claim; this script did not, so
    on its first real run against a round the canva row pulled the background-colour floor
    from 3 down to 1 and would have pulled every other floor with it. A failed capture that
    silently LOWERS a bar is the same defect class as a skipped check reading as a pass
    (ASK-1746).

    The test is a property no marketing page lacks and no bot wall has: at least one
    interactive control in the fold, and at least three distinct type sizes."""
    good, rejected = {}, []
    for name, cap in ex.items():
        controls = _n(cap, "layout", "buttons_in_fold")
        sizes = len(_l(cap, "type", "size_ramp"))
        if controls < 1 or sizes < 3:
            rejected.append(f"{name} (controls={controls}, type sizes={sizes}: reads as an "
                            f"error or bot-wall page, not a design)")
        else:
            good[name] = cap
    return good, rejected


def floors(ex: dict) -> dict:
    """floor = the least any exemplar reaches. Derived, so taste cannot set it."""
    out = {}
    for key, label, fn, floored, why in AXES:
        vals = [fn(v) for v in ex.values()]
        if floored == "presence":
            floor = PRESENCE_FLOOR[key]
        elif floored and vals:
            floor = min(vals)
        else:
            floor = None
        out[key] = {
            "label": label, "floored": bool(floored),
            "derived": floored is True, "why": why,
            "floor": floor,
            "ceiling": (max(vals) if (key in RANGE_AXES and vals) else None),
            "median": statistics.median(vals) if vals else None,
            "range": [min(vals), max(vals)] if vals else None,
        }
    return out


def _stay_in_the_round(ctx, url: str, refused: list) -> None:
    """Route every request of this browser context: the served round's origin (scheme, host AND
    port, compared parsed) goes through; anything else is aborted and recorded, and so is every
    WebSocket (recorded and left unconnected: ws.close() inside the handler hangs the sync API).
    ASK-1837: a stylesheet from another origin made a 9px page measure 18px and the round sealed
    on bytes that fail, while seal's byte compare saw only round files. The reader gate carries the
    same guard (ASK-1836)."""
    import urllib.parse as _up

    def origin(u):
        s = _up.urlsplit(u)
        return (s.scheme, s.hostname, s.port)
    allowed = origin(url)

    def gate(route):
        if origin(route.request.url) == allowed:
            route.continue_()
        else:
            if route.request.url not in refused:
                refused.append(route.request.url)
            route.abort()

    def no_socket(ws):
        if ws.url not in refused:
            refused.append(ws.url)
    ctx.route("**/*", gate)
    ctx.route_web_socket("**/*", no_socket)


def _refuse_outside(refused: list) -> None:
    if refused:
        raise RuntimeError(f"the page reached outside the served round for {refused[:5]}; the "
                           f"measurement would be of something the seal never hashed")


def probe_pages(round_dir: Path, url_base: str, names: list[str]) -> dict:
    import importlib.util
    cap_path = Path(__file__).resolve().parent / "design-exemplar-capture.py"
    spec = importlib.util.spec_from_file_location("cap", cap_path)
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    from playwright.sync_api import sync_playwright
    out = {}
    refused: list[str] = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name in names:
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            _stay_in_the_round(ctx, f"{url_base}/{name}", refused)
            pg = ctx.new_page()
            pg.goto(f"{url_base}/{name}", wait_until="networkidle")
            pg.wait_for_timeout(1200)
            measured = pg.evaluate(cap.PROBE)
            measured["ink"] = ink_for(round_dir / (Path(name).stem + ".png"))
            out[name] = measured
            ctx.close()
        b.close()
    _refuse_outside(refused)
    return out


def judge(measured: dict, fl: dict) -> list[str]:
    if not measured.get("ink"):
        return ["no screenshot beside this page, so the pixel axes could not be measured. "
                "Run the round's shoot.py first. An axis that cannot be measured must not "
                "read as met."]
    """Every floored axis this page does not reach, plus every range axis it overshoots.
    Empty list means every floor is met, which is NOT the same as the page being good."""
    bad = []
    for key, label, fn, floored, why in AXES:
        if not floored or fl[key]["floor"] is None:
            continue
        got, want = fn(measured), fl[key]["floor"]
        ceiling = fl[key].get("ceiling")
        if ceiling is not None and got > ceiling:
            bad.append(f"{label}: {got}, and the most any exemplar uses is {ceiling} "
                       f"(their range {fl[key]['range'][0]} to {fl[key]['range'][1]})")
            continue
        if got < want:
            how = ("the least any exemplar reaches is" if fl[key]["derived"]
                   else "the stated presence floor is")
            bad.append(f"{label}: {got}, and {how} {want} "
                       f"(their range {fl[key]['range'][0]} to {fl[key]['range'][1]})")
    return bad


# Exit codes (dc-03). 2 used to mean BOTH "an axis is below the floor" and "bad input", so
# seal could not tell a judged failure from a run that judged nothing. 2 now means one thing.
BELOW_FLOOR = 2
COULD_NOT_MEASURE = 3


def report(round_dir: Path, url_base: str, refs: Path, write: bool) -> int:
    names = sorted(p.name for p in round_dir.glob("*.html"))
    if not names:
        print(f"could not measure: no pages in {round_dir}", file=sys.stderr)
        return COULD_NOT_MEASURE
    if not url_base:
        print("could not measure: no --url-base. The round has to be SERVED to be measured; "
              "design-chain-gate.py seal serves it on a port of its own.", file=sys.stderr)
        return COULD_NOT_MEASURE
    # ONE read per page, before any browser; these are the only shas the receipt may carry.
    measured = {name: sha(round_dir / name) for name in names}
    for name in names:
        try:
            served = hashlib.sha256(urllib.request.urlopen(f"{url_base}/{urllib.parse.quote(name)}", timeout=20).read()).hexdigest()
        except OSError as e:
            print(f"could not measure: {url_base}/{name} is not being served: {e}", file=sys.stderr)
            return COULD_NOT_MEASURE
        if served != measured[name]:
            print(f"could not measure: served bytes differ from {name}. {url_base} is handing out "
                  f"another round, so a verdict here would be about the wrong bytes.", file=sys.stderr)
            return COULD_NOT_MEASURE
    ex, rejected = usable(load_exemplars(refs))
    if rejected:
        print("EXCLUDED CAPTURES (a failed capture must never quietly lower a floor):")
        for r in rejected:
            print(f"  {r}")
        print()
    if len(ex) < 3:
        print(f"could not measure: only {len(ex)} usable exemplar capture(s) in {refs}; the floors "
              f"would be set by too small a set to mean anything. Run design-exemplar-capture.py.",
              file=sys.stderr)
        return COULD_NOT_MEASURE
    fl = floors(ex)
    try:
        got = probe_pages(round_dir, url_base, names)
    except Exception as e:  # playwright missing, a page that will not load
        print(f"could not measure: {e}", file=sys.stderr)
        return COULD_NOT_MEASURE

    print(f"GAP TO THE EXEMPLARS: {', '.join(sorted(ex))}")
    print("floor = the least any one of them reaches. Derived from the captures, not chosen.\n")
    changed = [n for n in names if sha(round_dir / n) != measured[n]]
    if changed:
        print(f"could not measure: {changed} changed while being measured, so no verdict can be "
              f"signed for either version. Measure again.", file=sys.stderr)
        return COULD_NOT_MEASURE
    receipt, failed = {"_exemplars": sorted(ex), "_floors": fl, "pages": {}}, 0
    for name in names:
        bad = judge(got[name], fl)
        receipt["pages"][name] = {
            "sha256": measured[name],
            "axes": {k: f(got[name]) for k, _, f, _, _ in AXES},
            "below_floor": bad,
        }
        head = "MEETS EVERY FLOOR" if not bad else f"{len(bad)} AXIS/AXES BELOW FLOOR"
        print(f"{name}: {head}")
        for b in bad:
            print(f"    {b}")
        failed += bool(bad)

    print("\nnot floored, and why (read this before assuming silence is approval):")
    for key, label, _, floored, why in AXES:
        if not floored:
            print(f"  {label}: {why.splitlines()[0]}")
    print("""
THIS IS A FLOOR, NOT A FINISH LINE. Meeting every floor means the page is not sparser than
the least of the exemplars on the axes measured. It says nothing about whether the page is
good, whether the composition works, or whether a buyer understands it. Counting elements
is not judging them.""")
    if write:
        (round_dir / "checks").mkdir(exist_ok=True)
        (round_dir / "checks" / RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"\nwrote {round_dir / 'checks' / RECEIPT}")
    return BELOW_FLOOR if failed else 0


def selftest() -> int:
    """The guard has to be shown able to fail, and shown unable to emit a certificate."""
    src = Path(__file__).read_text()
    body = src.split('def selftest', 1)[0]
    for word in FORBIDDEN_VERDICTS:
        # the word may appear in the forbidden list itself and in prose about it
        printed = [ln for ln in body.splitlines()
                   if "print(" in ln and word in ln and "FORBIDDEN" not in ln]
        assert not printed, f"selftest: this tool must never print {word!r}: {printed}"

    ex = {
        "a": {"color": {"backgrounds": [1, 2, 3], "gradient_count": 0},
              "motion": {"transitioned": 20, "animated": 0},
              "imagery": {"svg": 6, "img": 0, "video": 0, "background_images": 0},
              "shape": {"radii": [1, 2], "shadow_count": 0},
              "layout": {"buttons_in_fold": 8},
              "type": {"size_ramp": [14, 16, 32, 48], "display": {"px": 48, "words": 6}},
              "ink": {"non_background_pct": 31, "chromatic_pct": 29}},
        "b": {"color": {"backgrounds": [1, 2, 3, 4, 5, 6], "gradient_count": 0},
              "motion": {"transitioned": 200, "animated": 1},
              "imagery": {"svg": 60, "img": 20, "video": 5, "background_images": 1},
              "shape": {"radii": [1, 2, 3, 4, 5], "shadow_count": 4},
              "layout": {"buttons_in_fold": 120},
              "type": {"size_ramp": [12, 14, 16, 20, 22, 72, 96], "display": {"px": 96, "words": 3}},
              "ink": {"non_background_pct": 89, "chromatic_pct": 48}},
        "c": {"color": {"backgrounds": [1, 2, 3, 4], "gradient_count": 9},
              "motion": {"transitioned": 40, "animated": 0},
              "imagery": {"svg": 11, "img": 4, "video": 0, "background_images": 0},
              "shape": {"radii": [1, 2, 3], "shadow_count": 2},
              "layout": {"buttons_in_fold": 10},
              "type": {"size_ramp": [16, 18, 30, 56], "display": {"px": 56, "words": 5}},
              "ink": {"non_background_pct": 37, "chromatic_pct": 16}},
    }
    fl = floors(ex)
    assert fl["background_colours"]["floor"] == 3, fl["background_colours"]
    assert fl["transitioned"]["floor"] is None, "transitioned is no longer an absolute floor"
    # Computed, not recalled. My first two attempts at this line asserted numbers from
    # memory and the script was right both times (no-mental-arithmetic.md).
    want = min(round(v["motion"]["transitioned"] / v["layout"]["buttons_in_fold"], 2)
               for v in ex.values())
    assert fl["responds_per_control"]["floor"] == want, (fl["responds_per_control"]["floor"], want)
    assert fl["controls"]["floor"] == 5 and not fl["controls"]["derived"], \
        "controls is a stated presence floor, not a derived one"
    assert fl["svg"]["floor"] is None, "svg is retired as a floor"
    assert fl["type_sizes"]["floor"] == 4
    assert fl["shadows"]["floor"] is None, "an unfloored axis must carry no floor"
    assert fl["images"]["floor"] is None

    rich = ex["c"]
    assert judge(rich, fl) == [], f"an exemplar-shaped page must meet the floors: {judge(rich, fl)}"

    bland = {"color": {"backgrounds": [], "gradient_count": 0},
             "motion": {"transitioned": 2, "animated": 1},
             "imagery": {"svg": 0, "img": 0, "video": 0, "background_images": 0},
             "shape": {"radii": [6], "shadow_count": 0},
             "layout": {"buttons_in_fold": 1},
             "type": {"size_ramp": [15, 16, 84], "display": {"px": 84, "words": 4}},
             "ink": {"non_background_pct": 4, "chromatic_pct": 0}}
    bad = judge(bland, fl)
    # The bland shape must still fail, and it must fail on the axes that survived the two
    # loosenings, not only on the ones that were removed. This is the counter-check for
    # moving a bar after it failed a page.
    assert len(bad) >= 4, f"the bland shape must still fail, got {len(bad)}: {bad}"
    assert any("not the page's own background" in b for b in bad), bad
    assert any("real colour" in b for b in bad), bad
    labels = " ".join(bad)
    for must in ("background colours", "corner radii", "interactive controls"):
        assert must in labels, f"the bland shape should fail on {must}: {bad}"

    # An axis that is floored must actually be able to fail on its own.
    for key, label, fn, floored, _ in AXES:
        if not floored:
            continue
        one_short = json.loads(json.dumps(rich))
        # drive this axis under the floor without touching the others
        if key == "responds_per_control":
            one_short["motion"]["transitioned"] = 0
        elif key == "background_colours":
            one_short["color"]["backgrounds"] = []
        elif key == "transitioned":
            one_short["motion"]["transitioned"] = 0

        elif key == "radii":
            one_short["shape"]["radii"] = []
        elif key == "controls":
            one_short["layout"]["buttons_in_fold"] = 0
        elif key == "type_sizes":
            one_short["type"]["size_ramp"] = [16]
        elif key == "ink_non_background":
            one_short["ink"]["non_background_pct"] = 0
        elif key == "ink_chromatic":
            one_short["ink"]["chromatic_pct"] = 0
        got = judge(one_short, fl)
        assert len(got) == 1 and label in got[0], f"{key} did not fail alone: {got}"

    # An unmeasurable axis must never read as met.
    no_shot = json.loads(json.dumps(rich)); no_shot.pop("ink")
    got = judge(no_shot, fl)
    assert len(got) == 1 and "no screenshot" in got[0], got

    # A bot-wall capture must be rejected BY NAME, and its rejection must RAISE the floors
    # rather than leave them where its near-zero numbers put them.
    botwall = {"color": {"backgrounds": [1], "gradient_count": 0},
               "motion": {"transitioned": 0, "animated": 0},
               "imagery": {"svg": 1, "img": 0, "video": 0, "background_images": 0},
               "shape": {"radii": [], "shadow_count": 0},
               "layout": {"buttons_in_fold": 0},
               "type": {"size_ramp": [28], "display": {"px": 28, "words": 5}},
               "ink": {"non_background_pct": 2, "chromatic_pct": 0}}
    with_wall = dict(ex, canva=botwall)
    kept, rej = usable(with_wall)
    assert "canva" not in kept and len(rej) == 1 and "canva" in rej[0], (kept, rej)
    assert len(kept) == 3, kept
    polluted = floors(with_wall)
    assert polluted["background_colours"]["floor"] == 1, "the bot wall should pull it to 1"
    assert floors(kept)["background_colours"]["floor"] == 3, "rejecting it must restore 3"

    # Too few exemplars must refuse rather than set a bar from one site.
    assert len(load_exemplars(Path("/nonexistent"))) == 0
    print("selftest: a bot-wall capture is rejected by name and rejecting it restores the floor it had lowered; floors derive from the set, an exemplar-shaped page meets them, the "
          "bland shape fails all 6, each floored axis fails alone, no certificate word is "
          "ever printed")
    return 0


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, and 2 means BELOW THE FLOOR here. A run that never
    started did not judge anything."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"could not measure: {message}", file=sys.stderr)
        sys.exit(COULD_NOT_MEASURE)


def main(argv=None) -> int:
    ap = _Parser()
    ap.add_argument("round_dir", nargs="?")
    ap.add_argument("--url-base")          # no default: a typed port is how a stale server got measured
    ap.add_argument("--refs")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.round_dir:
        ap.error("round_dir is required")
    rd = Path(a.round_dir).resolve()
    refs = Path(a.refs).resolve() if a.refs else rd.parent / "references"
    return report(rd, a.url_base, refs, a.write)


if __name__ == "__main__":
    sys.exit(main())
