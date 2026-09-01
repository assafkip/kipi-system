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
import difflib
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
LEDGER = Path(os.environ.get("KIPI_DRAFTS_LEDGER", QROOT / "output" / "drafts-ledger.jsonl"))
DB_PATH = Path(os.environ.get("KIPI_METRICS_DB", QROOT / ".q-system" / "data" / "metrics.db"))
ACTION = "draft-vs-sent"

SENT_PROMPT = (
    "Using the Gmail tools, for each of these Gmail message ids return the SENT "
    "message's plain-text body, subject and recipient addresses. Answer with ONE JSON object "
    "mapping id -> {\"body\": str, \"subject\": str, \"to\": [str]} and omit ids that are not in sent "
    "mail. No prose. Ids: {ids}"
)


def record_draft(draft_id: str, contact: str, body: str, source: str, ledger=None,
                 subject: str = "") -> dict:
    """The append helper every draft writer calls. One line per draft; the id
    is the Gmail draft message id and is the ONLY pairing key. The subject is
    recorded for the founder's eyes and is never read by the pairer (Codex
    standard finding on this issue: with no subject in the ledger, a test could
    not prove that subject-based pairing is absent)."""
    if not draft_id:
        raise ValueError("a draft without a Gmail message id cannot be paired later")
    row = {"draft_id": draft_id, "contact": contact, "subject": subject, "body": body,
           "source": source, "at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
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
    # Validate at the runner boundary (Codex adversarial finding on this
    # issue): an entry without a string body is NOT an empty sent message, it
    # is an invalid answer, and it is dropped and counted rather than stored
    # or crashed on.
    valid = {}
    for k, v in data.items():
        if k in ids and isinstance(v, dict) and isinstance(v.get("body"), str):
            valid[k] = v
    return valid


def _connect(db_path):
    con = sqlite3.connect(str(db_path))
    con.execute("""CREATE TABLE IF NOT EXISTS copy_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, contact_name TEXT NOT NULL,
        action_type TEXT, original TEXT NOT NULL, edited TEXT NOT NULL DEFAULT '',
        edit_summary TEXT, outreach_log_id INTEGER, UNIQUE(date, contact_name, action_type))""")
    return con


WINDOW_DAYS = 30
MAX_IDS_PER_RUN = 50
RETENTION_DAYS = 90
SALT_FILE = Path(os.environ.get("KIPI_STATE_DIR", str(Path.home() / ".config" / "kipi"))) / "draft-salt"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _salt(salt=None) -> str:
    """A per-machine salt, created once. Tests pass one explicitly."""
    if salt:
        return salt
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # A test never creates the machine's salt file (test isolation, the
        # fable-discipline rule); a fixed salt keeps hashing deterministic.
        return "pytest-salt"
    if SALT_FILE.is_file():
        return SALT_FILE.read_text(encoding="utf-8").strip()
    SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    value = os.urandom(16).hex()
    SALT_FILE.write_text(value, encoding="utf-8")
    return value


def hash_recipient(address: str, salt: str) -> str:
    return hashlib.sha256((salt + address.strip().lower()).encode("utf-8")).hexdigest()[:12]


def mask_recipients(text: str, salt: str) -> str:
    return _EMAIL.sub(lambda m: "rcpt:" + hash_recipient(m.group(0), salt), text)


_HEADER_LINE = re.compile(r"^\s*(subject|to|from|cc|bcc|date|reply-to|message-id|in-reply-to|references)\s*:", re.IGNORECASE)
MAX_SIDE_CHARS = 600
CONTEXT_WORDS = 2


def _strip_headers(text: str) -> list:
    """Header-shaped lines never enter the projection (Codex standard finding
    on this issue: a changed 'Subject:' or 'To:' line was being stored)."""
    return [l for l in text.splitlines() if not _HEADER_LINE.match(l)]


def _word_delta(a_line: str, b_line: str) -> tuple:
    """Only the differing words of a changed line pair, with two words of
    context each side (Codex adversarial finding: a single-line body was being
    stored whole as 'the changed line'). Returns (removed_words, added_words)."""
    a, b = a_line.split(), b_line.split()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    rem, add = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        rem.append(" ".join(a[max(0, i1 - CONTEXT_WORDS):i2 + CONTEXT_WORDS]))
        add.append(" ".join(b[max(0, j1 - CONTEXT_WORDS):j2 + CONTEXT_WORDS]))
    return " ... ".join(x for x in rem if x), " ... ".join(x for x in add if x)


def project(draft_body: str, sent_body: str, salt: str) -> tuple:
    """(original, edited): the delta between draft and sent, never the bodies,
    never a subject, never a header (Codex finding-8 on the PRD). Line diff
    first; a replaced line pair is reduced to its differing words; each side is
    capped at MAX_SIDE_CHARS. Addresses are salted hashes everywhere."""
    a = _strip_headers(mask_recipients(draft_body, salt))
    b = _strip_headers(mask_recipients(sent_body, salt))
    removed, added = [], []
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                r, ad = _word_delta(x, y)
                removed.append(r)
                added.append(ad)
            removed += a[i1 + (j2 - j1):i2]
            added += b[j1 + (i2 - i1):j2]
        elif tag == "delete":
            removed += a[i1:i2]
        elif tag == "insert":
            added += b[j1:j2]
    orig = "\n".join(x for x in removed if x)[:MAX_SIDE_CHARS]
    edit = "\n".join(x for x in added if x)[:MAX_SIDE_CHARS]
    return orig, edit


def purge(db_path=None, now=None, days: int = RETENTION_DAYS) -> int:
    """Delete draft-vs-sent rows older than `days`. Touches no other
    action_type. Returns the count removed."""
    now = now or dt.datetime.now().astimezone()
    cutoff = (now - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    con = _connect(Path(db_path) if db_path else DB_PATH)
    cur = con.execute("DELETE FROM copy_edits WHERE action_type LIKE ? AND date < ?", (f"{ACTION}:%", cutoff))
    con.commit()
    con.close()
    return cur.rowcount


def _in_window(row: dict, now: dt.datetime, days: int) -> bool:
    try:
        when = dt.datetime.fromisoformat(str(row.get("at", "")))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return (now - when) <= dt.timedelta(days=days)


def pair(ledger=None, db_path=None, runner=None, now=None, days: int = WINDOW_DAYS,
         max_ids: int = MAX_IDS_PER_RUN, salt=None) -> dict:
    """Pair every ledger draft with its sent message by id and insert one
    copy_edits row per pair. Returns counts; never guesses a pair.

    Bounded and idempotent across days (Codex adversarial findings on this
    issue): a draft already paired (its id is in copy_edits, any date) is
    skipped before any lookup; only drafts written in the last `days` are
    looked up, at most `max_ids` per run, oldest first, and the counts of
    what was skipped for each reason are reported."""
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
    all_drafts = read_ledger(ledger)
    con = _connect(Path(db_path) if db_path else DB_PATH)
    already = {row[0].split(":", 1)[1] for row in con.execute(
        "SELECT action_type FROM copy_edits WHERE action_type LIKE ?", (f"{ACTION}:%",))}
    already_paired = [d for d in all_drafts if d["draft_id"] in already]
    fresh = [d for d in all_drafts if d["draft_id"] not in already and _in_window(d, now, days)]
    too_old = len(all_drafts) - len(already_paired) - len(fresh)
    deferred = max(0, len(fresh) - max_ids)
    drafts = fresh[:max_ids]
    sent = fetch_sent([d["draft_id"] for d in drafts], runner)
    inserted = identical = 0
    unmatched = []
    for d in drafts:
        hit = sent.get(d["draft_id"])
        if hit is None:
            unmatched.append(d["draft_id"])
            continue
        if hit["body"].strip() == str(d.get("body", "")).strip():
            identical += 1
            continue
        the_salt = _salt(salt)
        original, edited = project(str(d.get("body", "")), hit["body"], the_salt)
        # contact_name is part of the persistence boundary too (both Codex
        # reviewers on this issue): a ledger contact that is an address is
        # stored as its salted hash, never raw.
        contact = mask_recipients(str(d.get("contact", "")), the_salt)
        recipients = [hash_recipient(t, the_salt) for t in (hit.get("to") or []) if isinstance(t, str)]
        cur = con.execute(
            "INSERT OR IGNORE INTO copy_edits (date, contact_name, action_type, original, edited, edit_summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now.strftime("%Y-%m-%d"), contact, f"{ACTION}:{d['draft_id']}",
             original, edited,
             f"diff projection, paired by id from {d.get('source', '?')}, "
             f"recipients {','.join(recipients) or 'none'}"))
        inserted += cur.rowcount
    con.commit()
    con.close()
    return {"drafts": len(all_drafts), "looked_up": len(drafts), "paired": inserted,
            "identical": identical, "unmatched": len(unmatched), "unmatched_ids": unmatched,
            "already_paired": len(already_paired), "too_old": too_old, "deferred": deferred}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pair recorded drafts with sent mail by Gmail id")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--purge", action="store_true", help=f"delete rows older than {RETENTION_DAYS} days and exit")
    args = ap.parse_args(argv)
    if args.purge:
        print(json.dumps({"purged": purge(args.db)}))
        return 0
    result = pair(args.ledger, args.db)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
