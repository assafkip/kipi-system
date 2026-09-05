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
                               Recognised by the assignment or key it sits in,
                               not by trust: `url`, `permalink`, `link`, `href`,
                               `BASE`, `display`.

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
import subprocess
import sys
from pathlib import Path

ALLOWED_HOSTS = ("arctic-shift.photon-reddit.com", "api.pullpush.io")

# A display link is allowed only where it is plainly a link. The name the literal
# is bound to (or the dict key it answers) has to say so.
DISPLAY_NAMES = ("url", "permalink", "link", "href", "base", "display",
                 "author_url", "thread_url", "source_url", "profile")

# A DENYLIST that names a host is the opposite of a violation: it is this rule
# being enforced somewhere else. `browser_session_health.forbidden_probe_hosts`
# was the first false positive this audit produced, and a checker that flags the
# guard it agrees with is a checker people switch off.
DENYLIST_NAMES = ("forbidden", "blocked", "denied", "banned", "retired",
                  "refuse", "reject", "deprecated", "never", "not_allowed",
                  "bad_hosts", "skip")

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


def _is_vendored_copy(path: Path, root) -> bool:
    text = str(path.resolve())
    root = str(Path(root).expanduser().resolve())
    if Path(root).name == "kipi-system":
        return False
    if not text.startswith(root + os.sep):
        return False
    parts = Path(text[len(root) + 1:]).parts
    return any(part in VENDORED for part in parts)


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


def _skip(path: Path) -> bool:
    text = str(path)
    return any(part in text for part in SKIP_DIR_PARTS)


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
        if "reddit" not in low:
            continue
        if any(host in low for host in ALLOWED_HOSTS):
            continue

        why = None
        label_early = (labels.get(id(node)) or "").lower()
        if any(name in label_early for name in DENYLIST_NAMES + DATA_NAMES):
            continue
        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in low:
                why = bad
                break
        if why is None and "reddit.com" in low:
            label = (labels.get(id(node)) or "").lower()
            is_display = any(name in label for name in DISPLAY_NAMES)
            # WHAT IT IS, not what it is called. The name-based rules were
            # doing this job and doing it badly in both directions: exempting
            # "sites" hid a live /user/<u>/about.json in a published repo, and
            # un-exempting it then flagged the display link sitting beside it.
            # A URL either names a machine endpoint or it names a page a person
            # opens, and that is readable from the URL.
            looks_like_an_endpoint = (
                ".json" in low or ".rss" in low or "/api/" in low
                or "/search" in low or "?" in low
                # a listing feed, with or without a suffix
                or any(seg in low for seg in ("/new/", "/hot/", "/top/",
                                              "/new.", "/hot.", "/top.",
                                              "/rising/", "/controversial/"))
            )
            # An endpoint is a finding regardless of what it is called. A
            # non-endpoint reddit.com URL is a link a human opens, and the
            # default for those is now CLEAN rather than suspicious. That is a
            # deliberate loosening: FORBIDDEN_SUBSTRINGS still catches
            # old.reddit.com, oauth.reddit.com, /api/ and the trudax actor
            # absolutely, so the loosened half is only "a www.reddit.com URL
            # with no endpoint shape", which is exactly what a profile or a
            # permalink looks like.
            if looks_like_an_endpoint:
                why = "reddit.com endpoint"
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
            if not _skip(root):
                out.extend(violations_in(root))
            continue
        if _is_linked_worktree(root):
            continue
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
            if _skip(here):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not _skip(Path(dirpath) / d)]
            for name in filenames:
                if name.endswith(SUFFIXES):
                    path = Path(dirpath) / name
                    if (not _skip(path) and not _is_test(path)
                            and not _exception_for(path)
                            and not _is_vendored_copy(path, root)):
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
        print("\n%d non-Arctic Reddit reference(s) in live code." % len(found))
        if found:
            print("Arctic Shift is the only sanctioned transport. It lives at "
                  "plugins/kipi-core/reddit_arctic; import it rather than "
                  "building a URL.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
