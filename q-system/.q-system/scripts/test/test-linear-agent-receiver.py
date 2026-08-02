#!/usr/bin/env python3
"""End-to-end round trip for linear-agent-receiver.py, against a COPY of every edge.

Pairs with: q-system/.q-system/scripts/linear-agent-receiver.py

WHAT THIS PROVES
----------------
A signed AgentSessionEvent arriving over a real socket reaches the local runner with
the right issue, and the outcome is posted back as agent activities in the right
order. That is the whole "Linear is the interface, local is the executor" claim, and
it is the one claim that cannot be checked by reading the source.

WHY EVERY EDGE IS FAKED
-----------------------
Nothing here may touch the live path. A test that posted real activities would write
into the founder's real Linear workspace, and a test that called the real runner would
create real worktrees and real sana/* branches and burn real model budget. So:
  - Linear's GraphQL API  -> a local recording server
  - linear-worker.sh      -> a shell stub that records its argv
  - the session ledger    -> a tmpdir
The fable-discipline lint blocks tests that touch a live data path; this is that rule
obeyed, not worked around.

THE CASE THAT MATTERS MOST is the negative one: a BAD SIGNATURE MUST NOT RUN THE
RUNNER. A signature check that returns 401 while still dispatching the work is worse
than no check, because it reads as safe. So the test asserts on the runner's own
receipt file, not on the HTTP status.
"""
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Overridable so a MUTANT copy can be driven through this same suite. A suite that
# can only ever run the good file cannot tell you whether it would catch the bad one,
# and "the test passed" is not evidence until you have watched it fail on purpose.
SCRIPT = Path(os.environ.get(
    "KIPI_RECEIVER_UNDER_TEST",
    Path(__file__).resolve().parent.parent / "linear-agent-receiver.py"))
SECRET = "test-secret-not-a-real-one"

