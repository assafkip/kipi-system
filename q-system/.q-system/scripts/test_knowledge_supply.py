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
        out = [i for i in out if i["entity"] == entity]
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
