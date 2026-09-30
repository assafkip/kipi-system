"""THE ONE WAY THE FLEET READS REDDIT. Arctic Shift, PullPush as the fallback.

Founder-directed 2026-09-04: "change any reddit searches on the entire kipi
corpus into arctic shift. Any collection from reddit that is not using arctic
shift should be changed to it. this must be the only way we scrape reddit."

This module is the single home for that. It lives in the kipi-core PLUGIN, not
in one instance, because the audit that produced it found the same transport
written twice with opposite failure semantics and four other reddit fetch paths
besides:

    q-consult/pipeline/reddit_research.py      arctic, raised on total failure
    kipi_mcp/competitive_intel.py              arctic, returned [] on total
                                               failure, so a dead mirror and a
                                               quiet subreddit were the same
                                               value (sp-a5461e0a)
    q-system/.q-system/scripts/reddit_read.py  old.reddit.com HTML scrape
    cole-gtm podcast fetch_reddit_rss          www.reddit.com/.rss
    cole-gtm podcast fetch_reddit_apify        Apify trudax/reddit-scraper-lite
    q-consult icp-signal-reddit.py             www.reddit.com/*.json

Every one of those is now a caller of this module. The rule is enforced by
`tests/test_arctic_is_the_only_reddit_transport.py` here and by the fleet sweep
in `scripts/reddit-transport-audit.py`, not by this docstring.

## Why Arctic Shift and not Reddit

Arctic Shift is an ARCHIVE MIRROR of Reddit. Free, no auth, no app approval. The
routes it replaced, and what each one actually did:

    Apify (trudax/reddit-scraper-lite)  the comment-count flag pushed a cell to
                                        ~240s against a 290s timeout under a
                                        ~300s server wall. 2 of 10 rooms dead.
                                        Retired by the founder: "we stopped
                                        apify - I dont want it."
    reddit.com over plain HTTP          throttled the same day. HTTP 200 with
                                        `Retry-After: 0` and a Welcome page.
    reddit.com/search.json              403 from datacenter IPs.
    the official OAuth API              app creation is gated behind Reddit
                                        approval. The founder has tried many
                                        times and it does not work. Do not
                                        propose it, and do not resurrect
                                        `reddit_api_probe.py`, which documents
                                        an open path that closed.
    a headful browser profile           forbidden, and unnecessary.

MEASURED 2026-08-31 before any of this was wired, not assumed:
    r/taxpros        100 posts, 90 carry a comment count, max 66, span 24.9 days
    r/smallbusiness  100 posts, 100 carry a comment count, span 0.6 days
So the counts are REAL, which is the thing Apify could not give us without
blowing its own ceiling. A busy room returning only 14 hours at limit=100 is the
honest shape of a busy room, not starvation.

## THE RULE THIS MODULE EXISTS TO HOLD

An empty list is never returned for a failed read. `RedditFetchFailed` is
raised. A quiet subreddit and two dead mirrors produce the same empty list, and
a caller cannot tell them apart afterwards, so the distinction has to be made
HERE or it is lost forever. That is the drift this module was built to end: two
copies of the same transport, one raising and one swallowing, and the swallowing
one shipped to the whole fleet.

## READ ONLY, structurally

Founder-directed 2026-08-31: "All I want with reddit is to be able to find and
scrape posts and comments - not find dms etc. I'll post to reddit myself." There
is no write path here, no POST, and no function whose name is an action. Held by
`test_there_is_no_write_path`.

## We identify ourselves truthfully

`USER_AGENT` names the client and gives a contact URL. Impersonating a browser
would be a choice to look like something we are not, made for no benefit. The
mirror needs no auth and no costume, so there is nothing to gain by wearing one.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com"
PULLPUSH_BASE = "https://api.pullpush.io"
# NO COMPANY DOMAIN HERE. This module ships to every instance through the
# skeleton, and validate-separation.py fails the build on a hardcoded brand
# reference for exactly that reason: one instance's domain baked into fleet code
# is wrong in every other instance. It cost this change a red `validate` on
# 2026-09-05, which was the gate doing its job.
#
# We still identify ourselves truthfully. The default names the client and its
# purpose and claims no affiliation; an instance that wants a contact URL sets
# KIPI_REDDIT_UA. Impersonating a browser would be a choice to look like
# something we are not, made for no benefit, since the mirror needs no auth.
USER_AGENT = os.environ.get(
    "KIPI_REDDIT_UA", "kipi-research/1.0 (automated research; contact via repo)")

# The mirror is a plain JSON API, not a hosted actor run, so the ~300s Apify
# server wall that shaped every timeout number in the retired path no longer
# applies. 45s is generous for a call measured under 3s.
DEFAULT_TIMEOUT = 45
DEFAULT_MAX_ITEMS = 15

# Arctic's own ceiling. Asking for more is not an error and not more data; it is
# a silently truncated answer, which is the exact shape this module refuses.
MAX_LIMIT = 100

# RETIRED, kept as a name rather than deleted so a session that greps for the
# actor finds this note instead of finding nothing and re-adding it. Nothing in
# the fleet may call it. Held by the fleet audit script.
RETIRED_ACTOR = "trudax/reddit-scraper-lite"


# A CALLER'S DEADLINE IS NOT A MIRROR REFUSAL, and it is NOT A NETWORK TIMEOUT
# EITHER. Round 8 expressed the first half by letting bare TimeoutError through
# every handler here, which was wrong for a reason worth stating plainly:
# `socket.timeout` IS `TimeoutError` since Python 3.10. So a genuinely hung
# mirror stopped falling back to PullPush and crashed out of read_thread, at
# exactly the moment a fallback matters most (PR 307 round 9).
#
# The distinction is a DEDICATED class, not a builtin somebody else also raises.
# ReadDeadlineExceeded is raised only by a caller's own budget and only that
# propagates; a socket timeout is a refusal like any other and takes the
# fallback.


class ReadDeadlineExceeded(Exception):
    """A CALLER ran out of its own time budget. Never raised by this module and
    never caught by it: the caller sets the budget, so the caller hears about
    it. Distinct from socket.timeout, which is a host problem and gets the
    ordinary fallback."""


class RedditFetchFailed(RuntimeError):
    """Every mirror refused. Raised, never returned as an empty list, because an
    empty list is indistinguishable from an empty subreddit."""


# ---------------------------------------------------------------------------
# transport


def _get_json(url: str, timeout: int, _opener=None, _get=None):
    """Two injection seams, because the callers already had two shapes.

    `_opener` replaces `urllib.request.urlopen` and is what a test that wants to
    assert on headers or on the built Request uses. `_get` replaces the whole
    fetch with `fn(url) -> parsed json`, which is the shape kipi-mcp's collectors
    already inject everywhere (`fetch_json`). Supporting both is what let those
    collectors move onto this transport without rewriting their test doubles;
    the alternative was a second copy of the transport, which is the defect this
    module exists to end."""
    if _get is not None:
        return _get(url)
    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _items(payload) -> list:
    """Arctic wraps rows in {"data": [...]}. PullPush does the same. A bare list
    is accepted because one PullPush deployment returns one.

    AN UNRECOGNISED BODY IS A FAILURE, NOT AN EMPTY ROOM. This returned [] for
    anything it did not recognise, so a 200 carrying an error object, an HTML
    interstitial or a renamed field made `all_comments` report complete=True and
    truncated=False for a thread it had read none of (PR 307 round 9). That is
    the module's founding defect, arriving through the parser instead of through
    the fetch.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if data is None and not payload:
            return []          # a genuinely empty object is an empty answer
    raise RedditFetchFailed(
        "unrecognised mirror body (%s); refusing to read it as an empty result"
        % type(payload).__name__)


