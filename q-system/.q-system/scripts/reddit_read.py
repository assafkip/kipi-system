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

Since any UA works, there is no reason to wear a costume. `user_agent()` names the
client, and adds an instance-supplied contact URL when one is configured. Impersonating Chrome would be a choice to look
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
import os
import re
import sys
import time
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Honest identification. Any UA that is not empty and is not curl's default gets
# a 200, so there is nothing to gain by impersonating a browser and the tests
# forbid the strings that would.
#
# NO COMPANY DOMAIN IN THE SKELETON. This file ships to every instance in the
# fleet, so a hardcoded contact URL would put ONE founder's domain into the
# Reddit header of all of them. The skeleton default is the bare form, and that
# is measured working: `kipi-research/1.0` returned 200 on 2026-08-31.
#
# An instance supplies its own contact URL, env first then a file, never
# raising, which is the resolution order slack_founder.py already uses for
# credentials. The fallback is the bare identifier and NEVER an empty string:
# empty and curl-shaped are precisely the two forms measured returning 403, so
# degrading to either would turn this lane into a 403 generator.
UA_BASE = "kipi-research/1.0"
STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
CONTACT_FILE = Path(os.environ.get("KIPI_RESEARCH_CONTACT_FILE",
                                   STATE_DIR / "reddit-contact-url"))


