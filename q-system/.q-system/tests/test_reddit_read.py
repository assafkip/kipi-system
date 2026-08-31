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

def test_the_pacer_holds_ten_seconds_between_requests(rr):
    slept = []
    clock = {"t": 1000.0}
    pacer = rr.Pacer(min_interval_s=rr.MIN_INTERVAL_S,
                     clock=lambda: clock["t"],
                     sleeper=lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    pacer.wait()          # first call is free
    assert slept == []
    clock["t"] += 1.0     # only 1s elapsed
    pacer.wait()
    assert slept and slept[0] == pytest.approx(9.0, abs=0.01)


def test_the_pacer_does_not_sleep_when_enough_time_already_passed(rr):
    slept = []
    clock = {"t": 0.0}
    pacer = rr.Pacer(min_interval_s=10, clock=lambda: clock["t"],
                     sleeper=lambda s: slept.append(s))
    pacer.wait()
    clock["t"] += 30
    pacer.wait()
    assert slept == []


def test_the_default_interval_is_the_measured_one(rr):
    """3s pacing 429'd 11 of 12 RSS requests. 10s ran 13 of 13 clean."""
    assert rr.MIN_INTERVAL_S == 10


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


def test_discovery_builds_an_old_reddit_listing_url(rr):
    url = rr.listing_url("programming", period="month")
    assert url.startswith("https://old.reddit.com/r/programming/top/")
    assert "t=month" in url
    assert ".rss" not in url


def test_thread_url_asks_for_limit_500(rr):
    """201 -> 215 of 214 declared. One query param, not an expansion API."""
    assert "limit=500" in rr.thread_url("/r/x/comments/abc/t/")


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

def test_read_thread_returns_a_full_artifact_from_a_200(rr, real_html):
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers))
        return 200, real_html

    art = rr.read_thread("/r/programming/comments/1w3blbq/t/", transport=transport,
                         pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert art["refused"] is False
    assert art["declared"] == 224 and art["fetched"] == 8
    assert art["truncated"] is True
    assert art["strategy"] == "single"
    assert art["fetched_at"] == "2026-08-31T12:00:00"
    assert "limit=500" in calls[0][0]
    assert calls[0][1]["User-Agent"] == rr.USER_AGENT
    rr.assert_coverage_recorded(art)


def test_the_artifact_is_json_serialisable(rr, real_html):
    art = rr.read_thread("/r/x/comments/a/t/", transport=lambda u, h, t: (200, real_html),
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