def arctic_url(subreddit: str, limit: int, *, after: str = "",
               before: str = "") -> str:
    q = {"subreddit": _clean_sub(subreddit), "limit": min(limit, MAX_LIMIT),
         "sort": "desc"}
    if after:
        q["after"] = after
    # `before` is the cursor for a DESCENDING page, and that is measured rather
    # than assumed (2026-09-05, r/programming, limit=10): passing the last row's
    # created_utc as `after` returned nine rows that OVERLAPPED page one, newest
    # first. Passing it as `before` returned ten strictly older rows with no
    # overlap. A first attempt at paging `recent` used `after` and would have
    # re-fetched the page it had just read.
    if before:
        q["before"] = before
    return f"{ARCTIC_BASE}/api/posts/search?{urllib.parse.urlencode(q)}"


def pullpush_url(subreddit: str, limit: int) -> str:
    q = {"subreddit": _clean_sub(subreddit), "size": min(limit, MAX_LIMIT),
         "sort": "desc"}
    return f"{PULLPUSH_BASE}/reddit/search/submission?{urllib.parse.urlencode(q)}"


def _clean_sub(subreddit: str) -> str:
    return (subreddit or "").lstrip("/").removeprefix("r/").strip().rstrip("/")


def fetch_posts(subreddit: str, *, limit: int = DEFAULT_MAX_ITEMS,
                after: str = "", before: str = "",
                timeout: int = DEFAULT_TIMEOUT,
                _opener=None, _get=None) -> tuple[list, str]:
    """Arctic Shift first, PullPush second. Returns (raw posts, which mirror).

    The fallback is a DIFFERENT HOST, which is what makes it a fallback rather
    than the identical-retry shape that made Apify's `retries=1` worthless.
    """
    try:
        return _items(_get_json(arctic_url(subreddit, limit, after=after,
                                           before=before),
                                timeout, _opener, _get)), "arctic"
    except ReadDeadlineExceeded:
        raise
    except Exception as arctic_exc:
        try:
            return _items(_get_json(pullpush_url(subreddit, limit),
                                    timeout, _opener, _get)), "pullpush"
        except ReadDeadlineExceeded:
            raise
        except Exception as pullpush_exc:
            raise RedditFetchFailed(
                "both mirrors refused r/%s: arctic=%s: %s; pullpush=%s: %s"
                % (_clean_sub(subreddit), type(arctic_exc).__name__, arctic_exc,
                   type(pullpush_exc).__name__, pullpush_exc))