def _read_contact(path=None) -> str:
    """An instance's contact URL, or "". Never raises: a missing optional file
    is a normal state, not a crash inside a scheduled job."""
    env = os.environ.get("KIPI_RESEARCH_CONTACT_URL", "").strip()
    if env:
        return env
    try:
        return (path or CONTACT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def user_agent(contact=None) -> str:
    """The UA this lane sends. Never empty, never curl-shaped."""
    contact = _read_contact() if contact is None else contact
    contact = (contact or "").strip()
    return f"{UA_BASE} (+{contact}; research)" if contact else UA_BASE

BASE = "https://old.reddit.com"

# 3s pacing 429'd 11 of 12 RSS requests. 10s pacing ran 13 of 13 clean across
# listing pages and thread fetches. This is the measured floor, not a guess.
MIN_INTERVAL_S = 10

# Derived from the population above, not picked:
#   224 declared measured 97.3% in one request
#   613 declared measured 79.1%
# So one request is complete enough at or below 250, and demonstrably is not at
# or above 600. NOTHING WAS MEASURED BETWEEN 224 AND 613, and `choose_strategy`
# says so rather than guessing which side that band falls on.
SINGLE_REQUEST_MAX = 250
LARGE_THREAD_MIN = 600

DEFAULT_TIMEOUT_S = 45

# PAGE CLASSIFICATION. A soft block answers HTTP 200 with a full-size page that
# is not the page you asked for, so the status code cannot be the check.
#
# Measured 2026-08-31: `reddit_read.py listing sysadmin --period month` returned
# http_status 200, refused False, thread_count 0. The same command returned three
# threads that morning. The page was a 321KB "Welcome to Reddit" interstitial. A
# soft block and a genuinely quiet subreddit produced identical output, and the
# honest-looking one was the wrong one.
#
# THE CLASSIFIER DETECTS THE INTERSTITIAL POSITIVELY, rather than requiring a
# listing marker to be present. That direction matters: a real but EMPTY listing
# has no thread rows either, so keying on "listing markers present" would refuse
# the one case that is legitimately zero. Refusing only on a positive
# interstitial match keeps `thread_count: 0` reachable and truthful.
#
# Both arms are verified against captured bytes, not just the failing one:
#   present in tests/fixtures/reddit_soft_block_interstitial.html (real block)
#   absent  in tests/fixtures/old_reddit_thread_trimmed.html      (real old.reddit)
# The interstitial is the NEW reddit shell, which is why its markers can never
# appear on a server-rendered old.reddit page.
INTERSTITIAL_MARKERS = ("shreddit-skip-link", 'id="tailwind"')
OLD_REDDIT_MARKERS = ("data-subreddit=", "data-fullname=")


def classify_page(html: str) -> str:
    """old_reddit / interstitial / unrecognised.

    `unrecognised` is a real third answer and is NOT folded into either
    neighbour: calling it old_reddit would let a future block shape report zero
    threads as fact, and calling it a block would refuse pages nobody has seen
    yet.
    """
    text = html or ""
    if any(m in text for m in INTERSTITIAL_MARKERS):
        return "interstitial"
    if any(m in text for m in OLD_REDDIT_MARKERS):
        return "old_reddit"
    return "unrecognised"


class ListingNotVerified(Exception):
    """A listing artifact reporting a count without saying what page it parsed."""


def assert_listing_verified(artifact: dict) -> None:
    """The same gatekeeper assert_coverage_recorded applies to threads, one call
    out. read_thread refuses to hand back comments without declared/fetched/
    coverage; read_listing had no equivalent contract at all, so it could report
    thread_count with nothing saying whether the page was a listing."""
    if artifact.get("thread_count") is None:
        return
    missing = [k for k in ("page_class", "refused") if k not in artifact]
    if missing:
        raise ListingNotVerified(
            f"listing artifact reports a count but is missing {missing}. A count "
            "with no page classification cannot tell a soft block from a quiet "
            "subreddit, and the soft block is the one that looks healthy.")


_DECLARED_RE = re.compile(r'data-comments-count="(\d+)"')
_COMMENT_RE = re.compile(r'data-fullname="(t1_[a-z0-9]+)"')
_AUTHOR_RE = re.compile(r'data-author="([^"]*)"')
_MD_RE = re.compile(r'<div class="md">(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_THING_RE = re.compile(r'data-fullname="(t[13]_[a-z0-9]+)"')


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

    PARSED PER BLOCK, NEVER BY ZIPPING PARALLEL LISTS. The first version
    collected ids, authors and bodies as three independent findall() results and
    joined them by index. A real thread page opens with the SUBMISSION row, a
    `t3` thing carrying its own data-author and its own .md body, before any
    comment. That one extra author and body shifted every comment onto the
    previous one's attribution: the reviewer's reproducer returned the OP's name
    and the OP's text under the first comment's id.

    The committed fixture trims the submission region, so the suite could not
    see it. That is the fixture-from-a-producer lesson landing on me: a trimmed
    slice is not the production shape, and the part trimmed away was the part
    that broke it.

    Each thing owns the region from its own data-fullname to the next one, so
    the submission's author and body stay with the submission, and a comment
    missing either field yields None instead of stealing its neighbour's.
    """
    text = html or ""
    marks = list(_THING_RE.finditer(text))
    out = []
    for i, mark in enumerate(marks):
        cid = mark.group(1)
        if not cid.startswith("t1_"):
            continue  # the submission row, or anything else that is not a comment
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[mark.end():end]
        author = _AUTHOR_RE.search(block)
        body = _MD_RE.search(block)
        out.append({
            "id": cid,
            "author": author.group(1) if author else None,
            "body": _text(body.group(1)) if body else None,
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
        "user_agent": user_agent(),
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

# WHAT read_thread WILL ACCEPT, ENFORCED HERE AT THE BOUNDARY.
#
# The first version did `permalink if permalink.startswith("http") else BASE +
# permalink`, so an absolute URL to any host was fetched and the artifact came
# back stamped as a successful Reddit read. That is request forgery that also
# LIES about what it read: a consumer sees a reddit artifact and has no way to
# know the bytes came from localhost.
#
# Only two shapes are legitimate: a relative permalink, or an absolute URL on a
# reddit host we already rewrite to. Everything else is a refusal with a reason,
# never a fetch.
ALLOWED_THREAD_HOSTS = ("old.reddit.com", "www.reddit.com", "reddit.com",
                        "np.reddit.com")
_PERMALINK_RE = re.compile(r"^/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(?:/[^/?#]*)?/?$")
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class UrlRefused(Exception):
    """A URL this lane will not fetch. Never caught internally."""


def thread_url(permalink: str) -> str:
    """The fetch URL for one thread, or a refusal.

    ?limit=500 moved one thread from 201 to 215 of 214 declared. It is one query
    param and it is worth taking; it does not rescue large threads.
    """
    raw = (permalink or "").strip()
    if "://" in raw or raw.startswith("//"):
        candidate = raw if "://" in raw else "https:" + raw
        parts = urlparse(candidate)
        if parts.scheme.lower() != "https":
            raise UrlRefused(
                f"refusing {raw[:100]!r}: only https is accepted here, and a "
                "scheme like file: would be read and reported as a Reddit thread.")
        host = (parts.hostname or "").lower()
        if host not in ALLOWED_THREAD_HOSTS:
            raise UrlRefused(
                f"refusing host {host!r}: read_thread fetches Reddit and stamps "
                f"its artifact as a Reddit read. Allowed: {ALLOWED_THREAD_HOSTS}.")
        path = parts.path
    else:
        if not raw.startswith("/") or raw.startswith("//"):
            raise UrlRefused(
                f"refusing {raw[:100]!r}: a permalink must start with / (e.g. "
                "/r/programming/comments/abc123/slug/).")
        path = raw

    if not _PERMALINK_RE.match(path):
        raise UrlRefused(
            f"refusing path {path[:100]!r}: not a thread permalink. Expected "
            "/r/<subreddit>/comments/<id>[/<slug>].")
    return f"{BASE}{path}?limit=500"


def listing_url(subreddit: str, period: str = "month", path_override=None) -> str:
    """Discovery goes through listing HTML.

    RSS is refused rather than merely not-preferred: at 3s pacing it returned
    429 on 11 of 12 requests while listing HTML returned 200 on 6 of 6 at 10s.
    A silent fallback to the throttling endpoint is how a lane starts reporting
    zeros that are really refusals.
    """
    if path_override is None and not _SUBREDDIT_RE.match((subreddit or "").strip()):
        raise DiscoveryRefused(
            f"refusing subreddit {subreddit!r}: names are letters, digits and "
            "underscores. Anything else is a path or a host smuggled into a URL.")
    path = path_override or f"/r/{subreddit}/top/"
    if ".rss" in path or path.endswith(".xml"):
        raise DiscoveryRefused(
            f"refusing {path}: discovery uses listing HTML, not RSS. Measured "
            "2026-08-31, RSS 429'd 11 of 12 requests at 3s pacing while listing "
            "HTML ran clean.")
    return f"{BASE}{path}?t={period}"


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
        "user_agent": user_agent(),
    }


def read_thread(permalink: str, transport=None, pacer=None, now=None,
                timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """One thread, one artifact. Read only."""
    transport = transport or _default_transport
    # A REAL PACER IS THE FREE PATH. It used to default to NullPacer, so anything
    # importing this function instead of shelling the CLI got zero pacing
    # silently, while the whole reliability story of this lane is a 10s interval.
    # A safety default that only applies when you go through the CLI is not a
    # default. Tests inject NullPacer explicitly; callers get pacing for free.
    pacer = Pacer() if pacer is None else pacer
    now = now or dt.datetime.now().astimezone()
    url = thread_url(permalink)
    pacer.wait()
    status, body = transport(url, {"User-Agent": user_agent()}, timeout)
    if status != 200:
        return _refusal(url, status, now)
    artifact = build_artifact(parse_thread(body, url=url), now)
    assert_coverage_recorded(artifact)
    return artifact


def read_listing(subreddit: str, period: str = "month", transport=None,
                 pacer=None, now=None, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Candidate threads with the size Reddit declares for each, so a caller can
    pick by size before spending a request per thread."""
    transport = transport or _default_transport
    pacer = Pacer() if pacer is None else pacer  # see read_thread: safe path is free
    now = now or dt.datetime.now().astimezone()
    url = listing_url(subreddit, period)
    pacer.wait()
    status, body = transport(url, {"User-Agent": user_agent()}, timeout)
    if status != 200:
        out = _refusal(url, status, now)
        out["threads"] = None
        out["thread_count"] = None
        out["page_class"] = None
        out["reason"] = f"HTTP {status}"
        return out

    page_class = classify_page(body)
    if page_class == "interstitial":
        # A soft block belongs in the same category as the 429 above, with its
        # own reason so a caller can tell them apart. Reporting it as zero
        # threads is how a rate-limited sweep reports every room as quiet.
        out = _refusal(url, status, now)
        out["threads"] = None
        out["thread_count"] = None
        out["page_class"] = page_class
        out["reason"] = ("soft block: Reddit answered HTTP 200 with its logged-out "
                         "interstitial instead of the listing. This is a refusal, "
                         "not an empty subreddit.")
        return out

    found = {}
    for pattern in (r'data-comments-count="(\d+)"[^>]*data-permalink="([^"]+)"',
                    r'data-permalink="([^"]+)"[^>]*data-comments-count="(\d+)"'):
        for match in re.finditer(pattern, body):
            first, second = match.group(1), match.group(2)
            count, permalink = (int(first), second) if first.isdigit() else (int(second), first)
            found[permalink] = count
    threads = [{"permalink": p, "declared": c, "strategy": choose_strategy(c)}
               for p, c in sorted(found.items(), key=lambda kv: kv[1])]
    artifact = {
        "url": url, "refused": False, "http_status": status,
        "page_class": page_class,
        "fetched_at": now.isoformat(timespec="seconds"),
        "subreddit": subreddit, "period": period,
        "threads": threads, "thread_count": len(threads),
        "user_agent": user_agent(), "comments": None,
    }
    assert_listing_verified(artifact)
    return artifact


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
