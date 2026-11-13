"""Tests for fleet_load.py: the lean launch and the start-up ratchet (ASK-4747, ASK-4756).

Fixture shapes are copied from real records: installed_plugins.json (version 2), a
skills-dir plugin.json, and the attachment records of two `claude -p` sessions taken
2026-11-12 in a kipi-system tree (full set: 345 / 617 / 14; lean: 106 / 13 / 0).
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_load  # noqa: E402

BUILTIN = ["CronCreate", "CronDelete", "CronList", "EnterWorktree", "ExitWorktree", "Monitor", "NotebookEdit",
           "SendMessage", "TaskStop", "WebFetch", "WebSearch", "ArtifactComments", "ArtifactData"]


def tx_lines(skills: int, mcp_names: list[str], instr: list[str], pending: list[str] | None = None) -> str:
    recs = [
        {"type": "attachment", "attachment": {"type": "skill_listing", "content": "- s: d\n" * skills,
                                              "skillCount": skills, "isInitial": True,
                                              "names": [f"s{i}" for i in range(skills)],
                                              "digests": ["0" * 16] * skills}},
        {"type": "attachment", "attachment": {"type": "deferred_tools_delta", "addedNames": BUILTIN + mcp_names,
                                              "addedLines": BUILTIN + mcp_names, "removedNames": [],
                                              "wireHiddenNames": [], "readdedNames": [],
                                              "pendingMcpServers": pending or [], "needsAuthMcpServers": [],
                                              "failedMcpServers": []}},
    ]
    if instr:
        recs.append({"type": "attachment", "attachment": {"type": "mcp_instructions_delta", "addedNames": instr,
                                                          "addedBlocks": ["## x"] * len(instr), "removedNames": []}})
    recs.append({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 2}}})
    return "\n".join(json.dumps(r) for r in recs) + "\n"


LEAN = tx_lines(106, [], [])
LEAN_AFTER_SYNC = tx_lines(121, [], [])  # 2026-11-13: +15 account skills no enabledPlugins key reaches
FULL = tx_lines(345, [f"mcp__linear__t{i}" for i in range(300)] + [f"mcp__claude_ai_Gmail__t{i}" for i in range(304)],
                [f"srv{i}" for i in range(14)], pending=["apify", "playwright"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / "cfg"
        self.tree = self.tmp / "tree"
        (self.cfg / "plugins").mkdir(parents=True)
        (self.tree / ".claude").mkdir(parents=True)
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"kipi-core@kipi": [{"scope": "user"}], "prd-os@kipi": [{"scope": "user"}],
                                       "posthog@claude-plugins-official": [{"scope": "user"}]}}))
        (self.cfg / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"vercel@claude-plugins-official": True, "kipi-core@kipi": True}}))
        (self.cfg / "settings.local.json").write_text(json.dumps(
            {"permissions": {"allow": []}, "enabledPlugins": {"slack@claude-plugins-official": True}}))
        (self.tree / ".claude" / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"frontend-design@claude-code-plugins": True}}))
        pj = self.cfg / "skills" / "last30days" / ".claude-plugin"
        pj.mkdir(parents=True)
        (pj / "plugin.json").write_text(json.dumps({"name": "last30days", "version": "2.9.5"}))
        sp = self.cfg / "plugins" / "synced" / "acct_org" / "dab4db2f" / ".claude-plugin"
        sp.mkdir(parents=True)
        (sp / "plugin.json").write_text(json.dumps({"name": "small-business", "version": "1.35.2"}))
        self.allow = self.tmp / "allow.json"
        self.allow.write_text(fleet_load.ALLOW.read_text())

    def session(self, sid: str, body: str) -> None:
        d = self.cfg / "projects" / "-tree"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.jsonl").write_text(body)


class LeanSettings(Base):
    def test_every_source_is_read(self):
        self.assertEqual(fleet_load.known_plugins(self.tree, self.cfg), {
            "kipi-core@kipi", "prd-os@kipi", "posthog@claude-plugins-official", "vercel@claude-plugins-official",
            "frontend-design@claude-code-plugins", "last30days@skills-dir", "small-business@synced",
            "slack@claude-plugins-official"})

    def test_off_is_the_complement_of_the_row_and_the_guard_survives(self):
        guard = json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "g"}]}]},
                            "permissions": {"deny": ["Bash(rm -rf *)"]}})
        doc = json.loads(fleet_load.lean_settings("worker", self.tree, guard, self.cfg, self.allow))
        self.assertEqual(doc["hooks"], json.loads(guard)["hooks"])
        self.assertEqual(doc["permissions"], {"deny": ["Bash(rm -rf *)"]})
        self.assertEqual(doc["enabledPlugins"], {
            "posthog@claude-plugins-official": False, "vercel@claude-plugins-official": False,
            "frontend-design@claude-code-plugins": False, "last30days@skills-dir": False,
            "small-business@synced": False, "slack@claude-plugins-official": False})

    def test_nothing_to_pass_prints_nothing(self):
        for f in (self.cfg / "plugins" / "installed_plugins.json", self.cfg / "settings.json",
                  self.cfg / "settings.local.json",
                  self.tree / ".claude" / "settings.json",
                  self.cfg / "skills" / "last30days" / ".claude-plugin" / "plugin.json",
                  self.cfg / "plugins" / "synced" / "acct_org" / "dab4db2f" / ".claude-plugin" / "plugin.json"):
            f.unlink()
        self.assertEqual(fleet_load.lean_settings("worker", self.tree, "", self.cfg, self.allow), "")

    def test_a_record_that_does_not_parse_is_an_error_not_an_empty_set(self):
        (self.cfg / "plugins" / "installed_plugins.json").write_text("{not json")
        with self.assertRaises(ValueError):
            fleet_load.known_plugins(self.tree, self.cfg)


class McpConfig(Base):
    def test_worker_gets_the_strict_empty_config(self):
        self.assertEqual(json.loads(fleet_load.mcp_config("worker", self.allow)), {"mcpServers": {}})

    def test_a_named_server_this_code_cannot_serve_is_refused(self):
        d = json.loads(self.allow.read_text())
        d["jobs"]["worker"]["mcp_servers"] = ["kipi"]
        self.allow.write_text(json.dumps(d))
        with self.assertRaises(fleet_load.Unservable):
            fleet_load.mcp_config("worker", self.allow)


class StartupRatchet(Base):
    def test_counts_from_the_two_measured_sessions(self):
        self.session("lean", LEAN)
        self.session("full", FULL)
        lean = fleet_load.startup_counts(self.cfg / "projects" / "-tree" / "lean.jsonl")
        full = fleet_load.startup_counts(self.cfg / "projects" / "-tree" / "full.jsonl")
        self.assertEqual((lean["skills"], lean["deferred_tools"], lean["mcp_servers"]), (106, 13, 0))
        self.assertEqual((full["skills"], full["deferred_tools"]), (345, 617))
        self.assertGreaterEqual(full["mcp_servers"], 14)

    def test_the_measured_lean_session_passes_the_committed_ceiling_and_the_full_one_does_not(self):
        ceiling = json.loads(fleet_load.ALLOW.read_text())["jobs"]["worker"]["startup_ceiling"]
        self.session("lean", LEAN)
        self.session("full", FULL)
        p = self.cfg / "projects" / "-tree"
        self.assertEqual(fleet_load.over_ceiling(fleet_load.startup_counts(p / "lean.jsonl"), ceiling), [])
        self.session("after", LEAN_AFTER_SYNC)
        self.assertEqual(fleet_load.over_ceiling(fleet_load.startup_counts(p / "after.jsonl"), ceiling), [])
        self.assertEqual(len(fleet_load.over_ceiling(fleet_load.startup_counts(p / "full.jsonl"), ceiling)), 3)

    def test_the_line_is_inclusive_and_one_past_it_fails(self):
        c = {"skills": 120, "deferred_tools": 20, "mcp_servers": 0}
        self.assertEqual(fleet_load.over_ceiling({"skills": 120, "deferred_tools": 20, "mcp_servers": 0}, c), [])
        self.assertEqual(fleet_load.over_ceiling({"skills": 121, "deferred_tools": 20, "mcp_servers": 0}, c),
                         ["skills 121 > 120"])
        self.assertEqual(fleet_load.over_ceiling({"skills": 120, "deferred_tools": 20, "mcp_servers": 1}, c),
                         ["mcp_servers 1 > 0"])

    def test_an_unread_count_is_over_never_a_clean_zero(self):
        self.session("bare", json.dumps({"type": "assistant", "message": {"id": "m"}}) + "\n")
        counts = fleet_load.startup_counts(self.cfg / "projects" / "-tree" / "bare.jsonl")
        self.assertIn("skills unread", fleet_load.over_ceiling(counts, {"skills": 120, "deferred_tools": 20}))

    def test_alert_once_on_the_state_change(self):
        rec = self.tmp / "state" / "worker-startup.jsonl"
        self.session("a", FULL)
        self.session("b", FULL)
        self.session("c", LEAN)
        self.session("d", FULL)
        first = fleet_load.startup("a", "ASK-1", rec, self.cfg, allow=self.allow)
        self.assertIn("grew past its ceiling on ASK-1", first)
        self.assertEqual(fleet_load.startup("b", "ASK-2", rec, self.cfg, allow=self.allow), "")
        self.assertEqual(fleet_load.startup("c", "ASK-3", rec, self.cfg, allow=self.allow), "")
        self.assertIn("ASK-4", fleet_load.startup("d", "ASK-4", rec, self.cfg, allow=self.allow))
        rows = [json.loads(x) for x in rec.read_text().splitlines()]
        self.assertEqual([r["ticket"] for r in rows], ["ASK-1", "ASK-2", "ASK-3", "ASK-4"])
        self.assertEqual(rows[2]["over"], [])

    def test_no_transcript_no_row(self):
        rec = self.tmp / "state" / "worker-startup.jsonl"
        self.assertEqual(fleet_load.startup("missing", "ASK-1", rec, self.cfg, allow=self.allow), "")
        self.assertFalse(rec.exists())


class Cli(Base):
    def test_exit_codes(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(err):
            self.assertEqual(fleet_load.main(["mcp-config", "--job", "worker"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"mcpServers": {}})
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(fleet_load.main(["settings", "--job", "nosuchjob", "--tree", str(self.tree)]), 1)


if __name__ == "__main__":
    unittest.main()
