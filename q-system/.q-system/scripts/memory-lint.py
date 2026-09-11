#!/usr/bin/env python3
"""Report-only hygiene sweep over an auto-memory directory.

Pairs with .claude/rules/memory-confidence.md (the supersession + as_of
convention) and .claude/rules/memory-freshness.md (the decay axis). The
validator hook owns the SHAPE of one file at write time; this owns the GRAPH
across the whole corpus, which no single-file hook can see.

    python3 memory-lint.py                       # this project's memory dir
    python3 memory-lint.py <dir>                 # any memory dir
    python3 memory-lint.py --max-age-months 3
    python3 memory-lint.py --strict              # exit 1 on structural findings

What it reports:

  structural (fails under --strict)
    - [[wiki-links]] pointing at a memory name that does not exist
    - superseded_by / supersedes pointing at a memory name that does not exist
    - MEMORY.md index lines pointing at files that do not exist
    - memory files with no index line
    - duplicate `name:` slugs

  advisory (NEVER fails, even under --strict)
    - files missing as_of / status
    - status:current memories whose as_of is older than N months

WHY THE ADVISORY HALF CANNOT FAIL --strict, and do not "tighten" it later
without re-reading this: the ~100 memory files that predate this convention
carry no as_of and no status, so a strict mode red on them would be red on its
whole population from the first run -- the shape that gets a gate switched off,
after which it protects nothing. Staleness is excluded for a second reason: it
goes red with the passage of time and no code change, so a blocking CI check on
it fails builds nobody can fix by editing anything.

NEVER AUTO-FIXES. A memory is a claim about the world; rewriting one from a
script would fabricate provenance. Every finding names the file and the fix, and
a human or an agent makes the edit.

HONEST BOUNDARY: it reads frontmatter and markdown links only. It cannot tell
whether a memory is TRUE, whether a `superseded_by` points at the RIGHT
successor, or whether an as_of date was honestly assigned. A memory that is
current, linked, indexed and completely wrong passes every check here.

stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_conventions import (  # noqa: E402
    LINK_FIELDS,
    as_of_date,
    effective_status,
    parse_frontmatter,
)

INDEX_NAME = "MEMORY.md"
WIKI_LINK_RE = re.compile(r"\[\[([^\]\[]+)\]\]")
MD_LINK_RE = re.compile(r"\]\(([^)\s]+\.md)\)")


# --- locating the corpus ----------------------------------------------------

def default_memory_dir() -> Path:
    """The current project's auto-memory dir.

    Derived exactly as memory-freshness-check.py derives it (project path with
    every '/' turned into '-'). Kept identical on purpose: two derivations of one
    path is how a sweep and a hook end up reading different corpora and both
    reporting clean.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    return Path.home() / ".claude" / "projects" / project_dir.replace("/", "-") / "memory"


def months_ago(today: datetime.date, months: int) -> datetime.date:
    """Calendar-month subtraction with end-of-month clamping.

    Not `today - timedelta(days=30*months)`: a day-count drifts against real
    months, so "6 months" would mean something different in February than in
    July and the same corpus would flip in and out of the report.
    """
    total = (today.year * 12 + (today.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(today.day, [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
                          else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)


class Memory:
    def __init__(self, path: Path, text: str):
        self.path = path
        self.text = text
        self.fm = parse_frontmatter(text) or {}
        declared = (self.fm.get("name") or "").strip()
        self.slug = declared or path.stem
        self.declared_name = declared


def load_corpus(memory_dir: Path):
    memories = []
    for md in sorted(memory_dir.glob("*.md")):
        if md.name == INDEX_NAME:
            continue
        try:
            memories.append(Memory(md, md.read_text()))
        except (IOError, OSError) as exc:
            memories.append(Memory(md, ""))
            sys.stderr.write("memory-lint: unreadable %s (%s)\n" % (md.name, exc))
    return memories


# --- the checks -------------------------------------------------------------

def check_duplicate_slugs(memories):
    by_slug = {}
    for mem in memories:
        by_slug.setdefault(mem.slug, []).append(mem)
    out = []
    for slug, group in sorted(by_slug.items()):
        if len(group) > 1:
            out.append("duplicate name slug %r: %s"
                       % (slug, ", ".join(m.path.name for m in group)))
    return out, set(by_slug)


def resolvable_targets(memories, slugs):
    """A link resolves against a declared `name:` slug OR a bare filename stem.

    Both are accepted because MEMORY.md's own instruction says [[name]] uses the
    `name:` slug, while several existing files were written before that and are
    linked by stem. Accepting one form only would report ~half a real corpus as
    dangling, which is a claim about the linter, not about the corpus.
    """
    return set(slugs) | {m.path.stem for m in memories}


def check_wiki_links(memories, targets):
    out = []
    for mem in memories:
        seen = set()
        for match in WIKI_LINK_RE.finditer(mem.text):
            name = match.group(1).strip()
            if not name or name in targets or name in seen:
                continue
            seen.add(name)
            out.append("%s: [[%s]] resolves to no memory" % (mem.path.name, name))
    return out


def check_supersession_links(memories, targets):
    out = []
    for mem in memories:
        for field in LINK_FIELDS:
            value = (mem.fm.get(field) or "").strip()
            if value and value not in targets:
                out.append("%s: %s: %s resolves to no memory"
                           % (mem.path.name, field, value))
    return out


def check_index(memory_dir: Path, memories):
    """MEMORY.md is an index; both directions of the mapping have to hold."""
    index_path = memory_dir / INDEX_NAME
    if not index_path.exists():
        return ["%s is missing (the index every session loads)" % INDEX_NAME]
    try:
        index_text = index_path.read_text()
    except (IOError, OSError) as exc:
        return ["%s is unreadable (%s)" % (INDEX_NAME, exc)]

    linked = set()
    out = []
    for match in MD_LINK_RE.finditer(index_text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://")):
            continue
        linked.add(target)
        if not (memory_dir / target).exists():
            out.append("%s: index line points at %s, which does not exist"
                       % (INDEX_NAME, target))
    for mem in memories:
        if mem.path.name not in linked:
            out.append("%s has no line in %s" % (mem.path.name, INDEX_NAME))
    return out


def check_missing_fields(memories):
    out = []
    for mem in memories:
        missing = [f for f in ("status", "as_of") if f not in mem.fm]
        if missing:
            out.append("%s: no %s (grandfathered; add on next edit)"
                       % (mem.path.name, " and no ".join(missing)))
    return out


def check_stale(memories, cutoff: datetime.date, months: int):
    out = []
    for mem in memories:
        if effective_status(mem.fm) != "current":
            continue
        stamped = as_of_date(mem.fm)
        if stamped is not None and stamped < cutoff:
            out.append("%s: status current but as_of %s is older than %d months "
                       "(re-verify, then bump as_of or supersede it)"
                       % (mem.path.name, stamped.isoformat(), months))
    return out


# --- reporting --------------------------------------------------------------

def render(section, findings):
    if not findings:
        return 0
    print("\n%s (%d)" % (section, len(findings)))
    for line in findings:
        print("  - %s" % line)
    return len(findings)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("memory_dir", nargs="?", default=None,
                    help="memory directory to sweep (default: this project's)")
    ap.add_argument("--max-age-months", type=int, default=6,
                    help="status:current memories older than this are reported (default 6)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a STRUCTURAL finding exists (advisory findings never fail)")
    ap.add_argument("--today", default=None,
                    help="YYYY-MM-DD override for the age cutoff; the tests pass it so "
                         "the stale case is not time-dependent and cannot rot")
    args = ap.parse_args(argv)

    memory_dir = Path(args.memory_dir) if args.memory_dir else default_memory_dir()
    if not memory_dir.is_dir():
        print("memory-lint: no memory directory at %s (nothing to sweep)" % memory_dir)
        return 0

    if args.today:
        try:
            today = datetime.date.fromisoformat(args.today)
        except ValueError:
            sys.stderr.write("memory-lint: --today %r is not YYYY-MM-DD\n" % args.today)
            return 2
    else:
        today = datetime.date.today()
    cutoff = months_ago(today, args.max_age_months)

    memories = load_corpus(memory_dir)
    dup_findings, slugs = check_duplicate_slugs(memories)
    targets = resolvable_targets(memories, slugs)

    print("memory-lint: %d memory file(s) in %s" % (len(memories), memory_dir))

    structural = 0
    structural += render("DANGLING WIKI LINKS", check_wiki_links(memories, targets))
    structural += render("DANGLING SUPERSESSION LINKS",
                         check_supersession_links(memories, targets))
    structural += render("INDEX MISMATCH", check_index(memory_dir, memories))
    structural += render("DUPLICATE NAME SLUGS", dup_findings)

    advisory = 0
    advisory += render("STALE (status current, as_of older than %d months)" % args.max_age_months,
                       check_stale(memories, cutoff, args.max_age_months))
    advisory += render("MISSING as_of / status", check_missing_fields(memories))

    print("\nstructural: %d   advisory: %d" % (structural, advisory))
    if structural and args.strict:
        print("strict mode: exiting 1 on structural findings")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
