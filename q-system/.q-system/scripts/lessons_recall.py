#!/usr/bin/env python3
"""Retrieval over the whole lessons corpus, so a lesson can be FOUND rather than listed.

## Why the corpus was not compounding (measured 2026-08-11)

`q-system/hooks/lessons-index.py` injects lesson TITLES at session start, sorted newest
first, capped at 20. Measured against the live corpus that day:

    122 lessons
     20 surfaced, always the 20 most recent
    102 never surfaced at all
        anything dated before 2026-08-05 was permanently invisible

So the mechanism was recency-ranked, title-only, and evicting: writing lesson 123 pushed
lesson 103 out of view for good. A title is also not a lesson, so even the 20 that showed
arrived as pointers nobody opened.

That produces a self-reinforcing decay, and the corpus already shows the damage. Pairwise
cosine similarity over the 7,381 pairs found 14 above 0.25, including a pair at 0.96 that
is the same lesson written twice, and further pairs at 0.50, 0.44, 0.41 and 0.40 that each
say one thing in two files. Nobody duplicated carelessly: a session writing a lesson could
not see the 102 it was not shown, so it wrote one that already existed, which evicted
another, which made the next duplicate likelier.

## What this provides

Retrieval and de-duplication, over ALL of it, with no cap and no recency bias:

    lessons_recall.py search "<what you are about to do>"   # the lessons that apply
    lessons_recall.py similar <path-to-a-draft-lesson>      # what already says this
    lessons_recall.py duplicates [--threshold 0.30]         # corpus health
    lessons_recall.py stats                                 # size, coverage, oldest

`similar` is the compounding half. Run it BEFORE writing a lesson: if something scores
above MERGE_THRESHOLD the corpus already holds that idea, and the right move is to
strengthen that file rather than add another. Growth by merge is compounding; growth by
append is a pile.

Pure stdlib tf-idf on purpose. No embedding service, no network, no key: a recall path
that can fail to be available is a recall path that gets skipped.
"""
from __future__ import annotations

import argparse
import collections
import glob
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.join(HERE, "..", "..")
LESSONS = os.path.join(QROOT, "lessons")

#: Above this, two lessons are the same idea and the second should merge into the first.
#: Calibrated on the live corpus: the 0.96 pair is a literal duplicate, 0.50 and 0.44 are
#: one idea in two files, and the next band down (0.27-0.34) is genuinely related but
#: distinct. 0.35 sits in that gap.
MERGE_THRESHOLD = 0.35

_STOP = set(
    "the a an and or of to in is it that this be are was for on with as not you your "
    "they them their we our if by from at what when how why which who all any can may "
    "must never always more most one two do does did has have had been being so than "
    "then there these those some such no nor only own same too very will just should "
    "would could into out up down over under again further once here about against "
    "between during before after above below its has".split())


def _tokens(text):
    return [w for w in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if w not in _STOP]


def _body(path):
    """Everything after the frontmatter. The title alone is what failed before."""
    raw = open(path, encoding="utf-8").read()
    parts = raw.split("---", 2)
    return parts[-1] if len(parts) == 3 else raw


def title_of(path):
    raw = open(path, encoding="utf-8").read()
    found = re.search(r"^title:\s*(.+)$", raw, re.M)
    return found.group(1).strip() if found else os.path.basename(path)


def corpus(lessons_dir=None):
    directory = lessons_dir or LESSONS
    return sorted(p for p in glob.glob(os.path.join(directory, "*.md"))
                  if os.path.basename(p) != "README.md")


