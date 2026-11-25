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
    # The pinned dispatch checkout, not the shared one (2026-11-25). Why: rule_gate requires the
    # enforcer to exist on disk, and the shared checkout ~/projects/kipi-system sat ahead 3 and
    # behind 31 of origin/main, so lessons-daily refused its fast-forward and this test never
    # reached it: the home proposal could not be applied without rule_gate reverting it.
    # kipi-dispatch-pinned.sh advances the pinned checkout in place on every run.
    "enforcer": "Enforced by: ~/.local/state/kipi/dispatch/kipi-system/" + SELF,
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


# --- explicit tool lists (inventory rows AG-amber, AG-cole, AG-ryan; 2026-11-25) -------------
# Why: an agent with no tools: line inherits every tool, so the writer-lane section above was
# prose standing between the agent and every sender it could reach. amber.md carried an
# allowed-tools: line, which is a skill key: the agent roster still listed her as "All tools".
# Measured 2026-11-25 with a probe agent: `tools: Read, mcp__linear` gave Read plus the linear
# server's tools and nothing else, so a server-level name works in an agent's tools: line.
# A RAW sender here is a tool that puts text in front of another person and that neither
# agent's job needs. The senders these two keep (Gmail drafts, the Chrome extension) sit inside
# the user-level outbound matcher (consulting automation/outbound_gate.py), which refuses text
# with no lane receipt.
# Ryan is ruled out of this list on purpose: the founder gave him research reach on 2026-10-07
# ("I want Ryan to do this research"), RULE-2026-11-17-LEAN-INVESTIGATORS pins which servers
# he keeps, and every sender he can reach is inside that same outbound matcher.
PROP_TOOLS = QS / "proposals" / "writer-lane-agent-tools.json"
TOOLS_AGENTS = {".claude/agents/amber.md", ".claude/agents/cole.md"}
RAW_SEND = ("mcp__publer", "mcp__claude_ai_Resend", "mcp__claude_ai_Slack", "mcp__plugin_slack_slack",
            "mcp__computer-use", "mcp__base44", "mcp__claude_ai_Google_Docs", "mcp__claude_ai_Notion",
            # both Notion servers write pages another person reads (PR #877 round 2, minor)
            "mcp__notion_api")


# A closed list silently drops a misspelled name (PR #877 round 1, minor): every name must be a
# built-in tool or a server this machine connects. Measured 2026-11-25 (the session's MCP list).
BUILTIN = {"Read", "Grep", "Glob", "Write", "Edit", "MultiEdit", "Bash", "Skill", "WebSearch",
           "WebFetch", "TodoWrite", "Agent", "NotebookEdit"}
KNOWN_SERVERS = {"linear", "ask-crm", "reddit", "claude_ai_Gmail", "claude-in-chrome",
                 "plugin_posthog_posthog", "infohawk", "miyo", "notebooklm", "notion_api",
                 "osint-infra", "perplexity-ask", "threat-intel"}


def _known(name):
    base = name.split("(", 1)[0]
    if base in BUILTIN:
        return True
    if base.startswith("mcp__"):
        return base[len("mcp__"):].split("__", 1)[0] in KNOWN_SERVERS
    return False


def tool_problems(insert):
    lines = [ln for ln in insert.splitlines() if ln.startswith("tools:")]
    if len(lines) != 1:
        return ["no single tools: line"]
    names = [n.strip() for n in lines[0][len("tools:"):].split(",") if n.strip()]
    out = ["raw sender " + n for n in names if any(n == r or n.startswith(r + "__") for r in RAW_SEND)]
    # A scoped pattern such as Bash(python3:*) narrows reach and is fine (round 1, minor);
    # only a bare wildcard, or one inside a tool name, widens it.
    out += ["wildcard " + n for n in names if "*" in n.split("(", 1)[0]]
    out += ["unknown tool " + n for n in names
            if "*" not in n.split("(", 1)[0] and not _known(n)
            and not any(n == r or n.startswith(r + "__") for r in RAW_SEND)]
    base = {n.split("(", 1)[0] for n in names}
    if "Bash" not in base or "Read" not in base:
        out.append("no Bash or Read: the agent cannot run the writer lane")
    return out


def test_amber_and_cole_get_an_explicit_tool_list_without_raw_senders():
    edits = {e["file"]: e for e in _inserts(PROP_TOOLS)}
    assert set(edits) == TOOLS_AGENTS
    for f, e in edits.items():
        assert tool_problems(e["insert"]) == [], (f, tool_problems(e["insert"]))


def test_a_raw_sender_or_a_missing_list_is_caught():
    assert tool_problems("tools: Read, Bash, mcp__publer\n") == ["raw sender mcp__publer"]
    assert tool_problems("tools: Read, Bash, mcp__claude_ai_Slack__slack_send_message\n") != []
    assert tool_problems("model: opus\n") == ["no single tools: line"]
    assert tool_problems("tools: Read, Bash, *\n") == ["wildcard *"]
    assert tool_problems("tools: Read, Bash(python3:*)\n") == []
    assert tool_problems("tools: Read, Bash, mcp__lineer\n") == ["unknown tool mcp__lineer"]
    assert tool_problems("tools: Read, Bash, Raed\n") == ["unknown tool Raed"]


def test_amber_gets_tools_after_her_inert_skill_key():
    e = [e for e in _inserts(PROP_TOOLS) if e["file"].endswith("amber.md")][0]
    # replace is refused outside .claude/rules, so the tools: line goes right after the inert key
    assert e["op"] == "insert_after" and e["anchor"].startswith("allowed-tools:")


def test_ryan_is_not_narrowed_here():
    assert ".claude/agents/ryan.md" not in {e["file"] for e in _inserts(PROP_TOOLS)}
