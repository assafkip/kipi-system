"""The audit has to FAIL on a reintroduced violation, or its zero means nothing.

A checker that returns clean is indistinguishable from a checker that cannot see
anything. Every case below is a NEGATIVE control first: a file that must be
flagged, then the shape that must not be.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "reddit-transport-audit.py"


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("reddit_transport_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["reddit_transport_audit"] = module
    spec.loader.exec_module(module)
    return module


def _write(tmp_path, body, name="collector.py"):
    path = tmp_path / name
    path.write_text(body)
    return path


# --- NEGATIVE CONTROLS: these must be caught ------------------------------

@pytest.mark.parametrize("body,why", [
    ('import urllib.request\n'
     'def go(sub):\n'
     '    return urllib.request.urlopen("https://www.reddit.com/r/%s/new.json" % sub)\n',
     "the .json endpoint"),
    ('BASE = "https://old.reddit.com"\n'
     'def go(p):\n'
     '    return BASE + p\n',
     "the retired HTML host"),
    ('TOKEN_URL = "https://oauth.reddit.com/api/v1/me"\n',
     "the official API"),
    ('ACTOR = "trudax/reddit-scraper-lite"\n',
     "the retired Apify actor"),
    ('def feed(sub):\n'
     '    src = "https://www.reddit.com/r/%s/hot/.rss" % sub\n'
     '    return src\n',
     "the RSS endpoint"),
])
def test_a_reintroduced_transport_is_caught(audit, tmp_path, body, why):
    found = audit.violations_in(_write(tmp_path, body))
    assert found, "audit did not catch %s -- its clean runs would mean nothing" % why


def test_the_whole_walk_catches_it_too(audit, tmp_path):
    """violations_in is the unit; `walk` is what actually runs. A skip rule that
    excluded the file would make the unit pass and the tool blind."""
    _write(tmp_path, 'U = "https://www.reddit.com/r/x/new.json"\n')
    assert audit.walk([tmp_path])


# --- POSITIVE CONTROLS: these must NOT be caught --------------------------

def test_the_sanctioned_transport_is_clean(audit, tmp_path):
    body = ('ARCTIC = "https://arctic-shift.photon-reddit.com"\n'
            'PULLPUSH = "https://api.pullpush.io"\n'
            'def posts(sub):\n'
            '    return ARCTIC + "/api/posts/search?subreddit=" + sub\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_display_link_is_clean(audit, tmp_path):
    body = ('def build(permalink):\n'
            '    url = "https://www.reddit.com" + permalink\n'
            '    return url\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_host_classifier_is_clean(audit, tmp_path):
    """Naming a domain to decide how a URL is TREATED is not fetching it."""
    body = ('def kind(url):\n'
            '    if "reddit.com" in url.lower():\n'
            '        return "reddit"\n'
            '    return "other"\n'
            'NOISE_HOSTS = {"reddit.com", "medium.com"}\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_scar_comment_naming_the_retired_host_is_clean(audit, tmp_path):
    """The retired hosts are named in the comments explaining WHY they are
    retired. A checker that forbids the file from recording its own reason is a
    checker that deletes the reason. This failed on its first version."""
    body = ('# We no longer read old.reddit.com: it is an HTML scrape and it\n'
            '# throttles. See plugins/kipi-core/reddit_arctic.\n'
            'def go():\n'
            '    """Once read https://www.reddit.com/r/x/new.json. Not any more."""\n'
            '    return None\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_an_inline_self_test_is_clean(audit, tmp_path):
    body = ('def check(label, got, want):\n'
            '    assert got == want, label\n'
            'def run():\n'
            '    check("a reddit thread has no publisher",\n'
            '          identity_of("https://www.reddit.com/r/x/comments/1/y/"), None)\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_file_that_never_mentions_reddit_is_clean(audit, tmp_path):
    assert audit.violations_in(_write(tmp_path, 'X = "https://example.com"\n')) == []


# --- the exceptions table stays honest ------------------------------------

def test_every_exception_carries_a_reason(audit):
    """A per-file allowlist rots the moment nobody can say why a row is on it."""
    assert audit.EXCEPTIONS
    for suffix, reason in audit.EXCEPTIONS.items():
        assert suffix.endswith(".py"), suffix
        assert len(reason) > 40, "exception %s needs a real reason, got %r" % (suffix, reason)


def test_a_nested_linked_worktree_is_skipped_under_a_parent_root(audit, tmp_path):
    """The regression that got past the first fix.

    Passing each repo as its own root exercised the worktree check on the root.
    The CLI default passes `~/projects` ONCE, so every checkout under it is just a
    subdirectory and the check never reached it. consulting-landing, a worktree on
    a two-week-old branch, came back a second time that way: green in the test,
    red on the command line. A guard has to run where the thing it guards against
    actually appears.
    """
    wt = tmp_path / "some-worktree"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /elsewhere/.git/worktrees/some-worktree\n")
    (wt / "old.py").write_text('U = "https://www.reddit.com/r/x/new.json"\n')
    assert audit.walk([wt]) == [], "a worktree passed as the root must be skipped"
    assert audit.walk([tmp_path]) == [], "and skipped under a parent root too"

    # NEGATIVE CONTROL: the same file in a plain directory is still caught, so the
    # skip is doing its job rather than disabling the walk.
    plain = tmp_path / "not-a-worktree"
    plain.mkdir()
    (plain / "old.py").write_text('U = "https://www.reddit.com/r/x/new.json"\n')
    assert audit.walk([tmp_path]), "the skip must not swallow a real finding"


def test_the_fleet_is_clean_right_now(audit):
    """The claim the whole conversion was for. Scoped to the repos that exist on
    this machine, so it is a real check here and a skip elsewhere rather than a
    green that proves nothing."""
    root = Path.home() / "projects"
    if not root.is_dir():
        pytest.skip("no fleet checkout on this machine")
    # ONE root, the way the CLI is actually invoked. Passing each repo separately
    # is a different code path and it is the one that hid a real finding.
    found = audit.walk([root])
    assert found == [], "non-Arctic Reddit reads: %s" % found[:5]
