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

## HIS DRAG ALWAYS WINS. This module never moves a row HE moved.

`Item id` carries "stable id the brief uses so a hand-moved item is never re-added". So:
create a row that does not exist, refresh the Notes and Source of one that does, and
never move a row a human put somewhere. That is `gtm_board.record_paint`'s posture
(painting is not deciding) and DEC-8/DEC-13's one-writer rule. The computed state is
authoritative about WHAT is owed; he is authoritative about where it sits on his board.

The first cut of that read "NEVER write `Bucket` on an existing row", which is a wider
rule than the promise and Codex round 6 (major) is what it cost: a client going red ->
green kept its old bucket forever and a human had to reconcile the board by hand. A
stale value the MACHINE painted is not his drag.

The two are told apart the way `gtm_board.apply_board_moves` does it: every write
records `bucket=` in the row's own Notes, which is what this module last painted there.
Nothing else writes that column, so a live value differing from the record is a human.

One deliberate divergence from gtm_board, and it is the whole design: there a drag is
applied back through `set_state`, so the computed state BECOMES his choice and adopting
the live value as the next baseline is right. Here health is computed from the state
card and no drag can change it, so adopting would make the record agree next morning and
move his row back one run later. A row he has moved is therefore PINNED (`pinned=1` in
the same note) and this module never sets its bucket again.

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

import contextlib
import fcntl
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import consulting_board
# ONE budget class, shared with the old bullet writer rather than copied from it.
# notion_board is unregistered as a section (see morning-brief.OPTIONAL_SECTIONS) and
# stays on disk as a library; its `_Budget` is the interlock both painters need.
from notion_board import Cancelled, _Budget, _bounded

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
#: The board's OWN deadline, held by the worker and checked before every Notion call.
#: Codex round 4 (major): morning-brief's `_guarded` abandons a collector on timeout,
#: which bounds the WAIT and not the WRITES. This painter kept creating, refreshing and
#: archiving rows after the brief had already reported it timed out, with no read-back
#: behind those writes. Now a spent or cancelled budget refuses the next request and
#: caps the one in flight, so nothing outlives it. Deliberately BELOW the brief's
#: COLLECT_BUDGET_S so this cancel fires first and the guard is the backstop;
#: test_consulting_board pins the ordering.
BUDGET_S = 15.0

BUCKET_OF = {"top_of_mind": "Top of Mind", "this_week": "This Week", "inbox": "Inbox"}


def _credentials(token_file=None, db_file=None):
    tf = Path(token_file) if token_file else TOKEN_FILE
    df = Path(db_file) if db_file else DB_FILE
    token = tf.read_text(encoding="utf-8").strip() if tf.exists() else None
    db = df.read_text(encoding="utf-8").strip() if df.exists() else DEFAULT_DB
    return token, db


def _request(token, method, path, body=None, opener=None, budget=None):
    timeout = TIMEOUT_S
    if budget is not None:
        timeout = min(TIMEOUT_S, max(0.001, budget.check()))   # raises Cancelled when spent
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as fh:
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


def existing_rows(token, db, opener=None, dupes_out=None, budget=None) -> dict:
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
        data = _request(token, "POST", f"/databases/{db}/query", body, opener, budget)
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


SCOPE_PREFIX = "scope="
#: What this module last PAINTED into the row's Bucket. See the module docstring.
BUCKET_PREFIX = "bucket="
#: A human moved this row. From then on the machine refreshes its text and never its
#: bucket. One flag rather than an inference, because the inference is what would
#: silently expire (see `_bucket_decision`).
PINNED_LINE = "pinned=1"
#: The note's machinery lines are short and fixed; the free text is capped so they
#: always fit. Before this the whole note was truncated at the end, so a long detail
#: could push `scope=` off and the row read back as an unknown scope: kept forever,
#: with no error anywhere.
NOTE_CAP = 1900


def _note_of(page) -> str:
    prop = (page.get("properties") or {}).get("Notes") or {}
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


def _note_field(page, prefix: str) -> str:
    """A `<prefix>value` line off the row's own Notes, or "" when it carries none."""
    for part in _note_of(page).split("\n"):
        if part.startswith(prefix):
            return part[len(prefix):].strip()
    return ""


def _scope_of(page) -> str:
    """The scope a row was written under, read back off the row itself.

    Stored in Notes rather than a new Notion property so the board's schema does not
    change: a select option added by a writer is a schema edit the founder did not ask
    for. Unknown scope is treated as UNHEALTHY by the caller, which fails safe: an
    unrecognised row is kept, never archived.
    """
    return _note_field(page, SCOPE_PREFIX)


def _live_bucket_of(page) -> str:
    """The bucket the row sits in RIGHT NOW, whoever put it there."""
    prop = (page.get("properties") or {}).get("Bucket") or {}
    return ((prop.get("select") or {}).get("name") or "").strip()