def comments_url(link_id: str, limit: int, after=None) -> str:
    q = {"link_id": str(link_id).removeprefix("t3_"), "limit": min(limit, MAX_LIMIT),
         "sort": "asc",
         "fields": "id,created_utc,author,parent_id,body,score"}
    if after is not None:
        q["after"] = after
    return f"{ARCTIC_BASE}/api/comments/search?{urllib.parse.urlencode(q)}"


def comments(link_id: str, *, limit: int = MAX_LIMIT,
             timeout: int = DEFAULT_TIMEOUT, _opener=None, _get=None) -> list[dict]:
    """Every comment on one thread, oldest first. Raises on a refused read: an
    empty list is a QUIET thread and must never be a broken fetch wearing one."""
    try:
        data = _get_json(comments_url(link_id, limit), timeout, _opener, _get)
    except ReadDeadlineExceeded:
        raise
    except Exception as exc:
        raise RedditFetchFailed("mirror refused comments for %s: %s: %s"
                                % (link_id, type(exc).__name__, exc))
    return _items(data)


def author_url(kind: str, author: str, limit: int) -> str:
    if kind not in ("posts", "comments"):
        raise ValueError("kind must be posts or comments, got %r" % (kind,))
    q = {"author": author, "limit": min(limit, MAX_LIMIT), "sort": "desc",
         "fields": ("id,created_utc,subreddit,title,selftext" if kind == "posts"
                    else "id,created_utc,subreddit,body")}
    return f"{ARCTIC_BASE}/api/{kind}/search?{urllib.parse.urlencode(q)}"


