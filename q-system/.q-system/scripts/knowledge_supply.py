#!/usr/bin/env python3
"""knowledge_supply: the read side of the instance knowledge base.

Given a prompt, resolve the entities it names and the class of task it is, read
the instance's own stores through the source classes the manifest declares for
that class, and hand back a bundle of VERBATIM excerpts (each with path and line,
a date and a status label) plus a receipt that names every declared source as
searched, empty, or absent. The hook `knowledge-inject.py` renders the bundle
into UserPromptSubmit context. Tests: test_knowledge_supply.py.

WHY (knowledge-supply plan, 2026-09-04): every store here already had a writer
and a guard. kb-graph-guard.py blocks a session close when entity files outgrow
graph.jsonl, commitments.py drops any promise it cannot quote verbatim, and the
decision log refuses an entry without an origin tag. NOTHING READ ANY OF IT on
the prompt path. Measured: 0 bytes injected for "who at 14 Peaks did we talk to
and what did they push back on". A store with no retrieval trigger is folklore
with a timestamp (lesson: a-knowledge-store-with-no-retrieval-trigger).

WHY A MANIFEST AND A RECEIPT, not just a grep: "I did not find it" and "I never
searched the source it lived in" are different sentences. The manifest declares
the source classes a task class needs; the receipt records each one as present,
empty, or absent; the first line of the payload says FULL or PARTIAL and names
what was missing. That is the check from the lesson "assert what went into a
composed artifact, not just that it came out valid": every declared input gets
a status, and a missing one is a recorded fact, never a silent omission.

WHY VERBATIM AND NEVER A SUMMARY: a summary is a copy that goes stale while the
source moves. This module has no summarize path; test_every_excerpt_is_verbatim
asserts each excerpt is a substring of its source. The model opens the src when
it matters; read-first-gate.py already teaches that shape.

WHY SINGLE-TOKEN GRAPH ENTITIES NEVER FIRE ALONE: the largest instance's graph subjects
include "Mark", "Lisa", "David". A hook that fires on "mark the file as done"
is noise, and every previous guard that produced noise got switched off
(kb-graph-guard.py docstring). Identifier kinds the manifest lists (client
slugs, meeting keys) fire on a whole-word match; multi-token names fire on a
phrase match; a bare first name fires only mid-sentence and only when it is the
first token of exactly one multi-token entity (measured from the replay, commit
184fcfbc), never at the start of a sentence, a line or a bullet. The misses
ledger records what the prompt named that the index could not resolve, which is
the data the Phase 2 decisions run on.

WHY STATUS LABELS COME FROM provenance-vocabulary.json: that file is the ONE
vocabulary, loaded at runtime by two lints already. A second table here would
drift the way the first two did on 2026-07-28 (the scar recorded in that file).

Contract: pure functions over paths. supply() writes only the receipt and misses
ledgers under <qroot>/memory/, both untracked jsonl like graph.jsonl, through
one append function. record=False writes nothing (replay and tests). Any store
that fails to parse is reported in the receipt, never raised past supply().
stdlib only.
"""
from __future__ import annotations

import datetime as dt
import functools
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

MANIFEST_NAME = "knowledge-sources.json"
RECEIPTS_NAME = ".knowledge-supply-receipts.jsonl"
MISSES_NAME = ".knowledge-supply-misses.jsonl"
VOCAB_NAME = "provenance-vocabulary.json"

KNOWN, STALE, CONFLICTING, UNVALIDATED = "KNOWN", "STALE", "CONFLICTING", "UNVALIDATED"
# The four marker forms in live use: q-system/CLAUDE.md names the first two,
# evidence-ledger.md names {{UNVERIFIED}}, and the skeleton's own talk-tracks.md
# carries {{NEEDS_VALIDATION}} (seen in the 2026-09-04 hook probe). A prefix
# match on "{{NEEDS_VALIDATION" also covers the annotated form "{{NEEDS_VALIDATION — ...}}".
UNVALIDATED_MARKERS = ("{{UNVALIDATED}}", "{{NEEDS_PROOF}}", "{{UNVERIFIED}}", "{{NEEDS_VALIDATION")
ALIAS_PREDICATES = {"alias_of": "s_is_alias", "uses_alias": "o_is_alias"}
ORG_PREDICATES = ("works_at",)
EVENT_KINDS = ("commitment", "meeting", "loop", "handoff")
# Commitment states, measured on consulting's commitments.jsonl 2026-09-04
# (open 73, superseded 121, confirmed-sent 20, misattributed 12, voided 6,
# resolved 5). The owner of that vocabulary is consulting's commitments.py, in
# another repo, so it cannot be derived here at runtime: "open" is the only open
# state, and voided/misattributed rows are not promises and are dropped.
OPEN_STATES = ("open",)
DROP_STATES = ("voided", "misattributed")

# Render order inside one entity. Canonical and decisions first (the founder's
# curated truth), then the graph newest-first, then event stores by recency.
TIER = {"canonical": 0, "decision": 0, "capability": 0, "relationship": 1, "graph": 2,
        "commitment": 3, "meeting": 4, "loop": 5, "handoff": 6}

STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "would", "should", "could", "there",
    "their", "them", "then", "than", "what", "when", "which", "while", "your", "about",
    "into", "over", "some", "just", "like", "make", "made", "does", "done", "here",
    "been", "being", "were", "want", "need", "also", "very", "much", "more", "most",
    "only", "same", "such", "each", "because", "before", "after", "again", "still",
    "even", "back", "down", "please", "write", "draft", "tell", "show", "give", "find",
    "know", "think", "today", "yesterday", "tomorrow", "week", "month", "year", "time",
    "everything", "anything", "something", "nothing", "status", "update", "email",
    "call", "meeting", "note", "notes", "file", "files", "plan", "list", "check",
}

TEMPORAL_RE = re.compile(
    r"\b(yesterday|today|tonight|this morning|this week|this month|last (?:week|month|night|call|meeting)|"
    r"since \d{4}-\d{2}-\d{2}|on \d{4}-\d{2}-\d{2}|recently|latest|lately)\b", re.IGNORECASE)
PROMISE_RE = re.compile(
    r"\b(promis\w*|owe\w*|committ\w*|commitment\w*|said (?:i|we) would|deliver\w*|due|deadline\w*|"
    r"outstanding|unresolved|still open|follow[- ]?ups?)\b", re.IGNORECASE)
CAPABILITY_RE = re.compile(
    r"\b(?:how (?:does|do|is)|what (?:is|does|are)|what's|explain|describe|where (?:does|is)|walk me through)\s+"
    r"(?:the\s+|our\s+|kipi'?s?\s+)?([\w][\w./-]*(?:\s+[\w][\w./-]*){0,2})", re.IGNORECASE)
