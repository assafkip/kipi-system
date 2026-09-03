#!/usr/bin/env python3
"""Paint the Kipi backlog ROWS from the consulting state. The board's row writer.

Founder, 2026-09-03: *"copy it but everyting needs to be actually connected fully and is
automated so its not done by hand"*.

## Rows, not bullets, and that is measured rather than preferred

The Morning board page holds four `child_database` blocks, read live 2026-09-03:
heading_2, paragraph, child_database, four times. Its three founder sections are FILTERED
VIEWS of one database, "Kipi backlog", split by the `Bucket` select. So a writer that
appends bullets under the "Top of mind" heading puts loose text between that heading and
its database, and the board's own views never see it.

The ids cost an hour and are recorded so nobody re-derives them:

  page               ~/.config/kipi/notion-board-page
  Kipi backlog DB    0a09bd16-b12e-49bf-a792-fad15e008ed0   <- writes go here
  data source        3017ad50-...   404s on /v1/databases; it is not an API database id
  the page's blocks  3cfbf98c-...   LINKED VIEWS, queryable, not the source of truth

## HIS DRAG ALWAYS WINS. This module never moves a row he moved.

`Item id` carries "stable id the brief uses so a hand-moved item is never re-added". So:
create a row that does not exist, refresh the Notes and Source of one that does, and
NEVER write `Bucket` on an existing row. That is `gtm_board.record_paint`'s posture
(painting is not deciding) and DEC-8/DEC-13's one-writer rule. The computed state is
authoritative about WHAT is owed; he is authoritative about where it sits on his board.

## Rows leave when the work does

An owned row whose id is no longer in the computed set is ARCHIVED, not deleted, and only
if we own its id prefix. Without this the board only ever grows, which is how the last
board became 4 stale rows nobody trusted. A row he created by hand carries no owned
prefix and is never touched.

## A stale source writes NOTHING

OFF switch: a missing `~/.config/kipi/notion-token`. `collect` returns None and no board
section renders. `~/.config/kipi/notion-backlog-db` overrides the database id without a
code change; its absence falls back to DEFAULT_DB rather than switching the module off,
because a token with no db file is a configured board, not an unconfigured one.

## A stale source writes NOTHING

If `consulting_board.buckets` reports an error (the state card is yesterday's, or the
07:30 job crashed), this writes no rows at all and returns that error. Mirroring a stale
source onto a board that looks fresh is the one failure that would make him act on a
wrong number.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import consulting_board

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
STATE_DIR = Path.home() / ".config" / "kipi"
TOKEN_FILE = STATE_DIR / "notion-token"
DB_FILE = STATE_DIR / "notion-backlog-db"
#: The database the founder's three board views read. Overridable by the file above so a
#: moved board is a config change, never an edit here.
DEFAULT_DB = "0a09bd16-b12e-49bf-a792-fad15e008ed0"

#: Every row this module owns starts with it. A row without it is the founder's and is
#: never updated, moved or archived.
OWNED_PREFIX = "cb:"
BUDGET_ROWS = 40
TIMEOUT_S = 10.0

BUCKET_OF = {"top_of_mind": "Top of Mind", "this_week": "This Week", "inbox": "Inbox"}


def _credentials(token_file=None, db_file=None):
    tf = Path(token_file) if token_file else TOKEN_FILE
    df = Path(db_file) if db_file else DB_FILE
    token = tf.read_text(encoding="utf-8").strip() if tf.exists() else None
    db = df.read_text(encoding="utf-8").strip() if df.exists() else DEFAULT_DB
    return token, db


def _request(token, method, path, body=None, opener=None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT_S) as fh:
        return json.load(fh)


def item_id(bucket_key: str, item: dict) -> str:
    """Stable across mornings for the same underlying thing.

    Hashed from `item["key"]`, which carries the client name or the GTM step id and
    NOTHING that changes day to day. Not the detail (its "(due ...)" suffix and reply
    counts move every morning) and, since a Codex finding on 2026-09-03, NOT the title
    either: the title embeds the health dot, so a client going red to green minted a new
    id, and the next unattended paint archived the row he had DRAGGED and created a
    replacement in a computed bucket. That silently reversed his move, which is the one
    thing this module promises never to do.

    Also NOT the bucket_key, for the same reason: a row moving from Top of Mind to This
    Week as its health improves is the same row.

    An item with no `key` is REFUSED rather than falling back to the title. A fallback
    here is how the defect comes back: it would work, quietly, with an unstable id.
    """
    key = item.get("key")
    if not key:
        raise ValueError(
            f"item {item.get('title')!r} carries no stable `key`. Every producer must "
            "supply one; falling back to the title is what made ids move with the "
            "health dot (Codex finding 2026-09-03)."
        )
    return OWNED_PREFIX + hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:16]


def existing_rows(token, db, opener=None, dupes_out=None) -> dict:
    """{item_id: page} for the rows this module owns. One query, paged.

    Pass `dupes_out` to learn about ids that appear more than once; see the comment
    at the collision branch for why they are not silently collapsed.
    """
    out, cursor = {}, None
    dupes = {} if dupes_out is None else dupes_out
    while True:
        body = {"page_size": 100, "filter": {"property": "Item id", "rich_text":
                                             {"starts_with": OWNED_PREFIX}}}
        if cursor:
            body["start_cursor"] = cursor
        data = _request(token, "POST", f"/databases/{db}/query", body, opener)
        for page in data.get("results", []):
            prop = (page.get("properties") or {}).get("Item id") or {}
            text = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
            if not text:
                continue
            if text in out:
                # DUPLICATES ARE COUNTED, NOT COLLAPSED. Codex finding (major),
                # 2026-09-03: this dict silently kept the last page for an id, so two
                # painters racing could create two rows for one item and the read-back
                # count still matched `wanted`, reporting "ok" over a board with
                # doubles on it. A proof that cannot see the defect it exists to catch
                # is not a proof.
                dupes.setdefault(text, 1)
                dupes[text] += 1
                continue
            out[text] = page
        if not data.get("has_more"):
            return out
        cursor = data.get("next_cursor")


def _properties(item, bucket, iid, include_bucket: bool):
    props = {
        "Task": {"title": [{"text": {"content": (item.get("title") or "(untitled)")[:200]}}]},
        "Item id": {"rich_text": [{"text": {"content": iid}}]},
        "Notes": {"rich_text": [{"text": {"content": (item.get("detail") or "")[:1800]}}]},
        "Domain": {"multi_select": [{"name": "Consulting"}]},
    }
    source = item.get("source")
    if source:
        # Notion creates a missing select option on write, so "State card" and
        # "GroupMe" do not need to be added to the schema by hand first.
        props["Source"] = {"select": {"name": source[:100]}}
    if include_bucket:
        # ONLY on create. On an existing row his drag is the truth.
        props["Bucket"] = {"select": {"name": bucket}}
        props["Status"] = {"select": {"name": "Not started"}}
    return props


def paint(buckets: dict, token, db, opener=None) -> dict:
    """Create, refresh and archive. Returns a counts dict. Never moves a row."""
    if buckets.get("error"):
        raise ValueError(buckets["error"])

    wanted = {}
    for key, bucket in BUCKET_OF.items():
        for item in (buckets.get(key) or [])[:BUDGET_ROWS]:
            wanted[item_id(key, item)] = (item, bucket)

    have = existing_rows(token, db, opener)
    created = updated = archived = 0

    for iid, (item, bucket) in wanted.items():
        page = have.get(iid)
        if page is None:
            _request(token, "POST", "/pages",
                     {"parent": {"database_id": db},
                      "properties": _properties(item, bucket, iid, include_bucket=True)},
                     opener)
            created += 1
        else:
            _request(token, "PATCH", f"/pages/{page['id']}",
                     {"properties": _properties(item, bucket, iid, include_bucket=False)},
                     opener)
            updated += 1

    for iid, page in have.items():
        if iid not in wanted:
            _request(token, "PATCH", f"/pages/{page['id']}", {"archived": True}, opener)
            archived += 1

    return {"created": created, "updated": updated, "archived": archived,
            "wanted": len(wanted)}


def read_back(token, db, opener=None) -> int:
    return len(existing_rows(token, db, opener))


def collect(now, sources: dict, opener=None, token_file=None, db_file=None):
    """Registry contract: (rows, error), or None when the board is OFF."""
    token, db = _credentials(token_file, db_file)
    if not token:
        return None                       # OFF, not broken
    if opener is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return [], "refused: running under pytest; the live board is never written by a test"
    if opener is None and os.environ.get("KIPI_BRIEF_DRY_RUN"):
        # MEASURED, not anticipated. The first end-to-end `--dry-run` printed
        # "nothing sent, no receipt written" and had already created 12 rows on his
        # live board. A dry run that writes is not a dry run, and the flag's promise
        # was only ever about the Slack send because that was the only write the brief
        # had before this module. An optional section can write, so the flag has to
        # reach the sections.
        return [], "dry-run: board not written"

    buckets = consulting_board.buckets(now, sources)
    if buckets.get("error"):
        return [], f"board not written: {buckets['error']}"
    try:
        counts = paint(buckets, token, db, opener)
        dupes = {}
        seen = len(existing_rows(token, db, opener, dupes_out=dupes))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return [], f"board write failed: {type(exc).__name__}: {exc}"

    if dupes:
        return [], (f"duplicate board rows for {len(dupes)} item(s): "
                    f"{', '.join(sorted(dupes))}. Two painters have run; the board "
                    "holds doubles and this run's counts cannot be trusted")
    if seen != counts["wanted"]:
        # The write-only-integration scar: a PATCH that returns 200 is not proof the
        # board holds what we think. The read-back is the proof.
        return [], (f"read-back mismatch: wrote {counts['wanted']} row(s), "
                    f"board shows {seen}")
    return [f"board: {counts['created']} new, {counts['updated']} refreshed, "
            f"{counts['archived']} cleared, read-back ok"], None