def author_items(author: str, *, limit: int = 25, timeout: int = DEFAULT_TIMEOUT,
                 _opener=None, _get=None) -> dict:
    """{"posts": [...], "comments": [...]} for one author, newest first.
    Raises on a refused read, for the reason `comments` does."""
    out = {}
    for kind in ("posts", "comments"):
        try:
            data = _get_json(author_url(kind, author, limit), timeout, _opener, _get)
        except ReadDeadlineExceeded:
            raise
        except Exception as exc:
            raise RedditFetchFailed("mirror refused %s for u/%s: %s: %s"
                                    % (kind, author, type(exc).__name__, exc))
        out[kind] = _items(data)
    return out


# ---------------------------------------------------------------------------
# one shape for every consumer


def normalize(r: dict, subreddit: str = "", term: str = "") -> dict:
    """One shape for every consumer, so scoring code never re-learns a source's
    field aliases. Bodies are ALWAYS carried: the tell lives in bodies, not
    titles, and a title-only corpus produced a confident n=0 on 2026-08-04.

    Arctic Shift and PullPush both return Reddit's OWN post object, so the field
    names here are Reddit's (`selftext`, `num_comments`, `created_utc`) rather
    than a scraper's rewording of them. The old Apify aliases are kept as a
    second choice so a corpus captured before 2026-08-31 still loads; every one
    of them is dead on the live path.

    `created` is emitted as an ISO string because every consumer parses it that
    way. Reddit hands back a unix float, so the conversion happens HERE, at the
    one normalisation chokepoint, rather than in each caller.
    """
    created = r.get("created_utc") or r.get("created")
    if isinstance(created, (int, float)):
        created = dt.datetime.fromtimestamp(created, dt.timezone.utc).isoformat()
    permalink = r.get("permalink") or ""
    return {
        "subreddit": (r.get("subreddit") or r.get("communityName")
                      or r.get("parsedCommunityName") or _clean_sub(subreddit)),
        "matched_term": term,
        "title": (r.get("title") or "").strip(),
        "body": r.get("selftext") or r.get("body") or r.get("text") or "",
        "url": (r.get("url") if str(r.get("url", "")).startswith("https://www.reddit.com")
                else ("https://www.reddit.com" + permalink if permalink
                      else r.get("url") or r.get("link") or "")),
        "created": created or r.get("createdAt") or r.get("postedDate") or "",
        "score": r.get("score") if r.get("score") is not None else (r.get("upVotes") or 0),
        "num_comments": (r.get("num_comments") if r.get("num_comments") is not None
                         else (r.get("numberOfComments") or 0)),
        "author": r.get("author") or r.get("username") or "",
        "id": r.get("id") or "",
        "permalink": permalink,
    }


