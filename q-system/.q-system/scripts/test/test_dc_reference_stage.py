#!/usr/bin/env python3
"""dc-25: the reference stage and the exemplar analysis, held.

Every case builds a throwaway instance in a temp dir; nothing reads a live path. Negative cases
first: each requirement is seen to FAIL before the complete round is seen to pass, and the
complete round is mutated one requirement at a time so a check that cannot fail shows up.
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REF = load("dc25_ref", "design-reference-check.py")
ANA = load("dc25_ana", "design-exemplar-analysis.py")
GATE = load("dc25_gate", "design-chain-gate.py")

ROSTER = {"exemplars": [
    {"url": "https://peer-one.example", "role": "peer", "primary": True},
    {"url": "https://peer-two.example", "role": "peer"},
    {"url": "https://peer-three.example", "role": "peer"},
    {"url": "https://craft.example", "role": "craft"},
]}
TRUST = {"face-photo": [2], "writing": [4], "case-studies": [3]}
BRIEF = ("# Brief\nFeel: calm, precise, forensic.\n"
         "Trust signals: face-photo, case-studies, writing\n")
DIRS = "".join(
    f"## Direction {d}\nPrimary reference: https://peer-one.example\n"
    f"Page path: nav > hero > case-studies > about-person > writing > footer\n\n" for d in "ABC")
CRITIQUE = "".join(f"SIDE-BY-SIDE: Direction {d} vs peer-one.example: AS GOOD. Holds the rhythm.\n"
                   for d in "ABC")
VISION = '**Feel (founder, 2026-10-09):** "calm, precise, forensic"\n'


class Instance:
    """A temp instance: design-chain.json, a roster, its analysis, VISION.md, one round."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="dc25-"))
        self.refs = self.root / "design" / "references"
        self.refs.mkdir(parents=True)
        self.rd = self.root / "design" / "2026-10-10"
        self.rd.mkdir()
        self.cfg = {"references": {"roster": "design/references/exemplars.json",
                                   "vision": "design/VISION.md", "since": "2026-10-10"}}
        self.cfg_path = self.root / "design-chain.json"
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.write_roster(ROSTER)
        self.write_analysis()
        (self.root / "design" / "VISION.md").write_text(VISION)
        for name, text in (("brief.md", BRIEF), ("directions.md", DIRS), ("critique.md", CRITIQUE)):
            (self.rd / name).write_text(text)

    def write_roster(self, data):
        (self.refs / "exemplars.json").write_text(json.dumps(data))

    def write_analysis(self, **over):
        roster = self.refs / "exemplars.json"
        sites = {}
        for e in json.loads(roster.read_text())["exemplars"]:
            sites[REF.host_of(e["url"])] = {"url": e["url"], "role": e.get("role"), "page_path": ["nav", "hero"],
                                            "trust_signals": TRUST if e.get("role") == "peer" else {}}
        data = {"roster_sha256": hashlib.sha256(roster.read_bytes()).hexdigest(),
                "section_kinds": list(ANA.SECTION_KINDS), "trust_kinds": list(ANA.TRUST_KINDS),
                "sites": sites}
        data.update(over)
        (self.refs / "ANALYSIS.json").write_text(json.dumps(data))

    def problems(self, need=3):
        return REF.reference_problems(self.rd, self.cfg, self.cfg_path, need)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class ReferenceStage(unittest.TestCase):
    def setUp(self):
        self.i = Instance()

    def tearDown(self):
        self.i.close()

    def has(self, needle):
        probs = self.i.problems()
        self.assertTrue(any(needle in p for p in probs), f"expected {needle!r} in {probs}")

    # ---- negatives, one requirement at a time

    def test_a_craft_only_set_fails(self):
        self.i.write_roster({"exemplars": [{"url": "https://craft.example", "role": "craft", "primary": True}]})
        self.i.write_analysis()
        self.has("peer exemplar(s); 3 required")

    def test_an_exemplar_with_no_role_fails(self):
        r = json.loads(json.dumps(ROSTER))
        del r["exemplars"][1]["role"]
        self.i.write_roster(r)
        self.i.write_analysis()
        self.has('carries "role"')

    def test_no_primary_fails(self):
        r = json.loads(json.dumps(ROSTER))
        r["exemplars"][0]["primary"] = False
        self.i.write_roster(r)
        self.i.write_analysis()
        self.has('"primary": true; exactly one')

    def test_a_craft_primary_fails(self):
        r = json.loads(json.dumps(ROSTER))
        r["exemplars"][0]["primary"] = False
        r["exemplars"][3]["primary"] = True
        self.i.write_roster(r)
        self.i.write_analysis()
        self.has("is not a peer")

    def test_missing_analysis_fails(self):
        (self.i.refs / "ANALYSIS.json").unlink()
        self.has("run design-exemplar-analysis.py")

    def test_an_analysis_older_than_the_roster_fails(self):
        r = json.loads(json.dumps(ROSTER))
        r["exemplars"][1]["note"] = "edited after the analysis ran"
        self.i.write_roster(r)
        self.has("is stale")

    def test_a_failed_site_fails(self):
        a = json.loads((self.i.refs / "ANALYSIS.json").read_text())
        a["sites"]["peer-two.example"] = {"error": "timeout"}
        (self.i.refs / "ANALYSIS.json").write_text(json.dumps(a))
        self.has("failed to analyse")

    def test_no_feel_line_fails(self):
        (self.i.root / "design" / "VISION.md").write_text("no feel here\n")
        self.has("has no line '**Feel")

    def test_a_two_word_feel_fails(self):
        (self.i.root / "design" / "VISION.md").write_text('**Feel (founder, 2026-10-09):** "calm, precise"\n')
        self.has("exactly 3")

    def test_a_brief_without_the_feel_fails(self):
        (self.i.rd / "brief.md").write_text("Trust signals: face-photo, writing\n")
        self.has("does not carry the feel")

    def test_a_direction_without_a_primary_fails(self):
        (self.i.rd / "directions.md").write_text(DIRS.replace("Primary reference: https://peer-one.example\n", "", 1))
        self.has("'Primary reference:' line(s)")

    def test_a_craft_site_as_primary_reference_fails(self):
        (self.i.rd / "directions.md").write_text(DIRS.replace("peer-one.example", "craft.example", 1))
        self.has("a craft site")

    def test_a_missing_page_path_fails(self):
        (self.i.rd / "directions.md").write_text(DIRS.replace("Page path:", "Path:", 1))
        self.has("'Page path:' line(s)")

    def test_a_page_path_outside_the_taxonomy_fails(self):
        (self.i.rd / "directions.md").write_text(DIRS.replace("about-person", "vibes", 1))
        self.has("not section kinds")

    def test_a_short_page_path_fails(self):
        (self.i.rd / "directions.md").write_text(DIRS.replace(
            "nav > hero > case-studies > about-person > writing > footer", "hero > footer", 1))
        self.has("at least 4")

    def test_no_trust_signals_fails(self):
        (self.i.rd / "brief.md").write_text("calm, precise, forensic\n")
        self.has("no 'Trust signals:' line")

    def test_a_trust_signal_no_peer_shows_fails(self):
        (self.i.rd / "brief.md").write_text(BRIEF.replace("writing", "certifications"))
        self.has("which no peer exemplar shows")

    def test_a_missing_side_by_side_fails(self):
        (self.i.rd / "critique.md").write_text(CRITIQUE.splitlines()[0] + "\n")
        self.has("'SIDE-BY-SIDE")

    def test_not_as_good_blocks(self):
        (self.i.rd / "critique.md").write_text(CRITIQUE.replace("AS GOOD", "NOT AS GOOD", 1))
        self.has("is NOT AS GOOD")

    # ---- the positive control, then scope

    def test_the_complete_round_passes(self):
        self.assertEqual(self.i.problems(), [])

    def test_a_round_dated_before_since_is_not_held(self):
        old = self.i.root / "design" / "2026-10-09"
        old.mkdir()
        self.assertEqual(REF.reference_problems(old, self.i.cfg, self.i.cfg_path, 3), [])

    def test_an_instance_without_the_block_is_not_held(self):
        self.assertEqual(REF.reference_problems(self.i.rd, {}, self.i.cfg_path, 3), [])

    def test_the_gate_wrapper_reaches_the_checker(self):
        (self.i.rd / "critique.md").write_text("")
        probs = GATE.reference_problems(self.i.rd, self.i.cfg, self.i.cfg_path, 3)
        self.assertTrue(any("SIDE-BY-SIDE" in p for p in probs), probs)
        self.assertEqual(GATE.reference_problems(self.i.rd, {}, self.i.cfg_path, 3), [])


