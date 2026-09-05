#!/usr/bin/env python3
"""The Reddit read lane: an HTTP client with an honest User-Agent.

WHY THERE IS NO BROWSER HERE. Measured 2026-08-31 across five UA strings against
the same thread:

    no User-Agent header at all   403
    curl/8.7.1  (curl's default)  403
    Python-urllib/3.14            200, 746652 bytes
    python-requests/2.31          200
    kipi-research/1.0 (+url)      200
    desktop Chrome                200, 746658 bytes

So the block is a UA DENYLIST, not a browser check and not an account check. An
obviously-non-browser Python string passes. That means the lane needs no Chrome,
no persistent profile, no session, and no exception to canon 2026-07-17, which
concerns a Playwright profile LOGIN. It also means we identify ourselves
truthfully rather than impersonating a browser, which the tests below pin.

THE CHECK THIS LANE LIVES OR DIES ON IS COVERAGE. Measured over a size-stratified
population, one request with ?limit=500:

    declared  fetched  coverage  stubs
           2        0      0.0%      0   <- unexplained, see the anomaly tests
          34       32     94.1%      0
          94       88     93.6%      0
         224      218     97.3%      1
         613      485     79.1%      8
         644      515     80.0%     51
        1190      536     45.0%     74

A bare comment list from the last row reads exactly like a complete thread. That
is silent truncation, the same defect class as a health run printing "0 dead"
having observed nothing, and it is why every artifact carries declared, fetched,
coverage and stub count rather than just comments.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "reddit_read.py"
FIXTURE = HERE / "fixtures" / "old_reddit_thread_trimmed.html"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rr():
    return _load(MODULE, "reddit_read")


@pytest.fixture(scope="module")
def real_html():
    """Real bytes off a live thread, trimmed to three verbatim slices. Its
    provenance header records what was kept. It shows 8 parsed comments against
    a declared 224, which is the truncation shape, from the producer."""
    return FIXTURE.read_text()


def _code_only(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, holders) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body.pop(0)
                if not node.body:
                    node.body.append(ast.Pass())
    return ast.unparse(tree)


# ---------------------------------------------------------------------------
# CONSTRAINT 1 -- self-reported coverage. The one the lane lives or dies on.
# ---------------------------------------------------------------------------

def test_parses_the_declared_count_off_the_real_page(rr, real_html):
    assert rr.declared_count(real_html) == 224


def test_parses_comment_ids_off_the_real_page(rr, real_html):
    ids = rr.comment_ids(real_html)
    assert len(ids) == 8, ids
    assert all(i.startswith("t1_") for i in ids)


def test_counts_stubs_off_the_real_page(rr, real_html):
    assert rr.stub_count(real_html) == 1


def test_coverage_is_computed_against_the_declared_count(rr, real_html):
    read = rr.parse_thread(real_html, url="https://old.reddit.com/x")
    assert read["declared"] == 224
    assert read["fetched"] == 8
    assert read["coverage_pct"] == pytest.approx(3.6, abs=0.1)


def test_a_truncated_fetch_is_flagged_truncated(rr, real_html):
    """THE MUTANT THIS EXISTS FOR: a lane that reports full coverage on a
    truncated fetch. 8 of 224 must never read as a complete thread."""
    read = rr.parse_thread(real_html, url="https://old.reddit.com/x")
    assert read["complete"] is False
    assert read["truncated"] is True


def test_a_complete_fetch_is_not_flagged_truncated(rr, real_html):
    """Derived from the SAME real bytes by rewriting only the declared count, so
    the markup stays the producer's. Without this arm, a module that hardcodes
    truncated=True passes the arm above."""
    html = real_html.replace('data-comments-count="224"', 'data-comments-count="8"')
    read = rr.parse_thread(html, url="https://old.reddit.com/x")
    assert read["declared"] == 8 and read["fetched"] == 8
    assert read["coverage_pct"] == pytest.approx(100.0)
    assert read["complete"] is True and read["truncated"] is False


def test_coverage_is_COMPARED_not_merely_computed(rr, real_html):
    """A coverage field that is written and never read is decoration. `complete`
    must be a function of the comparison, so a mutant that fixes coverage at
    100.0 flips this."""
    truncated = rr.parse_thread(real_html, url="u")
    complete = rr.parse_thread(
        real_html.replace('data-comments-count="224"', 'data-comments-count="8"'), url="u")
    assert truncated["complete"] != complete["complete"]


def test_the_artifact_never_carries_comments_without_coverage(rr, real_html):
    """No caller can obtain a bare comment list from this module. Every artifact
    that has `comments` also has the four numbers that say what it is."""
    art = rr.build_artifact(rr.parse_thread(real_html, url="u"),
                            now=dt.datetime(2026, 8, 31, 12, 0))
    assert "comments" in art
    for key in ("declared", "fetched", "coverage_pct", "stubs", "complete", "strategy"):
        assert key in art, f"artifact is missing {key}"
    rr.assert_coverage_recorded(art)


def test_assert_coverage_recorded_rejects_a_bare_comment_list(rr):
    with pytest.raises(rr.CoverageNotRecorded):
        rr.assert_coverage_recorded({"comments": [{"id": "t1_x"}], "url": "u"})


# ---------------------------------------------------------------------------
# CONSTRAINT 2 -- thread size decides strategy, thresholds DERIVED not picked
# ---------------------------------------------------------------------------

def test_the_thresholds_are_the_measured_ones(rr):
    """224 declared measured 97.3%; 613 measured 79.1%. The constants have to be
    the numbers that separated those observations, not round guesses."""
    assert rr.SINGLE_REQUEST_MAX == 250
    assert rr.LARGE_THREAD_MIN == 600


@pytest.mark.parametrize("declared,expected", [
    (2, "single"), (34, "single"), (224, "single"), (250, "single"),
    (251, "unmeasured_band"), (599, "unmeasured_band"),
    (600, "large_partial"), (1190, "large_partial"),
])
def test_strategy_follows_the_measured_bands(rr, declared, expected):
    assert rr.choose_strategy(declared) == expected


def test_the_unmeasured_band_is_named_as_unmeasured(rr):
    """Between 224 and 613 nothing was measured. Calling that band `single`
    would be a claim the population does not support, and calling it
    `large_partial` would be one too. It says what it is."""
    assert "unmeasured" in rr.choose_strategy(400)


def test_the_artifact_records_which_path_it_took(rr, real_html):
    art = rr.build_artifact(rr.parse_thread(real_html, url="u"),
                            now=dt.datetime(2026, 8, 31, 12, 0))
    assert art["strategy"] == "single"  # declared 224
    assert art["expected_incomplete"] is False


def test_a_large_thread_declares_that_it_is_expected_to_be_incomplete(rr, real_html):
    html = real_html.replace('data-comments-count="224"', 'data-comments-count="1190"')
    art = rr.build_artifact(rr.parse_thread(html, url="u"),
                            now=dt.datetime(2026, 8, 31, 12, 0))
    assert art["strategy"] == "large_partial"
    assert art["expected_incomplete"] is True


# ---------------------------------------------------------------------------
# The unexplained row. It stays unexplained IN THE RECORD.
# ---------------------------------------------------------------------------

def test_declared_nonzero_with_nothing_parsed_is_an_anomaly_not_an_empty_result(rr):
    """One row in the population read 2 declared, 0 fetched, 53 KB, HTTP 200. It
    was never explained. If the lane meets that shape live it says so, rather
    than handing back [] which reads as a thread with no comments."""
    html = '<div data-comments-count="2"></div>'
    read = rr.parse_thread(html, url="u")
    assert read["fetched"] == 0 and read["declared"] == 2
    assert read["anomaly"] == "declared_nonzero_but_none_parsed"
    assert read["complete"] is False


def test_a_genuinely_empty_thread_is_not_an_anomaly(rr):
    """0 declared and 0 parsed is a real, complete, empty thread. Flagging it
    would make the anomaly signal meaningless."""
    read = rr.parse_thread('<div data-comments-count="0"></div>', url="u")
    assert read["anomaly"] is None
    assert read["complete"] is True


def test_a_missing_declared_count_is_its_own_state(rr, real_html):
    """No declared count means coverage is UNKNOWABLE, which is not the same as
    0% and not the same as complete."""
    html = real_html.replace('data-comments-count="224"', 'data-comments-xount="224"')
    read = rr.parse_thread(html, url="u")
    assert read["declared"] is None
    assert read["coverage_pct"] is None
    assert read["complete"] is False
    assert read["anomaly"] == "no_declared_count"


# ---------------------------------------------------------------------------
# CONSTRAINT 3 -- pacing, listing discovery, 429 is a refusal
# ---------------------------------------------------------------------------

def test_the_pacer_holds_its_interval_between_requests(rr):
    """REPLACES test_the_pacer_holds_ten_seconds_between_requests.

    The claim is unchanged: a second request inside the interval sleeps the
    remainder. Only the NUMBER moved, because 10s was measured against
    old.reddit.com and this module reads the Arctic mirror now. Asserting the
    behaviour against whatever MIN_INTERVAL_S is keeps the test true when the
    measurement changes, which a hardcoded 9.0 did not.
    """
    interval = rr.MIN_INTERVAL_S
    elapsed = interval / 10.0
    slept = []
    clock = {"t": 1000.0}
    pacer = rr.Pacer(min_interval_s=interval,
                     clock=lambda: clock["t"],
                     sleeper=lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    pacer.wait()          # first call is free
    assert slept == []
    clock["t"] += elapsed
    pacer.wait()
    assert slept and slept[0] == pytest.approx(interval - elapsed, abs=0.01)


def test_the_pacer_does_not_sleep_when_enough_time_already_passed(rr):
    slept = []
    clock = {"t": 0.0}
    pacer = rr.Pacer(min_interval_s=10, clock=lambda: clock["t"],
                     sleeper=lambda s: slept.append(s))
    pacer.wait()
    clock["t"] += 30
    pacer.wait()
    assert slept == []


def test_the_default_interval_belongs_to_the_host_this_module_reads(rr):
    """REPLACES test_the_default_interval_is_the_measured_one.

    That test asserted MIN_INTERVAL_S == 10, and 10 WAS the measured floor: 3s
    pacing 429'd 11 of 12 RSS requests on old.reddit.com and 10s ran 13 of 13
    clean. The measurement was real and it belonged to a host this module no
    longer reads.

    Keeping it cost 400 seconds per thread once the pacer started covering every
    paged request. The retired number stays as a named constant carrying its
    scar, so nobody mistakes the new one for that measurement, and the new one is
    honest about being a COURTESY on a free archive rather than a measured floor:
    Arctic's own limit has not been measured.
    """
    assert rr.RETIRED_REDDIT_MIN_INTERVAL_S == 10
    assert rr.MIN_INTERVAL_S < rr.RETIRED_REDDIT_MIN_INTERVAL_S
def test_a_429_is_recorded_as_a_refusal_never_as_zero_results(rr):
    def transport(url, headers, timeout):
        return 429, ""
    out = rr.read_thread("https://old.reddit.com/r/x/comments/abc/t/",
                         transport=transport, pacer=rr.NullPacer(),
                         now=dt.datetime(2026, 8, 31, 12, 0))
    assert out["refused"] is True
    assert out["http_status"] == 429
    assert out.get("comments") in (None, [])
    assert out["fetched"] is None, "a refusal must not report a fetched count of 0"
    assert out["coverage_pct"] is None


def test_a_403_is_also_a_refusal(rr):
    out = rr.read_thread("https://old.reddit.com/r/x/comments/abc/t/",
                         transport=lambda u, h, t: (403, ""),
                         pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert out["refused"] is True and out["fetched"] is None


def test_discovery_refuses_an_rss_url(rr):
    """RSS 429'd 11 of 12 at 3s pacing while listing HTML ran 6 of 6 clean at
    10s. The lane may not quietly fall back to the endpoint that throttles."""
    with pytest.raises(rr.DiscoveryRefused):
        rr.listing_url("programming", period="month", path_override="/r/programming/top/.rss")


def test_discovery_builds_an_arctic_listing_url(rr):
    """REPLACED test_discovery_builds_an_old_reddit_listing_url (2026-09-04).
    Rewritten rather than deleted: the claim it held (discovery has one url
    shape, and it is not RSS) is still the claim. Only the host changed."""
    url = rr.listing_url("programming", period="month")
    assert url.startswith("https://arctic-shift.photon-reddit.com/api/posts/search")
    assert "subreddit=programming" in url
    assert ".rss" not in url and "old.reddit.com" not in url


def test_thread_url_is_the_mirrors_comments_endpoint(rr):
    """REPLACED test_thread_url_asks_for_limit_500 (2026-09-04). `limit=500`
    bought as much of a thread as ONE old.reddit request could reach; it moved
    one thread from 201 to 215 of 214 declared and did not rescue large ones.
    The mirror pages, so completeness stopped being a query parameter."""
    url = rr.thread_url("/r/x/comments/abc/t/")
    assert url.startswith("https://arctic-shift.photon-reddit.com/api/comments/search")
    assert "link_id=abc" in url
    assert "old.reddit.com" not in url


def test_no_function_here_builds_an_old_reddit_url(rr):
    """The founder-directed rule, checked rather than asserted in prose: Arctic
    Shift is the only way this fleet scrapes Reddit."""
    # Parsed, not grepped. Comments and docstrings are exempt and MUST be: the
    # retired host is named in the scar notes that explain why it is retired,
    # and a line-level grep that forbids saying so is a check that deletes its
    # own reason. A first attempt did exactly that and failed on the comment
    # recording the founder directive it was written to enforce.
    import ast
    tree = ast.parse(pathlib.Path(rr.__file__).read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    live = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]
    for text in live:
        assert "old.reddit.com" not in text, text
    assert rr.BASE == "https://www.reddit.com", (
        "the only sanctioned reddit.com string is the display link a human clicks")


# ---------------------------------------------------------------------------
# Read-only, and an honest User-Agent
# ---------------------------------------------------------------------------

def test_the_user_agent_identifies_us_and_does_not_impersonate_a_browser(rr):
    ua = rr.USER_AGENT
    assert "kipi-research" in ua
    for spoof in ("Mozilla", "Chrome", "Safari", "AppleWebKit", "Gecko"):
        assert spoof not in ua, f"UA impersonates a browser via {spoof!r}"


# Leading tokens only. A write function is named for its ACTION and the action
# comes first: submit_post, send_dm, post_comment. Matching any token anywhere
# would flag `comment_ids` and `parse_comments`, which are readers, and a check
# that flags correct code is a check that gets deleted.
WRITE_PREFIXES = ("post", "submit", "send", "reply", "vote", "upvote", "downvote",
                  "message", "dm", "delete", "edit", "subscribe", "follow",
                  "create", "publish", "update", "remove", "save", "write")


def _public_defs():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not n.name.startswith("_")]


def test_no_write_verb_leads_a_public_function_name():
    bad = [n for n in _public_defs() if n.lower().split("_")[0] in WRITE_PREFIXES]
    assert not bad, f"write verbs lead these public names: {bad}"


def test_the_verb_check_can_actually_fire():
    """A denylist that never matches anything is indistinguishable from one that
    works. This proves the matcher fires on the shape it is meant to catch."""
    for name in ("submit_post", "send_dm", "post_comment", "delete_thread"):
        assert name.lower().split("_")[0] in WRITE_PREFIXES, name
    for name in ("comment_ids", "parse_comments", "read_thread", "declared_count"):
        assert name.lower().split("_")[0] not in WRITE_PREFIXES, name


def test_the_module_issues_no_http_write():
    """Founder-directed 2026-08-31: 'All I want with reddit is to be able to
    find and scrape posts and comments - not find dms etc. I'll post to reddit
    myself.' Read only, no exceptions. A POST body or a non-GET method would be
    a write path regardless of what the function is called."""
    code = _code_only(MODULE)
    for token in ('method="POST"', "method='POST'", '"POST"', "'POST'",
                  "urlopen(req, data", "data=data", ".post("):
        assert token not in code, f"module contains an HTTP write shape: {token}"


def test_the_module_never_reaches_the_json_endpoint(rr):
    """.json 403s with every UA tried, including Chrome. It is an
    endpoint-level block, so a fallback there is a guaranteed refusal."""
    code = _code_only(MODULE)
    assert ".json" not in code


# ---------------------------------------------------------------------------
# End to end, through the injected transport (no network in this suite)
# ---------------------------------------------------------------------------

def _mirror_double(calls, declared=224, rows=8):
    """A double shaped like the mirror: the posts/ids call answers with the
    declared count, the comments call answers with one short page."""
    def transport(url, headers, timeout):
        calls.append((url, headers))
        if "/api/posts/ids" in url:
            return 200, json.dumps({"data": [{"id": "1w3blbq", "num_comments": declared}]})
        return 200, json.dumps({"data": [{"id": "c%d" % i, "created_utc": 1788136000 + i}
                                         for i in range(rows)]})
    return transport


def test_read_thread_returns_a_full_artifact_from_a_200(rr):
    """REWRITTEN for the mirror (2026-09-04). The artifact contract is what this
    test was ever about, and it is unchanged: a 200 produces declared, fetched,
    coverage, and a fetched_at, and `assert_coverage_recorded` accepts it."""
    calls = []
    art = rr.read_thread("/r/programming/comments/1w3blbq/t/",
                         transport=_mirror_double(calls),
                         pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert art["refused"] is False
    assert art["declared"] == 224 and art["fetched"] == 8
    assert art["coverage_pct"] == 3.6
    assert art["complete"] is True, "a short page means the mirror had no more"
    assert art["truncated"] is False
    assert art["strategy"] == "paginate"
    assert art["fetched_at"] == "2026-08-31T12:00:00"
    assert all("arctic-shift" in url for url, _ in calls)
    assert calls[0][1]["User-Agent"] == rr.USER_AGENT
    rr.assert_coverage_recorded(art)


def test_a_thread_pages_until_the_mirror_runs_out(rr):
    """The capability the HTML transport never had. Verified live on
    r/programming 1w67dpg: declared 108, fetched 111 across two pages."""
    pages = []

    def transport(url, headers, timeout):
        if "/api/posts/ids" in url:
            return 200, json.dumps({"data": [{"id": "x", "num_comments": 150}]})
        pages.append(url)
        n = len(pages)
        if n == 1:
            rows = [{"id": "a%d" % i, "created_utc": 1788136000 + i} for i in range(100)]
        else:
            rows = [{"id": "b%d" % i, "created_utc": 1788137000 + i} for i in range(11)]
        return 200, json.dumps({"data": rows})

    art = rr.read_thread("/r/x/comments/x/t/", transport=transport,
                         pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert art["fetched"] == 111 and art["pages"] == 2
    assert art["complete"] is True and art["truncated"] is False
    assert "after=" in pages[1], "page two must advance the cursor"


def test_the_artifact_is_json_serialisable(rr):
    art = rr.read_thread("/r/x/comments/a/t/", transport=_mirror_double([]),
                         pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    json.dumps(art)


def test_the_capability_fragment_declares_this_suite():
    frag = (HERE.parent / "capability" / "expected_tests"
            / "q-system__.q-system__tests__test_reddit_read.py.json")
    assert frag.exists(), f"no capability fragment at {frag}"
    assert json.loads(frag.read_text())["path"].endswith("tests/test_reddit_read.py")


def test_the_fixture_records_its_own_provenance(real_html):
    """A fixture with no provenance is indistinguishable from one I invented."""
    assert "FIXTURE PROVENANCE" in real_html
    assert "old.reddit.com" in real_html
    assert "TRIMMED" in real_html


# RESTORED. A file-level landing off a 92-commit branch dropped this
# along with the fix it guards (PR 307 review). Its subject is unchanged.
def test_comments_bind_author_and_body_per_comment_not_by_position(rr):
    """PR #294 review, major: a real page opens with the post's own data-author
    and selftext <div class="md">, and a deleted comment carries no body, so a
    positional join shifted every attribution by one. Control: the second
    comment has no body and must read as None, not steal the third's."""
    html = (
        '<div class=" thing id-t3_post link " data-fullname="t3_post" data-author="op_poster">'
        '<div class="md"><p>the post text</p></div></div>'
        '<div class=" thing id-t1_aaa comment " data-fullname="t1_aaa" data-author="alice">'
        '<div class="md"><p>first</p></div></div>'
        '<div class=" thing id-t1_bbb comment " data-fullname="t1_bbb" data-author="[deleted]"></div>'
        '<div class=" thing id-t1_ccc comment " data-fullname="t1_ccc" data-author="carol">'
        '<div class="md"><p>third</p></div></div>'
    )
    got = rr.parse_comments(html)
    assert [c["id"] for c in got] == ["t1_aaa", "t1_bbb", "t1_ccc"]
    assert [c["author"] for c in got] == ["alice", "[deleted]", "carol"], got
    assert [c["body"] for c in got] == ["first", None, "third"], got



