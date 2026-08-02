"""Vercel function: the Mac drains through here. Bearer-authenticated, thin.

Two endpoints in one file because they share the auth check:
  POST /api/poll  -> the pending events
  POST /api/ack   -> remove one, by key

WHY THIS NEEDS ITS OWN SECRET, SEPARATE FROM THE WEBHOOK SECRET
---------------------------------------------------------------
The webhook secret is shared with Linear, so anyone who can make Linear send a webhook
influences what enters the queue. Reading the queue is a different privilege: the
events contain issue identifiers and prompt text. Reusing one secret for both would
mean a leak of the Linear-side value also exposes everything queued. Separate secret,
separate blast radius.

Comparison is constant-time. A bearer check that leaks timing on a public endpoint is
a real, well-understood way to recover a token byte by byte.
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_lib"))

import linear_relay_core as core          # noqa: E402
import linear_relay_store as store_mod    # noqa: E402


class handler(BaseHTTPRequestHandler):    # noqa: N801 -- Vercel requires this name

    def do_POST(self):  # noqa: N802
        expected = os.environ.get("KIPI_RELAY_TOKEN", "")
        if not expected:
            self._reply(500, {"error": "relay not configured"})
            return

        presented = (self.headers.get("Authorization", "")
                     .removeprefix("Bearer ").strip())
        if not hmac.compare_digest(presented, expected):
            self._reply(401, {"error": "unauthorized"})
            return

        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}

        store = store_mod.RedisRestStore()

        # Vercel routes by filename, so both verbs arrive here; the path decides.
        if self.path.rstrip("/").endswith("/ack"):
            key = payload.get("key")
            if not key:
                self._reply(400, {"error": "no key"})
                return
            core.ack(store, key)
            self._reply(200, {"ok": True})
            return

        fresh, expired = core.drain(store)
        self._reply(200, {
            "events": [{
                "key": e["key"],
                # latin-1 round trip keeps the body byte-identical across JSON.
                # The Mac decodes it back and re-verifies the signature itself.
                "raw": e["raw"].decode("latin-1"),
                "signature": e["signature"],
            } for e in fresh],
            "expired": expired,
        })

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass
