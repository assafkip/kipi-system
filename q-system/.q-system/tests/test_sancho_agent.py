"""RULE-2026-11-14-SANCHO and RULE-2026-11-14-SANCHO-BODY: the sancho agent's guardrails.

Founder, 2026-11-14: build a fleet-wide subagent "sancho", a skeptical senior malware
analyst doing QC on defensive research and attribution, with hard out-of-scope lines.

The live definition sits at ~/.claude/agents/sancho.md, a live path no test reads.
The repo holds the source copy (`agent-defs/sancho.md`) that is installed byte for
byte. This test pins the parts that must never drift out of that copy: the model,
the four out-of-scope lines, the claim tags, the output shape, and the house text
rules (no emdash, no double hyphen, no table). The rule_gate reads this file as the
enforcer named in sancho.md.
"""
import re
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
AGENT = QS / "agent-defs" / "sancho.md"

OUT_OF_SCOPE = (
    "Writing, modifying, improving or repackaging malicious code.",
    "Advice that helps malware evade detection or analysis.",
    "Running, detonating or emulating samples.",
    "Contacting suspects, victims or attacker infrastructure.",
)


def _text():
    return AGENT.read_text()


def _frontmatter():
    m = re.match(r"^---\n(.*?)\n---\n", _text(), re.S)
    assert m, "frontmatter block"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


def test_name_and_model():
    fm = _frontmatter()
    assert fm["name"] == "sancho"
    assert fm["model"] == "claude-sonnet-5"
    assert fm["description"].strip()


def test_every_out_of_scope_line_is_present():
    t = _text()
    assert "### Out of scope, always" in t
    for line in OUT_OF_SCOPE:
        assert line in t, line


def test_passive_and_no_upload_rules():
    t = _text()
    assert "python3 -I" in t
    assert "No public uploads" in t
    assert "One shared indicator is a lead, not an identity." in t


def test_claim_tags_and_output_shape():
    t = _text()
    assert '"[seen]"' in t and '"[assessed]"' in t and '"carried over"' in t
    order = ["**What holds**", "**What is wrong or overstated**", "**What is unproven**", "**Recommended next step**"]
    pos = [t.index(s) for s in order]
    assert pos == sorted(pos), "output sections in order"
    assert t.rstrip().endswith('End with one line: "My call: X".')


def test_house_text_rules():
    t = _text()
    assert "—" not in t, "no emdash"
    assert "--" not in t.replace("\n---\n", "\n").lstrip("-"), "no double hyphen"
    assert not re.search(r"^\s*\|.*\|\s*$", t, re.M), "no table"


def test_each_rule_section_carries_its_own_id():
    # rule_gate splits on '# ' and '## ' headings; each section needs a unique Rule-ID.
    t = _text()
    assert re.findall(r"^#{1,2} ", t, re.M) == ["# "], "one top-level section; subheads use ###"
    ids = re.findall(r"^Rule-ID: (\S+)$", t, re.M)
    assert ids == ["RULE-2026-11-14-SANCHO", "RULE-2026-11-14-SANCHO-BODY"]