# RESTORED. A file-level landing off a 92-commit branch dropped this
# along with the fix it guards (PR 307 review). Its subject is unchanged.
def test_thread_url_refuses_anything_that_is_not_a_reddit_thread(rr):
    """PR #294 review, major: the MCP tool passed an absolute permalink straight
    to the transport, so any http(s) target could be fetched and its body
    returned through the tool.

    RESTORED after a file-level landing dropped it, and its assertions about the
    RETURN VALUE are rewritten because thread_url now returns a mirror URL. Every
    REFUSAL case below is the original's, unchanged: that is the half that was
    protecting anything.
    """
    import pytest
    ok = rr.thread_url("https://www.reddit.com/r/x/comments/abc/t/")
    assert ok.startswith("https://arctic-shift.photon-reddit.com/")
    assert "link_id=abc" in ok
    assert rr.thread_url("/r/x/comments/abc/t/").startswith(
        "https://arctic-shift.photon-reddit.com/")

    for bad in ("https://evil.example/r/x/comments/abc/",
                "http://old.reddit.com/r/x/comments/abc/",
                "https://old.reddit.com.evil.example/r/x/comments/abc/",
                "file:///etc/passwd",
                "r/x/comments/abc/",
                "https://www.reddit.com/r/x/"):
        with pytest.raises(rr.PermalinkRefused):
            rr.thread_url(bad)


