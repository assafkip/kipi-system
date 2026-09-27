#!/usr/bin/env python3
"""Arctic Shift is the only way this fleet scrapes Reddit. This is the check.

Founder-directed 2026-09-04, verbatim: "change any reddit searches on the entire
kipi corpus into arctic shift. Any collection from reddit that is not using
arctic shift should be changed to it. this must be the only way we scrape
reddit."

A rule that lives only in a docstring is a rule until the next person writes a
convenient `urlopen("https://www.reddit.com/r/x/new.json")`. So the rule is a
script that walks the corpus and exits 1.

## What it looks for

A NON-ARCTIC REDDIT HOST inside a string literal in live code. Parsed with `ast`,
not grepped, for a reason that cost a test rewrite the same day this was written:
the retired hosts are NAMED in the scar comments that explain why they are
retired, and a line-level grep forbids the file from recording its own reason.
Comments and docstrings are exempt. String literals are not.

## What it deliberately allows

  https://www.reddit.com/...   as a DISPLAY link a human clicks. Never fetched.
                               Recognised by the URL's own SHAPE, not by what it
                               is called: a bare profile or permalink is a link,
                               while .json, .rss, /api/, /search, a query string
                               or a listing feed segment is an endpoint.

## What it forbids

  old.reddit.com               the HTML scrape reddit_read.py used to do
  oauth.reddit.com             the official API, whose app creation is gated
                               behind an approval this account cannot get
  *.json / .rss endpoints      throttled and 403'd from datacenter IPs
  trudax/reddit-scraper-lite   the retired Apify actor
  api.apify.com + reddit       any Apify run whose input names a subreddit

Usage:

    python3 reddit-transport-audit.py [root ...]      # defaults to ~/projects
    python3 reddit-transport-audit.py --json

Exit 0 clean, exit 1 with one line per violation.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_HOSTS = ("arctic-shift.photon-reddit.com", "api.pullpush.io")

# WHAT DECIDES A DISPLAY LINK IS THE URL, NOT THE NAME. A DISPLAY_NAMES list
# lived here and went dead when the endpoint test moved to URL shape: still
# computed, never read, and still documented in the module docstring as the
# allow mechanism (PR 307 review, NIT 6). A list nothing reads is worse than no
# list, because the next person tunes it and nothing happens.

# A DENYLIST that names a host is the opposite of a violation: it is this rule
# being enforced somewhere else. `browser_session_health.forbidden_probe_hosts`
# was the first false positive this audit produced, and a checker that flags the
# guard it agrees with is a checker people switch off.
DENYLIST_NAMES = ("forbidden", "blocked", "denied", "banned",
                  "refuse", "reject", "never", "not_allowed",
                  "bad_hosts", "skip")

# THE ONE THING THAT OUTRANKS THE HARD DENYLIST. Naming the retired actor is how
# a module records that it is retired: `RETIRED_ACTOR = "trudax/..."` exists
# precisely so a session grepping for the actor finds the note instead of finding
# nothing and re-adding it. Making the denylist absolute (PR 307 review, MINOR 4)
# was right for `old.reddit.com` hiding inside a variable called `fetch_items`,
# and wrong for a constant whose name says RETIRED. The distinction is not "does
# the name sound friendly" but "does the name declare this thing dead".
RETIREMENT_MARKERS = ("retired", "deprecated", "removed", "dead")

# NAMING A DOMAIN IS NOT FETCHING IT. Three distinct non-fetch uses turned up
# across the corpus, and each one is a legitimate thing to write:
#
#   classification   `noise_hosts`, `venue_hosts`, `community_hosts`,
#                    `generic_infra`, `multi_tenant`, `marker`: a list of domains
#                    that decides how a URL is TREATED. Reddit has to be in it.
#   evidence         investigation case files and authorship fixtures carry the
#                    real URLs they are about.
#   sample text      a prompt or a docstring quoting what a source looks like.
#
# None of them opens a connection. A checker that cannot tell a domain being
# classified from a domain being fetched flags all three, and a report that is
# mostly false positives is a report nobody runs. Measured 2026-09-04: these
# three classes were the entire remainder after every real fetcher was converted.
DATA_NAMES = ("hosts", "domains", "infra", "venue", "noise", "community",
              "tenant", "marker", "sample", "fixture", "case", "seed",
              "example", "corpus", "known",
              # "sites" and "profile" were HERE and are deliberately not, any
              # more (2026-09-05). A table named _SITES in an OSINT probe holds
              # URL TEMPLATES THAT GET FETCHED, so exempting the word hid a live
              # `www.reddit.com/user/{u}/about.json` in a published repo. That is
              # the cost of a suppression list written to quiet false positives:
              # each entry buys silence on a real one somewhere. "public" stays
              # because it labels the human-facing link built beside that probe.
              "public", "expected", "row", "item")

FORBIDDEN_SUBSTRINGS = (
    "old.reddit.com",
    "oauth.reddit.com",
    "np.reddit.com",
    "reddit.com/api/",
    "trudax/reddit-scraper-lite",
    "trudax~reddit-scraper-lite",
)

# Directories that are copies, caches, or history. A violation in one of these is
# a violation in its source, and reporting both is noise that trains people to
# ignore the report.
SKIP_DIR_PARTS = (
    "node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages",
    "worktrees", "_archive", "_wt", ".wt-", "-wt-", "review-trees",
    "/output/", "/fixtures/", ".prd-os", "/logs/", "dist", "build",
    "consulting-baseline", "consulting-c3", "consulting-c4", "consulting-kipi",
    "kipi-system-main", "dead-hooks", ".review-tmp",
)

# The only tokens allowed to match INSIDE a directory name. Everything else in
# SKIP_DIR_PARTS is compared as a whole segment.
_FRAGMENT_TOKENS = {".wt-", "-wt-", "review-trees", ".review-tmp"}

# Calls that OPEN a URL. A display link is never an argument to one of these, so
# a reddit host appearing here is a fetch no matter how innocent its shape.
# Calls that OPEN a URL. A display link is never an argument to one of these,
# so a reddit host appearing here is a fetch no matter how innocent its shape.
#
# `get` is NOT on this list unqualified, and that is the whole design note:
# a first version included it and immediately condemned
# `NOISE_HOSTS = {..., "reddit.com", ...}` in Alice's sweep, a CLASSIFICATION
# set, because the name reaches some `.get(...)` somewhere. `dict.get` and
# `os.environ.get` are not HTTP.
_FETCH_CALLS = {
    "urlopen", "urlretrieve", "fetch", "fetch_json", "fetch_text",
    "_get_json", "_fetch", "_fetch_json", "_fetch_text", "read_url",
    "http_get", "urlretrieve",
}

# The verbs that only mean "fetch" when the RECEIVER is an HTTP client.
_HTTP_VERBS = {"get", "post", "head", "request", "send"}
_HTTP_RECEIVERS = ("requests", "session", "http", "client", "httpx", "urllib",
                   "opener", "curl", "aiohttp")

SUFFIXES = (".py",)

# THE EXCEPTIONS, each with its reason, in ONE place that is printed with every
# report. A per-file allowlist rots the moment nobody can say why a row is on it,
# so the reason is required here and the report shows the list even when it is
# clean. These are WRITE paths and self-references. This audit's subject is
# READING Reddit; posting to Reddit is a different rule with a different owner,
# and the two files below are not collectors.
EXCEPTIONS = {
    "gtm/scripts/reddit_worker/reddit_api_probe.py":
        "a WRITE path, and already refuses to run. Retired 2026-09-04: Reddit "
        "gates OAuth script-app creation behind an approval this account does "
        "not have. Kept, not deleted, because it is the most convincing "
        "resurrection kit in the fleet and the next session should find the "
        "reason rather than nothing.",
    "gtm/scripts/reddit_worker/reddit_driver.py":
        "a WRITE path (the browser poster). This audit governs reading Reddit; "
        "what posts to Reddit is a separate rule.",
    "q-system/.q-system/scripts/reddit-transport-audit.py":
        "this file. Its allow and deny lists have to name the hosts.",
    "plugins/kipi-core/reddit_arctic/transport.py":
        "the sanctioned transport. Its normalizer builds the display link.",
}


def _exception_for(path: Path):
    text = str(path)
    for suffix, reason in EXCEPTIONS.items():
        if text.endswith(suffix):
            return reason
    return None

# AN INSTANCE'S VENDORED COPIES ARE NOT SOURCE. `q-system/` and `plugins/` inside
# an instance are skeleton-sync DESTINATIONS, rsynced from the skeleton; a
# violation there is the skeleton's violation, and fixing it in place is undone
# by the next sync. The skeleton's own copies ARE audited, because there the path
# is the source. Measured 2026-09-04: auditing the vendored copies turned 8 real
# findings into 719, which is how a report stops being read.
VENDORED = ("q-system", "plugins")


def _repo_root_of(path: Path):
    """The checkout a file belongs to: nearest ancestor carrying a .git."""
    for parent in path.resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _is_the_skeleton(repo) -> bool:
    """The skeleton OWNS its q-system/ and plugins/; everywhere else those are
    sync destinations. Identified by the registry it carries, with the directory
    name as a fallback, so a rename cannot silently turn the source into a
    copy."""
    if repo is None:
        return False
    return (repo / "instance-registry.json").exists() or repo.name == "kipi-system"


def _is_vendored_copy(path: Path, root=None) -> bool:
    """Decided from the FILE's own repo, never from the root handed in.

    It used to read `Path(root).name == "kipi-system"`. The CLI default root is
    `~/projects`, and the fleet test passes `~/projects` as one root by design,
    so the name was `projects` and the SKELETON'S OWN q-system/ and plugins/
    were classed as vendored and skipped. The sweep reporting "0 across every
    checkout" was structurally unable to look at the two directories this audit
    lives in (PR 307 review, MAJOR 2, reproduced with two planted
    old.reddit.com fetchers that came back clean).

    A file belongs to whatever repo contains it, and that answer does not change
    with the argument the caller happened to pass.
    """
    repo = _repo_root_of(path)
    if repo is None:
        return False
    if _is_the_skeleton(repo):
        return False
    try:
        rel = path.resolve().relative_to(repo)
    except ValueError:
        return False
    return any(part in VENDORED for part in rel.parts)


def _is_test(path: Path) -> bool:
    """Tests are exempt, and the exemption is the honest one.

    A test that proves a guard BLOCKS old.reddit.com has to name old.reddit.com,
    and a fixture URL is not a fetch. Measured 2026-09-04: including tests turned
    8 live findings into 131, and every added row was a fixture or an assertion
    about a host being refused. The audit is about live fetch paths; the tests
    are how the live paths are held.
    """
    name = path.name
    return (name.startswith("test_") or name.endswith("_test.py")
            or "tests" in path.parts or name.startswith("calibrate_"))


def _is_linked_worktree(root: Path) -> bool:
    """A linked git worktree is a CHECKOUT, not a source of truth.

    Detected structurally: git writes a `.git` FILE (a pointer) in a linked
    worktree and a `.git` DIRECTORY in the main one. Its content is some branch's
    state and it converges when that branch does, so auditing it reports the same
    defect twice and blames the copy.

    Structural rather than by name, deliberately. SKIP_DIR_PARTS already carries
    a hand-written list of checkout directory names, and `consulting-landing` was
    not on it -- so the fleet test failed on a worktree sitting on a branch from
    two weeks earlier. A guard that enumerates by hand only sees what somebody
    remembered to add.
    """
    dot = root / ".git"
    return dot.is_file()


def _skip(path: Path, root=None) -> bool:
    """Skip decided on the path RELATIVE to the root handed in.

    It used to test those substrings against the FULL ABSOLUTE path, so a
    directory NAME anywhere ABOVE the repo switched the entire audit off. That
    is not theoretical: `.claude/rules/concurrent-session-worktrees.md` tells
    every session to work in `../kipi-wt-<name>`, and `-wt-` is on the list;
    `review-trees` is on it too, and that is where this branch's own review ran.
    Measured in review: 0 of 575 .py files opened, exit 0, and a printed claim
    about "live code".

    Worse than the worktree case round 1 fixed, because it also kills a MAIN
    checkout whose parent directory happens to contain `build`, `dist`, `venv`
    or `worktrees`. A checkout's own address is not a fact about its contents.
    """
    if root is None:
        return False
    try:
        rel = path.resolve().relative_to(Path(root).expanduser().resolve())
    except ValueError:
        return False
    # SEGMENTS, not substrings. `build` matched `reddit-build-radar`, a real
    # fleet project holding a live old.reddit.com fetch, so the audit walked
    # past it and printed 0. Measured in review: 28,051 .py files under
    # ~/projects were excluded by a substring that is not a directory, 232 of
    # them on `build` alone, including two source files in this repo.
    segments = rel.parts
    for token in SKIP_DIR_PARTS:
        bare = token.strip("/")
        for seg in segments:
            if seg == bare:
                return True
            # Only these tokens are deliberately fragments, and even they are
            # matched inside ONE segment so they cannot span a path boundary.
            if token in _FRAGMENT_TOKENS and bare in seg:
                return True
    return False


def _docstring_ids(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            first = node.body[0] if getattr(node, "body", None) else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.add(id(first.value))
    return out


def _context_names(tree: ast.AST) -> dict[int, str]:
    """Which name a string literal is bound to, so a display link is telling the
    truth about being one. Covers `X = "..."`, `{"url": "..."}`, f-strings inside
    either, and a `return f"https://..."` inside a function whose name says url.
    """
    names: dict[int, str] = {}

    def tag(node, label):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                names.setdefault(id(sub), label)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            label = " ".join(t.id for t in node.targets if isinstance(t, ast.Name))
            if label:
                tag(node.value, label)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                tag(node.value, node.target.id)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    tag(value, key.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    tag(sub.value, node.name)
    return names


def _classification_ids(tree: ast.AST) -> set[int]:
    """Literals that are being COMPARED against, or asserted on, never fetched.

    Two shapes, both principled rather than per-file:

      `if "reddit.com" in url:`        a URL classifier. The literal is the
                                       right side of an `in` test, which reads a
                                       string, it does not open one.
      `check("...", f("https://..."))` an inline self-test. A call whose name
                                       says check/assert/expect is a test even
                                       when it does not live in a tests/ dir.

    These were the last two findings in the corpus after every real fetcher was
    converted, and neither is a fetch. A name-based rule could not see them: one
    sits in a Compare node and one in a Call argument, so neither is bound to a
    variable there is a name for.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    for side in (node.left, comparator):
                        for sub in ast.walk(side):
                            if (isinstance(sub, ast.Constant)
                                    and isinstance(sub.value, str)):
                                out.add(id(sub))
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if any(w in name.lower() for w in ("check", "assert", "expect")):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        out.add(id(sub))
    return out