HASH_REF_RE = re.compile(r"(?<![\w/])#\d{2,6}\b")
CAP_BIGRAM_RE = re.compile(r"\b([A-Z][\w'-]+)\s+([A-Z][\w'-]+)\b")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

WRITING_FALLBACK = [r"\bwrit\w*\b", r"\bdraft\w*\b", r"\bcompose\w*\b", r"\bemail\w*\b",
                    r"\bdm\b", r"\bmessage\b", r"\breply\w*\b", r"\brespond\w*\b",
                    r"\bpost\b", r"\bproposal\b", r"\bpitch\b", r"\boutreach\b"]


# ------------------------------------------------------------------ helpers

def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def norm(text: str) -> str:
    return normalize_ws((text or "").casefold().replace("-", " ").replace("_", " "))


def phrase_in(needle: str, hay_norm: str) -> bool:
    n = norm(needle)
    if not n:
        return False
    return re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", hay_norm) is not None


def word_in_exact(word: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text) is not None


def mtime_date(path: Path) -> str | None:
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def parse_date(value) -> dt.date | None:
    if not value or not isinstance(value, str):
        return None
    m = DATE_RE.search(value)
    if not m:
        return None
    try:
        return dt.date.fromisoformat(m.group(0))
    except ValueError:
        return None


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def writing_patterns() -> list[re.Pattern]:
    """voice-dna-loader.py owns the writing-intent vocabulary. Load it from the
    owner at runtime (lesson: derive a value from its owner, never restate it);
    fall back to a short list only if the owner cannot be loaded."""
    loader = Path(__file__).resolve().parent / "voice-dna-loader.py"
    pats = None
    try:
        spec = importlib.util.spec_from_file_location("voice_dna_loader", loader)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pats = list(getattr(mod, "WRITING_TRIGGER_PATTERNS", []) or [])
    except Exception:
        pats = None
    return [re.compile(p, re.IGNORECASE) for p in (pats or WRITING_FALLBACK)]


# ------------------------------------------------------------------ discovery

def find_qroot(root: Path) -> Path | None:
    """Same family of rule as kb-graph-guard.find_kb: an instance q-dir first,
    the nested and flat q-system layouts next, the repo root last. A non-q-system
    q-* dir wins over q-system because instances carry BOTH (q-system is the
    synced skeleton, the q-dir is theirs) and the sorted glob would otherwise
    pick q-system for any q-dir that sorts after it (a q-dir whose name sorts after 's')."""
    q_dirs = sorted(p for p in root.glob("q-*") if p.is_dir() and p.name != "q-system")
    candidates = q_dirs + [root / "q-system" / "q-system", root / "q-system", root]
    for c in candidates:
        if c.is_dir() and ((c / "memory").is_dir() or (c / "canonical").is_dir()):
            return c
    return None


def load_manifest(qroot: Path, root: Path) -> tuple[dict | None, Path | None]:
    env = os.environ.get("KNOWLEDGE_SOURCES_MANIFEST")   # replay and probes against an instance that has no copy yet
    candidates = ([Path(env)] if env else []) + [
        qroot / ".q-system" / "data" / MANIFEST_NAME,      # instance override (owned subtree)
        qroot / ".q-system" / MANIFEST_NAME,               # shipped default at the qroot
        root / "q-system" / ".q-system" / MANIFEST_NAME,   # synced skeleton copy (q-dir-less instances)
    ]
    for p in candidates:
        if p.is_file():
            try:
                return load_json(p), p
            except (OSError, ValueError):
                return None, p
    return None, None


VOCAB_PATH = Path(__file__).resolve().parent / VOCAB_NAME


@functools.lru_cache(maxsize=4)
def _vocab_floor_at(mtime_ns: int) -> tuple[frozenset[str], int]:
    table = load_json(VOCAB_PATH)["provenance"]
    floor = min(v["rank"] for v in table.values())
    return frozenset(k for k, v in table.items() if v["rank"] <= floor), floor


def load_vocab_floor() -> tuple[frozenset[str], int]:
    """(names ranked at the floor, floor rank). Still read from the owner, keyed
    on its mtime so an edit to the vocabulary is seen on the next call, but
    parsed once per version rather than once per matched line. Codex round 2 on
    PR #302: the per-line re-parse was the whole cost of status_for_line on a
    hook wired at timeout 5."""
    try:
        return _vocab_floor_at(VOCAB_PATH.stat().st_mtime_ns)
    except Exception:
        return frozenset({"inferred"}), 10


def status_for_line(line: str) -> str:
    """UNVALIDATED if the line carries a marker or a provenance form ranked at the
    vocabulary floor; KNOWN otherwise. Freshness and supersession are decided by
    the callers that know the date and the class."""
    if any(m in line for m in UNVALIDATED_MARKERS):
        return UNVALIDATED
    floor_names, _ = load_vocab_floor()
    m = re.search(r"provenance:\s*`?([a-z_]+)`?", line)
    if m and m.group(1) in floor_names:
        return UNVALIDATED
    return KNOWN


# ------------------------------------------------------------------ entity index

class Entity:
    __slots__ = ("name", "kind", "aliases", "orgs")

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind          # graph | contact | slug | client | capability
        self.aliases: set[str] = set()
        self.orgs: dict[str, str | None] = {}   # org -> project, from works_at rows

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "aliases": sorted(self.aliases)}


def _add(index: dict[str, Entity], name: str, kind: str) -> Entity | None:
    name = normalize_ws(name)
    if not name or len(name) > 80:
        return None
    key = norm(name)
    ent = index.get(key)
    if ent is None:
        ent = Entity(name, kind)
        index[key] = ent
    elif kind in ("contact", "client", "slug") and ent.kind == "graph":
        ent.kind = kind   # a curated source outranks a graph mention for the fire rule
    return ent


def build_index(stores: dict) -> dict[str, Entity]:
    index: dict[str, Entity] = {}
    graph_rows = stores.get("graph_rows") or []
    for row in graph_rows:
        s, p, o = row.get("s"), row.get("p"), row.get("o")
        if not isinstance(s, str) or not isinstance(o, str):
            continue
        es = _add(index, s, "graph")
        if len(o.split()) <= 4:
            _add(index, o, "graph")
        if p in ALIAS_PREDICATES and es is not None:
            if ALIAS_PREDICATES[p] == "s_is_alias":
                canonical = _add(index, o, "graph")
                if canonical is not None:
                    canonical.aliases.add(normalize_ws(s))
                    index.pop(norm(s), None)
            else:
                es.aliases.add(normalize_ws(o))
                index.pop(norm(o), None)
        if p in ORG_PREDICATES and es is not None:
            es.orgs[normalize_ws(o)] = row.get("project")
    for name in stores.get("contact_names") or []:
        _add(index, name, "contact")
    for slug in stores.get("slugs") or []:
        _add(index, slug, "slug")
    for key in stores.get("client_keys") or []:
        _add(index, key, "client")
    return index


