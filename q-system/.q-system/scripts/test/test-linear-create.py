#!/usr/bin/env python3
"""Reproducer + acceptance criterion for `linear-sync.py create` (ASK-113).

Linear objects are PERMANENT here: delete and archive are blocked by the
destructive-op hook and an agent cannot self-authorize them. So a duplicate is
forever, and the cases below are mostly about refusing to create rather than
about creating.

ISOLATION: every case runs against a fake GraphQL server on localhost via
KIPI_LINEAR_API_URL, with KIPI_LINEAR_API_KEY and KIPI_LINEAR_LEDGER overridden.
This suite never reaches api.linear.app and never touches the live ledger. That
is not a nicety: a test that hits live Linear would mint permanent junk objects
in the founder's workspace on every CI run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SYNC = ROOT / "q-system/.q-system/scripts/linear-sync.py"

PASSED = 0


def ok(msg: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  ok: {msg}")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


class FakeLinear(BaseHTTPRequestHandler):
    """Minimal Linear GraphQL stand-in. State lives on the server class."""

    issues: list = []
    projects: list = []
    calls: list = []
    fail_issue_create_after: int | None = None

    def log_message(self, *_a):  # silence
        pass

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        query, variables = body.get("query", ""), body.get("variables", {})
        FakeLinear.calls.append(query.strip().split("\n")[1].strip()[:40])

        if "teams(filter" in query:
            data = {"teams": {"nodes": [{"id": "team-uuid", "key": variables["key"], "name": "T"}]}}
        elif "projects(first" in query:
            data = {"team": {"projects": {"nodes": list(FakeLinear.projects)}}}
        elif "issues(filter" in query:
            data = {
                "issues": {
                    "nodes": list(FakeLinear.issues),
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        elif "projectCreate" in query:
            proj = {
                "id": f"proj-{len(FakeLinear.projects)}",
                "name": variables["input"]["name"],
                "description": variables["input"].get("description", ""),
            }
            FakeLinear.projects.append(proj)
            data = {"projectCreate": {"success": True, "project": proj}}
        elif "issueCreate" in query:
            n = len([c for c in FakeLinear.calls if "issueCreate" in c])
            if (
                FakeLinear.fail_issue_create_after is not None
                and n > FakeLinear.fail_issue_create_after
            ):
                self._send({"errors": [{"message": "rate limited"}]})
                return
            issue = {
                "id": f"iss-{len(FakeLinear.issues)}",
                "identifier": f"ASK-{900 + len(FakeLinear.issues)}",
                "description": variables["input"].get("description", ""),
            }
            FakeLinear.issues.append(issue)
            data = {"issueCreate": {"success": True, "issue": issue}}
        else:
            data = {}
        self._send({"data": data})

    def _send(self, payload: dict) -> None:
        blob = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


def run(plan_path: Path, ledger: Path, port: int, *extra) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["KIPI_LINEAR_API_URL"] = f"http://127.0.0.1:{port}/graphql"
    env["KIPI_LINEAR_API_KEY"] = "fake-key-not-real"
    env["KIPI_LINEAR_LEDGER"] = str(ledger)
    return subprocess.run(
        [sys.executable, str(SYNC), "create", "--plan", str(plan_path), "--team", "ASK", *extra],
        capture_output=True,
        text=True,
        env=env,
    )


def ledger_keys(ledger: Path) -> list:
    if not ledger.is_file():
        return []
    return [json.loads(l)["key"] for l in ledger.read_text().splitlines() if l.strip()]


def main() -> int:
    if not SYNC.is_file():
        fail(f"linear-sync.py not found at {SYNC}")

    server = HTTPServer(("127.0.0.1", 0), FakeLinear)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp())
    ledger = tmp / "ledger.jsonl"
    plan = {
        "repo": "demo-repo",
        "create_project": {"key": "demo-repo/__project__", "name": "demo-repo", "summary": "s"},
        "create_issues": [
            {"key": "demo-repo/alpha", "title": "Alpha", "description": "a\n<!-- kipi-key: demo-repo/alpha -->"},
            {"key": "demo-repo/beta", "title": "Beta", "description": "b\n<!-- kipi-key: demo-repo/beta -->"},
        ],
    }
    plan_path = tmp / "plan.json"
    plan_path.write_text(json.dumps(plan))

    # --- 1. dry by default: nothing is written -----------------------------
    r = run(plan_path, ledger, port)
    if r.returncode != 0:
        fail(f"dry run exited {r.returncode}: {r.stderr}")
    if FakeLinear.issues or FakeLinear.projects:
        fail("a DRY run created objects in Linear -- permanence makes this unrecoverable")
    if ledger_keys(ledger):
        fail("a dry run wrote to the ledger")
    if "--apply" not in r.stdout:
        fail("dry run does not tell the operator how to apply")
    ok("dry by default: no objects, no ledger writes, and it says how to apply")

    # --- 2. --apply creates project + issues, ledger per create ------------
    r = run(plan_path, ledger, port, "--apply")
    if r.returncode != 0:
        fail(f"--apply exited {r.returncode}: {r.stderr}")
    if len(FakeLinear.projects) != 1:
        fail(f"expected 1 project, got {len(FakeLinear.projects)}")
    if len(FakeLinear.issues) != 2:
        fail(f"expected 2 issues, got {len(FakeLinear.issues)}")
    keys = ledger_keys(ledger)
    if sorted(keys) != sorted(["demo-repo/__project__", "demo-repo/alpha", "demo-repo/beta"]):
        fail(f"ledger does not hold all three keys: {keys}")
    ok("--apply creates the project and both issues, and records all three")

    # --- 3. THE PERMANENCE CASE: re-running creates nothing ---------------
    # The remote guard is refetched at create time, so a replayed plan is a
    # no-op even though the plan file still lists both issues.
    before_i, before_p = len(FakeLinear.issues), len(FakeLinear.projects)
    r = run(plan_path, ledger, port, "--apply")
    if r.returncode != 0:
        fail(f"re-run exited {r.returncode}: {r.stderr}")
    if len(FakeLinear.issues) != before_i or len(FakeLinear.projects) != before_p:
        fail(
            f"a replayed plan created DUPLICATES "
            f"({len(FakeLinear.issues) - before_i} issues, "
            f"{len(FakeLinear.projects) - before_p} projects). These cannot be deleted."
        )
    ok("re-running the same plan creates nothing (duplicates are permanent)")

    # --- 4. an empty ledger still creates nothing (remote is authoritative) -
    wiped = tmp / "wiped.jsonl"
    r = run(plan_path, wiped, port, "--apply")
    if r.returncode != 0:
        fail(f"wiped-ledger run exited {r.returncode}: {r.stderr}")
    if len(FakeLinear.issues) != before_i:
        fail("with the ledger wiped, the remote markers did not stop re-creation")
    ok("a wiped ledger is a no-op: the remote kipi-key markers are authoritative")

    # --- 5. a mid-run API failure STOPS and does not over-record -----------
    FakeLinear.issues.clear()
    FakeLinear.projects.clear()
    FakeLinear.calls.clear()
    FakeLinear.fail_issue_create_after = 1  # first issue ok, second fails
    ledger2 = tmp / "partial.jsonl"
    r = run(plan_path, ledger2, port, "--apply")
    if r.returncode == 0:
        fail("a failing issueCreate exited 0; a partial run must not look successful")
    recorded = [k for k in ledger_keys(ledger2) if k.startswith("demo-repo/")]
    issue_records = [k for k in recorded if not k.endswith("__project__")]
    if len(issue_records) != len(FakeLinear.issues):
        fail(
            f"ledger records {len(issue_records)} issue(s) but Linear holds "
            f"{len(FakeLinear.issues)} -- the ledger must never claim more than exists"
        )
    ok("a mid-run API failure stops, exits non-zero, and records only what was created")

    # --- 6. and the partial run is resumable, not a duplicate factory ------
    FakeLinear.fail_issue_create_after = None
    r = run(plan_path, ledger2, port, "--apply")
    if r.returncode != 0:
        fail(f"resume exited {r.returncode}: {r.stderr}")
    if len(FakeLinear.issues) != 2:
        fail(f"resume produced {len(FakeLinear.issues)} issues, expected exactly 2")
    ok("resuming after a failure completes the remainder without duplicating")

    # --- 7. a missing key is a clear refusal, not a traceback --------------
    env = dict(os.environ)
    env["KIPI_LINEAR_API_URL"] = f"http://127.0.0.1:{port}/graphql"
    env["KIPI_LINEAR_LEDGER"] = str(tmp / "nokey.jsonl")
    env.pop("KIPI_LINEAR_API_KEY", None)
    env["HOME"] = str(tmp / "empty-home")
    (tmp / "empty-home").mkdir(exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(SYNC), "create", "--plan", str(plan_path), "--team", "ASK", "--apply"],
        capture_output=True, text=True, env=env,
    )
    if r.returncode == 0:
        fail("running with no API key succeeded")
    if "linear.app/settings/api" not in r.stderr:
        fail(f"the no-key error does not tell the operator where to get one: {r.stderr[:200]}")
    ok("a missing API key refuses with the fix in the message")

    server.shutdown()
    print(f"PASS: linear-create ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
