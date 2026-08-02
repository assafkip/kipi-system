#!/usr/bin/env python3
"""Suite for linear-relay-core.py. No network, no live queue, no Linear.

Pairs with: q-system/.q-system/scripts/linear-relay-core.py

THE CENTRAL PROPERTY, and the one most likely to rot silently
-------------------------------------------------------------
Linear signs the RAW request bytes. The relay stores them, ships them to the Mac, and
the Mac verifies again -- so any byte the body loses in transit destroys the digest and
the Mac rejects every real delegation. The failure would look like "Sana ignores me",
which is indistinguishable from the outage this whole queue exists to prevent.

So the suite does not assert "the body looks the same". It re-runs the REAL verifier
over the drained bytes and requires it to pass. That is the only assertion that
actually proves the round trip, and it is why the raw body is stored as latin-1 rather
than parsed and re-serialized.

The verifier under test is the receiver's own, imported rather than reimplemented --
one definition of the signature check across both machines. A second copy would drift
and the drift would only show up in production.
"""
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RELAY = load("linear_relay_core", os.environ.get(
    "KIPI_RELAY_MODULE_UNDER_TEST", "linear-relay-core.py"))
RECEIVER = load("linear_agent_receiver", "linear-agent-receiver.py")

SECRET = "relay-test-secret-not-real"


def body(issue="ASK-1", session="s1", action="created", age_ms=0, ts=None) -> bytes:
    """`ts` is the wall-clock at which this event is claimed to have been SENT.

    It must track the `now` passed to admit(). The first version of this helper always
    stamped the current time, so a test that admitted "in the past" built a physically
    impossible event -- signed now, arriving 25 hours ago -- and the replay guard
    correctly refused it. Two cases failed for that reason and the code was right both
    times. A fixture whose shape cannot occur in production tests nothing.
    """
    base = ts if ts is not None else time.time()
    return json.dumps({
        "type": "AgentSessionEvent",
        "action": action,
        "webhookTimestamp": int(base * 1000) - age_ms,
        "agentSession": {"id": session, "issue": {"identifier": issue}},
    }).encode()


def sign(b: bytes) -> str:
    return hmac.new(SECRET.encode(), b, hashlib.sha256).hexdigest()


def main() -> int:
    failures, checks = [], []

    def check(name, got, want):
        ok = got == want
        checks.append((name, ok, got, want))
        if not ok:
            failures.append(name)

    V = RECEIVER.verify_signature

    # === forged input must not reach storage ==========================
    store = RELAY.MemoryStore()
    code, reason = RELAY.admit(body(), "deadbeef", SECRET, store, V)
    check("forged signature -> 401", code, 401)
    check("forged signature consumed NO storage", store.count(), 0)

    # A replayed-but-validly-signed event is the case an attacker actually has.
    stale = body(age_ms=120_000)
    code, _ = RELAY.admit(stale, sign(stale), SECRET, store, V)
    check("replayed event -> 401", code, 401)
    check("replayed event consumed NO storage", store.count(), 0)

    # === the happy path, and the byte-exactness that carries it =======
    store = RELAY.MemoryStore()
    b1 = body(issue="ASK-100", session="s-alpha")
    code, reason = RELAY.admit(b1, sign(b1), SECRET, store, V)
    check("signed event -> 200", code, 200)
    check("signed event queued", store.count(), 1)

    fresh, expired = RELAY.drain(store)
    check("one event drains", len(fresh), 1)
    check("nothing expired", expired, 0)

    # THE assertion. Not "bytes look equal" -- the real verifier must still pass.
    drained = fresh[0]
    ok, why = V(drained["raw"], drained["signature"], SECRET)
    check("SIGNATURE SURVIVES THE QUEUE ROUND TRIP", ok, True)
    check("drained body is byte-identical", drained["raw"], b1)

    # === retries must collapse, or one delegation becomes many runs ====
    # `count == 1` is NOT sufficient here and a mutation run proved it: put() on the
    # same key overwrites, so the count stays 1 even with the dedupe check deleted.
    # The damage a retry actually does is RESET received_at -- under a retry storm the
    # entry's age never advances, so it can never expire and its queue position keeps
    # jumping. Assert the age is untouched, which only holds if the retry was refused.
    age_before = json.loads(store.get("s-alpha:created"))["received_at"]
    # +5s, not +500s: a retry must land INSIDE the 60s replay window or the signature
    # check refuses it first and dedupe is never reached. Third time this fixture trap
    # has bitten in one file -- the arrival time and the signed timestamp are one fact,
    # not two independent knobs.
    code, reason = RELAY.admit(b1, sign(b1), SECRET, store, V, now=age_before + 5)
    check("duplicate retry -> 200", code, 200)
    check("duplicate did NOT enqueue twice", store.count(), 1)
    check("duplicate is NAMED as such, not silently re-queued",
          "duplicate" in reason, True)
    check("duplicate did NOT reset the entry's age",
          json.loads(store.get("s-alpha:created"))["received_at"], age_before)

    # but a genuinely different action on the same session is new work
    b2 = body(issue="ASK-100", session="s-alpha", action="prompted")
    RELAY.admit(b2, sign(b2), SECRET, store, V)
    check("different action on same session IS new work", store.count(), 2)

    # === the bound: refuse, never silently drop ========================
    store = RELAY.MemoryStore()
    for i in range(RELAY.MAX_QUEUE_DEPTH):
        bi = body(session=f"s{i}")
        RELAY.admit(bi, sign(bi), SECRET, store, V)
    check("queue filled to cap", store.count(), RELAY.MAX_QUEUE_DEPTH)

    overflow = body(session="s-overflow")
    code, reason = RELAY.admit(overflow, sign(overflow), SECRET, store, V)
    check("overflow -> 503 so Linear RETRIES", code, 503)
    check("overflow did not evict an existing delegation",
          store.count(), RELAY.MAX_QUEUE_DEPTH)
    check("overflow reason says refusing not dropping", "refusing" in reason, True)

    # === stale entries expire on drain, not on write ===================
    store = RELAY.MemoryStore()
    long_ago = time.time() - 90000
    b3 = body(session="s-old", ts=long_ago)
    RELAY.admit(b3, sign(b3), SECRET, store, V, now=long_ago)
    fresh, expired = RELAY.drain(store)
    check("day-old delegation expires rather than firing", len(fresh), 0)
    check("expiry counted", expired, 1)
    check("expired entry removed from store", store.count(), 0)

    # === ack is what removes, and only after the consumer is done ======
    store = RELAY.MemoryStore()
    b4 = body(session="s-ack")
    RELAY.admit(b4, sign(b4), SECRET, store, V)
    fresh, _ = RELAY.drain(store)
    check("drain does NOT remove (a crash mid-run must not lose it)",
          store.count(), 1)
    RELAY.ack(store, fresh[0]["key"])
    check("ack removes", store.count(), 0)

    # === ordering: delegations run in the order they were filed ========
    store = RELAY.MemoryStore()
    now = time.time()
    for i, t in enumerate([now - 10, now - 300, now - 60]):
        bi = body(session=f"ord{i}", ts=t)
        RELAY.admit(bi, sign(bi), SECRET, store, V, now=t)
    fresh, _ = RELAY.drain(store, now=now)
    check("drain returns oldest first",
          [e["key"] for e in fresh], ["ord1:created", "ord2:created", "ord0:created"])

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