def violations_in(path: Path) -> list[dict]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return violations_in_source(source, str(path))


def _name_says(label: str, tokens) -> bool:
    """Match a name token on WORD boundaries, never as a bare substring.

    `row` is in DATA_NAMES and `row` sits inside `browser`, so a variable named
    `browser_feed` was exempt from every check (review, MAJOR 2). Identifiers
    split on underscores, hyphens, dots and case changes; a token has to be one
    of those pieces.
    """
    if not label:
        return False
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", label)
    words = {w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w}
    return any(tok in words for tok in tokens)


def _is_endpoint(low: str) -> bool:
    """A URL either names a machine endpoint or a page a person opens. ONE
    definition, used by the single place that decides."""
    return (".json" in low or ".rss" in low or "/api/" in low
            or "/search" in low or "?" in low
            or _ends_in_a_listing(low))


_LISTINGS = ("new", "hot", "top", "rising", "controversial", "best")


def _ends_in_a_listing(low: str) -> bool:
    """`/r/x/new` with no trailing slash is a listing feed too.

    The old test looked for "/new/" and "/new.", so a URL ENDING in the segment
    was classed a display link while the docstring said "a listing feed segment
    is an endpoint" (review). Reddit serves both spellings.
    """
    path = low.split("?", 1)[0].rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    if tail in _LISTINGS:
        return True
    return any("/%s/" % seg in low or "/%s." % seg in low for seg in _LISTINGS)


