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
INTERSTITIAL = HERE / "fixtures" / "reddit_soft_block_interstitial.html"


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
    ua = rr.user_agent()
    assert "kipi-research" in ua
    for spoof in ("Mozilla", "Chrome", "Safari", "AppleWebKit", "Gecko"):
        assert spoof not in ua, f"UA impersonates a browser via {spoof!r}"


def test_the_skeleton_default_carries_no_company_domain(rr):
    """This file ships to every instance in the fleet. A hardcoded contact URL
    would put ONE founder's domain in all of their Reddit headers. Caught by
    the skeleton sweep in CI (validate, 2026-08-31); pinned here so it fails in
    the suite first."""
    default = rr.user_agent(contact="")
    assert default == "kipi-research/1.0"
    # The property is that the DEFAULT embeds no URL. A source-wide domain grep
    # was the first version of this and it was wrong: the module legitimately
    # contains old.reddit.com, which is the surface being read, not a contact.
    assert "://" not in default and "+" not in default
    assert "://" not in rr.UA_BASE and "." not in rr.UA_BASE.split("/")[0]


def test_the_ua_is_never_empty_and_never_curl_shaped(rr):
    """The two forms measured returning 403 are the empty UA and curl's own.
    Degrading to either turns this lane into a 403 generator, so the fallback
    is the bare identifier."""
    for contact in ("", None, "   "):
        ua = rr.user_agent(contact=contact) if contact is not None else rr.user_agent(contact="")
        assert ua.strip(), "empty UA is a measured 403"
        assert "curl" not in ua.lower(), "curl-shaped UA is a measured 403"


def test_an_instance_contact_url_is_picked_up(rr, monkeypatch):
    monkeypatch.setenv("KIPI_RESEARCH_CONTACT_URL", "https://example.com")
    assert rr.user_agent() == "kipi-research/1.0 (+https://example.com; research)"


def test_env_beats_the_file_and_a_missing_file_never_raises(rr, tmp_path, monkeypatch):
    """slack_founder.py's resolution order: env first, then a file, never
    raising, because a missing optional file is a normal state and not a crash
    inside a scheduled job."""
    monkeypatch.delenv("KIPI_RESEARCH_CONTACT_URL", raising=False)
    missing = tmp_path / "nope"
    assert rr._read_contact(missing) == ""
    present = tmp_path / "contact"
    present.write_text("https://file.example\n")
    assert rr._read_contact(present) == "https://file.example"
    monkeypatch.setenv("KIPI_RESEARCH_CONTACT_URL", "https://env.example")
    assert rr._read_contact(present) == "https://env.example"


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
    assert calls[0][1]["User-Agent"] == rr.user_agent()
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


# ---------------------------------------------------------------------------
# SOFT BLOCK. HTTP 200, full-size page, wrong page.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def interstitial_html():
    """Real bytes from an actual soft-blocked response, not a mock."""
    return INTERSTITIAL.read_text()


def test_classify_page_recognises_a_real_soft_block(rr, interstitial_html):
    assert rr.classify_page(interstitial_html) == "interstitial"


def test_classify_page_recognises_real_old_reddit(rr, real_html):
    """The other arm, and it is the one that is easy to skip. A classifier
    verified only against the failing case can be a function that returns
    "interstitial" for everything."""
    assert rr.classify_page(real_html) == "old_reddit"


def test_an_unknown_page_is_its_own_answer(rr):
    """Not folded into either neighbour: calling it old_reddit lets a future
    block shape report zero as fact, calling it a block refuses pages nobody
    has seen yet."""
    assert rr.classify_page("<html><body>hello</body></html>") == "unrecognised"