def _bucket_decision(page, computed: str):
    """(write_bucket, bucket_to_record, pinned) for an EXISTING row.

    The whole of "his drag always wins" lives in the branches below, so each one says
    what it is protecting rather than what it does.
    """
    if PINNED_LINE in _note_of(page).split("\n"):
        return False, _live_bucket_of(page), True      # decided; never revisited
    live = _live_bucket_of(page)
    painted = _note_field(page, BUCKET_PREFIX)
    if not live:
        # His three board views all filter on Bucket, so a row in none of them is on no
        # view at all. Leaving it invisible forever is worse than placing it.
        return True, computed, False
    if not painted:
        # COLD START: a row written before this module recorded anything, which on the
        # morning this ships is every row on the board. Nothing on disk can tell his
        # drag from our own stale paint here, so this is a one-time bet and it is made
        # toward the REVERSIBLE side. Moving a row he had dragged costs him one drag,
        # and that drag pins the row for good. Pinning a row he never touched is
        # silent, permanent, and leaves the board wrong with no lever to fix it, which
        # is the round-6 finding wearing a fail-safe's coat.
        return True, computed, False
    if live != painted:
        return False, live, True                       # nothing but a human writes this
    if live == computed:
        return False, live, False
    return True, computed, False


def _properties(item, bucket, iid, include_bucket: bool, *, status=None,
                record_bucket=None, pinned=False):
    """The row's Notion properties.

    `include_bucket` writes `Bucket`; `status` writes `Status` when given (create only,
    because he marks rows done and a refresh must never reset that). `record_bucket` is
    what the row's Bucket will hold AFTER this write and defaults to `bucket`; a caller
    DECLINING to move a row passes the live value instead, so the note never claims a
    paint that did not happen.
    """
    # The done signal leads the note, because it is the line that makes the row
    # actionable; `scope=` and `bucket=` are machinery the painter reads back and
    # belong last.
    done = (item.get("done") or "").strip()
    note = ""
    if done:
        note += f"Done signal: {done}\n"
    note += (item.get("detail") or "")[:1500]
    tail = f"{SCOPE_PREFIX}{item.get('scope') or 'card'}"
    tail += f"\n{BUCKET_PREFIX}{record_bucket if record_bucket is not None else bucket}"
    if pinned:
        tail += f"\n{PINNED_LINE}"
    # The FREE TEXT is what gets cut, never the machinery. Truncating the whole note
    # from the end drops `scope=` first, and an unknown scope is kept forever with no
    # error: a silent leak wearing a fail-safe's coat.
    note = f"{note[:max(0, NOTE_CAP - len(tail) - 1)]}\n{tail}"

    props = {
        "Task": {"title": [{"text": {"content": (item.get("title") or "(untitled)")[:200]}}]},
        "Item id": {"rich_text": [{"text": {"content": iid}}]},
        "Notes": {"rich_text": [{"text": {"content": note}}]},
        # The producer's own domain. Hardcoding "Consulting" put a GTM step and a
        # broken-source alarm under the client label, so the column could not be
        # filtered on -- which is the only thing a domain column is for.
        "Domain": {"multi_select": [{"name": item.get("domain") or "Consulting"}]},
    }
    priority = item.get("priority")
    if priority:
        props["Priority"] = {"select": {"name": priority}}
    source = item.get("source")
    if source:
        # Notion creates a missing select option on write, so "State card" and
        # "GroupMe" do not need to be added to the schema by hand first.
        props["Source"] = {"select": {"name": source[:100]}}
    if include_bucket:
        props["Bucket"] = {"select": {"name": bucket}}
    if status:
        # Create only. He marks rows done on the board; a morning refresh that reset
        # this to "Not started" would undo that every day.
        props["Status"] = {"select": {"name": status}}
    return props


LOCK_FILE = STATE_DIR / "board-rows.lock"


@contextlib.contextmanager
def exclusive(lock_path=None):
    """One painter at a time. Codex round 2 (major): paint() queries then creates, so
    two simultaneous runs both see "absent" and both create, leaving permanent
    duplicates. The round-1 fix only DETECTED duplicates after the fact, which reports
    a mess rather than preventing one.

    flock on a local file, non-blocking: a second painter refuses immediately rather
    than queueing behind a 07:40 job. The board is machine-local state and both writers
    would be on this machine, which is exactly what flock covers.
    """
    path = Path(lock_path) if lock_path else LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BoardBusy("another painter holds the board lock") from exc
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


class BoardBusy(RuntimeError):
    """A second painter tried to run. Not a failure of this one."""


