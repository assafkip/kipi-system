#!/usr/bin/env python3
"""Read Reddit threads over plain HTTP. No browser, no profile, no session.

## Why this is not the persistent-browsing capability

That capability exists for surfaces a real browser is the only way to reach.
NodeSeek is the proven case: 403 to curl AND to headless Chrome, loads headful.
Reddit was assumed to be in that category and is not.

Measured 2026-08-31, five User-Agents against one thread:

    (no User-Agent header at all)   403
    curl/8.7.1                      403
    Python-urllib/3.14              200, 746652 bytes
    python-requests/2.31            200
    kipi-research/1.0 (+url)        200
    desktop Chrome                  200, 746658 bytes

The block is a UA DENYLIST, not a browser check and not an account check. An
obviously-non-browser Python string passes, so there is nothing to impersonate.
The fleet's recorded knowledge that "Reddit 403s unauthenticated requests" is
true of a request with NO user-agent, and of the `.json` endpoint, and it got
generalised from there into a browser requirement that the measurement does not
support.

This lane therefore needs no Chrome, no persistent profile, no session, and no
exception to canon 2026-07-17, which concerns a Playwright profile LOGIN. It
does not trip `reddit_extension_only_guard.py` either: that hook blocks
`mcp__playwright__*` calls mentioning reddit and shell commands executing
`playwright` or `reddit_driver.py`, and its subject line is "Reddit SENDS".

## We identify ourselves truthfully

Since any UA works, there is no reason to wear a costume. `USER_AGENT` names the
client and gives a contact URL. Impersonating Chrome would be a choice to look
like something we are not, made for no benefit, and the tests forbid it.

## READ ONLY, and structurally so

Founder-directed 2026-08-31: "All I want with reddit is to be able to find and
scrape posts and comments - not find dms etc. I'll post to reddit myself." There
is no write path here, no POST, and no function whose name is an action. Both are
checked rather than asserted in prose.

## THE COVERAGE RULE, which is what this module is really for

One request does not return a whole thread. Measured over a size-stratified
population with `?limit=500`:

    declared  fetched  coverage  stubs
           2        0      0.0%      0   <- never explained, see `anomaly`
          34       32     94.1%      0
          94       88     93.6%      0
         224      218     97.3%      1
         613      485     79.1%      8
         644      515     80.0%     51
        1190      536     45.0%     74

536 comments off a 1190-comment thread, handed back as a plain list, is
indistinguishable from a complete thread. That is silent truncation, and it is
the same defect class as a health check printing "0 dead" having observed
nothing. So nothing here returns comments without also returning what fraction of
the thread they are, and `assert_coverage_recorded` refuses an artifact that
tries.

`data-comments-count` is on the page, so the lane can always know its own
coverage. There is no excuse for it not to say.

    reddit_read.py thread /r/programming/comments/abc/slug/
    reddit_read.py listing programming --period month
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
import pathlib


def _load_reddit_transport():
    """Walk up to the vendored `plugins/kipi-core` and import the transport.

    Walked rather than a fixed `parents[N]`: this script ships to every instance
    and sits at a different depth in some of them. The failure mode a hardcoded
    depth produces is the one `voiceloop/voice_ref.py` records, a caller wired on
    one machine only.
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "plugins" / "kipi-core"
        if (cand / "reddit_arctic").is_dir():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            from reddit_arctic import transport
            return transport
    raise RuntimeError(
        "no plugins/kipi-core/reddit_arctic above %s; this instance has not "
        "taken the skeleton update that ships it" % here)


# Honest identification. Any UA that is not empty and is not curl's default gets
# a 200, so there is nothing to gain by impersonating a browser and the tests
# forbid the strings that would.

# NOT old.reddit.com ANY MORE (2026-09-04, founder-directed: "Any collection from
# reddit that is not using arctic shift should be changed to it. this must be the
# only way we scrape reddit."). BASE is kept as a name because it builds DISPLAY
# links a human clicks, and because a session that greps for it should land on
# this note rather than on nothing.
BASE = "https://www.reddit.com"