def _joined_text(node: ast.AST) -> str:
    """The whole template an f-string spells out, placeholders as <>.

    THE REASON THIS EXISTS. `f"https://www.reddit.com/r/{sub}/hot/.rss"` is not
    one string node. Python splits it: "https://www.reddit.com/r/" and
    "/hot/.rss" are separate Constants with the placeholder between them. So a
    test asking "does the literal containing reddit.com also look like an
    endpoint" reads only the first fragment, sees no .rss, and calls a live RSS
    fetch a display link. Measured 2026-09-05: that dropped three real findings
    in published repos from the report while the checker still said it was
    working.
    """
    parts = []
    for sub in getattr(node, "values", []):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            parts.append(sub.value)
        else:
            parts.append("<>")
    return "".join(parts)


def violations_in_source(source: str, label: str) -> list[dict]:
    """The analysis, given content rather than a path.

    Split out so a BARE repository can be read. A bare repo has no working tree,
    so the file walk sees nothing in it and reports it clean. 33 published repos
    were reported clean that way by a checker structurally unable to open any of
    them, and three of them were shipping a retired Reddit transport at the time
    (measured 2026-09-05). A clean result from a reader that cannot read is the
    same defect this whole suite exists to refuse.
    """
    path = Path(label)
    if "reddit" not in source.lower():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # WHICH FUNCTIONS BUILD AN ENDPOINT ANYWHERE IN THEIR BODY.
    #
    # `base = f"https://www.reddit.com/r/{sub}"` is not an endpoint on its own,
    # and neither is `f"{base}/top/.rss"`. Split across two literals, each half
    # reads as innocent and the audit walked past a live RSS listing fetch
    # (reddit-build-radar `_reddit_listing_rss_url`).
    #
    # Joining them properly is dataflow, which this checker does not do. What it
    # does instead is scoped and explainable: if a function names a reddit host
    # AND any literal in that same function has an endpoint shape, the host
    # literal is judged an endpoint. HONEST LIMIT: a builder that returns a bare
    # host for a caller in another function to complete is still missed. That is
    # a smaller hole than the one it closes, and naming it is better than
    # implying the checker is complete.
    endpoint_funcs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lits = [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            # A REAL CONCATENATION, not "this function also mentions an
            # endpoint somewhere". The path half must be a PATH FRAGMENT: a
            # literal starting with "/" that is itself an endpoint. Without that
            # narrowing this rule flagged eight display links and refusal
            # messages to catch one builder.
            if any("reddit.com" in v.lower() for v in lits) and \
               any(v.startswith("/") and _is_endpoint(v.lower()) for v in lits):
                for n in ast.walk(node):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str):
                        endpoint_funcs.add(id(n))

    # A HOST CONSTANT THAT SOMEBODY CONCATENATES AN ENDPOINT ONTO.
    #
    # The round-3 rule looked inside ONE function, so the obvious reversion
    # walked past it: put `BASE = "https://www.reddit.com"` at module level, then
    # fetch `BASE + "/r/x/new.json"` from a function that itself contains no
    # host. Each half is innocent in its own scope and the pre-commit gate
    # reported clean on the exact change it exists to block (review, MAJOR 1).
    #
    # So: collect the names bound to a reddit host ANYWHERE (module, class or
    # function level), then flag that host literal if any `+` in the file joins
    # one of those names to an endpoint-shaped path. Still not dataflow, and the
    # THE HONEST LIMIT, stated wider than it was. This sees `+` and f-strings.
    # It does NOT see `"/".join([BASE, path])`, `urljoin(BASE, path)`,
    # `BASE + PATH` where both sides are names, `%` formatting, or a host passed
    # in as a function ARGUMENT. Each of those composes a URL without ever
    # putting the host beside an endpoint literal, which is the only shape this
    # rule reads.
    #
    # That is a real hole and naming it is the point: FORBIDDEN_SUBSTRINGS still
    # catches old.reddit.com, oauth.reddit.com, /api/ and the trudax actor
    # absolutely, in any composition, because those are decided on the literal
    # alone. What escapes is a www.reddit.com host composed with an endpoint
    # path through a route this rule cannot follow. Closing it properly is
    # dataflow analysis, which this checker does not do and should not pretend
    # to.
    # SCOPED. A name means different things in different functions, and the
    # first version of this rule did not care: `url` in `_reddit_archive_post`
    # holds a display link, and `url` in an unrelated Apify helper 180 lines
    # later is joined to "?token=". Scope-blind matching condemned the display
    # link in nine places across the fleet on the strength of a name collision.
    #
    # A binding is visible in the function that made it, and a module-level one
    # is visible everywhere. That is the whole of the scoping this needs.
    def _scope_of(tree_):
        owner = {}
        for fn in ast.walk(tree_):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for n in ast.walk(fn):
                    owner.setdefault(id(n), fn)
        return owner

    owner = _scope_of(tree)

    def _key(node):
        fn = owner.get(id(node))
        return id(fn) if fn is not None else "module"

    host_names = {}          # (scope, name) -> Constant nodes bound there
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            val = node.value
            if val is None:
                continue
            lits = [n for n in ast.walk(val)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and "reddit.com" in n.value.lower()
                    and "photon" not in n.value.lower()]
            if not lits:
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    host_names.setdefault((_key(node), tgt.id), []).extend(lits)

    concatenated_hosts = set()
    for node in ast.walk(tree):
        joined_names, endpoint_here = set(), False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            sides = [node.left, node.right]
            joined_names = {n.id for side in sides for n in ast.walk(side)
                            if isinstance(n, ast.Name)}
            endpoint_here = any(
                _is_endpoint(n.value.lower()) for side in sides
                for n in ast.walk(side)
                if isinstance(n, ast.Constant) and isinstance(n.value, str))
        elif isinstance(node, ast.JoinedStr):
            joined_names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            endpoint_here = _is_endpoint(_joined_text(node).lower())
        if not endpoint_here:
            continue
        here = _key(node)
        for name in joined_names:
            for scope in (here, "module"):
                for lit in host_names.get((scope, name), []):
                    concatenated_hosts.add(id(lit))

    # A HOST PASSED TO A FETCH IS A FETCH, whatever shape the URL has.
    #
    # Everything above reasons about the URL's SHAPE, and a bare
    # `https://www.reddit.com/r/x/` has no endpoint shape at all: no .json, no
    # query, no listing segment. It is indistinguishable from a display link by
    # inspection. So `urlopen("https://www.reddit.com/r/programming/")` and
    # `requests.get(...)` -- the exact HTML-scrape class this whole change
    # removes -- read clean (review, round 8).
    #
    # Shape cannot settle it. USE can: nobody hands a display link to urlopen.
    fetched_literals = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (getattr(node.func, "attr", "")
                or getattr(node.func, "id", "")).lower()
        if name in _HTTP_VERBS:
            recv = getattr(node.func, "value", None)
            recv_name = ((getattr(recv, "id", "") or getattr(recv, "attr", ""))
                         .lower())
            if not any(tok in recv_name for tok in _HTTP_RECEIVERS):
                continue
        elif name not in _FETCH_CALLS:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                        and "reddit.com" in sub.value.lower()
                        and "photon" not in sub.value.lower()):
                    fetched_literals.add(id(sub))
                # a NAME handed to a fetch drags in whatever host it was bound to
                if isinstance(sub, ast.Name):
                    for scope in (_key(node), "module"):
                        for lit in host_names.get((scope, sub.id), []):
                            fetched_literals.add(id(lit))

    skip = _docstring_ids(tree) | _classification_ids(tree)
    labels = _context_names(tree)
    # id(constant) -> the full f-string it is a fragment of
    joined: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            whole = _joined_text(node)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    joined[id(sub)] = whole
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        text = joined.get(id(node), node.value)
        low = text.lower()
        # A URL HAS NO SPACES. Refusal messages and prompt samples mention the
        # retired hosts by design ("reddit.com/.json is retired, use ..."), and
        # flagging those turned a 1-real-finding report into 9. A sentence about
        # a host is not a fetch of it.
        if any(ch.isspace() for ch in text.strip()):
            continue
        if "reddit" not in low:
            continue
        if any(host in low for host in ALLOWED_HOSTS):
            continue

        # THE HARD DENYLIST RUNS FIRST, BEFORE ANY NAME EXEMPTION. It used to
        # run after, so `old.reddit.com` inside a variable called `fetch_items`
        # was exempt purely because "item" is on the data list, while the same
        # URL under a plain name was caught. A comment further down claimed the
        # denylist "still catches old.reddit.com absolutely"; it did not (PR 307
        # review, MINOR 4). A name can argue that a www.reddit.com URL is a
        # label. It cannot argue about a retired host.
        why = None
        label_early = (labels.get(id(node)) or "").lower()

        # THE HARD DENYLIST AND THE ENDPOINT TEST BOTH RUN BEFORE ANY NAME MAY
        # EXEMPT. Round 2 moved the denylist ahead of the names and stopped
        # there, so `.json` and `.rss` -- which are NOT in FORBIDDEN_SUBSTRINGS,
        # they are decided by URL shape -- were still silenced by a variable
        # called `fetch_items` or `known_feeds`. The comment below already
        # claimed "an endpoint is a finding regardless of what it is called".
        # Now it is true.
        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in low:
                why = bad
                break
        if why is None and "reddit.com" in low and id(node) in fetched_literals:
            why = "reddit.com URL handed to a fetch"
        if why is None and "reddit.com" in low and (
                _is_endpoint(low) or id(node) in endpoint_funcs
                or id(node) in concatenated_hosts):
            why = "reddit.com endpoint"
        # A NAME MAY ONLY EXEMPT WHAT THE URL DID NOT ALREADY CONDEMN. What is
        # left here is a plain www.reddit.com URL with no endpoint shape, which
        # is what a profile or a permalink looks like, so a classification list
        # or a piece of evidence data may say "this is a label, not a fetch".
        # A TOMBSTONE MAY NAME THE DEAD THING. It may not BE a live fetch.
        #
        # The marker used to run before the denylist, so `DEPRECATED_BASE =
        # "https://old.reddit.com"` composed into a real fetch was exempt on the
        # strength of its name (review). Running it after instead broke the case
        # it exists for: `RETIRED_ACTOR = "trudax/..."` is a bare string that
        # nothing calls, and the denylist condemned it.
        #
        # Neither order is the answer, because the question is not WHEN to check
        # the name. It is whether the literal is USED. A retirement marker
        # excuses a string that is never composed into a URL, and excuses
        # nothing that is.
        # A tombstone is a string nothing uses. Round 8 added `fetched_literals`
        # -- a host handed straight to urlopen -- and did not add it here, so
        # `RETIRED_BASE = "https://old.reddit.com"` passed to urlopen was exempt
        # on the strength of its name (round 9). Every way of USING the literal
        # has to disqualify the marker, or the marker becomes the hole.
        if _name_says(label_early, RETIREMENT_MARKERS) and \
                id(node) not in concatenated_hosts and \
                id(node) not in endpoint_funcs and \
                id(node) not in fetched_literals and \
                not _is_endpoint(low):
            continue
        if why is None and _name_says(label_early,
                                      DENYLIST_NAMES + DATA_NAMES):
            continue
        if why:
            found.append({"file": str(path), "line": node.lineno,
                          "reason": why, "text": text[:120]})
    # One finding per (line, reason). An f-string reports through every fragment
    # it is made of, and three copies of one defect is a report people skim.
    seen, unique = set(), []
    for v in found:
        key = (v["file"], v["line"], v["reason"])
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return unique