def recent(subreddit: str, *, max_items: int = 60, timeout: int = DEFAULT_TIMEOUT,
           _opener=None, _get=None, **_ignored) -> list[dict]:
    """One room's recent posts, normalized. Synchronous.

    `matched_term` is deliberately empty: nothing was searched for, so nothing
    may claim to have matched.

    A thin result here is a QUIET ROOM and may be trusted as one, which was
    never true of the Apify path. Measured 2026-08-31: r/taxpros returned 7
    posts inside a 3-day window and r/smallbusiness returned 100, from the same
    call with the same limit.

    `**_ignored` swallows `with_counts` and `token`, which the retired Apify
    path needed. The mirror returns `num_comments` on every post for free and
    needs no auth, so there is no cheap arm and expensive arm to choose between
    any more. Kept as accepted-and-unused rather than removed so a caller that
    still passes them does not crash on an argument that stopped mattering.
    """
    # PAGE, rather than quietly hand back the ceiling. This used to send
    # min(max_items, 100) and return whatever came, with no flag, while the
    # comment at MAX_LIMIT said asking above the ceiling yields "a silently
    # truncated answer, which is the exact shape this module refuses" (review,
    # MINOR 4: a comment contradicting its own code twenty lines down).
    #
    # The cursor is `before`, MEASURED, not guessed. The first version of this
    # loop used `after` and re-fetched the page it had just read. `+ 1` keeps a
    # row that ties the boundary second, and `seen` throws away the overlap that
    # buys, which is the same trade `all_comments` makes for the same reason.
    raw, mirror = fetch_posts(subreddit, limit=min(max_items, MAX_LIMIT),
                              timeout=timeout, _opener=_opener, _get=_get)
    if max_items > MAX_LIMIT and len(raw) >= MAX_LIMIT:
        seen_ids = {r.get("id") for r in raw}
        cursor = None
        for _ in range(20):                  # a real ceiling, not a while True
            last = raw[-1].get("created_utc")
            nxt = (last + 1) if isinstance(last, (int, float)) else None
            if nxt is None or nxt == cursor:
                break
            cursor = nxt
            page, _m = fetch_posts(subreddit, limit=MAX_LIMIT,
                                   before=str(cursor), timeout=timeout,
                                   _opener=_opener, _get=_get)
            fresh = [r for r in page if r.get("id") not in seen_ids]
            seen_ids.update(r.get("id") for r in fresh)
            raw.extend(fresh)
            if len(raw) >= max_items or len(page) < MAX_LIMIT:
                break
        raw = raw[:max_items]
    out = []
    for record in raw:
        post = normalize(record, subreddit, "")
        post["mirror"] = mirror
        out.append(post)
    return out


def search(subreddit: str, term: str, *, max_items: int = DEFAULT_MAX_ITEMS,
           timeout: int = DEFAULT_TIMEOUT, _opener=None, _get=None,
           **_ignored) -> list[dict]:
    """One subreddit, one term, from the same mirror `recent` uses.

    The mirror has no term parameter on the posts endpoint, so the term is
    applied HERE against title and body. That is a real behaviour change from
    the old Reddit search: it matches what people WROTE rather than what
    Reddit's index would return for a query. The 2026-08-27 measurement said
    Reddit's own search could not match the corpus phrases anyway and silently
    returned the room feed on a miss, so this is the honest version of what was
    already happening.
    """
    # PAGE, like `recent` does, and for the reason `recent` was fixed. The
    # matching happens HERE rather than at the mirror, so one 100-post window is
    # not "the first 100 matches", it is "the matches inside the first 100
    # posts". A room holding ten mentions of the term returned three, and
    # nothing said so (review, MINOR 4).
    #
    # The scan is bounded by pages, not by the caller's max_items, because a
    # rare term could otherwise walk a room forever looking for its tenth hit.
    raw, mirror = fetch_posts(subreddit, limit=MAX_LIMIT,
                              timeout=timeout, _opener=_opener, _get=_get)
    needle_early = (term or "").lower().strip()

    def _hits(rows):
        if not needle_early:
            return len(rows)
        return sum(1 for r in rows
                   if needle_early in ((r.get("title") or "") + " " +
                                       (r.get("selftext") or r.get("body") or "")).lower())

    if len(raw) >= MAX_LIMIT and _hits(raw) < max_items:
        seen_ids = {r.get("id") for r in raw}
        cursor = None
        for _ in range(10):
            last = raw[-1].get("created_utc")
            nxt = (last + 1) if isinstance(last, (int, float)) else None
            if nxt is None or nxt == cursor:
                break
            cursor = nxt
            page, _m = fetch_posts(subreddit, limit=MAX_LIMIT,
                                   before=str(cursor), timeout=timeout,
                                   _opener=_opener, _get=_get)
            fresh = [r for r in page if r.get("id") not in seen_ids]
            seen_ids.update(r.get("id") for r in fresh)
            raw.extend(fresh)
            # STOP ONCE ENOUGH MATCHES ARE IN HAND. It used to page to its
            # ceiling regardless, spending 11 fetches to return 15 hits
            # (review). The term is matched here, so the count is knowable here.
            if len(page) < MAX_LIMIT or _hits(raw) >= max_items:
                break
    needle = (term or "").lower().strip()
    hits = []
    for record in raw:
        post = normalize(record, subreddit, term)
        post["mirror"] = mirror
        if not needle or needle in (post["title"] + " " + post["body"]).lower():
            hits.append(post)
        if len(hits) >= max_items:
            break
    return hits


