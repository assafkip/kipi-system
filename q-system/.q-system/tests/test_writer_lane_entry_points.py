"""RULE-2026-11-18-WRITER-ENTRY: skills and agents that write in his voice call the writer lane (ASK-5359).

Why this exists: the RCA rca-voice-loop-is-not-the-only-route-2026-11-16 counted a
session that drafts text itself as one route around the voice loop. Under
RULE-2026-11-16-V (consulting) every exit refuses a `hand` receipt, so a skill or an
agent that writes the text by hand produces work the exit throws away. The entry
points must send the writing to the lane that mints a lane receipt.

What is pinned, and what is not:
- ONE canonical section (config/writer-lane-entry-section.md). Every copy, in every
  proposal and every repo file, must equal it byte for byte. Why: rule_gate treats a
  second, different body under one Rule-ID as a second owner and strips it (the
  2026-11-18 loop, ASK-5448), and three hand-kept copies drift.
- The repo-resident roster is DERIVED, not listed: any skill, command or agent in the
  repo whose description says it drafts text for a post, email, comment, DM or headline,
  or whose body promises copy-paste-ready text, must carry the section, unless
  DISPOSED names it with a reason. A new drafting skill fails here until it does.
  (PR #858 round 1: a one-file roster and an equality pin let linkedin-brand stay open.)
- The section must be a real section: its heading present, its markers inside its own
  body. A whole-file substring match let the section be deleted and the needles hide
  in a comment (PR #858 round 1, minor).
- The agent and skill definitions under ~/.claude/ are a live path a test must not read
  (same stance as test_sana_agent_startup.py). The repo holds the proposals that apply
  the section; this test pins those. Whether the live files carry it is the apply
  step's log (apply-claude-changes.sh --root $HOME).
- Negative self-tests: dropping any marker, deleting the section, or changing one word
  of a copy must fail.
"""
import json
import re
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
REPO = QS.parents[1]
RULE_ID = "RULE-2026-11-18-WRITER-ENTRY"
CANON = (QS / "config" / "writer-lane-entry-section.md").read_text()
HEADING = CANON.splitlines()[0]
PROP_HOME = QS / "proposals" / "writer-lane-entry-home.json"
PROP_REPO = QS / "proposals" / "writer-lane-entry-repo.json"
SELF = "q-system/.q-system/tests/test_writer_lane_entry_points.py"

HOME_FILES = {
    ".claude/agents/ryan.md", ".claude/agents/amber.md", ".claude/agents/cole.md",
    ".claude/skills/assaf-voice/SKILL.md",
}

MARKERS = {
    "rule id": f"Rule-ID: {RULE_ID}",
    "enforcer": "Enforced by: ~/projects/kipi-system/" + SELF,
    "social lane": "python3 -m pipeline.social idea",
    "email lane": "python3 -m pipeline.draft_email",
    "hand receipt": "`hand`",
    "waiver": "pipeline.writer_provenance waive",
    "rule it serves": "RULE-2026-11-16-V",
}

# Repo files the derived roster flags that do not draft text for him. Each needs a reason.
DISPOSED = {
    "plugins/kipi-core/commands/voice-review.md":
        "reviews one draft and writes none (renamed from voice-loop in ASK-5359)",
    ".claude/agents/data-ingest.md": "pulls calendar, mail and Notion data; writes no copy",
    "plugins/kipi-core/skills/improve/SKILL.md":
        "critiques an outside idea against this system; its output is analysis, not copy",
}

DRAFTS_DESC = re.compile(r"\b(draft|drafting|write|writing|compose|reply|replies)\b", re.I)
DRAFTS_FOR = re.compile(r"\b(post|email|dm|dms|comment|reply|headline|tweet|social|linkedin"
                        r"|outreach)\b", re.I)
PROMISES_COPY = re.compile(r"copy-paste ready|ready-to-post|ready to post|ready-to-paste", re.I)
ALWAYS = ["plugins/kipi-core/skills/founder-voice/SKILL.md"]


def section(text):
    """The canonical section as it sits in `text`: from its heading to the next ## heading."""
    i = text.find(HEADING)
    if i < 0:
        return None
    rest = text[i + len(HEADING):]
    j = re.search(r"^## ", rest, re.M)
    return text[i: i + len(HEADING) + (j.start() if j else len(rest))]


def problems(text):
    """Empty when `text` holds the section, complete, and equal to the canonical one."""
    sec = section(text)
    if sec is None:
        return ["no section"]
    out = [name for name, needle in MARKERS.items() if needle not in sec]
    if not out and sec.strip() != CANON.strip():
        out.append("section differs from the canonical one")
    return out


