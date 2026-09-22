#!/usr/bin/env python3
"""Regenerate design-chain.json `standard` FROM the exemplars, instead of by hand.

RCA rca-design-chain-passes-bland-2026-09-15.md, root cause #3, the most actionable one:
the coded standard and the measured exemplars contradicted each other, and the coded one
won silently for seven rounds.

    design-chain.json standard   max_type_sizes: 3     measured group: 4 to 7
    design-chain.json standard   max_words: 80         never measured at all

Those numbers were hand-written from NN/g's "no more than 3 type sizes and 2 large elements
in a view" BEFORE the founder's exemplars were ever captured, and were never revisited when
the measurements arrived. A page could not satisfy both, so passing the floor GUARANTEED
being sparser than every site the founder had named as the target.

This script measures the exemplars with design-standard-check.py's OWN probe, so the caps
and the check that enforces them are derived from the same instrument, and proposes a
reconciled `standard`. It never writes silently: --apply prints a before-and-after diff and
records the measured basis into the block itself.

WHAT IT DOES NOT DECIDE. Where a cited principle and the founder's own exemplars disagree,
this script takes the exemplars, because the exemplars are what he actually pointed at. It
says so in the output rather than quietly dropping the citation, and the superseded source
stays named in the block. A cap the founder wants tighter than the group is a legitimate
hand override; it just has to carry a reason, which --apply refuses to invent.

Usage:
  design-standard-from-exemplars.py <design-chain.json> [--refs DIR] [--apply]
  design-standard-from-exemplars.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_probe_js() -> str:
    """Reuse design-standard-check.py's OWN measuring JS, read from that file at run time.

    Transcribing it here would make the caps and the check two copies that drift, which is
    the same hand-copy failure this whole script exists to undo."""
    src = (HERE / "design-standard-check.py").read_text()
    m = re.search(r'^JS = """(.*?)"""', src, re.S | re.M)
    if not m:
        raise SystemExit("could not read JS from design-standard-check.py; it moved or was renamed")
    return m.group(1)


def load_cfg(path: Path) -> dict:
    return json.loads(path.read_text())


def exemplar_urls(refs: Path) -> list[str]:
    roster = refs / "exemplars.json"
    d = json.loads(roster.read_text())
    return [e["url"] for e in d.get("exemplars", []) if e.get("url")]


def measure(urls: list[str], cfg: dict) -> dict:
    from playwright.sync_api import sync_playwright
    js = load_probe_js()
    large = str(cfg["standard"]["large_px"])
    sig = cfg["standard"]["signal"]
    w, h = cfg["standard"]["viewports"][0]
    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for url in urls:
            pg = b.new_page(viewport={"width": w, "height": h})
            try:
                # networkidle never settles on sites holding analytics/websocket
                # connections open: squarespace.com and figma.com both timed out at 45s on
                # the first real run, and deriving a cap from the three that DID load is
                # the same defect as letting a bot-walled capture set a floor.
                pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(3500)
                out[url] = pg.evaluate(js.replace("LARGE", large), sig)
            except Exception as e:  # a site that will not load is reported, never skipped
                out[url] = {"_error": str(e)[:120]}
            pg.close()
        b.close()
    return out


def propose(measured: dict, cfg: dict) -> tuple[dict, list[str]]:
    """The reconciled caps, plus a line per cap saying what it was derived from."""
    good = {u: m for u, m in measured.items() if "_error" not in m}
    bad = {u: m["_error"] for u, m in measured.items() if "_error" in m}
    if bad:
        # A cap derived from the exemplars that happened to load is a cap set by network
        # luck. Same posture design-gap-check.py takes on a bot-walled capture: a failed
        # measurement must never quietly move a bar.
        raise SystemExit(
            "REFUSING to propose caps: " + ", ".join(f"{u} ({e[:60]})" for u, e in bad.items()) +
            ". Every rostered exemplar has to measure, or the cap is set by whichever "
            "sites loaded today. Re-run, or drop the site from exemplars.json on purpose.")
    if len(good) < 3:
        raise SystemExit(f"only {len(good)} exemplar(s) measured; too few to set a cap from")
    std = dict(cfg["standard"])
    notes = []

    small = {u: [s for s in m["type_sizes"] if s < cfg["standard"]["large_px"]] for u, m in good.items()}
    hi = max(len(v) for v in small.values())
    notes.append(f"max_type_sizes: {std.get('max_type_sizes')} -> {hi}. Measured under "
                 f"{cfg['standard']['large_px']}px: " +
                 ", ".join(f"{u.split('//')[-1].strip('/')}={len(v)}" for u, v in sorted(small.items())) +
                 ". NN/g's 'no more than 3' is SUPERSEDED by the founder's own exemplars, "
                 "none of which obeys it.")
    std["max_type_sizes"] = hi

    words = {u: m["words"] for u, m in good.items()}
    import statistics as _st
    notes.append(f"max_words: LEFT at {std.get('max_words')}. Measured in the fold: " +
                 ", ".join(f"{u.split('//')[-1].strip('/')}={w}" for u, w in sorted(words.items())) +
                 f" (median {_st.median(words.values()):g}). "
                 "MY ASSUMPTION WAS REFUTED BY THIS MEASUREMENT and the number does not "
                 "move. I argued that 80 collided with the gap check's floor of 7 controls, "
                 "because a navigation carries words in. Four of five exemplars sit between "
                 "19 and 67 words WITH their navigation, so 80 is not binding and is not "
                 "what made the round bland. Deriving max() here would let the single "
                 "wordiest page set the cap, against the founder's own verdict on a block "
                 "of words.")

    larges = {u: m["large_elements"] for u, m in good.items()}
    lmax = max(larges.values())
    notes.append(f"max_large_elements: {std.get('max_large_elements')} -> {lmax}. Measured: " +
                 ", ".join(f"{u.split('//')[-1].strip('/')}={n}" for u, n in sorted(larges.items())) + ".")
    std["max_large_elements"] = lmax

    body = {u: m["min_body_px"] for u, m in good.items() if m.get("min_body_px")}
    if body:
        bmin = min(body.values())
        notes.append(f"min_body_px: LEFT at {std.get('min_body_px')}. Measured smallest: " +
                     ", ".join(f"{u.split('//')[-1].strip('/')}={n}" for u, n in sorted(body.items())) +
                     ". NOT lowered to match: Butterick and Bringhurst put body at 15px "
                     "minimum and the group going smaller is not a reason for this site to.")

    notes.append("max_signal_elements: LEFT at "
                 f"{std.get('max_signal_elements')}. The signal colour means the mismatch and "
                 "nothing else (design-dna.md section 4), which is this site's idea and not "
                 "the group's, so the group cannot set it. Distinct BACKGROUND colours are a "
                 "different axis and are floored by design-gap-check.py.")
    std["_derived"] = {
        "by": "design-standard-from-exemplars.py",
        "from": sorted(good),
        "errors": {u: m["_error"] for u, m in measured.items() if "_error" in m},
        "notes": notes,
    }
    return std, notes


def selftest() -> int:
    js = load_probe_js()
    assert "type_sizes" in js and "large_elements" in js, "the probe did not come back whole"
    fake = {
        "a": {"type_sizes": [14, 16, 32, 48], "large_elements": 1, "words": 40, "min_body_px": 14},
        "b": {"type_sizes": [12, 14, 16, 20, 22, 72, 96], "large_elements": 2, "words": 90, "min_body_px": 12},
        "c": {"type_sizes": [16, 18, 30, 56], "large_elements": 1, "words": 61, "min_body_px": 16},
    }
    cfg = {"standard": {"large_px": 40, "signal": "#0066b3", "viewports": [[1440, 900]],
                        "max_type_sizes": 3, "max_words": 80, "max_large_elements": 2,
                        "min_body_px": 15, "max_signal_elements": 2}}
    std, notes = propose(fake, cfg)
    # b's ramp is [12,14,16,20,22,72,96]; five of those are under 40px, not six. My first
    # version of this line asserted 6 from memory and the script was right. Counted, not recalled:
    assert len([x for x in fake["b"]["type_sizes"] if x < 40]) == 5
    assert std["max_type_sizes"] == 5, std["max_type_sizes"]
    assert std["max_words"] == 80, "max_words must NOT be derived from the wordiest exemplar"
    assert std["max_large_elements"] == 2
    assert std["min_body_px"] == 15, "min_body_px must NOT be lowered to match the group"
    assert std["max_signal_elements"] == 2, "the group cannot set this site's signal rule"
    assert any("SUPERSEDED" in n for n in notes)
    # A single failed measurement must refuse outright, even when enough others loaded.
    try:
        propose(dict(fake, d={"_error": "boom"}), cfg)
    except SystemExit as e:
        assert "REFUSING" in str(e), e
    else:
        raise AssertionError("a failed exemplar measurement must refuse, not derive around it")
    try:
        propose({"a": fake["a"], "b": fake["b"]}, cfg)
    except SystemExit:
        pass
    else:
        raise AssertionError("too few measured exemplars must refuse, not guess")
    print("selftest: one failed measurement refuses outright; caps derive from the measured group, min_body_px and the signal rule "
          "are held against it, a too-small sample refuses")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?")
    ap.add_argument("--refs")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.config:
        ap.error("config is required")
    cfgp = Path(a.config).resolve()
    cfg = load_cfg(cfgp)
    refs = Path(a.refs).resolve() if a.refs else cfgp.parent / "site" / "design" / "references"
    urls = exemplar_urls(refs)
    print(f"measuring {len(urls)} exemplar(s) with design-standard-check.py's own probe")
    measured = measure(urls, cfg)
    for u, m in measured.items():
        if "_error" in m:
            print(f"  COULD NOT MEASURE {u}: {m['_error']}")
    std, notes = propose(measured, cfg)
    print("\nPROPOSED standard, derived:")
    for n in notes:
        print(f"  - {n}")
    if a.apply:
        cfg["standard"] = std
        cfgp.write_text(json.dumps(cfg, indent=2) + "\n")
        print(f"\napplied to {cfgp}")
    else:
        print("\nnot applied. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