def test_a_soft_block_is_a_REFUSAL_not_an_empty_subreddit(rr, interstitial_html):
    """Measured 2026-08-31: `listing sysadmin --period month` returned
    http_status 200, refused False, thread_count 0, having parsed a "Welcome to
    Reddit" page. The same call returned three threads that morning."""
    out = rr.read_listing("sysadmin", transport=lambda u, h, t: (200, interstitial_html),
                          pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert out["refused"] is True
    assert out["thread_count"] is None, "a refusal must not report a count of 0"
    assert out["page_class"] == "interstitial"
    assert "soft block" in out["reason"]


def test_a_soft_block_reads_differently_from_a_429(rr, interstitial_html):
    """Same category, distinct reason, so a caller can tell them apart."""
    soft = rr.read_listing("x", transport=lambda u, h, t: (200, interstitial_html),
                           pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    rate = rr.read_listing("x", transport=lambda u, h, t: (429, ""),
                           pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert soft["refused"] and rate["refused"]
    assert soft["reason"] != rate["reason"]
    assert "429" in rate["reason"]
    assert soft["http_status"] == 200 and rate["http_status"] == 429


def test_a_genuinely_empty_listing_still_reports_zero(rr, real_html):
    """THE NEGATIVE ARM. Without it the classifier becomes a thing that can only
    ever report failure. Derived from the real old.reddit fixture by removing
    the thread-row attributes, which is exactly the shape of a listing whose
    period holds no posts: real chrome, no rows."""
    empty = real_html.replace("data-permalink=", "data-x-permalink=") \
                     .replace("data-comments-count=", "data-x-comments-count=")
    out = rr.read_listing("quiet", transport=lambda u, h, t: (200, empty),
                          pacer=rr.NullPacer(), now=dt.datetime(2026, 8, 31, 12, 0))
    assert out["refused"] is False
    assert out["thread_count"] == 0
    assert out["page_class"] == "old_reddit"


def test_assert_listing_verified_refuses_a_count_with_no_page_class(rr):
    with pytest.raises(rr.ListingNotVerified):
        rr.assert_listing_verified({"thread_count": 3})


# ---------------------------------------------------------------------------
# The safe path is the FREE path
# ---------------------------------------------------------------------------

class _RecordingPacer:
    made = 0
    def __init__(self, *a, **k):
        type(self).made += 1
        self.waits = 0
    def wait(self):
        self.waits += 1


@pytest.mark.parametrize("call", ["thread", "listing"])
def test_omitting_the_pacer_gives_you_a_real_one(rr, monkeypatch, real_html, call):
    """It used to default to NullPacer, so anything importing these functions
    rather than shelling the CLI got zero pacing silently, while the entire
    reliability story of this lane is a 10 second interval. A safety default
    that only applies through the CLI is not a default."""
    _RecordingPacer.made = 0
    monkeypatch.setattr(rr, "Pacer", _RecordingPacer)
    fn = rr.read_thread if call == "thread" else rr.read_listing
    arg = "/r/x/comments/a/t/" if call == "thread" else "x"
    fn(arg, transport=lambda u, h, t: (200, real_html),
       now=dt.datetime(2026, 8, 31, 12, 0))
    assert _RecordingPacer.made == 1, "no pacer was constructed by default"


def test_the_null_pacer_must_be_asked_for_explicitly(rr):
    """NullPacer still exists for tests; it is just no longer what you get by
    forgetting."""
    assert rr.NullPacer().wait() is None


# ---------------------------------------------------------------------------
# Codex review of PR #293: the submission row shifted every attribution.
# ---------------------------------------------------------------------------

SUBMISSION_ROW = ('<div data-fullname="t3_post" data-author="OP_ACCOUNT">'
                  '<div class="md"><p>SUBMISSION BODY</p></div></div>')


def test_the_submission_row_does_not_shift_comment_attribution(rr, real_html):
    """The reviewer's reproducer. Real pages open with a `t3` submission
    carrying its own data-author and .md body; the old parser collected ids,
    authors and bodies as three independent lists and joined them by index, so
    that one extra pair pushed every comment onto the previous one's author and
    text. It returned the OP's name and words under the first comment's id.

    The committed fixture trims the submission region, which is exactly why the
    suite stayed green. The attribute names here are copied from the fixture's
    own markup rather than invented."""
    page = SUBMISSION_ROW + real_html
    comments = rr.parse_comments(page)
    assert comments, "no comments parsed"
    assert all(c["id"].startswith("t1_") for c in comments), "the submission was parsed as a comment"
    assert all(c["author"] != "OP_ACCOUNT" for c in comments), "OP was attributed a comment"
    assert all(c["body"] != "SUBMISSION BODY" for c in comments), "OP's text leaked into a comment"


def test_a_comment_missing_an_author_yields_none_not_its_neighbours(rr):
    """The failure mode index-joining hides: a gap silently borrows from the
    next comment instead of admitting it is missing."""
    page = ('<div data-fullname="t1_a"><div class="md"><p>first</p></div></div>'
            '<div data-fullname="t1_b" data-author="second_person">'
            '<div class="md"><p>second</p></div></div>')
    a, b = rr.parse_comments(page)
    assert a["id"] == "t1_a" and a["author"] is None and a["body"] == "first"
    assert b["id"] == "t1_b" and b["author"] == "second_person" and b["body"] == "second"


def test_comment_count_is_unchanged_by_a_submission_row(rr, real_html):
    """Coverage is computed off this list, so a parser that swallowed or
    invented a row would quietly move the coverage number too."""
    assert len(rr.parse_comments(SUBMISSION_ROW + real_html)) == len(rr.parse_comments(real_html))


# ---------------------------------------------------------------------------
# Codex round 2, MAJOR: absolute non-Reddit URLs were fetched and reported as
# successful Reddit reads.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,why", [
    ("http://localhost:8080/r/x/comments/a/b/", "loopback"),
    ("http://127.0.0.1/r/x/comments/a/b/", "loopback literal"),
    ("file:///etc/passwd", "file scheme"),
    ("https://evil.example/r/x/comments/a/b/", "another host"),
    ("//evil.example/r/x/comments/a/b/", "protocol-relative"),
    ("/etc/passwd", "not a permalink"),
    ("/r/x/../../admin", "traversal"),
    ("r/x/comments/a/b/", "no leading slash"),
])
def test_thread_url_refuses_anything_that_is_not_reddit(rr, url, why):
    """It fetched these and stamped the artifact as a Reddit read, so a consumer
    saw a reddit result with no way to know the bytes came from localhost. That
    is request forgery that also lies about its source."""
    with pytest.raises(rr.UrlRefused):
        rr.thread_url(url)


@pytest.mark.parametrize("url", [
    "/r/programming/comments/1w3blbq/please_i_beg_you/",
    "/r/programming/comments/1w3blbq",
    "https://old.reddit.com/r/programming/comments/1w3blbq/x/",
    "https://www.reddit.com/r/programming/comments/1w3blbq/x/",
])
def test_thread_url_still_accepts_legitimate_reddit_urls(rr, url):
    """THE NEGATIVE ARM. Without it a guard that refuses everything ships and
    nobody notices until the tool is useless."""
    built = rr.thread_url(url)
    assert built.startswith("https://old.reddit.com/r/programming/comments/1w3blbq")
    assert "limit=500" in built


def test_read_thread_refuses_before_it_fetches(rr):
    """The guard is at the boundary, so a bad URL never reaches the transport."""
    calls = []
    with pytest.raises(rr.UrlRefused):
        rr.read_thread("file:///etc/passwd",
                       transport=lambda u, h, t: (calls.append(u), (200, "x"))[1],
                       pacer=rr.NullPacer())
    assert calls == [], "a refused URL was still fetched"


def test_listing_url_refuses_a_smuggled_subreddit(rr):
    for bad in ("x/../../admin", "evil.example/x", "x?a=b", "../etc"):
        with pytest.raises(rr.DiscoveryRefused):
            rr.listing_url(bad)


def test_listing_url_still_accepts_a_real_subreddit(rr):
    assert rr.listing_url("sysadmin", period="month").startswith(
        "https://old.reddit.com/r/sysadmin/top/")
