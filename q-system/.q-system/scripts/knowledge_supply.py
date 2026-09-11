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

WHY STORES, DOCS AND PROMPT-DRIVEN CANDIDATES (founder-directed 2026-09-05, plan
knowledge-supply-project-folders-2026-09-05): "every project reads its own folder,
and each 4_points investigation is its own knowledge base." Measured before this:
4_points had 45 investigation folders and 1,475 markdown files that no source
class covered (index: 40 graph entities); a consulting instance had 83 files and an index of 0, so the reader never woke up there. Three additions, all declared as data in
the manifest: `stores` (a glob of sub-directories, each a knowledge base with the
qroot layout; naming one in the prompt scopes the search to it), a `docs` class
(the project's own markdown folders, one grep pass per prompt, Python fallback),
and prompt-driven candidates (a capitalized word the index cannot resolve is
searched case-sensitively in the docs; a hit makes it an entity, a miss stays a
miss). Headings never index: the heading census across every case file was
section labels (Notes, Summary, Integrity), not names.

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
import shutil
import subprocess
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
        "commitment": 3, "meeting": 4, "loop": 5, "handoff": 6, "doc": 7}

# The project-level store's name in receipts and items; sub-stores carry their
# directory name (case-023-shinyhunters), which the src path shows anyway.
PROJECT_STORE = "project"
# A store directory's entity name drops a `case-023-` style prefix: the founder
# says "shinyhunters", never "case-023-shinyhunters".
STORE_PREFIX_RE = re.compile(r"^[a-z]+-\d+-", re.IGNORECASE)
# Never knowledge, never disclosed: tooling dirs. Everything else a store keeps
# out of the docs class is DECLARED in the manifest (skip_dirs) and counted in
# the receipt, the way doc_max_bytes skips are (PR #308 review round 11: the
# hardcoded raw-collections/exports skip had no record anywhere under FULL).
HARD_SKIP_DIRS = {"node_modules", "__pycache__"}
DEFAULT_SKIP_DIRS = ["exports", "screenshots", "raw-collections"]
DOC_MAX_BYTES_DEFAULT = 512 * 1024
# Python fallback budget when grep is unavailable: past this many bytes the
# scan stops and the receipt engine says "python (budget)".
DOC_SCAN_BUDGET_BYTES = 3 * 1024 * 1024
GREP_CHUNK = 400
MAX_DOC_CANDIDATES = 6
# Bounds on the docs pass. grep -m caps matches PER FILE; MAX_DOC_HITS caps the
# lines the fold will look at at all. PR #308 review round 2: an entity with a
# hit on most lines of a large corpus ran the fold for 8.46 s and 1.1 GB, past
# both the 3.5 s deadline and the 5 s hook timeout, because every bound sat
# BEFORE the fold and none inside it.
GREP_MAX_PER_FILE = 200
MAX_DOC_HITS = 20000
# Every way a search can stop early, as the suffix the engine string carries.
# ONE chokepoint (class_search_state) turns any of them into searched=partial
# and, for a required class, a missing entry; PR #308 review rounds 1 and 2
# found the same defect on two paths (deadline before the class, then grep
# timeout / byte budget inside it), which is the signal for one rule, not two.
TRUNCATION_MARKERS = ("(deadline)", "(timeout)", "(budget)", "(hit cap)", "(file cap)")
# A prompt word that hits in more than this many stores is a word this corpus
# uses everywhere (Facebook, Miami across 27 of 43 cases, measured 2026-09-05),
# not a subject. It is dropped and named in the receipt; naming a case first
# scopes the count to that case, so the same word works inside one.
MAX_CANDIDATE_STORES = 4
ENTITY_DIR_MAX_DEPTH = 4

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
# Lookahead so the scan overlaps: "Ping Sarah Chen" yields "Sarah Chen" and not
# only "Ping Sarah" (sp-c9b6401d). Sentence openers and articles as a FIRST
# token are dropped by MISS_OPENERS, not by the initial-position rule, which
# stays inside single_token_hit as its only call site.
CAP_BIGRAM_RE = re.compile(r"(?=\b([A-Z][\w'-]+)\s+([A-Z][\w'-]+)\b)")
MISS_OPENERS = {"the", "a", "an", "and", "or", "ping", "ask", "tell", "email", "call", "review",
                "check", "send", "draft", "write", "read", "open", "run", "fix", "add", "update",
                "see", "note", "re", "fw", "fwd", "please", "also", "then", "when", "what", "who"}
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
    __slots__ = ("name", "kind", "aliases", "orgs", "stores", "alias_stores")

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind          # graph | contact | slug | client | store | target | noun | capability
        self.aliases: set[str] = set()
        self.orgs: dict[str, str | None] = {}   # org -> project, from works_at rows
        # Every sub-store directory a `store` entity names. A SET, not one value:
        # PR #308 review round 1 found case-010-lapsus and case-041-lapsus collapsing
        # to one entity whose last writer won, so the other case vanished from the
        # search with no receipt. A recurring subject across cases is the normal
        # shape of investigation work, not an edge.
        self.stores: set[str] = set()
        # alias -> the stores whose graph asserted it. An alias_of edge is one
        # case's knowledge; applied to another case's content it rewrote identity
        # there (PR #308 review round 1, major 2). The project store's aliases
        # apply instance-wide.
        self.alias_stores: dict[str, set[str]] = {}

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "aliases": sorted(self.aliases),
                "stores": sorted(self.stores),
                "alias_stores": {a: sorted(s) for a, s in self.alias_stores.items()}}


def _add(index: dict[str, Entity], name: str, kind: str) -> Entity | None:
    name = normalize_ws(name)
    if not name or len(name) > 80:
        return None
    key = norm(name)
    ent = index.get(key)
    if ent is None:
        ent = Entity(name, kind)
        index[key] = ent
    elif kind in ("contact", "client", "slug", "store", "target", "noun") and ent.kind == "graph":
        ent.kind = kind   # a curated source outranks a graph mention for the fire rule
    return ent


def build_index(stores: dict, substores: list[dict] | None = None) -> dict[str, Entity]:
    """One index over the project store and every sub-store. Curated kinds (a
    store's own name, a target file, a proper noun) outrank a graph mention."""
    index: dict[str, Entity] = {}
    all_stores = [stores] + list(substores or [])
    graph_rows = [r for st in all_stores for r in (st.get("graph_rows") or [])]
    # Which stores contributed each name on their own (as a subject or object).
    # An alias edge may only remove a name from the index when no OTHER store
    # contributed it: case-020's "Widget Corp" is case-020's entity even when
    # case-010 says Widget Corp is an alias of Zeta Holdings.
    contributors: dict[str, set[str]] = {}
    alias_rows: list[dict] = []
    for row in graph_rows:
        s, p, o = row.get("s"), row.get("p"), row.get("o")
        if not isinstance(s, str) or not isinstance(o, str):
            continue
        st_name = row.get("_store") or PROJECT_STORE
        es = _add(index, s, "graph")
        if es is not None:
            contributors.setdefault(norm(s), set()).add(st_name)
        if len(o.split()) <= 4:
            if _add(index, o, "graph") is not None:
                contributors.setdefault(norm(o), set()).add(st_name)
        if p in ALIAS_PREDICATES and es is not None:
            alias_rows.append(row)
        if p in ORG_PREDICATES and es is not None:
            es.orgs[normalize_ws(o)] = row.get("project")
    for row in alias_rows:
        s, p, o = row["s"], row["p"], row["o"]
        st_name = row.get("_store") or PROJECT_STORE
        if ALIAS_PREDICATES[p] == "s_is_alias":
            canonical, alias = _add(index, o, "graph"), normalize_ws(s)
        else:
            canonical, alias = index.get(norm(s)), normalize_ws(o)
        if canonical is None or norm(alias) == norm(canonical.name):
            continue
        canonical.aliases.add(alias)
        canonical.alias_stores.setdefault(alias, set()).add(st_name)
        if contributors.get(norm(alias), set()) <= {st_name}:
            index.pop(norm(alias), None)
    for st in all_stores:
        for name in st.get("contact_names") or []:
            _add(index, name, "contact")
        for slug in st.get("slugs") or []:
            _add(index, slug, "slug")
        for key in st.get("client_keys") or []:
            _add(index, key, "client")
        for name in st.get("target_names") or []:
            ent = _add(index, name, "target")
            # A targets/ file is one case's declaration of a subject; asking about
            # it means that case unless another is named. Without this, a target
            # stem that is also a common word ("miami") fired alone across every
            # case and bypassed the corpus-common rule (PR #308 review round 8).
            if ent is not None and st.get("name") and st["name"] != PROJECT_STORE:
                ent.stores.add(st["name"])
        for name in st.get("noun_names") or []:
            _add(index, name, "noun")
        if st.get("name") and st["name"] != PROJECT_STORE:
            ent = _add(index, store_entity_name(st["name"]), "store")
            if ent is not None:
                ent.kind = "store"
                ent.stores.add(st["name"])
    return index


def store_entity_name(dirname: str) -> str:
    return normalize_ws(STORE_PREFIX_RE.sub("", dirname).replace("-", " ").replace("_", " "))


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


