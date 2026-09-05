"""The transport's contract, proved against a fake opener. No network.

The three claims worth pinning are the three that were WRONG somewhere in the
fleet before this module existed:

  1. a total failure raises, it never returns []   (competitive_intel returned [])
  2. every URL is a mirror, never reddit.com       (reddit_read.py used old.reddit)
  3. there is no write path                        (nothing had checked)
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT))

from reddit_arctic import transport as t  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(payload_by_host):
    """A fake urlopen that answers per host, so an arctic failure and a pullpush
    success can be expressed without patching two different things."""
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for host, payload in payload_by_host.items():
            if host in url:
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(payload)
        raise AssertionError("fake opener got an unexpected host: %s" % url)
    return _open


POST = {"id": "abc", "title": "invoice pile", "selftext": "we key them by hand",
        "subreddit": "taxpros", "created_utc": 1788136000, "score": 4,
        "num_comments": 11, "author": "someone", "permalink": "/r/taxpros/abc/"}


# --- 1. failure is raised, never returned as emptiness ----------------------

def test_both_mirrors_refusing_raises_and_never_returns_empty():
    """sp-a5461e0a: the kipi-mcp copy returned [] here, so a dead mirror and a
    quiet subreddit were the same value and no caller could tell them apart."""
    op = opener_for({"arctic-shift": OSError("arctic down"),
                     "pullpush": OSError("pullpush down")})
    with pytest.raises(t.RedditFetchFailed) as err:
        t.fetch_posts("taxpros", limit=10, _opener=op)
    assert "arctic" in str(err.value) and "pullpush" in str(err.value)


def test_a_quiet_subreddit_returns_empty_and_does_not_raise():
    """The other half of the same contract. Empty must stay meaningful."""
    op = opener_for({"arctic-shift": {"data": []}})
    posts, mirror = t.fetch_posts("taxpros", limit=10, _opener=op)
    assert posts == [] and mirror == "arctic"


def test_pullpush_is_the_fallback_and_reports_itself():
    op = opener_for({"arctic-shift": OSError("arctic down"),
                     "pullpush": {"data": [POST]}})
    posts, mirror = t.fetch_posts("taxpros", limit=10, _opener=op)
    assert len(posts) == 1 and mirror == "pullpush"


def test_comments_raise_rather_than_return_an_empty_thread():
    op = opener_for({"arctic-shift": OSError("refused")})
    with pytest.raises(t.RedditFetchFailed):
        t.comments("t3_abc", _opener=op)


def test_author_items_raise_rather_than_return_an_empty_history():
    op = opener_for({"arctic-shift": OSError("refused")})
    with pytest.raises(t.RedditFetchFailed):
        t.author_items("someone", _opener=op)


# --- 2. every fetch goes to a mirror ---------------------------------------

MIRROR_HOSTS = ("arctic-shift.photon-reddit.com", "api.pullpush.io")


@pytest.mark.parametrize("url", [
    t.arctic_url("taxpros", 10),
    t.pullpush_url("taxpros", 10),
    t.comments_url("t3_abc", 100),
    t.author_url("posts", "someone", 25),
    t.author_url("comments", "someone", 25),
])
def test_every_url_this_module_builds_is_a_mirror(url):
    assert any(h in url for h in MIRROR_HOSTS), url
    assert "reddit.com" not in url.replace("photon-reddit.com", ""), url


def test_the_module_names_no_reddit_host_anywhere_it_fetches():
    """A source-level check, because a new function could add one. Only
    `normalize` may mention www.reddit.com, and only to BUILD a display link
    from a permalink, which is not a fetch. Scoped by function rather than by
    line: the display expression wraps across lines, and a per-line keyword
    guess passed on one line and failed on its continuation."""
    src = (PLUGIN_ROOT / "reddit_arctic" / "transport.py").read_text()
    body = src.split('"""', 2)[-1]          # skip the module docstring
    func = "module"
    for line in body.splitlines():
        if line.startswith("def "):
            func = line[4:].split("(")[0]
        if "reddit.com" not in line or "photon-reddit" in line:
            continue
        assert "https://www.reddit.com" in line, line
        assert func == "normalize", "%s must not name a reddit host: %s" % (func, line)


