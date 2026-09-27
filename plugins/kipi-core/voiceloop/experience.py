#!/usr/bin/env python3
"""Find the author's OWN material that matches an idea. The experience lane.

why this exists (author-directed 2026-08-24, verbatim: "when I say write me a post
about something, you find what it's about from my experience through the knowledge
base, use my voice, and then build that into one of these post archetypes"):

The idea lane took his typed sentence and nothing else. A corpus directory holds a
`scars.md` that is the verified, audience-mapped library of what he actually did at
the employers he worked for, and nothing reached for it. The instance rule that
governs first-person output already said any such draft is written only after
reading that file, and records the defect behind the rule: a comment draft cleared
all fourteen output gates with ZERO violations while using none of his experience,
because every one of those gates is a NEGATIVE check. The employer gate blocks a
FALSE employer claim and nothing anywhere requires a TRUE one.

**A clean gate run is not evidence a draft used his material.** This module is the
positive half.

## THE CORPUS DIRECTORY IS HANDED IN. There is no default and there must not be.

Every public function here takes the corpus directory, or the explicit file paths
inside it, from its caller. A default resolved from `__file__` would put ONE
author's corpus on everyone's machine the moment this package ships fleet-wide,
which is the same failure `voice_ref` refuses by carrying no default corpus path at
all. The instance adapter binds its own directory; the engine binds nothing.

## What it may hand to a writer, and what it may never hand to one

`scars.md` rows carry a flag. `public-safe` rows are cleared for publication.
`permission-required` rows name people whose OK has not been obtained.
`_PUBLISHABLE` is an ALLOWLIST, not a blocklist: a row whose flag this module does
not recognise is treated as not clearing, so a new flag spelling fails closed
instead of publishing something uncleared.

The rows also carry PROVENANCE notes explaining which thesis a story maps to. Those
notes are for a human reading the file. The row parser returns the quoted material
and the flag and drops the rest, because the note is where private brand names live.
That stripping is the primary control; the instance's own separation gate in the
output stack is the backstop for when this stripping is wrong, and both are tested.

## Retrieval is deliberately dumb

Token overlap against the row's title and story text, stopworded, ranked. No
embedding, no model call. A model call here would make the one deterministic half of
the lane non-deterministic and would put a second unreviewed prompt between his idea
and his post. If the matching is too crude, the fix is better rows, not a smarter
matcher: a wrong row surfaced to him costs one glance, and he is the one who picks.
"""
from __future__ import annotations

import json
import os
import re

# The three corpus files, by name. The DIRECTORY is the caller's; the layout inside
# it is this module's contract, so a caller cannot half-bind a corpus by naming two
# of three files and silently reading a third from somewhere else.
SCARS_FILE = "scars.md"
BUILT_FILE = "built.md"
MINED_FILE = "built-mined.jsonl"


class CorpusNotBound(ValueError):
    """No corpus directory was supplied, so there is nothing to read.

    why this is loud rather than a fallback (2026-09-05, the package extraction):
    the module this was lifted from resolved all three paths from `__file__`. In an
    instance that is correct and invisible; in a shared package it silently points
    every founder at whichever corpus happens to sit beside the code. A refusal is
    the only answer that cannot be wrong quietly. A caller that wants a corpus
    passes one.
    """


def corpus_paths(corpus_dir):
    """The three corpus file paths inside `corpus_dir`. REFUSES a missing dir.

    Deliberately does not check that the files exist: the three loaders each return
    [] for a file that is not there, and that degradation is a decision made in
    their own docstrings. What is refused here is the absence of an ANSWER to
    "whose corpus", which no loader can degrade its way out of.
    """
    if not corpus_dir:
        raise CorpusNotBound(
            "experience needs a corpus directory and has no default. Pass the "
            "directory holding %s, %s and %s."
            % (SCARS_FILE, BUILT_FILE, MINED_FILE))
    return {
        "scars": os.path.join(corpus_dir, SCARS_FILE),
        "built": os.path.join(corpus_dir, BUILT_FILE),
        "mined": os.path.join(corpus_dir, MINED_FILE),
    }


