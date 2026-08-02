#!/usr/bin/env python3
"""Token rotation suite for linear-agent-token.py. Against a fake OAuth server only.

Pairs with: q-system/.q-system/scripts/linear-agent-token.py

THE FAILURE THIS EXISTS TO PREVENT
----------------------------------
Case 1 below is the observed failure, asserted first: a token past its 24h life with
no way to renew leaves the agent offline, and the only thing standing between that and
a silently dead board is a page. So the suite asserts the PAGE CONTENT, not the exit
code. slack-notify.sh is a deliberate silent no-op when unconfigured and always exits
0, so "we called the pager" is unfalsifiable from an exit status -- KIPI_NOTIFY is
pointed at a recorder and the message text is read back from a file.

THE ROTATION HAZARD
-------------------
Linear rotates the refresh token on every use. The token we send is dead the instant
the response comes back. So the suite checks two separate things that are easy to
conflate: that a refresh HAPPENED, and that the NEW refresh token actually landed on
disk. A build that refreshes correctly but persists nothing passes the first and fails
the second, and in production it would work exactly once.

Nothing here touches the real Linear, the real token file, or the real pager.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MODULE = Path(os.environ.get(
    "KIPI_TOKEN_MODULE_UNDER_TEST",
    Path(__file__).resolve().parent.parent / "linear-agent-token.py"))

SEEN_REFRESH = []        # refresh_tokens the fake server was presented with
_LOCK = threading.Lock()
MODE = {"fail": None}    # None | "invalid_grant" | "server_error"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeOAuth(BaseHTTPRequestHandler):
    """Stands in for api.linear.app/oauth/token. Rotates like the real thing."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        params = dict(p.split("=", 1) for p in raw.split("&") if "=" in p)
        with _LOCK:
            SEEN_REFRESH.append(params.get("refresh_token", ""))

        if MODE["fail"] == "invalid_grant":
            self._send(400, {"error": "invalid_grant"})
            return
        if MODE["fail"] == "server_error":
            self._send(500, {"error": "boom"})
            return

        n = len(SEEN_REFRESH)
        self._send(200, {
            "access_token": f"access-{n}",
            "refresh_token": f"refresh-{n}",      # ROTATED, as Linear does
            "expires_in": 86399,
            "token_type": "Bearer",
            "scope": "read write app:assignable",
        })

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="linear-token-test-"))
    failures, checks = [], []

    def check(name, got, want):
        ok = got == want
        checks.append((name, ok, got, want))
        if not ok:
            failures.append(name)

    try:
        port = free_port()
        srv = HTTPServer(("127.0.0.1", port), FakeOAuth)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        # A recorder in place of the real pager. This is the ONLY way to prove a page
        # happened -- the real one exits 0 whether it sent anything or not.
        pagelog = tmp / "pages.txt"
        pager = tmp / "fake-pager.sh"
        pager.write_text(f'#!/usr/bin/env bash\necho "$1" >> "{pagelog}"\n')
        pager.chmod(0o755)

        env = {
            **os.environ,
            "KIPI_LINEAR_OAUTH_URL": f"http://127.0.0.1:{port}/oauth/token",
            "KIPI_LINEAR_AGENT_STATE": str(tmp),
            "KIPI_NOTIFY": str(pager),
        }
        tokfile = tmp / "linear-agent-token.json"

        def run(cmd):
            return subprocess.run([sys.executable, str(MODULE), cmd],
                                  env=env, capture_output=True, text=True)

        def pages():
            return pagelog.read_text() if pagelog.exists() else ""

        def write_token(expires_in, refresh_token="refresh-0"):
            tokfile.write_text(json.dumps({
                "access_token": "access-0",
                "refresh_token": refresh_token,
                "expires_at": int(time.time()) + expires_in,
                "obtained_at": int(time.time()),
            }))

        # === CASE 1: THE OBSERVED FAILURE -- no token at all =============
        # The assertion here was originally `page-fired OR stderr-mentions-it`, which
        # is unfalsifiable: stderr always mentions it, so the page half was never
        # tested. An `or` across two signals passes on the weaker one and hides the
        # stronger one failing. Asserting the PAGE only.
        r = run("get")
        check("no token on disk -> exit 3 (reauth)", r.returncode, 3)
        check("no token on disk -> PAGES the founder", pagelog.exists(), True)
        check("that page names re-authorization", "authoriz" in pages(), True)

        # === CASE 2: a healthy token is used, NOT refreshed ==============
        # Refreshing early is not harmless: every refresh burns a rotation, and a bug
        # that refreshes on every call turns one credential into a rotation treadmill.
        write_token(expires_in=80000)
        before = len(SEEN_REFRESH)
        r = run("get")
        check("healthy token -> exit 0", r.returncode, 0)
        check("healthy token -> returned as-is", r.stdout.strip(), "access-0")
        check("healthy token -> NO refresh call burned", len(SEEN_REFRESH), before)

        # === CASE 3: near expiry -> refresh, and ROTATION IS PERSISTED ===
        write_token(expires_in=600, refresh_token="refresh-0")
        r = run("get")
        check("near-expiry -> exit 0", r.returncode, 0)
        check("near-expiry -> a NEW access token is returned",
              r.stdout.strip().startswith("access-"), True)
        check("near-expiry -> the stored refresh token was sent",
              SEEN_REFRESH[-1], "refresh-0")

        saved = json.loads(tokfile.read_text())
        # The two easily-conflated checks. A build that refreshes but never persists
        # passes the first and fails these.
        check("ROTATION PERSISTED: new refresh token on disk",
              saved["refresh_token"] != "refresh-0", True)
        check("PERSIST BEFORE USE: returned token is the one on disk",
              saved["access_token"], r.stdout.strip())
        check("expiry advanced past the skew window",
              saved["expires_at"] - int(time.time()) > 3600, True)
        check("credential file is 0600", oct(tokfile.stat().st_mode)[-3:], "600")

        # === CASE 4: dead refresh token -> reauth, and it PAGES ==========
        MODE["fail"] = "invalid_grant"
        write_token(expires_in=60, refresh_token="dead-token")
        pagelog.unlink(missing_ok=True)
        r = run("get")
        check("dead refresh token -> exit 3 (reauth)", r.returncode, 3)
        check("dead refresh token -> PAGES", pagelog.exists(), True)
        check("page names re-authorization as the fix",
              "re-authorize" in pages(), True)
        check("page says delegations will sit unanswered",
              "unanswered" in pages(), True)
        # The credential must survive a REJECTED refresh untouched. Overwriting it
        # here would destroy the evidence the founder needs to recover.
        still = json.loads(tokfile.read_text())
        check("rejected refresh did NOT clobber the stored token",
              still["refresh_token"], "dead-token")

        # === CASE 5: endpoint down -> environmental, still loud ==========
        MODE["fail"] = "server_error"
        write_token(expires_in=60, refresh_token="refresh-x")
        pagelog.unlink(missing_ok=True)
        r = run("get")
        check("endpoint 5xx -> exit 4 (token error, not reauth)", r.returncode, 4)
        check("endpoint 5xx -> PAGES", pagelog.exists(), True)

        MODE["fail"] = None
        srv.shutdown()

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 66)
    for name, ok, got, want in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         got={got!r} want={want!r}")
    print("=" * 66)
    print(f"{len(checks) - len(failures)}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