def single_token_hit(tok: str, prompt: str, rule: str) -> bool:
    """THE one place a one-word name is accepted from the prompt: a contact
    heading, an uppercase alias, an identifier kind the manifest lists, or a
    first-name expansion. Every occurrence is checked with the initial-position
    rule, so a sentence-, line- or bullet-initial token never fires on any
    path. ASK-1261: PR #302 round 1 minor 4 and round 5 major were the same
    defect on two paths (one guard, applied to one of them). Two paths, one
    guard, is the repeat; one chokepoint is the fix, and
    test_initial_position_has_one_call_site pins that this is the only caller."""
    if not tok or tok.casefold() in STOPWORDS:
        return False
    if rule == "alias":
        if not (len(tok) >= 4 or tok.isupper()):
            return False
        pat, hay = re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)"), prompt
    elif rule == "identifier":
        if len(tok) < 4:
            return False
        # Matched on the RAW prompt with IGNORECASE and a separator class, so
        # every offset is exact. A casefolded haystack shifts offsets after any
        # casefold-expanding character (PR #304 review).
        parts = re.findall(r"[a-z0-9]+", norm(tok))
        if not parts:
            return False
        pat = re.compile(r"(?<!\w)" + r"[\s_-]+".join(re.escape(p) for p in parts) + r"(?!\w)", re.IGNORECASE)
        hay = prompt
    elif rule == "contact":
        if len(tok) < 4 or not tok[0].isupper():
            return False
        pat, hay = re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)"), prompt
    else:
        return False
    for m in pat.finditer(hay):
        if not is_initial_position(prompt, m.start()):
            return True
    return False


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
        hit_via, hit_name = None, None
        names = [(ent.name, "self")] + [(a, "alias") for a in ent.aliases]
        for name, via in names:
            toks = name.split()
            if len(toks) >= 2:
                if phrase_in(name, pn):
                    hit_via = via
            else:
                tok = toks[0] if toks else ""
                # Every single-token path goes through single_token_hit. The
                # manifest decides which identifier kinds fire on one word (no
                # hardcoded second list, Codex round 1 on PR #302); a graph-only
                # single token never fires alone.
                if via == "alias":
                    if single_token_hit(tok, prompt, "alias"):
                        hit_via = via
                elif ent.kind in fire_alone:
                    if single_token_hit(tok, prompt, "identifier"):
                        hit_via = via
                elif ent.kind == "contact":
                    if single_token_hit(tok, prompt, "contact"):
                        hit_via = via
            if hit_via:
                hit_name = name
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
                      "orgs": sorted(ent.orgs), "aliases": sorted(ent.aliases),
                      "stores": sorted(ent.stores), "via_alias": hit_name if hit_via == "alias" else None,
                      "alias_stores": {a: sorted(s) for a, s in ent.alias_stores.items()}}
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
        seen_tok: set[str] = set()
        for m in re.finditer(r"\b([A-Z][a-z]{3,})\b", prompt):
            tok = m.group(1)
            if tok in seen_tok:
                continue
            seen_tok.add(tok)
            keys = first_tokens.get(tok.casefold()) or []
            if len(keys) == 1 and keys[0] not in found and single_token_hit(tok, prompt, "contact"):
                ent = index[keys[0]]
                found[keys[0]] = {"name": ent.name, "kind": ent.kind, "resolved_from": "first_name",
                                  "ambiguous": len(ent.orgs) >= 2, "project": None,
                                  "orgs": sorted(ent.orgs), "aliases": sorted(ent.aliases),
                                  "stores": sorted(ent.stores), "via_alias": None,
                                  "alias_stores": {a: sorted(s) for a, s in ent.alias_stores.items()}}
    # Longest name wins when one resolved name contains another ("Dana Okafor" vs "Okafor Co").
    out = list(found.values())
    out.sort(key=lambda e: -len(e["name"]))
    kept: list[dict] = []
    for e in out:
        # A store name that is a substring of another resolved name ("zeta" in
        # "Zeta Holdings") is still the scope the founder named; dropping it
        # silently widened the search to every case (PR #308 review round 6).
        if e.get("kind") != "store" and any(norm(e["name"]) != norm(k["name"]) and phrase_in(e["name"], norm(k["name"])) for k in kept):
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


def entity_matches(entity: dict, text: str, store: str | None = None) -> bool:
    """Content-side match. The name matches anywhere; an alias matches only
    content in a store that asserted it (or anywhere, when the project store
    asserted it, or when the caller has no store to name). A prompt-driven
    candidate was admitted case-sensitively and whole-word; it is matched the
    same way by EVERY resolver, or a capitalized common word pulls unrelated
    lowercase lines labelled KNOWN (PR #308 review round 5)."""
    if entity.get("case_sensitive"):
        return word_in_exact(entity["name"], text)
    if phrase_in(entity["name"], norm(text)):
        return True
    scopes = entity.get("alias_stores") or {}
    for a in entity.get("aliases", []):
        allowed = scopes.get(a)
        if store is not None and allowed and store not in allowed and PROJECT_STORE not in allowed:
            continue
        if alias_in_text(a, text):
            return True
    return False


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

def load_stores(qroot: Path, root: Path, manifest: dict | None = None,
                name: str = PROJECT_STORE) -> tuple[dict, dict]:
    """Read every store once. Returns (stores, problems). A store that fails to
    parse lands in problems and counts as present-but-unreadable in the receipt.
    The same loader reads the project qroot and every sub-store directory (a
    4_points case folder has the same layout), so a case's own graph, canonical,
    handoff and documents are read the way the project's are."""
    stores: dict = {"paths": {}, "name": name, "dir": qroot}
    problems: dict = {}
    stores["problems"] = problems
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
                        row["_store"] = name
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
                    # `contact`, never `name`: that is this function's store-name
                    # parameter, and rebinding it here made the sub-store exclusion
                    # below compare against the last contact heading instead
                    # (PR #308 review round 3).
                    contact = re.split(r"\s+[—–-]\s+", head, maxsplit=1)[0].strip()
                    if contact and not contact.startswith("["):
                        contact_names.append(contact)
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
            if isinstance(data, list):
                loops = data
            elif isinstance(data, dict):
                loops = data.get("loops") or []
            else:
                problems["loops"] = f"not an object or a list: {type(data).__name__}"   # sp-a4a5028a
            if not isinstance(loops, list):
                problems["loops"] = "loops is not a list"
                loops = []
        except (OSError, ValueError) as exc:
            problems["loops"] = str(exc)
    stores["loops"] = [l for l in loops if isinstance(l, dict)]

    folders = list((manifest or {}).get("folders") or [])
    max_bytes = int((manifest or {}).get("doc_max_bytes") or DOC_MAX_BYTES_DEFAULT)
    # The project walk never enters a sub-store root: each case is loaded by
    # its own call, and the project's rglob("*") over 4_points was 57,081
    # entries and 318 ms per prompt (measured 2026-09-05).
    exclude = {path for _, path in discover_stores(qroot, manifest or {})} if name == PROJECT_STORE else set()
    skip_dirs = set((manifest or {}).get("skip_dirs") if (manifest or {}).get("skip_dirs") is not None else DEFAULT_SKIP_DIRS)
    skipped: list[Path] = []
    skipped_dirs: list[Path] = []
    stores["doc_files"] = enumerate_docs(qroot, folders, max_bytes, exclude, skipped, skip_dirs, skipped_dirs) if folders else []
    stores["doc_skipped_oversize"] = skipped
    stores["doc_skipped_dirs"] = skipped_dirs
    # A markdown file directly under a `targets`-style directory names a subject
    # of the work (4_points: investigation/targets/<subject>.md). Its stem is an
    # entity that fires alone; a finding or note file's stem never does.
    target_names = []
    entity_dirs = set((manifest or {}).get("entity_dirs") or [])
    if entity_dirs:
        for d in walk_dirs(qroot, exclude, ENTITY_DIR_MAX_DEPTH, skip_dirs):
            if d.name not in entity_dirs:
                continue
            for f in sorted(d.glob("*.md")):
                if not f.name.startswith("_") and not f.name.startswith("."):
                    target_names.append(normalize_ws(f.stem.replace("-", " ").replace("_", " ")))
    stores["target_names"] = target_names
    # canonical/proper-nouns.txt is the voice lint's curated name list (its own
    # header says to keep common words out), which makes it a safe fire-alone
    # index source for a project with no graph yet (a consulting instance with no graph, 2026-09-05).
    nouns = []
    pn = qroot / "canonical" / "proper-nouns.txt"
    if pn.is_file():
        try:
            for line in read_lines(pn):
                s = line.strip()
                if s and not s.startswith("#"):
                    nouns.append(s)
        except OSError as exc:
            problems["nouns"] = str(exc)
    stores["noun_names"] = nouns
    return stores, problems


def walk_dirs(base: Path, exclude: set[Path], max_depth: int, skip_dirs: set[str] | None = None):
    """Pruned directory walk: dot dirs, tooling dirs, declared skip dirs and
    `exclude` (sub-store roots) are never entered, and nothing below max_depth is."""
    base_depth = len(base.parts)
    skips = HARD_SKIP_DIRS | set(skip_dirs or ())
    for dirpath, dirnames, _ in os.walk(base):
        cur = Path(dirpath)
        if len(cur.parts) - base_depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in skips
                                 and (cur / d) not in exclude)
        yield cur


def enumerate_docs(store_dir: Path, folders: list[str], max_bytes: int,
                   exclude: set[Path] | None = None, skipped: list[Path] | None = None,
                   skip_dirs: set[str] | None = None, skipped_dirs: list[Path] | None = None) -> list[Path]:
    """The markdown files of a store's declared folders, in a stable order. Dot
    dirs, tooling dirs, sub-store roots, dot files and last-handoff.md (the
    handoff class owns it) are skipped silently; a DECLARED skip (a manifest
    skip_dirs name, a file over doc_max_bytes) is recorded in `skipped_dirs` /
    `skipped` so the receipt and the header can say so."""
    out: list[Path] = []
    excl = exclude or set()
    declared = set(skip_dirs or ())
    for folder in folders:
        base = store_dir / folder
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            cur = Path(dirpath)
            keep = []
            for d in sorted(dirnames):
                if d.startswith(".") or d in HARD_SKIP_DIRS or (cur / d) in excl:
                    continue
                if d in declared:
                    if skipped_dirs is not None:
                        skipped_dirs.append(cur / d)
                    continue
                keep.append(d)
            dirnames[:] = keep
            for fn in sorted(filenames):
                if not fn.endswith(".md") or fn.startswith(".") or fn == "last-handoff.md":
                    continue
                f = Path(dirpath) / fn
                try:
                    if f.stat().st_size > max_bytes:
                        # A declared exclusion (manifest doc_max_bytes), not a
                        # truncation, so coverage stays FULL; the receipt counts
                        # it so a reader can see what was never opened (PR #308
                        # review round 6).
                        if skipped is not None:
                            skipped.append(f)
                        continue
                except OSError:
                    continue
                out.append(f)
    return out