# --- 3. read only ----------------------------------------------------------

def test_there_is_no_write_path():
    src = (PLUGIN_ROOT / "reddit_arctic" / "transport.py").read_text()
    assert "urlopen(req, data" not in src
    assert "method=\"POST\"" not in src and "method='POST'" not in src
    assert ".post(" not in src


def test_the_retired_actor_is_named_but_never_called():
    src = (PLUGIN_ROOT / "reddit_arctic" / "transport.py").read_text()
    assert t.RETIRED_ACTOR == "trudax/reddit-scraper-lite"
    assert "api.apify.com" not in src


# --- shape -----------------------------------------------------------------

def test_normalize_emits_iso_created_and_carries_the_body():
    out = t.normalize(POST, "taxpros", "invoice")
    assert out["created"].startswith("2026-")
    assert out["body"] == "we key them by hand"
    assert out["url"] == "https://www.reddit.com/r/taxpros/abc/"
    assert out["num_comments"] == 11
    assert out["matched_term"] == "invoice"


def test_recent_tags_every_post_with_the_mirror_that_served_it():
    op = opener_for({"arctic-shift": {"data": [POST]}})
    posts = t.recent("r/taxpros", max_items=5, _opener=op)
    assert posts[0]["mirror"] == "arctic"
    assert posts[0]["matched_term"] == ""


def test_recent_still_accepts_the_dead_apify_arguments():
    """`with_counts` and `token` selected an expensive Apify mode that no longer
    exists. Callers still pass them; they must not crash."""
    op = opener_for({"arctic-shift": {"data": [POST]}})
    assert t.recent("taxpros", max_items=5, with_counts=True, token="x",
                    _opener=op)


def test_search_matches_the_written_body_not_reddits_index():
    op = opener_for({"arctic-shift": {"data": [POST]}})
    assert t.search("taxpros", "key them by hand", _opener=op)
    assert t.search("taxpros", "nothing like this", _opener=op) == []


def test_a_bare_list_payload_is_accepted():
    """One PullPush deployment returns a bare list rather than {"data": [...]}."""
    op = opener_for({"arctic-shift": [POST]})
    posts, _ = t.fetch_posts("taxpros", limit=5, _opener=op)
    assert len(posts) == 1


def test_limits_are_capped_at_the_mirrors_own_ceiling():
    """Asking past the ceiling is not more data, it is a silently truncated
    answer, which is the shape this module exists to refuse."""
    assert "limit=100" in t.arctic_url("taxpros", 5000)
    assert "size=100" in t.pullpush_url("taxpros", 5000)


def test_subreddit_prefixes_are_stripped_once_here():
    for form in ("taxpros", "r/taxpros", "/r/taxpros", "/r/taxpros/"):
        assert "subreddit=taxpros&" in t.arctic_url(form, 10) + "&"


def test_thread_reports_truncation_rather_than_hiding_it():
    """536 comments off a 1190-comment thread, handed back as a plain list, is
    indistinguishable from a complete thread. So the ceiling travels with it."""
    op = opener_for({"arctic-shift": {"data": [{"id": str(i)} for i in range(100)]}})
    got = t.thread("t3_abc", comment_limit=100, _opener=op)
    assert got["fetched"] == 100 and got["truncated"] is True
    assert t.coverage(got["fetched"], 1190) == 8.4


def test_coverage_of_a_thread_that_declares_nothing_is_none_not_full():
    assert t.coverage(0, 0) is None
    assert t.coverage(0, None) is None
    assert t.coverage(32, 34) == 94.1


# --- paging, measured rather than assumed ---------------------------------

