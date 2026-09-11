#!/usr/bin/env python3
"""Tests for knowledge_supply.py and knowledge-inject.py. Runnable via pytest.

Reproducer (2026-09-04, knowledge-supply plan): graph.jsonl, relationships.md,
canonical, decisions, commitments and meeting stores existed in the fleet and
NOTHING read any of them conditioned on the prompt. Measured: 0 bytes injected
for "who at 14 Peaks did we talk to and what did they push back on". Every test
here builds a fixture instance under a temp dir and asserts the supply pass
puts the right excerpt, with path and line, in front of the model, or emits
nothing at all. Never a live path.

Negative self-test discipline (fable-discipline): each positive case is paired
with a case proving the check can fail (no entity -> zero bytes; bare first
name -> zero bytes; missing source -> PARTIAL; foreign instance -> zero foreign
lines). Expected vocabularies are DERIVED from the files that own them
(provenance-vocabulary.json, knowledge-sources.json), never restated here.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LIB = HERE / "knowledge_supply.py"
HOOK = HERE / "knowledge-inject.py"
MANIFEST = HERE.parent / "knowledge-sources.json"
VOCAB = HERE / "provenance-vocabulary.json"

spec = importlib.util.spec_from_file_location("knowledge_supply", LIB)
ks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ks)

NOW = dt.date(2026, 9, 4)

GRAPH_ROWS = [
    {"s": "Dana Okafor", "p": "owns", "o": "merging PR #19 on acme-webapp", "t": "2026-09-02", "project": "acme-app"},
    {"s": "Dana Okafor", "p": "pushed_back_on", "o": "weekly status calls", "t": "2026-08-10", "project": "acme-app"},
    {"s": "Dana Okafor", "p": "status", "o": "memo on hold pending send decision", "t": "2026-09-01", "project": "acme-app"},
    {"s": "Dana Okafor", "p": "status", "o": "memo sent", "t": "2026-08-20", "project": "acme-app"},
    {"s": "Lisa", "p": "discovered", "o": "DOM mutation signal", "t": "2026-03-09", "project": "acme-app"},
    {"s": "Mark Chen", "p": "works_at", "o": "Acme", "t": "2026-07-01", "project": "acme"},
    {"s": "Mark Chen", "p": "works_at", "o": "Globex", "t": "2026-07-02", "project": "globex"},
    {"s": "Mark Chen", "p": "owns", "o": "the acme rollout", "t": "2026-07-03", "project": "acme"},
    {"s": "Mark Chen", "p": "owns", "o": "the globex audit", "t": "2026-07-04", "project": "globex"},
    {"s": "DO", "p": "alias_of", "o": "Dana Okafor", "t": "2026-08-01"},
    {"s": "Dana Okafor", "p": "owns", "o": "the deployment runbook", "t": "2026-08-15", "project": "acme-app"},
]

RELATIONSHIPS = """# Relationships

## Contacts

### Dana Okafor — CTO — Acme Labs
- **Type:** Customer
- **Status:** Active
- **What they care about:** shipping the auth probe
- **What they pushed back on:** weekly status calls
- **Next step:** send the deployment doc

### Mark Chen — Engineer — Acme
- **Type:** Practitioner

### Ally — Founder — Intel Shop
- **Type:** Design Partner
"""

TALK_TRACKS = """# Talk tracks

The pricing memo for Dana Okafor was sent on 2026-08-20.
Dana Okafor prefers async updates {{UNVALIDATED}}.
Old Client onboarding line, provenance: inferred, Dana Okafor mentioned it.
Dana Okafor budget figure {{UNVERIFIED}}.
Dana Okafor quoted line {{NEEDS_VALIDATION — derived from her own language}}.
"""

DECISIONS = """# Decision Log

