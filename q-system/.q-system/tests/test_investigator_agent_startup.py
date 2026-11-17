"""RULE-2026-11-17-LEAN-INVESTIGATORS: which MCP servers sancho and ryan load at start-up (ASK-5377).

Why: a subagent pays every connected server's names and instructions on every request.
Before probes 2026-11-17 (Sonnet, reply "ok"): sancho 99,535 tokens, ryan 97,771.

Why this is NOT sana's deny list: ryan was installed 2026-10-07 with MCP reachable on
purpose ("I want Ryan to do this research"). Copying RULE-2026-11-13-LEAN's list would
cut Firecrawl, granola, Drive and claude-in-chrome, which subagents called in the window.
So the deny list holds only servers that cannot serve an investigation.

Both agent files live under ~/.claude/agents/, a live path this test never reads. The
repo holds the decision (`investigator-startup.json`) and the proposal generated from
it (`proposals/investigator-lean-startup.json`); this test pins the two together:

- the proposal's deny line is generated from the decision, never edited apart from it;
- every server a subagent called in the window stays allowed, each with a reason;
- the deny set may grow, never shrink;
- every entry is a server-level spec, because a prefix wildcard was measured to remove
  nothing (test_sana_agent_startup.py, 109,109 tokens with `mcp__claude_ai_*`).

The rule_gate reads this file as the enforcer named in ryan.md's preamble.
"""
import json
from pathlib import Path

QS = Path(__file__).resolve().parents[1]
DECISION = QS / "investigator-startup.json"
PROPOSAL = QS / "proposals" / "investigator-lean-startup.json"
AGENTS = {".claude/agents/sancho.md", ".claude/agents/ryan.md"}

# Called by some subagent in the 8-day window ending 2026-11-17.
MEASURED_CALLED = {
    "linear", "claude_ai_Firecrawl", "perplexity-ask", "infohawk", "claude_ai_Gmail",
    "osint-infra", "threat-intel", "granola", "claude-in-chrome", "plugin_kipi-core_kipi",
    "claude_ai_Google_Drive",
}
# Denied 2026-11-17: 0 calls and no investigation use.
MEASURED_DENY = {
    "base44", "claude_ai_Era_Context", "claude_ai_Resend", "claude_ai_Claude_Docs",
    "claude_ai_Google_Calendar", "publer", "google-home", "easel", "computer-use", "supabase",
    "plugin_kipi-notebooklm_notebooklm", "plugin_chrome-devtools-mcp_chrome-devtools",
    "claude_ai_Anthropic_Economic_Index", "claude_ai_Supabase", "claude_ai_Vercel",
    "plugin_vercel_vercel", "claude_ai_Canva", "claude_ai_Figma", "claude_ai_Replit",
    "claude_ai_Claude_Academy", "plugin_small-business_shopify", "plugin_posthog_posthog",
}


def _decision():
    return json.loads(DECISION.read_text())


def _edits():
    return json.loads(PROPOSAL.read_text())["edits"]


def deny_line(deny):
    return "disallowedTools: " + ", ".join("mcp__" + s for s in deny) + "\n"


def problems(decision, edits):
    """Every reason this decision + proposal pair breaks the rule. Empty means it holds."""
    found = []
    deny, keep = decision["deny_mcp_servers"], decision["keep_mcp_servers"]
    lines = {e["file"]: e["insert"] for e in edits if e["insert"].startswith("disallowedTools:")}
    if set(lines) != AGENTS:
        found.append(f"deny line must target exactly {sorted(AGENTS)}, got {sorted(lines)}")
    for f, line in lines.items():
        if line != deny_line(deny):
            found.append(f"{f}: deny line is not generated from the decision")
        for spec in line[len("disallowedTools: "):].strip().split(", "):
            server = spec[len("mcp__"):]
            if not spec.startswith("mcp__") or not server or "*" in server or "__" in server:
                found.append(f"{f}: {spec} is not a server-level spec")
    missing = MEASURED_CALLED - set(keep)
    if missing:
        found.append(f"called servers not kept: {sorted(missing)}")
    if MEASURED_CALLED & set(deny):
        found.append(f"called servers denied: {sorted(MEASURED_CALLED & set(deny))}")
    if set(keep) & set(deny):
        found.append("a server is kept or denied, never both")
    if not all(str(keep.get(s, "")).strip() for s in MEASURED_CALLED):
        found.append("each kept server says why")
    if not set(deny) >= MEASURED_DENY:
        found.append(f"deny set shrank: {sorted(MEASURED_DENY - set(deny))}")
    if {e["op"] for e in edits} - {"insert_after", "insert_before"}:
        found.append("proposal must be additive")
    if {e["file"] for e in edits} != AGENTS:
        found.append("proposal touches a file outside sancho.md and ryan.md")
    return found


def test_tree_holds_the_rule():
    assert problems(_decision(), _edits()) == []


def test_ryan_preamble_names_this_enforcer():
    pre = [e["insert"] for e in _edits() if e["file"] == ".claude/agents/ryan.md" and "Rule-ID:" in e["insert"]]
    assert pre and "RULE-2026-11-17-LEAN-INVESTIGATORS" in pre[0]
    assert "test_investigator_agent_startup.py" in pre[0]


def test_the_check_goes_red_on_each_planted_defect():
    d, e = _decision(), _edits()

    def with_decision(**kw):
        return problems({**d, **kw}, e)

    hand_edited = [dict(x) for x in e]
    hand_edited[0]["insert"] = hand_edited[0]["insert"].replace("mcp__base44, ", "")
    wildcard = [dict(x) for x in e]
    wildcard[0]["insert"] = "disallowedTools: mcp__claude_ai_*\n"
    replace_op = [dict(x) for x in e]
    replace_op[0]["op"] = "replace"
    keep_no_gmail = {k: v for k, v in d["keep_mcp_servers"].items() if k != "claude_ai_Gmail"}
    planted = {
        "hand-edited line": problems(d, hand_edited),
        "wildcard spec": problems(d, wildcard),
        "replace op": problems(d, replace_op),
        "ryan dropped": problems(d, [x for x in e if x["file"] != ".claude/agents/ryan.md"]),
        "called server dropped from keep": with_decision(keep_mcp_servers=keep_no_gmail),
        "called server denied": problems(
            {**d, "deny_mcp_servers": d["deny_mcp_servers"] + ["granola"]},
            [dict(x, insert=deny_line(d["deny_mcp_servers"] + ["granola"]))
             if x["insert"].startswith("disallowedTools:") else x for x in e],
        ),
        "deny shrank": with_decision(deny_mcp_servers=d["deny_mcp_servers"][1:]),
    }
    for label, found in planted.items():
        assert found, f"planted defect not caught: {label}"