def thread(link_id: str, *, comment_limit: int = MAX_LIMIT,
           timeout: int = DEFAULT_TIMEOUT, _opener=None, _get=None) -> dict:
    """One thread's comments plus the coverage the read actually achieved.

    THE COVERAGE FIELD IS THE POINT. It replaces the old HTML reader's coverage
    rule, and it exists for the same reason: 536 comments handed back off a
    1190-comment thread, as a plain list, is indistinguishable from a complete
    thread. Silent truncation. So the count that came back and the ceiling that
    bounded it both travel with the data, and a caller that wants completeness
    can see it did not get it.

    `declared` is not available from the comments endpoint alone. A caller that
    has the post (and therefore its `num_comments`) passes it to
    `coverage` itself; this function reports what it fetched and what capped it.
    """
    got = comments(link_id, limit=comment_limit, timeout=timeout,
                   _opener=_opener, _get=_get)
    return {
        "link_id": str(link_id).removeprefix("t3_"),
        "comments": got,
        "fetched": len(got),
        "limit": min(comment_limit, MAX_LIMIT),
        "truncated": len(got) >= min(comment_limit, MAX_LIMIT),
        "source": "arctic",
    }


def coverage(fetched: int, declared) -> float | None:
    """Percent of the declared comment count actually read. None when the thread
    declares nothing, because 0/0 is not 100%."""
    try:
        declared = int(declared)
    except (TypeError, ValueError):
        return None
    if declared <= 0:
        return None
    return round(100.0 * fetched / declared, 1)