### RULE-010: Dana Okafor owns merges
- **Origin:** [USER-DIRECTED]
- **Decision:** Dana Okafor merges every acme-webapp PR himself.
- **Reason:** his call
- **Date:** 2026-09-02
"""

COMMITMENTS = [
    {"due": "2026-09-10", "extracted_at": "2026-08-25T10:00:00+00:00", "id": "c1",
     "promise": "send Dana Okafor the deployment documentation", "resolved_by": None,
     "slug": "acme-labs", "source": {"kind": "founder-stated", "pointer": "crm-working.md", "ref": "chat"},
     "state": "open"},
    {"due": None, "extracted_at": "2026-06-01T10:00:00+00:00", "id": "c2",
     "promise": "old promise to Dana Okafor about the audit plan", "resolved_by": "founder-inbox",
     "slug": "acme-labs", "source": {"kind": "founder-stated", "pointer": "x", "ref": "y"},
     "state": "confirmed-sent"},
]

GRANOLA = {
    "_provenance": {"source": "fixture"},
    "acme-labs": [
        {"date": "2026-09-03", "meeting_id": "m1", "title": "Sync with Dana",
         "summary": "Dana Okafor said the PR merges Friday.", "next_steps": ["send doc"]},
        {"date": "2026-08-01", "meeting_id": "m0", "title": "Kickoff",
         "summary": "Dana Okafor walked through the acme-webapp scope.", "next_steps": []},
    ],
    "old-client": [
        {"date": "2025-03-01", "meeting_id": "m9", "title": "Old intro",
         "summary": "old-client wants a phishing audit.", "next_steps": []},
    ],
}

LOOPS = {"loops": [
    {"id": "l1", "title": "Reply to Dana Okafor about PR #19", "status": "open",
     "next_action": "send the note", "added": "2026-09-01", "needs_founder": False, "github": None},
    {"id": "l2", "title": "Closed thing with Dana Okafor", "status": "closed",
     "next_action": "none", "added": "2026-08-01", "needs_founder": False, "github": None},
]}

HANDOFF = "# Last handoff\n\nDana Okafor is waiting on the deployment doc. `provenance: explicit_statement`\n"


def make_instance(tmp: Path, name: str = "repo", q_dir: str = "q-fix",
                  marker: str = "") -> tuple[Path, Path]:
    root = tmp / name
    q = root / q_dir
    (q / "memory").mkdir(parents=True)
    (q / "my-project").mkdir()
    (q / "canonical").mkdir()
    (q / "output").mkdir()
    (q / ".q-system").mkdir()
    shutil.copy(MANIFEST, q / ".q-system" / "knowledge-sources.json")
    with open(q / "memory" / "graph.jsonl", "w") as f:
        for row in GRAPH_ROWS:
            f.write(json.dumps(row) + "\n")
    (q / "my-project" / "relationships.md").write_text(RELATIONSHIPS)
    (q / "canonical" / "talk-tracks.md").write_text(TALK_TRACKS + (f"\n{marker} Dana Okafor line\n" if marker else ""))
    (q / "canonical" / "decisions.md").write_text(DECISIONS)
    with open(q / "my-project" / "commitments.jsonl", "w") as f:
        for row in COMMITMENTS:
            f.write(json.dumps(row) + "\n")
    (q / "output" / "granola-cache.json").write_text(json.dumps(GRANOLA))
    (q / "memory" / "open-loops.json").write_text(json.dumps(LOOPS))
    (q / "memory" / "last-handoff.md").write_text(HANDOFF)
    return root, q


def run(root: Path, prompt: str, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("session_id", "test-session")
    return ks.supply(root, prompt, **kw)


def items_of(bundle, kind=None, entity=None):
    out = bundle["items"]
    if kind:
        out = [i for i in out if i["kind"] == kind]
    if entity:
        # a merged heading ("== A, B ==") carries B in co_entities (round 11)
        out = [i for i in out if i["entity"] == entity or entity in (i.get("co_entities") or [])]
    return out


# ---------------------------------------------------------------- negatives

def test_no_entity_emits_nothing(tmp_path):
    root, _ = make_instance(tmp_path)
    assert run(root, "what is the weather like in Lisbon today") is None


def test_bare_first_name_and_lowercase_emit_nothing(tmp_path):
    root, _ = make_instance(tmp_path)
    assert run(root, "Lisa") is None, "a bare single-token graph subject never fires"
    assert run(root, "mark the file as done") is None, "lowercase common word never fires"
    assert run(root, "Mark") is None, "first token of a multi-token entity, alone, never fires"


# ---------------------------------------------------------------- entity lookup

def test_entity_lookup_graph_newest_first_with_src(tmp_path):
    root, q = make_instance(tmp_path)
    b = run(root, "what do we know about Dana Okafor")
    assert b["task_class"] == "entity_lookup"
    g = items_of(b, "graph", "Dana Okafor")
    assert g, "graph items expected"
    dates = [i["t"] for i in g]
    assert dates == sorted(dates, reverse=True), "newest first"
    assert g[0]["src"].endswith("memory/graph.jsonl:1"), g[0]["src"]
    assert g[0]["predicate"] == "owns"
    assert all("graph.jsonl:" in i["src"] for i in g)


def test_first_name_expands_when_unique_and_not_sentence_initial(tmp_path):
    """Replay of 2,131 real prompts (2026-09-04): the top misses were bare first
    names. Mid-sentence, a capitalized first token of exactly one multi-token
    entity resolves; sentence-initial stays out (a verb reads the same)."""
    root, _ = make_instance(tmp_path)
    b = run(root, "what did Dana say about the runbook")
    assert b is not None
    ent = [e for e in b["entities"] if e["name"] == "Dana Okafor"]
    assert ent and ent[0]["resolved_from"] == "first_name"
    assert run(root, "Dana") is None, "sentence-initial bare first name never fires"
    assert run(root, "Mark") is None
    assert run(root, "mark the file as done") is None


def test_alias_resolves_to_canonical_entity(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "anything new from DO")
    assert b is not None
    names = {e["name"] for e in b["entities"]}
    assert "Dana Okafor" in names
    assert any(e.get("resolved_from") == "alias" for e in b["entities"])


def test_supersession_marks_older_stale_and_newer_current(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "what is the memo status for Dana Okafor")
    status_items = [i for i in items_of(b, "graph", "Dana Okafor") if i["predicate"] == "status"]
    assert len(status_items) == 2
    newer, older = status_items[0], status_items[1]
    assert newer["t"] == "2026-09-01" and newer["status"] == "KNOWN"
    assert older["t"] == "2026-08-20" and older["status"] == "STALE"
    assert older["supersedes"] == newer["src"]
    assert b["conflicts"] >= 1


def test_accumulative_predicate_is_never_superseded(tmp_path):
    """Measured on the largest instance 2026-09-04: 'owns merging PR #19' wrongly
    superseded 'owns merged PR #8'. Only state predicates supersede."""
    root, _ = make_instance(tmp_path)
    b = run(root, "what does Dana Okafor own")
    owns = [i for i in items_of(b, "graph", "Dana Okafor") if i["predicate"] == "owns"]
    assert len(owns) == 2
    assert all(i["status"] == "KNOWN" and i["supersedes"] is None for i in owns)


def test_commitment_states_from_real_vocabulary(tmp_path):
    """Measured on consulting 2026-09-04: open 73, superseded 121, confirmed-sent
    20, misattributed 12, voided 6, resolved 5. Only 'open' is open; voided and
    misattributed rows are not promises."""
    root, q = make_instance(tmp_path)
    with open(q / "my-project" / "commitments.jsonl", "a") as f:
        f.write(json.dumps({"id": "c3", "promise": "voided thing for Dana Okafor", "slug": "acme-labs",
                            "state": "voided", "extracted_at": "2026-09-01T00:00:00+00:00", "source": {}}) + "\n")
        f.write(json.dumps({"id": "c4", "promise": "superseded thing for Dana Okafor", "slug": "acme-labs",
                            "state": "superseded", "extracted_at": "2026-09-02T00:00:00+00:00", "source": {}}) + "\n")
    b = run(root, "what have we promised Dana Okafor")
    texts = [i["text"] for i in items_of(b, "commitment")]
    assert not any("voided thing" in t for t in texts)
    assert texts[0].startswith("send Dana Okafor the deployment"), "open row first even though superseded row is newer"
    assert any("superseded thing" in t and "[state: superseded" in t for t in texts)


def test_canonical_and_graph_both_present_with_hierarchy_header(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "did the memo go to Dana Okafor")
    canon = items_of(b, "canonical", "Dana Okafor")
    assert any("memo for Dana Okafor was sent" in i["text"] for i in canon)
    assert any("memo on hold" in i["text"] for i in items_of(b, "graph"))
    text = ks.render(b)
    assert "graph beats canonical" in text
    unval = [i for i in canon if i["status"] == "UNVALIDATED"]
    assert any("prefers async" in i["text"] for i in unval), "{{UNVALIDATED}} marker -> UNVALIDATED"
    assert any("provenance: inferred" in i["text"] for i in unval), "inferred rank -> UNVALIDATED"
    assert any("budget figure" in i["text"] for i in unval), "{{UNVERIFIED}} -> UNVALIDATED"
    assert any("quoted line" in i["text"] for i in unval), "{{NEEDS_VALIDATION — ...}} -> UNVALIDATED"


def test_status_threshold_is_derived_from_vocabulary_file():
    vocab = json.loads(VOCAB.read_text())["provenance"]
    assert vocab, "vocabulary must parse to a non-empty table"
    floor = min(vocab.values(), key=lambda v: v["rank"])
    low = [k for k, v in vocab.items() if v["rank"] <= floor["rank"]]
    high = [k for k, v in vocab.items() if v["rank"] > floor["rank"]]
    assert low and high
    assert ks.status_for_line(f"a line, provenance: {low[0]}") == "UNVALIDATED"
    assert ks.status_for_line(f"a line, provenance: {high[0]}") == "KNOWN"


# ---------------------------------------------------------------- commitments, coverage, meetings

def test_commitment_class_surfaces_open_promise_and_receipt(tmp_path):
    root, q = make_instance(tmp_path)
    b = run(root, "what have we promised Dana Okafor that is still open")
    assert b["task_class"] == "commitment"
    c = items_of(b, "commitment")
    assert any(i["text"].startswith("send Dana Okafor the deployment") for i in c)
    open_first = c[0]
    assert "open" in open_first["text"]
    assert open_first["src"].endswith("commitments.jsonl:1")
    r = b["receipt"]
    by_class = {s["class"]: s for s in r["sources"]}
    assert by_class["commitments"]["hits"] >= 1
    assert by_class["commitments"]["present"] is True
    assert r["coverage"] == "FULL"
    assert r["declared_missing"] == []


def test_coverage_partial_when_required_source_absent(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "output" / "granola-cache.json").unlink()
    b = run(root, "what did we promise Dana Okafor")
    assert b["coverage"]["verdict"] == "PARTIAL"
    assert "meetings" in b["coverage"]["missing"]
    assert "meetings" in b["receipt"]["declared_missing"]
    text = ks.render(b)
    assert text.splitlines()[0].startswith("[knowledge-supply] COVERAGE: PARTIAL")
    assert "meetings" in text.splitlines()[0]


def test_present_but_no_hits_is_still_searched(tmp_path):
    root, q = make_instance(tmp_path)
    b = run(root, "tell me about Mark Chen")
    by_class = {s["class"]: s for s in b["receipt"]["sources"]}
    assert by_class["commitments"]["present"] is True
    assert by_class["commitments"]["hits"] == 0
    assert b["coverage"]["verdict"] == "FULL"


def test_old_meeting_only_entity_is_stale(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "what do we know about old-client")
    m = items_of(b, "meeting", "old-client")
    assert m and m[0]["t"] == "2025-03-01"
    assert m[0]["status"] == "STALE"
    assert m[0]["src"].endswith("granola-cache.json#old-client/m9")


def test_temporal_class_filters_to_window(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "what did Dana Okafor say yesterday")
    assert b["task_class"] == "temporal_event"
    kinds = {i["kind"] for i in b["items"]}
    assert "canonical" not in kinds
    assert "relationship" not in kinds
    meetings = items_of(b, "meeting")
    assert [i["t"] for i in meetings] == ["2026-09-03"], "only the meeting inside the window"
    assert b["receipt"]["window"] == {"from": "2026-09-03", "to": "2026-09-04"}


def test_loops_only_open_ones(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "what do we know about Dana Okafor")
    loops = items_of(b, "loop")
    assert len(loops) == 1 and "PR #19" in loops[0]["text"]


# ---------------------------------------------------------------- ambiguity and scoping

def test_same_name_two_orgs_is_ambiguous_and_project_scoped(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "what does Mark Chen own")
    ent = [e for e in b["entities"] if e["name"] == "Mark Chen"][0]
    assert ent["ambiguous"] is True
    owns = [i["text"] for i in items_of(b, "graph", "Mark Chen") if i["predicate"] == "owns"]
    assert len(owns) == 2, "never merged, never dropped"
    b2 = run(root, "what does Mark Chen at Acme own")
    ent2 = [e for e in b2["entities"] if e["name"] == "Mark Chen"][0]
    assert ent2["ambiguous"] is False
    owns2 = [i["text"] for i in items_of(b2, "graph", "Mark Chen") if i["predicate"] == "owns"]
    assert owns2 == ["Mark Chen owns the acme rollout"]


# ---------------------------------------------------------------- writing, isolation, verbatim

def test_writing_class_carries_knowledge_only(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "draft an email to Dana Okafor about the PR")
    assert b["task_class"] == "writing"
    assert items_of(b, "relationship"), "audience block present"
    assert not [i for i in b["items"] if i["kind"] == "voice"]
    assert b["delegated"]["voice"] == "voice-dna-loader"
    assert "exemplar" not in ks.render(b).lower()


def test_instance_isolation(tmp_path):
    root_a, _ = make_instance(tmp_path, name="a", marker="")
    root_b, _ = make_instance(tmp_path, name="b", marker="ZEBRA-MARKER-B")
    b = run(root_a, "what do we know about Dana Okafor")
    assert "ZEBRA-MARKER-B" not in ks.render(b)
    assert all(str(root_a) in i["abs_src"] for i in b["items"])


def test_every_excerpt_is_verbatim_from_its_source(tmp_path):
    root, _ = make_instance(tmp_path)
    b = run(root, "everything on Dana Okafor and Mark Chen")
    for item in b["items"]:
        path = Path(item["abs_src"])
        src_text = ks.normalize_ws(path.read_text())
        for piece in ks.verbatim_pieces(item):
            assert ks.normalize_ws(piece) in src_text, (item["kind"], piece)


def test_ceiling_keeps_newest_triple_and_records_cut(tmp_path):
    root, q = make_instance(tmp_path)
    # Instance override path: lift the graph cap so the CHAR ceiling is what cuts.
    override = json.loads(MANIFEST.read_text())
    override["classes"]["entity_lookup"]["sources"]["graph"]["cap"] = 5000
    override["classes"]["entity_lookup"]["sources"]["canonical"]["cap"] = 5000
    (q / ".q-system" / "data").mkdir()
    (q / ".q-system" / "data" / "knowledge-sources.json").write_text(json.dumps(override))
    # Canonical renders BEFORE graph. Enough canonical hits to exhaust the ceiling
    # on their own is the only case where the pin, not the ordering, keeps the
    # newest triple alive. Without this the pin mutation survives (measured).
    with open(q / "canonical" / "talk-tracks.md", "a") as f:
        for n in range(400):
            f.write(f"Dana Okafor canonical filler line {n} " + "y" * 60 + "\n")
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n in range(2000):
            f.write(json.dumps({"s": "Dana Okafor", "p": f"pred{n % 7}", "o": f"object number {n} " + "x" * 40,
                                "t": f"2025-{(n % 12) + 1:02d}-{(n % 27) + 1:02d}", "project": "bulk"}) + "\n")
    b = run(root, "what do we know about Dana Okafor")
    text = ks.render(b)
    assert len(text) <= b["budget"]["ceiling"]
    assert b["budget"]["cut"] > 0
    assert b["receipt"]["ceiling_hit"] is True
    g = items_of(b, "graph", "Dana Okafor")
    assert g and g[0]["t"] == "2026-09-02", "newest triple survives the cut"


# ---------------------------------------------------------------- capability class

def test_capability_class_reads_repo_index(tmp_path):
    root, _ = make_instance(tmp_path)
    cmd = root / "plugins" / "kipi-core" / "commands"
    cmd.mkdir(parents=True)
    (cmd / "wiring-check.md").write_text("---\ndescription: End-of-task gate that verifies every change is connected\n---\n# wiring check\n")
    rules = root / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "wiring-check.md").write_text("# Definition of Done: Fully Wired (ENFORCED)\n\nNo task is done until wired.\n")
    b = run(root, "how does wiring-check work")
    assert b["task_class"] == "capability"
    caps = items_of(b, "capability")
    assert any("commands/wiring-check.md" in i["src"] for i in caps)
    assert any("rules/wiring-check.md" in i["src"] for i in caps)


# ---------------------------------------------------------------- Codex round 1 on PR #302

def test_multi_entity_each_gets_its_newest_fact(tmp_path):
    """MAJOR 1: the per-class cap is per entity. One person with many rows must
    not starve the others named in the same prompt."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n in range(14):
            f.write(json.dumps({"s": "Dana Okafor", "p": "cares_about", "o": f"topic {n}",
                                "t": f"2026-07-{n + 1:02d}", "project": "acme-app"}) + "\n")
        f.write(json.dumps({"s": "Priya Raman", "p": "pushed_back_on", "o": "the timeline",
                            "t": "2026-09-01", "project": "x"}) + "\n")
        f.write(json.dumps({"s": "Tomas Lind", "p": "owns", "o": "the vendor review",
                            "t": "2026-09-02", "project": "x"}) + "\n")
    b = run(root, "what do we know about Dana Okafor, Priya Raman and Tomas Lind")
    assert [e["name"] for e in b["entities"]] == ["Dana Okafor", "Priya Raman", "Tomas Lind"]
    assert items_of(b, "graph", "Priya Raman"), "second entity got zero facts"
    assert items_of(b, "graph", "Tomas Lind"), "third entity got zero facts"
    cap = json.loads(MANIFEST.read_text())["classes"]["entity_lookup"]["sources"]["graph"]["cap"]
    assert len(items_of(b, "graph", "Dana Okafor")) == cap, "cap applies per entity"
    assert items_of(b, "graph", "Dana Okafor")[0]["t"] == "2026-09-02", "newest survives the per-entity cap"


def test_short_alias_matches_only_uppercase_whole_word(tmp_path):
    """MAJOR 2: a two-letter alias is an initialism. It matches store content only
    as an uppercase whole word; never the English word it casefolds to."""
    root, q = make_instance(tmp_path)
    (q / "canonical" / "pricing-framework.md").write_text(
        "# Pricing\nNever do discounts below the floor.\nGlobex asked what we do about weekend support.\n"
        "DO confirmed the floor holds.\n")
    b = run(root, "draft an email to Dana Okafor about pricing")
    texts = [i["text"] for i in items_of(b, "canonical", "Dana Okafor")]
    assert not any("Never do discounts" in t for t in texts)
    assert not any("Globex asked" in t for t in texts)
    assert any("DO confirmed" in t for t in texts), "uppercase whole-word alias still matches"
    assert ks.alias_in_text("DO", "what do we do") is False
    assert ks.alias_in_text("DO", "DO said yes") is True
    assert ks.alias_in_text("dana", "Dana said yes") is True, "4+ char aliases stay case-insensitive"


def test_corrupt_commitments_is_unreadable_not_empty(tmp_path):
    """MAJOR 3: an all-corrupt promise ledger is a missing required source,
    never an empty one. A partly corrupt one stays present and says how many
    lines it could not read."""
    root, q = make_instance(tmp_path)
    (q / "my-project" / "commitments.jsonl").write_text("{not json\n[1,2]\n")
    b = run(root, "what have we promised Dana Okafor")
    assert b["coverage"]["verdict"] == "PARTIAL" and "commitments" in b["coverage"]["missing"]
    row = {s["class"]: s for s in b["receipt"]["sources"]}["commitments"]
    assert row["present"] is False and row["bad_lines"] == 2 and "unreadable" in row["problem"]
    assert "unreadable" in ks.render(b).splitlines()[0]
    with open(q / "my-project" / "commitments.jsonl", "w") as f:
        f.write("{not json\n")
        for r in COMMITMENTS:
            f.write(json.dumps(r) + "\n")
    b = run(root, "what have we promised Dana Okafor")
    row = {s["class"]: s for s in b["receipt"]["sources"]}["commitments"]
    assert row["present"] is True and row["bad_lines"] == 1 and row["hits"] >= 1
    assert b["coverage"]["verdict"] == "FULL"


