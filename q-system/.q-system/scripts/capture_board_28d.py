#!/usr/bin/env python3
"""One-off capture: the ASK board's last N days, reduced to the fields ASK-2012's
replay needs and NOTHING else.

WHY THIS EXISTS AS A SCRIPT RATHER THAN A PASTED PAYLOAD. The replay fixture has
to come from the producer (the live board), not from an invention, and this repo
is PUBLIC -- validate-separation refuses client names and home paths under
q-system/. So the capture is derived at the source: a title never leaves this
process, only `fingerprint(title)`, which is the same one-way hash
alert-to-linear.py already keys its dedup on. Provenance (query, capture time,
row counts) is written INTO the fixture so a later reader can tell what it is.

Run:  python3 capture_board_28d.py [--days 28] [--out <path>]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str, mod_name: str):
    path = os.path.join(HERE, name)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ISSUES_QUERY = """
query($t: String!, $after: String, $since: DateTimeOrDuration!) {
  issues(filter: { team: { key: { eq: $t } }, createdAt: { gte: $since } },
         first: 250, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      identifier title createdAt
      state { type }
      labels { nodes { name } }
      botActor { name }
      description
    }
  }
}
"""

# FILER CLASSES, from ASK-2006's taxonomy. Each is matched on a mark the PRODUCER
# writes, never on prose a human could have typed the same way:
#   alert        alert-to-linear.py stamps `<!-- kipi-alert-fingerprint: ... -->`
#   spillover    prd_runner.py titles every row `spillover sp-<id> ...`
#   lgtm         the lgtm bot's own ticket prefix
#   radar        the radar bots' own prefix
#   fleet-health the fleet health sweeps
# Anything unmatched is `other` and stays visible as `other` -- a bucket that
# quietly absorbs unknown producers would make the per-filer cap meaningless.
_FILER_RULES = [
    ("alert", re.compile(r"<!--\s*kipi-alert-fingerprint:", re.I), "description"),
    ("spillover", re.compile(r"^spillover\s+sp-[0-9a-f]+", re.I), "title"),
    ("lgtm", re.compile(r"^\s*(?:\[[^\]]+\]\s*)?lgtm\b", re.I), "title"),
    ("radar", re.compile(r"\bradar\b", re.I), "title"),
    ("fleet-health", re.compile(r"\bfleet[- ]health\b|\bdeadman\b|\bheartbeat\b", re.I),
     "title"),
]


def classify(title: str, description: str) -> str:
    fields = {"title": title or "", "description": description or ""}
    for name, pattern, field in _FILER_RULES:
        if pattern.search(fields[field]):
            return name
    return "other"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--out", default=os.path.join(
        HERE, "..", "tests", "fixtures", "filer-cap-replay-28d.json"))
    args = ap.parse_args(argv[1:])

    ln = _load("linear-sync.py", "kipi_linear_sync")
    alert = _load("alert-to-linear.py", "kipi_alert_to_linear")

    captured_at = datetime.datetime.now(datetime.timezone.utc)
    since = (captured_at - datetime.timedelta(days=args.days)).isoformat()

    nodes: list = []
    after = None
    while True:
        page = ln.graphql(ISSUES_QUERY,
                          {"t": args.team, "after": after, "since": since})["issues"]
        nodes.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    rows = []
    for node in nodes:
        title = node.get("title") or ""
        desc = node.get("description") or ""
        state_type = ((node.get("state") or {}).get("type") or "").lower()
        rows.append({
            # The one-way hash, derived from alert-to-linear's own normalizer so
            # there is exactly one definition of "the same alert said again".
            "fp": alert.fingerprint(title),
            "created_at": node.get("createdAt"),
            "filer": classify(title, desc),
            "state_type": state_type,
            # The DoR gate is about tickets that were WORKED. Completed is that;
            # canceled is the opposite (someone decided it should not exist).
            "completed": state_type == "completed",
            "bot": bool(node.get("botActor")),
        })
    rows.sort(key=lambda r: r["created_at"] or "")

    payload = {
        "provenance": {
            "source": "Linear GraphQL api.linear.app, issues(filter: team+createdAt)",
            "team": args.team,
            "captured_at": captured_at.isoformat(),
            "window_days": args.days,
            "since": since,
            "query": " ".join(ISSUES_QUERY.split()),
            "redaction": (
                "Titles and descriptions are NOT stored. `fp` is "
                "alert-to-linear.fingerprint(title), a truncated sha256. This "
                "repo is public; see validate-separation Gate 1.2."
            ),
            "row_count": len(rows),
            "by_state": dict(collections.Counter(r["state_type"] for r in rows)),
            "by_filer": dict(collections.Counter(r["filer"] for r in rows)),
        },
        "rows": rows,
    }
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps(payload["provenance"], indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
