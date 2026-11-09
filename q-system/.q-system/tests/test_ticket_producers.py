#!/usr/bin/env python3
"""The creation gate (ASK-4205): no ticket opens unless a registered job can close it.

Founder, 2026-11-09: "What's the point of tickets that nothing can close?"

What this pins:
  * run time: `linear-sync.py create` refuses (exit 5, reason on stderr, ZERO
    calls to Linear) an unregistered producer, a row with no exit, a producer
    filing through a path its row does not name, a missing registry, and a plan
    that would create an issue with no project (audit R7). A registered producer
    still creates.
  * merge time: every tracked file that builds an issue create is named by a row,
    and every row lints clean (consumer, exit, signature, paths that exist).
  * the negative self-test: a mutant reader that skips the registry lookup lets
    the unregistered create through, and the same assertion catches it.

ISOLATION: every create runs against a fake GraphQL server on 127.0.0.1 through
KIPI_LINEAR_API_URL, with a fake key and a temp ledger, under KIPI_TEST=1. No
call reaches api.linear.app and nothing touches the live ledger.

Runs under /usr/bin/python3 3.9 (launchd's interpreter) and CI's 3.12.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "q-system/.q-system/scripts"
SYNC = SCRIPTS / "linear-sync.py"
GATE = SCRIPTS / "ticket_producers.py"
REGISTRY = ROOT / "q-system/.q-system/ticket-producers.json"
EXIT_REFUSED = 5

sys.path.insert(0, str(SCRIPTS))
import ticket_producers as tp  # noqa: E402


class FakeLinear(BaseHTTPRequestHandler):
    """Linear GraphQL stand-in. Records every call; holds projects and issues."""

    calls: list = []
    creates: list = []
    projects: list = []

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        q, v = body.get("query", ""), body.get("variables", {})
        FakeLinear.calls.append(q)
        if "teams(filter" in q:
            data = {"teams": {"nodes": [{"id": "team-uuid", "key": v.get("key"), "name": "T"}]}}
        elif "projects(first" in q:
            data = {"team": {"projects": {"nodes": list(FakeLinear.projects)}}}
        elif "issues(filter" in q:
            data = {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        elif "projectCreate" in q:
            proj = {"id": f"proj-{len(FakeLinear.projects)}", "name": v["input"]["name"],
                    "description": v["input"].get("description", "")}
            FakeLinear.projects.append(proj)
            data = {"projectCreate": {"success": True, "project": proj}}
        elif "issueCreate" in q:
            FakeLinear.creates.append(v["input"])
            data = {"issueCreate": {"success": True, "issue": {
                "id": f"iss-{len(FakeLinear.creates)}",
                "identifier": f"FAKE-{len(FakeLinear.creates)}"}}}
        else:
            data = {}
        blob = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


def plan_for(tmp: Path, name: str, producer=None, with_project=True) -> Path:
    plan = {
        "repo": "gate-demo",
        "create_issues": [
            {"key": "gate-demo/alpha", "title": "Alpha",
             "description": "a\n<!-- kipi-key: gate-demo/alpha -->"},
        ],
    }
    if with_project:
        plan["create_project"] = {"key": "gate-demo/__project__", "name": "gate-demo", "summary": "s"}
    if producer is not None:
        plan["producer"] = producer
    path = tmp / f"{name}.json"
    path.write_text(json.dumps(plan))
    return path


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeLinear)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = Path(tempfile.mkdtemp(prefix="ticket-producers-"))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        FakeLinear.calls.clear()
        FakeLinear.creates.clear()
        FakeLinear.projects.clear()

    def run_create(self, plan: Path, *extra, sync: Path = SYNC, env_extra=None, test_mode=True):
        env = dict(os.environ)
        env.pop("KIPI_TICKET_PRODUCERS", None)
        env["KIPI_LINEAR_API_URL"] = f"http://127.0.0.1:{self.port}/graphql"
        env["KIPI_LINEAR_API_KEY"] = "fake-key-not-real"
        env["KIPI_LINEAR_LEDGER"] = str(self.tmp / f"ledger-{len(os.listdir(self.tmp))}.jsonl")
        if test_mode:
            env["KIPI_TEST"] = "1"
        else:
            env.pop("KIPI_TEST", None)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, str(sync), "create", "--plan", str(plan),
                               "--team", "ASK", *extra], capture_output=True, text=True, env=env)

    def assert_refused(self, r, needle: str):
        """THE assertion the mutant test proves can fail: exit 5, the reason on
        stderr, and not one call to Linear (the gate runs before the network)."""
        self.assertEqual(r.returncode, EXIT_REFUSED, f"expected a refusal, got {r.returncode}: {r.stderr}")
        self.assertIn(needle, r.stderr)
        self.assertEqual(FakeLinear.creates, [], "a refused create reached issueCreate")

    # --- run time -------------------------------------------------------------

    def test_unregistered_producer_is_refused_before_any_network_call(self):
        r = self.run_create(plan_for(self.tmp, "unreg", "made-up-producer"), "--apply")
        self.assert_refused(r, "made-up-producer` is not registered")
        self.assertEqual(FakeLinear.calls, [], "the gate must refuse before calling Linear at all")

    def test_dry_run_is_gated_too(self):
        r = self.run_create(plan_for(self.tmp, "unreg-dry", "made-up-producer"))
        self.assert_refused(r, "is not registered")

    def test_a_plan_with_no_producer_is_refused(self):
        r = self.run_create(plan_for(self.tmp, "noprod"), "--apply")
        self.assert_refused(r, "no producer named")

    def test_registered_producer_still_creates_with_a_project(self):
        r = self.run_create(plan_for(self.tmp, "ok", "linear-sync-capability"), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(FakeLinear.creates), 1)
        self.assertTrue(FakeLinear.creates[0].get("projectId"), "created with no projectId")

    def test_a_plan_from_plan_carries_its_producer_and_create_takes_it(self):
        # Day one for the one live producer of this path: `kipi linear plan`
        # then `kipi linear create`. The plan must name the producer itself, or
        # every capability rollout after this PR would be refused.
        cmap = self.tmp / "cap-map.json"
        cmap.write_text(json.dumps({"repo": "gate-demo", "capabilities": [
            {"name": "alpha engine", "status": "BROKEN", "path": "x.py"}]}))
        remote = self.tmp / "remote.json"
        remote.write_text(json.dumps({"project": None, "issues": []}))
        out = self.tmp / "made-plan.json"
        env = dict(os.environ, KIPI_LINEAR_LEDGER=str(self.tmp / "plan-ledger.jsonl"), KIPI_TEST="1")
        p = subprocess.run([sys.executable, str(SYNC), "plan", "--map", str(cmap), "--remote",
                            str(remote), "--out", str(out)], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(out.read_text()).get("producer"), "linear-sync-capability")
        r = self.run_create(out, "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(FakeLinear.creates), 1)

    def test_cli_producer_names_the_producer_for_an_old_plan(self):
        r = self.run_create(plan_for(self.tmp, "cli"), "--apply", "--producer", "linear-sync-capability")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(FakeLinear.creates), 1)

    def test_cli_and_plan_producer_that_disagree_are_refused(self):
        r = self.run_create(plan_for(self.tmp, "clash", "linear-sync-capability"), "--apply",
                            "--producer", "spillover-promote")
        self.assert_refused(r, "disagree")

    def test_a_producer_filing_through_a_path_its_row_does_not_name_is_refused(self):
        # spillover-promote is registered, but to create through spillover-promote.py.
        r = self.run_create(plan_for(self.tmp, "wrongpath", "spillover-promote"), "--apply")
        self.assert_refused(r, "not q-system/.q-system/scripts/linear-sync.py")

    def test_a_row_with_an_empty_exit_is_refused_at_run_time(self):
        reg = json.loads(REGISTRY.read_text())
        for row in reg["producers"]:
            if row["id"] == "linear-sync-capability":
                row["exit"] = {"kind": "", "by": ""}
        bad = self.tmp / "no-exit-registry.json"
        bad.write_text(json.dumps(reg))
        r = self.run_create(plan_for(self.tmp, "noexit", "linear-sync-capability"), "--apply",
                            env_extra={"KIPI_TICKET_PRODUCERS": str(bad)})
        self.assert_refused(r, "no exit")

    def test_a_missing_registry_fails_closed(self):
        r = self.run_create(plan_for(self.tmp, "noreg", "linear-sync-capability"), "--apply",
                            env_extra={"KIPI_TICKET_PRODUCERS": str(self.tmp / "absent.json")})
        self.assert_refused(r, "fails closed")

    def test_the_registry_override_is_ignored_outside_test_mode(self):
        # A permissive copy that registers made-up-producer must not be honoured
        # by a live run: without KIPI_TEST=1 the checkout's own registry decides.
        reg = json.loads(REGISTRY.read_text())
        row = dict(next(r for r in reg["producers"] if r["id"] == "linear-sync-capability"))
        row["id"] = "made-up-producer"
        reg["producers"].append(row)
        loose = self.tmp / "loose-registry.json"
        loose.write_text(json.dumps(reg))
        r = self.run_create(plan_for(self.tmp, "loose", "made-up-producer"), "--apply",
                            env_extra={"KIPI_TICKET_PRODUCERS": str(loose)}, test_mode=False)
        self.assert_refused(r, "is not registered")

    def test_no_project_anywhere_is_refused(self):
        # Audit R7: no project on the board and none in the plan. Before the gate
        # this sent issueCreate with no projectId.
        for extra in ((), ("--apply",)):
            FakeLinear.creates.clear()
            r = self.run_create(plan_for(self.tmp, "noproj", "linear-sync-capability",
                                         with_project=False), *extra)
            self.assert_refused(r, "no Linear project")

    def test_the_cli_check_command_agrees(self):
        ok = subprocess.run([sys.executable, str(GATE), "check", "linear-sync-capability",
                             "q-system/.q-system/scripts/linear-sync.py"], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        no = subprocess.run([sys.executable, str(GATE), "check", "made-up-producer",
                             "q-system/.q-system/scripts/linear-sync.py"], capture_output=True, text=True)
        self.assertEqual(no.returncode, EXIT_REFUSED)
        self.assertIn("not registered", no.stderr)

    # --- the negative self-test -----------------------------------------------

    def test_mutant_that_skips_the_registry_lookup_is_caught(self):
        """Copy the gate's two files, make refusal() skip the lookup, and run the
        unregistered case. The mutant must let it through, and assert_refused
        must fail on that result. If either is false, the test above cannot fail."""
        src = GATE.read_text()
        anchor = "    root = root or repo_root()\n    path = path or registry_path(root)\n"
        self.assertEqual(src.count(anchor), 1, "mutation anchor moved; update this test")
        mutant_root = self.tmp / "mutant"
        scripts = mutant_root / "q-system/.q-system/scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "ticket_producers.py").write_text(src.replace(anchor, "    return None\n" + anchor))
        shutil.copy(SYNC, scripts / "linear-sync.py")
        r = self.run_create(plan_for(self.tmp, "mutant", "made-up-producer"), "--apply",
                            sync=scripts / "linear-sync.py")
        self.assertEqual(r.returncode, 0, f"the mutant should let the bad create through: {r.stderr}")
        self.assertEqual(len(FakeLinear.creates), 1)
        with self.assertRaises(AssertionError):
            self.assert_refused(r, "is not registered")


class Registry(unittest.TestCase):
    def setUp(self):
        self.reg = tp.load(str(REGISTRY))

    def test_the_shipped_registry_lints_clean(self):
        self.assertEqual(tp.lint(self.reg, str(ROOT)), [])

    def test_every_tracked_filer_has_a_row_and_every_row_path_still_files(self):
        self.assertEqual(tp.coverage_problems(self.reg, str(ROOT)), [])

    def test_lint_refuses_a_row_with_no_exit_or_no_consumer(self):
        reg = json.loads(json.dumps(self.reg))
        reg["producers"][0]["exit"] = {"kind": "", "by": ""}
        reg["producers"][1]["consumer"] = ""
        reg["producers"][2]["exit"] = {"kind": "eventually", "by": reg["producers"][2]["exit"]["by"]}
        got = "\n".join(tp.lint(reg, str(ROOT)))
        self.assertIn(f"`{reg['producers'][0]['id']}`: no exit", got)
        self.assertIn(f"`{reg['producers'][1]['id']}`: no consumer", got)
        self.assertIn("exit.kind `eventually`", got)

    def test_lint_refuses_gate_none_without_a_gap_ticket_and_a_missing_path(self):
        reg = json.loads(json.dumps(self.reg))
        row = next(r for r in reg["producers"] if r["gate"] == "none")
        row.pop("gap")
        reg["producers"][0]["consumer"] = "q-system/.q-system/scripts/no-such-consumer.py"
        got = "\n".join(tp.lint(reg, str(ROOT)))
        self.assertIn("needs `gap`", got)
        self.assertIn("no-such-consumer.py` does not exist", got)

    def test_coverage_flags_a_new_filer_and_a_stale_row(self):
        filers = tp.tracked_filers(str(ROOT))
        got = tp.coverage_problems(self.reg, str(ROOT),
                                   filers=filers + ["q-system/.q-system/scripts/new-filer.py"])
        self.assertTrue(any("new-filer.py builds a Linear issue create" in p for p in got), got)
        stale = [f for f in filers if f != "q-system/.q-system/scripts/stall-sweep.py"]
        got = tp.coverage_problems(self.reg, str(ROOT), filers=stale)
        self.assertTrue(any("stall-sweep.py` no longer builds" in p for p in got), got)

    def test_the_create_shape_matches_real_filers_not_mentions(self):
        self.assertTrue(tp.CREATE_RE.search('mutation { issueCreate(input: $i) { success } }'))
        self.assertTrue(tp.CREATE_RE.search('node = data.get("issueCreate") or {}'))
        self.assertTrue(tp.CREATE_RE.search('res = ls.graphql(ls.ISSUE_CREATE, {})'))
        self.assertFalse(tp.CREATE_RE.search("sets projectId in the SAME issueCreate\ncall"))
        self.assertNotIn("q-system/.q-system/scripts/linear-triage-health.py", tp.tracked_filers(str(ROOT)))

    def test_every_signature_finds_its_own_ticket_shape(self):
        samples = {
            "linear-sync-capability": "<!-- kipi-key: kipi-system/voice-loop-mirror -->",
            "job-migration": "<!-- kipi-key: job-migration/com-kipi-dispatch -->",
            "linear-dor-failure": "<!-- kipi-key: linear-dor/run-failure -->",
            "fleet-health-daily": "<!-- kipi-key: fleet-health/launchd-job -->",
            "stall-sweep": "<!-- kipi-key: stall-sweep/pr-idle -->",
            "spillover-promote": "Promoted from spillover `sp-1234abcd`",
            "cap-ladder": "Fix the thing (split after cap)",
            "spillover": "spillover sp-1234abcd (major) from ASK-1: x",
            "alert-to-linear": "Filed automatically by the fleet alert path.",
            "chief-ping-gate": "ping-gate:radar:audhd: radar.social: a post broke",
            "chief-routine-runs": "Filed by the Mac's daily routine-run check",
            "chief-cloud-health": "Filed by the daily cloud health check",
        }
        import re
        for row in self.reg["producers"]:
            if row["signature"] is None:
                continue
            self.assertIn(row["id"], samples, f"add a sample for {row['id']}")
            self.assertTrue(re.search(row["signature"], samples[row["id"]], re.M),
                            f"{row['id']} signature misses its own shape")
        # The capability signature must not swallow the other keyed producers.
        cap = next(r for r in self.reg["producers"] if r["id"] == "linear-sync-capability")
        for other in ("job-migration", "linear-dor-failure", "fleet-health-daily", "stall-sweep"):
            self.assertIsNone(re.search(cap["signature"], samples[other]), other)
        # A hand-filed ticket that only discusses a spillover id is not spillover.
        spill = next(r for r in self.reg["producers"] if r["id"] == "spillover")
        self.assertIsNone(re.search(spill["signature"], "Title\nThe original alert is spillover sp-55e61d4b.", re.M))


if __name__ == "__main__":
    unittest.main(verbosity=2)