def prompt_tokens(pn: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", pn))


def candidate_keys(index: dict[str, Entity], ptoks: set[str]) -> list[str]:
    """Index keys whose name or an alias STARTS with a word the prompt contains.
    Everything else cannot match and never reaches a regex. Pure, so the prune
    is testable without a clock: a paste against 6,000 entities yields a
    handful of candidates, not 6,000 regex scans."""
    out = []
    for key, ent in index.items():
        for name in (ent.name, *ent.aliases):
            first = re.findall(r"[a-z0-9]+", norm(name))
            if first and first[0] in ptoks:
                out.append(key)
                break
    return out


def resolve_entities(prompt: str, index: dict[str, Entity], fire_alone: set[str]) -> list[dict]:
    """Which index entities the prompt names. Multi-token: phrase match. Single
    token: identifier kinds on a whole-word match, contacts on the capitalized
    form, graph-only names never (see module docstring). Aliases follow the
    same rules by their own token count, with an all-caps short alias allowed."""
    pn = norm(prompt)
    # Token prefilter: an entity whose first token is not a word of the prompt
    # cannot match, so it never reaches the regex. Codex round 3 on PR #302:
    # a regex per entity over the whole prompt was O(prompt x index), 7.1 s for
    # a 109 KB paste against 6,000 entities, past the hook's 5 s timeout.
    ptoks = prompt_tokens(pn)
    found: dict[str, dict] = {}
    for key in candidate_keys(index, ptoks):
        ent = index[key]
        hit_via = None
        names = [(ent.name, "self")] + [(a, "alias") for a in ent.aliases]
        for name, via in names:
            toks = name.split()
            if len(toks) >= 2:
                if phrase_in(name, pn):
                    hit_via = via
            else:
                tok = toks[0] if toks else ""
                if not tok or tok.casefold() in STOPWORDS:
                    continue
                if via == "alias":
                    if (len(tok) >= 4 or tok.isupper()) and word_in_exact(tok, prompt):
                        hit_via = via
                    continue
                if len(tok) < 4:
                    continue
                if ent.kind in fire_alone:
                    # The manifest decides which identifier kinds fire on one
                    # word. No hardcoded second list: Codex round 1 on PR #302
                    # found the knob inert because an `or` here overrode it.
                    if re.search(r"(?<!\w)" + re.escape(norm(tok)) + r"(?!\w)", pn):
                        hit_via = via
                elif ent.kind == "contact":
                    if word_in_exact(tok, prompt) and tok[0].isupper():
                        hit_via = via
                # graph-only single token: never alone
            if hit_via:
                break
        if not hit_via:
            continue
        scoped_project, ambiguous = None, False
        if len(ent.orgs) >= 2:
            named = [org for org in ent.orgs if phrase_in(org, pn)]
            if len(named) == 1:
                scoped_project = ent.orgs[named[0]]
                ambiguous = scoped_project is None
            else:
                ambiguous = True
        found[key] = {"name": ent.name, "kind": ent.kind,
                      "resolved_from": "alias" if hit_via == "alias" else ent.kind,
                      "ambiguous": ambiguous, "project": scoped_project,
                      "orgs": sorted(ent.orgs), "aliases": sorted(ent.aliases)}
    # First-name expansion, measured not guessed. Replay of 2,131 real prompts
    # (2026-09-04) showed the founder names people by bare first name; the top
    # misses were exactly those. A capitalized token that is NOT sentence-initial
    # and is the first token of exactly ONE multi-token index entity resolves to
    # it. Sentence-initial stays out ("Mark the file as done" is a verb), so a
    # first name alone at the start of a prompt still never fires.
    # Runs ALONGSIDE the other resolutions, never only when they found nothing.
    # Codex round 2 on PR #302: gated on `if not found`, a first name was dropped
    # whenever any other entity resolved, under a FULL header and no misses row.
    if True:
        first_tokens: dict[str, list[str]] = {}
        for key, ent in index.items():
            toks = ent.name.split()
            if len(toks) >= 2:
                first_tokens.setdefault(toks[0].casefold(), []).append(key)
        for m in re.finditer(r"\b([A-Z][a-z]{3,})\b", prompt):
            if is_initial_position(prompt, m.start()):
                continue
            tok = m.group(1)
            if tok.casefold() in STOPWORDS:
                continue
            keys = first_tokens.get(tok.casefold()) or []
            if len(keys) == 1 and keys[0] not in found:
                ent = index[keys[0]]
                found[keys[0]] = {"name": ent.name, "kind": ent.kind, "resolved_from": "first_name",
                                  "ambiguous": len(ent.orgs) >= 2, "project": None,
                                  "orgs": sorted(ent.orgs), "aliases": sorted(ent.aliases)}
    # Longest name wins when one resolved name contains another ("Dana Okafor" vs "Okafor Co").
    out = list(found.values())
    out.sort(key=lambda e: -len(e["name"]))
    kept: list[dict] = []
    for e in out:
        if any(norm(e["name"]) != norm(k["name"]) and phrase_in(e["name"], norm(k["name"])) for k in kept):
            continue
        kept.append(e)
    kept.sort(key=lambda e: prompt.casefold().find(e["name"].casefold()) if e["name"].casefold() in prompt.casefold() else 10**6)
    return kept


def alias_in_text(alias: str, text: str) -> bool:
    """Content-side alias match, the same rule resolve_entities applies on the
    prompt side. A short alias (under 4 chars) is an initialism: it matches only
    as an UPPERCASE whole word, case-sensitively, against the raw text. Codex
    round 1 on PR #302: alias "DO" matched every store line containing the word
    "do", so a rate-floor rule and another client's question rendered under a
    person's heading in an outbound draft."""
    a = normalize_ws(alias)
    if not a:
        return False
    if len(a) < 4:
        return a.isupper() and word_in_exact(a, text)
    return phrase_in(a, norm(text))


INITIAL_PREFIX_RE = re.compile(r"^\s*(?:[-*>•]+|\d+[.)])?\s*$")


def is_initial_position(text: str, pos: int) -> bool:
    """True when pos opens a sentence or a line (after an optional bullet or
    numbering). A capitalized word there reads as a verb as often as a name
    ('Mark the file as done'). Codex round 1 on PR #302: the old lookbehind knew
    only sentence punctuation, so line-initial and bullet-initial tokens fired,
    and bulleted multi-line prompts are the house style."""
    line_start = text.rfind("\n", 0, pos) + 1
    if INITIAL_PREFIX_RE.match(text[line_start:pos]):
        return True
    before = text[:pos].rstrip()
    return not before or before[-1] in ".!?:;"


def entity_matches(entity: dict, text: str) -> bool:
    if phrase_in(entity["name"], norm(text)):
        return True
    return any(alias_in_text(a, text) for a in entity.get("aliases", []))


# ------------------------------------------------------------------ router

def classify(prompt: str, entities: list[dict], capability_hits: list, now: dt.date) -> tuple[str, dict | None]:
    """First match wins, in the plan's order. Returns (class, window)."""
    if entities:
        m = TEMPORAL_RE.search(prompt)
        if m:
            return "temporal_event", window_for(m.group(1).casefold(), now)
        if PROMISE_RE.search(prompt):
            return "commitment", None
        if any(p.search(prompt) for p in writing_patterns()):
            return "writing", None
        return "entity_lookup", None
    if capability_hits:
        return "capability", None
    return "none", None


def window_for(phrase: str, now: dt.date) -> dict:
    if phrase == "yesterday":
        start = now - dt.timedelta(days=1)
    elif phrase in ("today", "tonight", "this morning"):
        start = now
    elif phrase == "this week":
        start = now - dt.timedelta(days=now.weekday())
    elif phrase in ("last week", "last call", "last meeting"):
        start = now - dt.timedelta(days=7)
    elif phrase in ("last month", "this month"):
        start = now - dt.timedelta(days=31)
    elif phrase.startswith("since ") or phrase.startswith("on "):
        d = parse_date(phrase)
        start = d if d else now - dt.timedelta(days=7)
        if phrase.startswith("on ") and d:
            return {"from": d.isoformat(), "to": d.isoformat()}
    else:
        start = now - dt.timedelta(days=14)
    return {"from": start.isoformat(), "to": now.isoformat()}


def in_window(t: str | None, window: dict | None) -> bool:
    if window is None:
        return True
    d = parse_date(t)
    if d is None:
        return False
    return window["from"] <= d.isoformat() <= window["to"]


# ------------------------------------------------------------------ store loading

def load_stores(qroot: Path, root: Path) -> tuple[dict, dict]:
    """Read every store once. Returns (stores, problems). A store that fails to
    parse lands in problems and counts as present-but-unreadable in the receipt."""
    stores: dict = {"paths": {}}
    problems: dict = {}
    paths = {
        "graph": qroot / "memory" / "graph.jsonl",
        "relationships": qroot / "my-project" / "relationships.md",
        "decisions": qroot / "canonical" / "decisions.md",
        "commitments": qroot / "my-project" / "commitments.jsonl",
        "meetings": qroot / "output" / "granola-cache.json",
        "handoff": qroot / "memory" / "last-handoff.md",
    }
    loops_candidates = [qroot / "memory" / "open-loops.json", qroot / "output" / "open-loops.json"]
    paths["loops"] = next((p for p in loops_candidates if p.is_file()), loops_candidates[0])
    stores["paths"] = paths
    canon_files = []
    for d in (qroot / "canonical", qroot / "my-project"):
        if d.is_dir():
            canon_files += sorted(p for p in d.glob("*.md") if p.name not in ("relationships.md", "decisions.md"))
    stores["canonical_files"] = canon_files

    rows, bad = [], 0
    if paths["graph"].is_file():
        try:
            for n, line in enumerate(read_lines(paths["graph"]), start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        row["_line"] = n
                        rows.append(row)
                    else:
                        bad += 1
                except ValueError:
                    bad += 1
        except OSError as exc:
            problems["graph"] = str(exc)
    elif paths["graph"].exists():
        problems["graph"] = "not a file"
    stores["graph_rows"] = rows
    # Bad lines are recorded PER STORE under one key the receipt reads, and a
    # store with rows parsed == 0 and bad > 0 is UNREADABLE, not empty. Codex
    # round 1 on PR #302: the commitments counter went to a key nothing read,
    # so an all-corrupt promise ledger reported present=True under FULL, the
    # exact "never searched vs not found" collapse the receipt exists to stop.
    stores["bad_lines"] = {"graph": bad}
    if bad and not rows:
        problems["graph"] = f"unreadable: {bad} bad line(s), 0 parsed"

    contact_names = []
    if paths["relationships"].is_file():
        try:
            for line in read_lines(paths["relationships"]):
                if line.startswith("### "):
                    head = line[4:].split("<!--")[0]
                    name = re.split(r"\s+[—–-]\s+", head, maxsplit=1)[0].strip()
                    if name and not name.startswith("["):
                        contact_names.append(name)
        except OSError as exc:
            problems["relationships"] = str(exc)
    stores["contact_names"] = contact_names

    commitments, bad_c = [], 0
    if paths["commitments"].is_file():
        try:
            for n, line in enumerate(read_lines(paths["commitments"]), start=1):
                if line.strip():
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError("row is not an object")
                        row["_line"] = n
                        commitments.append(row)
                    except ValueError:
                        bad_c += 1
        except OSError as exc:
            problems["commitments"] = str(exc)
    stores["commitments"] = commitments
    stores["bad_lines"]["commitments"] = bad_c
    if bad_c and not commitments:
        problems["commitments"] = f"unreadable: {bad_c} bad line(s), 0 parsed"
    stores["slugs"] = sorted({r.get("slug") for r in commitments if isinstance(r.get("slug"), str)})

    meetings = {}
    if paths["meetings"].is_file():
        try:
            data = load_json(paths["meetings"])
            if isinstance(data, dict):
                meetings = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, list)}
        except (OSError, ValueError) as exc:
            problems["meetings"] = str(exc)
    stores["meetings"] = meetings
    stores["client_keys"] = sorted(meetings)

    loops = []
    if paths["loops"].is_file():
        try:
            data = load_json(paths["loops"])
            loops = data if isinstance(data, list) else (data.get("loops") or [])
        except (OSError, ValueError) as exc:
            problems["loops"] = str(exc)
    stores["loops"] = [l for l in loops if isinstance(l, dict)]
    return stores, problems


