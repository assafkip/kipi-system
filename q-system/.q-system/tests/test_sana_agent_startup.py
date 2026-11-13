"""RULE-2026-11-13-LEAN: what a sana subagent loads at start-up (ASK-4747 step 3).

The sana agent definition lives under ~/.claude/agents/, out of a test's reach (a
live path). What the repo holds is the decision (`sana-startup.json`) and the
proposal that applies it (`proposals/sana-lean-startup.json`). This test pins the
two together and ratchets the deny list:

- the proposal's frontmatter line is generated from the decision file, never
  hand-edited apart from it (two copies drift; one did in PR #792's numbers);
- the servers builders were measured calling stay allowed;
- the measured deny set may grow, never shrink (a shrink brings back up to
  32k tokens per request, re-read on every request of every build);
- every entry is a server-level spec, because a prefix wildcard was measured to
  remove nothing (109,109 tokens with `mcp__claude_ai_*`, 109,108 without).

The rule_gate reads this file as the enforcer named in sana.md's preamble.
"""
import json
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
DECISION = QS / "sana-startup.json"
PROPOSAL = QS / "proposals" / "sana-lean-startup.json"

# Measured 2026-11-13 over 14 sana build transcripts: 0 calls to each of these.
MEASURED_DENY = {
    "base44", "claude_ai_Anthropic_Economic_Index", "claude_ai_Claude_Docs", "claude_ai_Era_Context",
    "claude_ai_Google_Calendar", "claude_ai_Google_Docs", "claude_ai_Google_Drive",
    "claude_ai_Google_Sheets", "claude_ai_Google_Slides", "claude_ai_Notion", "claude_ai_Resend",
    "claude_ai_Scholar_Gateway", "claude_ai_Slack", "claude_ai_Supabase", "claude_ai_Vercel",
    "claude_ai_Firecrawl", "claude_ai_Canva", "claude_ai_Figma", "claude_ai_Financial_Datasets",
    "claude_ai_Mermaid_Chart", "claude_ai_Replit", "claude_ai_Claude_Academy", "granola", "publer",
    "apify", "supabase", "playwright", "claude-in-chrome", "computer-use", "easel", "google-home",
    "plugin_chrome-devtools-mcp_chrome-devtools", "plugin_kipi-core_kipi",
    "plugin_small-business_shopify", "plugin_context7_context7", "plugin_kipi-notebooklm_notebooklm",
    "plugin_posthog_posthog", "plugin_slack_slack", "plugin_vercel_vercel",
}
# Called by builds: linear 13 of 14 runs, claude_ai_Gmail 1 of 14.
MEASURED_KEEP = {"linear", "claude_ai_Gmail"}


def _decision():
    return json.loads(DECISION.read_text())


def _deny_line():
    edits = json.loads(PROPOSAL.read_text())["edits"]
    lines = [e["insert"] for e in edits if e["insert"].startswith("disallowedTools:")]
    assert len(lines) == 1, "exactly one disallowedTools edit"
    return lines[0]


def test_proposal_line_is_generated_from_the_decision():
    d = _decision()
    want = "disallowedTools: " + ", ".join("mcp__" + s for s in d["deny_mcp_servers"]) + "\n"
    assert _deny_line() == want


def test_builders_servers_stay_allowed():
    d = _decision()
    assert set(d["keep_mcp_servers"]) >= MEASURED_KEEP
    assert not set(d["keep_mcp_servers"]) & set(d["deny_mcp_servers"]), "a server is kept or denied, never both"
    assert all(d["keep_mcp_servers"][s].strip() for s in MEASURED_KEEP), "each kept server says why"


def test_deny_set_only_grows():
    assert set(_decision()["deny_mcp_servers"]) >= MEASURED_DENY


def test_every_entry_is_a_server_level_spec():
    for spec in _deny_line()[len("disallowedTools: "):].strip().split(", "):
        assert spec.startswith("mcp__")
        server = spec[len("mcp__"):]
        assert server and "*" not in server and "__" not in server, spec


def test_proposal_is_additive_and_scoped_to_the_sana_agent():
    p = json.loads(PROPOSAL.read_text())
    assert {e["file"] for e in p["edits"]} == {".claude/agents/sana.md"}
    assert {e["op"] for e in p["edits"]} <= {"insert_after", "insert_before"}
    preamble = [e for e in p["edits"] if "Rule-ID:" in e["insert"]]
    assert preamble and "RULE-2026-11-13-LEAN" in preamble[0]["insert"]
    assert "test_sana_agent_startup.py" in preamble[0]["insert"]