def _resolve(corpus_dir, scars_path=None, built_path=None, mined_path=None):
    """Per-file overrides on top of a corpus directory.

    The overrides exist for the benchmark and for tests, which build one file at a
    time. `corpus_dir` is still required even when all three are given, because a
    caller that can name three files can name the directory, and making it optional
    reopens exactly the "no default" hole this module was moved to close.
    """
    paths = corpus_paths(corpus_dir)
    return (scars_path or paths["scars"],
            built_path or paths["built"],
            mined_path or paths["mined"])


# `| **Item** | flag | The specific |`  -- the flagged tables.
_BUILT_ROW = re.compile(
    r"^\|\s*\*\*(?P<title>.+?)\*\*\s*\|(?P<flags>[^|]*)\|(?P<body>.*?)\|\s*$")

# `| **Trace** | The specific |` -- the lineage table, which has NO per-row flag
# column. Its section prose may say the engagement behind a row is confidential.
# Prose above a table is not a clearance, so an unflagged row yields flags=[] and
# fails the `_PUBLISHABLE` allowlist like any other unrecognised flag. It still
# reaches the AUTHOR in the card, marked, exactly as a permission-required row does.
_BUILT_ROW_UNFLAGGED = re.compile(
    r"^\|\s*\*\*(?P<title>.+?)\*\*\s*\|(?P<body>[^|]*)\|\s*$")

# Inline markdown carried straight into a writer prompt reads as formatting the model
# should imitate. The words are the material; the emphasis is not.
_MD_NOISE = re.compile(r"\*\*|`")

# ALLOWLIST. An unrecognised flag does not clear. See the docstring.
_PUBLISHABLE = ("public-safe",)

_STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have how i if in into is it its of on
or that the their them then there these they this to was were what when which who will
with you your we our us my me not no do does did can could should would about after
before over under more most some any than too very just so such own same other
""".split())

# `| **Title** | flags | audience | body |`
_ROW = re.compile(r"^\|\s*\*\*(?P<title>.+?)\*\*\s*\|(?P<flags>[^|]*)\|(?P<audience>[^|]*)\|(?P<body>.*?)\|\s*$")

# A row whose title is still a template placeholder is not a story yet.
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")

# `### Google` / `### Meta` ... the company each row below it belongs to.
_SECTION = re.compile(r"^###\s+(?P<name>.+?)\s*$")

# Only these carry an employer claim into a post. The corpus file also has "Adjacent
# Credibility (NOT Companies)" sections, and attributing a row to one of those would
# manufacture an employment claim out of a section heading that explicitly says it is
# not one. An unrecognised heading yields NO company, and the writer is told nothing
# rather than told something invented.
#
# KNOWN GAP, carried deliberately into the package (2026-09-05): this list is one
# author's employers, so it is DATA sitting in engine code. It was not parameterised
# in the move because doing so changes what `load` returns, and the move's whole
# acceptance was that retrieval stays bit-identical. Captured as a follow-up rather
# than smuggled into a file move.
_REAL_EMPLOYERS = ("Google", "Meta", "LinkedIn", "ElevenLabs")

# These terms describe a writing request, not the material behind it. Keeping them
# out of the match set prevents a single generic word from selecting real work.
_MATCH_NOISE = frozenset("make team teams voice".split())

# One shared term is not enough evidence to put a row in a writer's prompt.
MIN_MATCH_SCORE = 2

# A MINED row needs three, and the difference is not a preference. A hand-written row
# is a distilled claim of a few dozen words that somebody chose to write down, so two
# shared terms is real signal. A mined row is a paragraph lifted whole out of a
# docstring: ~80 tokens, of which "file", "script", "built" and "function" are
# ordinary vocabulary. Measured the hour the mined corpus landed: an idea about an
# executive-function skill returned three shell scripts, matched on {file, script} and
# {built, function}, ranked above everything because 322 mined rows raised the odds of
# a generic collision roughly twentyfold over the 19 hand-written ones. Same matcher,
# different base rate. This is the corpus growing, not the matcher breaking.
MIN_MINED_MATCH_SCORE = 3


def _tokens(text):
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower())
            if word not in _STOPWORDS and word not in _MATCH_NOISE and len(word) > 2}


def _quoted(body):
    """The QUOTED story inside a row's body, or "" when the row has none.

    The quote is the publishable material. Everything outside it is the provenance
    note, which is where private references live.

    FAILS CLOSED, and it did not at first (caught 2026-08-24 by running the parser
    over the real file instead of trusting it). The first version fell back to the
    raw body when a row carried no quotation, and a career-arc row was exactly that
    shape: an unquoted arrow list of employers ending in a private brand name, plus
    an editorial note about which posts to use it in.

    So the primary control handed a private brand name and an editorial note straight
    to the writer, and only the output stack's separation gate stood between that and
    a published post. A row with no quotation has no cleared extract. It gets none,
    and `reference_section` drops it. It still reaches the AUTHOR in the card by
    title, because a story he has to phrase himself is still one worth surfacing.
    """
    quotes = re.findall(r'"([^"]+)"', body or "")
    if not quotes:
        return ""
    return max(quotes, key=len).strip()


def load(path):
    """Every scar row in the file at `path`. Returns [] if missing or unreadable.

    Never raises on the READ: a drafting lane that dies because a reference file
    moved is worse than one that drafts without the reference and says so. The path
    itself is required, which is a different question and is answered loudly.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return []
    rows = []
    company = ""
    for line in lines:
        section = _SECTION.match(line.strip())
        if section:
            name = section.group("name").strip()
            company = name if name in _REAL_EMPLOYERS else ""
            continue
        match_row = _ROW.match(line.strip())
        if not match_row:
            continue
        title = match_row.group("title").strip()
        if _PLACEHOLDER.search(title) or _PLACEHOLDER.search(match_row.group("body")):
            continue
        flags = [f.strip().lower()
                 for f in match_row.group("flags").split(",") if f.strip()]
        rows.append({
            "title": title,
            "flags": flags,
            "publishable": any(f.startswith(_PUBLISHABLE) for f in flags),
            "audience": [a.strip()
                         for a in match_row.group("audience").split(",") if a.strip()],
            "company": company,
            "story": _quoted(match_row.group("body")),
            "kind": "scar",
        })
    return rows


def load_built(path):
    """Every row in the built file. Same contract as `load`: never raises, [] on trouble.

    The BODY is the material here, and that is the one real difference from the scar
    parser. Scar rows mix a quotation with a provenance note naming the thesis it maps
    to, which is why `_quoted` exists and strips a row down to the quotation. The built
    file carries no such notes -- its "What NOT to say" section keeps client names,
    private repo names and the employer claim out of the rows themselves -- so quoting
    would throw the material away and return a fragment. The output stack's separation
    gate remains the backstop either way.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if line.startswith("|---") or _PLACEHOLDER.search(line):
            continue
        hit = _BUILT_ROW.match(line)
        flags = []
        if hit:
            flags = [f.strip().lower() for f in hit.group("flags").split(",") if f.strip()]
        else:
            hit = _BUILT_ROW_UNFLAGGED.match(line)
            if not hit:
                continue
        body = _MD_NOISE.sub("", hit.group("body")).strip()
        if not body:
            continue
        rows.append({
            "title": _MD_NOISE.sub("", hit.group("title")).strip(),
            "flags": flags,
            "publishable": bool(flags) and any(f.startswith(_PUBLISHABLE) for f in flags),
            "audience": [],
            # DELIBERATELY EMPTY. A built item is a claim about his own work, not about
            # an employer, and `reference_section` prints "At <company>: " whenever this
            # is set. Attributing a mechanism he built for his own practice to a past
            # employer would manufacture exactly the employment claim the employer gate
            # cannot see.
            "company": "",
            "story": body,
            "kind": "built",
        })
    return rows


def _mined_row(row):
    """One extractor row in the shape every other row in this module has.

    `kind` is "built" and not a third kind on purpose. A mined row and a hand-written
    built row are the same KIND of authority -- a mechanism in his own system -- so the
    tie-break in `match` and the one-source-per-output rule both keep working without
    learning a new name. `origin` records which door it came through, for the card only.
    """
    flag = (row or {}).get("flag")
    flags = [flag] if flag else []
    return {
        "title": (row or {}).get("title", ""),
        "flags": flags,
        # SAME ALLOWLIST as everything else here. A row whose flag this module does not
        # recognise -- including a row the extractor could not classify at all, which it
        # writes as null -- does not clear.
        "publishable": bool(flags) and any(f.startswith(_PUBLISHABLE) for f in flags),
        "audience": [],
        # Deliberately empty, for the reason `load_built` gives: a mechanism he built for
        # his own practice is not work done at an employer.
        "company": "",
        "story": (row or {}).get("story", ""),
        "kind": "built",
        "origin": "mined",
        "where": "/".join(x for x in [(row or {}).get("repo"),
                                      (row or {}).get("path")] if x),
    }


def load_mined(path):
    """Every mined row at `path`. Same contract as `load`: never raises, [] on trouble.

    A malformed LINE is skipped rather than killing the read. The alternative is that
    one bad row silently removes his entire work corpus from every draft, and the lane
    would look identical to the day before this module could see it.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        row = _mined_row(raw)
        if row["title"] and row["story"]:
            rows.append(row)
    return rows