def _bare_repo_violations(repo: Path) -> list[dict]:
    """Read a bare repo's HEAD tree through git, since there is no checkout.

    Only .py, because that is what this audit parses. A bare repo carrying a
    Reddit fetcher in another language is a gap this names rather than hides.
    """
    try:
        listing = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    if listing.returncode != 0:
        return []
    out = []
    for name in listing.stdout.splitlines():
        if not name.endswith(".py"):
            continue
        try:
            blob = subprocess.run(["git", "-C", str(repo), "show", "HEAD:" + name],
                                  capture_output=True, text=True, timeout=60)
        except Exception:
            continue
        if blob.returncode != 0 or "reddit" not in blob.stdout.lower():
            continue
        if _exception_for(Path(name)) or _is_test(Path(name)):
            continue
        for v in violations_in_source(blob.stdout, name):
            v["file"] = "%s!%s" % (repo, name)   # ! marks a blob, not a file
            out.append(v)
    return out


def _is_bare_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    # A NORMAL REPO'S OWN .git DIRECTORY passes the HEAD/objects/refs test, so
    # without this the audit read every checkout's internal object store and
    # reported findings at paths like `consulting/.git!q-consult/...`. Those are
    # the same files it already reads from the working tree, attributed to a
    # directory nobody edits.
    if path.name == ".git":
        return False
    # A bare repo has HEAD/objects/refs at its top level and no .git dir.
    return all((path / n).exists() for n in ("HEAD", "objects", "refs")) \
        and not (path / ".git").exists()


