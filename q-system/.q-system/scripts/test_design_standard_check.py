"""Tests for design-standard-check.py's hero alignment rule (ASK-1743).

Founder, 2026-09-15: left-aligned everything reads as slop. Founder, 2026-09-16, on round
16d: "the text is again on lined on the left". The first note lived in a critique and
drifted back within a day, so it is a measured rule now, read from design-chain.json
`standard.hero_align`.
"""
import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dsc", HERE / "design-standard-check.py")
dsc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dsc)

BASE = {"type_sizes": [16, 64], "large_elements": 1, "words": 20, "min_body_px": 16,
        "max_line_chars": 40, "signal_elements": 0}

PAGE = """<!doctype html><html><head><style>
body{margin:0;font:16px sans-serif} main{max-width:1180px;margin:0 auto;padding:40px}
h1{font-size:64px;%s} p{%s}
</style></head><body><main><h1>Eight hours, billed as two.</h1>
<p>A line of body copy under the headline.</p></main></body></html>"""


def cfg(**kw):
    c = dict(dsc.DEFAULTS)
    c.update(kw)
    return c


class JudgeHeroAlign(unittest.TestCase):
    def test_no_rule_no_finding(self):
        m = dict(BASE, hero={"text_align": "left", "offset_pct": 30.0})
        self.assertEqual(dsc.judge(m, cfg()), [])

    def test_left_headline_fails_when_center_required(self):
        m = dict(BASE, hero={"text_align": "left", "offset_pct": 30.0})
        f = dsc.judge(m, cfg(hero_align="center"))
        self.assertEqual(len(f), 1)
        self.assertIn("headline", f[0])

    def test_centered_headline_passes(self):
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 0.4})
        self.assertEqual(dsc.judge(m, cfg(hero_align="center")), [])

    def test_centered_text_in_an_offset_column_fails(self):
        # text-align:center inside a left-hand column is still a left-hand headline
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 22.0})
        self.assertEqual(len(dsc.judge(m, cfg(hero_align="center"))), 1)

    def test_no_headline_in_view_fails_closed(self):
        m = dict(BASE, hero=None)
        f = dsc.judge(m, cfg(hero_align="center"))
        self.assertEqual(len(f), 1)
        self.assertIn("no headline", f[0])


class JudgeHeroCluster(unittest.TestCase):
    """Founder 2026-09-16: "the text kind of bunches up in the middle, wrapped, and it looks
    like a block of text". Measured on the five exemplars the same day: the most text any of
    them puts around the headline is calendly's 2 pieces, 18 words, 3 lines."""
    CAPS = dict(max_hero_pieces=2, max_hero_words=18, max_hero_lines=3)

    def test_no_caps_no_finding(self):
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 0.0, "pieces": 4, "words": 43, "lines": 6})
        self.assertEqual(dsc.judge(m, cfg()), [])

    def test_block_fails(self):
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 0.0, "pieces": 4, "words": 43, "lines": 6})
        f = dsc.judge(m, cfg(**self.CAPS))
        self.assertEqual(len(f), 1)
        self.assertIn("block", f[0])

    def test_calendly_amount_passes(self):
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 0.0, "pieces": 2, "words": 18, "lines": 3})
        self.assertEqual(dsc.judge(m, cfg(**self.CAPS)), [])

    def test_one_long_wrapped_piece_fails_on_lines(self):
        m = dict(BASE, hero={"text_align": "center", "offset_pct": 0.0, "pieces": 1, "words": 17, "lines": 4})
        self.assertEqual(len(dsc.judge(m, cfg(**self.CAPS))), 1)


class MeasureHeroAlign(unittest.TestCase):
    """Runs the real browser probe on two pages that differ only in alignment."""

    def _measure(self, h1_css, p_css):
        d = pathlib.Path(tempfile.mkdtemp())
        page = d / "p.html"
        page.write_text(PAGE % (h1_css, p_css))
        return dsc.measure(page.as_uri(), cfg(viewports=[[1440, 900], [390, 844]]))

    def test_left_page_is_measured_left(self):
        for m in self._measure("", ""):
            c = cfg(hero_align="center")
            self.assertTrue(dsc.judge(m, c), m["viewport"])

    def test_cluster_is_counted_on_a_real_page(self):
        d = pathlib.Path(tempfile.mkdtemp())
        page = d / "p.html"
        page.write_text(PAGE.replace("<p>A line of body copy under the headline.</p>",
            "<p>A line of body copy under the headline.</p><p>And a second line of body copy here.</p>"
            "<p>And a third one, which makes the block.</p>") % ("text-align:center", "text-align:center"))
        m = dsc.measure(page.as_uri(), cfg(viewports=[[1440, 900]]))[0]
        self.assertEqual(m["hero"]["pieces"], 3, m["hero"])
        self.assertEqual(m["hero"]["words"], 24, m["hero"])
        self.assertTrue(dsc.judge(m, cfg(**JudgeHeroCluster.CAPS)))

    def test_text_inside_a_figure_is_not_the_block(self):
        # a drawing's labels are part of the picture, not prose stacked under the headline
        d = pathlib.Path(tempfile.mkdtemp())
        page = d / "p.html"
        page.write_text(PAGE.replace("<p>A line of body copy under the headline.</p>",
            "<figure><p>Where the hours leak</p><p>The records behind it</p><p>The build that stops it</p></figure>")
            % ("text-align:center", "text-align:center"))
        m = dsc.measure(page.as_uri(), cfg(viewports=[[1440, 900]]))[0]
        self.assertEqual(m["hero"]["pieces"], 0, m["hero"])

    def test_centered_page_is_measured_centered(self):
        for m in self._measure("text-align:center", "text-align:center"):
            self.assertEqual(dsc.judge(m, cfg(hero_align="center")), [], m)


if __name__ == "__main__":
    unittest.main()
