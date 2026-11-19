"""RULE-2026-11-18-WRITER-ENTRY: skills and agents that write in his voice call the writer lane (ASK-5359).

Why this exists: the RCA rca-voice-loop-is-not-the-only-route-2026-11-16 counted a
session that drafts text itself as one route around the voice loop. Under
RULE-2026-11-16-V (consulting) every exit refuses a `hand` receipt, so a skill or an
agent that writes the text by hand produces work the exit throws away. The entry
points must send the writing to the lane that mints a lane receipt.

What is pinned, and what is not:
- The agent and skill definitions live under ~/.claude/, a live path a test must not
  read (same stance as test_sana_agent_startup.py). What the repo holds is the two
  proposals that apply the section. This test pins those proposals, the text each one
  inserts, and the repo-resident entry points (the founder-voice skill).
- The `problems()` check has a negative self-test: it must fail on a section that
  drops any one required marker, or the green on the real text proves nothing.
- Not pinned here: that the live ~/.claude files carry the section. That is the
  apply step (apply-claude-changes.sh --root $HOME), whose log names the files.
"""
import json
import re
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
REPO = QS.parents[1]
RULE_ID = "RULE-2026-11-18-WRITER-ENTRY"
PROP_HOME = QS / "proposals" / "writer-lane-entry-home.json"
PROP_REPO = QS / "proposals" / "writer-lane-entry-repo.json"
SELF = "q-system/.q-system/tests/test_writer_lane_entry_points.py"

HOME_FILES = {
    ".claude/agents/ryan.md", ".claude/agents/amber.md", ".claude/agents/cole.md",
    ".claude/skills/assaf-voice/SKILL.md",
}
REPO_FILES = {".claude/agents/engagement-hitlist.md"}
# Entry points that sit in the repo as ordinary files (no .claude/ path).
DIRECT_FILES = [REPO / "plugins/kipi-core/skills/founder-voice/SKILL.md"]

MARKERS = {
    "rule id": f"Rule-ID: {RULE_ID}",
    "enforcer": "Enforced by: ~/projects/kipi-system/" + SELF,
    "social lane": "python3 -m pipeline.social idea",
    "email lane": "python3 -m pipeline.draft_email",
    "hand receipt": "`hand`",
    "waiver": "waive",
    "rule it serves": "RULE-2026-11-16-V",
}


def problems(text):
    """Names every required marker the section lacks. Empty list means it is complete."""
    return [name for name, needle in MARKERS.items() if needle not in text]


def _inserts(path):
    return [e for e in json.loads(path.read_text())["edits"]]


def test_a_section_missing_any_marker_is_caught():
    full = "\n".join(MARKERS.values())
    assert problems(full) == []
    for name, needle in MARKERS.items():
        assert problems(full.replace(needle, "")) == [name], name


def test_home_proposal_covers_exactly_the_user_level_entry_points():
    edits = _inserts(PROP_HOME)
    assert {e["file"] for e in edits} == HOME_FILES


def test_repo_proposal_covers_the_repo_agent():
    assert {e["file"] for e in _inserts(PROP_REPO)} == REPO_FILES


def test_every_proposed_section_is_complete_and_additive():
    for path in (PROP_HOME, PROP_REPO):
        for e in _inserts(path):
            assert e["op"] in ("append", "insert_before"), (path.name, e["file"], e["op"])
            assert problems(e["insert"]) == [], (e["file"], problems(e["insert"]))
            assert re.search(r"^## ", e["insert"], re.M), "rule_gate splits on headings"


def test_assaf_voice_override_sits_under_its_routing_section():
    """The skill's own "Routing first" says everything else is this skill. The override
    goes right after that section's bullets (before the next heading), so the old bullets
    do not fall under the new heading and it is not left at the file's end."""
    e = [e for e in _inserts(PROP_HOME) if e["file"].endswith("assaf-voice/SKILL.md")][0]
    assert e["op"] == "insert_before" and e["anchor"].startswith("## Load at use time")


def test_repo_resident_entry_points_carry_the_section():
    for f in DIRECT_FILES:
        assert problems(f.read_text()) == [], (str(f), problems(f.read_text()))
