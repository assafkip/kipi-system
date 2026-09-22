#!/usr/bin/env python3
"""Every property the exemplar probe measures must have a reader, or a written reason.

Founder, 2026-09-15: "Why was this not enforced. It doesn't look like the hook mechanism
works well."

The hooks work. Their COVERAGE was the problem, and the coverage was chosen by hand.
Measured by mutation rather than argued: of 31 properties the probe records on every
exemplar, 6 moved a floored axis, 5 moved an axis deliberately left unfloored, and 20
moved nothing at all. Two of the twenty are exactly what cost a round:

  type.display.words   squarespace 3, notion 5, calendly 6, stripe 6, figma 6.
                       Round 2026-09-15g shipped 16 and no gate looked.
  imagery.*            every exemplar's fold is dominated by a large visual object. The
                       svg COUNT floor was satisfied by a logo, three bars and an arrow.

The cause is structural and not carelessness. There are two writers and only one is a
machine: design-exemplar-capture.py writes the measurements, a person writes the rules, and
nothing forces the second to be derived from the first. So every axis exists because
somebody thought of it, and the ones nobody thought of do not exist. A gate can only
enforce what was written down.

This closes that by making a measured property with no reader a BLOCKING state. Each one
must be one of:
  - read by a floored axis in design-gap-check.py
  - read by an axis deliberately left unfloored, which carries its reason in the source
  - capped by design-chain.json `standard`
  - listed in NOT_AN_AXIS below with a written reason

Readership is established by MUTATION, never by matching names: change the property, and
see whether any axis's value changes. An earlier version of this diagnostic matched axis
names against field names with a regex and over-counted the blind list, which is the same
error as counting a control by its class name.

Exit 0 = every measured property has a reader or a stated reason.
Exit 2 = at least one does not. There is no exit code meaning the coverage is good.

Usage:
  design-axis-coverage.py <references-dir> [--config <design-chain.json>]
  design-axis-coverage.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Properties that are deliberately NOT axes. Each carries the reason, and the reason has to
# say why the property cannot discipline a build rather than that nobody got to it.
NOT_AN_AXIS = {
    "viewport": "the capture's own label, not a property of the design",
    "type.display.text": "the words themselves; a comparison would be meaningless",
    "type.display.family": "settled by the typeface decision in OPEN-DECISIONS.md, not by a range",
    "type.families": "same decision; a count of families is governed by site-design.md section 6 "
                     "('one typeface can be enough and two is usually plenty'), not by the group",
    "color.gradient_samples": "sample strings kept for reading, not for comparison",
    "shape.shadow_samples": "same",
    "imagery.img_src_sample": "same",
    "layout.buttons": "per-button detail kept for reading; the count is the axis",
    "color.text": "text colours are governed by the WCAG contrast check in the impeccable "
                  "detector, which is a stronger instrument than a count",
    "type.display.leading": "governed by site-design.md section 6 craft specs (120 to 145%), "
                            "which is a cap and not an exemplar-derived range",
    "type.display.width_px": "a consequence of the measure and the viewport, not a choice",
    "type.display.width_pct": "same",
    "type.weights": "a count of weights says nothing without knowing which; the display weight "
                    "is the property that matters and it is governed by the craft manifest",
    "type.display.weight": "declared and fingerprinted per round in craft-manifest.json, which "
                           "is a stronger check than a range: it names the value and proves it "
                           "reached the page",
    "type.display.tracking": "same, declared and fingerprinted in craft-manifest.json",
    "layout.content_measure_px": "governed by standard.max_line_chars, which measures the same "
                                 "property in the unit the canon uses",
    "motion.animated": "design-dna.md section 4 permits exactly one animation and only when it "
                       "reveals the discrepancy. A floor derived from the group would push "
                       "toward more animation, which the canon argues against",
    "imagery.canvas": "a rendering technique rather than a design property; the area axes are "
                      "the thing that matters and they count canvas already",
    "imagery.background_images": "same, counted by the area axes",
}


def load(mod: str):
    spec = importlib.util.spec_from_file_location(mod.replace("-", "_"), HERE / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def leaves(d: dict, prefix: str = "") -> list[str]:
    out = []
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        out += leaves(v, p) if isinstance(v, dict) else [p]
    return out


def _get(d, path):
    cur = d
    for k in path.split("."):
        cur = cur[k]
    return cur


def _set(d, path, val):
    cur = d
    parts = path.split(".")
    for k in parts[:-1]:
        cur = cur[k]
    cur[parts[-1]] = val


def _mutate(v):
    if isinstance(v, list):
        return []
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return 0 if v else 999
    if isinstance(v, str):
        return "MUTATED"
    return None


def readers(capture: dict, axes) -> dict:
    """{property: [axis names that change when it changes]}. Mutation, not name matching."""
    out = {}
    for p in leaves(capture):
        if p.startswith("layout.buttons."):
            p = "layout.buttons"
        if p in out:
            continue
        m = copy.deepcopy(capture)
        try:
            _set(m, p, _mutate(_get(capture, p)))
        except (KeyError, TypeError):
            continue
        movers = []
        for key, _label, fn, floored, _why in axes:
            try:
                if fn(m) != fn(capture):
                    movers.append((key, bool(floored)))
            except Exception:
                pass
        out[p] = movers
    return out


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def audit(refs: Path, cfg_path: Path | None) -> int:
    gap = load("design-gap-check")
    caps = []
    if cfg_path and cfg_path.is_file():
        std = json.loads(cfg_path.read_text()).get("standard", {})
        caps = [k for k in std if k.startswith(("max_", "min_"))]

    captures = [f for f in sorted(refs.glob("*.json")) if f.name != "exemplars.json"]
    if not captures:
        print(f"no exemplar captures in {refs}", file=sys.stderr)
        return 2
    # UNION every capture, never just the first. The first version read captures[0] alone,
    # and its own negative control did not fire: a property added to stripe-com.json went
    # unnoticed because the audit was looking at calendly-com.json. A coverage check that
    # inspects one member of a set is the same class of defect as the checks it exists to
    # catch.
    merged, seen_in = {}, {}
    for f in captures:
        try:
            c = json.loads(f.read_text())["viewports"]["laptop"]
        except (ValueError, KeyError):
            continue
        for k in leaves(c):
            seen_in.setdefault(k, []).append(f.stem)
        merged = _deep_merge(merged, c)
    cap = merged

    r = readers(cap, gap.AXES)
    floored = {p: m for p, m in r.items() if any(f for _, f in m)}
    unfloored = {p: m for p, m in r.items() if m and not any(f for _, f in m)}
    blind = [p for p, m in r.items() if not m]

    print("AXIS COVERAGE, readership established by mutation")
    print(f"basis: the UNION of {len(captures)} captures "
          f"({', '.join(c.stem for c in captures)})\n")
    print(f"  properties measured on every exemplar   {len(r)}")
    print(f"  read by a FLOORED axis                  {len(floored)}")
    print(f"  read by an axis left unfloored, w/ why  {len(unfloored)}")
    print(f"  read by no axis                         {len(blind)}")
    if caps:
        print(f"  (design-chain.json standard also caps: {', '.join(caps)})")

    unexplained = [p for p in blind if p not in NOT_AN_AXIS]
    print("\nread by no axis, and EXPLAINED:")
    for p in sorted(set(blind) - set(unexplained)):
        print(f"  {p:32} {NOT_AN_AXIS[p]}")
    if unexplained:
        print("\nMEASURED AND UNREAD AND UNEXPLAINED. This is the blind spot that cost a round:")
        for p in sorted(unexplained):
            where = seen_in.get(p) or seen_in.get(p.rsplit(".", 1)[0]) or []
            print(f"  {p}" + (f"   (measured on: {', '.join(sorted(set(where)))})" if where else ""))
        print("\nEach needs one of: an axis in design-gap-check.py, a cap in "
              "design-chain.json `standard`, or an entry in NOT_AN_AXIS naming why it cannot "
              "discipline a build. Measuring a thing and reading it nowhere is how seven "
              "rounds drifted while every gate stayed green.")
        return 2
    print("\nevery measured property has a reader or a written reason.")
    print("""
