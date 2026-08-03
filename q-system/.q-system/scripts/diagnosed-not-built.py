#!/usr/bin/env python3
"""Find code that has been DIAGNOSED repeatedly and never CHANGED.

WHY THIS EXISTS (ASK-310, 2026-08-02)

`auto-commit.py` was diagnosed five separate times over a month -- an RCA, a
lesson written three weeks before the damage, a Linear issue carrying a full
Definition of Ready, and multiple spillover items -- and the file was not touched
once between the first diagnosis and the day it split a session across two
branches and cost an hour of misattributed debugging.

That is not "built but not wired", the failure this repo already hunts. It is
"specified and abandoned", and nothing looked for it. The volume of tickets about
one file WAS the signal, and no reader aggregated across the four places those
tickets live, so nobody saw five -- they saw one, four times, months apart.

The founder asked how a finding is "kept". A sentence in a summary is not kept;
that is precisely what failed here, five times. This is the answer: a script that
finds the class, so the next instance surfaces without anyone remembering.

THE RULE

A file is flagged when BOTH hold:
  * two or more DISTINCT diagnosis documents name it, and
  * its last commit predates the earliest of those diagnoses.

Two sources, not one: a single RCA naming a file is a normal, healthy record of
work already done. Two or more, with no code change after the first, is a class
being re-discovered instead of fixed.

HONEST BOUNDARY -- what this does NOT catch:
  * A diagnosis that never names a filename. Prose about "the notify path" is
    invisible here. Naming the file is what makes a finding actionable anyway.
  * A file fixed under a different name, or split. The rename reads as "never
    touched" for the old path.
  * A diagnosis correctly closed as won't-do. The flag means "look", not "bug".
  * Volume alone. Three mentions in one document count once, deliberately.

Exit 0 clean, 1 when something is diagnosed and untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

FILE_RE = re.compile(r"\b([a-zA-Z0-9][a-zA-Z0-9._-]*\.(?:py|sh))\b")
MIN_SOURCES = 2
# A finding from yesterday is work in flight, not an abandoned class. Without
# this the detector reported ci-redrive.py at a ONE-DAY gap alongside
# capability-token.sh at forty-one, and a list that mixes those two teaches the
# reader to skim it -- the same permanently-red-gate failure this session already
# hit twice. The signal is a diagnosis that has had time to be acted on.
STALE_DAYS = 14
# Names that appear as generic references rather than as the subject of a finding.
NOISE = {"setup.py", "__init__.py", "conftest.py"}
STEMS: dict = {}


def run(repo: str, *args) -> str:
    out = subprocess.run(["git", "-C", repo, *args],
                         capture_output=True, text=True, check=False)
    return out.stdout.strip()


def last_commit_iso(repo: str, path: str) -> str:
    return run(repo, "log", "-1", "--format=%cI", "--", path)


def doc_date_iso(repo: str, path: str) -> str:
    """When the diagnosis was recorded. The commit date, not mtime: mtime moves
    when a file is merely touched, and would silently reclassify old findings."""
    return last_commit_iso(repo, path) or ""


def diagnosis_docs(repo: str) -> list:
    docs = []
    for rel in ("q-system/output/rca", "q-system/lessons"):
        d = os.path.join(repo, rel)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".md"):
                docs.append(os.path.join(rel, name))
    return docs


def build_stems(repo: str) -> dict:
    """{stem: extension} for every tracked script, longest first so `auto-commit`
    is preferred over a shorter substring that also matches."""
    out = {}
    for rel in run(repo, "ls-files").splitlines():
        base = os.path.basename(rel)
        if base.endswith((".py", ".sh")) and base not in NOISE:
            stem, dot, ext = base.rpartition(".")
            if len(stem) >= 6:      # short stems match unrelated slugs
                out[stem] = dot + ext
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def mentions_from_docs(repo: str, docs: list) -> dict:
    """{target_file: {source_doc: recorded_date}} -- one entry per doc, so three
    mentions inside one document count once."""
    found: dict = {}
    for rel in docs:
        try:
            text = open(os.path.join(repo, rel), encoding="utf-8",
                        errors="replace").read()
        except OSError:
            continue
        named = {m for m in FILE_RE.findall(text) if m not in NOISE}
        # ALSO match the doc's own slug against a file STEM. Measured while
        # building this: the detector would have MISSED auto-commit.py, the case
        # it exists for. The lesson written three weeks before the damage is
        # `an-auto-commit-to-the-current-branch-strands-unmerged-work.md`, and it
        # names the behaviour, not the filename -- its body contains zero
        # occurrences of "auto-commit.py". Diagnoses are titled by symptom, and a
        # detector that only reads filenames reads only the diagnoses written by
        # someone already holding the file open.
        slug = os.path.basename(rel).rsplit(".", 1)[0]
        for stem in STEMS:
            if stem in slug:
                named.add(stem + STEMS[stem])
        if not named:
            continue
        when = doc_date_iso(repo, rel)
        for target in named:
            found.setdefault(target, {})[rel] = when
    return found


def mentions_from_spillover(repo: str, found: dict) -> None:
    path = os.path.join(repo, ".prd-os", "spillover.jsonl")
    if not os.path.exists(path):
        return
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") != "open":
            continue
        for target in {m for m in FILE_RE.findall(row.get("description") or "")
                       if m not in NOISE}:
            key = f"spillover:{row.get('id')}"
            found.setdefault(target, {})[key] = (row.get("created_at") or "")


def resolve(repo: str, target: str) -> str:
    """Repo-relative path for a bare filename, or "" when it does not exist."""
    hits = run(repo, "ls-files", f"*/{target}", target).splitlines()
    return hits[0] if len(hits) == 1 else ""


def findings(repo: str) -> list:
    global STEMS
    STEMS = build_stems(repo)
    found = mentions_from_docs(repo, diagnosis_docs(repo))
    mentions_from_spillover(repo, found)
    out = []
    for target, sources in sorted(found.items()):
        dated = {s: d for s, d in sources.items() if d}
        if len(dated) < MIN_SOURCES:
            continue
        path = resolve(repo, target)
        if not path:
            continue
        touched = last_commit_iso(repo, path)
        # COUNT DIAGNOSES THAT POSTDATE THE LAST CHANGE, not "was it ever touched
        # after the first one". Measured against the case this exists for:
        # auto-commit.py carried five diagnoses (2026-07-14 .. 08-02) and was
        # edited once on 07-26 for unrelated reasons. The naive rule read that
        # single unrelated commit as "acted on" and filtered the file out -- the
        # detector would have missed the very failure that motivated it. What
        # matters is how many times it was re-diagnosed WITHOUT anyone changing
        # it, which is the definition of a class being re-discovered.
        since = {s: d for s, d in dated.items() if not touched or d > touched}
        if len(since) < MIN_SOURCES:
            continue
        earliest = min(since.values())
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(earliest.replace("Z", "+00:00"))).days
        if age < STALE_DAYS:
            continue          # still in flight, not abandoned
        out.append((target, path, earliest, touched, sorted(since)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    bad = findings(repo)
    if not bad:
        print("diagnosed-not-built: OK -- nothing diagnosed twice and left untouched")
        return 0
    print(f"diagnosed-not-built: {len(bad)} file(s) diagnosed {MIN_SOURCES}+ times "
          f"and NOT changed since.\n")
    for target, path, earliest, touched, sources in bad:
        print(f"  {path}")
        print(f"      first diagnosed {earliest[:10]}, last changed "
              f"{(touched or 'never')[:10]}")
        for s in sources:
            print(f"      - {s}")
    print("\nEach is a class being re-discovered instead of fixed. Build it, or "
          "close the findings as won't-do -- writing it down a sixth time is the "
          "failure this detects.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