def test_first_name_never_line_or_bullet_initial(tmp_path):
    """MINOR 4: line-initial and bullet-initial are sentence-initial too."""
    root, _ = make_instance(tmp_path)
    for prompt in ("Mark the file as done", "Fix the tests\nMark the file as done",
                   "- Mark the file as done", "1. Mark the file as done", "Notes:\nDana", "todo: Dana"):
        assert run(root, prompt) is None, prompt
    assert run(root, "what did Dana say") is not None
    assert run(root, "Fix the tests, then ask Dana about it") is not None


def test_same_date_later_line_is_newer(tmp_path):
    """Append-only store: two rows on one date, the later line is the later write.
    Reviewer noted the inverted tiebreak was masked by the conflict branch; this
    pins it on a non-conflicting predicate where nothing masks it."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        f.write(json.dumps({"s": "Tomas Lind", "p": "noted", "o": "first write", "t": "2026-09-03", "project": "x"}) + "\n")
        f.write(json.dumps({"s": "Tomas Lind", "p": "noted", "o": "second write", "t": "2026-09-03", "project": "x"}) + "\n")
    b = run(root, "what do we know about Tomas Lind")
    noted = [i for i in items_of(b, "graph", "Tomas Lind") if i["predicate"] == "noted"]
    assert [i["text"] for i in noted][0].endswith("second write")


def test_fire_alone_knob_is_live(tmp_path):
    """MINOR 5: the manifest decides which identifier kinds fire on one word."""
    root, q = make_instance(tmp_path)
    assert run(root, "anything new on acme-labs") is not None
    override = json.loads(MANIFEST.read_text())
    override["entity_kinds_that_fire_alone"] = []
    (q / ".q-system" / "data").mkdir()
    (q / ".q-system" / "data" / "knowledge-sources.json").write_text(json.dumps(override))
    assert run(root, "anything new on acme-labs") is None, "empty list is a deliberate quiet"
    del override["entity_kinds_that_fire_alone"]
    (q / ".q-system" / "data" / "knowledge-sources.json").write_text(json.dumps(override))
    assert run(root, "anything new on acme-labs") is not None, "absent key is the shipped default"


# ---------------------------------------------------------------- Codex round 2 on PR #302

def test_first_name_resolves_alongside_other_entities(tmp_path):
    """MAJOR: expansion ran only when nothing else resolved, so 'Mark Chen and
    Dana' silently dropped Dana under a FULL header."""
    root, _ = make_instance(tmp_path)
    b = run(root, "what do we know about Mark Chen and Dana")
    names = {e["name"]: e for e in b["entities"]}
    assert "Mark Chen" in names and "Dana Okafor" in names
    assert names["Dana Okafor"]["resolved_from"] == "first_name"
    assert items_of(b, "graph", "Dana Okafor"), "the first-named person's facts are present"
    assert items_of(b, "graph", "Mark Chen")


def test_pins_alone_over_ceiling_is_reported_not_hidden(tmp_path):
    """MINOR: pinned items always ship, so if the pins alone overrun the ceiling
    the receipt says so (ceiling_hit, overflow) instead of cut=0."""
    root, q = make_instance(tmp_path)
    # MAX_ENTITIES names, each with one triple long enough that the pins alone
    # overrun the 8,000-char ceiling (12 x ~760 chars).
    words = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet",
             "Kilo", "Lima"][:ks.MAX_ENTITIES]
    names = [f"Pinned {w}" for w in words]
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n, name in enumerate(names):
            f.write(json.dumps({"s": name, "p": "noted", "o": f"object {n} " + "z" * 700,
                                "t": "2026-09-01", "project": "bulk"}) + "\n")
    b = run(root, "status on " + ", ".join(names))
    assert len(b["entities"]) == len(names) == ks.MAX_ENTITIES
    assert all(items_of(b, "graph", name) for name in names), "every entity keeps its pinned fact"
    assert b["receipt"]["ceiling_hit"] is True
    assert b["budget"]["overflow"] > 0 and b["receipt"]["overflow"] == b["budget"]["overflow"]
    assert len(ks.render(b)) > b["budget"]["ceiling"], "the overrun is real and reported, not hidden"


def test_vocab_floor_is_parsed_once_per_version():
    """MINOR: status_for_line re-parsed provenance-vocabulary.json per matched
    line. Cached on the file's mtime, so an edit is still seen next call."""
    ks._vocab_floor_at.cache_clear()
    a = ks.load_vocab_floor()
    b = ks.load_vocab_floor()
    assert a == b and ks._vocab_floor_at.cache_info().hits >= 1
    assert ks._vocab_floor_at.cache_info().misses == 1


# ---------------------------------------------------------------- Codex round 3 on PR #302

def test_misses_are_deduped_capped_and_ledger_bounded(tmp_path):
    """MAJOR: one row per occurrence, no cap, no prune wrote 1,600 rows from one
    pasted transcript. Distinct candidates, at most MISS_CAP_PER_PROMPT per
    prompt, a truncated paste gets one row, and the ledger stays under its size."""
    root, q = make_instance(tmp_path)
    ledger = q / "memory" / ".knowledge-supply-misses.jsonl"
    # 60 distinct bigrams, each repeated 5 times: 300 occurrences on the wire.
    transcript = " ".join(f"Vendor Number{n} said so, Vendor Number{n} again" for n in range(60) for _ in range(5))
    run(root, transcript[:ks.PROMPT_SCAN_CHARS - 1])
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(rows) == ks.MISS_CAP_PER_PROMPT, "capped per prompt, and the cap is the whole point"
    assert len({r["candidate"] for r in rows}) == len(rows), "distinct per prompt"
    ledger.unlink()
    run(root, "x" * (ks.PROMPT_SCAN_CHARS + 10))
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert rows == [rows[0]] and rows[0]["shape"] == "large_prompt_skipped"
    ledger.write_text("".join(json.dumps({"candidate": f"Old Row{n}", "shape": "x"}) + "\n"
                              for n in range(9000)))
    assert ledger.stat().st_size > ks.MISS_LEDGER_MAX_BYTES
    run(root, "tell me about Acme Corp")
    assert ledger.stat().st_size <= ks.MISS_LEDGER_MAX_BYTES
    assert ledger.read_text().splitlines()[-1].count("Acme Corp") == 1, "newest row survives the prune"


def test_render_fits_ceiling_with_separators_and_footer(tmp_path):
    """MINOR: separators and footer were outside the byte accounting, so the
    rendered text ran past the ceiling under overflow 0. Now the fit is against
    the rendered text; unpinned items drop until it fits."""
    root, q = make_instance(tmp_path)
    # MAX_ENTITIES names, one pinned and one droppable triple each, sized so the
    # pins fit, the droppables overrun, and separators decide the last one.
    words = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet",
             "Kilo", "Lima"][:ks.MAX_ENTITIES]
    names = [f"Fitted {w}" for w in words]
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n, name in enumerate(names):
            f.write(json.dumps({"s": name, "p": "noted", "o": f"pinned {n} " + "p" * 300, "t": "2026-09-01", "project": "b"}) + "\n")
            f.write(json.dumps({"s": name, "p": "also", "o": f"droppable {n} " + "d" * 300, "t": "2026-08-01", "project": "b"}) + "\n")
    b = run(root, "status on " + ", ".join(names))
    text = ks.render(b)
    assert len(text) <= b["budget"]["ceiling"]
    assert b["budget"]["overflow"] == 0 and b["budget"]["used"] == len(text)
    assert b["budget"]["cut"] > 0 and b["receipt"]["ceiling_hit"] is True
    assert all(items_of(b, "graph", name) for name in names), "every pin kept"
    # The fit loop in isolation, where fixture sizing cannot mask it: lower the
    # ceiling to just under the rendered size and the loop must drop unpinned
    # items until the RENDERED text fits, with the numbers matching the wire.
    tight = len(text) - 10
    cut_before = b["budget"]["cut"]
    cut, hit, overflow = ks.fit_to_ceiling(b, tight, cut_before, 0, False)
    assert len(ks.render(b)) <= tight and overflow == 0 and hit is True and cut > cut_before
    assert all(items_of(b, "graph", name) for name in names), "pins survive the tighter fit"


def test_zero_items_is_one_short_line(tmp_path):
    """MINOR: a resolved entity with nothing in any store injected an 800-char
    header. One line now: searched, nothing recorded, coverage and receipt."""
    root, _ = make_instance(tmp_path)
    b = run(root, "what did Dana Okafor say on 2019-01-01")
    assert b["items"] == []
    text = ks.render(b)
    assert len(text.splitlines()) == 1 and len(text) < 300
    assert "nothing recorded" in text and "COVERAGE: FULL" in text


def test_large_paste_against_big_index_is_fast_and_truncated(tmp_path):
    """MINOR: O(prompt x index) resolution took 7.1 s for a 109 KB paste against
    6,000 entities. Token prefilter plus a scan bound keep it well inside the
    hook's 5 s timeout, and the receipt says the prompt was truncated."""
    import time
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n in range(6000):
            f.write(json.dumps({"s": f"Person Number{n}", "p": "works_at", "o": f"Firm{n}", "t": "2026-01-01"}) + "\n")
    paste = ("Dana Okafor is in this paste. " + "lorem ipsum dolor sit amet " * 4000)[:109_000]
    t0 = time.time()
    b = run(root, paste)
    elapsed = time.time() - t0
    assert elapsed < 2.5, f"{elapsed:.2f}s"
    assert b is not None and any(e["name"] == "Dana Okafor" for e in b["entities"])
    assert b["receipt"]["prompt_truncated"] is True and b["receipt"]["prompt_chars"] == len(paste)
    # The prune itself, without a clock: 6,000+ entities, a handful of candidates.
    index = ks.build_index(ks.load_stores(q, root)[0])
    assert len(index) > 6000
    cands = ks.candidate_keys(index, ks.prompt_tokens(ks.norm(paste[:ks.PROMPT_SCAN_CHARS])))
    assert len(cands) < 20, len(cands)
    assert "dana okafor" in cands


# ---------------------------------------------------------------- Codex round 4 on PR #302 (structural)

def test_deadline_yields_partial_bundle_with_receipt(tmp_path):
    """MAJOR, structural: rounds 3 and 4 each found a different O(N x M) blowup
    that killed the hook at its 5 s timeout with nothing injected and no
    receipt. A wall-clock deadline inside supply() means the pass always
    returns what it gathered, names where it stopped, and marks every class
    after that point as NOT searched (required ones drop coverage to PARTIAL)."""
    root, _ = make_instance(tmp_path)
    b = run(root, "what have we promised Dana Okafor", deadline_s=0.0)
    assert b is not None, "a deadline never returns nothing"
    d = b["receipt"]["deadline_hit"]
    assert d and d["at_class"] and d["at_entity"] == "Dana Okafor"
    rows = {s["class"]: s for s in b["receipt"]["sources"]}
    assert any(s["searched"] is False and s["problem"] == "not searched (deadline)" for s in rows.values())
    assert b["coverage"]["verdict"] == "PARTIAL"
    assert any("deadline" in v for v in b["coverage"]["missing_paths"].values())
    text = ks.render(b)
    assert "DEADLINE: stopped after" in text and "NOT searched" in text
    b2 = run(root, "what have we promised Dana Okafor")
    assert b2["receipt"]["deadline_hit"] is None and b2["coverage"]["verdict"] == "FULL"


def test_entities_capped_and_dropped_names_in_receipt(tmp_path):
    """Structural bound on the multiplier: at most MAX_ENTITIES resolve; the
    rest are named in the receipt and the header, never silently ignored."""
    root, q = make_instance(tmp_path)
    words = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet",
             "Kilo", "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango"]
    names = [f"Capped {w}" for w in words]
    with open(q / "memory" / "graph.jsonl", "a") as f:
        for n, name in enumerate(names):
            f.write(json.dumps({"s": name, "p": "noted", "o": f"thing {n}", "t": "2026-09-01", "project": "b"}) + "\n")
    b = run(root, "status on " + ", ".join(names))
    assert len(b["entities"]) == ks.MAX_ENTITIES
    assert len(b["receipt"]["entities_dropped"]) == len(names) - ks.MAX_ENTITIES
    assert "ENTITIES DROPPED" in ks.render(b) and b["receipt"]["entities_dropped"][0] in ks.render(b)


# ---------------------------------------------------------------- Phase 2: recall producer

