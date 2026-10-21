#!/usr/bin/env python3
"""Replay real alert tickets through the sustained-failure rule (ASK-2013).

TWO RULES, and the difference between them is the whole point.

`--rule scoped` (DEFAULT, and what alert-to-linear.py actually ships): the
second-observation requirement applies to ONE fingerprint, the one named by
`SUSTAINED_FINGERPRINT` in alert-to-linear.py. The decision is not restated
here -- this imports `sustained_defers` from that module and calls it, so the
replay scores the predicate production runs rather than a copy that agrees
today and stops describing the system the next time the rule moves.

`--rule global`: the same requirement applied to EVERY fingerprint. This is the
refusal evidence, kept runnable rather than described: it loses 8 of the 11
tickets Sana actually worked and exits 1. It is not what ships, and the reason
the scoped rule is one hardcoded hash instead of a config file.

HOW "FIRED TWICE" IS DECIDED under `--rule global`, strongest evidence first:

  1. `repeat_state.count` from alert-to-linear.py's own fingerprint cache,
     snapshotted into the payload at capture time. This is the producer's own
     counter and the only source that sees a repeat inside the 12h silent
     window. Used ONLY when the state still belongs to this ticket
     (`repeat_state.identifier`): the cache is overwritten when a closed ticket's
     shape recurs, so a count sitting under a LATER identifier is not this
     ticket's history.
  2. A repeat comment on the ticket ("Still firing. N occurrence(s)"), written by
     the repeat branch after 12h.
  3. The same fingerprint owning more than one ticket in the window: the shape
     recurred after a close.

A ticket with none of the three fired once as far as anything in this fleet
records, and the sustained rule would never have created it.

WHAT THIS MEASURED (2026-09-28, 45-day window, 702 alert tickets):
11 tickets were worked; 10 of them came from a shape that fired exactly once.
Recurrence does not separate the work from the noise here, it very nearly
inverts it. The refusal note in `.sana-needs-scope` carries the argument.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PAYLOAD = os.path.join(HERE, "alert-tickets-45d.json")
ALERT_SCRIPT = os.path.join(HERE, "..", "scripts", "alert-to-linear.py")


def _alert_module():
    """alert-to-linear.py, loaded by path because its name carries hyphens."""
    spec = importlib.util.spec_from_file_location("kipi_alert_to_linear",
                                                  ALERT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

FINGERPRINT_RE = re.compile(r"<!--\s*kipi-alert-fingerprint:\s*(?P<fp>[^\s>-]+)")
REPEAT_COMMENT_RE = re.compile(r"Still firing\.\s*(\d+)\s*occurrence", re.I)
ALERT_BODY_RE = re.compile(r"```\n(.*?)\n```", re.DOTALL)

# A ticket in one of these states is one a human took up: worked, not swept.
WORKED_STATE_TYPES = ("completed", "started")


def fingerprint_of(node: dict) -> str:
    if "alert_fingerprint" in node:
        return node["alert_fingerprint"] or ""
    match = FINGERPRINT_RE.search(node.get("description") or "")
    return match.group("fp") if match else ""


def alert_text(node: dict) -> str:
    match = ALERT_BODY_RE.search(node.get("description") or "")
    return " ".join((match.group(1) if match else "").split())


def has_repeat_comment(node: dict) -> bool:
    """Pre-computed by capture_alert_tickets.reduce_node on a reduced payload.

    The comment BODY names client instances and this repo is public, so the
    stored payload carries the boolean and not the text. The raw branch stays
    for a payload captured before the reduction existed.
    """
    if "repeat_comment" in node:
        return bool(node["repeat_comment"])
    for comment in ((node.get("comments") or {}).get("nodes") or []):
        if REPEAT_COMMENT_RE.search(comment.get("body") or ""):
            return True
    return False


def own_repeat_count(node: dict) -> int | None:
    """The producer's count for THIS ticket, or None when it cannot say."""
    state = node.get("repeat_state") or {}
    count = state.get("count")
    if count is None:
        return None
    if state.get("identifier") != node.get("identifier"):
        return None
    return int(count)


def fired_twice(node: dict, siblings: int) -> bool:
    count = own_repeat_count(node)
    if count is not None and count >= 2:
        return True
    if has_repeat_comment(node):
        return True
    return siblings > 1


def replay_scoped(alerts: list) -> tuple:
    """What alert-to-linear.py ships: the rule, on one fingerprint.

    Walks the tickets in creation order with the same per-fingerprint counter
    the live state file keeps, and asks the PRODUCTION predicate whether each
    observation opens a ticket. A filed ticket resets the counter, because the
    create path in alert-to-linear.py replaces the whole state dict and so drops
    `pending_count` -- each recurrence after a close earns its own ticket again.

    Every fingerprint the predicate does not name files on observation 1, which
    is today's behaviour, unchanged.
    """
    defers = _alert_module().sustained_defers
    pending: dict = defaultdict(int)
    filed, deferred = [], []
    for node in sorted(alerts, key=lambda n: n.get("createdAt") or ""):
        fp = fingerprint_of(node)
        pending[fp] += 1
        if defers(fp, pending[fp]):
            deferred.append(node)
            continue
        pending[fp] = 0
        filed.append(node)
    return filed, deferred


