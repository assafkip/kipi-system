"""The load allowlist per job class is real data (RULE-2026-11-13-E).

Sana's decision 2026-11-13 (D1): a headless worker, the PR reviewer and background calls
load only the fleet's own plugins a job class names, no account connectors, and the big
non-fleet plugins leave user scope. The file is q-system/.q-system/fleet-load-allowlist.json.
ASK-4756 wires the launchers to read it. This test holds the file to the fleet as it
exists: a plugin name must be one the fleet marketplace ships, an MCP server one a fleet
plugin declares, and no fleet plugin may be listed to leave user scope.

WHY a closed check on names: the file is read by launch flags later, and a typo there
turns into a plugin that silently does not load. A name that is not in the marketplace
manifest is refused here, before any launcher reads it.
"""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ALLOW = REPO / "q-system/.q-system/fleet-load-allowlist.json"
MARKET = REPO / ".claude-plugin/marketplace.json"
JOBS = {"worker", "review", "background"}
INSTALL_KEY = re.compile(r"^[a-z0-9-]+@[a-z0-9-]+$")


def fleet():
    m = json.loads(MARKET.read_text())
    plugins = {p["name"] for p in m["plugins"]}
    servers = set()
    for p in m["plugins"]:
        mcp = REPO / p["source"] / ".mcp.json"
        if mcp.exists():
            servers |= set(json.loads(mcp.read_text()).get("mcpServers", {}))
    return m["name"], plugins, servers


def problems(doc, market, plugins, servers):
    out = []
    if set(doc.get("jobs", {})) != JOBS:
        out.append(f"job classes {sorted(doc.get('jobs', {}))} != {sorted(JOBS)}")
    for job, row in doc.get("jobs", {}).items():
        out += [f"{job}: plugin {p} is not a fleet plugin" for p in row.get("plugins", []) if p not in plugins]
        out += [f"{job}: MCP server {s} no fleet plugin declares" for s in row.get("mcp_servers", []) if s not in servers]
        if row.get("account_connectors") is not False:
            out.append(f"{job}: account_connectors must be false")
        if not str(row.get("why", "")).strip():
            out.append(f"{job}: no why")
    for key in doc.get("interactive", {}).get("leave_user_scope", []):
        if not INSTALL_KEY.match(key):
            out.append(f"interactive: {key} is not name@marketplace")
        elif key.endswith("@" + market):
            out.append(f"interactive: {key} is a fleet plugin; fleet plugins stay user scope")
    return out


class FleetLoadAllowlist(unittest.TestCase):
    def test_the_file_matches_the_fleet(self):
        doc = json.loads(ALLOW.read_text())
        self.assertIn("RULE-2026-11-13-E", doc["_"])
        self.assertEqual(problems(doc, *fleet()), [])

    def test_the_worker_keeps_the_guard_plugins(self):
        # the hooks a builder works through ship in these; dropping one drops its gate
        worker = json.loads(ALLOW.read_text())["jobs"]["worker"]["plugins"]
        for p in ("kipi-core", "prd-os"):
            self.assertIn(p, worker)

    def test_negative_self_test_each_check_can_fail(self):
        market, plugins, servers = fleet()
        good = json.loads(ALLOW.read_text())
        self.assertEqual(problems(good, market, plugins, servers), [])
        cases = (
            lambda d: d["jobs"]["worker"]["plugins"].append("posthog"),
            lambda d: d["jobs"]["review"]["mcp_servers"].append("claude_ai_Gmail"),
            lambda d: d["jobs"]["background"].update(account_connectors=True),
            lambda d: d["jobs"].pop("review"),
            lambda d: d["interactive"]["leave_user_scope"].append("kipi-core@" + market),
            lambda d: d["interactive"]["leave_user_scope"].append("posthog"),
        )
        for i, mutate in enumerate(cases):
            d = json.loads(json.dumps(good))
            mutate(d)
            self.assertTrue(problems(d, market, plugins, servers), f"case {i} passed")


if __name__ == "__main__":
    unittest.main()