def paint(buckets: dict, token, db, opener=None, budget=None) -> dict:
    """Create, refresh and archive. Returns a counts dict. Never moves a row."""
    if buckets.get("error"):
        raise ValueError(buckets["error"])

    wanted, scopes = {}, {}
    for key, bucket in BUCKET_OF.items():
        for item in (buckets.get(key) or [])[:BUDGET_ROWS]:
            iid = item_id(key, item)
            wanted[iid] = (item, bucket)
            scopes[iid] = item.get("scope") or "card"

    # ARCHIVE ONLY INSIDE A HEALTHY SCOPE. Codex round 2 (major): a transient Gmail
    # error replaced that source's rows with one error row, so every previously
    # positioned inbox row fell out of `wanted` and the painter archived the lot. A
    # source that could not answer this morning has said NOTHING about its rows, and
    # nothing is not "they are gone".
    healthy = buckets.get("healthy_scopes")
    if healthy is None:
        raise ValueError(
            "buckets carries no `healthy_scopes`. Archiving without it would delete "
            "rows on any transient source failure (Codex round 2)."
        )

    have = existing_rows(token, db, opener, budget=budget)
    created = updated = archived = moved = pinned = 0

    for iid, (item, bucket) in wanted.items():
        page = have.get(iid)
        if page is None:
            _request(token, "POST", "/pages",
                     {"parent": {"database_id": db},
                      "properties": _properties(item, bucket, iid, include_bucket=True,
                                                status="Not started")},
                     opener, budget)
            created += 1
        else:
            # Codex round 6 (major): this passed include_bucket=False unconditionally,
            # so a row's bucket was frozen at whatever its FIRST morning computed. See
            # `_bucket_decision` and the module docstring for how his drag is told from
            # our own stale paint.
            write, record, pin = _bucket_decision(page, bucket)
            _request(token, "PATCH", f"/pages/{page['id']}",
                     {"properties": _properties(item, record, iid, include_bucket=write,
                                                record_bucket=record, pinned=pin)},
                     opener, budget)
            updated += 1
            moved += 1 if write else 0
            pinned += 1 if pin else 0

    kept = 0
    for iid, page in have.items():
        if iid in wanted:
            continue
        if _scope_of(page) not in healthy:
            kept += 1                      # its source could not answer; leave it alone
            continue
        _request(token, "PATCH", f"/pages/{page['id']}", {"archived": True}, opener, budget)
        archived += 1

    return {"created": created, "updated": updated, "archived": archived,
            "kept": kept, "wanted": len(wanted), "moved": moved, "pinned": pinned}


def read_back(token, db, opener=None, budget=None) -> int:
    return len(existing_rows(token, db, opener, budget=budget))


def collect(now, sources: dict, opener=None, token_file=None, db_file=None,
            budget_s: float = BUDGET_S):
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
    def work(budget):
        # The lock is held INSIDE the budget: a painter that runs out of time also
        # lets go, so the 07:40 job is not refused by a worker the brief abandoned.
        with exclusive():
            counts = paint(buckets, token, db, opener, budget)
        dupes = {}
        seen = len(existing_rows(token, db, opener, dupes_out=dupes, budget=budget))
        return counts, dupes, seen

    try:
        counts, dupes, seen = _bounded(work, budget_s)
    except BoardBusy as exc:
        return [], f"board not written: {exc}"
    except (TimeoutError, Cancelled) as exc:
        # The budget is cancelled before this line runs, so the worker's next Notion
        # call refuses. Partial writes up to that point are ordinary rows the next
        # paint reconciles; what cannot happen is a write after the brief moved on.
        return [], f"board write timed out: {exc}; no further write lands"
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return [], f"board write failed: {type(exc).__name__}: {exc}"

    if dupes:
        return [], (f"duplicate board rows for {len(dupes)} item(s): "
                    f"{', '.join(sorted(dupes))}. Two painters have run; the board "
                    "holds doubles and this run's counts cannot be trusted")
    # `kept` rows belong to a source that could not answer this run: they are on the
    # board and deliberately not in `wanted`. Round 3 (major): comparing `seen` to
    # `wanted` alone made every quiet source report a false read-back mismatch and mark
    # the whole brief degraded, which would have trained him to ignore the word.
    expected = counts["wanted"] + counts["kept"]
    if seen != expected:
        # The write-only-integration scar: a PATCH that returns 200 is not proof the
        # board holds what we think. The read-back is the proof.
        return [], (f"read-back mismatch: expected {expected} row(s) "
                    f"({counts['wanted']} written + {counts['kept']} kept from a quiet "
                    f"source), board shows {seen}")
    return [f"board: {counts['created']} new, {counts['updated']} refreshed, "
            f"{counts['moved']} rebucketed, {counts['archived']} cleared, "
            f"{counts['kept']} kept (source quiet), {counts['pinned']} yours (untouched), "
            "read-back ok"], None
