#!/usr/bin/env python3
"""dc-22: one design command in the menu.

WHY. The founder named /design-chain the one design command (2026-09-18). The other design skills
stay installed as engines the chain calls, and design-engine-door.py refuses them outside a round
(dc-18). They still sat in the slash menu as commands of their own. This pins the menu side: every
in-repo skill the engine registry lists carries `user-invocable: false`, every skill in the design
plugin is in the registry, and both routing rules name the door and its test.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "q-system" / ".q-system" / "scripts"
RULES = (ROOT / ".claude" / "rules" / "design-auto-invoke.md", ROOT / ".claude" / "rules" / "dogfood-gate.md")


def frontmatter(p: Path) -> dict:
    text = p.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep and not line.startswith(" "):
            # YAML says False, 'false' and a trailing comment are the same value
            v = v.split("#")[0].strip().strip("'\"").casefold()
            out[k.strip()] = v
    return out


def engines() -> set:
    names = {e["skill"] for e in json.loads((SCRIPTS / "design-engines.json").read_text())["engines"]}
    assert names, "the registry lists no engines"
    return names


def repo_skills() -> dict:
    out = {}
    for p in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        name = frontmatter(p).get("name") or p.parent.name
        out[name] = p
    assert out, "no in-repo skills found"
    return out


class OneDoorMenu(unittest.TestCase):
    def test_every_listed_in_repo_engine_is_hidden_from_the_menu(self):
        listed = engines()
        ours = {n: p for n, p in repo_skills().items() if n in listed}
        self.assertGreaterEqual(len(ours), 4, ours)          # brand, design, ui-ux-pro-max, deck-ai
        shown = [str(p.relative_to(ROOT)) for p in ours.values()
                 if frontmatter(p).get("user-invocable") != "false"]
        self.assertEqual(shown, [], "a design engine is still a slash command of its own")

    def test_every_design_shaped_skill_in_the_repo_is_a_listed_engine(self):
        # not only kipi-design: deck-ai lives in kipi-core and is an engine. A skill whose name reads
        # as design work must be in the registry, or the door does not know it (review of 566ca38d)
        # unambiguous design-OUTPUT words only: "brand" alone reads as content (linkedin-brand is a
        # writing skill), and the kipi-design clause already covers the brand engine
        words = ("design", "deck", "slide", "motion", "video", "ui", "ux", "logo", "art")
        shaped = {n for n, p in repo_skills().items()
                  if p.parts[-4] == "kipi-design" or any(w in n.casefold().split("-") for w in words)}
        self.assertTrue(shaped)
        self.assertEqual(shaped - engines(), set(), "a design-shaped skill the door does not know")

    def test_both_routing_rules_name_the_door_and_its_test(self):
        for rule in RULES:
            text = rule.read_text()
            self.assertIn("design-engine-door.py", text, rule.name)
            self.assertIn("test_design_engine_door.py", text, rule.name)


if __name__ == "__main__":
    unittest.main()