def test_a_row_tying_the_cursor_second_is_not_dropped():
    """The cursor is EXCLUSIVE, measured live against Arctic: passing a row's own
    created_utc as `after` omits every row sharing that second. `seen` protects
    against an INCLUSIVE cursor, the opposite case, so it could not recover them
    and a 106-comment thread came back as 105 with complete=True."""
    rows = [{"id": "c%d" % i, "created_utc": 1788136000 + i} for i in range(100)]
    rows.append({"id": "c100", "created_utc": 1788136000 + 99})   # ties the edge
    tail = [{"id": "d%d" % i, "created_utc": 1788136200 + i} for i in range(5)]

    def fake(url):
        import urllib.parse as up
        q = dict(up.parse_qsl(url.split("?", 1)[1]))
        pool = rows + tail
        if "after" not in q:
            return {"data": pool[:100]}
        a = float(q["after"])
        return {"data": [r for r in pool if r["created_utc"] > a][:100]}

    got = t.all_comments("x", _get=fake)
    assert {c["id"] for c in got["comments"]} >= {"c100"}, "boundary row dropped"
    assert got["fetched"] == 106 and got["complete"] is True


def test_recent_pages_past_the_ceiling_on_the_measured_cursor():
    """`recent` used to send min(max_items, 100) and hand back the ceiling with
    no flag, while MAX_LIMIT's comment called that "the exact shape this module
    refuses".

    The cursor is `before`, MEASURED 2026-09-05 against r/programming at
    limit=10: the last row's created_utc passed as `after` returned nine rows
    OVERLAPPING page one; passed as `before` it returned ten strictly older rows.
    The first version of this loop used `after` and re-read its own page.
    """
    pool = [{"id": "p%d" % i, "title": "t", "subreddit": "x",
             "created_utc": 1788136000 - i} for i in range(250)]

    def fake(url):
        import urllib.parse as up
        q = dict(up.parse_qsl(url.split("?", 1)[1]))
        if "before" not in q:
            return {"data": pool[:100]}
        b = float(q["before"])
        return {"data": [p for p in pool if p["created_utc"] < b][:100]}

    out = t.recent("x", max_items=250, _get=fake)
    assert len(out) == 250, len(out)
    assert len({p["id"] for p in out}) == 250, "the overlap was not deduped"


def test_recent_below_the_ceiling_makes_exactly_one_request():
    """The paging must not cost a second call for the ordinary case."""
    calls = []

    def fake(url):
        calls.append(url)
        return {"data": [{"id": "a", "title": "t", "subreddit": "x"}]}

    t.recent("x", max_items=5, _get=fake)
    assert len(calls) == 1, calls


def test_search_pages_because_it_matches_locally():
    """`search` filters the term HERE, not at the mirror, so one 100-post window
    is not "the first 100 matches", it is "the matches inside the first 100
    posts". A room holding ten mentions returned three and said nothing (review,
    MINOR 4). Same silent truncation `recent` was already fixed for."""
    pool = [{"id": "p%d" % i, "subreddit": "x", "selftext": "",
             "title": ("needle" if i % 40 == 0 else "x"),
             "created_utc": 1788136000 - i} for i in range(250)]

    def fake(url):
        import urllib.parse as up
        q = dict(up.parse_qsl(url.split("?", 1)[1]))
        if "before" not in q:
            return {"data": pool[:100]}
        b = float(q["before"])
        return {"data": [p for p in pool if p["created_utc"] < b][:100]}

    hits = t.search("x", "needle", max_items=10, _get=fake)
    assert len(hits) > 3, "one window would have found 3"

    # NEGATIVE CONTROL: a short room must still cost exactly one request
    calls = []

    def one(url):
        calls.append(url)
        return {"data": [{"id": "a", "title": "needle", "subreddit": "x",
                          "selftext": ""}]}

    t.search("x", "needle", _get=one)
    assert len(calls) == 1, calls