# The transport lives once, in the kipi-core plugin. This script is a caller.
_ARCTIC = _load_reddit_transport()

# ONE definition, in the transport. It used to be a second copy of the same
# string here, which is the shape this whole change exists to remove: two copies
# of a rule drift, and this pair drifted into a hardcoded company domain that
# the skeleton's own separation gate refuses.
USER_AGENT = _ARCTIC.USER_AGENT

# 3s pacing 429'd 11 of 12 RSS requests. 10s pacing ran 13 of 13 clean across
# listing pages and thread fetches. This is the measured floor, not a guess.
MIN_INTERVAL_S = 10

# Derived from the population above, not picked:
#   224 declared measured 97.3% in one request
#   613 declared measured 79.1%
# So one request is complete enough at or below 250, and demonstrably is not at
# or above 600. NOTHING WAS MEASURED BETWEEN 224 AND 613, and `choose_strategy`
# says so rather than guessing which side that band falls on.
# These bands described how much of a thread ONE old.reddit request could
# reach. Pagination removed that ceiling, so they no longer choose a
# strategy for the live path; `read_listing` still reports them so a caller
# can rank threads by size, which is the use that outlived the transport.
SINGLE_REQUEST_MAX = 250
LARGE_THREAD_MIN = 600

DEFAULT_TIMEOUT_S = 45