def test_a_thread_that_declares_nothing_has_no_coverage(rr):
    """0.0 beside complete=True reads as "the read worked and returned none of
    the thread". There is no denominator, so there is no percentage (review).
    An EMPTY thread stays 100.0: it really was fully read."""
    assert rr.coverage_pct(7, 0) is None
    assert rr.coverage_pct(0, 0) == 100.0
    assert rr.coverage_pct(32, 34) == 94.1


def test_the_pacer_covers_every_request_a_paged_read_makes(rr):
    """`Pacer` promises at most one request per min_interval_s. One wait() before
    the read was that promise back when a thread was one request. `all_comments`
    pages now, so a multi-page thread got one wait and the rest unpaced."""
    import json
    waits = []

    class CountingPacer:
        def wait(self):
            waits.append(1)

    pages = {"n": 0}

    def transport(url, headers, timeout):
        if "/api/posts/ids" in url:
            return 200, json.dumps({"data": [{"id": "x", "num_comments": 300}]})
        pages["n"] += 1
        n = pages["n"]
        rows = [{"id": "p%d_%d" % (n, i), "created_utc": 1788136000 + n * 1000 + i}
                for i in range(100 if n < 3 else 5)]
        return 200, json.dumps({"data": rows})

    rr.read_thread("/r/x/comments/abc/t/", transport=transport,
                   pacer=CountingPacer())
    assert pages["n"] > 1, "the fixture must actually page"
    assert len(waits) == pages["n"] + 1, (len(waits), pages["n"])