def match(idea_text, corpus_dir, limit=3, publishable_only=True,
          scars_path=None, built_path=None, mined_path=None):
    """Rows ranked by token overlap with the idea. Best first, empty when nothing hits.

    `corpus_dir` is POSITIONAL AND REQUIRED. Calling `match(idea)` is a TypeError and
    `match(idea, None)` is a `CorpusNotBound`; neither silently reads a corpus that
    happens to sit beside this file. See the module docstring.

    `publishable_only` defaults True and every writer path uses the default. The
    parameter exists so a test can prove the filter is doing work rather than matching
    nothing anyway.
    """
    scars, built, mined = _resolve(corpus_dir, scars_path, built_path, mined_path)
    wanted = _tokens(idea_text)
    if not wanted:
        return []
    scored = []
    for row in list(load(scars)) + list(load_built(built)) + list(load_mined(mined)):
        if publishable_only and not row["publishable"]:
            continue
        overlap = wanted & _tokens(f"{row['title']} {row['story']}")
        floor = (MIN_MINED_MATCH_SCORE if row.get("origin") == "mined"
                 else MIN_MATCH_SCORE)
        if len(overlap) >= floor:
            scored.append((len(overlap), sorted(overlap), row))
    # BUILT WINS A TIE (author-directed 2026-09-04). On a post about his work the
    # credential is the mechanism and its number; the witnessed story is the weaker
    # fit, and the two are never equally right for one draft.
    scored.sort(key=lambda item: (-item[0], item[2].get("kind") != "built",
                                  item[2]["title"]))
    # ONE SOURCE PER OUTPUT, and it is the top row's source that decides. The instance
    # rule: never one of each in the same piece, because two stacked reads as a
    # portfolio tour. Filtering here rather than in `reference_section` means the trail
    # and the card he reads agree with the prompt the writer got, instead of showing him
    # a match the writer never saw.
    if scored:
        winner = scored[0][2].get("kind")
        scored = [item for item in scored if item[2].get("kind") == winner]
    return [dict(row, matched_on=terms, score=score)
            for score, terms, row in scored[:limit]]