# ------------------------------------------------------------------ resolvers

def _item(entity: str, kind: str, text: str, path: Path, anchor, t: str | None, root: Path,
          status: str = KNOWN, predicate: str | None = None, pieces: list[str] | None = None) -> dict:
    sep = ":" if isinstance(anchor, int) else "#"
    return {"entity": entity, "kind": kind, "text": text, "src": f"{rel(path, root)}{sep}{anchor}",
            "abs_src": str(path), "t": t, "status": status, "supersedes": None,
            "predicate": predicate, "pieces": pieces if pieces is not None else [text]}


def resolve_graph(entity: dict, stores: dict, root: Path, window: dict | None,
                  state_predicates: set[str] | None = None) -> tuple[list[dict], int]:
    """Supersession is decided per (subject, STATE predicate, project). Only a
    state-like predicate can be superseded; an accumulative one (owns, confirmed,
    discovered) holds many objects at once and every one of them stays KNOWN.
    Measured on the largest instance 2026-09-04 before this rule: 'owns merging PR
    #19' wrongly marked 'owns merged PR #8' STALE. The allowlist is data in the
    manifest (state_predicates), never a table here."""
    path = stores["paths"]["graph"]
    state_predicates = {norm(p) for p in (state_predicates or ())}
    rows = [r for r in stores["graph_rows"]
            if isinstance(r.get("s"), str) and isinstance(r.get("o"), str)
            and (entity_matches(entity, r["s"]) or entity_matches(entity, r["o"]))
            and r.get("p") not in ALIAS_PREDICATES]
    if entity.get("project"):
        rows = [r for r in rows if r.get("project") in (entity["project"], None, "all")]
    rows = [r for r in rows if in_window(r.get("t"), window)]
    # Same date: the later line in the file is the later write (append-only store).
    rows.sort(key=lambda r: ((r.get("t") or ""), r["_line"]), reverse=True)
    items, conflicts = [], 0
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if norm(str(r.get("p"))) in state_predicates:
            groups.setdefault((norm(r["s"]), norm(str(r.get("p"))), r.get("project")), []).append(r)
    newest_src: dict[tuple, str] = {}
    conflict_keys: set[tuple] = set()
    for key, grp in groups.items():
        objs = {norm(g["o"]) for g in grp}
        if len(objs) > 1:
            conflicts += 1
            if len({g.get("t") for g in grp[:2]}) == 1:
                conflict_keys.add(key)
        newest_src[key] = f"{rel(path, root)}:{grp[0]['_line']}"
    for r in rows:
        key = (norm(r["s"]), norm(str(r.get("p"))), r.get("project"))
        src = f"{rel(path, root)}:{r['_line']}"
        text = f"{r['s']} {r.get('p')} {r['o']}"
        item = _item(entity["name"], "graph", text, path, r["_line"], r.get("t"), root,
                     predicate=str(r.get("p")), pieces=[r["s"], str(r.get("p")), r["o"]])
        if key in conflict_keys:
            item["status"] = CONFLICTING
        elif key in newest_src and newest_src[key] != src and len({norm(g["o"]) for g in groups[key]}) > 1:
            item["status"] = STALE
            item["supersedes"] = newest_src[key]
        items.append(item)
    return items, conflicts


