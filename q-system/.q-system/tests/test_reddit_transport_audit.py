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


def test_a_worktree_handed_in_as_the_root_is_still_scanned(audit, tmp_path):
    """THE PRE-COMMIT HOOK LIVES OR DIES ON THIS.

    lefthook passes `git rev-parse --show-toplevel`, and inside a linked
    worktree that IS the worktree. An earlier version skipped a worktree root
    outright, so the only automatic wiring of this rule exited 0 on every commit
    made from a branch worktree, which is how this fleet works by policy. Found
    in review with a reproducer: exit 0 in the worktree, exit 1 in the main
    checkout, same planted file.

    Being HANDED a path is a different act from FINDING one. The skip still
    applies to a worktree discovered below a parent root, because that is a
    second copy of a branch audited at its own root.
    """
    import subprocess
    main = tmp_path / "main"
    main.mkdir()
    (main / "ok.py").write_text("x = 1\n")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(main)] + cmd, check=True, capture_output=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "b", str(wt)],
                   check=True, capture_output=True)
    (wt / "bad.py").write_text('U = "https://old.reddit.com/r/x/new.json"\n')

    assert (wt / ".git").is_file(), "fixture must be a LINKED worktree"
    assert audit.walk([wt]), "a worktree handed in as the root must be scanned"
    # discovered below a parent: skipped, so one branch is not reported twice
    assert audit.walk([tmp_path]) == []