def test_recall_records_each_surfaced_source_once(tmp_path):
    """Every distinct source file the pass surfaced lands in the session recall
    artifact under this session, so memory_autocapture can score it at Stop
    (useful if opened, dead_end if never touched). record=False writes nothing."""
    root, q = make_instance(tmp_path)
    recall = tmp_path / "recall.json"
    b = run(root, "what do we know about Dana Okafor", recall_path=recall)
    entries = json.loads(recall.read_text())["test-session"]["surfaced"]
    srcs = {e["source_file"] for e in entries}
    assert srcs == {i["abs_src"] for i in b["items"]} and len(srcs) > 1
    assert len(entries) == len(srcs), "one entry per source file"
    assert all(e["memory_id"].startswith("knowledge-supply:") for e in entries)
    recall.unlink()
    run(root, "what do we know about Dana Okafor", record=False, recall_path=recall)
    assert not recall.exists()


# ---------------------------------------------------------------- ASK-1261: one chokepoint + captured minors

def test_single_token_chokepoint_all_paths(tmp_path):
    """Contact heading, uppercase alias, first-name expansion: none fires at the
    start of a sentence, a line or a bullet; each fires mid-sentence."""
    root, _ = make_instance(tmp_path)
    for path, tok in (("contact", "Ally"), ("alias", "DO"), ("first_name", "Dana")):
        for prompt in (f"{tok} said hi", f"Fix it\n{tok} said hi", f"- {tok} said hi", f"1. {tok} said hi"):
            assert run(root, prompt) is None, (path, prompt)
        assert run(root, f"please ask {tok} about it") is not None, path
    assert "Ally" in {e["name"] for e in run(root, "please ask Ally about it")["entities"]}
    assert "Dana Okafor" in {e["name"] for e in run(root, "please ask DO about it")["entities"]}


def test_initial_position_has_one_call_site():
    """The grep-the-tree half of ASK-1261: the initial-position rule is called
    from exactly one place in the engine, the chokepoint."""
    lines = LIB.read_text().splitlines()
    calls = [l for l in lines if "is_initial_position(" in l
             and not l.lstrip().startswith(("def ", "#")) and '"""' not in l]
    assert len(calls) == 1, calls
    assert "single_token_hit" in "\n".join(lines[max(0, lines.index(calls[0]) - 40):lines.index(calls[0])])


def test_unreadable_markdown_class_is_unreadable_not_empty(tmp_path):
    """sp-ca1769db: every file of a markdown class unreadable -> the class is
    a recorded problem and a required one drops coverage; never present, 0 hits."""
    root, q = make_instance(tmp_path)
    tt = q / "canonical" / "talk-tracks.md"
    tt.chmod(0)
    try:
        b = run(root, "what do we know about Dana Okafor")
    finally:
        tt.chmod(0o644)
    row = {s["class"]: s for s in b["receipt"]["sources"]}["canonical"]
    assert row["problem"] and "talk-tracks" in row["problem"] and row["present"] is False
    assert b["coverage"]["verdict"] == "PARTIAL" and "canonical" in b["coverage"]["missing"]


def test_non_object_loops_is_a_problem_not_a_crash(tmp_path):
    """sp-a4a5028a: a bare JSON string in open-loops.json is a recorded problem."""
    root, q = make_instance(tmp_path)
    (q / "memory" / "open-loops.json").write_text('"junk"')
    b = run(root, "what do we know about Dana Okafor")
    assert b is not None
    row = {s["class"]: s for s in b["receipt"]["sources"]}["loops"]
    assert row["present"] is False and "not an object" in row["problem"]


def test_duplicate_facts_keep_each_entity_section(tmp_path):
    """sp-1b3ef442: a line naming two entities renders under both sections."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        f.write(json.dumps({"s": "Priya Raman", "p": "works_at", "o": "Vendor Co", "t": "2026-08-01", "project": "v"}) + "\n")
        f.write(json.dumps({"s": "Tomas Lind", "p": "works_at", "o": "Vendor Co", "t": "2026-08-01", "project": "v"}) + "\n")
    with open(q / "canonical" / "talk-tracks.md", "a") as f:
        f.write("Priya Raman and Tomas Lind both own the vendor review.\n")
    b = run(root, "what do we know about Priya Raman and Tomas Lind")
    assert items_of(b, "canonical", "Priya Raman") and items_of(b, "canonical", "Tomas Lind")
    text = ks.render(b)
    assert "== Priya Raman ==" in text and "== Tomas Lind ==" in text


def test_conflict_only_when_newest_two_differ(tmp_path):
    """sp-67d54572: two newest rows on one date that AGREE are not a conflict;
    the older differing row is STALE."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        f.write(json.dumps({"s": "Dana Okafor", "p": "status", "o": "memo on hold pending send decision",
                            "t": "2026-09-01", "project": "acme-app"}) + "\n")
    b = run(root, "what is the memo status for Dana Okafor")
    status = [i for i in items_of(b, "graph", "Dana Okafor") if i["predicate"] == "status"]
    assert not any(i["status"] == "CONFLICTING" for i in status)
    assert [i for i in status if i["t"] == "2026-08-20"][0]["status"] == "STALE"


def test_miss_bigrams_overlap_and_skip_openers(tmp_path):
    """sp-c9b6401d: 'Ping Sarah Chen about The Acme Contract' records the two
    names, not the opener and the article."""
    root, q = make_instance(tmp_path)
    run(root, "Ping Sarah Chen about The Acme Contract")
    rows = [json.loads(l) for l in (q / "memory" / ".knowledge-supply-misses.jsonl").read_text().splitlines()]
    assert {r["candidate"] for r in rows} == {"Sarah Chen", "Acme Contract"}


def test_item_text_capped_with_marker(tmp_path):
    """sp-d830d71e: one multi-KB object cannot carry the ceiling; the text is cut
    with an explicit marker, the src stays, the render fits."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:
        f.write(json.dumps({"s": "Dana Okafor", "p": "noted", "o": "x" * 5000, "t": "2026-09-03", "project": "acme-app"}) + "\n")
    b = run(root, "what do we know about Dana Okafor")
    big = [i for i in items_of(b, "graph", "Dana Okafor") if i["predicate"] == "noted"][0]
    assert big["text"].endswith("open src]") and len(big["text"]) < ks.ITEM_MAX_CHARS + 60
    assert len(ks.render(b)) <= b["budget"]["ceiling"] and b["budget"]["overflow"] == 0


# ---------------------------------------------------------------- ASK-1261 review round

def test_unreadable_is_every_file_not_zero_hits(tmp_path):
    """One unreadable file among readable ones never marks the class
    unreadable, with or without hits; every file failing does."""
    root, q = make_instance(tmp_path)
    (q / "canonical" / "objections.md").write_text("# Objections\nNothing about anyone here.\n")
    tt = q / "canonical" / "talk-tracks.md"
    tt.chmod(0)
    try:
        b_hits = run(root, "what do we know about Dana Okafor")
        b_none = run(root, "what do we know about Mark Chen")
    finally:
        tt.chmod(0o644)
    for b in (b_hits, b_none):
        row = {s["class"]: s for s in b["receipt"]["sources"]}["canonical"]
        assert row["present"] is True and row["problem"] and "talk-tracks" in row["problem"]
        assert b["coverage"]["verdict"] == "FULL", "one unreadable file among readable ones is not PARTIAL"
    (q / "canonical" / "objections.md").chmod(0)
    tt.chmod(0)
    try:
        b = run(root, "what do we know about Mark Chen")
    finally:
        tt.chmod(0o644)
        (q / "canonical" / "objections.md").chmod(0o644)
    assert b["coverage"]["verdict"] == "PARTIAL" and "canonical" in b["coverage"]["missing"]


def test_identifier_initial_position_survives_casefold_expansion(tmp_path):
    """A casefold-expanding character before a line-initial slug must not shift
    the offset the initial-position rule reads."""
    root, _ = make_instance(tmp_path)
    assert run(root, "Straße\nacme-labs said hi") is None
    assert run(root, "Straße, then acme-labs said hi") is not None


def test_relationship_block_is_not_cut(tmp_path):
    root, q = make_instance(tmp_path)
    with open(q / "my-project" / "relationships.md", "a") as f:
        f.write("\n### Long Person — Ops — Big Co\n" + "".join(f"- **Note {n}:** " + "n" * 70 + "\n" for n in range(10)))
    b = run(root, "what do we know about Long Person")
    rel = items_of(b, "relationship", "Long Person")
    assert rel and len(rel[0]["text"]) > ks.ITEM_MAX_CHARS and "[cut" not in rel[0]["text"]


# ---------------------------------------------------------------- receipts and misses

def test_receipt_and_misses_are_written(tmp_path):
    root, q = make_instance(tmp_path)
    run(root, "what do we know about Dana Okafor and Acme Corp and #442")
    receipts = (q / "memory" / ".knowledge-supply-receipts.jsonl").read_text().splitlines()
    assert len(receipts) == 1
    r = json.loads(receipts[0])
    assert r["task_class"] == "entity_lookup" and r["session_id"] == "test-session"
    misses = [json.loads(l) for l in (q / "memory" / ".knowledge-supply-misses.jsonl").read_text().splitlines()]
    cands = {m["candidate"] for m in misses}
    assert "Acme Corp" in cands and "#442" in cands
    assert "Dana Okafor" not in cands


def test_record_false_writes_nothing(tmp_path):
    root, q = make_instance(tmp_path)
    run(root, "what do we know about Dana Okafor", record=False)
    assert not (q / "memory" / ".knowledge-supply-receipts.jsonl").exists()


def test_missing_manifest_is_observable_not_silent(tmp_path):
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "knowledge-sources.json").unlink()
    assert run(root, "what do we know about Dana Okafor") is None
    r = json.loads((q / "memory" / ".knowledge-supply-receipts.jsonl").read_text().splitlines()[-1])
    assert r["error"] == "manifest_missing"


# ---------------------------------------------------------------- project folders
# Founder-directed 2026-09-05 (plan knowledge-supply-project-folders-2026-09-05):
# every project reads its OWN folder, and each 4_points investigation is its own
# knowledge base. Reproducer: 4_points had 1,475 case files and an index of 40;
# a consulting instance had 83 files and an index of 0, so the reader never woke up.

INVESTIGATION_MANIFEST = HERE.parent / "knowledge-sources.investigation.json"


def add_store(q: Path, name: str, scope_line: str, finding_line: str) -> Path:
    s = q / "investigations" / name
    (s / "canonical").mkdir(parents=True)
    (s / "memory").mkdir()
    (s / "investigation" / "findings").mkdir(parents=True)
    (s / "investigation" / "targets").mkdir(parents=True)
    (s / "canonical" / "scope.md").write_text(f"# Investigation Scope\n\n## Primary Question\n\n{scope_line}\n")
    (s / "investigation" / "findings" / "finding-001.md").write_text(
        f"# Finding 001\n\n## Summary\n\n{finding_line}\n\n## Next Steps\n\n- none\n")
    return s


def make_bare_instance(tmp: Path) -> tuple[Path, Path]:
    """A project with NO graph, relationships, commitments or meetings: documents only.
    a consulting instance's shape on 2026-09-05."""
    root = tmp / "bare"
    q = root / "q-bare"
    for d in ("canonical", "memory", "output", ".q-system"):
        (q / d).mkdir(parents=True)
    shutil.copy(MANIFEST, q / ".q-system" / "knowledge-sources.json")
    (q / "canonical" / "client-profile.md").write_text("# Client\n\nThe client sells gold coins.\n")
    (q / "output" / "brief-2026-08-14.md").write_text(
        "# Brief\n\nBluepeak asked for a name column on the intake form.\n\n## Next Steps\n\n- reply to the carrier\n")
    return root, q


def receipt_row(bundle, cls):
    return next(r for r in bundle["receipt"]["sources"] if r["class"] == cls)