_DECLARED_RE = re.compile(r'data-comments-count="(\d+)"')
_COMMENT_RE = re.compile(r'data-fullname="(t1_[a-z0-9]+)"')
_AUTHOR_RE = re.compile(r'data-author="([^"]*)"')
_MD_RE = re.compile(r'<div class="md">(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class CoverageNotRecorded(Exception):
    """An artifact carrying comments without saying what fraction they are."""


class DiscoveryRefused(Exception):
    """A discovery URL this lane will not use."""


class Pacer:
    """At most one request per `min_interval_s`.

    Clock and sleeper are injected so the interval is testable without the test
    actually sleeping ten seconds, which is how a pacing test ends up deleted.
    """

    def __init__(self, min_interval_s: float = MIN_INTERVAL_S, clock=None, sleeper=None):
        self.min_interval_s = min_interval_s
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval_s - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


class NullPacer:
    """For tests and for a single one-off fetch. Never used by a loop."""

    def wait(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Parsing. Pure, no network, exercised against real captured bytes.
# ---------------------------------------------------------------------------

def declared_count(html: str):
    """Reddit's own count of comments on the thread, or None.

    None is a THIRD state. It means coverage is unknowable for this page, which
    is not 0% and is not complete, and the caller must not round it to either.
    """
    match = _DECLARED_RE.search(html or "")
    return int(match.group(1)) if match else None


def comment_ids(html: str) -> list:
    """Every distinct t1_ fullname, in document order."""
    seen, out = set(), []
    for cid in _COMMENT_RE.findall(html or ""):
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def stub_count(html: str) -> int:
    """Unexpanded "load more comments" stubs. Part of the coverage story: 74 of
    them sat on the thread that returned 45%."""
    return (html or "").count("morecomments")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", fragment or "")).strip()


def parse_comments(html: str) -> list:
    """id, author and body text per comment, in document order.

    Deliberately shallow. Threading, scores and semantic scoring are not this
    module's job; it is a fetcher and an artifact.
    """
    ids = comment_ids(html)
    authors = _AUTHOR_RE.findall(html or "")
    bodies = [_text(b) for b in _MD_RE.findall(html or "")]
    out = []
    for i, cid in enumerate(ids):
        out.append({
            "id": cid,
            "author": authors[i] if i < len(authors) else None,
            "body": bodies[i] if i < len(bodies) else None,
        })
    return out


def coverage_pct(fetched, declared):
    """Percentage of the declared thread actually parsed, or None when the page
    declared nothing. Never silently 100."""
    if declared is None:
        return None
    if declared == 0:
        return 100.0 if fetched == 0 else 0.0
    return round(100.0 * fetched / declared, 1)


def choose_strategy(declared) -> str:
    """Which band this thread falls in, by the measured numbers.

    `unmeasured_band` is a real answer. Between 224 and 613 the population has
    no observation, so calling that band complete-enough would be a claim the
    measurement does not support, and calling it partial would be one too.
    """
    if declared is None:
        return "unknown_size"
    if declared <= SINGLE_REQUEST_MAX:
        return "single"
    if declared >= LARGE_THREAD_MIN:
        return "large_partial"
    return "unmeasured_band"


def parse_thread(html: str, url: str) -> dict:
    """One thread page into a read record. Coverage is computed here and
    COMPARED here; `complete` is a function of that comparison, so a coverage
    number nobody looks at cannot exist."""
    declared = declared_count(html)
    comments = parse_comments(html)
    fetched = len(comments)
    pct = coverage_pct(fetched, declared)

    anomaly = None
    if declared is None:
        anomaly = "no_declared_count"
    elif declared > 0 and fetched == 0:
        # One row in the 2026-08-31 population: 2 declared, 0 parsed, 53 KB,
        # HTTP 200. Never explained. It stays named rather than smoothed into an
        # empty result, because [] reads as "a thread with no comments".
        anomaly = "declared_nonzero_but_none_parsed"

    complete = bool(declared is not None and anomaly is None and fetched >= declared)
    return {
        "url": url,
        "declared": declared,
        "fetched": fetched,
        "coverage_pct": pct,
        "stubs": stub_count(html),
        "complete": complete,
        "truncated": not complete,
        "anomaly": anomaly,
        "comments": comments,
    }


def build_artifact(read: dict, now: dt.datetime) -> dict:
    """The read record plus the path it took and when. Everything a consumer
    needs to know whether it is holding a whole thread."""
    strategy = choose_strategy(read.get("declared"))
    artifact = dict(read)
    artifact.update({
        "fetched_at": now.isoformat(timespec="seconds"),
        "strategy": strategy,
        "expected_incomplete": strategy in ("large_partial", "unmeasured_band"),
        "user_agent": USER_AGENT,
        "refused": False,
        "http_status": 200,
    })
    return artifact


def assert_coverage_recorded(artifact: dict) -> None:
    """Refuse an artifact that carries comments without saying what they are.

    This is the check the lane lives or dies on. A coverage field that is
    computed and never compared is decoration, so there is an executable
    gatekeeper and a mutant that fixes coverage at 100 has to get past it.
    """
    if artifact.get("comments") is None:
        return
    missing = [k for k in ("declared", "fetched", "coverage_pct", "stubs",
                           "complete", "strategy")
               if k not in artifact]
    if missing:
        raise CoverageNotRecorded(
            f"artifact carries comments but is missing {missing}. A comment list "
            "without its coverage reads as a whole thread; 536 of 1190 looked "
            "exactly like 1190 of 1190 in the 2026-08-31 population.")


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def thread_url(permalink: str) -> str:
    """The mirror's comments endpoint for this thread.

    The old version built `old.reddit.com<permalink>?limit=500`, and the 500 was
    the best available answer to a transport that could only ever return one
    page. The mirror PAGES, so completeness stopped being something to buy with
    a query parameter and became something the reader can just do. See
    `read_thread`.
    """
    return _ARCTIC.comments_url(_ARCTIC.link_id_from_permalink(permalink),
                                _ARCTIC.MAX_LIMIT)


def display_url(permalink: str) -> str:
    """The link a human clicks. Never fetched."""
    if str(permalink).startswith("http"):
        return permalink
    return BASE + permalink


def listing_url(subreddit: str, period: str = "month", path_override=None) -> str:
    """Discovery goes through listing HTML.

    RSS is refused rather than merely not-preferred: at 3s pacing it returned
    429 on 11 of 12 requests while listing HTML returned 200 on 6 of 6 at 10s.
    A silent fallback to the throttling endpoint is how a lane starts reporting
    zeros that are really refusals.
    """
    path = path_override or f"/r/{subreddit}/top/"
    if ".rss" in path or path.endswith(".xml"):
        raise DiscoveryRefused(
            f"refusing {path}: discovery goes through the Arctic Shift mirror, "
            "not RSS. Measured 2026-08-31, RSS 429'd 11 of 12 requests at 3s "
            "pacing. The refusal outlived the HTML transport it was written for "
            "because the reason did: a silent fallback to a throttling endpoint "
            "is how a lane starts reporting zeros that are really refusals.")
    sub = path.strip("/").split("/")[1] if path.startswith("/r/") else subreddit
    return _ARCTIC.arctic_url(sub, _ARCTIC.MAX_LIMIT)


# ---------------------------------------------------------------------------
# Transport. One chokepoint, GET only.
# ---------------------------------------------------------------------------

def _default_transport(url: str, headers: dict, timeout: int):
    """(status, body). Never raises. GET only; there is no body parameter and
    no method override, which is what makes the read-only claim structural."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return f"EXC:{type(exc).__name__}", ""


def _refusal(url: str, status, now: dt.datetime) -> dict:
    """A refusal is not a result.

    `fetched` and `coverage_pct` are None, never 0. A 429 recorded as zero
    comments is a throttled run that looks like a quiet one, which is the
    mistake the linux.do harvester already documents.
    """
    return {
        "url": url, "refused": True, "http_status": status,
        "fetched_at": now.isoformat(timespec="seconds"),
        "declared": None, "fetched": None, "coverage_pct": None, "stubs": None,
        "complete": False, "truncated": None, "anomaly": None,
        "comments": None, "strategy": None, "expected_incomplete": None,
        "user_agent": USER_AGENT,
    }


def read_thread(permalink: str, transport=None, pacer=None, now=None,
                timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """One thread, one artifact, from the mirror. Read only.

    THE COVERAGE RULE IS UNCHANGED AND IS NOW USUALLY SATISFIABLE. The rule was
    never "report a percentage"; it was "never hand back comments without saying
    what fraction of the thread they are", because 536 rows off a 1190-comment
    thread looks exactly like a complete one. The HTML transport could only ever
    take one page, so the honest answer was a well-labelled partial. The mirror
    pages on `after=<created_utc>`, so the honest answer is a COMPLETE thread and
    `coverage_pct` reaches 100.

    VERIFIED LIVE 2026-09-04 on r/programming 1w67dpg: declared 108, fetched 111
    across two pages. The archive can hold slightly more rows than the live post
    declares, so `coverage_pct` is allowed above 100 and `complete` is decided by
    pagination exhausting, never by matching `declared`.

    `transport` is still accepted so every existing caller and test double keeps
    working; it is passed to the mirror as its `_get` seam.
    """
    pacer = pacer or NullPacer()
    now = now or dt.datetime.now().astimezone()
    link_id = _ARCTIC.link_id_from_permalink(permalink)
    url = thread_url(permalink)
    getter, seen = _as_getter(transport)
    pacer.wait()
    try:
        declared = None
        rows = _ARCTIC.posts_by_id(link_id, timeout=timeout, _get=getter)
        if rows:
            declared = rows[0].get("num_comments")
        read = _ARCTIC.all_comments(link_id, timeout=timeout, _get=getter)
    except _ARCTIC.RedditFetchFailed as exc:
        return _refusal(url, seen.get("status", "EXC:RedditFetchFailed: %s" % exc), now)

    fetched = read["fetched"]
    artifact = {
        "url": url,
        "display_url": display_url(permalink),
        "refused": False,
        "http_status": 200,
        "fetched_at": now.isoformat(timespec="seconds"),
        "declared": declared,
        "fetched": fetched,
        "coverage_pct": coverage_pct(fetched, declared),
        "stubs": 0,
        "complete": bool(read["complete"]),
        "truncated": bool(read["capped"]),
        "anomaly": None,
        "comments": read["comments"],
        "strategy": "paginate",
        "expected_incomplete": bool(read["capped"]),
        "pages": read["pages"],
        "source": "arctic",
        "user_agent": USER_AGENT,
    }
    assert_coverage_recorded(artifact)
    return artifact


def _as_getter(transport):
    """Adapt the old `(url, headers, timeout) -> (status, body)` transport to the
    mirror's `(url) -> parsed json`, so existing callers and test doubles still
    drive this. Returns `(getter, seen)`.

    A non-200 becomes a raise, which is what the mirror path expects and what
    `read_thread` turns back into a refusal artifact. THE STATUS IS CARRIED OUT
    IN `seen`, not left inside the exception text: a 429 recorded as
    `EXC:something` is a throttled run that no longer looks like a throttled
    run, and telling those apart is the entire reason `_refusal` exists.
    """
    seen = {}
    if transport is None:
        return None, seen

    def _get(url):
        status, body = transport(url, {"User-Agent": USER_AGENT},
                                 DEFAULT_TIMEOUT_S)
        if status != 200:
            seen["status"] = status
            raise RuntimeError("transport returned %s for %s" % (status, url))
        return json.loads(body) if isinstance(body, str) else body
    return _get, seen


def read_listing(subreddit: str, period: str = "month", transport=None,
                 pacer=None, now=None, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Candidate threads with the size the mirror declares for each, so a caller
    can pick by size before spending a request per thread.

    `period` is accepted and no longer filters: the mirror returns a room's most
    recent posts and the window that produces is a property of how busy the room
    is, not something a `t=` parameter can set. Measured 2026-08-31: r/taxpros
    reached back 24.9 days at limit=100 and r/smallbusiness reached 0.6. Kept in
    the signature and echoed in the artifact so no caller breaks, and so the
    lie is visible rather than implied.
    """
    pacer = pacer or NullPacer()
    now = now or dt.datetime.now().astimezone()
    url = listing_url(subreddit, period)
    getter, seen = _as_getter(transport)
    pacer.wait()
    try:
        posts = _ARCTIC.recent(subreddit, max_items=_ARCTIC.MAX_LIMIT,
                               timeout=timeout, _get=getter)
    except _ARCTIC.RedditFetchFailed as exc:
        out = _refusal(url, seen.get("status", "EXC:RedditFetchFailed: %s" % exc), now)
        out["threads"] = None
        return out

    threads = []
    for post in posts:
        permalink = post.get("permalink") or ""
        if not permalink:
            continue
        declared = int(post.get("num_comments") or 0)
        threads.append({"permalink": permalink, "declared": declared,
                        "strategy": choose_strategy(declared),
                        "title": post.get("title", ""), "id": post.get("id", "")})
    threads.sort(key=lambda t: t["declared"])
    return {
        "url": url, "refused": False, "http_status": 200,
        "fetched_at": now.isoformat(timespec="seconds"),
        "subreddit": subreddit, "period": period,
        "period_is_advisory": True,
        "threads": threads, "thread_count": len(threads),
        "source": "arctic",
        "user_agent": USER_AGENT, "comments": None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read Reddit over plain HTTP.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("thread")
    one.add_argument("permalink")
    listing = sub.add_parser("listing")
    listing.add_argument("subreddit")
    listing.add_argument("--period", default="month")
    args = parser.parse_args(argv)

    pacer = Pacer()
    if args.cmd == "thread":
        result = read_thread(args.permalink, pacer=pacer)
    else:
        result = read_listing(args.subreddit, period=args.period, pacer=pacer)
    print(json.dumps(result, indent=2))
    return 1 if result.get("refused") else 0


if __name__ == "__main__":
    raise SystemExit(main())