def walk(roots) -> list[dict]:
    out = []
    for root in roots:
        root = Path(root).expanduser()
        if _is_bare_repo(root):
            out.extend(_bare_repo_violations(root))
            continue
        # A directory OF bare repos (the publish mirrors) is the shape that hid
        # three findings, so it is handled explicitly rather than left to the
        # file walk that cannot see into any of them.
        if root.is_dir():
            bares = [c for c in sorted(root.glob("*.git")) if _is_bare_repo(c)]
            for bare in bares:
                out.extend(_bare_repo_violations(bare))
        if root.is_file():
            if not _skip(root, root.parent):
                out.extend(violations_in(root))
            continue
        # A ROOT THE CALLER NAMED IS ALWAYS SCANNED. This used to `continue`
        # when the root was a linked worktree, which made the pre-commit hook a
        # NO-OP everywhere this fleet actually works: lefthook passes
        # `git rev-parse --show-toplevel`, and inside a worktree that IS the
        # worktree, so the only automatic wiring of this rule exited 0 on every
        # commit without opening a file (PR 307 review, MAJOR 1, reproduced:
        # exit 0 in the worktree and exit 1 in the main checkout, same planted
        # file).
        #
        # The skip was written for a different case and still serves it: a
        # worktree found BELOW a parent root is a second copy of a branch that
        # gets audited at its own root, and reporting it twice blames the copy.
        # That case is handled inside the walk. Being handed a path is a
        # different act from finding one.
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            # PER DIRECTORY, not only on the root handed in. Checking the root
            # alone is right when each repo is passed separately and useless when
            # `~/projects` is passed once, because then every checkout under it is
            # just a subdirectory and the check never reaches it. That is exactly
            # how consulting-landing came back a second time after the first fix:
            # the test passed each repo as its own root and the CLI default did
            # not. A guard has to run where the thing it guards against actually
            # appears.
            if here != root and _is_linked_worktree(here):
                dirnames[:] = []
                continue
            if _skip(here, root):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not _skip(Path(dirpath) / d, root)]
            for name in filenames:
                if name.endswith(SUFFIXES):
                    path = Path(dirpath) / name
                    if (not _skip(path, root) and not _is_test(path)
                            and not _exception_for(path)
                            and not _is_vendored_copy(path)):
                        out.extend(violations_in(path))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="*", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    roots = args.roots or [Path.home() / "projects"]
    found = walk(roots)

    if args.json:
        print(json.dumps(found, indent=2))
    else:
        for v in found:
            print("%s:%d  %s\n    %s" % (v["file"], v["line"], v["reason"], v["text"]))
        print("\nStanding exceptions (printed every run, clean or not):")
        for suffix, reason in EXCEPTIONS.items():
            print("  %s\n      %s" % (suffix, reason))
        # SAY WHAT WAS READ. "in live code" was a claim about the whole corpus
        # from a checker that parses Python and nothing else, so a shell or JS
        # Reddit fetcher exits 0 clean under a sentence that implies otherwise
        # (review). The scope belongs in the sentence, not in the docstring.
        print("\n%d non-Arctic Reddit reference(s) in %s files. This checker "
              "parses %s ONLY: a Reddit fetch in shell, JS or any other language "
              "is outside what this number covers."
              % (len(found), ", ".join(SUFFIXES), ", ".join(SUFFIXES)))
        if found:
            print("Arctic Shift is the only sanctioned transport. It lives at "
                  "plugins/kipi-core/reddit_arctic; import it rather than "
                  "building a URL.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