def resolve_canonical(entity: dict, stores: dict, root: Path, kind: str = "canonical",
                      files: list[Path] | None = None) -> list[dict]:
    items = []
    for path in (files if files is not None else stores["canonical_files"]):
        try:
            lines = read_lines(path)
        except OSError:
            continue
        t = mtime_date(path)
        in_fence = False
        for n, line in enumerate(lines, start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            if entity_matches(entity, line):
                items.append(_item(entity["name"], kind, line.strip(), path, n, t, root,
                                   status=status_for_line(line)))
    items.sort(key=lambda i: (i["t"] or ""), reverse=True)
    return items


def resolve_blocks(entity: dict, path: Path, root: Path, kind: str, max_lines: int) -> list[dict]:
    """### blocks in relationships.md / decisions.md that mention the entity."""
    if not path.is_file():
        return []
    try:
        lines = read_lines(path)
    except OSError:
        return []
    items, start, in_fence = [], None, False
    blocks = []
    for n, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if in_fence:
            continue
        if line.startswith("### ") or line.startswith("## "):
            if start is not None:
                blocks.append((start, lines[start - 1:n - 1]))
            start = n if line.startswith("### ") else None
    if start is not None:
        blocks.append((start, lines[start - 1:]))
    file_t = mtime_date(path)
    for start, block in blocks:
        body = [l for l in block if l.strip()]
        joined = "\n".join(body)
        target = body[0] if kind == "relationship" else joined
        if not entity_matches(entity, target if kind == "relationship" else joined):
            continue
        if kind == "decision":
            decision = next((l for l in body if "**Decision:**" in l), "")
            date_line = next((l for l in body if "**Date:**" in l), "")
            d = parse_date(date_line)
            text = "\n".join([body[0], decision] if decision else [body[0]])
            items.append(_item(entity["name"], kind, text, path, start,
                               d.isoformat() if d else file_t, root,
                               status=status_for_line(joined), pieces=[body[0]] + ([decision] if decision else [])))
        else:
            text = "\n".join(body[:max_lines])
            items.append(_item(entity["name"], kind, text, path, start, file_t, root,
                               status=status_for_line(joined), pieces=[text]))
    return items


def resolve_commitments(entity: dict, stores: dict, root: Path, window: dict | None) -> list[dict]:
    path = stores["paths"]["commitments"]
    items = []
    open_first, others = [], []
    for r in stores["commitments"]:
        promise, slug, state = str(r.get("promise") or ""), str(r.get("slug") or ""), str(r.get("state") or "")
        if state in DROP_STATES:
            continue
        if not (entity_matches(entity, slug) or entity_matches(entity, promise)):
            continue
        t = (r.get("extracted_at") or "")[:10] or None
        if not in_window(t, window):
            continue
        text = f"{promise} [state: {state or 'open'}; due: {r.get('due') or 'none'}; slug: {slug}]"
        item = _item(entity["name"], "commitment", text, path, r["_line"], t, root,
                     pieces=[promise] + ([state] if state else []))
        (open_first if (not state or state in OPEN_STATES) else others).append(item)
    open_first.sort(key=lambda i: i["t"] or "", reverse=True)
    others.sort(key=lambda i: i["t"] or "", reverse=True)
    return open_first + others


def resolve_meetings(entity: dict, stores: dict, root: Path, window: dict | None) -> list[dict]:
    path = stores["paths"]["meetings"]
    items = []
    for key, rows in stores["meetings"].items():
        key_hit = entity_matches(entity, key)
        for r in rows:
            if not isinstance(r, dict):
                continue
            title, summary = str(r.get("title") or ""), str(r.get("summary") or "")
            if not (key_hit or entity_matches(entity, title) or entity_matches(entity, summary)):
                continue
            t = (r.get("date") or "")[:10] or None
            if not in_window(t, window):
                continue
            text = f"{t or '?'} {title}: {summary}"
            items.append(_item(entity["name"], "meeting", text, path, f"{key}/{r.get('meeting_id') or '?'}",
                               t, root, pieces=[p for p in (title, summary) if p]))
    items.sort(key=lambda i: i["t"] or "", reverse=True)
    return items


def resolve_loops(entity: dict, stores: dict, root: Path, window: dict | None) -> list[dict]:
    path = stores["paths"]["loops"]
    items = []
    for l in stores["loops"]:
        if l.get("status") != "open":
            continue
        title, nxt = str(l.get("title") or ""), str(l.get("next_action") or "")
        if not (entity_matches(entity, title) or entity_matches(entity, nxt)):
            continue
        t = (l.get("added") or "")[:10] or None
        if not in_window(t, window):
            continue
        items.append(_item(entity["name"], "loop", f"{title} -> next: {nxt}", path, str(l.get("id") or "?"),
                           t, root, pieces=[p for p in (title, nxt) if p]))
    items.sort(key=lambda i: i["t"] or "", reverse=True)
    return items


def resolve_handoff(entity: dict, stores: dict, root: Path, window: dict | None) -> list[dict]:
    path = stores["paths"]["handoff"]
    if not path.is_file():
        return []
    items = resolve_canonical(entity, stores, root, kind="handoff", files=[path])
    return [i for i in items if in_window(i["t"], window)]


def capability_index(root: Path) -> dict[str, list[tuple[Path, int, str]]]:
    """name -> [(path, line, description)] over the repo's own commands, skills,
    rules and scripts. Built only when the prompt has capability phrasing."""
    out: dict[str, list[tuple[Path, int, str]]] = {}

    def add(name: str, path: Path, line: int, desc: str):
        out.setdefault(norm(name), []).append((path, line, desc))

    for md in sorted(root.glob("plugins/*/commands/*.md")):
        add(md.stem, md, *first_desc(md))
    for skill in sorted(root.glob("plugins/*/skills/*/SKILL.md")):
        add(skill.parent.name, skill, *first_desc(skill))
    for rule in sorted(root.glob(".claude/rules/*.md")):
        add(rule.stem, rule, *first_desc(rule))
    for script in sorted(root.glob("q-system/.q-system/scripts/*.py")):
        if script.name.startswith("test"):
            continue
        add(script.stem, script, *first_desc(script))
    return out


def first_desc(path: Path) -> tuple[int, str]:
    try:
        lines = read_lines(path)
    except OSError:
        return 1, ""
    for n, line in enumerate(lines[:40], start=1):
        s = line.strip()
        if s.startswith("description:"):
            return n, s
        if s.startswith("# "):
            return n, s
        if s.startswith('"""') and len(s) > 3:
            return n, s.strip('"').strip()
    return 1, (lines[0].strip() if lines else "")


def capability_hits(prompt: str, cap_index: dict) -> list[tuple[str, list]]:
    hits = []
    for m in CAPABILITY_RE.finditer(prompt):
        phrase = m.group(1)
        toks = phrase.split()
        for k in range(len(toks), 0, -1):
            cand = norm(" ".join(toks[:k])).rstrip("?.!,")
            if cand in cap_index:
                hits.append((cand, cap_index[cand]))
                break
    return hits


# ------------------------------------------------------------------ assembly

def assemble(items: list[dict], entities: list[dict], ceiling: int, header_len: int) -> tuple[list[dict], int, bool]:
    """Order, dedupe, and cut to the ceiling. The newest graph item per entity is
    pinned first so a cut can never drop the one fact most likely to be current."""
    order = {norm(e["name"]): i for i, e in enumerate(entities)}
    seen: set[tuple] = set()
    deduped = []
    for it in items:
        key = (it["kind"], norm(it["text"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    deduped.sort(key=lambda i: (order.get(norm(i["entity"]), 99), TIER.get(i["kind"], 9)))  # stable: resolver order survives inside a tier (open commitments first, newest first)
    pinned: set[int] = set()
    seen_ent: set[str] = set()
    for idx, it in enumerate(deduped):
        if it["kind"] == "graph" and norm(it["entity"]) not in seen_ent:
            pinned.add(idx)
            seen_ent.add(norm(it["entity"]))
    used = header_len
    kept, cut, ceiling_hit = [], 0, False
    # Pins are reserved FIRST and always kept, so their cost sits inside `used`
    # before the fill starts. If the pins alone overrun the ceiling, that is
    # REPORTED (ceiling_hit, overflow), never hidden: Codex round 2 on PR #302
    # found pinned items slipping past the ceiling under cut=0, ceiling_hit=False.
    for idx, it in enumerate(deduped):
        it["pinned"] = idx in pinned
    for idx in sorted(pinned):
        used += len(render_item(deduped[idx])) + 1
        kept.append(deduped[idx])
    if used > ceiling:
        ceiling_hit = True
    # The first cut ends the fill for everything else. A per-item check would
    # let a short low-tier line slip into the gap left after a higher-tier cut,
    # which reorders priority by accident (measured: the pin mutation survived
    # until this was a hard stop).
    for idx, it in enumerate(deduped):
        if idx in pinned:
            continue
        cost = len(render_item(it)) + 1
        if not ceiling_hit and used + cost <= ceiling:
            kept.append(it)
            used += cost
        else:
            cut += 1
            ceiling_hit = True
    kept.sort(key=lambda i: (order.get(norm(i["entity"]), 99), TIER.get(i["kind"], 9)))  # stable: resolver order survives inside a tier (open commitments first, newest first)
    return kept, cut, ceiling_hit


def render_item(it: dict) -> str:
    tag = it["status"]
    if it["supersedes"]:
        tag += f", superseded by {it['supersedes'].split('/')[-1]}"
    kind = it["kind"] + (f"/{it['predicate']}" if it.get("predicate") else "")
    text = it["text"].replace("\n", "\n    ")
    return f"- [{tag} {it['t'] or 'undated'} {kind}] {text}  ({it['src']})"


def render_header(bundle: dict) -> str:
    cov = bundle["coverage"]
    if cov["verdict"] == "FULL":
        line = "[knowledge-supply] COVERAGE: FULL."
    else:
        miss = "; ".join(f"{m} ({bundle['coverage']['missing_paths'].get(m, 'absent')})" for m in cov["missing"])
        line = f"[knowledge-supply] COVERAGE: {cov['verdict']}. missing: {miss}."
    ents = ", ".join(e["name"] + (" (ambiguous: " + " | ".join(e["orgs"]) + ")" if e["ambiguous"] else "")
                     for e in bundle["entities"]) or "none"
    win = bundle.get("window")
    win_s = f" window={win['from']}..{win['to']}" if win else ""
    return (f"{line} task={bundle['task_class']} entities={ents}.{win_s}\n"
            "[knowledge-supply] Hierarchy: graph beats canonical beats notes (q-system/methodology/anti-hallucination.md). "
            "Verbatim excerpts, newest first, each with path:line; open the src before asserting it. "
            "This layer never infers; anything you add beyond these lines is INFERRED and yours to label.")


def render(bundle: dict) -> str:
    if not bundle["items"]:
        # An entity resolved and every declared store was searched and held
        # nothing: one line, not an 800-char header. Codex round 3 on PR #302.
        # It is still a line and not zero bytes on purpose: "searched, nothing
        # recorded" is the receipt this module exists to give.
        cov = bundle["coverage"]
        ents = ", ".join(e["name"] for e in bundle["entities"]) or "none"
        miss = f" missing: {', '.join(cov['missing'])}." if cov["missing"] else ""
        return (f"[knowledge-supply] COVERAGE: {cov['verdict']}. task={bundle['task_class']} entities={ents}. "
                f"Searched, nothing recorded.{miss} receipt={bundle['receipt_path']}")
    parts = [render_header(bundle)]
    current = None
    for it in bundle["items"]:
        if it["entity"] != current:
            current = it["entity"]
            parts.append(f"== {current} ==")
        parts.append(render_item(it))
    d = bundle["delegated"]
    parts.append(f"[knowledge-supply] delegated: lessons -> {d['lessons']}, voice -> {d['voice']}. "
                 f"cut={bundle['budget']['cut']} receipt={bundle['receipt_path']}")
    return "\n".join(parts)


def verbatim_pieces(item: dict) -> list[str]:
    return [p for p in item.get("pieces") or [item["text"]] if p]


# ------------------------------------------------------------------ ledgers

def append_jsonl(path: Path, row: dict) -> None:
    """The single writer for both ledgers. O_APPEND so overlapping sessions never
    truncate each other (the session_recall scar)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


MISS_CAP_PER_PROMPT = 20
MISS_LEDGER_MAX_BYTES = 256 * 1024


def miss_candidates(prompt: str, entities: list[dict]) -> list[dict]:
    """Distinct unresolved candidates, at most MISS_CAP_PER_PROMPT per prompt.
    Codex round 3 on PR #302: one row per OCCURRENCE with no cap wrote 1,600
    rows (245 KB) from a single pasted transcript. A ledger that grows without
    bound from one paste is the noise that gets a hook switched off."""
    resolved = [norm(e["name"]) for e in entities] + [norm(a) for e in entities for a in e.get("aliases", [])]
    out: dict[str, dict] = {}
    for m in CAP_BIGRAM_RE.finditer(prompt):
        a, b = m.group(1), m.group(2)
        if a.casefold() in STOPWORDS or b.casefold() in STOPWORDS:
            continue
        cand = f"{a} {b}"
        cn = norm(cand)
        if cn in out or any(cn in r or r in cn for r in resolved):
            continue
        out[cn] = {"candidate": cand, "shape": "capitalized_bigram"}
        if len(out) >= MISS_CAP_PER_PROMPT:
            break
    for m in HASH_REF_RE.finditer(prompt):
        if len(out) >= MISS_CAP_PER_PROMPT:
            break
        out.setdefault(m.group(0), {"candidate": m.group(0), "shape": "hash_ref"})
    return list(out.values())


def append_bounded(path: Path, row: dict, max_bytes: int = MISS_LEDGER_MAX_BYTES) -> None:
    """append_jsonl, then keep the file under max_bytes by dropping the oldest
    half of its lines (atomic rewrite). The receipts ledger is small per row and
    one per firing; the misses ledger is the one that can balloon."""
    append_jsonl(path, row)
    try:
        if path.stat().st_size <= max_bytes:
            return
        lines = read_lines(path)
        keep = lines[len(lines) // 2:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


PROMPT_SCAN_CHARS = 12000


def _record_misses(qroot: Path, prompt: str, scan: str, truncated: bool,
                   entities: list[dict], ts: str, session_id: str) -> None:
    """One bounded write per prompt. A truncated prompt (a paste) gets ONE row
    saying so instead of its candidates: the founder did not name those things,
    the pasted text did."""
    path = qroot / "memory" / MISSES_NAME
    h = _hash(prompt)
    if truncated:
        append_bounded(path, {"ts": ts, "session_id": session_id, "prompt_hash": h,
                              "candidate": None, "shape": "large_prompt_skipped", "chars": len(prompt)})
        return
    for miss in miss_candidates(scan, entities):
        append_bounded(path, {"ts": ts, "session_id": session_id, "prompt_hash": h, **miss})


# ------------------------------------------------------------------ entry point

def supply(root: Path, prompt: str, *, session_id: str, now: dt.date | None = None,
           record: bool = True) -> dict | None:
    t0 = time.time()
    root = Path(root)
    now = now or dt.date.today()
    qroot = find_qroot(root)
    if qroot is None:
        return None
    receipts_path = qroot / "memory" / RECEIPTS_NAME
    manifest, manifest_path = load_manifest(qroot, root)
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if manifest is None:
        if record:
            append_jsonl(receipts_path, {"ts": ts, "session_id": session_id, "error": "manifest_missing",
                                         "looked_at": str(manifest_path) if manifest_path else None})
        return None

    stores, problems = load_stores(qroot, root)
    index = build_index(stores)
    # Absent key: the shipped default. Present but empty: a deliberate quiet.
    fire_alone = set(manifest["entity_kinds_that_fire_alone"]
                     if "entity_kinds_that_fire_alone" in manifest else ["slug", "client"])
    # Only the head of a very long prompt is scanned: past PROMPT_SCAN_CHARS it
    # is a paste, not a question, and the receipt says it was truncated.
    scan = prompt[:PROMPT_SCAN_CHARS]
    truncated = len(prompt) > PROMPT_SCAN_CHARS
    entities = resolve_entities(scan, index, fire_alone)
    cap_hits = capability_hits(scan, capability_index(root)) if (CAPABILITY_RE.search(scan) and not entities) else []
    task_class, window = classify(scan, entities, cap_hits, now)
    if task_class == "none":
        if record:
            _record_misses(qroot, prompt, scan, truncated, entities, ts, session_id)
        return None

    declared = (manifest.get("classes") or {}).get(task_class, {}).get("sources") or {}
    items: list[dict] = []
    conflicts = 0
    source_rows: list[dict] = []
    missing: list[str] = []
    missing_paths: dict[str, str] = {}
    paths = stores["paths"]

    def present_of(cls: str) -> tuple[bool, str | None]:
        if cls == "canonical":
            return bool(stores["canonical_files"]), rel(qroot / "canonical", root)
        if cls == "capability":
            return bool(cap_hits), "repo capability index"
        p = paths.get(cls if cls != "relationship" else "relationships")
        if p is None:
            return False, None
        return (p.is_file() and cls not in problems), rel(p, root)

    for cls, spec in declared.items():
        present, path_s = present_of(cls)
        cls_items: list[dict] = []
        # The cap is N per class PER ENTITY, applied to each resolver result
        # before the lists are joined. Codex round 1 on PR #302: a cap applied
        # to the joined list let the first entity eat the whole budget, so the
        # header named three people and the body carried facts about one.
        cap = spec.get("cap")
        cut_here = 0
        if present:
            for ent in entities:
                if cls == "graph":
                    got, c = resolve_graph(ent, stores, root, window,
                                           set(manifest.get("state_predicates") or []))
                    conflicts += c
                elif cls == "canonical":
                    got = resolve_canonical(ent, stores, root)
                elif cls == "relationships":
                    got = resolve_blocks(ent, paths["relationships"], root, "relationship", 12)
                elif cls == "decisions":
                    got = resolve_blocks(ent, paths["decisions"], root, "decision", 8)
                elif cls == "commitments":
                    got = resolve_commitments(ent, stores, root, window)
                elif cls == "meetings":
                    got = resolve_meetings(ent, stores, root, window)
                elif cls == "loops":
                    got = resolve_loops(ent, stores, root, window)
                elif cls == "handoff":
                    got = resolve_handoff(ent, stores, root, window)
                else:
                    got = []
                if cap is not None and len(got) > cap:
                    cut_here += len(got) - cap
                    got = got[:cap]
                cls_items += got
            if cls == "capability":
                for name, entries in cap_hits:
                    got = [_item(name, "capability", desc or path.name, path, line,
                                 mtime_date(path), root, pieces=[desc] if desc else [])
                           for path, line, desc in entries]
                    if cap is not None and len(got) > cap:
                        cut_here += len(got) - cap
                        got = got[:cap]
                    cls_items += got
        fresh_days = spec.get("fresh_days")
        if fresh_days:
            for it in cls_items:
                d = parse_date(it["t"])
                if it["status"] == KNOWN and (d is None or (now - d).days > fresh_days):
                    it["status"] = STALE
        items += cls_items
        if not present and spec.get("required"):
            missing.append(cls)
            missing_paths[cls] = f"{path_s or cls} {'unreadable' if cls in problems else 'absent'}"
        src_path = Path(root) / path_s if path_s and cls not in ("canonical", "capability") else None
        source_rows.append({
            "class": cls, "path": path_s, "present": present, "required": bool(spec.get("required")),
            "mtime": mtime_date(src_path) if src_path and src_path.exists() else None,
            "fresh_days": fresh_days, "hits": len(cls_items) + cut_here, "cut": cut_here,
            "bytes": sum(len(i["text"]) for i in cls_items),
            "bad_lines": stores["bad_lines"].get(cls, 0),
            "problem": problems.get(cls),
        })

    verdict = "FULL" if not missing else ("NONE" if all(not r["present"] for r in source_rows) else "PARTIAL")
    ceiling = int(manifest.get("ceiling_chars") or 8000)
    bundle = {
        "task_class": task_class, "window": window,
        "entities": [{k: v for k, v in e.items() if k != "project"} | {"project": e.get("project")} for e in entities],
        "coverage": {"verdict": verdict, "missing": missing, "missing_paths": missing_paths},
        "items": [], "conflicts": conflicts,
        "budget": {"ceiling": ceiling, "used": 0, "cut": 0},
        "delegated": {"lessons": "lessons-inject", "voice": "voice-dna-loader"},
        "receipt_path": rel(receipts_path, root),
    }
    header_len = len(render_header(bundle)) + 200
    kept, cut, ceiling_hit = assemble(items, entities, ceiling, header_len)
    bundle["items"] = kept
    source_cut = sum(r["cut"] for r in source_rows)
    # Exact fit against the RENDERED text, separators and footer included, so
    # the number in the receipt is the number on the wire. Codex round 3 on
    # PR #302: the byte accounting skipped the per-entity separator lines, so
    # render() ran past the ceiling while the receipt said overflow 0. Drops
    # the lowest-priority unpinned item until it fits; pins never drop, and if
    # pins alone overrun, overflow says by how much.
    while True:
        bundle["budget"]["cut"] = cut + source_cut
        rendered = len(render(bundle))
        if rendered <= ceiling:
            break
        drop = next((i for i in range(len(bundle["items"]) - 1, -1, -1)
                     if not bundle["items"][i].get("pinned")), None)
        ceiling_hit = True
        if drop is None:
            break
        bundle["items"].pop(drop)
        cut += 1
    bundle["budget"]["cut"] = cut + source_cut
    bundle["budget"]["used"] = len(render(bundle))
    overflow = max(0, bundle["budget"]["used"] - ceiling)
    bundle["budget"]["overflow"] = overflow   # chars the pins alone ran past the ceiling; 0 when honest
    receipt = {
        "ts": ts, "session_id": session_id, "task_class": task_class, "prompt_hash": _hash(prompt),
        "entities": [e["name"] for e in entities], "window": window,
        "sources": source_rows, "declared_missing": missing, "coverage": verdict,
        "conflicts": conflicts, "ceiling_hit": ceiling_hit, "overflow": overflow,
        "prompt_chars": len(prompt), "prompt_truncated": truncated,
        "items": len(kept), "bytes": bundle["budget"]["used"], "elapsed_ms": int((time.time() - t0) * 1000),
        "manifest": rel(manifest_path, root) if manifest_path else None,
    }
    bundle["receipt"] = receipt
    if record:
        append_jsonl(receipts_path, receipt)
        _record_misses(qroot, prompt, scan, truncated, entities, ts, session_id)
    return bundle


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


if __name__ == "__main__":  # manual probe: python3 knowledge_supply.py "<prompt>" [root]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    prompt = sys.argv[1] if len(sys.argv) > 1 else ""
    b = supply(root, prompt, session_id="manual", record=False)
    if b:
        print(render(b))
    else:
        # Say WHY, so a silent probe is never mistaken for a working one.
        q = find_qroot(root)
        if q is None:
            print(f"(no supply) reason=no_qroot root={root}")
        else:
            m, mp = load_manifest(q, root)
            if m is None:
                print(f"(no supply) reason=manifest_missing qroot={q} looked_at={mp}")
            else:
                st, pr = load_stores(q, root)
                ents = resolve_entities(prompt, build_index(st), set(m.get("entity_kinds_that_fire_alone") or []))
                print(f"(no supply) reason=no_entities_or_class qroot={q} index_size={len(build_index(st))} "
                      f"entities={[e['name'] for e in ents]} problems={pr}")
