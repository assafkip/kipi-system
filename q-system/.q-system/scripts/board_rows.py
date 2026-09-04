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
import time
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


#: Codex round 8 (major): Notion documents roughly three requests per second and asks
#: clients to honour `Retry-After` on a 429. This painter sends one query plus up to 40
#: sequential mutations with no pacing, so an ordinary morning could be rejected
#: part-way and report the whole brief degraded. Retried, not paced: a blanket sleep
#: between every write would spend the 15-second budget on waiting even when nothing is
#: rate limited, and the next paint reconciles a partial board anyway, so the cost of a
#: 429 is alert noise rather than a wrong board.
RATE_LIMIT_RETRIES = 2
#: 502/503 join 429 because they are the same shape: the server saying "not now".
RETRYABLE_STATUS = (429, 502, 503)
#: What the header is allowed to ask for. A server asking for a minute is not something
#: a 15-second budget can honour, and pretending to wait it out is worse than refusing.
RETRY_WAIT_CAP_S = 5.0
RETRY_WAIT_DEFAULT_S = 1.0


def _retry_after(exc) -> float:
    """Seconds the server asked us to wait, clamped. Never trusts the header blindly."""
    raw = None
    headers = getattr(exc, "headers", None)
    if headers is not None:
        try:
            raw = headers.get("Retry-After")
        except AttributeError:
            raw = None
    try:
        wait = float(raw)
    except (TypeError, ValueError):
        wait = RETRY_WAIT_DEFAULT_S
    return max(0.0, min(RETRY_WAIT_CAP_S, wait))


def _request(token, method, path, body=None, opener=None, budget=None):
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        timeout = TIMEOUT_S
        if budget is not None:
            timeout = min(TIMEOUT_S, max(0.001, budget.check()))  # raises Cancelled when spent
        req = urllib.request.Request(
            f"{API}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Notion-Version", VERSION)
        req.add_header("Content-Type", "application/json")
        try:
            with (opener or urllib.request.urlopen)(req, timeout=timeout) as fh:
                return json.load(fh)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == RATE_LIMIT_RETRIES:
                raise
            wait = _retry_after(exc)
            # SLEEPING PAST THE BUDGET IS THE ROUND-4 DEFECT WEARING A RETRY'S COAT.
            # A worker the brief has already abandoned must not still be waiting to
            # write. If the wait does not fit in what is left, this call fails now.
            if budget is not None and wait >= budget.check():
                raise
            time.sleep(wait)


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


#: Seconds of the budget held back so the read-back that PROVES the paint can run. A
#: painter that spends its last millisecond on one more write has no way to say whether
#: the board holds what it thinks, which is the write-only-integration scar.
WRITE_RESERVE_S = 2.0


class _Unreadable:
    """Sentinel for a property shape this module cannot flatten."""
    __slots__ = ()


def _prop_value(prop):
    """One Notion property flattened to something comparable. Unknown shapes -> None,
    which never compares equal, so an unrecognised property means "write it" rather
    than "assume it matches"."""
    if not isinstance(prop, dict):
        return _Unreadable()
    if "title" in prop or "rich_text" in prop:
        parts = prop.get("title") or prop.get("rich_text") or []
        out = []
        for part in parts:
            if "plain_text" in part:
                out.append(part["plain_text"])
            elif isinstance(part.get("text"), dict):
                out.append(part["text"].get("content", ""))
        return "".join(out)
    if "select" in prop:
        return ((prop.get("select") or {}).get("name") or "") or None
    if "multi_select" in prop:
        return tuple(sorted((o.get("name") or "") for o in prop.get("multi_select") or []))
    # A DISTINCT OBJECT, never None (round 13, minor). The docstring below promised
    # that an unreadable property compares unequal and fails toward writing, while
    # None == None made two unreadable shapes compare EQUAL and skip the write, so a
    # row kept stale text forever. A fresh object is equal to nothing but itself.
    return _Unreadable()


def _already_holds(page, props) -> bool:
    """True when the row already carries every value this run would write.

    Round 9 (major): the painter PATCHed every wanted row every run, so a steady
    morning cost one mutation per row against an API documented at roughly three
    requests a second. Almost none of those writes changed anything: the detail and the
    `bucket=`/`pinned=` machinery are the only volatile parts, and on most mornings
    they are identical to what is already there. Comparing against the page we have
    ALREADY read costs nothing and removes the mutation entirely.

    Fails toward writing: any property this cannot read back compares unequal.
    """
    have = page.get("properties") or {}
    for name, want in props.items():
        if _prop_value(have.get(name)) != _prop_value(want):
            return False
    return True


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
        # "Done WHEN", not "Done signal". Founder, 2026-09-04, reading his own board:
        # *"if it says I'm done why is it showing me the thread?"* Every Gmail row read
        # "Done signal: you replied in the thread", which is a past-tense sentence about
        # him, so the row asserted the very thing it was asking for while Status said
        # Not started. The phrasing came off the reference board and I never read it
        # back as a sentence. A criterion has to be written as a condition.
        note += f"Done when: {done}\n"
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


def _fair_share(rows, budget):
    """`rows` reordered so the write budget is shared across SCOPES, round robin.

    ## Why this exists: the two findings that produced it are opposites

    A producer-side cap on mail was removed because trimming DATA meant a still
    unanswered thread never entered `wanted`, and the archive loop then deleted its
    live page inside a healthy scope -- a dragged, pinned row gone because a
    sixteenth thread arrived.

    Uncapped mail then took the whole 40-row budget in source order, so every
    GroupMe row fell past it. Those rows are protected from archiving by `capped`,
    which is round 11's rule working, but protected is not updated: they sit on his
    board unchanged forever while the source that starved them refreshes daily. A
    channel he asked for, permanently frozen, with nothing saying so.

    Capping the producer brings back defect one. Not capping it is defect two. So
    neither is the answer: what was wrong is that a single source could spend the
    whole budget. Each scope now takes one row in turn, so a busy inbox delays the
    tail of its OWN source rather than deleting another source's channel.

    Order within a scope is preserved (the mail prompt sorts oldest first, and that
    ordering is a judgement this function must not re-make). Rows past the budget
    still land in `capped` at the call site and are kept, never archived.
    """
    by_scope, order = {}, []
    for item in rows:
        scope = item.get("scope") or "card"
        if scope not in by_scope:
            by_scope[scope] = []
            order.append(scope)
        by_scope[scope].append(item)
    if len(order) < 2:
        return list(rows)          # one source cannot starve anybody
    out = []
    while len(out) < len(rows):
        for scope in order:
            queue = by_scope[scope]
            if queue:
                out.append(queue.pop(0))
    return out