def reference_section(matches):
    """The matched material as text a writer may be shown. Publishable rows only.

    Returns "" for no matches, so a lane with nothing to offer renders the prompt it
    rendered before this module existed.

    Belt and braces: `match()` already filters, and this filters AGAIN on the way out.
    The two filters are not redundant. This function is public and a future caller
    could hand it rows from somewhere else.
    """
    # BOTH conditions. `publishable` is the row's own clearance flag; `story` is
    # non-empty only when a cleared quotation was actually extracted. A row can be
    # public-safe and still have no quotable extract (see `_quoted`), and handing the
    # writer an empty bullet is the least bad of the wrong answers there.
    rows = [row for row in (matches or [])
            if row.get("publishable") and (row.get("story") or "").strip()]
    if not rows:
        return ""
    # The header names which library these came from, because the two carry different
    # kinds of authority and a writer told "his own experience" about a mechanism he
    # built will reach for a career framing that is not in the row.
    if all(row.get("kind") == "built" for row in rows):
        out = ["WHAT HE BUILT (real, verified, cleared for publication; use it only if "
               "it fits the idea, and never restate it as a quotation). These are "
               "mechanisms in his own systems. They are NOT work done at an employer, "
               "so never attach a company name to one:"]
    else:
        out = ["HIS OWN EXPERIENCE (real, verified, cleared for publication; use it only "
               "if it fits the idea, and never restate it as a quotation). The company "
               "named on a line is where it happened; do not attribute it anywhere else:"]
    # THE EMPLOYER IS NAMED, not left to be inferred (2026-08-24, found in review).
    # `_quoted` strips a row to its quotation, and the quotations do not carry the
    # company. So the writer was handed a real story with the employer removed and
    # guessed one. It guessed right in the observed run and there is nothing that would
    # have caught a wrong guess: the employer gate blocks a forbidden ROLE phrase paired
    # with a KNOWN employer, so a company he never worked at is invisible to it ("four
    # teams at Amazon" returns clean, verified 2026-08-24). Removing the guess is cheaper
    # and safer than widening that gate, whose blast radius is every post in the engine.
    for row in rows:
        prefix = f"At {row['company']}: " if row.get("company") else ""
        out.append(f"- {prefix}{row['story']}")
    return "\n".join(out)


def card_matches(idea_text, corpus_dir, limit=3, scars_path=None,
                 built_path=None, mined_path=None):
    """The card's own door into retrieval, and the ONLY caller that asks for the
    rows a writer may not see.

    why it is separate (2026-09-04): `match()` defaults to `publishable_only=True` and
    every writer path uses that default, so the "PERMISSION REQUIRED" branch below was
    unreachable in production -- a confidential row was mined, labelled, stored, and
    then shown to nobody. The contract is that such a row NEVER reaches the writer and
    ALWAYS reaches the author, marked. Half of that contract needs a door of its own.
    """
    return match(idea_text, corpus_dir, limit=limit, publishable_only=False,
                 scars_path=scars_path, built_path=built_path, mined_path=mined_path)


def _flag_label(row):
    """The row's OWN flag, not a boolean rendered as a phrase.

    "PERMISSION REQUIRED" is right for a row naming someone whose OK has not been
    obtained. It is wrong for a confidential mechanism, where no permission is coming
    and the answer is to describe the pattern without the engagement. Showing him the
    same words for both hides which one he is looking at.
    """
    if row.get("publishable"):
        return "public-safe"
    flags = [f for f in (row.get("flags") or []) if f]
    return flags[0] if flags else "PERMISSION REQUIRED"


def card_lines(matches):
    """What to show the AUTHOR in the terminal: the title, the flag, and why it matched.

    Includes non-publishable rows he may want to use with permission, clearly marked,
    because the card is his own terminal and a story he cannot publish today is still
    one he can ask about.
    """
    lines = []
    for row in matches or []:
        flag = _flag_label(row)
        terms = ", ".join(row.get("matched_on") or [])
        where = f" @ {row['company']}" if row.get("company") else ""
        # Which library it came from, so a glance tells him whether he is being offered
        # something he witnessed or something he built.
        source = "built" if row.get("kind") == "built" else "scar"
        # WHERE it came from, for a mined row only. A hand-written built row reads as a
        # claim; a mined row is a quotation from one file, and the file is how he checks
        # it in ten seconds instead of trusting the extractor.
        origin = f" {row['where']}" if row.get("origin") == "mined" and row.get("where") else ""
        lines.append(
            f"{row['title']}{where} [{source}, {flag}{origin}] (matched on: {terms})")
    return lines