ACTIVITIES = []          # what the fake Linear was asked to post
AUTH_HEADERS = []        # the token each call actually presented
_ACT_LOCK = threading.Lock()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeLinear(BaseHTTPRequestHandler):
    """Records agentActivityCreate calls. Stands in for api.linear.app."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with _ACT_LOCK:
            AUTH_HEADERS.append(self.headers.get("Authorization", ""))
        try:
            req = json.loads(raw)
        except ValueError:
            req = {}

        # The identifier lookup (UUID -> ASK-123) and the activity write share one
        # endpoint, so the fake routes on the query text the same way Linear does.
        if "query Issue" in (req.get("query") or ""):
            body = json.dumps({"data": {"issue": {"identifier": "ASK-555"}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            with _ACT_LOCK:
                ACTIVITIES.append(req["variables"]["input"]["content"])
        except (KeyError, TypeError):
            pass
        body = json.dumps({"data": {"agentActivityCreate": {"success": True}}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def event(issue="ASK-999", session="sess-abc", age_ms=0) -> bytes:
    return json.dumps({
        "type": "AgentSessionEvent",
        "action": "created",
        "webhookTimestamp": int(time.time() * 1000) - age_ms,
        "agentSession": {
            "id": session,
            "issue": {"identifier": issue, "title": "fixture issue"},
        },
    }).encode()


def post(url: str, body: bytes, sig: str) -> int:
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Linear-Signature": sig,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="linear-agent-test-"))
    failures, checks = [], []

    def check(name, got, want):
        ok = got == want
        checks.append((name, ok, got, want))
        if not ok:
            failures.append(name)

    try:
        # --- the fake Linear API ---------------------------------------
        fake_port = free_port()
        fake = HTTPServer(("127.0.0.1", fake_port), FakeLinear)
        threading.Thread(target=fake.serve_forever, daemon=True).start()

        # --- the fake runner: records argv, never runs anything ---------
        receipt = tmp / "runner-receipt.txt"
        runner = tmp / "fake-runner.sh"
        runner.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{receipt}"\necho "fake run ok"\n')
        runner.chmod(0o755)

        env = {
            **os.environ,
            "KIPI_LINEAR_API": f"http://127.0.0.1:{fake_port}/graphql",
            "KIPI_LINEAR_AGENT_RUNNER": f"bash {runner}",
            "KIPI_LINEAR_AGENT_STATE": str(tmp),
            "KIPI_LINEAR_WEBHOOK_SECRET": SECRET,
            "KIPI_LINEAR_AGENT_TOKEN": "test-token",
            "KIPI_NOTIFY": "/usr/bin/true",
        }

        # --- the receiver under test ------------------------------------
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), "serve", "--port", str(port)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        url = f"http://127.0.0.1:{port}/"
        for _ in range(50):                     # wait for the socket, not a sleep
            try:
                urllib.request.urlopen(url, data=b"{}", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)

        # === NEGATIVE FIRST: a forged event must not reach the runner ===
        code = post(url, event(issue="ASK-666"), "deadbeef")
        check("forged signature -> 401", code, 401)
        time.sleep(1.0)                          # give a bug time to misbehave
        ran = receipt.read_text() if receipt.exists() else ""
        check("forged signature -> runner NOT invoked", "ASK-666" in ran, False)
        check("forged signature -> no activity posted", len(ACTIVITIES), 0)

        # === REPLAY: a CORRECTLY SIGNED but old event must not run =======
        # This case escaped the first mutation run: killing the replay guard left the
        # suite green, because every other negative case used a bad signature. A
        # captured real webhook replayed later carries a PERFECTLY VALID signature --
        # the timestamp window is the only thing standing between a replay and a
        # duplicate run, so it needs a case of its own.
        stale = event(issue="ASK-777", age_ms=120_000)
        code = post(url, stale, sign(stale))
        check("replayed event (valid sig, old ts) -> 401", code, 401)
        time.sleep(1.0)
        ran = receipt.read_text() if receipt.exists() else ""
        check("replayed event -> runner NOT invoked", "ASK-777" in ran, False)

        # === POSITIVE: a signed event runs and reports back ==============
        body = event(issue="ASK-999")
        t0 = time.time()
        code = post(url, body, sign(body))
        ack_ms = (time.time() - t0) * 1000
        check("signed event -> 200", code, 200)
        # Linear retries anything slower than 5s; a slow ack means duplicate runs.
        check("ack under Linear's 5s retry budget", ack_ms < 5000, True)

        for _ in range(100):                     # wait for the background thread
            if receipt.exists() and "ASK-999" in receipt.read_text():
                break
            time.sleep(0.1)

        ran = receipt.read_text() if receipt.exists() else ""
        check("runner invoked with the delegated issue", "--issue ASK-999" in ran, True)
        check("runner invoked in apply mode", "--apply" in ran, True)

        for _ in range(50):
            with _ACT_LOCK:
                if any(a.get("type") in ("response", "error") for a in ACTIVITIES):
                    break
            time.sleep(0.1)

        with _ACT_LOCK:
            types = [a.get("type") for a in ACTIVITIES]
        check("first activity is a thought (10s ack rule)", types[:1], ["thought"])
        check("an action activity names the run", "action" in types, True)
        check("terminal activity is response", types[-1] if types else None, "response")

        # === UUID-ONLY EVENT: the identifier must be RESOLVED, not guessed =====
        # Linear's published SDL does not promise `issue.identifier` on the webhook --
        # only UUIDs. If that is what arrives, passing the UUID straight to the runner
        # matches no issue and the run exits 0 having done nothing, which is invisible
        # to the attempt counter. So this drives the shape with NO identifier at all.
        uuid_ev = json.dumps({
            "type": "AgentSessionEvent", "action": "created",
            "webhookTimestamp": int(time.time() * 1000),
            "agentSession": {"id": "sess-uuid", "issueId": "d290f1ee-6c54-4b01-90e6-d701748f0851"},
        }).encode()
        post(url, uuid_ev, sign(uuid_ev))

        for _ in range(100):
            if receipt.exists() and "ASK-555" in receipt.read_text():
                break
            time.sleep(0.1)
        ran = receipt.read_text() if receipt.exists() else ""
        check("UUID-only event -> identifier resolved and dispatched",
              "--issue ASK-555" in ran, True)
        check("UUID never passed to the runner as an issue key",
              "d290f1ee" in ran, False)

        # --- the ledger recorded the session ----------------------------
        ledger = tmp / "linear-agent-sessions.json"
        rec = json.loads(ledger.read_text()) if ledger.exists() else {}
        check("session recorded as done", rec.get("sess-abc", {}).get("status"), "done")

        proc.terminate()

        # === LOAD-PATH PROOF: with NO env token, the TOKEN STORE is used =====
        # Every case above injects KIPI_LINEAR_AGENT_TOKEN, so none of them proves the
        # refresh path is reachable -- the receiver could read a static token forever
        # and stay green. Grepping that ensure_fresh() appears in the source proves
        # nothing either. This starts a receiver with the env token REMOVED and a real
        # token store on disk, then reads back which credential actually went out on
        # the wire.
        (tmp / "linear-agent-token.json").write_text(json.dumps({
            "access_token": "from-the-token-store",
            "refresh_token": "r0",
            "expires_at": int(time.time()) + 80000,
        }))
        env2 = {k: v for k, v in env.items() if k != "KIPI_LINEAR_AGENT_TOKEN"}
        port2 = free_port()
        proc2 = subprocess.Popen(
            [sys.executable, str(SCRIPT), "serve", "--port", str(port2)],
            env=env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        url2 = f"http://127.0.0.1:{port2}/"
        for _ in range(50):
            try:
                urllib.request.urlopen(url2, data=b"{}", timeout=1); break
            except urllib.error.HTTPError:
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)

        with _ACT_LOCK:
            AUTH_HEADERS.clear()
        ev2 = event(issue="ASK-111", session="sess-token")
        post(url2, ev2, sign(ev2))
        for _ in range(60):
            with _ACT_LOCK:
                if AUTH_HEADERS:
                    break
            time.sleep(0.1)
        with _ACT_LOCK:
            seen = list(AUTH_HEADERS)
        check("no env token -> credential comes from the token store",
              seen[:1], ["from-the-token-store"])
        proc2.terminate()

        fake.shutdown()

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 62)
    for name, ok, got, want in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         got={got!r} want={want!r}")
    print("=" * 62)
    print(f"{len(checks) - len(failures)}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