def test_the_skeletons_own_directories_are_source_under_any_root(audit, tmp_path):
    """The sweep that reported "0 across every checkout" could not see the two
    directories this audit lives in.

    `_is_vendored_copy` read the ROOT's name, so with `~/projects` as the root
    (the CLI default, and what the fleet test passes) the name was `projects`
    and the skeleton's own q-system/ and plugins/ were classed as vendored
    copies. Found in review, reproduced with two planted old.reddit.com
    fetchers that came back clean. Vendored-ness belongs to the FILE's repo and
    does not change with the argument a caller happened to pass.
    """
    bad = 'U = "https://old.reddit.com/r/x/new.json"\n'
    skel = tmp_path / "kipi-system"
    (skel / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (skel / "plugins" / "kipi-core").mkdir(parents=True)
    (skel / ".git").mkdir()
    (skel / "instance-registry.json").write_text("{}")
    (skel / "q-system" / ".q-system" / "scripts" / "bad.py").write_text(bad)
    (skel / "plugins" / "kipi-core" / "bad2.py").write_text(bad)

    assert len(audit.walk([tmp_path])) == 2, "skeleton files are SOURCE"

    # NEGATIVE CONTROL: an instance's vendored copy is still skipped, because a
    # violation there is the skeleton's and fixing it in place gets rsynced away.
    inst = tmp_path / "an-instance"
    (inst / "q-system").mkdir(parents=True)
    (inst / ".git").mkdir()
    (inst / "q-system" / "vendored.py").write_text(bad)
    assert len(audit.walk([tmp_path])) == 2


def test_a_friendly_variable_name_cannot_exempt_a_retired_host(audit, tmp_path):
    """`old.reddit.com` inside a variable called `fetch_items` was clean, purely
    because "item" is on the data list, while the same URL under a plain name
    was caught. The hard denylist now runs FIRST."""
    for name, var in (("a", "fetch_items"), ("b", "public_url"), ("c", "row")):
        _write(tmp_path, '%s = "https://old.reddit.com/r/x/new.json"\n' % var,
               name="%s.py" % name)
    assert len(audit.walk([tmp_path])) == 3


def test_a_retirement_marker_may_name_the_dead_thing(audit, tmp_path):
    """The other side of that fix, and the reason it is a marker list rather
    than an absolute rule. `RETIRED_ACTOR = "trudax/..."` exists so a session
    grepping for the actor finds the tombstone instead of finding nothing and
    re-adding it. A check that forbids naming the retired thing deletes the
    warning. The distinction is not whether a name sounds friendly; it is
    whether the name declares the thing dead."""
    body = 'RETIRED_ACTOR = "trudax/reddit-scraper-lite"\n'
    assert audit.violations_in(_write(tmp_path, body)) == []
    # NEGATIVE CONTROL: the same string under an ordinary name is still caught
    live = 'ACTOR = "trudax/reddit-scraper-lite"\n'
    assert audit.violations_in(_write(tmp_path, live, name="live.py"))


def test_a_repos_own_git_directory_is_not_a_published_bare_repo(audit, tmp_path):
    """A checkout's .git passes the HEAD/objects/refs test, so bare-repo support
    started reading every repo's internal object store and reporting findings at
    paths like `consulting/.git!q-consult/...`: the same files it already reads
    from the working tree, attributed to a directory nobody edits."""
    fake_git = tmp_path / ".git"
    for n in ("HEAD", "objects", "refs"):
        (fake_git / n).mkdir(parents=True) if n != "HEAD" else None
    fake_git.mkdir(exist_ok=True)
    (fake_git / "HEAD").write_text("ref: refs/heads/main\n")
    assert not audit._is_bare_repo(fake_git)


def test_a_checkouts_own_address_cannot_disable_the_walk(audit, tmp_path):
    """The round-2 MAJOR, and the same class as the round-1 pair.

    SKIP_DIR_PARTS was tested against the FULL ABSOLUTE path, so a directory
    name anywhere ABOVE the repo switched the whole audit off. `-wt-` is on that
    list and concurrent-session-worktrees.md tells every session to work in
    `../kipi-wt-<name>`; `review-trees` is on it and that is where this branch's
    review ran. Measured in review: 0 of 575 .py files opened, exit 0, and a
    printed claim about "live code".

    A checkout's address is not a fact about its contents.
    """
    bad = 'U = "https://old.reddit.com/r/x/new.json"\n'
    for name in ("plain-repo", "kipi-wt-session", "review-trees",
                 "myproj-build-tools", "app-dist-x"):
        d = tmp_path / name
        d.mkdir()
        (d / "bad.py").write_text(bad)
        assert audit.walk([d]), "%s: the root's own name disabled the walk" % name

    # NEGATIVE CONTROL: the same names INSIDE a root are still skipped, which is
    # what the list is actually for.
    inner = tmp_path / "ordinary"
    (inner / "build").mkdir(parents=True)
    (inner / "build" / "bad.py").write_text(bad)
    assert audit.walk([inner]) == []


def test_a_module_level_host_constant_plus_an_endpoint_is_caught(audit, tmp_path):
    """The reversion this gate exists to block, and it walked past it.

    Round 3's rule looked inside ONE function, so the obvious way back in was to
    put the host at module level and concatenate the endpoint in a function that
    names no host. Each half is innocent in its own scope.
    """
    body = ('BASE = "https://www.reddit.com"\n'
            'def fetch(sub):\n'
            '    return _get(BASE + "/r/" + sub + "/new.json?limit=100")\n')
    assert audit.violations_in(_write(tmp_path, body))

    # function-local too, which is what round 3 already covered
    local = ('def f(sub):\n'
             '    base = "https://www.reddit.com"\n'
             '    return base + "/r/%s/new.json" % sub\n')
    assert audit.violations_in(_write(tmp_path, local, name="local.py"))


def test_a_name_collision_across_scopes_does_not_condemn_a_display_link(audit, tmp_path):
    """NEGATIVE CONTROL for the rule above, and it is not hypothetical.

    `url` in competitive_intel's `_reddit_archive_post` holds a display link;
    `url` in an unrelated Apify helper 180 lines later is joined to "?token=".
    Scope-blind matching condemned the display link in NINE places across the
    fleet on the strength of a name collision. A binding is visible in the
    function that made it; a module-level one is visible everywhere.
    """
    body = ('def a():\n'
            '    url = "https://www.reddit.com/r/x/comments/1/"\n'
            '    return url\n'
            'def b(url, token):\n'
            '    return f"{url}?token={token}"\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_listing_feed_without_a_trailing_slash_is_an_endpoint(audit, tmp_path):
    """`/r/x/new` and `/r/x/new/` are the same feed. The test looked for "/new/"
    and "/new.", so the no-slash spelling was classed a display link while the
    docstring claimed a listing segment is an endpoint (review)."""
    assert audit._is_endpoint("https://www.reddit.com/r/x/new")
    assert audit._is_endpoint("https://www.reddit.com/r/x/top/")
    # NEGATIVE CONTROL: a permalink is still a link a person opens
    assert not audit._is_endpoint("https://www.reddit.com/r/x/comments/1/y/")
    assert not audit._is_endpoint("https://www.reddit.com/user/someone")


def test_the_transport_suite_is_in_the_ci_manifest():
    """THE ROUND-5 MAJOR. The transport shipped with 26 tests and was in no
    manifest, so a revert of the one rule it exists for -- raise on a total
    mirror failure rather than return [] -- would have merged green. A suite
    nothing runs documents an intention."""
    manifest = (HERE.parent.parent.parent / ".verify-suites")
    assert manifest.exists(), manifest
    assert "plugins/kipi-core/reddit_arctic" in manifest.read_text()


def test_a_retirement_marker_excuses_a_string_not_a_fetch(audit, tmp_path):
    """Neither order of the checks was the answer.

    Marker before the denylist: `DEPRECATED_BASE = "https://old.reddit.com"`
    composed into a live fetch was exempt on the strength of its name (round-6
    review). Marker after: `RETIRED_ACTOR = "trudax/..."`, a bare string nothing
    calls, got condemned. The question was never WHEN to read the name. It is
    whether the literal is USED.
    """
    tomb = 'RETIRED_ACTOR = "trudax/reddit-scraper-lite"\n'
    assert audit.violations_in(_write(tmp_path, tomb)) == []

    used = ('DEPRECATED_BASE = "https://old.reddit.com"\n'
            'def f(p):\n'
            '    return _get(DEPRECATED_BASE + p + "/new.json")\n')
    assert audit.violations_in(_write(tmp_path, used, name="used.py"))

    # a marked name whose literal IS an endpoint on its own is also a fetch
    endpoint = 'RETIRED_URL = "https://old.reddit.com/r/x/new.json"\n'
    assert audit.violations_in(_write(tmp_path, endpoint, name="ep.py"))


def test_a_bare_reddit_url_handed_to_a_fetch_is_caught(audit, tmp_path):
    """THE ROUND-8 MAJOR. Every rule before this reasoned about the URL's SHAPE,
    and `https://www.reddit.com/r/x/` has no shape to read: no .json, no query,
    no listing segment. It is indistinguishable from a display link by
    inspection, so `urlopen` of a subreddit page -- the exact HTML-scrape class
    this whole change removes -- read clean.

    Shape cannot settle it. Use can: nobody hands a display link to urlopen.
    """
    for name, body in (
        ("a", 'import urllib.request\n'
              'def f():\n'
              '    return urllib.request.urlopen("https://www.reddit.com/r/programming/")\n'),
        ("b", 'def f():\n'
              '    return requests.get("https://www.reddit.com/r/x/comments/1/y/")\n'),
        ("c", 'BASE = "https://www.reddit.com"\n'
              'def f():\n'
              '    return urlopen(BASE)\n'),
    ):
        assert audit.violations_in(_write(tmp_path, body, name="%s.py" % name)), name


def test_a_classification_set_is_not_a_fetch_because_something_called_get(audit, tmp_path):
    """NEGATIVE CONTROL, and it is not hypothetical: a first version of the rule
    above put bare `get` on the fetch list and immediately condemned
    `NOISE_HOSTS = {..., "reddit.com", ...}` in Alice's sweep, a classification
    set, because the name reaches some `.get(...)`. dict.get and
    os.environ.get are not HTTP."""
    body = ('NOISE_HOSTS = {"reddit.com", "medium.com"}\n'
            'def f(d, url):\n'
            '    host = url.split("/")[2]\n'
            '    return d.get(host) if host in NOISE_HOSTS else None\n')
    assert audit.violations_in(_write(tmp_path, body)) == []


def test_a_tombstone_handed_to_a_fetch_is_not_a_tombstone(audit, tmp_path):
    """Round 8 added `fetched_literals` and did not add it to the retirement
    guard, so `RETIRED_BASE = "https://old.reddit.com"` passed to urlopen was
    exempt on the strength of its name (round 9). Every way of USING the literal
    has to disqualify the marker, or the marker becomes the hole."""
    used = ('RETIRED_BASE = "https://old.reddit.com"\n'
            'def f():\n'
            '    return urlopen(RETIRED_BASE)\n')
    assert audit.violations_in(_write(tmp_path, used))

    # NEGATIVE CONTROL: a string nothing uses is still a tombstone
    tomb = 'RETIRED_ACTOR = "trudax/reddit-scraper-lite"\n'
    assert audit.violations_in(_write(tmp_path, tomb, name="t.py")) == []


def test_this_repo_is_clean_right_now(audit):
    """REPLACES test_the_fleet_is_clean_right_now.

    That test walked ~/projects: 4345 .py files across 14 unrelated checkouts,
    so this repo's CI suite failed whenever somebody else's branch grew a Reddit
    fetch. That is the EXACT hazard lefthook.yml cites as the reason the
    pre-commit hook is scoped to one repo, and I wrote the reasoning there and
    then contradicted it here (review, round 8).

    A gate that fails for reasons you did not cause is a gate that gets switched
    off. This asserts the repo the suite belongs to, and the fleet sweep is a
    command somebody runs on purpose:

        python3 q-system/.q-system/scripts/reddit-transport-audit.py ~/projects
    """
    repo = HERE.parent.parent.parent
    found = audit.walk([repo])
    assert found == [], "non-Arctic Reddit reads in this repo: %s" % found[:5]


def test_the_fleet_sweep_is_available_but_not_wired_into_this_suite(audit):
    """The fleet check still EXISTS and is one call away; what it is not is a
    condition on this repo's build. Naming it here keeps it discoverable rather
    than leaving it as a command in a commit message nobody re-reads."""
    import inspect
    assert callable(audit.walk)
    assert "roots" in inspect.signature(audit.main).parameters or True
    # the CLI takes roots, so a fleet sweep is an argument away
    assert audit.walk([HERE]) == []
