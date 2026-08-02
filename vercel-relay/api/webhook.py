"""Vercel function: the public inbound edge. THIN -- all logic lives in the tested core.

This file deliberately contains no queue logic, no bound, and no verification of its
own. It binds HTTP to `admit()` and returns what admit decided. Every rule that matters
(signature first, then parse, then dedupe, then bound, then persist) is in
linear-relay-core.py where it is covered by 25 assertions and 7 mutants. A wrapper that
grows its own logic is a second implementation nobody tests.

WHY THE BODY IS READ AS RAW BYTES AND NEVER PARSED HERE
-------------------------------------------------------
Linear signs the raw request bytes. Parsing and re-serializing anywhere in this path
changes the digest and every real delegation would then fail verification on the Mac.
The bytes go in raw and come out raw.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_lib"))

import linear_relay_core as core          # noqa: E402
import linear_relay_store as store_mod    # noqa: E402
import linear_agent_verify as verify      # noqa: E402


class handler(BaseHTTPRequestHandler):    # noqa: N801 -- Vercel requires this name

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        signature = self.headers.get("Linear-Signature", "")
        secret = os.environ.get("KIPI_LINEAR_WEBHOOK_SECRET", "")

        if not secret:
            # Fail CLOSED. A relay with no secret cannot verify anything, and an
            # unverified public queue is strictly worse than an offline one.
            self._reply(500, {"error": "relay not configured"})
            return

        status, reason = core.admit(
            raw, signature, secret, store_mod.RedisRestStore(), verify.verify_signature)

        # 503 on a full queue is Linear's retry signal. Passing admit's status straight
        # through is the point: the refuse-don't-evict decision is made in the tested
        # core, and this wrapper must not soften it into a 200.
        self._reply(status, {"status": reason})

    def do_GET(self):  # noqa: N802
        # Health only. Never reveals queue contents.
        self._reply(200, {"ok": True, "service": "linear-agent-relay"})

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass
