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

If `consulting_board.buckets` reports an error (the 07:30 job crashed, or it has run and
the card is STILL yesterday's), this writes no rows at all and returns that error.
Mirroring a stale source onto a board that looks fresh is the one failure that would
make him act on a wrong number.

Before 07:30 a card stamped yesterday is NOT an error, because yesterday's is then the
newest one there is. The committed brief slot is 07:40, AFTER the card, so on the shipped
schedule this never happens; it happens on a hand run, or on a machine whose job has
drifted early, which is what it was built for. Those rows paint, and each one carries
"from yesterday's card" in its detail so the board never looks fresher than its source.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import sys
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

    Stored in Notes rather than in a property of its own. The original reason was that
    the board's schema should not change at all; that is no longer true, and saying so
    was misleading (round 8, minor). `ensure_columns` now adds up to eight columns
    deliberately, and tells him on the morning line when it does.

    What survives the change is the narrower reason, which is why this still lives in
    Notes: `scope=` is MACHINERY, read back by the painter to decide an archive. A
    column for it would put an internal decision on his board as something to look at
    and edit, and this file has spent a night removing exactly that kind of row.
    Unknown scope is treated as UNHEALTHY by the caller, which fails safe: an
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
    # `url` joined this list with `Link` (PR reviewer, major). Without it every row
    # carrying a Link read as unreadable, `_already_holds` was always False, and the
    # painter PATCHed every Gmail row on every run: a write budget spent re-writing
    # values that had not changed, and a `last_edited_time` that lied about it.
    if "url" in prop:
        return prop.get("url") or None
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
    detail = (item.get("detail") or "").strip()
    note = ""
    if done:
        note += f"Done signal: {done}\n"
    # THE DETAIL IS NOT THE DONE SIGNAL REPEATED. Measured on the live board
    # 2026-09-07: 6 of 12 rows carried "Done signal: X" followed by X character for
    # character, because the GTM producer passes `done_looks_like` as both. The column
    # truncates in his table view, so what he read was the opening fragment of a
    # sentence he was about to read again.
    if detail and detail != done:
        note += detail[:1500]
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
    # NO PRODUCER EMITS `next` TODAY and that is the point (PR reviewer round 3, nit).
    # The constant one the inbox lane briefly had restated DONE_BY_SOURCE and was cut in
    # round 1. The column is filled BY HAND, per row, in his own words -- which is the
    # half of an actionable row nothing here can know -- and this writer's whole job for
    # it is to refuse to blank what he wrote. A producer that learns a real next step
    # later needs no change here.
    #
    # LINK AND NEXT ARE WRITTEN ONLY WHEN THE PRODUCER SUPPLIES THEM, never blanked.
    # A row whose producer knows neither keeps whatever a human put there; clearing it
    # every morning would make the two columns useless on exactly the rows that needed
    # a person to fill them. Same posture as Size, which this module deliberately does
    # not write (see the note above `buckets`).
    link = item.get("link")
    if link:
        props["Link"] = {"url": str(link)[:2000]}
    nxt = item.get("next")
    if nxt:
        props["Next"] = {"rich_text": [{"text": {"content": str(nxt)[:1900]}}]}
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


def _schema_properties(token, db, opener=None, budget=None):
    """The property names this database actually carries, or None when unreadable.

    None means "do not filter", which is the behaviour that shipped before this
    existed. A board whose schema cannot be read is not a board whose columns are
    gone, and refusing to write on a failed read would turn one bad response into a
    blank morning.
    """
    try:
        data = _request(token, "GET", f"/databases/{db}", None, opener, budget)
    except Exception:
        return None
    props = (data or {}).get("properties")
    if not isinstance(props, dict) or not props:
        return None
    # NAME AND TYPE, not name alone (PR reviewer round 7, minor). A board carrying a
    # `Link` column that is rich_text rather than url still takes the 400 this guard
    # exists to prevent, and the guard would have said the column was fine.
    return {name: (p or {}).get("type") for name, p in props.items()}


#: What `_properties` writes, per column, so a board whose column is a different TYPE
#: is treated the same as a board that lacks it: dropped, and said out loud.
WRITES_TYPE = {"Task": "title", "Item id": "rich_text", "Notes": "rich_text",
               "Domain": "multi_select", "Priority": "select", "Source": "select",
               "Bucket": "select", "Status": "select", "Link": "url",
               "Next": "rich_text"}

#: NEVER DROPPABLE (PR reviewer round 8, major). `Item id` is the row's identity: every
#: lookup, every refresh and every archive decision keys on it, and `existing_rows`
#: queries the board by its prefix. Dropping it does not degrade a row, it creates a
#: row this module can never find again -- one more per wanted row per run, forever,
#: with no error anywhere. `Task` is the title, so a row without it is untitled on his
#: board. Losing either is worse than the 400 the filter exists to prevent, so a board
#: that cannot take them stops the paint instead of half-writing it.
UNDROPPABLE = ("Item id", "Task")

#: Columns whose ABSENCE breaks the board rather than costing one value on a row. These
#: are reported every run even when he removed them deliberately, because the failure is
#: silent otherwise and this file's whole posture is that a silent half-working board is
#: worse than a loud broken one.
STRUCTURAL_COST = {
    "Notes": ("without it no row carries its `scope=` line, so nothing is ever "
              "archived and stale rows accumulate with no run able to clear them"),
    "Bucket": ("without it every row lands in none of the three sections and is "
               "invisible on the board"),
}


class MissingIdentityColumn(RuntimeError):
    """The board cannot take a column the painter cannot work without."""


def _only_known(props: dict, known):
    """(props this board can take, names dropped). `known` None -> unchanged, nothing
    dropped, which is what shipped before the filter existed.

    A column is dropped when the board does not have it OR has it under a different
    type. The caller REPORTS what was dropped: silently writing a row without its link
    and then printing "read-back ok" is the quiet half-write this whole file is built
    to refuse (PR reviewer round 7, major).
    """
    if known is None:
        return props, ()
    # TWO LISTS ON PURPOSE. `names` is what the code reasons about; `shown` is what he
    # reads. Annotating the single list broke the undroppable check below, because
    # "Item id" is not "Item id (it is select, this writes rich_text)" and the identity
    # refusal silently stopped firing for the wrong-type case. A display string is not
    # an identifier.
    keep, names, shown = {}, [], []
    for k, v in props.items():
        want = WRITES_TYPE.get(k)
        if k in known and (want is None or known[k] == want):
            keep[k] = v
            continue
        names.append(k)
        # PRESENT, WRONG TYPE. Naming it as absent sends him looking for something that
        # is there; naming the types tells him the one edit that fixes it.
        shown.append(f"{k} (it is {known[k]}, this writes {want})"
                     if k in known else k)
    dropped = tuple(s for _, s in sorted(zip(names, shown)))
    hard = [k for k in UNDROPPABLE if k in names]
    if hard:
        raise MissingIdentityColumn(
            f"the board cannot take {', '.join(hard)}, which the painter identifies "
            "rows by. Writing rows without it would create pages this module can never "
            "find or archive again, one per row per run. Fix the board's columns.")
    return keep, dropped


#: Columns this module writes that it will CREATE on a board that lacks them:
#: EVERYTHING IT WRITES except the identity pair. Listing only Link and Next was a
#: half-heal (PR #332 reviewer round 3, major): a board missing `Notes` cannot carry
#: the `scope=` line, so `_scope_of` reads unknown and no row is ever archived, and a
#: board missing `Bucket` puts every row in none of his three sections. Both were
#: "healed" boards reporting no problem at all.
#:
#: DERIVED, never restated. A column added to WRITES_TYPE and forgotten here would be
#: the same silent half-heal again, one release later.
CREATABLE = tuple(n for n in WRITES_TYPE if n not in UNDROPPABLE)


#: Columns this module has created before, per board. A column in here that is now
#: ABSENT was deleted by a person, and this module does not put it back.
#: ONE literal, because the guard below is path equality against it (PR #334 reviewer
#: round 5, minor). Written twice, renaming the file moved COLUMNS_MADE and left
#: _LIVE_RECORD pointing at a name nothing uses. The guard would then match nothing,
#: refuse nothing, and all 85 board tests would stay green while the protection was
#: gone. A duplicated literal is a silent off switch.
_RECORD_NAME = "board-columns-created.json"
COLUMNS_MADE = STATE_DIR / _RECORD_NAME

#: THE REAL LOCATION, frozen. Production reads `COLUMNS_MADE`, which a test may redirect
#: to tmp to opt in; this one is the fixed answer to "am I about to touch the founder's
#: live file". Two tests DO monkeypatch it, and that is the sanctioned way to exercise
#: the guard without handing it his real path (round 5, minor: the comment here used to
#: claim nothing redirected it, which those same two tests contradicted).
_LIVE_RECORD = STATE_DIR / _RECORD_NAME


def _refuse_live_record_under_test(path):
    """Refuse the founder's real record file while a test is running.

    THE GUARD HAS TO SURVIVE `collect` NAMING THE PATH (PR #334 reviewer round 3,
    major). Requiring an explicit `record=` closed the direct callers and opened the
    one that mattered: `collect` names COLUMNS_MADE itself, so any test reaching
    `collect` sailed through a check the previous commit would have failed. My fix made
    the exact incident case worse while the commit message said it was closed.

    And it cannot key on PYTEST_CURRENT_TEST, because every collect-level test in this
    suite deletes that variable to get past the board's own chokepoint. `sys.modules`
    is the honest signal: pytest is imported for the whole run and no test removes it.
    A test that wants this path redirects `COLUMNS_MADE`, which is what the others
    already do for `LOCK_FILE`.
    """
    if "pytest" not in sys.modules:
        return
    try:
        same = Path(path).resolve() == _LIVE_RECORD.resolve()
    except OSError:
        same = str(path) == str(_LIVE_RECORD)
    if same:
        raise AssertionError(
            f"a test reached the live column record at {_LIVE_RECORD}. Redirect it "
            "with monkeypatch.setattr(board_rows, 'COLUMNS_MADE', tmp_path / ...), "
            "the way LOCK_FILE is redirected.")



def _columns_made(db, path=None):
    """What this module created on `db` before. Unreadable or malformed reads EMPTY.

    `_remember_columns` already refused a non-dict and this did not, so a file holding
    a JSON list raised AttributeError out of `.get`, which no `collect` handler catches
    (they take OSError and ValueError), and the entire board section died on a
    malformed file this module writes itself (PR #332 reviewer round 5, minor). Empty
    is the safe answer: the worst it costs is offering a column he removed once more,
    and that is said on the line.
    """
    # NO AMBIENT DEFAULT ON THE READ EITHER (PR #334 reviewer, minor). The write lost
    # its default and the comment said there was none left; the read still had one, so
    # a caller that omitted `record=` quietly consulted the live file while the module
    # claimed that could not happen. Half a chokepoint described as a whole one.
    if path is None:
        raise AssertionError(
            "no record path given. Production passes record=COLUMNS_MADE explicitly; "
            "a test passes its own tmp path. There is no default.")
    _refuse_live_record_under_test(path)
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    names = data.get(db)
    return set(names) if isinstance(names, (list, tuple, set)) else set()


def _remember_columns(db, names, path=None):
    """Append to the record.

    A WRITE failure is not fatal: an OSError is swallowed and the worst case is
    offering to create a column he removed a second time, which is the behaviour
    before the record existed, and it is still said out loud on the line.

    A MISSING PATH is a different thing and is fatal on purpose (PR #334 reviewer,
    minor: the old docstring said "a failure here is not fatal" flatly, while the
    AssertionError below escapes every except arm in `collect` and takes the whole
    board section with it). That is the intent. A caller that forgot `record=` is a
    programming error, it only reaches this line in a test, and a loud failure in the
    suite is exactly what stops it reaching his machine.

    THE LIVE RECORD IS NEVER WRITTEN BY A TEST, and that is a chokepoint rather than a
    rule someone remembers (PR #332 reviewer round 7, minor). `collect` has had this
    guard for the board itself; this file did not, so a test that simply forgot
    `record=` wrote into ~/.config/kipi and taught the 07:40 job that he had deleted
    columns he never touched. That happened, once, in this PR. Three separate rounds
    of it found a test reaching something live and each was fixed by hand; a hand fix
    protects the tests that exist today. This one protects the ones nobody has written.
    """
    if path is None:
        # NO AMBIENT DEFAULT. The first version of this guard refused only when
        # PYTEST_CURRENT_TEST was set, and every test in this suite that reaches
        # `collect` deletes that variable to get past the board's own chokepoint -- so
        # the guard was bypassed by the exact idiom that caused the problem it was
        # written for, and I had already described it to the founder as a mechanism
        # rather than a discipline (PR #332 reviewer round 9, minor).
        #
        # There is no environment to read now: the live path is reachable only by a
        # caller that names it, which is `collect` and nothing else. A test that
        # forgets `record=` fails the same way on any machine, in any environment,
        # whether or not pytest is announcing itself.
        raise AssertionError(
            "no record path given. Production passes record=COLUMNS_MADE explicitly; "
            "a test passes its own tmp path. There is no default.")
    _refuse_live_record_under_test(path)
    p = Path(path)
    try:
        data = json.loads(p.read_text("utf-8")) or {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[db] = sorted(set(data.get(db) or []) | set(names))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, sort_keys=True), "utf-8")
    except OSError:
        pass


def ensure_columns(known, token, db, opener=None, budget=None, *, record):
    """Add the optional columns this board is missing. Returns (schema, problems).

    `record` IS REQUIRED, and keyword-only so it cannot be passed by accident (PR #334
    reviewer round 2, minor). The inner reader and writer both refuse a missing path,
    and this signature still offered `record=None`, so the refusal arrived from two
    frames down as an AssertionError no `collect` arm catches, instead of from the call
    a person was looking at. A default whose only outcome is a crash is not a default.
    `opener` and `budget` keep theirs: those are genuinely optional and every test in
    the suite omits them.

    A REFUSED OR UNCONFIRMED CREATE is not fatal and degrades with its reason on the
    line. A missing `record` is a programming error and is meant to be loud; the old
    docstring flattened both into "failure here is not fatal", which was true of one of
    them.

    THE FEATURE WAS DEAD ON EVERY BOARD BUT ONE (PR reviewer round 12, major). Nothing
    created `Link`, so `_only_known` dropped it on every run and the morning line said
    the board could not take it and named no way to change that. The column had been
    added by hand, once, on the founder's own board; a fresh instance would have
    reported the same sentence every morning forever. Silent degradation with a
    permanent explanation is not a fix.

    Failure is not fatal: on a refusal the schema is returned unchanged and the drop
    path reports it, which is exactly the behaviour before this existed.
    """
    if known is None:
        return None, ()
    missing = {name: WRITES_TYPE[name] for name in CREATABLE if name not in known}
    # A COLUMN HE DELETED IS NOT A COLUMN THAT IS MISSING (PR #332 reviewer round 4,
    # major). Without this the module re-created it every single morning and never said
    # so: he would remove a column he did not want and find it back the next day, with
    # no way to make it stop. That is the same "his choice wins" line the row painter
    # holds everywhere else, one level down at the schema.
    made_before = _columns_made(db, record)
    removed = sorted(n for n in missing if n in made_before)
    for n in removed:
        del missing[n]

    # A column PRESENT UNDER THE WRONG TYPE is deliberately not healed here (PR #332
    # reviewer, minor). Creating an absent column adds nothing and loses nothing;
    # retyping an existing one makes Notion convert every value in it, which is a data
    # decision and not this module's to take. What was wrong was the message: it said
    # the board "cannot take" the column, so he would go looking for something that is
    # sitting right there. `_only_known`'s report now says which it is.
    # A REMOVAL HE CAN AFFORD IS SILENT; ONE HE CANNOT IS SAID EVERY RUN.
    #
    # Round 5 tried to solve the double-naming by filtering these out of the
    # dropped-columns sentence through a module global. That was worse than the problem
    # twice over (round 6): the global was never cleared and unioned across every board
    # id, so the report cross-contaminated and the suite went order-dependent; and it
    # silenced the warning for `Notes` and `Bucket`, whose absence stops archiving
    # entirely and hides every row from his three sections, WHILE the line still ended
    # "read-back ok". Silent degradation is the one thing this file exists to refuse.
    #
    # The real distinction is consequence, and it needs no state at all. Losing `Notes`
    # or `Bucket` breaks the board, so it is named every run, with what it costs, until
    # he puts it back.
    #
    # NOT SILENCE, ONE MENTION (round 7, minor: the previous comment and its test both
    # claimed silence and the dropped-columns sentence still named the column every
    # run, so the claim was simply false). Losing `Link` or `Next` costs one value on a
    # row, so it earns no SECOND sentence explaining itself, and the report that the
    # value was not written stands as it does for any other column. Suppressing that
    # too is what round 5 did, and it hid `Notes` and `Bucket` with it.
    told = tuple(
        f"{n} is gone and this module created it, so it is treated as your removal; "
        + STRUCTURAL_COST[n] for n in removed if n in STRUCTURAL_COST)
    if not missing:
        return known, told
    try:
        data = _request(token, "PATCH", f"/databases/{db}",
                        {"properties": {n: {t: {}} for n, t in missing.items()}},
                        opener, budget)
    except Exception as exc:
        # A REFUSAL IS NOT AN ABSENCE (PR #332 reviewer, minor). Both used to end in
        # the same sentence, so he could not tell "this board has no Link column" from
        # "I tried to add one and Notion said no", and only the second is about
        # permissions or a token. The reason is carried back and said.
        #
        # AND THE BODY, NOT JUST THE STATUS LINE (round 4, minor). "HTTPError: 400 Bad
        # Request" is the half that says nothing; Notion puts what is actually wrong in
        # the response body, which is the whole reason this branch exists.
        detail = ""
        try:
            detail = " " + exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        # THE CONSEQUENCE BELONGS TO THE ABSENCE, NOT TO THE REASON (round 7, minor).
        # It was attached only to his deletion, so a board where Notion REFUSED to
        # create `Notes` reported the refusal and never that nothing would be archived,
        # which is the half he needs.
        cost = tuple(f"{n}: {STRUCTURAL_COST[n]}" for n in sorted(missing)
                     if n in STRUCTURAL_COST)
        return known, told + ((f"{type(exc).__name__}: {exc}{detail}")[:300],) + cost
    # WHAT NOTION RETURNED, not what we asked for (PR #332 reviewer, minor). Synthesising
    # `dict(known, **missing)` asserts the create took effect; if it did not, the next
    # write carries the column anyway and takes the raw 400 this whole guard exists to
    # prevent, losing the morning's paint. The PATCH response is the database, so its
    # properties are the answer.
    fresh = (data or {}).get("properties")
    if isinstance(fresh, dict) and fresh:
        made = sorted(n for n in missing if n in fresh)
        if made:
            _remember_columns(db, made, record)
        # A RESPONSE THAT ANSWERS AND STILL LACKS THE COLUMN IS NOT A SUCCESS (round 8,
        # minor). The empty-properties and refusal paths both report an unconfirmed
        # create; this one returned no problem at all, so a Notion that accepts the
        # PATCH and quietly does not add the column read as a clean run.
        absent = sorted(n for n in missing if n not in fresh)
        if absent:
            return ({n: (p or {}).get("type") for n, p in fresh.items()},
                    told + (f"asked Notion for {', '.join(absent)} and the schema it "
                            "returned does not carry them, so they were not written",)
                    + tuple(f"{n}: {STRUCTURAL_COST[n]}" for n in absent
                            if n in STRUCTURAL_COST)
                    + ((f"added the {', '.join(made)} "
                        + ("columns" if len(made) > 1 else "column")
                        + " to this board",) if made else ()))
        # SAID OUT LOUD (round 4, major). Adding columns to his board is a change to
        # his board, and a change he is not told about is one he cannot disagree with.
        return ({n: (p or {}).get("type") for n, p in fresh.items()},
                told + ((f"added the {', '.join(made)} "
                         + ("columns" if len(made) > 1 else "column")
                         + " to this board",) if made else ()))
    unconfirmed = tuple(f"{n}: {STRUCTURAL_COST[n]}" for n in sorted(missing)
                        if n in STRUCTURAL_COST)
    return known, told + ("the schema PATCH returned no properties, so the new columns "
                          "are unconfirmed and were not written",) + unconfirmed


def _refuse_without_identity(known):
    """Raise when the board cannot take a column the painter works by. `known` None
    (schema unreadable) is not a verdict about the columns, so it passes."""
    if known is None:
        return
    missing = [k for k in UNDROPPABLE
               if k not in known or known[k] != WRITES_TYPE[k]]
    if missing:
        raise MissingIdentityColumn(
            f"the board cannot take {', '.join(missing)}, which the painter "
            "identifies rows by. Writing rows without it would create pages this "
            "module can never find or archive again, one per row per run. Fix the "
            "board's columns.")


def _drop_and_note(props, known, sink: set):
    """`_only_known`, recording what it dropped into `sink` for the caller to report."""
    keep, dropped = _only_known(props, known)
    sink.update(dropped)
    return keep


def paint(buckets: dict, token, db, opener=None, budget=None, known=None) -> dict:
    """Create, refresh and archive. Returns a counts dict. Never moves a row.

    `known` is the set of property names this board actually has, or None for "write
    everything", which is what shipped before it existed. It is READ BY THE CALLER and
    passed in rather than fetched here, so driving `paint` directly makes exactly the
    requests it always made. See `_schema_properties` for why the filter exists.
    """
    if buckets.get("error"):
        raise ValueError(buckets["error"])

    #: Every column this run could not write, so the morning line can say so. A link
    #: dropped in silence is worse than a crash: the crash gets looked at.
    dropped_cols: set = set()

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
    #: Rows HE pinned whose producer went quiet: kept because he placed them, and
    #: counted apart from `kept` (a quiet source) and `pinned` (a live row he moved),
    #: because the morning line reports all three and they are three different facts.
    #: It is a term of the read-back sum below: a held row IS on the board, so leaving
    #: it out made the proof report a mismatch every run after any pinned row's
    #: producer went quiet (PR reviewer round 4, major).
    held = 0
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
                      "properties": _drop_and_note(
                          _properties(item, bucket, iid, include_bucket=True,
                                      status="Not started"), known, dropped_cols)},
                     opener, budget)
            created += 1
        else:
            # Codex round 6 (major): this passed include_bucket=False unconditionally,
            # so a row's bucket was frozen at whatever its FIRST morning computed. See
            # `_bucket_decision` and the module docstring for how his drag is told from
            # our own stale paint.
            write, record, pin = _bucket_decision(page, bucket)
            # FILTERED BEFORE THE COMPARISON, not after (PR reviewer round 6, minor).
            # Comparing the full property set against a board that cannot hold `Link`
            # made the row differ forever: it was PATCHed every run, `unchanged` stayed
            # at zero, and the write budget went on rewriting values nobody changed.
            # What is compared has to be what is written.
            props = _drop_and_note(
                _properties(item, record, iid, include_bucket=write,
                            record_bucket=record, pinned=pin), known, dropped_cols)
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
        if _note_field(page, PINNED_LINE.split("=")[0] + "="):
            # HIS DRAG SURVIVES THE PRODUCER DROPPING THE ROW (PR reviewer, major).
            # The module's contract is that a row a human moved is never moved or
            # re-bucketed by the machine, and this loop was the hole in it: a row he
            # had pinned was still archived the moment its producer stopped emitting
            # it, taking his placement and his Status with it and recreating the row
            # at "Not started" when the producer came back. Filtering white client
            # lines out of the board (DEC-34) makes that flip ordinary rather than
            # rare, which is how the reviewer found it.
            #
            # HIS EXIT IS HIS OWN ARCHIVE, and that is the whole answer to "a pinned
            # row has no exit" (PR reviewer round 2, major). The first answer was a
            # stamp written into the row's Notes saying its source had gone quiet. It
            # cost three findings across two rounds and the last of them was serious:
            # the note's machinery lines (`scope=`, `bucket=`, `pinned=`) live at the
            # END, so truncating the note to make room for the stamp deleted the pin
            # the stamp existed to protect. The file already warns about exactly that
            # above NOTE_CAP, and the fix walked into it anyway.
            #
            # A row he pinned is a row he placed. This module's contract is that the
            # machine never moves or removes it; removing it is his, in the UI, the
            # same exit he has for every other row he ever pinned. Counted as `held`
            # rather than folded into `kept`, because `kept` means the SOURCE went
            # quiet and this source answered fine.
            held += 1
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
            "held": held, "dropped_columns": tuple(sorted(dropped_cols)),
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
            # The schema read happens HERE, once per run, and its answer is handed
            # to the painter. See `_schema_properties`: a board that predates `Link`
            # and `Next` would otherwise take a 400 on the first row and lose the
            # whole morning's paint to a column nobody noticed was missing.
            known = _schema_properties(token, db, opener, budget)
            # IDENTITY FIRST, THEN HEAL (PR #332 reviewer, major). The first cut had
            # these the other way round, so a database this module then rejected as
            # "not our board" had already had two columns PATCHed onto it. Deciding
            # whether a thing is ours has to come before writing to it. Worse, the
            # test that shipped with it asserted the wrong order and called it
            # correct, which is how a mistake gets a guard of its own.
            #
            # `_refuse_without_identity` also has to run BEFORE the first query:
            # `existing_rows` filters on `Item id`, so a board without that column
            # takes a raw 400 from Notion before `_only_known` is ever reached and the
            # remediation sentence never fires (#327 round 10, minor).
            _refuse_without_identity(known)
            # The live record is named HERE, by the one caller that should touch it.
            known, column_problems = ensure_columns(known, token, db, opener, budget,
                                                    record=COLUMNS_MADE)
            counts = paint(buckets, token, db, opener, budget, known=known)
            counts["column_problems"] = column_problems
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
    except MissingIdentityColumn as exc:
        # ITS OWN ARM, ahead of the generic one (PR reviewer round 9, minor). This is
        # the one failure here that a person can actually fix, and the whole point of
        # raising it is the sentence it carries. Falling through to the generic arm
        # printed "MissingIdentityColumn" and threw the remediation away, which is the
        # class-name-instead-of-help shape this file refuses everywhere else.
        return [], str(exc)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return [], f"board write failed: {type(exc).__name__}: {exc}"

    notes = "".join(f"; {n}" for n in (counts.get("column_problems") or ()))
    if dupes:
        return [], (notes.lstrip("; ") + ("; " if notes else "")
                    + f"duplicate board rows for {len(dupes)} item(s): "
                    f"{', '.join(sorted(dupes))}. Two painters have run; the board "
                    "holds doubles and this run's counts cannot be trusted")
    # `kept` rows belong to a source that could not answer this run: they are on the
    # board and deliberately not in `wanted`. Round 3 (major): comparing `seen` to
    # `wanted` alone made every quiet source report a false read-back mismatch and mark
    # the whole brief degraded, which would have trained him to ignore the word.
    expected = (counts["wanted"] + counts["kept"] + counts["held"]
                - counts["deferred_new"])
    if seen != expected:
        # The write-only-integration scar: a PATCH that returns 200 is not proof the
        # board holds what we think. The read-back is the proof.
        return [], (notes.lstrip("; ") + ("; " if notes else "")
                    + f"read-back mismatch: expected {expected} row(s) "
                    f"({counts['wanted']} written + {counts['kept']} kept from a quiet "
                    f"source + {counts['held']} held for you), board shows {seen}")
    line = (f"board: {counts['created']} new, {counts['updated']} refreshed, "
            f"{counts['unchanged']} unchanged, "
            f"{counts['moved']} rebucketed, {counts['archived']} cleared, "
            f"{counts['kept']} kept (source quiet), {counts['pinned']} yours (untouched), "
            f"{counts['held']} yours (source stopped reporting it), "
            "read-back ok")
    for note in counts.get("column_problems") or ():
        line += f"; {note}"
    if counts["dropped_columns"]:
        # NEVER SILENT. The filter stops a missing column aborting the paint; it must
        # not also hide that the rows went out without it. A board missing `Link` wrote
        # every row without its link and still said "read-back ok" (round 7, major).
        #
        # "cannot take", not "has no": the column may be present under the wrong TYPE,
        # and telling him it is missing sends him looking for something that is there
        # (round 8, minor). The plural is counted rather than assumed for the same
        # reason: a line that says "column" about three of them reads as one.
        names = counts["dropped_columns"]
        line += ("; this board cannot take the "
                 + ", ".join(names)
                 + (" columns" if len(names) > 1 else " column")
                 + ", so those values were not written")
    if counts["over_cap"]:
        line += f"; {counts['over_cap']} row(s) over the {BUDGET_ROWS}-row cap, not written"
    if counts["deferred"]:
        line += (f"; {counts['deferred']} row(s) deferred to the next run "
                 "(write budget spent)")
    if card_error:
        line = f"board: your book could not be read ({card_error}); " + line[len("board: "):]
    return [line], None