def test_the_production_path_is_paced_not_only_the_injected_one(rr, monkeypatch):
    """THE ROUND-6 MAJOR, and the mode-nobody-tests defect in one function.

    Round 5 wrapped the injected getter and returned None when no transport was
    supplied, reasoning "the transport does its own fetching, so there is nothing
    to pace". Backwards: `transport` is None on the MCP and CLI paths, so the
    only arm that got paced was the one TESTS supply. Production made up to 41
    unpaced mirror requests per thread.
    """
    import json
    import urllib.request as u

    waits, opens = [], []

    class CountingPacer:
        def wait(self):
            waits.append(1)

    class Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        opens.append(url)
        if "/api/posts/ids" in url:
            return Resp({"data": [{"id": "x", "num_comments": 300}]})
        n = len([o for o in opens if "comments/search" in o])
        rows = [{"id": "p%d_%d" % (n, i), "created_utc": 1788136000 + n * 1000 + i}
                for i in range(100 if n < 3 else 4)]
        return Resp({"data": rows})

    monkeypatch.setattr(u, "urlopen", fake_urlopen)
    rr.read_thread("/r/x/comments/abc/t/", pacer=CountingPacer())

    assert len(opens) > 1, "the fixture must actually page"
    assert len(waits) == len(opens), (len(waits), len(opens))


