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
