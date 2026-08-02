#!/usr/bin/env python3
"""End-to-end chain: signed webhook -> relay queue -> poller -> local runner.

Pairs with: linear-relay-core.py + linear-agent-poller.py + linear-agent-receiver.py

This is the only test that exercises the ACTUAL shape of the design: three components
on two machines, joined by raw bytes that must survive intact. Each piece has its own
suite; none of them can catch a seam defect between the pieces.

THE CASE THIS EXISTS FOR
------------------------
`relay delivers a forged event`. The relay verifies at the edge, so in the happy path
the poller's own check is redundant and would stay green forever if it were deleted.
The whole point of verifying twice is the case where the relay is WRONG -- compromised,
misconfigured, or replaced -- and hands the Mac something Linear never signed. Without
a test that simulates a lying relay, defence-in-depth is decoration. Here the relay is
made to inject a forged event directly into the queue, bypassing admit(), and the
poller must refuse to run it AND refuse to ack it.

No network, no Linear, no real runner.
"""
import hashlib
import hmac
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SECRET = "chain-test-secret-not-real"

TMP = Path(tempfile.mkdtemp(prefix="relay-chain-"))
RECEIPT = TMP / "runner-receipt.txt"
RUNNER = TMP / "fake-runner.sh"
RUNNER.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{RECEIPT}"\necho ok\n')
RUNNER.chmod(0o755)

# Env must be set BEFORE the receiver is imported: it resolves RUNNER at module load.
os.environ.update({
    "KIPI_LINEAR_AGENT_RUNNER": f"bash {RUNNER}",
    "KIPI_LINEAR_AGENT_STATE": str(TMP),
    "KIPI_LINEAR_AGENT_TOKEN": "test-token",
    "KIPI_LINEAR_API": "http://127.0.0.1:1/graphql",   # unreachable on purpose
    "KIPI_NOTIFY": "/usr/bin/true",
    "KIPI_LINEAR_WEBHOOK_SECRET": SECRET,
})


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RELAY = load("linear_relay_core", "linear-relay-core.py")
RECEIVER = load("linear_agent_receiver", "linear-agent-receiver.py")
# Overridable so a MUTANT poller can be driven through this same chain. The poller's
# own verification is REDUNDANT on the happy path, so deleting it leaves every other
# case green -- only a lying-relay case plus a mutation run proves it is load-bearing.
POLLER = load("linear_agent_poller",
              os.environ.get("KIPI_POLLER_UNDER_TEST", "linear-agent-poller.py"))


def body(issue, session, ts=None) -> bytes:
    base = ts if ts is not None else time.time()
    return json.dumps({
        "type": "AgentSessionEvent", "action": "created",
        "webhookTimestamp": int(base * 1000),
        "agentSession": {"id": session, "issue": {"identifier": issue}},
    }).encode()


def sign(b: bytes, secret=SECRET) -> str:
    return hmac.new(secret.encode(), b, hashlib.sha256).hexdigest()


def make_transport(store):
    """Speaks the relay's HTTP contract straight against the queue, no socket."""
    def transport(path, payload=None):
        if path == "/api/poll":
            fresh, _ = RELAY.drain(store)
            return {"events": [{"key": e["key"],
                                "raw": e["raw"].decode("latin-1"),
                                "signature": e["signature"]} for e in fresh]}
        if path == "/api/ack":
            RELAY.ack(store, payload["key"])
            return {"ok": True}
        raise ValueError(path)
    return transport


def main() -> int:
    failures, checks = [], []

    def check(name, got, want):
        ok = got == want
        checks.append((name, ok, got, want))
        if not ok:
            failures.append(name)

    V = RECEIVER.verify_signature

    try:
        # === HAPPY PATH: the full chain end to end ====================
        store = RELAY.MemoryStore()
        transport = make_transport(store)

        b1 = body("ASK-900", "s-chain")
        code, _ = RELAY.admit(b1, sign(b1), SECRET, store, V)
        check("relay accepts the signed delegation", code, 200)
        check("it is durably queued", store.count(), 1)

        result = POLLER.poll_once(receiver=RECEIVER, transport=transport, secret=SECRET)
        check("poller ran one delegation", result["ran"], 1)

        ran = RECEIPT.read_text() if RECEIPT.exists() else ""
        check("the local runner got the delegated issue", "--issue ASK-900" in ran, True)
        check("acked after the run, queue now empty", store.count(), 0)

        # === A LYING RELAY: forged event injected past admit() ========
        # Bypasses admit entirely, exactly as a compromised relay would.
        store2 = RELAY.MemoryStore()
        transport2 = make_transport(store2)
        forged = body("ASK-666", "s-forged")
        store2.put("s-forged:created", json.dumps({
            "raw": forged.decode("latin-1"),
            "signature": "forged-not-a-real-signature",
            "received_at": time.time(),
        }))
        check("forged event is sitting in the queue", store2.count(), 1)

        before = RECEIPT.read_text() if RECEIPT.exists() else ""
        result = POLLER.poll_once(receiver=RECEIVER, transport=transport2, secret=SECRET)
        after = RECEIPT.read_text() if RECEIPT.exists() else ""

        check("poller REFUSED to run it", result["ran"], 0)
        check("poller counted it rejected", result["rejected"], 1)
        check("runner never saw ASK-666", "ASK-666" in after, False)
        check("nothing else ran either", after, before)
        # Not acking is deliberate: the event is evidence about the relay.
        check("forged event was NOT acked away", store2.count(), 1)

        # === WRONG SECRET: relay and Mac disagree ====================
        # Signed with a different secret than the Mac holds. Must not run.
        store3 = RELAY.MemoryStore()
        transport3 = make_transport(store3)
        b3 = body("ASK-777", "s-wrong")
        store3.put("s-wrong:created", json.dumps({
            "raw": b3.decode("latin-1"),
            "signature": sign(b3, "a-different-secret"),
            "received_at": time.time(),
        }))
        result = POLLER.poll_once(receiver=RECEIVER, transport=transport3, secret=SECRET)
        check("mismatched secret does not run", result["ran"], 0)
        check("mismatched secret stays queued", store3.count(), 1)

        # === AT-LEAST-ONCE: a failed run must NOT be acked ============
        store4 = RELAY.MemoryStore()
        transport4 = make_transport(store4)
        b4 = body("ASK-800", "s-fail")
        RELAY.admit(b4, sign(b4), SECRET, store4, V)

        class Exploding:
            verify_signature = staticmethod(RECEIVER.verify_signature)

            @staticmethod
            def handle_event(_payload):
                raise RuntimeError("run blew up")

        result = POLLER.poll_once(receiver=Exploding, transport=transport4, secret=SECRET)
        check("a crashed run reports zero ran", result["ran"], 0)
        check("a crashed run leaves the delegation QUEUED for retry",
              store4.count(), 1)

    finally:
        shutil.rmtree(TMP, ignore_errors=True)

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