def test_the_pace_is_not_the_retired_reddit_number(rr):
    """10s was MEASURED against old.reddit.com and was right for it. It is wrong
    for the mirror, and keeping it did real damage once the pacer covered every
    request instead of the first: one reddit_thread call became 41 requests and
    400 seconds of deliberate sleeping against a host that never asked (review).

    The retired number stays as a named constant carrying its scar, so nobody
    reads the new one as the old measurement.
    """
    assert rr.RETIRED_REDDIT_MIN_INTERVAL_S == 10
    assert rr.MIN_INTERVAL_S < 1, "the mirror is not old.reddit.com"
    assert 41 * rr.MIN_INTERVAL_S < 30, "41 paged requests must not cost minutes"


def test_a_paged_read_has_a_whole_read_deadline(rr, monkeypatch):
    """A per-request pace bounds the GAP between requests and says nothing about
    the total. 41 requests at any interval still needs a ceiling somebody chose.
    """
    import json
    import urllib.request as u

    assert rr.READ_DEADLINE_S > 0

    clock = {"t": 0.0}
    monkeypatch.setattr(rr._time, "monotonic", lambda: clock["t"])

    class Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def slow(req, timeout=None):
        clock["t"] += rr.READ_DEADLINE_S / 2.0     # each fetch eats half the budget
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/api/posts/ids" in url:
            return Resp({"data": [{"id": "x", "num_comments": 5000}]})
        n = int(clock["t"])
        return Resp({"data": [{"id": "p%d_%d" % (n, i),
                               "created_utc": 1788136000 + n * 1000 + i}
                              for i in range(100)]})

    monkeypatch.setattr(u, "urlopen", slow)

    class NoPacer:
        def wait(self):
            pass

    art = rr.read_thread("/r/x/comments/abc/t/", pacer=NoPacer())
    # NOT a refusal. Round 7 wrote this assertion as `refused is True`, and round
    # 8 showed that was wrong: every page came back 200 and the read simply ran
    # out of budget, so calling it a refusal blames a host that answered and
    # discards what it returned. The deadline still has to BITE, which is what
    # complete=False and deadline_hit assert.
    assert art["deadline_hit"] is True
    assert art["complete"] is False
    assert art["http_status"] == 200