def discover_stores(qroot: Path, manifest: dict) -> list[tuple[str, Path]]:
    """(dirname, path) for every directory a manifest `stores` glob matches.
    A glob that matches nothing costs nothing, so the default ships it fleet-wide."""
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for spec in manifest.get("stores") or []:
        glob = spec.get("glob") if isinstance(spec, dict) else None
        if not glob or ".." in glob:
            continue
        for d in sorted(qroot.glob(glob)):
            if d.is_dir() and d not in seen and not d.name.startswith("."):
                seen.add(d)
                out.append((d.name, d))
    return out


def load_all_stores(qroot: Path, root: Path, manifest: dict) -> tuple[dict, list[dict], dict]:
    """The project store plus every sub-store. Problems of the project store come
    back as before; a sub-store's live on that store dict under `problems`."""
    project, problems = load_stores(qroot, root, manifest, PROJECT_STORE)
    subs = [load_stores(path, root, manifest, name)[0] for name, path in discover_stores(qroot, manifest)]
    return project, subs, problems


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
    st_name = stores.get("name")
    rows = [r for r in stores["graph_rows"]
            if isinstance(r.get("s"), str) and isinstance(r.get("o"), str)
            and (entity_matches(entity, r["s"], st_name) or entity_matches(entity, r["o"], st_name))
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
            if len({g.get("t") for g in grp[:2]}) == 1 and len({norm(g["o"]) for g in grp[:2]}) > 1:
                conflict_keys.add(key)   # sp-67d54572: two newest agree -> the older row is STALE, not CONFLICTING
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
                      files: list[Path] | None = None, errors: dict | None = None,
                      cls: str = "canonical") -> list[dict]:
    items = []
    for path in (files if files is not None else stores["canonical_files"]):
        st = stores.setdefault("read_stats", {}).setdefault(cls, {"files": set(), "failed": set()})
        st["files"].add(str(path))
        try:
            lines = read_lines(path)
        except OSError as exc:
            # sp-ca1769db: an unreadable file is a recorded problem, never a
            # silent skip that reads as "present, 0 hits" under FULL. The
            # class is UNREADABLE only when every file failed (read_stats),
            # never from zero hits: PR #304 review found one unreadable file
            # among readable ones marking the whole class unreadable on an
            # entity with no hits, a false PARTIAL.
            st["failed"].add(str(path))
            if errors is not None:
                errors[cls] = f"{path.name}: {exc}"
            continue
        t = mtime_date(path)
        in_fence = False
        for n, line in enumerate(lines, start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            if entity_matches(entity, line, stores.get("name")):
                items.append(_item(entity["name"], kind, line.strip(), path, n, t, root,
                                   status=status_for_line(line)))
    items.sort(key=lambda i: (i["t"] or ""), reverse=True)
    return items


def resolve_blocks(entity: dict, path: Path, root: Path, kind: str, max_lines: int,
                   errors: dict | None = None, cls: str = "", stores: dict | None = None) -> list[dict]:
    """### blocks in relationships.md / decisions.md that mention the entity."""
    if not path.is_file():
        return []
    st = None
    if stores is not None:
        st = stores.setdefault("read_stats", {}).setdefault(cls or kind, {"files": set(), "failed": set()})
        st["files"].add(str(path))
    try:
        lines = read_lines(path)
    except OSError as exc:
        if st is not None:
            st["failed"].add(str(path))
        if errors is not None:
            errors[cls or kind] = f"{path.name}: {exc}"   # sp-ca1769db
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
        if not entity_matches(entity, target if kind == "relationship" else joined,
                              (stores or {}).get("name")):
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
        if not (entity_matches(entity, slug, stores.get("name")) or entity_matches(entity, promise, stores.get("name"))):
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
    st_name = stores.get("name")
    for key, rows in stores["meetings"].items():
        key_hit = entity_matches(entity, key, st_name)
        for r in rows:
            if not isinstance(r, dict):
                continue
            title, summary = str(r.get("title") or ""), str(r.get("summary") or "")
            if not (key_hit or entity_matches(entity, title, st_name) or entity_matches(entity, summary, st_name)):
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
        if not (entity_matches(entity, title, stores.get("name")) or entity_matches(entity, nxt, stores.get("name"))):
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
    # cls="handoff": the read failure lands under the handoff class, never under
    # canonical's read_stats (PR #308 review round 8, pre-existing from #302).
    items = resolve_canonical(entity, stores, root, kind="handoff", files=[path],
                              errors=stores.get("problems"), cls="handoff")
    return [i for i in items if in_window(i["t"], window)]


def pattern_variants(name: str) -> list[str]:
    """The spellings a name takes on disk: the name, and its `-` and `_` joins
    (the phrase rule folds those to spaces on the prompt side; grep -F does not)."""
    n = normalize_ws(name)
    if len(n) < 4:
        return []   # a short initialism over a corpus is noise (alias "DO", PR #302 round 1)
    out = [n]
    if " " in n:
        out += [n.replace(" ", "-"), n.replace(" ", "_")]
    return out


def grep_binary() -> str | None:
    return shutil.which("grep")


HIT_RE = re.compile(r"^(?P<path>.+?):(?P<n>\d+):(?P<text>.*)$")


GREP_ERR_RE = re.compile(r"^grep: (?P<path>.+?): (?P<err>.+)$")


def _grep(files: list[Path], patterns: list[str], *, ignore_case: bool, word: bool,
          deadline: float, failed: list[Path] | None = None) -> tuple[list[tuple[Path, int, str]], str] | None:
    """One fixed-string grep over the files, chunked. None when grep is not on
    PATH (the caller falls back to the Python scan). BSD grep 2.6 and GNU grep
    share every flag used here. The timeout is the remaining deadline, so a
    killed hook still returns what it gathered plus a receipt naming the stop."""
    binary = grep_binary()
    if binary is None or not files or not patterns:
        return None if binary is None else ([], "grep")
    # -m is the cap PLUS ONE: a file that yields cap+1 lines was truncated, a file
    # that yields exactly cap was read to its end (PR #308 review round 7: the
    # cap fired at exactly 200 matches and reported PARTIAL for nothing unread).
    args = [binary, "-n", "-H", "-I", "-F", "-m", str(GREP_MAX_PER_FILE + 1)] + (["-i"] if ignore_case else []) + (["-w"] if word else [])
    for pat in patterns:
        args += ["-e", pat]
    args.append("--")
    hits: list[tuple[Path, int, str]] = []
    engine = "grep"
    per_file: dict[str, int] = {}
    for i in range(0, len(files), GREP_CHUNK):
        remaining = deadline - time.time()
        if remaining <= 0.05:
            return hits, "grep (deadline)"
        chunk = [str(f) for f in files[i:i + GREP_CHUNK]]
        try:
            cp = subprocess.run(args + chunk, capture_output=True, text=True, errors="replace",
                                timeout=max(0.2, remaining))
        except subprocess.TimeoutExpired:
            return hits, "grep (timeout)"
        except OSError:
            return None
        # grep reports a file it could not open on stderr ("grep: <path>: No such
        # file or directory") and exits 2. Those files were enumerated and never
        # read; they go to the caller's `failed` list, the same read accounting
        # every other class has (PR #308 review round 7: the docs class was the
        # one required class with no read-failure path, and a file deleted
        # between enumeration and the grep reported "searched, 0 hits").
        if failed is not None and cp.returncode == 2 and cp.stderr:
            for eline in cp.stderr.splitlines():
                em = GREP_ERR_RE.match(eline.strip())
                if em:
                    failed.append(Path(em.group("path")))
        for line in cp.stdout.splitlines():
            m = HIT_RE.match(line)
            if m:
                per_file[m.group("path")] = per_file.get(m.group("path"), 0) + 1
                if per_file[m.group("path")] > GREP_MAX_PER_FILE:
                    # the cap+1-th line: -m stopped reading that file, lines past
                    # the cap were never looked at (PR #308 review round 4). The
                    # extra line is not kept, so both engines return exactly cap.
                    engine = "grep (file cap)"
                    continue
                hits.append((Path(m.group("path")), int(m.group("n")), m.group("text")))
                if len(hits) >= MAX_DOC_HITS:
                    return hits, "grep (hit cap)"
    return hits, engine


def _pyscan(files: list[Path], patterns: list[str], *, ignore_case: bool, word: bool,
            deadline: float, budget_bytes: int = DOC_SCAN_BUDGET_BYTES,
            failed: list[Path] | None = None) -> tuple[list[tuple[Path, int, str]], str]:
    """The grep-less path: same substring / whole-word semantics, bounded by a
    byte budget and the deadline, both reported in the engine string."""
    alts = "|".join(re.escape(p) for p in patterns)
    body = f"(?<!\\w)(?:{alts})(?!\\w)" if word else f"(?:{alts})"
    pat = re.compile(body, re.IGNORECASE if ignore_case else 0)
    hits: list[tuple[Path, int, str]] = []
    used, engine = 0, "python"
    for f in files:
        if time.time() > deadline:
            return hits, "python (deadline)"
        try:
            data = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            if failed is not None:
                failed.append(f)   # counted, never swallowed (PR #308 review round 7)
            continue
        used += len(data)
        in_file = 0
        for n, line in enumerate(data.splitlines(), start=1):
            if pat.search(line):
                in_file += 1
                if in_file > GREP_MAX_PER_FILE:
                    engine = "python (file cap)"   # parity with grep -m cap+1, and the same receipt
                    break
                hits.append((f, n, line))
                if len(hits) >= MAX_DOC_HITS:
                    return hits, "python (hit cap)"
        if used > budget_bytes:
            return hits, "python (budget)"
    return hits, engine


def truncation_of(engine: str | None) -> str | None:
    """The reason a docs pass stopped early, or None when it ran to the end."""
    for marker in TRUNCATION_MARKERS:
        if marker in (engine or ""):
            return marker.strip("()")
    return None


def class_search_state(stopped_cold: bool, truncated: str | None, present: bool = True) -> bool | str:
    """THE one place that says how far a class was searched: False (never
    started, which includes a class that is absent), "partial" (started and
    cut short, for any reason), True. A class that is not True never counts
    toward FULL. PR #308 review round 9: an absent class read searched=True."""
    if stopped_cold or not present:
        return False
    return "partial" if truncated else True


def search_docs(files: list[Path], patterns: list[str], *, ignore_case: bool, word: bool,
                deadline: float, failed: list[Path] | None = None) -> tuple[list[tuple[Path, int, str]], str]:
    """`failed` collects the enumerated files the engine could not read. The
    readability check is made HERE, before either engine runs, so it does not
    depend on how a given grep reports an unreadable file (PR #308 review round
    7 fix reported it on BSD grep and CI's GNU grep stayed silent): a file that
    vanished or lost read permission between enumeration and the search is
    recorded and never handed to the engine."""
    if not files or not patterns:
        return [], "none"
    readable: list[Path] = []
    for f in files:
        if os.access(f, os.R_OK):
            readable.append(f)
        elif failed is not None:
            failed.append(f)
    if not readable:
        return [], "grep" if grep_binary() else "python"
    r = _grep(readable, patterns, ignore_case=ignore_case, word=word, deadline=deadline, failed=failed)
    if r is None:
        return _pyscan(readable, patterns, ignore_case=ignore_case, word=word, deadline=deadline, failed=failed)
    return r


def doc_candidates(scan: str, entities: list[dict], index: dict[str, Entity]) -> list[str]:
    """What the prompt names that the index cannot resolve, in proper-noun shape:
    capitalized bigrams (the misses ledger's rule) and capitalized single words
    of 4+ letters that are not sentence-, line- or bullet-initial (through
    single_token_hit, the one chokepoint). A word that is the first token of an
    index entity is left to the first-name rule, which owns that ambiguity."""
    resolved = [norm(e["name"]) for e in entities] + [norm(a) for e in entities for a in e.get("aliases", [])]
    first_tokens = {ent.name.split()[0].casefold() for ent in index.values() if ent.name.split()}
    out: list[str] = []
    seen: set[str] = set()
    consumed: set[str] = set()
    for m in CAP_BIGRAM_RE.finditer(scan):
        a, b = m.group(1), m.group(2)
        if a.casefold() in STOPWORDS or b.casefold() in STOPWORDS or a.casefold() in MISS_OPENERS:
            continue
        cand = f"{a} {b}"
        cn = norm(cand)
        if cn in seen or any(cn in r or r in cn for r in resolved):
            # A bigram the resolver already covers ("ShinyHunters Crew" behind
            # the store shinyhunters) takes BOTH its halves out of the single-word
            # pass, or the generic half ("Crew") becomes a subject on its own
            # and pulls unrelated lines labelled KNOWN (PR #308 review round 11).
            consumed.update({a.casefold(), b.casefold()})
            continue
        seen.add(cn)
        out.append(cand)
    for m in re.finditer(r"\b([A-Z][a-z]{3,})\b", scan):
        tok = m.group(1)
        tn = tok.casefold()
        if tn in seen or tn in consumed or tn in STOPWORDS or tn in MISS_OPENERS or tn in first_tokens:
            continue
        if any(tn in r.split() for r in resolved) or any(tn in s.split() for s in seen):
            continue
        if not single_token_hit(tok, scan, "contact"):
            continue
        seen.add(tn)
        out.append(tok)
    return out[:MAX_DOC_CANDIDATES]


def search_docs_for_candidates(cands: list[str], search_stores: list[dict], root: Path,
                               deadline: float) -> tuple[dict[str, list[tuple[Path, int, str, str]]], str]:
    """Case-sensitive, whole-word, headings excluded: a heading is a section label
    (the 2026-09-05 census over every 4_points case: Notes, Summary, Integrity),
    so "Next Steps" in a prompt never resolves to the heading that says so.
    Each hit carries its store so the caller can apply MAX_CANDIDATE_STORES."""
    file_store: dict[str, str] = {}
    for st in search_stores:
        for f in st.get("doc_files") or []:
            file_store[str(f)] = st["name"]
    files = [Path(f) for f in file_store]
    hits, engine = search_docs(files, cands, ignore_case=False, word=True, deadline=deadline)
    out: dict[str, list[tuple[Path, int, str, str]]] = {}
    for i, (f, n, text) in enumerate(hits):
        # The deadline ALWAYS ends the fold; the suffix is only added when the
        # engine string does not already carry a stop reason. PR #308 review
        # round 3: with the guard on the whole condition, a search that had
        # already hit the cap ran the fold unbounded past the hook timeout.
        if i % 500 == 0 and time.time() > deadline:
            if not truncation_of(engine):
                engine += " (deadline)"
            break
        s = text.strip()
        if not s or s.startswith("#"):
            continue
        for c in cands:
            if word_in_exact(c, text):
                out.setdefault(c, []).append((f, n, text, file_store.get(str(f), PROJECT_STORE)))
    return out, engine


def resolve_docs(entities: list[dict], search_stores: list[dict], root: Path,
                 candidate_hits: dict[str, list[tuple[Path, int, str, str]]],
                 deadline: float, candidate_engine: str = "none") -> tuple[dict[str, dict[str, list[dict]]], dict]:
    """entity key -> store name -> items, newest file first. One grep over every
    document of the stores in scope for the index entities; the candidates'
    hits were gathered before classification and are folded in here."""
    file_store: dict[str, str] = {}
    for st in search_stores:
        for f in st.get("doc_files") or []:
            file_store[str(f)] = st["name"]
    files = [Path(f) for f in file_store]
    index_ents = [e for e in entities if e.get("kind") != "docs_hit"]
    patterns: list[str] = []
    for e in index_ents:
        for nm in [e["name"], *e.get("aliases", [])]:
            for v in pattern_variants(nm):
                if v not in patterns:
                    patterns.append(v)
    # Readability is accounted for EVERY enumerated file before any search, so an
    # index of 0 (no patterns, early return inside search_docs) cannot leave an
    # unreadable store invisible under FULL (PR #308 review round 10).
    failed: list[Path] = [f for f in files if not os.access(f, os.R_OK)]
    hits, engine = search_docs(files, patterns, ignore_case=True, word=False, deadline=deadline, failed=failed)
    # The same read accounting every file class has: per store, the files the
    # engine was asked to read and the ones it could not. A store whose every
    # doc failed is unreadable (degrades the class); one failed among readable
    # ones is a recorded problem (PR #304, sp-ca1769db). Counted whether or not
    # the entity had a hit there: the engine was asked to read them all.
    by_store_files: dict[str, set[str]] = {}
    for f_s, st_name in file_store.items():
        by_store_files.setdefault(st_name, set()).add(f_s)
    for st in search_stores:
        st_files = by_store_files.get(st["name"], set())
        if not st_files:
            continue
        rs = st.setdefault("read_stats", {}).setdefault("docs", {"files": set(), "failed": set()})
        rs["files"] |= st_files
        rs["failed"] |= {str(f) for f in failed if str(f) in st_files}
        if rs["failed"]:
            st["problems"]["docs"] = f"{len(rs['failed'])} of {len(rs['files'])} doc file(s) unreadable"
    mtimes: dict[str, str | None] = {}
    mtimes_ns: dict[str, int] = {}

    def t_of(f: Path) -> str | None:
        k = str(f)
        if k not in mtimes:
            mtimes[k] = mtime_date(f)
            try:
                mtimes_ns[k] = f.stat().st_mtime_ns
            except OSError:
                mtimes_ns[k] = 0
        return mtimes[k]

    out: dict[str, dict[str, list[dict]]] = {}
    for i, (f, n, text) in enumerate(hits):
        # The deadline ALWAYS ends the fold; the suffix is only added when the
        # engine string does not already carry a stop reason. PR #308 review
        # round 3: with the guard on the whole condition, a search that had
        # already hit the cap ran the fold unbounded past the hook timeout.
        if i % 500 == 0 and time.time() > deadline:
            if not truncation_of(engine):
                engine += " (deadline)"
            break
        s = text.strip()
        if not s:
            continue
        store = file_store.get(str(f), PROJECT_STORE)
        for e in index_ents:
            if not store_in_scope_of(e, store):
                continue
            if entity_matches(e, text, store):
                out.setdefault(norm(e["name"]), {}).setdefault(store, []).append(
                    _item(e["name"], "doc", s, f, n, t_of(f), root, status=status_for_line(text)))
    for e in entities:
        if e.get("kind") != "docs_hit":
            continue
        for f, n, text, store in candidate_hits.get(e["name"], []):
            out.setdefault(norm(e["name"]), {}).setdefault(store, []).append(
                _item(e["name"], "doc", text.strip(), f, n, t_of(f), root, status=status_for_line(text)))
    # Order inside one entity and store: newest FILE first by full mtime (the
    # displayed t is a date, and every file of a fresh checkout shares one), then
    # the file that mentions the entity most, then path and line ascending. PR #308
    # review round 4: a plain reverse sort on "date, src" kept the alphabetically
    # last filler files and dropped the one answer file under a "newest first" header.
    for by_store in out.values():
        for lst in by_store.values():
            per_file: dict[str, int] = {}
            for it in lst:
                per_file[it["abs_src"]] = per_file.get(it["abs_src"], 0) + 1
            lst.sort(key=lambda i: (-mtimes_ns.get(i["abs_src"], 0), -per_file[i["abs_src"]],
                                    i["abs_src"], int(i["src"].rsplit(":", 1)[-1] or 0)))
    # `stop` is the truth the class state reads; the engine string is display.
    # Each pass is inspected on its own, so a composed label can never hide a
    # stop: PR #308 review round 6 found "grep (candidates file cap)", built
    # here in round 3, which the marker parser could not read, and a required
    # docs class went FULL with 100 lines never looked at. Fourth path for the
    # same class; the fix is a field, not another string format.
    stop = truncation_of(engine) or truncation_of(candidate_engine)
    if engine == "none" and candidate_hits:
        engine = candidate_engine   # only the candidate pass ran (an index of 0)
    elif truncation_of(candidate_engine) and not truncation_of(engine):
        engine += f" (candidates: {candidate_engine})"
    return out, {"files": len(files), "engine": engine, "stop": stop}


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
    """Two passes at most: if the first leaves a store with nothing, the note
    that names it is on the wire, so the second pass pays for the note up
    front (PR #308 review round 8: the note pushed the render 128 chars past
    the ceiling with every remaining line pinned and nothing left to drop)."""
    kept, cut, ceiling_hit = _assemble(items, entities, ceiling, header_len)
    cut_stores = stores_cut_by_ceiling(items, kept)
    if cut_stores:
        reserve = len(ceiling_note_text(cut_stores)) + 8
        kept, cut, ceiling_hit = _assemble(items, entities, ceiling - reserve, header_len)
    return kept, cut, ceiling_hit


def _assemble(items: list[dict], entities: list[dict], ceiling: int, header_len: int) -> tuple[list[dict], int, bool]:
    """Order, dedupe, and cut to the ceiling. The newest graph item per entity is
    pinned first so a cut can never drop the one fact most likely to be current."""
    order = {norm(e["name"]): i for i, e in enumerate(entities)}
    seen: set[tuple] = set()
    deduped = []
    for it in items:
        if it["kind"] == "graph" and len(it["text"]) > ITEM_MAX_CHARS:
            # Graph triples only: a relationship block is a 12-line excerpt by
            # design and was being cut at 600 (PR #304 review).
            it["text"] = it["text"][:ITEM_MAX_CHARS] + f" [cut at {ITEM_MAX_CHARS} chars; open src]"
        # sp-1b3ef442: a shared line stays under each named entity; PR #308 review
        # round 6: and under each STORE, or an identical line in two cases collapsed
        # to one while the receipt said both stores hit and the footer said cut=0.
        key = (norm(it["entity"]), it["kind"], norm(it["text"]), it.get("store"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    deduped = collapse_identical_blocks(deduped, entities)
    recency = store_recency(deduped)
    deduped.sort(key=item_order(order, recency))  # stable: resolver order survives inside a tier (open commitments first, newest first)
    pinned: set[int] = set()
    seen_ent: set[str] = set()
    for idx, it in enumerate(deduped):
        if it["kind"] == "graph" and norm(it["entity"]) not in seen_ent:
            pinned.add(idx)
            seen_ent.add(norm(it["entity"]))
    used = header_len
    kept, cut, ceiling_hit = [], 0, False
    blocks: set[tuple[str, str]] = set()

    def cost_of(it: dict) -> tuple[int, tuple[str, str]]:
        # A block heading ("== name [store] ==") is on the wire too. Uncounted, 40
        # case headings put the rendered text 1,553 chars past the ceiling while
        # the budget said it fit (PR #308 review round 8, measured).
        key = (norm(it["entity"]), it.get("store") or PROJECT_STORE)
        c = len(render_item(it)) + 1
        if key not in blocks:
            c += len(f"== {block_label(it)} ==") + 1
        return c, key

    # Pins are reserved FIRST and always kept, so their cost sits inside `used`
    # before the fill starts. If the pins alone overrun the ceiling, that is
    # REPORTED (ceiling_hit, overflow), never hidden: Codex round 2 on PR #302
    # found pinned items slipping past the ceiling under cut=0, ceiling_hit=False.
    for idx, it in enumerate(deduped):
        it["pinned"] = idx in pinned
    for idx in sorted(pinned):
        c, key = cost_of(deduped[idx])
        used += c
        blocks.add(key)
        kept.append(deduped[idx])
    if used > ceiling:
        ceiling_hit = True
    # Then one line per (entity, store), newest store first, WHILE IT FITS: a
    # store with a hit is never dropped whole because a newer store had more to
    # say; a store that gets no line is named on the wire (stores_cut). PR #308
    # review round 8: the fill kept case-001..006 by directory name and cut the
    # case that held the answer.
    seen_store: set[tuple[str, str]] = {(norm(deduped[i]["entity"]), deduped[i].get("store") or PROJECT_STORE) for i in pinned}
    for idx, it in enumerate(deduped):
        if idx in pinned:
            continue
        key = (norm(it["entity"]), it.get("store") or PROJECT_STORE)
        if key in seen_store:
            continue
        seen_store.add(key)
        c, _ = cost_of(it)
        if not ceiling_hit and used + c <= ceiling:
            pinned.add(idx)
            it["pinned"] = True
            blocks.add(key)
            used += c
            kept.append(it)
    # The first cut ends the fill for everything else. A per-item check would
    # let a short low-tier line slip into the gap left after a higher-tier cut,
    # which reorders priority by accident (measured: the pin mutation survived
    # until this was a hard stop).
    for idx, it in enumerate(deduped):
        if idx in pinned:
            continue
        c, key = cost_of(it)
        if not ceiling_hit and used + c <= ceiling:
            kept.append(it)
            blocks.add(key)
            used += c
        else:
            cut += 1
            ceiling_hit = True
    kept.sort(key=item_order(order, recency))  # stable: resolver order survives inside a tier (open commitments first, newest first)
    return kept, cut, ceiling_hit


def store_in_scope_of(entity: dict, store_name: str) -> bool:
    """A target entity's items come from the cases that declared it, plus the
    project level; every other entity reads every store in scope."""
    if entity.get("kind") != "target" or not entity.get("stores"):
        return True
    return store_name == PROJECT_STORE or store_name in entity["stores"]


def stores_for(entity: dict, search_stores: list[dict]) -> list[dict]:
    return [st for st in search_stores if store_in_scope_of(entity, st["name"])]


def store_recency(items: list[dict]) -> dict[str, str]:
    """store -> the newest item date it carries. The project store always ranks
    first; the cases rank newest first, never by directory name: PR #308 review
    round 8 measured the ceiling keeping case-001..006 and cutting the case that
    held the answer because "case-040" sorts last."""
    newest: dict[str, str] = {}
    for it in items:
        st = it.get("store") or PROJECT_STORE
        t = it.get("t") or ""
        if t > newest.get(st, ""):
            newest[st] = t
    return newest


def item_order(order: dict[str, int], recency: dict[str, str] | None = None):
    """Entity, then the project block, then each case block newest first, then
    tier. A name carried by two cases is two blocks, never one identity (PR #308
    review round 2)."""
    rec = recency or {}

    def key(i: dict):
        store = i.get("store") or PROJECT_STORE
        return (order.get(norm(i["entity"]), 99), 0 if store == PROJECT_STORE else 1,
                "" if store == PROJECT_STORE else rec.get(store, ""), store, TIER.get(i["kind"], 9))

    def wrapped(i: dict):
        k = key(i)
        # Newest date first, and on a tie the HIGHER case number first: in a
        # case-NNN scheme the number grows with time, and a fresh checkout gives
        # every doc one date (PR #308 review round 8). Both descend by sorting on
        # the negated code points.
        return (k[0], k[1], tuple(-ord(c) for c in k[2]), tuple(-ord(c) for c in k[3]), k[4])
    return wrapped


def block_label(it: dict) -> str:
    store = it.get("store") or PROJECT_STORE
    name = ", ".join([it["entity"], *it.get("co_entities", [])])
    return name if store == PROJECT_STORE else f"{name} [{store}]"


def collapse_identical_blocks(items: list[dict], entities: list[dict]) -> list[dict]:
    """Two entities whose blocks in one store carry the SAME set of lines are one
    block under one heading naming both. A line naming two people still renders
    under each of them when their blocks differ (sp-1b3ef442); only a byte-identical
    second block is dropped, because it spends the cap twice and reads like two
    sources corroborating one claim (PR #308 review round 11)."""
    order = {norm(e["name"]): i for i, e in enumerate(entities)}
    blocks: dict[tuple[str, str], list[dict]] = {}
    for it in items:
        blocks.setdefault((norm(it["entity"]), it.get("store") or PROJECT_STORE), []).append(it)
    signature: dict[tuple[str, str], tuple] = {k: tuple(sorted((i["kind"], norm(i["text"])) for i in v)) for k, v in blocks.items()}
    dropped: set[tuple[str, str]] = set()
    keys = sorted(blocks, key=lambda k: (k[1], order.get(k[0], 99)))
    for i, a in enumerate(keys):
        if a in dropped:
            continue
        for b in keys[i + 1:]:
            if b in dropped or b[1] != a[1] or signature[a] != signature[b]:
                continue
            dropped.add(b)
            name_b = blocks[b][0]["entity"]
            for it in blocks[a]:
                it.setdefault("co_entities", [])
                if name_b not in it["co_entities"]:
                    it["co_entities"].append(name_b)
    return [it for it in items if (norm(it["entity"]), it.get("store") or PROJECT_STORE) not in dropped]


def render_item(it: dict) -> str:
    tag = it["status"]
    if it["supersedes"]:
        tag += f", superseded by {it['supersedes'].split('/')[-1]}"
    kind = it["kind"] + (f"/{it['predicate']}" if it.get("predicate") else "")
    text = it["text"].replace("\n", "\n    ")
    return f"- [{tag} {it['t'] or 'undated'} {kind}] {text}  ({it['src']})"


def deadline_note(bundle: dict) -> str:
    """The one line that turns a killed hook into a receipt: where the pass
    stopped, and that every class after it was NOT searched."""
    parts = []
    d = bundle.get("deadline_hit")
    if d:
        parts.append(f" DEADLINE: stopped after {d['elapsed_ms']} ms at {d['at_class']}/{d['at_entity']}; "
                     "classes after it were NOT searched.")
    dropped = bundle.get("entities_dropped") or []
    if dropped:
        parts.append(f" ENTITIES DROPPED (cap {MAX_ENTITIES}): {', '.join(dropped)}.")
    cut_stores = (bundle.get("budget") or {}).get("stores_cut") or []
    if cut_stores:
        parts.append(ceiling_note_text(cut_stores))
    sk = bundle.get("declared_skips") or {}
    if sk.get("files") or sk.get("dirs"):
        # A declared exclusion keeps FULL, but the model reads only the header,
        # so the header says what was never opened (PR #308 review round 11).
        parts.append(f" SKIPPED (declared): {sk.get('files', 0)} file(s) over doc_max_bytes, "
                     f"{sk.get('dirs', 0)} dir(s) in skip_dirs; the receipt lists them.")
    return "".join(parts)


def ceiling_note_text(cut_stores: list[str]) -> str:
    """Bounded: six names and a count, so the disclosure never eats the budget."""
    shown = ", ".join(cut_stores[:6]) + (f" and {len(cut_stores) - 6} more" if len(cut_stores) > 6 else "")
    return f" CEILING: {len(cut_stores)} store(s) with hits reached you with nothing: {shown} (full list in the receipt)."


def render_header(bundle: dict) -> str:
    cov = bundle["coverage"]
    if cov["verdict"] == "FULL":
        line = "[knowledge-supply] COVERAGE: FULL."
    else:
        miss = "; ".join(f"{m} ({bundle['coverage']['missing_paths'].get(m, 'absent')})" for m in cov["missing"])
        line = f"[knowledge-supply] COVERAGE: {cov['verdict']}. missing: {miss}."
    line += scope_note(cov)
    def bounded(names: list[str]) -> str:
        return ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")

    def suffix(e: dict) -> str:
        if e.get("kind") == "store" and e.get("stores"):
            return f" [{bounded(e['stores'])}]"
        if e.get("kind") == "target" and e.get("stores"):
            return f" [target of {bounded(e['stores'])}]"
        if e.get("kind") == "docs_hit":
            return " [docs]"
        out = ""
        via = e.get("via_alias")
        if via:
            asserted = (e.get("alias_stores") or {}).get(via) or []
            out += f" (via alias {via}" + (f": {', '.join(asserted)}" if asserted else "") + ")"
        if e["ambiguous"]:
            out += " (ambiguous: " + " | ".join(e["orgs"]) + ")"
        return out
    ents = ", ".join(e["name"] + suffix(e) for e in bundle["entities"]) or "none"
    win = bundle.get("window")
    win_s = f" window={win['from']}..{win['to']}" if win else ""
    win_s += deadline_note(bundle)
    return (f"{line} task={bundle['task_class']} entities={ents}.{win_s}\n"
            "[knowledge-supply] Hierarchy: graph beats canonical beats notes (q-system/methodology/anti-hallucination.md). "
            "Verbatim excerpts, newest first, each with path:line; open the src before asserting it. "
            "This layer never infers; anything you add beyond these lines is INFERRED and yours to label.")


def scope_note(cov: dict) -> str:
    """One clause naming what a named case left out of the search. The verdict
    word is relative to the scope and the clause says so, because the engine
    cannot tell "in jennica pounds, ..." from an incidental "post it on
    Facebook" matching case-005-facebook (PR #308 review rounds 7 and 8)."""
    excluded = cov.get("stores_excluded") or []
    if cov.get("scope") and excluded:
        scope = cov["scope"]
        shown = ", ".join(scope[:6]) + (f" and {len(scope) - 6} more" if len(scope) > 6 else "")
        n = len(excluded)
        return (f" WITHIN SCOPE {shown} + project only; {n} other store{'s' if n != 1 else ''} "
                f"not searched (name a different case, or none, to widen).")
    return ""   # nothing excluded: nothing to disclose, and no budget spent saying so (round 9 minor 2)


def render(bundle: dict) -> str:
    if bundle.get("note") and not bundle["items"]:
        return bundle["note"]
    if not bundle["items"]:
        # An entity resolved and every declared store was searched and held
        # nothing: one line, not an 800-char header. Codex round 3 on PR #302.
        # It is still a line and not zero bytes on purpose: "searched, nothing
        # recorded" is the receipt this module exists to give.
        cov = bundle["coverage"]
        ents = ", ".join(e["name"] for e in bundle["entities"]) or "none"
        miss = f" missing: {', '.join(cov['missing'])}." if cov["missing"] else ""
        return (f"[knowledge-supply] COVERAGE: {cov['verdict']}.{scope_note(cov)} task={bundle['task_class']} entities={ents}. "
                f"Searched, nothing recorded.{miss}{deadline_note(bundle)} receipt={bundle['receipt_path']}")
    parts = [render_header(bundle)]
    current = None
    for it in bundle["items"]:
        label = block_label(it)
        if label != current:
            current = label
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
# A receipt row grows with the store count (3.4 KB at 45 stores, measured by the
# PR #308 round 10 reviewer: 124 MB/year at 100 prompts/day unbounded).
RECEIPT_LEDGER_MAX_BYTES = 2 * 1024 * 1024


def miss_candidates(prompt: str, entities: list[dict]) -> list[dict]:
    """Distinct unresolved candidates, at most MISS_CAP_PER_PROMPT per prompt.
    Codex round 3 on PR #302: one row per OCCURRENCE with no cap wrote 1,600
    rows (245 KB) from a single pasted transcript. A ledger that grows without
    bound from one paste is the noise that gets a hook switched off."""
    resolved = [norm(e["name"]) for e in entities] + [norm(a) for e in entities for a in e.get("aliases", [])]
    out: dict[str, dict] = {}
    for m in CAP_BIGRAM_RE.finditer(prompt):
        a, b = m.group(1), m.group(2)
        if a.casefold() in STOPWORDS or b.casefold() in STOPWORDS or a.casefold() in MISS_OPENERS:
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
    half of its lines (atomic rewrite). Both ledgers go through it: the misses
    ledger balloons per paste, the receipts ledger per store count."""
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

# Two structural bounds on the resolver pass, added after Codex rounds 3 and 4
# on PR #302 each found a different O(N x M) blowup (prompt x index, then
# entities x store rows). Per-loop optimisation is the wrong fix shape when the
# class repeats. A wall-clock DEADLINE inside supply() means the hook always
# returns what it gathered plus a receipt naming where it stopped, instead of
# being killed at the wired 5 s timeout with nothing injected and no receipt.
# An entity CAP bounds the multiplier at the source; the dropped names go in
# the receipt.
MAX_ENTITIES = 12
# One triple with a multi-KB object could carry the whole ceiling on its own
# (sp-d830d71e). Text past this is cut with an explicit marker; the src stays
# so the model opens the full row, and the verbatim pieces are untouched.
ITEM_MAX_CHARS = 600
SUPPLY_DEADLINE_S = float(os.environ.get("KNOWLEDGE_SUPPLY_DEADLINE_S", "3.5"))


def _record_misses(qroot: Path, prompt: str, scan: str, truncated: bool,
                   entities: list[dict], ts: str, session_id: str,
                   candidates_dropped: list[dict] | None = None) -> None:
    """One bounded write per prompt. A truncated prompt (a paste) gets ONE row
    saying so instead of its candidates: the founder did not name those things,
    the pasted text did. A candidate dropped as corpus-common is a row too: it
    was named, searched, found everywhere, and is the data for a per-instance
    stopword list if that ever earns its cost."""
    path = qroot / "memory" / MISSES_NAME
    h = _hash(prompt)
    if truncated:
        append_bounded(path, {"ts": ts, "session_id": session_id, "prompt_hash": h,
                              "candidate": None, "shape": "large_prompt_skipped", "chars": len(prompt)})
        return
    for miss in miss_candidates(scan, entities):
        append_bounded(path, {"ts": ts, "session_id": session_id, "prompt_hash": h, **miss})
    for d in candidates_dropped or []:
        append_bounded(path, {"ts": ts, "session_id": session_id, "prompt_hash": h,
                              "candidate": d["candidate"], "shape": "corpus_common", "stores": d["stores"]})


# ------------------------------------------------------------------ entry point

def supply(root: Path, prompt: str, *, session_id: str, now: dt.date | None = None,
           record: bool = True, deadline_s: float | None = None,
           recall_path: Path | None = None) -> dict | None:
    t0 = time.time()
    t_deadline = t0 + (SUPPLY_DEADLINE_S if deadline_s is None else deadline_s)
    deadline_hit: dict | None = None
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

    project, substores, problems = load_all_stores(qroot, root, manifest)
    stores = project
    index = build_index(project, substores)
    # Absent key: the shipped default. Present but empty: a deliberate quiet.
    fire_alone = set(manifest["entity_kinds_that_fire_alone"]
                     if "entity_kinds_that_fire_alone" in manifest else ["slug", "client"])
    # Only the head of a very long prompt is scanned: past PROMPT_SCAN_CHARS it
    # is a paste, not a question, and the receipt says it was truncated.
    scan = prompt[:PROMPT_SCAN_CHARS]
    truncated = len(prompt) > PROMPT_SCAN_CHARS
    entities = resolve_entities(scan, index, fire_alone)
    # Naming a sub-store (a 4_points case) scopes every other entity's search to
    # it plus the project level; naming none searches every store.
    # A case name the founder TYPED is the scope. A filename inside one case is
    # not: a targets/ stem narrows only its own entity's items to the cases that
    # declared it (stores_for), never the whole prompt. PR #308 review rounds 8,
    # 9 and 10 each found a prompt-level target scope wrong on a different
    # input (bypassed the corpus-common rule; unioned past the named case;
    # hijacked an unrelated fully-indexed subject).
    named_stores = {s for e in entities if e.get("kind") == "store" for s in (e.get("stores") or [])}
    search_stores = [project] + [s for s in substores if not named_stores or s["name"] in named_stores]
    # What the scope left out is a fact on the wire, not only in the receipt:
    # "payment fraud" in a prompt matched case-031-payment-fraud and silently
    # dropped three cases that held the answer, under FULL (PR #308 review
    # round 7). FULL now reads "FULL within case-031-...; N stores not searched".
    stores_excluded = sorted(s["name"] for s in substores if named_stores and s["name"] not in named_stores)
    # Prompt-driven candidates against the project's own documents: what makes a
    # project with no graph and no relationships.md answer from its folder.
    candidate_hits: dict[str, list] = {}
    candidate_engine = "none"
    candidate_pass_cut: str | None = None
    candidates_dropped: list[dict] = []
    docs_declared = any("docs" in (c.get("sources") or {}) for c in (manifest.get("classes") or {}).values())
    if docs_declared and not truncated:
        cands = doc_candidates(scan, entities, index)
        if cands:
            candidate_hits, candidate_engine = search_docs_for_candidates(cands, search_stores, root, deadline=t_deadline)
            candidate_pass_cut = truncation_of(candidate_engine)
            for cand in cands:
                hits = candidate_hits.get(cand) or []
                if not hits:
                    continue
                n_stores = len({h[3] for h in hits})
                # A store count over a hit set the engine cut short is not a
                # count (PR #308 review round 7): the rule is then not applied,
                # the candidate is admitted, and candidate_rule says why.
                if n_stores > MAX_CANDIDATE_STORES and not candidate_pass_cut:
                    candidates_dropped.append({"candidate": cand, "stores": n_stores})
                    candidate_hits.pop(cand, None)
                    continue
                entities.append({"name": cand, "kind": "docs_hit", "resolved_from": "docs",
                                 "ambiguous": False, "project": None, "orgs": [], "aliases": [],
                                 "stores": [], "via_alias": None, "alias_stores": {}, "case_sensitive": True})
    entities_dropped = [e["name"] for e in entities[MAX_ENTITIES:]]
    entities = entities[:MAX_ENTITIES]
    cap_hits = capability_hits(scan, capability_index(root)) if (CAPABILITY_RE.search(scan) and not entities) else []
    task_class, window = classify(scan, entities, cap_hits, now)
    if task_class == "none":
        if record:
            _record_misses(qroot, prompt, scan, truncated, entities, ts, session_id, candidates_dropped)
        if candidates_dropped:
            # Searched, found everywhere, not injected: still a line, never zero
            # bytes (PR #308 review round 7). "I did not find it" and "I found it
            # in 6 of 45 cases and held it back" are different sentences.
            names = ", ".join(f"{d['candidate']} ({d['stores']} stores)" for d in candidates_dropped)
            return {"task_class": "none", "window": None, "entities": [], "items": [],
                    "coverage": {"verdict": "NONE", "missing": [], "missing_paths": {}},
                    "conflicts": 0, "budget": {"ceiling": 0, "used": 0, "cut": 0},
                    "delegated": {"lessons": "lessons-inject", "voice": "voice-dna-loader"},
                    "receipt_path": rel(receipts_path, root), "deadline_hit": None, "entities_dropped": [],
                    "note": (f"[knowledge-supply] searched the docs for {names}: corpus-common (more than "
                             f"{MAX_CANDIDATE_STORES} stores), not injected; name a case to scope it. "
                             f"receipt={rel(qroot / 'memory' / MISSES_NAME, root)}"),
                    "receipt": {"task_class": "none", "candidates_dropped": candidates_dropped}}
        return None

    declared = (manifest.get("classes") or {}).get(task_class, {}).get("sources") or {}
    declared_skips: dict = {"files": 0, "dirs": 0}
    items: list[dict] = []
    conflicts = 0
    source_rows: list[dict] = []
    missing: list[str] = []
    missing_paths: dict[str, str] = {}
    paths = stores["paths"]

    folders = list(manifest.get("folders") or [])

    def present_of(cls: str) -> tuple[bool, str | None]:
        if cls == "canonical":
            return any(s["canonical_files"] for s in search_stores), rel(qroot / "canonical", root)
        if cls == "docs":
            return any(s.get("doc_files") for s in search_stores), f"{rel(qroot, root)}/{{{','.join(folders)}}}"
        if cls == "capability":
            return bool(cap_hits), "repo capability index"
        key = cls if cls != "relationship" else "relationships"
        p = paths.get(key)
        if p is None:
            return False, None
        ok = any(s["paths"][key].is_file() and key not in s["problems"] for s in search_stores)
        return ok, rel(p, root)

    for cls, spec in declared.items():
        present, path_s = present_of(cls)
        cls_items: list[dict] = []
        stores_hit: set[str] = set()
        docs_meta: dict = {}
        if deadline_hit is not None:
            # Past the deadline: this class was never searched, and the receipt
            # and the coverage line both say so. Never "present, 0 hits".
            if spec.get("required"):
                missing.append(cls)
                missing_paths[cls] = f"{path_s or cls} not searched (deadline)"
            source_rows.append({"class": cls, "path": path_s, "present": present, "required": bool(spec.get("required")),
                                "searched": False, "mtime": None, "fresh_days": spec.get("fresh_days"),
                                "hits": 0, "cut": 0, "bytes": 0, "bad_lines": 0, "problem": "not searched (deadline)",
                                "stores_searched": 0, "stores_hit": []})
            continue
        # The cap is N per class PER ENTITY, applied to each resolver result
        # before the lists are joined. Codex round 1 on PR #302: a cap applied
        # to the joined list let the first entity eat the whole budget, so the
        # header named three people and the body carried facts about one.
        cap = spec.get("cap")
        cut_here = 0
        searched_any = False
        if present and cls == "docs":
            if time.time() > t_deadline:
                deadline_hit = {"at_class": cls, "at_entity": entities[0]["name"] if entities else "",
                                "elapsed_ms": int((time.time() - t0) * 1000)}
            else:
                searched_any = True
                by_ent, docs_meta = resolve_docs(entities, search_stores, root, candidate_hits,
                                                 deadline=t_deadline, candidate_engine=candidate_engine)
                for ent in entities:
                    for store_name, got in (by_ent.get(norm(ent["name"])) or {}).items():
                        if cap is not None and len(got) > cap:
                            cut_here += len(got) - cap
                            got = got[:cap]
                        if got:
                            stores_hit.add(store_name)
                        for it in got:
                            it["store"] = store_name
                        cls_items += got
        elif present:
            for ent in entities:
                if deadline_hit is not None:
                    break
                for st in stores_for(ent, search_stores):
                    if time.time() > t_deadline:
                        deadline_hit = {"at_class": cls, "at_entity": ent["name"],
                                        "elapsed_ms": int((time.time() - t0) * 1000)}
                        break
                    searched_any = True
                    st_paths = st["paths"]
                    st_problems = st["problems"]
                    if cls == "graph":
                        got, c = resolve_graph(ent, st, root, window,
                                               set(manifest.get("state_predicates") or []))
                        conflicts += c
                    elif cls == "canonical":
                        got = resolve_canonical(ent, st, root, errors=st_problems, cls=cls)
                    elif cls == "relationships":
                        got = resolve_blocks(ent, st_paths["relationships"], root, "relationship", 12, errors=st_problems, cls=cls, stores=st)
                    elif cls == "decisions":
                        got = resolve_blocks(ent, st_paths["decisions"], root, "decision", 8, errors=st_problems, cls=cls, stores=st)
                    elif cls == "commitments":
                        got = resolve_commitments(ent, st, root, window)
                    elif cls == "meetings":
                        got = resolve_meetings(ent, st, root, window)
                    elif cls == "loops":
                        got = resolve_loops(ent, st, root, window)
                    elif cls == "handoff":
                        got = resolve_handoff(ent, st, root, window)
                    else:
                        got = []
                    # The cap is N per class PER ENTITY PER STORE (a case is its
                    # own knowledge base and keeps its own budget).
                    if cap is not None and len(got) > cap:
                        cut_here += len(got) - cap
                        got = got[:cap]
                    if got:
                        stores_hit.add(st["name"])
                    for it in got:
                        it["store"] = st["name"]
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
        read = [s.get("read_stats", {}).get(cls) for s in search_stores]
        read = [r for r in read if r and r["files"]]
        if present and read and all(r["failed"] and r["failed"] >= r["files"] for r in read):
            present = False   # EVERY file of the class failed to read: unreadable, not empty (sp-ca1769db)
        if not present and spec.get("required"):
            missing.append(cls)
            missing_paths[cls] = f"{path_s or cls} {'unreadable' if cls in problems else 'absent'}"
        # The deadline landed on this class before ANY store was read: that is
        # "not searched", never "partial", and a required class goes to missing.
        # PR #308 review round 1 minor 3: the investigation manifest lists docs
        # first and alone under temporal_event, so this one row decided FULL.
        stopped_cold = bool(deadline_hit and deadline_hit["at_class"] == cls and present and not searched_any)
        # `cut_reason`, never `truncated`: that name is the PROMPT truncation
        # flag in this scope, and shadowing it blanked the receipt's prompt
        # fields (caught by test_large_paste_against_big_index_is_fast_and_truncated).
        cut_reason = None
        if present and not stopped_cold:
            if cls == "docs":
                cut_reason = docs_meta.get("stop")   # the field, never the display string
            elif deadline_hit and deadline_hit["at_class"] == cls:
                cut_reason = "deadline"
        searched_state = class_search_state(stopped_cold, cut_reason, present)
        if searched_state is not True and present and spec.get("required") and cls not in missing:
            missing.append(cls)
            missing_paths[cls] = (f"{path_s or cls} not searched (deadline)" if stopped_cold
                                  else f"{path_s or cls} partially searched ({cut_reason})")
        src_path = Path(root) / path_s if path_s and cls not in ("canonical", "capability", "docs") else None
        store_problems = "; ".join(f"{s['name']}: {s['problems'][cls]}" for s in search_stores if cls in s["problems"]) or None
        # present_of() asks "does ANY store in scope carry this class", which is
        # the right question for ABSENT (a case with no graph.jsonl must not hide
        # the project's). UNREADABLE is a different fact: a copy that exists and
        # failed to parse was never searched, so the class is degraded no matter
        # how many other copies read cleanly. PR #308 review round 5: a truncated
        # graph in the one case that held the answer reported FULL because the
        # project's graph parsed. The receipt carried the problem; the header,
        # the only channel the model reads, did not.
        # "Unreadable" means a store's WHOLE copy of the class: a parse failure on
        # its ledger, or every file of the class in that store failing to read.
        # One unreadable file among readable ones in a store stays a problem in
        # the receipt and never a PARTIAL (PR #304 review, sp-ca1769db, pinned by
        # test_unreadable_is_every_file_not_zero_hits).
        # For a file-per-class store (canonical, handoff, relationships, decisions)
        # the resolver records a per-FILE read error under the same problems key,
        # so the ledger rule (a key in problems) applies only to the ledger
        # classes; the file classes use read_stats and the all-failed test.
        ledger_classes = ("graph", "commitments", "meetings", "loops")
        unreadable_in = [s["name"] for s in search_stores if cls in ledger_classes and cls in s["problems"]]
        for s in search_stores:
            rs_s = s.get("read_stats", {}).get(cls)
            if rs_s and rs_s["files"] and rs_s["failed"] >= rs_s["files"] and s["name"] not in unreadable_in:
                unreadable_in.append(s["name"])
        if present and unreadable_in:
            if searched_state is True:
                searched_state = "partial"
            if spec.get("required") and cls not in missing:
                missing.append(cls)
                missing_paths[cls] = f"{path_s or cls} unreadable in {', '.join(unreadable_in)}"
        row = {
            "class": cls, "path": path_s, "present": present, "required": bool(spec.get("required")),
            "mtime": mtime_date(src_path) if src_path and src_path.exists() else None,
            "fresh_days": fresh_days, "hits": len(cls_items) + cut_here, "cut": cut_here,
            "bytes": sum(len(i["text"]) for i in cls_items),
            "bad_lines": sum(s["bad_lines"].get(cls, 0) for s in search_stores),
            "problem": store_problems,
            "searched": searched_state,
            "stores_searched": 0 if (stopped_cold or not present) else len(search_stores), "stores_hit": sorted(stores_hit),
        }
        if stopped_cold:
            row["problem"] = "not searched (deadline)"
        elif cut_reason:
            row["problem"] = f"partially searched ({cut_reason})"
        if cls == "docs":
            row["files"] = docs_meta.get("files", sum(len(s.get("doc_files") or []) for s in search_stores))
            row["engine"] = docs_meta.get("engine")
            row["files_skipped_oversize"] = sum(len(s.get("doc_skipped_oversize") or []) for s in search_stores)
            skipped_dirs_all = [rel(d, root) for s in search_stores for d in (s.get("doc_skipped_dirs") or [])]
            row["dirs_skipped"] = len(skipped_dirs_all)
            row["dirs_skipped_sample"] = skipped_dirs_all[:6]
            declared_skips = {"files": row["files_skipped_oversize"], "dirs": row["dirs_skipped"]}
        source_rows.append(row)

    verdict = "FULL" if not missing else ("NONE" if all(not r["present"] for r in source_rows) else "PARTIAL")
    ceiling = int(manifest.get("ceiling_chars") or 8000)
    bundle = {
        "task_class": task_class, "window": window,
        "entities": [{k: v for k, v in e.items() if k != "project"} | {"project": e.get("project")} for e in entities],
        "coverage": {"verdict": verdict, "missing": missing, "missing_paths": missing_paths,
                     "scope": sorted(named_stores), "stores_excluded": stores_excluded},
        "items": [], "conflicts": conflicts,
        "budget": {"ceiling": ceiling, "used": 0, "cut": 0},
        "delegated": {"lessons": "lessons-inject", "voice": "voice-dna-loader"},
        "receipt_path": rel(receipts_path, root),
        "deadline_hit": deadline_hit, "entities_dropped": entities_dropped,
    }
    header_len = len(render_header(bundle)) + 200
    kept, cut, ceiling_hit = assemble(items, entities, ceiling, header_len)
    bundle["items"] = kept
    source_cut = sum(r["cut"] for r in source_rows)
    # The cut-stores note is on the wire, so it is set BEFORE the exact fit and
    # the fit pays for it; recomputed after, since the fit never drops a pinned
    # line and so never cuts another store whole (PR #308 review round 8).
    bundle["budget"]["stores_cut"] = stores_cut_by_ceiling(items, bundle["items"])
    bundle["declared_skips"] = declared_skips
    cut, ceiling_hit, overflow = fit_to_ceiling(bundle, ceiling, cut, source_cut, ceiling_hit)
    bundle["budget"]["stores_cut"] = stores_cut_by_ceiling(items, bundle["items"])
    receipt = {
        "ts": ts, "session_id": session_id, "task_class": task_class, "prompt_hash": _hash(prompt),
        "entities": [e["name"] for e in entities], "window": window,
        "sources": source_rows, "declared_missing": missing, "coverage": verdict,
        "scope": sorted(named_stores), "stores_excluded": stores_excluded,
        "conflicts": conflicts, "ceiling_hit": ceiling_hit, "overflow": overflow,
        "stores_cut": bundle["budget"]["stores_cut"],
        "prompt_chars": len(prompt), "prompt_truncated": truncated,
        "deadline_hit": deadline_hit, "entities_dropped": entities_dropped,
        "candidates_dropped": candidates_dropped,
        # The corpus-common rule counts STORES, so on a project with no sub-stores
        # it cannot fire and an empty candidates_dropped would read as "nothing
        # was common" (PR #308 review round 1 minor 4). Say so. A file-count rule
        # is not the fix: on a single-store project the main client's name is in
        # most files by design (measured 2026-09-05: one instance's client hit
        # 97 lines across its research and output), and dropping it would be
        # dropping the subject.
        "candidate_rule": {"max_stores": MAX_CANDIDATE_STORES,
                           "applicable": bool(substores) and not candidate_pass_cut,
                           "note": (None if (substores and not candidate_pass_cut)
                                    else f"candidate pass truncated ({candidate_pass_cut}): rule not applied"
                                    if substores else "single store: rule cannot run")},
        "items": len(kept), "bytes": bundle["budget"]["used"], "elapsed_ms": int((time.time() - t0) * 1000),
        "manifest": rel(manifest_path, root) if manifest_path else None,
    }
    bundle["receipt"] = receipt
    if record:
        append_bounded(receipts_path, receipt, RECEIPT_LEDGER_MAX_BYTES)
        _record_misses(qroot, prompt, scan, truncated, entities, ts, session_id, candidates_dropped)
        _record_recall(bundle, session_id, recall_path)
    return bundle


def fit_to_ceiling(bundle: dict, ceiling: int, cut: int, source_cut: int,
                   ceiling_hit: bool) -> tuple[int, bool, int]:
    """Exact fit against the RENDERED text, separators and footer included, so
    the number in the receipt is the number on the wire. Codex round 3 on
    PR #302: the byte accounting skipped the per-entity separator lines, so
    render() ran past the ceiling while the receipt said overflow 0. Drops the
    lowest-priority unpinned item until it fits; pins never drop, and if the
    pins alone overrun, overflow says by how much. Mutates bundle["items"] and
    bundle["budget"]; returns (cut, ceiling_hit, overflow)."""
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
    return cut, ceiling_hit, overflow


def stores_cut_by_ceiling(all_items: list[dict], kept: list[dict]) -> list[str]:
    """Stores that had a hit and reached the model with nothing. With one pin per
    (entity, store) this is empty unless the pins alone overran the ceiling,
    and then it is named on the wire (PR #308 review round 8)."""
    had = {it.get("store") or PROJECT_STORE for it in all_items}
    have = {it.get("store") or PROJECT_STORE for it in kept}
    return sorted(had - have)


def _record_recall(bundle: dict, session_id: str, recall_path: Path | None) -> None:
    """Producer half of the memory outcome loop (knowledge-supply plan, Phase 2).
    Each distinct source file this pass surfaced is recorded in the session
    recall artifact, the same one memory-scores-surface.py writes, so the Stop
    hook memory_autocapture.py can score it: useful if the model opened that
    file this session, dead_end if it never touched it. That is the only proxy
    for "the bundle was used" this repo has, and it needs no new mechanism. The
    id prefix lets a consumer tell these rows from auto-memory rows. Best
    effort: a recall write must never fail a supply pass."""
    try:
        spec = importlib.util.spec_from_file_location(
            "session_recall", Path(__file__).resolve().parent / "session_recall.py")
        sr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sr)
        seen: dict[str, str] = {}
        for it in bundle["items"]:
            seen.setdefault(it["abs_src"], it["src"])
        entries = [{"memory_id": f"knowledge-supply:{rel_src}", "source_file": abs_src}
                   for abs_src, rel_src in seen.items()]
        if entries:
            sr.record_surfaced(entries, session_id=session_id, path=recall_path)
    except Exception:
        pass


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
                st, subs, pr = load_all_stores(q, root, m)
                idx = build_index(st, subs)
                ents = resolve_entities(prompt, idx, set(m.get("entity_kinds_that_fire_alone") or []))
                print(f"(no supply) reason=no_entities_or_class qroot={q} index_size={len(idx)} "
                      f"stores={[s['name'] for s in subs]} docs={sum(len(s['doc_files']) for s in [st] + subs)} "
                      f"entities={[e['name'] for e in ents]} problems={pr}")
