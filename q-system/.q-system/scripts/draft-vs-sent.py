#!/usr/bin/env python3
"""draft-vs-sent.py -- the producer for the draft-vs-sent learning stage.

Plan item 2k of prd-morning-brief-learns-2026-09-01. route-overrides-to-learn.py
reads the copy_edits table and has read nothing since 2026-04-03 because its
producer was an agent of the retired 9-phase pipeline. This is the producer
that replaces it.

Pairing is by Gmail IDENTITY and nothing else (Codex finding-7 on the PRD):
a draft's message id survives sending, so every draft this system writes is
recorded in q-system/output/drafts-ledger.jsonl with that id, and this script
looks each id up in sent mail through the same injectable runner seam the
brief uses. Subject, recipient or time similarity is never used: two drafts
with the same subject pair only the one whose id appears in sent mail, and
the other is reported as unmatched, with a count. A guess would persist false
voice-learning data; a count is honest.

Single-writer note: this writes copy_edits in this instance's metrics.db and
NEVER q-consult/voice/exemplars.jsonl (that file's only writer is
q-consult/pipeline/voice.py, agreed with the voice-loop lane 2026-09-01).

Under pytest the live runner is refused; tests inject one.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
LEDGER = Path(os.environ.get("KIPI_DRAFTS_LEDGER", QROOT / "output" / "drafts-ledger.jsonl"))
DB_PATH = Path(os.environ.get("KIPI_METRICS_DB", QROOT / ".q-system" / "data" / "metrics.db"))
ACTION = "draft-vs-sent"

SENT_PROMPT = (
    "Using the Gmail tools, for each of these Gmail message ids return the SENT "
    "message's plain-text body and recipient addresses. Answer with ONE JSON object "
    "mapping id -> {\"body\": str, \"to\": [str]} and omit ids that are not in sent "
    "mail. No prose. Ids: {ids}"
)


def record_draft(draft_id: str, contact: str, body: str, source: str, ledger=None) -> dict:
    """The append helper every draft writer calls. One line per draft; the id
    is the Gmail draft message id and is the ONLY pairing key."""
    if not draft_id:
        raise ValueError("a draft without a Gmail message id cannot be paired later")
    row = {"draft_id": draft_id, "contact": contact, "body": body, "source": source,
           "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    path = Path(ledger) if ledger else LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def read_ledger(ledger=None) -> list:
    path = Path(ledger) if ledger else LEDGER
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def fetch_sent(ids: list, runner) -> dict:
    """{id: {"body", "to"}} for ids present in sent mail; ONLY by id."""
    if not ids:
        return {}
    # str.replace, not str.format: the prompt carries literal JSON braces.
    out, err = runner(SENT_PROMPT.replace("{ids}", ", ".join(ids)), ["mcp__claude_ai_Gmail__*"])
    if err:
        raise RuntimeError(err)
    text = out.strip() if isinstance(out, str) else json.dumps(out)
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        raise RuntimeError("runner returned no JSON object")
    data = json.loads(text[start:end + 1])
    return {k: v for k, v in data.items() if k in ids and isinstance(v, dict)}


def _connect(db_path):
    con = sqlite3.connect(str(db_path))
    con.execute("""CREATE TABLE IF NOT EXISTS copy_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, contact_name TEXT NOT NULL,
        action_type TEXT, original TEXT NOT NULL, edited TEXT NOT NULL DEFAULT '',
        edit_summary TEXT, outreach_log_id INTEGER, UNIQUE(date, contact_name, action_type))""")
    return con


def pair(ledger=None, db_path=None, runner=None, now=None) -> dict:
    """Pair every ledger draft with its sent message by id and insert one
    copy_edits row per pair. Returns counts; never guesses a pair."""
    now = now or dt.datetime.now().astimezone()
    if runner is None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            # Distinct wording on purpose: the brief's run_claude refuses too,
            # with its own words, and a mutation that removed THIS check was
            # invisible while both said the same thing (2026-09-01).
            raise RuntimeError("refused by draft-vs-sent: running under pytest, the brief's runner is never loaded")
        brief = importlib.util.spec_from_file_location("morning_brief", HERE / "morning-brief.py")
        mod = importlib.util.module_from_spec(brief)
        brief.loader.exec_module(mod)
        runner = mod.run_claude
    drafts = read_ledger(ledger)
    sent = fetch_sent([d["draft_id"] for d in drafts], runner)
    con = _connect(Path(db_path) if db_path else DB_PATH)
    inserted = identical = 0
    unmatched = []
    for d in drafts:
        hit = sent.get(d["draft_id"])
        if hit is None:
            unmatched.append(d["draft_id"])
            continue
        if hit.get("body", "").strip() == d.get("body", "").strip():
            identical += 1
            continue
        cur = con.execute(
            "INSERT OR IGNORE INTO copy_edits (date, contact_name, action_type, original, edited, edit_summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now.strftime("%Y-%m-%d"), d.get("contact", ""), f"{ACTION}:{d['draft_id']}",
             d.get("body", ""), hit.get("body", ""), f"paired by id from {d.get('source', '?')}"))
        inserted += cur.rowcount
    con.commit()
    con.close()
    return {"drafts": len(drafts), "paired": inserted, "identical": identical,
            "unmatched": len(unmatched), "unmatched_ids": unmatched}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pair recorded drafts with sent mail by Gmail id")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)
    result = pair(args.ledger, args.db)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