def test_read_listing_passes_the_paced_opener_it_builds(rr, monkeypatch):
    """Round 6 fixed read_thread and left its sibling building a paced opener and
    never passing it, so the production LISTING path stayed unpaced (review)."""
    import json
    import urllib.request as u

    waits, opens = [], []

    class CountingPacer:
        def wait(self):
            waits.append(1)

    class Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        opens.append(req.full_url if hasattr(req, "full_url") else str(req))
        return Resp({"data": [{"id": "a", "title": "t", "subreddit": "x",
                               "permalink": "/r/x/comments/a/t/",
                               "num_comments": 3, "created_utc": 1788136000}]})

    monkeypatch.setattr(u, "urlopen", fake)
    rr.read_listing("x", pacer=CountingPacer())
    assert opens, "the fixture must actually fetch"
    assert len(waits) == len(opens), (len(waits), len(opens))


def test_a_deadline_is_not_a_refusal(rr, monkeypatch):
    """Every page already fetched came back 200; the read ran out of budget.
    Reporting that as "mirror refused" threw away real comments and blamed a
    host that answered every time (review, round 8)."""
    import json
    import urllib.request as u

    clock = {"t": 0.0}
    monkeypatch.setattr(rr._time, "monotonic", lambda: clock["t"])

    class Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def slow(req, timeout=None):
        clock["t"] += rr.READ_DEADLINE_S / 2.0
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/api/posts/ids" in url:
            return Resp({"data": [{"id": "x", "num_comments": 5000}]})
        n = int(clock["t"])
        return Resp({"data": [{"id": "p%d_%d" % (n, i),
                               "created_utc": 1788136000 + n * 1000 + i}
                              for i in range(100)]})

    monkeypatch.setattr(u, "urlopen", slow)

    class NoPacer:
        def wait(self):
            pass

    art = rr.read_thread("/r/x/comments/abc/t/", pacer=NoPacer())
    assert art["deadline_hit"] is True
    assert art["complete"] is False, "an over-budget read is incomplete"
    assert art["http_status"] == 200, "the mirror answered; do not blame it"