class Analysis(unittest.TestCase):
    """The classifier, on raw features shaped like the probe's output. No browser."""

    def sec(self, **kw):
        base = {"tag": "section", "hint": "", "top": 2000, "height": 600, "text": "", "words": 80,
                "links": 1, "buttons": 0, "headings_h1": 0, "forms": 0, "inputs": 0, "blockquotes": 0,
                "big_numbers": 0, "logo_row": 0, "portrait": 0}
        base.update(kw)
        return base

    def test_the_first_block_under_the_nav_is_the_hero(self):
        raw = {"sections": [self.sec(tag="nav", top=0, height=80, links=6),
                            self.sec(top=80, height=700, text="We find what breaks"),
                            self.sec(tag="footer", links=12)], "page": {}}
        self.assertEqual(ANA.analyse(raw, "peer")["page_path"], ["nav", "hero", "footer"])

    def test_section_kinds_are_recognised(self):
        cases = [
            (self.sec(logo_row=6, words=10), "logo-wall"),
            (self.sec(blockquotes=2), "testimonials"),
            (self.sec(text="Selected work and case studies"), "case-studies"),
            (self.sec(big_numbers=3, text="200+ clients 12 years"), "stats"),
            (self.sec(forms=1, inputs=3), "contact-form"),
            (self.sec(portrait=1, text="About me"), "about-person"),
            (self.sec(text="Latest writing from the blog"), "writing"),
            (self.sec(height=300, buttons=1, words=12, text="Book a call"), "cta-band"),
        ]
        for f, want in cases:
            self.assertEqual(ANA.classify_section(f, 3, 9), want, f)

    def test_a_wordy_block_with_logos_is_not_a_logo_wall(self):
        self.assertNotEqual(ANA.classify_section(self.sec(logo_row=8, words=500), 3, 9), "logo-wall")

    def test_technologies_are_detected_from_signals_and_headers(self):
        t = ANA.detect_technologies(
            '<script id="__NEXT_DATA__"></script> https://www.googletagmanager.com/gtag/js gsap',
            ["px-4 py-2 text-sm", "max-w-7xl mx-auto", "grid-cols-3 gap-6", "plain"],
            {"x-vercel-id": "sfo1::abc"}, ["Inter"])
        self.assertIn("Next.js", t["framework"])
        self.assertNotIn("React", t.get("framework", []))
        self.assertIn("Tailwind", t["css"])
        self.assertIn("GSAP", t["animation"])
        self.assertIn("Google Analytics", t["analytics"])
        self.assertIn("Vercel", t["hosting"])
        self.assertIn("self-hosted", t["fonts"])

    def test_no_signals_means_no_technologies(self):
        self.assertEqual(ANA.detect_technologies("", [], {}, []), {})

    def test_trust_signals_come_from_sections_and_text(self):
        secs = [{"kind": "logo-wall"}, {"kind": "about-person", "portrait": 1},
                {"kind": "case-studies"}, {"kind": "content", "big_numbers": 3}]
        t = ANA.trust_signals(secs, "Formerly at Google. SOC 2 certified. Featured in Wired.")
        for k in ("client-logos", "face-photo", "case-studies", "numbers", "credentials",
                  "certifications", "press-awards"):
            self.assertIn(k, t)
        self.assertEqual(ANA.trust_signals([], ""), {})

    def test_every_kind_the_classifier_emits_is_in_the_vocabulary(self):
        self.assertTrue(set(ANA.SECTION_KINDS) >= {
            "nav", "hero", "footer", "logo-wall", "testimonials", "case-studies", "stats",
            "contact-form", "about-person", "writing", "cta-band", "content"})

    def test_synthesis_counts_sites_per_role(self):
        site = lambda role, path: {"role": role, "page_path": path, "trust_signals": {"writing": [1]},
                                   "technologies": {"framework": ["Astro"]},
                                   "taxonomy": {"hero_archetype": "text-only", "sections": len(path),
                                                "page_screens": 4.0},
                                   "techniques": {"sticky_nav": True}}
        syn = ANA.synthesis({"a": site("peer", ["nav", "hero", "hero"]), "b": site("peer", ["nav"]),
                             "c": {"role": "peer", "error": "x"}})
        self.assertEqual(syn["peer"]["n"], 2)
        self.assertEqual(syn["peer"]["section_kinds"]["hero"], 1)
        self.assertNotIn("craft", syn)