def test_the_contract_competitive_intel_depends_on():
    """kipi-mcp's own suite is SKIPPED in CI for missing plugin deps
    (apify-client, feedparser, mcp, pyyaml, tenacity), which is a documented
    exclusion with a ticket, sp-97ce989b. So `competitive_intel` is guarded by
    nothing there (PR 307 review).

    What that module now does with Reddit is delegate to this transport through
    the `_get` seam, so the ONE rule it depends on can be pinned HERE, in a suite
    the floor runs: both mirrors refusing raises, and a quiet subreddit returns
    an empty list. Reverting `_reddit_archive_posts` to `return []` still would
    not fail its own suite; reverting THIS breaks a suite that runs.

    That is a smaller claim than "competitive_intel is tested in CI" and it is
    the true one. The dependency install is a CI-environment change with its own
    blast radius and belongs to its ticket, not to this PR.
    """
    op = opener_for({"arctic-shift": OSError("down"), "pullpush": OSError("down")})
    with pytest.raises(t.RedditFetchFailed):
        t.fetch_posts("taxpros", limit=5, _opener=op)

    # the `_get` seam competitive_intel injects through, both ways
    with pytest.raises(t.RedditFetchFailed):
        t.fetch_posts("taxpros", limit=5,
                      _get=lambda url: (_ for _ in ()).throw(OSError("down")))
    rows, mirror = t.fetch_posts("taxpros", limit=5,
                                 _get=lambda url: {"data": []})
    assert rows == [] and mirror == "arctic", "a quiet room is still empty"


# --- a caller's budget is not a host's problem ----------------------------

def test_a_socket_timeout_still_takes_the_pullpush_fallback():
    """THE ROUND-9 MAJOR, and a regression I shipped in round 8.

    `socket.timeout` IS `TimeoutError` since Python 3.10. Round 8 let bare
    TimeoutError through every handler here so a caller's deadline would not be
    mistaken for a refusal, and in doing so stopped a genuinely hung mirror from
    falling back to PullPush, at exactly the moment a fallback matters most.
    """
    import socket
    calls = []

    def opener(req, timeout=None):
        calls.append(req.full_url)
        if "arctic-shift" in req.full_url:
            raise socket.timeout("hung")
        return _Resp({"data": [{"id": "a"}]})

    rows, mirror = t.fetch_posts("taxpros", limit=5, _opener=opener)
    assert mirror == "pullpush" and len(rows) == 1
    assert len(calls) == 2, calls


def test_a_callers_own_deadline_still_propagates():
    """The other half. A dedicated class, not a builtin somebody else raises."""
    with pytest.raises(t.ReadDeadlineExceeded):
        t.fetch_posts("x", limit=5, _get=lambda u: (_ for _ in ()).throw(
            t.ReadDeadlineExceeded("budget")))


def test_a_deadline_hands_back_the_pages_it_already_collected():
    """The caller's budget ran out; the rows it already paid for are not the
    mirror's to take back."""
    seen = {"n": 0}

    def fake(url):
        seen["n"] += 1
        if seen["n"] > 2:
            raise t.ReadDeadlineExceeded("budget")
        return {"data": [{"id": "c%d_%d" % (seen["n"], i),
                          "created_utc": 1788136000 + seen["n"] * 1000 + i}
                         for i in range(100)]}

    with pytest.raises(t.ReadDeadlineExceeded) as err:
        t.all_comments("x", _get=fake)
    assert getattr(err.value, "partial", None), "the collected pages were dropped"
    assert len(err.value.partial) == 200


def test_an_unrecognised_body_is_a_failure_not_an_empty_room():
    """A 200 carrying an error object, an HTML interstitial or a renamed field
    made all_comments report complete=True for a thread it read none of. That is
    this module's founding defect arriving through the parser instead of the
    fetch."""
    for body in ({"error": "nope"}, "html", 42):
        with pytest.raises(t.RedditFetchFailed):
            t._items(body)

    # NEGATIVE CONTROL: the genuinely empty answers stay empty
    assert t._items({"data": []}) == []
    assert t._items([]) == []
    assert t._items({}) == []