def all_comments(link_id: str, *, page_size: int = MAX_LIMIT, max_pages: int = 40,
                 timeout: int = DEFAULT_TIMEOUT, _opener=None, _get=None) -> dict:
    """Every comment on a thread, paging until the mirror stops handing them over.

    THIS IS THE THING THE HTML READER COULD NOT DO. That reader measured its own
    truncation and reported it honestly (536 of 1190 on the worst thread), which
    was the right answer to a wrong transport. The mirror paginates on
    `after=<created_utc>`, so the honest answer here is a COMPLETE thread rather
    than a well-labelled partial one.

    VERIFIED LIVE 2026-09-04 against r/programming thread 1w67dpg, which declares
    108 comments: page one returned 100, page two returned 11. The archive can
    hold slightly more rows than the live post declares, which is why `complete`
    is decided by a short page and never by matching a declared count.

    `max_pages` is a real ceiling and a hit one is reported, not hidden. Returns
    the same coverage vocabulary the artifact contract already uses.
    """
    out: list[dict] = []
    seen: set = set()
    after = None
    pages = 0
    # CAP ONCE, HERE. `comments_url` capped internally while the short-page test
    # below compared against the caller's uncapped number, so page_size=500
    # asked for 100, got 100, saw 100 < 500, and called a 300-comment thread
    # complete after one page (PR 307 review, MINOR 5). That is the exact silent
    # truncation this module's docstring says it exists to end, reintroduced by
    # comparing against a number the request never used.
    page_size = min(page_size, MAX_LIMIT)
    while pages < max_pages:
        url = comments_url(link_id, page_size, after=after)
        try:
            batch = _items(_get_json(url, timeout, _opener, _get))
        except ReadDeadlineExceeded as exc:
            # HAND BACK WHAT WAS ALREADY COLLECTED. The caller's budget ran out;
            # the rows it already paid for are not the mirror's to take back, and
            # `read_thread` builds its partial artifact from exactly this.
            exc.partial = out
            raise
        except Exception as exc:
            raise RedditFetchFailed("mirror refused comments page %d for %s: %s: %s"
                                    % (pages + 1, link_id, type(exc).__name__, exc))
        pages += 1
        fresh = [c for c in batch if c.get("id") not in seen]
        for c in fresh:
            seen.add(c.get("id"))
        out.extend(fresh)
        # A SHORT PAGE ENDS IT, not an empty one. Waiting for empty costs an
        # extra request on every thread; a page under the size asked for cannot
        # be followed by more rows under `after` ordering.
        if len(batch) < page_size:
            return _thread_result(link_id, out, pages, complete=True, capped=False)
        # THE CURSOR IS EXCLUSIVE, so step BACK one second and let `seen` dedupe
        # the overlap. Measured live against Arctic in review: passing a row's
        # own created_utc as `after` returns the rows AFTER it and omits every
        # row sharing that second. The `seen` set protects against an inclusive
        # cursor, which is the opposite case, so it could not recover them: a
        # 106-comment thread came back as 105 rows with complete=True. A missing
        # comment reported as a whole thread is the silent truncation this
        # module exists to end.
        #
        # Overlapping by a second costs at most one repeated page of rows that
        # `seen` throws away. Losing a comment costs a comment, silently.
        last = batch[-1].get("created_utc")
        nxt = (last - 1) if isinstance(last, (int, float)) else last
        if nxt is None or nxt == after:
            # No cursor to advance on. Stopping is correct; claiming completeness
            # is not, because the next page was never asked for.
            return _thread_result(link_id, out, pages, complete=False, capped=False)
        after = nxt
    return _thread_result(link_id, out, pages, complete=False, capped=True)


def _thread_result(link_id, got, pages, *, complete, capped) -> dict:
    return {
        "link_id": str(link_id).removeprefix("t3_"),
        "comments": got,
        "fetched": len(got),
        "pages": pages,
        "complete": complete,
        "capped": capped,
        "source": "arctic",
    }


def posts_by_id_url(ids) -> str:
    if isinstance(ids, str):
        ids = [ids]
    clean = ",".join(str(i).removeprefix("t3_") for i in ids)
    return f"{ARCTIC_BASE}/api/posts/ids?ids={urllib.parse.quote(clean)}"


def posts_by_id(ids, *, timeout: int = DEFAULT_TIMEOUT, _opener=None,
                _get=None) -> list[dict]:
    """The post objects for specific ids, raw.

    This is what makes a thread read able to state its DECLARED comment count,
    which is the number the whole coverage contract is measured against.
    VERIFIED LIVE 2026-09-04: /api/posts/ids?ids=1w67dpg returned one row with
    num_comments 108 and the full permalink.

    There is no PullPush fallback on this endpoint. A caller that loses it loses
    `declared`, not the thread, so it raises here and the caller decides.
    """
    try:
        return _items(_get_json(posts_by_id_url(ids), timeout, _opener, _get))
    except ReadDeadlineExceeded:
        raise
    except Exception as exc:
        raise RedditFetchFailed("mirror refused posts %s: %s: %s"
                                % (ids, type(exc).__name__, exc))


def link_id_from_permalink(permalink: str) -> str:
    """`/r/x/comments/<id>/slug/` -> `<id>`. Accepts a bare id and a full url.

    One parser, because every caller had its own and a wrong one silently reads
    a different thread rather than failing."""
    text = str(permalink or "").strip()
    if "/comments/" in text:
        tail = text.split("/comments/", 1)[1]
        return tail.split("/", 1)[0].split("?", 1)[0]
    return text.strip("/").split("/")[-1].split("?", 1)[0].removeprefix("t3_")
