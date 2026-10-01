#!/usr/bin/env python3
"""Capture the real alert tickets of the last N days into a replay payload.

PROVENANCE, not a fixture someone typed. `fixtures-from-producers`: the replay
that decides whether the Step 7 rule keeps the tickets Sana actually worked has
to run against the board's own rows, so this script is the producer and
`alert-tickets-45d.json` beside it is its only output.

Read-only. One query, paginated. Run by hand when the payload needs refreshing:

    python3 q-system/.q-system/tests/capture_alert_tickets.py --days 45
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
DEFAULT_OUT = os.path.join(HERE, "alert-tickets-45d.json")

QUERY = """
query($since: DateTimeOrDuration!, $after: String) {
  issues(first: 250, after: $after,
         filter: { createdAt: { gte: $since },
                   description: { contains: "kipi-alert-fingerprint" } }) {
    pageInfo { hasNextPage endCursor }
    nodes {
      identifier
      createdAt
      state { name type }
      description
      comments(first: 50) { nodes { createdAt body } }
    }
  }
}
"""


def _linear():
    path = os.path.join(SCRIPTS, "linear-sync.py")
    spec = importlib.util.spec_from_file_location("kipi_linear_sync", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FINGERPRINT_RE = re.compile(r"<!--\s*kipi-alert-fingerprint:\s*(?P<fp>[^\s>-]+)")
REPEAT_COMMENT_RE = re.compile(r"Still firing\.\s*(\d+)\s*occurrence", re.I)

# alert-to-linear.py's own state dir (_state_dir). Named here rather than
# imported because that module's name carries hyphens; the path is one string in
# one place and a drift between the two is a one-line fix.
ALERT_STATE_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "kipi", "alert-to-linear")


def _repeat_state(fp: str) -> dict:
    """The producer's OWN counter for this fingerprint, or {}.

    THIS IS THE ONLY HONEST SOURCE for "did this shape fire twice".
    alert-to-linear.py stays silent on a repeat inside
    REPEAT_COMMENT_AFTER_HOURS (12), so the board shows nothing for a condition
    that fired five times in one hour. Reading the board alone would score those
    as single failures and make any sustained-failure replay wrong in the
    direction that flatters the rule.

    Snapshotted INTO the payload on purpose: the cache is live and mutable, so a
    replay that read it at test time would give a different answer next week.
    """
    path = os.path.join(ALERT_STATE_DIR, f"{fp}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {"count": state.get("count"), "identifier": state.get("identifier"),
            "first_at": state.get("first_at"), "last_at": state.get("last_at")}


# WHAT A TICKET IS REDUCED TO BEFORE IT IS WRITTEN DOWN.
#
# THIS REPO IS PUBLIC and alert bodies name client instances by their real
# names -- the `[instance]` prefix alert-to-linear.py writes into every title.
# The first version of this script stored `description` and `comments` verbatim
# and the pre-commit client-name guard refused the payload outright, naming nine
# client instances in one file. It was right to.
#
# So the payload keeps only what the replay SCORES on, and the names are gone
# structurally rather than by find-and-replace: a redaction that greps for known
# names ships every name nobody thought to list.
#
# The one thing lost is the human-readable text of a ticket the rule would have
# destroyed. That text was diagnostic, never part of any assertion.
def reduce_node(node: dict) -> dict:
    """One ticket, stripped to the fields the sustained-rule replay reads."""
    return {
        "identifier": node.get("identifier"),
        "createdAt": node.get("createdAt"),
        "state": {"type": (node.get("state") or {}).get("type")},
        "alert_fingerprint": node.get("alert_fingerprint", ""),
        "repeat_state": node.get("repeat_state") or {},
        # Pre-computed here because the regex needs the comment BODY, which is
        # exactly what must not be stored.
        #
        # AND THEREFORE NOT RECOMPUTABLE. An already-reduced node has no
        # `comments` left, so re-deriving would read an empty string and answer
        # False for every ticket. Running `--reduce` twice did exactly that:
        # 127 of 704 rows flipped true -> false, silently, with the replay's
        # numbers changing underneath a fixture that still looked captured.
        # A second pass has to be a no-op, so the already-computed value wins.
        "repeat_comment": (node["repeat_comment"] if "repeat_comment" in node
                           else bool(REPEAT_COMMENT_RE.search(" ".join(
                               (c.get("body") or "")
                               for c in ((node.get("comments") or {}).get("nodes") or []))))),
    }


def portable(path: str) -> str:
    """Collapse the home prefix, because the capture is COMMITTED.

    The payload lands in a public repo and rides kipi update to every instance.
    validate-separation.py's full skeleton sweep fails on an absolute home path
    anywhere under q-system/, and it did on the first capture -- state_dir was
    the one field the reduction left whole, since it names no ticket and no
    instance. It still names the machine.

    Redacted at the producer and not only in the committed file: the whole point
    of a capture script is that a re-run reproduces the payload, so a fix that
    lives only in the artifact is one `--days 45` away from being undone.
    """
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def reduce_payload(payload: dict) -> dict:
    return {**payload, "reduced": True,
            "state_dir": portable(payload.get("state_dir") or ""),
            "nodes": [reduce_node(n) for n in payload.get("nodes") or []]}


def capture(days: int) -> dict:
    ln = _linear()
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(days=days)).isoformat()
    nodes: list = []
    after = None
    while True:
        page = ln.graphql(QUERY, {"since": since, "after": after})["issues"]
        nodes.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    for node in nodes:
        match = FINGERPRINT_RE.search(node.get("description") or "")
        node["alert_fingerprint"] = match.group("fp") if match else ""
        node["repeat_state"] = (_repeat_state(node["alert_fingerprint"])
                                if node["alert_fingerprint"] else {})
    return {"captured_at": now.isoformat(), "since": since,
            "days": days, "state_dir": portable(ALERT_STATE_DIR), "nodes": nodes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--reduce", metavar="PATH",
                    help="reduce an already-captured payload in place instead "
                         "of hitting Linear (offline, deterministic)")
    args = ap.parse_args()
    if args.reduce:
        with open(args.reduce, encoding="utf-8") as fh:
            payload = reduce_payload(json.load(fh))
        with open(args.reduce, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        print(f"reduced {len(payload['nodes'])} ticket(s) in {args.reduce}")
        return 0
    payload = reduce_payload(capture(args.days))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    counts: dict = {}
    for node in payload["nodes"]:
        key = (node.get("state") or {}).get("type") or "?"
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(payload['nodes'])} alert tickets in {args.days}d -> {args.out}")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
