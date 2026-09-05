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
