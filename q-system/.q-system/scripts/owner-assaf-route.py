#!/usr/bin/env python3
"""owner-assaf-route.py: an owner:assaf ticket goes back to owner:sana, unless it asks a founder question (ASK-3961).

owner:assaf has been an error path since 2026-08-03 (founder: "nothing should
be on me"). linear-worker.sh refuses it and pages "DEFECT: owner:assaf" about it
again and again, and nothing moved it, so the alert itself was the dead end.
Measured 2026-11-08: 3 open, among them ASK-2612 and ASK-830.

THE RULE, nightly:
  - A ticket whose text asks a spend, scope or outside-reach question is the
    founder's: one ask goes to the morning status file through its one writer,
    `cap-ladder.py --founder-ask` (ASK-3824), and the label stays.
  - Every other one is relabelled owner:sana, with one comment naming why, so
    the worker and the DoR drafter take it from there.

The question match is a closed list of words, not a model's guess: a wrong
relabel costs a worker run, a wrong founder ask costs the founder's attention,
and the second is the cost the founder ruled out. So a ticket is the founder's
only when the words are there.

Dry by default; --apply writes. Exit 0 always under launchd; the summary line
says what happened.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FOUNDER = "owner:assaf"
SANA = "owner:sana"
# Spend, scope and outside reach (no-idle-escalate-to-sana.md: those, and only
# those, reach the founder). Words, not a judgment.
# NO BARE NOUNS (codex, PR #670). `client`, `vendor`, `contract` and `legal`
# matched "Fix client synchronization", which asks nothing, and kept it on the
# founder's list: the exact false ask this closed list exists to prevent. Every
# entry is now money, a decision phrase, or an act only he can do.
QUESTION_RE = re.compile(
    r"\$\s?\d|\bbudget\b|\bspend\b|\bpay(ment)?\b|\bpurchase\b|\bsubscription\b|\bpricing\b|\binvoice\b"
    r"|\bscope decision\b|\bshould we\b|\bdo we want\b|\bpriority call\b"
    r"|\bsign (the |a )?(contract|agreement)\b|\bgrant (him |me |us )?access\b",
    re.I)
SENTENCE_END = ".?!\n"
OPEN_Q = """query($a:String){issues(first:100,after:$a,filter:{team:{key:{eq:"ASK"}},
  labels:{name:{eq:"owner:assaf"}},state:{type:{nin:["completed","canceled"]}}}){
  pageInfo{hasNextPage endCursor} nodes{id identifier title description labels{nodes{id name}}}}}"""


def _ls():
    spec = importlib.util.spec_from_file_location("kipi_linear_sync_oar", str(HERE / "linear-sync.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def tickets(g) -> list:
    out, after = [], None
    while True:
        page = (g(OPEN_Q, {"a": after}) or {}).get("issues") or {}
        out += page.get("nodes") or []
        if not (page.get("pageInfo") or {}).get("hasNextPage"):
            return out
        after = page["pageInfo"]["endCursor"]


def asks_founder(t: dict) -> str:
    """The matched words, or "" when the ticket asks no founder question."""
    m = QUESTION_RE.search(f"{t.get('title') or ''}\n{t.get('description') or ''}")
    return m.group(0) if m else ""


def label_id(g, name: str) -> str:
    nodes = (g('query($n:String!){issueLabels(filter:{name:{eq:$n}}){nodes{id}}}', {"n": name})
             .get("issueLabels") or {}).get("nodes") or []
    return nodes[0]["id"] if nodes else ""


def question(t: dict) -> str:
    """The sentence that asks, from the description first, else the title.

    THE TITLE ALONE DROPPED THE QUESTION (codex, PR #670). "Renew service" with
    "Should we pay the $40 invoice?" in the description reached the founder as
    "asks: Renew service", without the decision or the amount."""
    for text in (t.get("description") or "", t.get("title") or ""):
        m = QUESTION_RE.search(text)
        if m:
            start = max(text.rfind(c, 0, m.start()) for c in SENTENCE_END) + 1
            ends = [i for i in (text.find(c, m.end()) for c in SENTENCE_END) if i != -1]
            return text[start:(min(ends) + 1 if ends else len(text))].strip()
    return ""


def ask_text(t: dict) -> str:
    """The one ask this job files for a ticket. answered() matches on it, so the two
    can never disagree about which ask is this ticket's."""
    title, q = (t.get("title") or "")[:200], question(t)
    return f"{t['identifier']} asks: {title}" + (f": {q[:300]}" if q and q != title.strip() else "")


def answered(t: dict, status: Path) -> dict | None:
    """The founder's resolved answer to THIS job's ask for this ticket, or None.

    THE ANSWERED ASK WAS ASKED AGAIN (ASK-3961). cap-ladder.py dedupes only against
    OPEN asks, so once the founder ran --resolve, the ticket was still owner:assaf,
    still matched, and the next night filed the same ask as a new row: a decision
    he made came back every morning. Read-only: cap-ladder.py is the file's one
    writer. Matched on the issue AND this job's ask text, so a resolve of some other
    ask on the same ticket (a cap-ladder decision) is not taken as this answer."""
    try:
        rows = [json.loads(l) for l in status.read_text().splitlines() if l.strip()]
    except (OSError, ValueError):
        return None
    want = ask_text(t)
    hits = [r for r in rows if r.get("issue") == t["identifier"] and r.get("kind") == "founder-decision"
            and r.get("resolved") and r.get("ask") == want]
    return hits[-1] if hits else None


def route(t: dict, g, apply: bool, ladder: list, sync: list, status: Path) -> str:
    ident = t["identifier"]
    hit = asks_founder(t)
    done = answered(t, status) if hit else None
    if hit and not done:
        if not apply:
            return f"{ident}: asks a founder question ({hit!r}); would list it for the founder"
        p = subprocess.run(ladder + ["--founder-ask", ident, "founder-decision", ask_text(t)],
                           capture_output=True, text=True, timeout=60)
        said = (p.stdout or p.stderr).strip()[:160]
        return f"{ident}: asks a founder question ({hit!r}); " + (said if p.returncode == 0 else f"ask NOT listed ({said})")
    if done:
        why = (f"**Relabelled owner:sana by owner-assaf-route.py (ASK-3961).** The founder answered this "
               f"ticket's ask ({done.get('id')}, resolved by {done.get('resolved_by') or 'unnamed'}): "
               f"\"{(done.get('note') or 'no note given')[:300]}\". The fleet works it from that answer.")
    else:
        why = ("**Relabelled owner:sana by owner-assaf-route.py (ASK-3961).** owner:assaf is an error "
               "path, and this ticket asks no spend, scope or outside-reach question, so the fleet works "
               "it: the worker picks it once it has a Definition of Ready, and linear-dor-drafter.py "
               "writes one if it has none.")
    if not apply:
        return f"{ident}: " + ("the founder answered its ask" if done else "no founder question") + "; would relabel owner:sana"
    sana, founder = label_id(g, SANA), next((l["id"] for l in t["labels"]["nodes"] if l["name"] == FOUNDER), "")
    # issueAddLabel and issueRemoveLabel name ONE label each, so a label another
    # actor adds in between is never overwritten (the PR #77 lesson).
    ok = bool(sana) and (g('mutation($i:String!,$l:String!){issueAddLabel(id:$i,labelId:$l){success}}',
                           {"i": t["id"], "l": sana}).get("issueAddLabel") or {}).get("success")
    if not ok:
        return f"{ident}: could not add owner:sana; left as is, the next run retries"
    # THE REMOVAL IS CHECKED TOO (codex, PR #670). A refused removal left both
    # labels on, the worker still excluded the ticket, and this line said
    # "relabelled". Nothing is said or posted until both writes landed; the next
    # run finds it under owner:assaf again and retries (the add is idempotent).
    removed = bool(founder) and (g('mutation($i:String!,$l:String!){issueRemoveLabel(id:$i,labelId:$l){success}}',
                                   {"i": t["id"], "l": founder}).get("issueRemoveLabel") or {}).get("success")
    if not removed:
        return f"{ident}: owner:sana added, but owner:assaf was not removed; no comment, the next run retries"
    subprocess.run(sync + ["progress", ident, why, "--agent", "sana"], capture_output=True, text=True)
    return f"{ident}: relabelled owner:sana" + (" (the founder answered its ask)" if done else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    fixture = os.environ.get("OWNER_ROUTE_FIXTURE")
    if fixture:
        # The test seam: a recorded Linear, never the live one.
        sys.path.insert(0, str(Path(fixture).parent))
        g = __import__(Path(fixture).stem).graphql
    else:
        g = _ls().graphql
    ladder = (os.environ.get("OWNER_ROUTE_LADDER") or f"{sys.executable} {HERE / 'cap-ladder.py'}").split()
    sync = (os.environ.get("OWNER_ROUTE_SYNC") or f"{sys.executable} {HERE / 'linear-sync.py'}").split()
    # The path cap-ladder.py writes (its STATUS); read here, never written.
    status = Path(os.environ.get("CAP_LADDER_STATUS") or Path.home() / ".local/state/kipi/morning-status.jsonl")
    rows = tickets(g)
    for t in rows:
        print("owner-assaf-route: " + route(t, g, args.apply, ladder, sync, status))
    print(f"owner-assaf-route: {len(rows)} owner:assaf ticket(s){'' if args.apply else ' (dry)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