def replay_global(alerts: list) -> tuple:
    """The rule on EVERY fingerprint. The refusal evidence, not what ships."""
    by_fp: dict = defaultdict(list)
    for node in alerts:
        by_fp[fingerprint_of(node)].append(node)
    filed, deferred = [], []
    for tickets in by_fp.values():
        for node in tickets:
            (filed if fired_twice(node, len(tickets)) else deferred).append(node)
    return filed, deferred


def replay(nodes: list, rule: str = "scoped") -> dict:
    alerts = [n for n in nodes if fingerprint_of(n)]
    filed, deferred = (replay_scoped(alerts) if rule == "scoped"
                       else replay_global(alerts))
    # Tickets whose description merely MENTIONS the marker (engineering issues
    # about the alert path) carry no fingerprint and are not alert output. They
    # are excluded rather than scored: counting them as lost work would credit
    # the rule with destroying tickets it never had the chance to file.
    return {"filed": filed, "deferred": deferred,
            "not_alerts": [n for n in nodes if not fingerprint_of(n)]}


def summarize(payload: dict, rule: str = "scoped") -> dict:
    nodes = payload["nodes"]
    result = replay(nodes, rule)
    deferred_ids = {n["identifier"] for n in result["deferred"]}
    alerts = result["filed"] + result["deferred"]

    worked = [n for n in alerts
              if (n.get("state") or {}).get("type") in WORKED_STATE_TYPES]
    worked_lost = [n for n in worked if n["identifier"] in deferred_ids]
    canceled = [n for n in alerts
                if (n.get("state") or {}).get("type") == "canceled"]
    canceled_deferred = [n for n in canceled if n["identifier"] in deferred_ids]

    scoped_fp = _alert_module().SUSTAINED_FINGERPRINT
    on_fp = [n for n in alerts if fingerprint_of(n) == scoped_fp]
    fp_canceled = [n for n in on_fp
                   if (n.get("state") or {}).get("type") == "canceled"]

    return {
        "rule": rule,
        "scoped_fingerprint": scoped_fp,
        "scoped_fp_total": len(on_fp),
        "scoped_fp_never_filed": len([n for n in on_fp
                                      if n["identifier"] in deferred_ids]),
        "scoped_fp_canceled": len(fp_canceled),
        "scoped_fp_canceled_never_filed": len(
            [n for n in fp_canceled if n["identifier"] in deferred_ids]),
        "alerts": len(alerts),
        "not_alerts": len(result["not_alerts"]),
        "filed": len(result["filed"]),
        "deferred": len(result["deferred"]),
        "worked_total": len(worked),
        "worked_kept": len(worked) - len(worked_lost),
        "worked_lost": [n["identifier"] for n in worked_lost],
        "worked_lost_text": [(n["identifier"], alert_text(n)[:110])
                             for n in worked_lost],
        "canceled_total": len(canceled),
        "canceled_never_filed": len(canceled_deferred),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default=DEFAULT_PAYLOAD)
    ap.add_argument("--rule", choices=("scoped", "global"), default="scoped",
                    help="scoped = what ships (one fingerprint); "
                         "global = the measured refusal, every fingerprint")
    args = ap.parse_args()
    with open(args.payload, encoding="utf-8") as fh:
        payload = json.load(fh)
    s = summarize(payload, args.rule)
    print(f"payload captured_at={payload.get('captured_at')} "
          f"window={payload.get('days')}d rule={s['rule']}")
    print(f"  alert tickets            : {s['alerts']} "
          f"(+{s['not_alerts']} non-alert issues that only mention the marker)")
    print(f"  would still be filed     : {s['filed']}")
    print(f"  never filed              : {s['deferred']}")
    print(f"  worked (completed/started): {s['worked_total']}, "
          f"kept {s['worked_kept']}, LOST {len(s['worked_lost'])}")
    for ident, text in s["worked_lost_text"]:
        print(f"      {ident}  {text}")
    print(f"  canceled: {s['canceled_total']}, of which never filed "
          f"{s['canceled_never_filed']}")
    print(f"  scoped fingerprint {s['scoped_fingerprint']}: "
          f"{s['scoped_fp_total']} ticket(s), {s['scoped_fp_canceled']} canceled")
    print(f"      never filed under this rule: {s['scoped_fp_never_filed']} "
          f"({s['scoped_fp_canceled_never_filed']} of them canceled)")
    gate = not s["worked_lost"]
    print(f"  GATE (every worked ticket survives): {'PASS' if gate else 'FAIL'}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
