#!/usr/bin/env python3
"""Mirror q-system/lessons into the founder's Notion "Kipi lessons" database.

Founder 2026-09-02: "there needs to be a place where all the lessons brought up
by these builds show up ... dynamic lessons that grow over time ... the process
needs to constantly write to Notion." The repo corpus stays the source of
truth; this writes it to Notion so a new lesson is on the board the morning it
lands. Runs from lessons-daily.sh after publish (non-fatal), and by hand.

Contract:
  - Upsert by the corpus id (the Notion "Id" property). A row that exists gets
    Kind, Learned, Rule, Came from and Synced refreshed. Status and Notes are
    the founder's and are never written after creation.
  - A new row gets Status "in corpus" and the lesson body as page content.
  - OFF when ~/.config/kipi/notion-token or notion-lessons-db is missing:
    prints one line, exits 0, touches nothing (every writer has an off switch).
  - Refuses to reach the live API under pytest unless an opener is injected.
  - Exit 0 ok, 2 on a Notion error (the daily job logs it and continues).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS = HERE.parent.parent / "lessons"
STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR") or (Path.home() / ".config" / "kipi"))
TOKEN_FILE = STATE_DIR / "notion-token"
DB_FILE = STATE_DIR / "notion-lessons-db"
# One sync at a time (PR #294 review round 3, major): sync() snapshots the
# database and then creates what is missing, so two runs (the nightly job and
# a by-hand run) that both snapshot before either writes would each create the
# same corpus id. flock is per open file description, so this serialises two
# processes AND two threads; the second run snapshots after the first wrote.
LOCK_FILE = STATE_DIR / "notion-lessons-sync.lock"
API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TIMEOUT = 20
EXIT_OK, EXIT_ERROR = 0, 2
MAX_TEXT = 1900  # Notion rich_text cap is 2000 per span


class NotionError(Exception):
    pass


# Notion allows about three requests a second and answers 429 past it. The
# nightly run issues one request per lesson (175 today), so it PACES live
# requests and RETRIES a 429 or a 5xx with backoff instead of aborting the
# whole loop on the first refusal (PR #294 review round 6). An injected opener
# (tests) is never paced; `_sleep` is the seam a test replaces.
PACE_S = float(os.environ.get("KIPI_NOTION_PACE_S", "0.35"))
RETRIES = 3
_sleep = time.sleep


def _request(token, method, path, body=None, opener=None, retry=True):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    if opener is None and PACE_S > 0:
        _sleep(PACE_S)
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200] if exc.fp else ""
            last = NotionError(f"{method} {path} -> {exc.code}: {detail}")
            if exc.code != 429 and exc.code < 500:
                raise last from None
            retry_after = (exc.headers or {}).get("Retry-After") if hasattr(exc, "headers") else None
            try:
                wait = min(float(retry_after), 10.0) if retry_after else float(attempt)
            except ValueError:
                wait = float(attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = NotionError(f"{method} {path} -> {exc}")
            wait = float(attempt)
        last.retryable, last.wait = True, wait
        if not retry:
            raise last from None  # the caller decides how to retry (a create is not idempotent)
        if attempt < RETRIES:
            _sleep(wait)
    raise last from None


def _row_for(token, db_id, cid, opener=None):
    """The page id holding corpus id `cid`, or None. Asked with a filter, and
    filtered again client-side because the answer is what matters."""
    page = _request(token, "POST", f"/databases/{db_id}/query",
                    {"page_size": 5, "filter": {"property": "Id", "rich_text": {"equals": cid}}}, opener)
    for row in page.get("results") or []:
        spans = ((row.get("properties") or {}).get("Id") or {}).get("rich_text") or []
        if "".join(s.get("plain_text") or (s.get("text") or {}).get("content", "") for s in spans).strip() == cid:
            return row["id"]
    return None


def _create(token, db_id, lesson, opener=None):
    """Create is NOT idempotent (PR #294 review round 7, major): a 5xx or a
    dropped connection can answer a POST /pages that Notion already applied,
    and a blind retry made a second row that no later sync reconciles. So a
    failed create is never re-sent blind: the database is asked whether the
    row landed, and only a confirmed absence is retried."""
    body = {"parent": {"database_id": db_id}, "properties": _properties(lesson, created=True),
            "children": _children(lesson["body"])}
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            _request(token, "POST", "/pages", body, opener, retry=False)
            return
        except NotionError as exc:
            if not getattr(exc, "retryable", False):
                raise
            last = exc
            if _row_for(token, db_id, lesson["id"], opener):
                return  # it landed; the answer was lost, not the write
            if attempt < RETRIES:
                _sleep(exc.wait)
    raise last


def parse_lesson(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    fm, body = {}, raw
    m = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", raw)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if _:
                fm[k.strip()] = v.strip()
        body = m.group(2).strip()
    rule = ""
    r = re.search(r"(?m)^\s*1\.\s+(.+)$", body)
    if r:
        rule = r.group(1).strip()
    came = ""
    # A lesson names its PRD with or without the date suffix (the 13 build
    # lessons of 2026-09-02 wrote "prd-lessons-rail-and-up-rail" bare, and the
    # first sync filed them as "distiller"). Either form is a build review.
    c = re.search(r"\bprd-[a-z][a-z0-9-]*|\brca-[a-z0-9-]+|\bASK-\d+", body)
    if c:
        came = c.group(0).rstrip("-")
    origin = "build review" if came.startswith("prd-") else ("rca" if came.startswith("rca-") else "distiller")
    return {"id": fm.get("id") or path.stem, "kind": fm.get("kind", "pattern"), "title": fm.get("title") or path.stem,
            "date": fm.get("date", ""), "body": body, "rule": rule[:MAX_TEXT], "came_from": came, "origin": origin}


def corpus(lessons_dir=None):
    d = Path(lessons_dir or LESSONS)
    return [parse_lesson(p) for p in sorted(d.glob("*.md")) if p.name != "README.md"]


def _rt(text):
    return [{"type": "text", "text": {"content": text[:MAX_TEXT]}}] if text else []


def _properties(lesson, created: bool):
    props = {
        "Lesson": {"title": _rt(lesson["title"])},
        "Id": {"rich_text": _rt(lesson["id"])},
        "Kind": {"select": {"name": lesson["kind"] if lesson["kind"] in ("pattern", "scar", "rule", "measurement") else "pattern"}},
        "Rule": {"rich_text": _rt(lesson["rule"])},
        "Came from": {"rich_text": _rt(lesson["came_from"])},
        "Synced": {"date": {"start": date.today().isoformat()}},
        # Origin is derived from the lesson text, so it is refreshed like Kind;
        # only Status and Notes belong to the founder and are create-only.
        "Origin": {"select": {"name": lesson["origin"]}},
    }
    if re.match(r"\d{4}-\d{2}-\d{2}", lesson["date"]):
        props["Learned"] = {"date": {"start": lesson["date"][:10]}}
    if created:
        props["Status"] = {"select": {"name": "in corpus"}}
    return props


def _children(body: str):
    blocks = []
    for para in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()][:60]:
        for chunk in (para[i:i + MAX_TEXT] for i in range(0, len(para), MAX_TEXT)):
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(chunk)}})
    return blocks[:100]


def existing_rows(token, db_id, opener=None) -> dict:
    """corpus id -> page id, over every row in the database."""
    out, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        page = _request(token, "POST", f"/databases/{db_id}/query", body, opener)
        for row in page.get("results") or []:
            spans = ((row.get("properties") or {}).get("Id") or {}).get("rich_text") or []
            cid = "".join(s.get("plain_text") or (s.get("text") or {}).get("content", "") for s in spans).strip()
            if cid:
                out[cid] = row["id"]
        if not page.get("has_more"):
            return out
        cursor = page.get("next_cursor")


def sync(token, db_id, lessons, opener=None, out=print, lock_file=None) -> dict:
    lock_path = Path(lock_file or LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # held across the snapshot AND the writes
        try:
            have = existing_rows(token, db_id, opener)
            created = updated = 0
            errors = []
            for lesson in lessons:
                try:
                    if lesson["id"] in have:
                        _request(token, "PATCH", f"/pages/{have[lesson['id']]}", {"properties": _properties(lesson, created=False)}, opener)
                        updated += 1
                    else:
                        _create(token, db_id, lesson, opener)
                        created += 1
                except NotionError as exc:
                    # One lesson's refusal never leaves the rest unwritten; it
                    # is counted, named, and the run reports ok=False.
                    errors.append({"id": lesson["id"], "error": str(exc)})
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    report = {"ok": not errors, "created": created, "updated": updated, "total": len(lessons),
              "failed": len(errors), "errors": errors[:10]}
    out(json.dumps(report))
    return report


def credentials(token_file=None, db_file=None):
    tf, df = Path(token_file or TOKEN_FILE), Path(db_file or DB_FILE)
    if not tf.exists() or not df.exists():
        return None, None
    return tf.read_text().strip(), df.read_text().strip()


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="mirror q-system/lessons into the Notion lessons database")
    ap.add_argument("--lessons-dir", default=None)
    ap.add_argument("--dry-run", action="store_true", help="list what would sync, touch nothing")
    a = ap.parse_args(argv)
    token, db_id = credentials()
    lessons = corpus(a.lessons_dir)
    if a.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "would_sync": len(lessons)}))
        return EXIT_OK
    if not token or not db_id:
        print(json.dumps({"ok": True, "off": True, "reason": f"missing {TOKEN_FILE.name} or {DB_FILE.name}; nothing written"}))
        return EXIT_OK
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print(json.dumps({"ok": False, "reason": "refused: running under pytest; the live database is never written by a test"}))
        return EXIT_ERROR
    try:
        report = sync(token, db_id, lessons)
        if not report["ok"]:
            return EXIT_ERROR  # the report already names the failures; the daily job logs it
    except NotionError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