def roster():
    """Repo files whose own text says they draft text for a reader."""
    out = set(ALWAYS)
    files = (list(REPO.glob("plugins/*/skills/*/SKILL.md")) + list(REPO.glob(".claude/agents/*.md"))
             + list(REPO.glob("plugins/*/commands/*.md")))
    for f in files:
        text = f.read_text()
        m = re.search(r"^description:\s*(.*)$", text, re.M)
        desc = m.group(1) if m else ""
        if (DRAFTS_DESC.search(desc) and DRAFTS_FOR.search(desc)) or PROMISES_COPY.search(text):
            out.add(str(f.relative_to(REPO)))
    return sorted(out)


def test_the_canonical_section_is_complete():
    assert problems(CANON) == []


def test_a_section_missing_a_marker_is_caught():
    for name, needle in MARKERS.items():
        broken = CANON.replace(needle, "", 1)
        assert problems(broken) == [name], name


def test_a_deleted_section_or_a_comment_with_the_needles_is_caught():
    assert problems("# Skill\n\nnothing here\n") == ["no section"]
    hidden = "# Skill\n\n<!-- historical, ignore; draft it yourself\n" + "\n".join(MARKERS.values()) + " -->\n"
    assert problems(hidden) == ["no section"]
    # needles that sit AFTER the next heading are outside the section
    moved = HEADING + "\n\nbody\n\n## Other\n\n" + "\n".join(MARKERS.values()) + "\n"
    assert problems(moved) != []


def test_one_changed_word_in_a_copy_is_caught():
    assert problems(CANON.replace("never draft it", "sometimes draft it")) != []
    assert problems(CANON.replace("Do not edit it", "Edit it")) == ["section differs from the canonical one"]


def _inserts(path):
    return json.loads(path.read_text())["edits"]


def test_home_proposal_covers_at_least_the_user_level_entry_points():
    # superset, not equality: widening coverage must never turn this red (PR #858 round 1)
    assert {e["file"] for e in _inserts(PROP_HOME)} >= HOME_FILES


def test_repo_proposal_covers_the_hitlist_agent():
    assert {e["file"] for e in _inserts(PROP_REPO)} >= {".claude/agents/engagement-hitlist.md"}


def test_every_proposed_section_equals_the_canonical_one_and_is_additive():
    for path in (PROP_HOME, PROP_REPO):
        for e in _inserts(path):
            assert e["op"] in ("append", "insert_before"), (path.name, e["file"], e["op"])
            assert problems(e["insert"]) == [], (e["file"], problems(e["insert"]))


def test_assaf_voice_section_sits_before_its_load_section():
    """The skill's own "Routing first" says everything else is this skill. The canonical
    section goes right after that section's bullets, so the old bullets do not fall under
    the new heading and it is not left at the file's end under the contradiction."""
    e = [e for e in _inserts(PROP_HOME) if e["file"].endswith("assaf-voice/SKILL.md")][0]
    assert e["op"] == "insert_before" and e["anchor"].startswith("## Load at use time")


def test_every_derived_roster_file_carries_the_section_or_a_disposition():
    found = []
    # A .claude/ file is edited only through a proposal, so a proposal that targets it counts
    # (test_every_proposed_section_equals_the_canonical_one checks that proposal's text).
    proposed = {e["file"] for p in (PROP_HOME, PROP_REPO) for e in _inserts(p)}
    for rel in roster():
        if rel in DISPOSED or rel in proposed:
            continue
        probs = problems((REPO / rel).read_text())
        if probs:
            found.append((rel, probs))
    assert found == [], found


def test_the_roster_derivation_can_find_a_new_drafting_skill(tmp_path, monkeypatch):
    """Negative self-test: a skill that drafts a LinkedIn post and has no section is flagged."""
    skill = tmp_path / "plugins" / "x" / "skills" / "new" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: new\ndescription: Draft a LinkedIn post in the founder's voice\n---\nbody\n")
    monkeypatch.setattr(__import__(__name__), "REPO", tmp_path, raising=False)
    import sys
    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "REPO", tmp_path)
    assert "plugins/x/skills/new/SKILL.md" in roster()
    assert problems(skill.read_text()) == ["no section"]


def test_every_disposition_names_a_real_file_and_a_reason():
    for rel, why in DISPOSED.items():
        assert (REPO / rel).is_file(), rel
        assert len(why) > 20, rel