def paint(buckets: dict, token, db, opener=None, budget=None) -> dict:
    """Create, refresh and archive. Returns a counts dict. Never moves a row."""
    if buckets.get("error"):
        raise ValueError(buckets["error"])

    wanted, scopes, over_cap, capped = {}, {}, 0, set()
    for key, bucket in BUCKET_OF.items():
        # Round 7 (minor): this truncation was SILENT, and the read-back cannot see it
        # because `wanted` has already lost the row before the count is taken. The
        # inbox alone can produce 41 (mail 15 + its overflow row + GroupMe 25), so the
        # 41st vanished with nothing said anywhere. The cap stays -- it bounds the
        # Notion writes -- and what changes is that the loss is now counted and printed
        # beside the other counts. Not an overflow ROW: a synthetic row needs a stable
        # id and a scope, and inventing a scope the painter itself declares healthy
        # would make it a writer of the archive authority it consumes.
        rows_here = _fair_share(buckets.get(key) or [], BUDGET_ROWS)
        over_cap += max(0, len(rows_here) - BUDGET_ROWS)
        for item in rows_here[BUDGET_ROWS:]:
            # A CAPPED ROW IS NOT AN ABSENT ROW (round 11, major). Trimmed rows never
            # entered `wanted`, so the archive loop below saw their live page inside a
            # HEALTHY scope and archived it -- destroying a row he may have dragged and
            # pinned, because the producer emitted one row too many. The cap is a write
            # budget, not a statement that the work is finished.
            with contextlib.suppress(ValueError):
                capped.add(item_id(key, item))
        for item in rows_here[:BUDGET_ROWS]:
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
    created = updated = archived = moved = pinned = unchanged = deferred = 0
    deferred_new = 0

    def out_of_write_budget() -> bool:
        """Stop issuing NEW mutations while there is still time to prove the paint.

        Round 9 (major): BUDGET_ROWS is per BUCKET, so a full paint could ask for 120
        sequential mutations inside a 15-second budget it cannot finish. The cap is not
        raised or replaced by a second invented number -- the real constraint is the
        clock, so the clock is what stops it. With `_already_holds` above, a steady
        morning issues a handful of writes, which is what keeps the deferred tail from
        starving: the next run has almost nothing else to do.
        """
        return budget is not None and budget.check() <= WRITE_RESERVE_S

    for iid, (item, bucket) in wanted.items():
        page = have.get(iid)
        if page is None:
            if out_of_write_budget():
                deferred += 1
                deferred_new += 1
                continue
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
            props = _properties(item, record, iid, include_bucket=write,
                                record_bucket=record, pinned=pin)
            pinned += 1 if pin else 0
            if _already_holds(page, props):
                unchanged += 1
                continue
            if out_of_write_budget():
                deferred += 1
                continue
            _request(token, "PATCH", f"/pages/{page['id']}", {"properties": props},
                     opener, budget)
            updated += 1
            moved += 1 if write else 0

    kept = 0
    for iid, page in have.items():
        if iid in wanted:
            continue
        if iid in capped:
            kept += 1                      # over the write cap this run, not gone
            continue
        if _scope_of(page) not in healthy:
            kept += 1                      # its source could not answer; leave it alone
            continue
        if out_of_write_budget():
            # An unarchived row is on the board, so it counts as kept for the read-back
            # or the proof would report a mismatch about a row we deliberately left.
            kept += 1
            deferred += 1
            continue
        _request(token, "PATCH", f"/pages/{page['id']}", {"archived": True}, opener, budget)
        archived += 1

    return {"created": created, "updated": updated, "archived": archived,
            "kept": kept, "wanted": len(wanted), "moved": moved, "pinned": pinned,
            "over_cap": over_cap, "unchanged": unchanged, "deferred": deferred,
            # Rows we WANTED but never created: they are not on the board, so the
            # read-back must not expect them or a deferred write reads as a mismatch.
            "deferred_new": deferred_new}


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
    # A CARD PROBLEM IS NOT A REASON TO WRITE NOTHING (round 9, major). This used to
    # refuse the whole paint, so a late 07:30 state card also kept Gmail and GroupMe
    # rows off the board -- sources that answered. The stale scope writes nothing, the
    # board carries an alarm row saying the book could not be read, and the line below
    # says it too. Not an `error` return: the job did its work, and an exit code that
    # calls this hour broken is the wolf-cry that costs the real alert later.
    card_error = buckets.get("card_error")
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
    expected = counts["wanted"] + counts["kept"] - counts["deferred_new"]
    if seen != expected:
        # The write-only-integration scar: a PATCH that returns 200 is not proof the
        # board holds what we think. The read-back is the proof.
        return [], (f"read-back mismatch: expected {expected} row(s) "
                    f"({counts['wanted']} written + {counts['kept']} kept from a quiet "
                    f"source), board shows {seen}")
    line = (f"board: {counts['created']} new, {counts['updated']} refreshed, "
            f"{counts['unchanged']} unchanged, "
            f"{counts['moved']} rebucketed, {counts['archived']} cleared, "
            f"{counts['kept']} kept (source quiet), {counts['pinned']} yours (untouched), "
            "read-back ok")
    if counts["over_cap"]:
        line += f"; {counts['over_cap']} row(s) over the {BUDGET_ROWS}-row cap, not written"
    if counts["deferred"]:
        line += (f"; {counts['deferred']} row(s) deferred to the next run "
                 "(write budget spent)")
    if card_error:
        line = f"board: your book could not be read ({card_error}); " + line[len("board: "):]
    return [line], None