class Index:
    """tf-idf over lesson BODIES. Built per call; the corpus is small and disk is cheap."""

    def __init__(self, paths):
        self.paths = list(paths)
        self.counts = {p: collections.Counter(_tokens(_body(p))) for p in self.paths}
        self.df = collections.Counter()
        for counted in self.counts.values():
            for word in counted:
                self.df[word] += 1
        self.n = max(1, len(self.paths))
        self.vectors = {p: self._weigh(c) for p, c in self.counts.items()}

    def _weigh(self, counted):
        # df > 1 only: a term appearing in exactly one lesson carries no similarity signal
        # and dominates the vector when it is a proper noun.
        return {w: (1 + math.log(n)) * math.log(self.n / self.df[w])
                for w, n in counted.items() if self.df.get(w, 0) > 1}

    def vector_for_text(self, text):
        return self._weigh(collections.Counter(_tokens(text)))

    @staticmethod
    def cosine(a, b):
        shared = set(a) & set(b)
        if not shared:
            return 0.0
        num = sum(a[k] * b[k] for k in shared)
        da = math.sqrt(sum(v * v for v in a.values()))
        db = math.sqrt(sum(v * v for v in b.values()))
        return num / (da * db) if da and db else 0.0

    def rank(self, vector, exclude=None):
        scored = [(self.cosine(vector, self.vectors[p]), p)
                  for p in self.paths if p != exclude]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(s, p) for s, p in scored if s > 0]


def search(query, k=5, lessons_dir=None):
    index = Index(corpus(lessons_dir))
    return index.rank(index.vector_for_text(query))[:k]


def similar_to(path, k=5, lessons_dir=None):
    """Nearest existing lessons to a draft. The de-duplication half."""
    paths = corpus(lessons_dir)
    index = Index(paths + ([path] if path not in paths else []))
    return index.rank(index.vectors[path], exclude=path)[:k]


def duplicates(threshold=MERGE_THRESHOLD, lessons_dir=None):
    index = Index(corpus(lessons_dir))
    out = []
    paths = index.paths
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            score = index.cosine(index.vectors[paths[i]], index.vectors[paths[j]])
            if score >= threshold:
                out.append((score, paths[i], paths[j]))
    out.sort(reverse=True)
    return out


def _print(rows):
    for score, path in rows:
        print(f"  {score:.2f}  {title_of(path)}")
        print(f"        {os.path.relpath(path, QROOT)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    find = sub.add_parser("search", help="lessons relevant to a description of the work")
    find.add_argument("query")
    find.add_argument("-k", type=int, default=5)

    near = sub.add_parser("similar", help="what the corpus already says; run BEFORE writing")
    near.add_argument("path")
    near.add_argument("-k", type=int, default=5)

    dupes = sub.add_parser("duplicates", help="pairs that should be merged")
    dupes.add_argument("--threshold", type=float, default=MERGE_THRESHOLD)

    sub.add_parser("stats", help="corpus size and coverage")

    args = parser.parse_args(argv)

    if args.cmd == "search":
        rows = search(args.query, args.k)
        if not rows:
            print("  no lesson matches that. It may genuinely be new.")
        _print(rows)
        return 0

    if args.cmd == "similar":
        rows = similar_to(os.path.abspath(args.path), args.k)
        _print(rows)
        if rows and rows[0][0] >= MERGE_THRESHOLD:
            print()
            print(f"  MERGE: {rows[0][0]:.2f} against an existing lesson. The corpus "
                  f"already holds this idea.")
            print("  Strengthen that file instead of adding another. Growth by merge is "
                  "compounding; growth by append is a pile.")
            return 2
        return 0

    if args.cmd == "duplicates":
        rows = duplicates(args.threshold)
        print(f"{len(rows)} pair(s) at or above {args.threshold}")
        for score, a, b in rows:
            print(f"  {score:.2f}  {os.path.basename(a)}")
            print(f"        {os.path.basename(b)}")
        return 0

    paths = corpus()
    dates = sorted(re.search(r"^date:\s*(\S+)", open(p, encoding="utf-8").read(), re.M)
                   .group(1) for p in paths
                   if re.search(r"^date:\s*(\S+)", open(p, encoding="utf-8").read(), re.M))
    print(f"  lessons          {len(paths)}")
    print(f"  oldest / newest  {dates[0] if dates else '?'} / {dates[-1] if dates else '?'}")
    print(f"  duplicate pairs  {len(duplicates())} at or above {MERGE_THRESHOLD}")
    print("  reachable        all of them, via search; retrieval is not capped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