def test_store_named_in_prompt_scopes_to_that_store(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-001-foo-bar", "Why does Foo Bar keep getting breached?", "Dana Okafor briefed the Foo Bar victim list.")
    add_store(q, "case-002-other-thing", "What is Other Thing?", "Dana Okafor also appears in the Other Thing case.")
    b = run(root, "what do we know about foo bar")
    assert b is not None
    ents = {e["name"]: e for e in b["entities"]}
    assert "foo bar" in ents and ents["foo bar"]["kind"] == "store" and ents["foo bar"]["stores"] == ["case-001-foo-bar"]
    srcs = [i["src"] for i in b["items"]]
    assert any("investigations/case-001-foo-bar/canonical/scope.md:5" in s for s in srcs), srcs
    assert any("investigations/case-001-foo-bar/investigation/findings/finding-001.md:5" in s for s in srcs), srcs
    assert not any("case-002-other-thing" in s for s in srcs), srcs


def test_store_plus_person_never_leaks_the_other_store(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    add_store(q, "case-002-other-thing", "scope", "Dana Okafor also appears in the Other Thing case.")
    b = run(root, "in foo bar, what did Dana Okafor brief")
    dana = items_of(b, entity="Dana Okafor")
    assert any("case-001-foo-bar" in i["src"] for i in dana), [i["src"] for i in dana]
    assert not any("case-002-other-thing" in i["src"] for i in b["items"]), [i["src"] for i in b["items"]]
    assert any(i["kind"] == "graph" for i in dana)   # project-level stores are always in scope


def test_no_store_named_searches_every_store(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    add_store(q, "case-002-other-thing", "scope", "Dana Okafor also appears in the Other Thing case.")
    b = run(root, "what do we know about Dana Okafor")
    srcs = [i["src"] for i in items_of(b, kind="doc")]
    assert any("case-001-foo-bar" in s for s in srcs) and any("case-002-other-thing" in s for s in srcs), srcs
    row = receipt_row(b, "docs")
    assert row["stores_searched"] == 3 and sorted(row["stores_hit"]) == ["case-001-foo-bar", "case-002-other-thing"]
    assert receipt_row(b, "canonical")["stores_searched"] == 3


def test_target_file_stem_fires_alone_but_a_finding_stem_does_not(tmp_path):
    root, q = make_instance(tmp_path)
    s = add_store(q, "case-003-x-case", "scope", "finding")
    (s / "investigation" / "targets" / "acme-corp.md").write_text("# acme-corp\n\nacme-corp runs the fake exchange.\n")
    (s / "investigation" / "findings" / "weird-note.md").write_text("# weird-note\n\nweird-note is a finding file.\n")
    b = run(root, "pull everything on acme-corp")
    assert b is not None and any(e["kind"] == "target" and e["name"] == "acme corp" for e in b["entities"])
    assert any(i["text"] == "acme-corp runs the fake exchange." for i in items_of(b, kind="doc"))
    b2 = run(root, "pull everything on weird-note")
    assert b2 is None or not any(e["name"] == "weird note" for e in b2["entities"])


def test_proper_nouns_file_indexes_curated_names_only(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "canonical" / "proper-nouns.txt").write_text("# names kept OUT of common words\n\nMarilyn\nBlue Peak\n")
    (q / "output" / "call-2026-09-01.md").write_text("# Call\n\nMarilyn asked for the pay sheet by Friday.\n")
    b = run(root, "what did Marilyn ask for")
    assert b is not None and any(e["kind"] == "noun" and e["name"] == "Marilyn" for e in b["entities"])
    docs = items_of(b, kind="doc", entity="Marilyn")
    assert docs and docs[0]["text"] == "Marilyn asked for the pay sheet by Friday."
    assert docs[0]["src"].endswith("output/call-2026-09-01.md:3")
    manifest, _ = ks.load_manifest(q, root)
    assert ks.load_stores(q, root, manifest)[0]["noun_names"] == ["Marilyn", "Blue Peak"], "comment and blank lines never index"


def test_docs_class_returns_verbatim_line_after_graph_and_canonical(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "output" / "notes-2026-09-01.md").write_text("# Notes\n\nDana Okafor asked for the runbook in writing.\n")
    b = run(root, "what do we know about Dana Okafor")
    docs = items_of(b, kind="doc", entity="Dana Okafor")
    assert docs and docs[0]["text"] == "Dana Okafor asked for the runbook in writing."
    assert docs[0]["src"].endswith("output/notes-2026-09-01.md:3")
    kinds = [i["kind"] for i in b["items"] if i["entity"] == "Dana Okafor"]
    assert kinds.index("doc") > kinds.index("graph") and kinds.index("doc") > kinds.index("canonical")
    row = receipt_row(b, "docs")
    assert row["engine"] == "grep" and row["files"] >= 1 and row["present"] is True


def test_docs_python_fallback_matches_grep(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    (q / "output" / "notes.md").write_text("Dana Okafor asked for the runbook in writing.\n")
    a = run(root, "what do we know about Dana Okafor")
    monkeypatch.setattr(ks.shutil, "which", lambda name: None)
    b = run(root, "what do we know about Dana Okafor")
    assert [i["src"] for i in items_of(a, kind="doc")] == [i["src"] for i in items_of(b, kind="doc")]
    assert receipt_row(a, "docs")["engine"] == "grep" and receipt_row(b, "docs")["engine"] == "python"


def test_docs_engines_agree_on_the_per_file_cap_and_both_report_it(tmp_path, monkeypatch):
    """PR #308 review round 4: grep -m capped a file at 200 silently while the
    Python scan returned 300, under searched=True. The one way the engines could
    differ is the one this fixture exercises."""
    root, q = make_instance(tmp_path)
    (q / "output" / "flood.md").write_text("".join(f"Dana Okafor line {i}\n" for i in range(300)))
    manifest, _ = ks.load_manifest(q, root)
    project, subs, _ = ks.load_all_stores(q, root, manifest)
    files = project["doc_files"]
    g_hits, g_engine = ks.search_docs(files, ["Dana Okafor"], ignore_case=True, word=False, deadline=dt.datetime.now().timestamp() + 5)
    monkeypatch.setattr(ks.shutil, "which", lambda name: None)
    p_hits, p_engine = ks.search_docs(files, ["Dana Okafor"], ignore_case=True, word=False, deadline=dt.datetime.now().timestamp() + 5)
    assert len(g_hits) == len(p_hits) == ks.GREP_MAX_PER_FILE
    assert [h[1] for h in g_hits] == [h[1] for h in p_hits]
    assert g_engine == "grep (file cap)" and p_engine == "python (file cap)"
    monkeypatch.undo()
    b = run(root, "what do we know about Dana Okafor")
    row = receipt_row(b, "docs")
    assert row["searched"] == "partial" and "file cap" in row["problem"], row
    # exactly the cap is NOT a truncation (PR #308 review round 7 minor 4)
    (q / "output" / "flood.md").write_text("".join(f"Dana Okafor line {i}\n" for i in range(ks.GREP_MAX_PER_FILE)))
    project2, subs2, _ = ks.load_all_stores(q, root, manifest)
    g2, e2 = ks.search_docs(project2["doc_files"], ["Dana Okafor"], ignore_case=True, word=False, deadline=dt.datetime.now().timestamp() + 5)
    assert len(g2) == ks.GREP_MAX_PER_FILE and e2 == "grep", (len(g2), e2)
    monkeypatch.setattr(ks.shutil, "which", lambda name: None)
    p2, pe2 = ks.search_docs(project2["doc_files"], ["Dana Okafor"], ignore_case=True, word=False, deadline=dt.datetime.now().timestamp() + 5)
    assert len(p2) == ks.GREP_MAX_PER_FILE and pe2 == "python", (len(p2), pe2)
    monkeypatch.undo()
    b2 = run(root, "what do we know about Dana Okafor")
    assert receipt_row(b2, "docs")["searched"] is True


def test_prompt_proper_noun_with_doc_hits_becomes_entity(tmp_path):
    root, q = make_bare_instance(tmp_path)
    b = run(root, "what did Bluepeak ask for")
    assert b is not None, "an index of 0 must not mean the reader never wakes up"
    e = b["entities"][0]
    assert e["name"] == "Bluepeak" and e["resolved_from"] == "docs" and e["kind"] == "docs_hit"
    assert any(i["text"] == "Bluepeak asked for a name column on the intake form." for i in items_of(b, kind="doc"))
    assert b["coverage"]["verdict"] in ("FULL", "PARTIAL")


def test_prompt_proper_noun_without_hits_lowercase_or_initial_never_fires(tmp_path):
    root, q = make_bare_instance(tmp_path)
    assert run(root, "what did Nobody ask for") is None
    assert run(root, "what did bluepeak ask for") is None
    assert run(root, "Bluepeak asked for what") is None
    assert run(root, "- Bluepeak asked for what") is None


def test_headings_never_become_entities(tmp_path):
    root, q = make_bare_instance(tmp_path)
    assert run(root, "what are the next steps") is None
    assert run(root, "what are the Next Steps here") is None


def test_docs_skip_big_hidden_and_node_modules(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "output" / "big.md").write_text("Dana Okafor big\n" + "x" * 600_000)
    (q / "output" / ".hidden").mkdir()
    (q / "output" / ".hidden" / "h.md").write_text("Dana Okafor hidden\n")
    (q / "output" / "node_modules").mkdir()
    (q / "output" / "node_modules" / "n.md").write_text("Dana Okafor node\n")
    (q / "output" / "ok.md").write_text("Dana Okafor ok\n")
    b = run(root, "what do we know about Dana Okafor")
    texts = [i["text"] for i in items_of(b, kind="doc")]
    assert "Dana Okafor ok" in texts
    assert not any(t in texts for t in ("Dana Okafor big", "Dana Okafor hidden", "Dana Okafor node"))
    assert receipt_row(b, "docs")["files"] == 1
    assert receipt_row(b, "docs")["files_skipped_oversize"] == 1, "a declared skip is counted, never silent"


def test_docs_items_are_verbatim_and_dated_by_file(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    b = run(root, "what do we know about Dana Okafor")
    for it in items_of(b, kind="doc"):
        text = Path(it["abs_src"]).read_text()
        for piece in ks.verbatim_pieces(it):
            assert piece in text
        assert it["t"] is not None


def test_shipped_manifests_declare_project_folders():
    m = json.loads(MANIFEST.read_text())
    assert m["_version"] >= 2
    assert any(s["glob"] == "investigations/case-*" for s in m["stores"])
    assert {"output", "investigation", "research"} <= set(m["folders"])
    assert {"targets", "clients"} <= set(m["entity_dirs"])
    assert {"exports", "screenshots", "raw-collections"} <= set(m["skip_dirs"]), "skips are declared, never hardcoded"
    assert set(inv_skip := json.loads(INVESTIGATION_MANIFEST.read_text())["skip_dirs"]) >= {"raw-collections"}
    assert {"store", "target", "noun"} <= set(m["entity_kinds_that_fire_alone"])
    for cls, spec in m["classes"].items():
        assert "docs" in spec["sources"], cls
    inv = json.loads(INVESTIGATION_MANIFEST.read_text())
    lookup = inv["classes"]["entity_lookup"]["sources"]
    assert lookup["graph"]["required"] and lookup["canonical"]["required"] and lookup["docs"]["required"]
    for cls, spec in inv["classes"].items():
        for name in ("commitments", "meetings", "relationships"):
            assert not spec["sources"].get(name, {}).get("required"), (cls, name)


def test_investigation_manifest_loads_as_instance_override(tmp_path):
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    for p in ("my-project/commitments.jsonl", "output/granola-cache.json", "my-project/relationships.md"):
        (q / p).unlink()
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    b = run(root, "what is still outstanding on Dana Okafor")
    assert b is not None and b["task_class"] == "commitment"
    assert b["coverage"]["verdict"] == "FULL", b["coverage"]
    assert b["receipt"]["manifest"].endswith(".q-system/data/knowledge-sources.json")


def test_corpus_common_word_is_dropped_unless_a_store_is_named(tmp_path):
    root, q = make_instance(tmp_path)
    for i in range(1, 7):
        add_store(q, f"case-00{i}-thing-{i}", "scope", f"Facebook profile checked in case {i}.")
    b0 = run(root, "update on the Facebook profiles", record=True)
    assert b0 is not None and b0["items"] == [] and "corpus-common" in ks.render(b0) and "Facebook (6 stores)" in ks.render(b0), \
        "a word in 6 of 6 cases is not a subject, and the hook still says it searched (round 7 minor 5)"
    rows = [json.loads(l) for l in (q / "memory" / ".knowledge-supply-misses.jsonl").read_text().splitlines()]
    assert any(r["candidate"] == "Facebook" and r["shape"] == "corpus_common" and r["stores"] == 6 for r in rows), rows
    b = run(root, "in thing 2, what did the Facebook profiles show")
    names = {e["name"]: e for e in b["entities"]}
    assert "Facebook" in names and names["Facebook"]["resolved_from"] == "docs"
    srcs = [i["src"] for i in items_of(b, entity="Facebook")]
    assert srcs and all("case-002-thing-2" in s for s in srcs), srcs


def test_dropped_candidates_are_named_in_the_receipt(tmp_path):
    root, q = make_instance(tmp_path)
    for i in range(1, 7):
        add_store(q, f"case-00{i}-thing-{i}", "scope", f"Facebook profile checked in case {i}.")
    b = run(root, "what do we know about Dana Okafor and the Facebook profiles")
    assert b is not None and not any(e["name"] == "Facebook" for e in b["entities"])
    assert b["receipt"]["candidates_dropped"] == [{"candidate": "Facebook", "stores": 6}]


# PR #308 review round 1: the reviewer's executed reproducers, kept as tests.

def test_same_subject_in_two_cases_searches_both(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-010-lapsus", "scope", "LAPSUS first engagement: server in Rio.")
    add_store(q, "case-041-lapsus", "scope", "LAPSUS second engagement: server in Oslo.")
    b = run(root, "what do we know about lapsus")
    ent = next(e for e in b["entities"] if e["kind"] == "store")
    assert ent["stores"] == ["case-010-lapsus", "case-041-lapsus"]
    srcs = [i["src"] for i in b["items"]]
    assert any("case-010-lapsus" in s for s in srcs) and any("case-041-lapsus" in s for s in srcs), srcs
    assert receipt_row(b, "docs")["stores_searched"] == 3
    assert "case-010-lapsus, case-041-lapsus" in ks.render(b).splitlines()[0]


def _graph(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_alias_asserted_in_one_case_never_rewrites_another(tmp_path):
    root, q = make_instance(tmp_path)
    a = add_store(q, "case-010-alpha", "scope", "alpha finding")
    b_ = add_store(q, "case-020-bravo", "scope", "bravo finding")
    _graph(a / "memory" / "graph.jsonl", [
        {"s": "Widget Corp", "p": "alias_of", "o": "Zeta Holdings", "t": "2026-09-01"},
        {"s": "Zeta Holdings", "p": "status", "o": "under sanctions", "t": "2026-09-02"},
    ])
    _graph(b_ / "memory" / "graph.jsonl", [
        {"s": "Widget Corp", "p": "status", "o": "clean, no findings", "t": "2026-09-03"},
    ])
    b = run(root, "what do we know about Widget Corp")
    names = {e["name"]: e for e in b["entities"]}
    assert "Widget Corp" in names, "a name another case contributed on its own survives the alias edge"
    assert "Zeta Holdings" in names and names["Zeta Holdings"]["via_alias"] == "Widget Corp"
    assert names["Zeta Holdings"]["alias_stores"] == {"Widget Corp": ["case-010-alpha"]}
    widget = items_of(b, entity="Widget Corp")
    zeta = items_of(b, entity="Zeta Holdings")
    assert widget and all("case-020-bravo" in i["src"] for i in widget), [i["src"] for i in widget]
    assert zeta and all("case-010-alpha" in i["src"] for i in zeta), [i["src"] for i in zeta]
    assert not any("clean, no findings" in i["text"] for i in zeta), "case-020's line never lands under Zeta"
    assert "(via alias Widget Corp: case-010-alpha)" in ks.render(b).splitlines()[0]


def test_project_level_alias_still_applies_everywhere(tmp_path):
    root, q = make_instance(tmp_path)   # the fixture graph has "DO alias_of Dana Okafor" at the project level
    add_store(q, "case-001-foo-bar", "DO briefed the Foo Bar victim list.", "finding")
    b = run(root, "what do we know about Dana Okafor")
    hits = [i for i in items_of(b, kind="canonical", entity="Dana Okafor") if "case-001-foo-bar" in i["src"]]
    assert hits and hits[0]["text"] == "DO briefed the Foo Bar victim list.", "a project-level alias reaches every case"


def test_deadline_on_the_first_required_class_is_not_full(tmp_path):
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list yesterday.")
    b = run(root, "what happened yesterday with Dana Okafor", deadline_s=0)
    assert b is not None and b["task_class"] == "temporal_event"
    assert b["coverage"]["verdict"] != "FULL", b["coverage"]
    assert "docs" in b["coverage"]["missing"]
    row = receipt_row(b, "docs")
    assert row["searched"] is False and row["stores_searched"] == 0 and row["problem"] == "not searched (deadline)"


def test_receipt_says_when_the_corpus_common_rule_cannot_run(tmp_path):
    root, q = make_bare_instance(tmp_path)
    for i in range(8):
        (q / "output" / f"r{i}.md").write_text("Bluepeak again.\n")
    b = run(root, "what did Bluepeak ask for")
    assert b["receipt"]["candidate_rule"] == {"max_stores": 4, "applicable": False, "note": "single store: rule cannot run"}
    root2, q2 = make_instance(tmp_path)
    add_store(q2, "case-001-foo-bar", "scope", "x")
    b2 = run(root2, "what do we know about Dana Okafor")
    assert b2["receipt"]["candidate_rule"]["applicable"] is True


# PR #308 review round 2: truncation is one rule, the docs fold is bounded, one block per case.

def test_truncated_docs_search_is_partial_never_full(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    for reason in ("grep (timeout)", "grep (deadline)", "python (budget)", "grep (hit cap)"):
        monkeypatch.setattr(ks, "search_docs", lambda files, patterns, **kw: ([], reason))
        b = run(root, "what do we know about Dana Okafor")
        row = receipt_row(b, "docs")
        assert row["searched"] == "partial" and row["problem"].startswith("partially searched ("), (reason, row)
        assert b["coverage"]["verdict"] != "FULL" and "docs" in b["coverage"]["missing"], (reason, b["coverage"])
        assert "partially searched" in b["coverage"]["missing_paths"]["docs"]


def test_docs_hit_cap_bounds_the_fold(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    (q / "output" / "flood.md").write_text("".join(f"Dana Okafor line {i}\n" for i in range(3000)))
    monkeypatch.setattr(ks, "MAX_DOC_HITS", 40)
    b = run(root, "what do we know about Dana Okafor")
    row = receipt_row(b, "docs")
    assert "(hit cap)" in row["engine"] and row["searched"] == "partial", row
    assert len(items_of(b, kind="doc")) <= 40
    monkeypatch.setattr(ks.shutil, "which", lambda name: None)
    b2 = run(root, "what do we know about Dana Okafor")
    assert "(hit cap)" in receipt_row(b2, "docs")["engine"]


def test_same_name_in_two_cases_renders_one_block_per_case(tmp_path):
    root, q = make_instance(tmp_path)
    a = add_store(q, "case-010-alpha", "scope", "alpha")
    b_ = add_store(q, "case-020-bravo", "scope", "bravo")
    _graph(a / "memory" / "graph.jsonl", [{"s": "John Smith", "p": "role", "o": "the victim in alpha", "t": "2026-09-01"}])
    _graph(b_ / "memory" / "graph.jsonl", [{"s": "John Smith", "p": "role", "o": "the suspect in bravo", "t": "2026-09-02"}])
    b = run(root, "what do we know about John Smith")
    out = ks.render(b)
    assert "== John Smith [case-010-alpha] ==" in out and "== John Smith [case-020-bravo] ==" in out
    assert "\n== John Smith ==\n" not in out, "no project-level block when the project has nothing"
    alpha = out.index("[case-010-alpha] ==")
    bravo = out.index("[case-020-bravo] ==")
    assert bravo < alpha, "the newer case (2026-09-02) renders first (PR #308 review round 8)"
    assert out.index("the victim in alpha") > alpha and out.index("the suspect in bravo") > bravo and out.index("the suspect in bravo") < alpha
    assert all(i["status"] == "KNOWN" for i in items_of(b, kind="graph")), "a case never supersedes another case"


def test_project_block_comes_before_case_blocks(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    out = ks.render(run(root, "what do we know about Dana Okafor"))
    assert out.index("== Dana Okafor ==") < out.index("== Dana Okafor [case-001-foo-bar] ==")


# PR #308 review round 3: the fold's deadline always ends it; the project walk never enters a case.

def test_docs_fold_stops_at_the_deadline_even_after_a_hit_cap(tmp_path, monkeypatch):
    import time as _time
    root, q = make_instance(tmp_path)
    (q / "output" / "one.md").write_text("Dana Okafor line\n")
    manifest, _ = ks.load_manifest(q, root)
    project, subs, _ = ks.load_all_stores(q, root, manifest)
    ent = {"name": "Dana Okafor", "kind": "contact", "aliases": [], "alias_stores": {}, "stores": []}
    f = q / "output" / "one.md"
    flood = [(f, 1, "Dana Okafor line")] * 200_000
    for engine_in in ("grep (hit cap)", "grep"):
        monkeypatch.setattr(ks, "search_docs", lambda files, patterns, **kw: (flood, engine_in))
        t0 = _time.time()
        out, meta = ks.resolve_docs([ent], [project] + subs, root, {}, deadline=_time.time() - 1)
        assert _time.time() - t0 < 1.0, "the fold must end at the deadline, not after 200,000 hits"
        assert sum(len(v) for by in out.values() for v in by.values()) <= 500
        assert "(deadline)" in meta["engine"] or "(hit cap)" in meta["engine"]
        if engine_in == "grep (hit cap)":
            assert meta["engine"] == "grep (hit cap)", "an existing stop reason is kept, not doubled"


def test_project_store_never_indexes_a_substore_target(tmp_path):
    root, q = make_instance(tmp_path)   # relationships.md present: the loop that used to rebind `name`
    s = add_store(q, "case-003-x-case", "scope", "finding")
    (s / "investigation" / "targets" / "acme-corp.md").write_text("# acme-corp\n")
    manifest, _ = ks.load_manifest(q, root)
    project, subs, _ = ks.load_all_stores(q, root, manifest)
    assert project["name"] == "project" and "acme corp" not in project["target_names"], project["target_names"]
    assert subs[0]["target_names"] == ["acme corp"]
    assert not any("case-003-x-case" in str(f) for f in project["doc_files"])


# PR #308 review round 4: order inside a store is by file time, then mentions, never by name.

def test_docs_order_is_file_time_then_mentions_never_path(tmp_path):
    import os as _os
    root, q = make_instance(tmp_path)
    same = 1_700_000_000
    for i in range(1, 10):
        f = q / "output" / f"z-noise-{i}.md"
        f.write_text("Dana Okafor filler.\n")
        _os.utime(f, ns=(same * 10**9, same * 10**9))
    ans = q / "output" / "a-the-answer.md"
    ans.write_text("Dana Okafor ANSWER one.\nDana Okafor ANSWER two.\nDana Okafor ANSWER three.\n")
    _os.utime(ans, ns=(same * 10**9, same * 10**9))
    b = run(root, "what do we know about Dana Okafor")
    docs = items_of(b, kind="doc")
    assert docs and "a-the-answer.md" in docs[0]["src"], [i["src"] for i in docs]
    assert [i["src"].rsplit(":", 1)[-1] for i in docs[:3]] == ["1", "2", "3"], "lines of one file stay in file order"
    newer = q / "output" / "b-newer.md"
    newer.write_text("Dana Okafor newer.\n")
    _os.utime(newer, ns=((same + 60) * 10**9, (same + 60) * 10**9))
    b2 = run(root, "what do we know about Dana Okafor")
    assert "b-newer.md" in items_of(b2, kind="doc")[0]["src"], "a file one minute newer on the same date wins"


# PR #308 review round 5: unreadable anywhere in scope is never FULL; a candidate stays case-sensitive.

def test_unreadable_copy_in_one_store_is_never_full(tmp_path):
    root, q = make_instance(tmp_path)
    s = add_store(q, "case-045-zeta", "scope", "finding")
    _graph(s / "memory" / "graph.jsonl", [{"s": "Dana Okafor", "p": "status", "o": "sanctioned in zeta", "t": "2026-09-05"}])
    ok = run(root, "what do we know about Dana Okafor")
    assert ok["coverage"]["verdict"] == "FULL", "control: a readable case graph is FULL"
    (s / "memory" / "graph.jsonl").write_text('{"s": "Dana Okafor", "p": "status", "o": "sanct\n')   # a killed writer
    b = run(root, "what do we know about Dana Okafor")
    assert b["coverage"]["verdict"] != "FULL", b["coverage"]
    assert b["coverage"]["missing_paths"]["graph"].endswith("unreadable in case-045-zeta")
    row = receipt_row(b, "graph")
    assert row["present"] is True and row["searched"] == "partial" and "case-045-zeta: unreadable" in row["problem"]
    assert "unreadable in case-045-zeta" in ks.render(b).splitlines()[0], "the header, not only the receipt, says it"
    # the mirror image: the PROJECT graph corrupt, one healthy case, still never FULL
    (s / "memory" / "graph.jsonl").write_text(json.dumps({"s": "Dana Okafor", "p": "owns", "o": "zeta", "t": "2026-09-05"}) + "\n")
    (q / "memory" / "graph.jsonl").write_text("{not json\n{still not\n")
    b2 = run(root, "what do we know about Dana Okafor")
    assert b2["coverage"]["verdict"] != "FULL" and "unreadable in project" in b2["coverage"]["missing_paths"]["graph"]


def test_docs_candidate_stays_case_sensitive_in_every_resolver(tmp_path):
    root, q = make_bare_instance(tmp_path)
    (q / "canonical" / "client-profile.md").write_text("# Client\n\nthe bluepeak channel is closed for now.\n")
    b = run(root, "what did Bluepeak ask for")
    ent = next(e for e in b["entities"] if e["name"] == "Bluepeak")
    assert ent["case_sensitive"] is True
    texts = [i["text"] for i in b["items"]]
    assert "Bluepeak asked for a name column on the intake form." in texts
    assert not any("bluepeak channel" in t for t in texts), texts


# PR #308 review round 6: the stop reason is a field; dedupe keeps stores apart; a store name survives.

def test_candidate_pass_truncation_is_partial_without_monkeypatch(tmp_path):
    """The reviewer's fixture: the index pass (Dana Okafor) finishes clean, the
    candidate pass (Bluepeak, 300 lines) hits grep -m. No monkeypatch, so a
    composed engine string cannot hide the stop the way it did in round 6."""
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    (q / "output" / "flood.md").write_text("".join(f"Bluepeak asked line {i}\n" for i in range(300)))
    b = run(root, "what did Bluepeak ask Dana Okafor about")
    assert any(e["name"] == "Bluepeak" and e["kind"] == "docs_hit" for e in b["entities"])
    row = receipt_row(b, "docs")
    assert row["searched"] == "partial", row
    assert "file cap" in row["problem"] and "candidates" in row["engine"], row
    assert b["coverage"]["verdict"] != "FULL" and "docs" in b["coverage"]["missing"], b["coverage"]


def test_identical_line_in_two_cases_keeps_both(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-010-alpha", "scope", "Dana Okafor reused the same bulletproof host.")
    add_store(q, "case-041-beta", "scope", "Dana Okafor reused the same bulletproof host.")
    b = run(root, "what do we know about Dana Okafor")
    docs = [i for i in items_of(b, kind="doc") if "bulletproof" in i["text"]]
    assert sorted(i["store"] for i in docs) == ["case-010-alpha", "case-041-beta"], [i["src"] for i in docs]
    out = ks.render(b)
    assert "[case-010-alpha] ==" in out and "[case-041-beta] ==" in out
    assert b["budget"]["cut"] == 0


def test_named_store_survives_the_longest_name_rule(tmp_path):
    root, q = make_instance(tmp_path)
    a = add_store(q, "case-010-zeta", "scope", "zeta finding")
    b_ = add_store(q, "case-020-other", "scope", "other finding")
    _graph(a / "memory" / "graph.jsonl", [{"s": "Zeta Holdings", "p": "status", "o": "sanctioned", "t": "2026-09-05"}])
    _graph(b_ / "memory" / "graph.jsonl", [{"s": "Zeta Holdings", "p": "status", "o": "clean", "t": "2026-09-05"}])
    b = run(root, "in zeta, what do we know about Zeta Holdings")
    assert any(e["kind"] == "store" and e["stores"] == ["case-010-zeta"] for e in b["entities"]), b["entities"]
    srcs = [i["src"] for i in b["items"]]
    assert srcs and not any("case-020-other" in s for s in srcs), srcs


# PR #308 review round 7: docs read failures are counted; a scoped search says so; the rule declares itself.

def test_unreadable_doc_files_are_counted_and_an_all_failed_store_degrades(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    s = add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    (q / "output" / "ok.md").write_text("Dana Okafor ok\n")
    only = s / "investigation" / "findings" / "finding-001.md"
    for engine_off in (False, True):
        if engine_off:
            monkeypatch.setattr(ks.shutil, "which", lambda name: None)
        only.chmod(0)
        try:
            b = run(root, "what do we know about Dana Okafor")
        finally:
            only.chmod(0o644)
        row = receipt_row(b, "docs")
        assert row["problem"] and "1 of 1 doc file(s) unreadable" in row["problem"], row
        assert row["searched"] == "partial" and "case-001-foo-bar" in b["coverage"]["missing_paths"].get("docs", ""), b["coverage"]
        assert b["coverage"]["verdict"] != "FULL"
    # one unreadable among readable ones in the SAME store: recorded, never PARTIAL
    (q / "output" / "bad.md").write_text("Dana Okafor bad\n")
    (q / "output" / "bad.md").chmod(0)
    only.chmod(0o644)
    try:
        b2 = run(root, "what do we know about Dana Okafor")
    finally:
        (q / "output" / "bad.md").chmod(0o644)
    row2 = receipt_row(b2, "docs")
    assert "1 of 2 doc file(s) unreadable" in (row2["problem"] or "") and row2["searched"] is True, row2


def test_scoped_search_names_what_it_left_out(tmp_path):
    root, q = make_instance(tmp_path)
    for i in (1, 2, 3):
        add_store(q, f"case-00{i}-thing-{i}", "scope", f"Dana Okafor fact {i}.")
    add_store(q, "case-031-payment-fraud", "scope", "nothing here")
    b = run(root, "for the payment fraud workstream, what do we know about Dana Okafor")
    assert b["coverage"]["scope"] == ["case-031-payment-fraud"]
    assert b["coverage"]["stores_excluded"] == ["case-001-thing-1", "case-002-thing-2", "case-003-thing-3"]
    head = ks.render(b).splitlines()[0]
    assert "WITHIN SCOPE case-031-payment-fraud + project only; 3 other stores not searched" in head, head
    assert b["receipt"]["stores_excluded"] == b["coverage"]["stores_excluded"]
    b2 = run(root, "what do we know about Dana Okafor")
    assert b2["coverage"]["scope"] == [] and "scope:" not in ks.render(b2).splitlines()[0]


def test_corpus_common_rule_declares_itself_inapplicable_when_the_candidate_pass_truncated(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    for i in range(1, 7):
        add_store(q, f"case-00{i}-thing-{i}", "scope", "Wachovia Trust checked here.")
    # Six stores, one line each, cap five: the cut hit set still spans five stores,
    # so a rule applied over it WOULD drop the candidate; the correct code does not.
    monkeypatch.setattr(ks, "MAX_DOC_HITS", 5)
    b = run(root, "what do we know about Wachovia Trust and Dana Okafor")
    rule = b["receipt"]["candidate_rule"]
    assert rule["applicable"] is False and "candidate pass truncated" in rule["note"], rule
    assert b["receipt"]["candidates_dropped"] == [], "a count over a cut hit set is not a count"
    assert any(e["name"] == "Wachovia Trust" for e in b["entities"]), "admitted, and the receipt says the rule did not run"


# PR #308 review round 8: no store is dropped whole by the ceiling; cases order newest first; a target scopes.

def test_every_store_with_a_hit_keeps_one_line_under_the_ceiling(tmp_path):
    """A newest store with a lot to say cannot starve the others of their one line."""
    root, q = make_instance(tmp_path)
    big = add_store(q, "case-003-charlie", "scope", "nothing about anyone")
    # inside the per-store caps (12 graph, 6 docs) and still past the ceiling on its own
    _graph(big / "memory" / "graph.jsonl", [{"s": "Satoshi Nakamoto", "p": "owns", "o": f"thing {k} " + "x" * 540, "t": "2026-09-03"} for k in range(12)])
    (big / "investigation" / "findings" / "flood.md").write_text("".join(f"Satoshi Nakamoto note {k} " + "y" * 420 + "\n" for k in range(6)))
    for i in (1, 2):
        s = add_store(q, f"case-00{i}-alpha{i}", "scope", "nothing about anyone")
        _graph(s / "memory" / "graph.jsonl", [{"s": "Satoshi Nakamoto", "p": "owns", "o": f"older thing {i}", "t": f"2026-08-0{i}"}])
    b = run(root, "what do we know about Satoshi Nakamoto")
    assert b["budget"]["cut"] > 0, "the ceiling must actually bite for this test to mean anything"
    assert {i.get("store") for i in b["items"]} >= {"case-001-alpha1", "case-002-alpha2", "case-003-charlie"}
    assert b["budget"]["stores_cut"] == [] and "CEILING:" not in ks.render(b)
    assert ks.render(b).splitlines()[2] == "== Satoshi Nakamoto [case-003-charlie] ==", "newest store first"
    assert len(ks.render(b)) <= 8000, "block headings are inside the budget now"


def test_ceiling_keeps_the_newest_stores_and_names_the_cut(tmp_path):
    """The reviewer's shape: 60 cases mention the subject, the answer is the only
    line in the newest one. Under the ceiling the newest cases survive, the
    oldest are cut, and the cut ones are named on the wire."""
    root, q = make_instance(tmp_path)
    for i in range(1, 60):
        s = add_store(q, f"case-{i:03d}-alpha{i:02d}", "scope", "nothing about anyone")
        day = f"2026-{7 + i // 28:02d}-{i % 28 + 1:02d}"
        _graph(s / "memory" / "graph.jsonl", [{"s": "Satoshi Nakamoto", "p": "owns", "o": f"thing {i} " + "x" * 90, "t": day}])
    add_store(q, "case-060-alpha60", "scope", "Satoshi Nakamoto ANSWER lives here.")
    b = run(root, "what do we know about Satoshi Nakamoto")
    assert any("ANSWER lives here" in i["text"] for i in b["items"]), "the newest case reaches the model"
    assert ks.render(b).splitlines()[2] == "== Satoshi Nakamoto [case-060-alpha60] =="
    cut_stores = b["budget"]["stores_cut"]
    assert cut_stores, "60 lines of this size cannot fit 8,000 chars; something must be cut"
    kept_nums = {int(i["store"].split("-")[1]) for i in b["items"] if i.get("store", "").startswith("case-")}
    cut_nums = {int(s.split("-")[1]) for s in cut_stores}
    assert max(cut_nums) < min(kept_nums), (sorted(cut_nums)[-3:], sorted(kept_nums)[:3])
    assert f"CEILING: {len(cut_stores)} store(s) with hits reached you with nothing: " in ks.render(b)
    assert b["receipt"]["stores_cut"] == cut_stores and len(ks.render(b)) <= 8000


def test_a_store_cut_by_the_ceiling_is_named(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    for i in range(1, 4):
        s = add_store(q, f"case-00{i}-alpha{i}", "scope", "Dana Okafor " + "y" * 300 + f" {i}.")
    b = run(root, "what do we know about Dana Okafor")
    bundle_items = list(b["items"])
    kept = [i for i in bundle_items if (i.get("store") or "project") != "case-003-alpha3"]
    assert ks.stores_cut_by_ceiling(bundle_items, kept) == ["case-003-alpha3"]
    b["budget"]["stores_cut"] = ["case-003-alpha3"]
    assert "CEILING: 1 store(s) with hits reached you with nothing: case-003-alpha3" in ks.render(b)


def test_target_stem_scopes_to_the_declaring_case(tmp_path):
    root, q = make_instance(tmp_path)
    for i in range(1, 7):
        add_store(q, f"case-00{i}-alpha{i}", "scope", f"Miami appears in case {i}.")
    t = q / "investigations" / "case-001-alpha1" / "investigation" / "targets" / "miami.md"
    t.write_text("# miami\n\nMiami target notes.\n")
    b = run(root, "what do we know about miami")
    ent = next(e for e in b["entities"] if e["kind"] == "target")
    assert ent["stores"] == ["case-001-alpha1"]
    assert b["coverage"]["scope"] == [] and b["coverage"]["stores_excluded"] == [], "a filename is never a prompt scope"
    miami = items_of(b, entity="miami")
    assert miami and all(i.get("store") in ("case-001-alpha1", "project") for i in miami), [i["src"] for i in miami]
    assert "[target of case-001-alpha1]" in ks.render(b).splitlines()[0]


def test_unreadable_handoff_is_filed_under_handoff(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "memory" / "last-handoff.md").chmod(0)
    try:
        b = run(root, "what do we know about Dana Okafor")
    finally:
        (q / "memory" / "last-handoff.md").chmod(0o644)
    row = receipt_row(b, "handoff")
    assert row["problem"] and "last-handoff" in row["problem"] and row["present"] is False, row   # unreadable, the way a ledger is
    assert receipt_row(b, "canonical")["problem"] is None and receipt_row(b, "canonical")["present"] is True


def test_store_recency_beats_case_number(tmp_path):
    """An older-numbered case with newer activity renders before a newer-numbered
    quiet one; the case number is only the tie-break for a fresh checkout."""
    root, q = make_instance(tmp_path)
    a = add_store(q, "case-001-alpha", "scope", "nothing")
    b_ = add_store(q, "case-050-bravo", "scope", "nothing")
    _graph(a / "memory" / "graph.jsonl", [{"s": "Satoshi Nakamoto", "p": "owns", "o": "fresh work", "t": "2026-09-01"}])
    _graph(b_ / "memory" / "graph.jsonl", [{"s": "Satoshi Nakamoto", "p": "owns", "o": "old work", "t": "2026-07-01"}])
    heads = [l for l in ks.render(run(root, "what do we know about Satoshi Nakamoto")).splitlines() if l.startswith("== ")]
    assert heads[0] == "== Satoshi Nakamoto [case-001-alpha] ==", heads


# PR #308 review round 9: a named case wins over a shared target; the scope note is bounded; absent = never searched.

def _three_cases_sharing_a_target(q):
    for name, line in (("case-001-alpha", "Acme wired ALPHA-ONLY to the shell company"),
                       ("case-002-beta", "Acme wired BETA-ONLY to the shell company"),
                       ("case-003-gamma", "Acme wired GAMMA-ONLY to the shell company")):
        s = add_store(q, name, "scope", line)
        (s / "investigation" / "targets" / "acme.md").write_text("# acme\n")


def test_named_case_wins_over_a_target_shared_by_other_cases(tmp_path):
    root, q = make_instance(tmp_path)
    _three_cases_sharing_a_target(q)
    b = run(root, "in beta, what did acme do")
    assert b["coverage"]["scope"] == ["case-002-beta"], b["coverage"]
    assert b["coverage"]["stores_excluded"] == ["case-001-alpha", "case-003-gamma"]
    texts = [i["text"] for i in b["items"]]
    assert any("BETA-ONLY" in t for t in texts) and not any("ALPHA-ONLY" in t or "GAMMA-ONLY" in t for t in texts), texts


def test_target_shared_by_many_cases_scopes_to_all_of_them_when_none_is_named(tmp_path):
    root, q = make_instance(tmp_path)
    _three_cases_sharing_a_target(q)
    b = run(root, "what did acme do")
    assert b["coverage"]["scope"] == [] and b["coverage"]["stores_excluded"] == []
    assert "WITHIN SCOPE" not in ks.render(b)
    texts = [i["text"] for i in b["items"]]
    assert all(any(k in t for t in texts) for k in ("ALPHA-ONLY", "BETA-ONLY", "GAMMA-ONLY"))


def test_target_never_narrows_another_entity(tmp_path):
    """The round 10 reproducer: 'Orbit Holdings and the miami accounts' with
    miami a target of one case must still deliver every Orbit Holdings fact."""
    root, q = make_instance(tmp_path)
    with open(q / "memory" / "graph.jsonl", "a") as f:   # a fully-indexed subject, as in the reviewer's repro
        f.write(json.dumps({"s": "Orbit Holdings", "p": "is", "o": "a shell company", "t": "2026-09-01"}) + "\n")
    for i in range(1, 6):
        s = add_store(q, f"case-00{i}-thing{i}", "scope", f"Orbit Holdings fact {i}.")
        if i == 3:
            (s / "investigation" / "targets" / "miami.md").write_text("# miami\n\nmiami target notes\n")
    b = run(root, "what do we have on Orbit Holdings and the miami accounts")
    assert b["coverage"]["scope"] == [] and b["coverage"]["stores_excluded"] == []
    orbit = items_of(b, entity="Orbit Holdings")
    assert {i["store"] for i in orbit} >= {f"case-00{i}-thing{i}" for i in range(1, 6)}, sorted({i["store"] for i in orbit})
    miami = items_of(b, entity="miami")
    assert miami and all(i["store"] in ("case-003-thing3", "project") for i in miami)


def test_scope_note_is_bounded(tmp_path):
    root, q = make_instance(tmp_path)
    for i in range(1, 10):
        s = add_store(q, f"case-00{i}-thing{i}", "scope", f"Acme in case {i}")
        if i <= 8:
            (s / "investigation" / "targets" / "acme.md").write_text("# acme\n")
    named = ", ".join(f"thing{i}" for i in range(1, 9))
    b = run(root, f"in {named}: what did acme do")
    assert len(b["coverage"]["scope"]) == 8 and b["coverage"]["stores_excluded"] == ["case-009-thing9"]
    head = ks.render(b).splitlines()[0]
    assert "and 2 more + project only; 1 other store not searched" in head, head
    scope_clause = head.split("WITHIN SCOPE", 1)[1].split("+ project", 1)[0]
    assert scope_clause.count("case-00") == 6, scope_clause
    assert "[target of case-001-thing1, case-002-thing2, case-003-thing3, case-004-thing4, case-005-thing5, case-006-thing6 and 2 more]" in head, head
    # every store named: a scope with nothing excluded discloses nothing
    b2 = run(root, "in " + ", ".join(f"thing{i}" for i in range(1, 10)) + ": what did acme do")
    assert len(b2["coverage"]["scope"]) == 9 and b2["coverage"]["stores_excluded"] == []
    assert "WITHIN SCOPE" not in ks.render(b2).splitlines()[0]


def test_absent_class_is_never_searched_in_the_receipt(tmp_path):
    root, q = make_bare_instance(tmp_path)
    b = run(root, "what did Bluepeak ask for")
    for cls in ("graph", "commitments", "meetings", "loops"):
        row = receipt_row(b, cls)
        assert row["present"] is False and row["searched"] is False and row["stores_searched"] == 0, row


# PR #308 review round 10: an index of 0 still accounts for unreadable docs; the receipts ledger is bounded.

def test_unreadable_store_is_seen_with_an_index_of_zero(tmp_path):
    root, q = make_bare_instance(tmp_path)
    (q / ".q-system" / "data").mkdir()
    shutil.copy(INVESTIGATION_MANIFEST, q / ".q-system" / "data" / "knowledge-sources.json")
    s = add_store(q, "case-001-alpha", "scope", "Bluepeak asked here too.")
    only = s / "investigation" / "findings" / "finding-001.md"
    only.chmod(0)
    try:
        b = run(root, "what did Bluepeak ask for")
    finally:
        only.chmod(0o644)
    assert b is not None and any(e["kind"] == "docs_hit" for e in b["entities"])
    row = receipt_row(b, "docs")
    assert "case-001-alpha: 1 of 1 doc file(s) unreadable" in (row["problem"] or ""), row
    assert row["searched"] == "partial" and b["coverage"]["verdict"] != "FULL", b["coverage"]


def test_receipts_ledger_is_bounded(tmp_path, monkeypatch):
    root, q = make_instance(tmp_path)
    monkeypatch.setattr(ks, "RECEIPT_LEDGER_MAX_BYTES", 4000)
    for _ in range(12):
        run(root, "what do we know about Dana Okafor", record=True)
    path = q / "memory" / ".knowledge-supply-receipts.jsonl"
    assert path.stat().st_size <= 4000 * 2, path.stat().st_size   # one row may land before the trim
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert 1 <= len(rows) < 12 and all("sources" in r for r in rows)


# PR #308 review round 11: consumed bigram halves; declared skips disclosed; identical blocks collapse.

def test_suppressed_bigram_half_is_never_a_candidate(tmp_path):
    root, q = make_instance(tmp_path)
    add_store(q, "case-023-shinyhunters", "scope", "ShinyHunters hit the CRM vendor.")
    (q / "output" / "others.md").write_text("The Lapsus Crew was dormant all quarter.\nA different Crew filed the takedown request.\n")
    b = run(root, "what do we know about ShinyHunters Crew")
    names = [e["name"] for e in b["entities"]]
    assert "shinyhunters" in names and "Crew" not in names, names
    assert not any("Lapsus" in i["text"] or "takedown" in i["text"] for i in b["items"]), [i["text"] for i in b["items"]]


def test_declared_skips_are_counted_and_disclosed(tmp_path):
    root, q = make_instance(tmp_path)
    s = add_store(q, "case-001-foo-bar", "scope", "Dana Okafor briefed the Foo Bar victim list.")
    (s / "investigation" / "raw-collections").mkdir()
    (s / "investigation" / "raw-collections" / "dump.md").write_text("Dana Okafor controls the wallet.\n")
    (q / "output" / "big.md").write_text("Dana Okafor pilot is cancelled\n" + "x" * 600_000)
    b = run(root, "what do we know about Dana Okafor")
    row = receipt_row(b, "docs")
    assert row["files_skipped_oversize"] == 1 and row["dirs_skipped"] == 1
    assert row["dirs_skipped_sample"] == ["q-fix/investigations/case-001-foo-bar/investigation/raw-collections"]
    head = ks.render(b).splitlines()[0]
    assert "SKIPPED (declared): 1 file(s) over doc_max_bytes, 1 dir(s) in skip_dirs; the receipt lists them." in head, head
    assert b["coverage"]["verdict"] == "FULL", "a declared exclusion is not a truncation"
    texts = [i["text"] for i in b["items"]]
    assert not any("controls the wallet" in t or "pilot is cancelled" in t for t in texts)
    # tooling dirs stay silent
    (q / "output" / "node_modules").mkdir()
    (q / "output" / "node_modules" / "n.md").write_text("Dana Okafor node\n")
    b2 = run(root, "what do we know about Dana Okafor")
    assert receipt_row(b2, "docs")["dirs_skipped"] == 1


def test_identical_blocks_collapse_into_one_heading(tmp_path):
    root, q = make_instance(tmp_path)
    _graph(q / "memory" / "graph.jsonl", GRAPH_ROWS + [
        {"s": "Priya Raman", "p": "met", "o": "Tomas Lind", "t": "2026-08-20", "project": "v"},
    ])
    b = run(root, "what do we know about Priya Raman and Tomas Lind")
    out = ks.render(b)
    assert "== Priya Raman, Tomas Lind ==" in out, out
    assert "== Tomas Lind ==" not in out
    assert out.count("Priya Raman met Tomas Lind") == 1
    assert [e["name"] for e in b["entities"]] == ["Priya Raman", "Tomas Lind"], "both still resolved"


# ---------------------------------------------------------------- the hook

def run_hook(root: Path, prompt: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env.pop("KNOWLEDGE_INJECT_OFF", None)
    env.update(extra_env or {})
    payload = json.dumps({"prompt": prompt, "session_id": "hook-session", "cwd": str(root)})
    return subprocess.run([sys.executable, str(HOOK)], input=payload, cwd=root, env=env,
                          capture_output=True, text=True, timeout=30)


def test_hook_envelope_and_exit_zero(tmp_path):
    root, _ = make_instance(tmp_path)
    p = run_hook(root, "what do we know about Dana Okafor")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert hso["additionalContext"].startswith("[knowledge-supply] COVERAGE:")
    assert "graph.jsonl:1" in hso["additionalContext"]


def test_hook_kill_switch_and_no_entity_are_silent(tmp_path):
    root, _ = make_instance(tmp_path)
    p = run_hook(root, "what do we know about Dana Okafor", {"KNOWLEDGE_INJECT_OFF": "1"})
    assert p.returncode == 0 and p.stdout == ""
    p = run_hook(root, "what is the weather")
    assert p.returncode == 0 and p.stdout == ""


def test_hook_silent_on_broken_store(tmp_path):
    root, q = make_instance(tmp_path)
    (q / "memory" / "graph.jsonl").unlink()
    (q / "memory" / "graph.jsonl").mkdir()
    p = run_hook(root, "what do we know about Dana Okafor")
    assert p.returncode == 0
    assert p.stdout == "" or json.loads(p.stdout)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