class GapFloorsFromThePrimary(unittest.TestCase):
    """design-gap-check.py: with a primary declared, the floors are that one site's (dc-25)."""

    def setUp(self):
        self.gap = load("dc25_gap", "design-gap-check.py")
        self.refs = Path(tempfile.mkdtemp(prefix="dc25-gap-"))
        self.ex = {"latacora-com": {"a": 1}, "stripe-com": {"a": 9}, "figma-com": {"a": 5}}

    def tearDown(self):
        shutil.rmtree(self.refs, ignore_errors=True)

    def roster(self, items):
        (self.refs / "exemplars.json").write_text(json.dumps({"exemplars": items}))

    def test_no_primary_keeps_the_whole_set(self):
        self.roster([{"url": "https://latacora.com"}, {"url": "https://stripe.com"}])
        self.assertEqual(self.gap.primary_only(self.ex, self.refs), (self.ex, None))

    def test_a_primary_floors_against_that_site_only(self):
        self.roster([{"url": "https://latacora.com", "primary": True}, {"url": "https://stripe.com"}])
        self.assertEqual(self.gap.primary_only(self.ex, self.refs),
                         ({"latacora-com": {"a": 1}}, "latacora-com"))

    def test_a_primary_without_a_capture_returns_nothing_to_floor_against(self):
        self.roster([{"url": "https://hamel.dev", "primary": True}])
        self.assertEqual(self.gap.primary_only(self.ex, self.refs), ({}, "hamel-dev"))

    def test_two_primaries_are_not_a_primary(self):
        self.roster([{"url": "https://latacora.com", "primary": True},
                     {"url": "https://stripe.com", "primary": True}])
        self.assertEqual(self.gap.primary_only(self.ex, self.refs)[1], None)

    def test_a_missing_roster_keeps_the_whole_set(self):
        self.assertEqual(self.gap.primary_only(self.ex, self.refs), (self.ex, None))


if __name__ == "__main__":
    unittest.main()
