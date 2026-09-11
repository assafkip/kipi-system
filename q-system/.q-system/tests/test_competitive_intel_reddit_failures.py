"""The failure semantics competitive_intel gained in PR 307, tested where CI runs.

WHY THIS FILE IS HERE AND NOT BESIDE THE MODULE. `plugins/kipi-core/kipi-mcp` is
excluded from `.verify-suites` because its own `tests/conftest.py` skips the whole
suite when the plugin's dependencies are absent (apify-client, feedparser, mcp,
pyyaml, tenacity). That exclusion is documented, measured and ticketed as
sp-97ce589b. It also meant this PR added 110 lines of new failure handling with
NOTHING running against it (PR 307 review, round 7, MAJOR).

The previous round answered that by pinning only the transport contract and
saying so. The reviewer was right that it was not enough: the per-room catch, the
total-outage raise and the failures sidecar are this PR's logic, not the
transport's, and they were guarded by nothing.

`competitive_intel` imports cleanly once those five modules exist as names, and
none of them is touched by the code under test here. So the deps are stubbed and
the real module is exercised. That is a smaller thing than installing the plugin
in CI, which is an environment change with its own blast radius and its own
ticket, and it is enough to catch a revert of the behaviour below.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "plugins" / "kipi-core" / "kipi-mcp" / "src"


@pytest.fixture(scope="module")
def ci():
    for name in ("yaml", "feedparser", "apify_client", "mcp", "tenacity"):
        if name in sys.modules:
            continue
        try:
            __import__(name)
        except ImportError:
            stub = types.ModuleType(name)
            stub.safe_load = lambda *a, **k: {}
            sys.modules[name] = stub
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from kipi_mcp import competitive_intel
    return competitive_intel


def _source(*subs):
    return {"name": "reddit-test", "subreddits": list(subs),
            "lookback_days": 30, "posts_per_sub": 2}


def _row(url):
    return {"data": [{"id": "x", "title": "t", "subreddit": "s",
                      "created_utc": 1788136000, "permalink": "/r/s/x/"}]}


def test_one_dead_room_does_not_lose_the_others(ci):
    """The raise used to escape into collect_ai_raw_records' `except Exception:
    continue`, so ONE dead subreddit lost the other three and the harvest still
    wrote a success artifact with zero Reddit rows."""
    def fetch(url):
        if "subreddit=dead" in url:
            raise OSError("down")
        return _row(url)

    records = ci._collect_reddit_rss(_source("good", "dead", "also_good"), 10, fetch)
    assert records, "a dead room must not take the live ones with it"
    assert len(records) == 2


def test_every_room_refusing_raises_rather_than_returning_empty(ci):
    """A total outage returning [] is indistinguishable from a quiet week. That
    is the same rule the transport holds, one layer up."""
    def dead(url):
        raise OSError("down")

    with pytest.raises(ci.RedditFetchFailed):
        ci._collect_reddit_rss(_source("a", "b"), 10, dead)


def test_a_lost_source_reaches_the_artifact_not_only_stderr(ci, tmp_path):
    """A stderr line at an unattended entry point is a line nobody reads: the run
    still exited 0 and still wrote a clean-looking harvest."""
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [
        {"type": "reddit_rss", "name": "reddit-dead", "subreddits": ["a"]},
        {"type": "reddit_rss", "name": "reddit-live", "subreddits": ["b"]},
    ]}))
    out = tmp_path / "harvest.json"

    def fetch(url):
        if "subreddit=a" in url:
            raise OSError("down")
        return _row(url)

    records = ci.collect_ai_raw_records(
        output_path=out, sources_config_path=config, fetch_json=fetch)
    assert records, "the live source must still be harvested"

    sidecar = out.with_suffix(out.suffix + ".failures.json")
    assert sidecar.exists(), "a lost source must travel with the output"
    failures = json.loads(sidecar.read_text())
    assert any(f["source"] == "reddit-dead" for f in failures), failures


def test_a_harvest_that_lost_everything_raises(ci, tmp_path):
    """NEGATIVE CONTROL for the sidecar: recording a failure is not enough when
    there is nothing else in the artifact to read."""
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [
        {"type": "reddit_rss", "name": "reddit-dead", "subreddits": ["a"]},
    ]}))

    def dead(url):
        raise OSError("down")

    with pytest.raises(ci.RedditFetchFailed):
        ci.collect_ai_raw_records(output_path=tmp_path / "h.json",
                                  sources_config_path=config, fetch_json=dead)


def test_the_delegate_still_raises_rather_than_returning_empty(ci):
    """The one rule the whole module change exists for. `_reddit_archive_posts`
    returned [] when both mirrors refused; four of the five copies of that
    transport across the corpus did."""
    with pytest.raises(ci.RedditFetchFailed):
        ci._reddit_archive_posts("taxpros", "2026-08-01", 5,
                                 lambda url: (_ for _ in ()).throw(OSError("down")))

    # a quiet subreddit is still empty, and that distinction is the point
    rows = ci._reddit_archive_posts("taxpros", "2026-08-01", 5,
                                    lambda url: {"data": []})
    assert rows == []