WHAT THIS DOES NOT CHECK: that the axes are the RIGHT axes, that their floors are set
sensibly, or that a page meeting them is any good. It checks that nothing is measured and
silently ignored. A property can have a reader and still be read badly.""")
    return 0


def selftest() -> int:
    gap = load("design-gap-check")
    cap = {"type": {"size_ramp": [14, 16, 32, 48], "display": {"px": 48, "words": 6}},
           "color": {"backgrounds": [1, 2, 3], "gradient_count": 0},
           "motion": {"transitioned": 20, "animated": 0},
           "imagery": {"svg": 6, "img": 0, "video": 0, "background_images": 0,
                       "largest_visual_pct": 40, "visual_area_pct": 60},
           "shape": {"radii": [1, 2], "shadow_count": 0},
           "layout": {"buttons_in_fold": 8}}
    r = readers(cap, gap.AXES)
    assert r["type.display.words"], "the display-words axis must read type.display.words"
    assert any(f for _, f in r["type.display.words"]), "and it must be FLOORED"
    assert r["imagery.largest_visual_pct"], "the area axis must read the area property"
    assert not any(f for _, f in r["imagery.largest_visual_pct"]), \
        "and it must NOT be floored while the probe misses figma's artwork"
    assert not r["motion.animated"], "motion.animated is deliberately unread"
    assert "motion.animated" in NOT_AN_AXIS, "an unread property must carry its reason"
    # a property nobody reads and nobody explains must be reportable
    cap2 = copy.deepcopy(cap)
    cap2["imagery"]["invented_metric"] = 5
    r2 = readers(cap2, gap.AXES)
    assert not r2["imagery.invented_metric"]
    assert "imagery.invented_metric" not in NOT_AN_AXIS
    print("selftest: readership is established by mutation, the new display-words axis is "
          "floored, the area axes are measured and deliberately not, and a property that is "
          "neither read nor explained is detected")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("refs", nargs="?")
    ap.add_argument("--config")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.refs:
        ap.error("refs is required")
    refs = Path(a.refs).resolve()
    cfg = Path(a.config).resolve() if a.config else refs.parents[2] / "design-chain.json"
    return audit(refs, cfg)


if __name__ == "__main__":
    sys.exit(main())
